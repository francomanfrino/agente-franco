"""
Business logic for alerts:
  - Overdue invoices with aging buckets
  - Missing invoice sequence gaps
  - Volume anomaly detection
  - Missing recurring supplier invoices
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _today() -> date:
    return date.today()


# ── Overdue invoices ─────────────────────────────────────────────────────────

def clasificar_mora(dias: int) -> str:
    """Returns semáforo color string."""
    if dias <= 0:
        return "verde"
    elif dias <= 30:
        return "amarillo"
    elif dias <= 60:
        return "naranja"
    else:
        return "rojo"


def get_facturas_vencidas(facturas: list[dict]) -> list[dict]:
    """
    Given a list of factura dicts, return those that are overdue
    with aging bucket and color.

    Each returned dict adds:
      dias_mora    — int (days past due)
      bucket       — '0-30' | '31-60' | '61-90' | '+90'
      semaforo     — 'verde' | 'amarillo' | 'naranja' | 'rojo'
    """
    hoy = _today()
    resultado = []

    for f in facturas:
        if f.get("estado") not in ("pendiente", "cobrada_parcial"):
            continue
        vto = _parse_date(f.get("fecha_vencimiento"))
        if not vto:
            continue
        dias = (hoy - vto).days
        if dias < 0:
            continue  # not yet due

        if dias <= 30:
            bucket = "0-30"
        elif dias <= 60:
            bucket = "31-60"
        elif dias <= 90:
            bucket = "61-90"
        else:
            bucket = "+90"

        resultado.append({
            **f,
            "dias_mora": dias,
            "bucket": bucket,
            "semaforo": clasificar_mora(dias),
        })

    return sorted(resultado, key=lambda x: x["dias_mora"], reverse=True)


def calcular_dias_promedio_cobro(conciliaciones: list[dict], facturas: list[dict]) -> dict[str, float]:
    """
    Returns {cuit_cliente: avg_days_to_pay} based on reconciled invoices.
    conciliaciones — list of {factura_id, created_at (date of payment)}
    facturas       — list of {id, cuit_cliente, fecha_emision, fecha_vencimiento}
    """
    fac_by_id = {f["id"]: f for f in facturas}
    days_by_cuit: dict[str, list[float]] = defaultdict(list)

    for c in conciliaciones:
        fac = fac_by_id.get(c.get("factura_id"))
        if not fac:
            continue
        fecha_cobro = _parse_date(c.get("created_at"))
        fecha_emision = _parse_date(fac.get("fecha_emision"))
        if not fecha_cobro or not fecha_emision:
            continue
        days_by_cuit[fac["cuit_cliente"]].append((fecha_cobro - fecha_emision).days)

    return {cuit: round(sum(days) / len(days), 1) for cuit, days in days_by_cuit.items()}


# ── Sequence gap detection ───────────────────────────────────────────────────

def detectar_saltos_numeracion(facturas: list[dict]) -> list[dict]:
    """
    Returns list of gaps in invoice numbering.
    Expects facturas with 'nro_factura' like '0001-00000123' or just '123'.

    Returns: [{punto_venta, desde, hasta, faltantes: int}]
    """
    gaps = []

    # Group by punto_venta
    by_pv: dict[str, list[int]] = defaultdict(list)
    for f in facturas:
        nro = str(f.get("nro_factura", ""))
        match = re.match(r"(\d{4})-(\d{8})", nro)
        if match:
            pv, num = match.group(1), int(match.group(2))
        else:
            digits = re.sub(r"\D", "", nro)
            if not digits:
                continue
            pv = f.get("punto_venta", "0001")
            num = int(digits)
        by_pv[pv].append(num)

    for pv, nums in by_pv.items():
        nums_sorted = sorted(set(nums))
        for i in range(len(nums_sorted) - 1):
            diff = nums_sorted[i + 1] - nums_sorted[i]
            if diff > 1:
                gaps.append({
                    "punto_venta": pv,
                    "desde": nums_sorted[i],
                    "hasta": nums_sorted[i + 1],
                    "faltantes": diff - 1,
                    "descripcion": f"Falta{'n' if diff > 2 else ''} {diff-1} factura{'s' if diff > 2 else ''} entre {pv}-{nums_sorted[i]:08d} y {pv}-{nums_sorted[i+1]:08d}",
                })

    return gaps


# ── Volume anomaly ───────────────────────────────────────────────────────────

def detectar_anomalia_volumen(facturas: list[dict], meses_historico: int = 6) -> dict | None:
    """
    Compare current month's invoice count vs historical average.
    Returns dict with alert info or None if no anomaly.
    """
    from collections import Counter

    hoy = _today()
    mes_actual = hoy.strftime("%Y-%m")

    conteo: Counter = Counter()
    for f in facturas:
        fe = _parse_date(f.get("fecha_emision"))
        if fe:
            conteo[fe.strftime("%Y-%m")] += 1

    actual = conteo.get(mes_actual, 0)

    # Historical: last N months excluding current
    historico = []
    for i in range(1, meses_historico + 1):
        d = hoy.replace(day=1) - timedelta(days=1)
        for _ in range(i - 1):
            d = d.replace(day=1) - timedelta(days=1)
        mes = d.strftime("%Y-%m")
        if mes in conteo:
            historico.append(conteo[mes])

    if len(historico) < 2:
        return None

    promedio = sum(historico) / len(historico)
    if promedio == 0:
        return None

    ratio = actual / promedio
    if ratio < 0.6:
        return {
            "tipo": "volumen_bajo",
            "mes_actual": mes_actual,
            "cantidad_actual": actual,
            "promedio_historico": round(promedio, 1),
            "descripcion": (
                f"Este mes cargaste {actual} factura{'s' if actual != 1 else ''}, "
                f"el promedio de los últimos {len(historico)} meses es {promedio:.0f}"
            ),
        }
    return None


# ── Missing recurring suppliers ──────────────────────────────────────────────

def detectar_proveedores_faltantes(
    proveedores_recurrentes: list[dict],
    facturas_recibidas: list[dict],
) -> list[dict]:
    """
    Check if recurring suppliers are missing invoices for current month.
    Returns list of {proveedor_id, cuit, razon_social}.
    """
    hoy = _today()
    mes_actual = hoy.strftime("%Y-%m")

    cuits_con_factura = set()
    for f in facturas_recibidas:
        fe = _parse_date(f.get("fecha_emision"))
        if fe and fe.strftime("%Y-%m") == mes_actual:
            cuits_con_factura.add(f.get("cuit_proveedor"))

    faltantes = []
    for prov in proveedores_recurrentes:
        if prov.get("es_recurrente") and prov.get("cuit") not in cuits_con_factura:
            faltantes.append({
                "proveedor_id": prov.get("id"),
                "cuit": prov.get("cuit"),
                "razon_social": prov.get("razon_social"),
                "descripcion": f"No se recibió factura de {prov.get('razon_social')} este mes",
            })

    return faltantes
