"""
Automatic reconciliation engine: bank movements ↔ issued invoices.

Priority order:
  1. Exact amount + date within tolerance window
  2. Exact amount + CUIT found in description
  3. Exact amount + fuzzy match on company name (threshold 85%)
  4. Partial payment: sum of movements equals invoice total
  5. Retenciones: movement is net of withholdings, gross matches invoice

Returns ConciliacionResult objects; caller decides what to persist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

# Optional: fuzzywuzzy with fallback to difflib
try:
    from rapidfuzz import fuzz as _fuzz
    _fuzzy_ratio = lambda a, b: _fuzz.ratio(a, b)
except ImportError:
    try:
        from fuzzywuzzy import fuzz as _fuzz
        _fuzzy_ratio = lambda a, b: _fuzz.token_set_ratio(a, b)
    except ImportError:
        import difflib
        def _fuzzy_ratio(a: str, b: str) -> float:
            return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


TOLERANCE_DAYS = 5        # default date window around due date
FUZZY_THRESHOLD = 85.0    # minimum similarity score
AMOUNT_TOLERANCE = 0.01   # 1 centavo de diferencia admisible


@dataclass
class MovimientoDTO:
    id: int
    fecha: str           # ISO date
    descripcion: str
    credito: float       # amount received (positive)
    debito: float        # amount paid (positive)
    conciliado: bool = False
    es_transferencia_interna: bool = False


@dataclass
class FacturaDTO:
    id: int
    nro_factura: str
    fecha_emision: str
    fecha_vencimiento: str | None
    cuit: str            # cuit_cliente or cuit_proveedor
    razon_social: str
    total: float
    monto_cobrado: float = 0.0
    estado: str = "pendiente"
    tipo: str = "emitida"  # 'emitida' | 'recibida'

    @property
    def pendiente(self) -> float:
        return round(self.total - self.monto_cobrado, 2)


@dataclass
class ConciliacionResult:
    movimiento_id: int
    factura_id: int
    factura_tipo: str
    monto_aplicado: float
    metodo: str
    confianza: float          # 0.0 – 1.0
    notas: str = ""
    es_probable: bool = False  # True = needs human review


# ── Helper functions ─────────────────────────────────────────────────────────

def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    return None


def _amounts_match(a: float, b: float, tolerance: float = AMOUNT_TOLERANCE) -> bool:
    return abs(a - b) <= tolerance


def _cuit_in_text(cuit: str, text: str) -> bool:
    """Check if CUIT appears in description (with or without dashes)."""
    if not cuit or len(cuit) < 10:
        return False
    clean = re.sub(r"\D", "", cuit)
    # Try both raw and formatted XX-XXXXXXXX-X
    formatted = f"{clean[:2]}-{clean[2:10]}-{clean[10:]}"
    return clean in re.sub(r"\D", "", text) or formatted in text


def _normalize_name(s: str) -> str:
    s = s.upper()
    for a, b in [("Á","A"),("É","E"),("Í","I"),("Ó","O"),("Ú","U"),("Ñ","N")]:
        s = s.replace(a, b)
    # Remove common legal suffixes for better matching
    for suffix in ("S.A.", "SA", "S.R.L.", "SRL", "S.A.S.", "SAS", "S.C.", "SCE"):
        s = s.replace(suffix, "").strip()
    return s.strip()


def _within_date_window(mov_fecha: str, fac_vencimiento: str | None,
                        fac_emision: str, days: int = TOLERANCE_DAYS) -> bool:
    mov_dt = _parse_date(mov_fecha)
    if not mov_dt:
        return True  # can't check, don't discard

    # Use vencimiento if available, else emision + 30 days
    ref_dt = _parse_date(fac_vencimiento) or (_parse_date(fac_emision) + timedelta(days=30))
    if not ref_dt:
        return True

    return abs((mov_dt - ref_dt).days) <= days


# ── Core reconciliation function ─────────────────────────────────────────────

def conciliar(
    movimientos: Sequence[MovimientoDTO],
    facturas: Sequence[FacturaDTO],
    tolerance_days: int = TOLERANCE_DAYS,
    fuzzy_threshold: float = FUZZY_THRESHOLD,
) -> tuple[list[ConciliacionResult], list[int], list[int]]:
    """
    Main reconciliation algorithm.

    Returns:
      matches       — list of ConciliacionResult
      unmatched_mov — IDs of movements that couldn't be matched
      unmatched_fac — IDs of invoices that couldn't be matched
    """
    matches: list[ConciliacionResult] = []
    matched_mov_ids: set[int] = set()
    matched_fac_ids: set[int] = set()

    # Only consider credits (cobros) for emitidas reconciliation
    pending_movs = [m for m in movimientos
                    if not m.conciliado and not m.es_transferencia_interna and m.credito > 0]
    pending_facs = [f for f in facturas
                    if f.estado in ("pendiente", "cobrada_parcial") and f.pendiente > 0]

    # ── Pass 1: Exact amount + date window ──────────────────────────────────
    for mov in pending_movs:
        if mov.id in matched_mov_ids:
            continue
        for fac in pending_facs:
            if fac.id in matched_fac_ids:
                continue
            if (_amounts_match(mov.credito, fac.pendiente) and
                    _within_date_window(mov.fecha, fac.fecha_vencimiento, fac.fecha_emision, tolerance_days)):
                matches.append(ConciliacionResult(
                    movimiento_id=mov.id,
                    factura_id=fac.id,
                    factura_tipo=fac.tipo,
                    monto_aplicado=mov.credito,
                    metodo="automatico_exacto",
                    confianza=1.0,
                    notas=f"Match exacto por importe ${mov.credito:,.2f} y fecha",
                ))
                matched_mov_ids.add(mov.id)
                matched_fac_ids.add(fac.id)
                break

    # ── Pass 2: Amount + CUIT in description ────────────────────────────────
    for mov in pending_movs:
        if mov.id in matched_mov_ids:
            continue
        for fac in pending_facs:
            if fac.id in matched_fac_ids:
                continue
            if (_amounts_match(mov.credito, fac.pendiente) and
                    _cuit_in_text(fac.cuit, mov.descripcion)):
                matches.append(ConciliacionResult(
                    movimiento_id=mov.id,
                    factura_id=fac.id,
                    factura_tipo=fac.tipo,
                    monto_aplicado=mov.credito,
                    metodo="automatico_cuit",
                    confianza=0.95,
                    notas=f"CUIT {fac.cuit} encontrado en descripción",
                ))
                matched_mov_ids.add(mov.id)
                matched_fac_ids.add(fac.id)
                break

    # ── Pass 3: Amount + fuzzy name match ───────────────────────────────────
    for mov in pending_movs:
        if mov.id in matched_mov_ids:
            continue
        best_score = 0.0
        best_fac = None
        for fac in pending_facs:
            if fac.id in matched_fac_ids:
                continue
            if not _amounts_match(mov.credito, fac.pendiente):
                continue
            score = _fuzzy_ratio(
                _normalize_name(fac.razon_social),
                _normalize_name(mov.descripcion)
            )
            if score > best_score:
                best_score = score
                best_fac = fac

        if best_fac and best_score >= fuzzy_threshold:
            is_probable = best_score < 92
            matches.append(ConciliacionResult(
                movimiento_id=mov.id,
                factura_id=best_fac.id,
                factura_tipo=best_fac.tipo,
                monto_aplicado=mov.credito,
                metodo="automatico_fuzzy",
                confianza=round(best_score / 100, 2),
                notas=f"Match por nombre (similitud {best_score:.0f}%): '{best_fac.razon_social}'",
                es_probable=is_probable,
            ))
            matched_mov_ids.add(mov.id)
            matched_fac_ids.add(best_fac.id)

    # ── Pass 4: Partial payments — sum of movements = invoice total ──────────
    remaining_movs = [m for m in pending_movs if m.id not in matched_mov_ids]
    remaining_facs = [f for f in pending_facs if f.id not in matched_fac_ids]

    for fac in remaining_facs:
        best_combo = _find_partial_payment_combo(remaining_movs, fac.pendiente)
        if best_combo:
            for mov in best_combo:
                matches.append(ConciliacionResult(
                    movimiento_id=mov.id,
                    factura_id=fac.id,
                    factura_tipo=fac.tipo,
                    monto_aplicado=mov.credito,
                    metodo="automatico_parcial",
                    confianza=0.80,
                    notas=f"Pago parcial: {len(best_combo)} movimientos suman ${fac.pendiente:,.2f}",
                    es_probable=True,
                ))
                matched_mov_ids.add(mov.id)
            matched_fac_ids.add(fac.id)

    # ── Pass 5: Net amount with retenciones tolerance (up to 35% discount) ──
    for mov in pending_movs:
        if mov.id in matched_mov_ids:
            continue
        for fac in pending_facs:
            if fac.id in matched_fac_ids:
                continue
            if mov.credito < fac.pendiente and mov.credito > fac.pendiente * 0.60:
                retencion_pct = (fac.pendiente - mov.credito) / fac.pendiente * 100
                if retencion_pct <= 35:
                    matches.append(ConciliacionResult(
                        movimiento_id=mov.id,
                        factura_id=fac.id,
                        factura_tipo=fac.tipo,
                        monto_aplicado=mov.credito,
                        metodo="automatico_exacto",
                        confianza=0.70,
                        notas=f"Probable cobro neto de retenciones ({retencion_pct:.1f}% retenido)",
                        es_probable=True,
                    ))
                    matched_mov_ids.add(mov.id)
                    matched_fac_ids.add(fac.id)
                    break

    unmatched_mov = [m.id for m in pending_movs if m.id not in matched_mov_ids]
    unmatched_fac = [f.id for f in pending_facs if f.id not in matched_fac_ids]

    return matches, unmatched_mov, unmatched_fac


def _find_partial_payment_combo(
    movimientos: list[MovimientoDTO],
    target: float,
    max_items: int = 4,
) -> list[MovimientoDTO] | None:
    """
    Find a subset of movements whose credits sum to target.
    Brute-force limited to max_items to avoid exponential blowup.
    """
    from itertools import combinations
    candidates = [m for m in movimientos if m.credito <= target + 0.01]
    for size in range(2, min(max_items + 1, len(candidates) + 1)):
        for combo in combinations(candidates, size):
            total = sum(m.credito for m in combo)
            if _amounts_match(total, target):
                return list(combo)
    return None


# ── Utility: detect internal transfers ───────────────────────────────────────

_TRANSFER_KEYWORDS = [
    "transf entre ctas", "transferencia propia", "entre cuentas",
    "propio", "interbank", "echeq emitido",
]

def detectar_transferencia_interna(descripcion: str, cuit_empresa: str) -> bool:
    desc_lower = descripcion.lower()
    if any(kw in desc_lower for kw in _TRANSFER_KEYWORDS):
        return True
    if cuit_empresa and _cuit_in_text(cuit_empresa, descripcion):
        return True
    return False
