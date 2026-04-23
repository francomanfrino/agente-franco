"""
File importer for bank statements and invoices.

Handles Excel (.xlsx, .xls) and CSV with flexible column mapping.
Returns a preview DataFrame + a validated list of dicts ready to insert.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


# ── Column alias dictionaries ────────────────────────────────────────────────

_FECHA_ALIASES = [
    "fecha", "date", "fecha operacion", "fecha_operacion", "fec. operacion",
    "fecha mov", "fecha movimiento",
]
_DESCRIPCION_ALIASES = [
    "descripcion", "concepto", "detalle", "description", "referencia",
    "leyenda", "glosa", "texto",
]
_DEBITO_ALIASES = [
    "debito", "debitos", "cargo", "cargos", "debe", "egreso", "egresos",
    "debit", "withdrawal",
]
_CREDITO_ALIASES = [
    "credito", "creditos", "abono", "abonos", "haber", "ingreso", "ingresos",
    "credit", "deposit",
]
_SALDO_ALIASES = ["saldo", "balance", "saldo final", "saldo parcial"]
_REFERENCIA_ALIASES = [
    "referencia", "nro operacion", "nro. operacion", "numero operacion",
    "voucher", "comprobante", "id transaccion",
]

_NRO_FACTURA_ALIASES = ["nro factura", "numero factura", "numero comprobante", "comprobante", "numero"]
_TIPO_ALIASES = ["tipo", "tipo comprobante", "tipo factura"]
_FECHA_EMISION_ALIASES = ["fecha emision", "fecha_emision", "fecha comprobante", "fecha"]
_FECHA_VTO_ALIASES = ["fecha vencimiento", "vencimiento", "fecha_vencimiento", "vto"]
_CUIT_ALIASES = ["cuit", "cuit cliente", "cuit_cliente", "cuit proveedor", "cuit_proveedor", "nro doc"]
_RAZON_SOCIAL_ALIASES = ["razon social", "razon_social", "cliente", "proveedor", "nombre", "denominacion"]
_NETO_ALIASES = ["neto", "importe neto", "base imponible", "subtotal"]
_IVA_ALIASES = ["iva", "impuesto", "importe iva"]
_PERCEPCIONES_ALIASES = ["percepciones", "percepcion", "perc iibb", "perc iva"]
_TOTAL_ALIASES = ["total", "total factura", "importe total", "monto total", "importe"]


def _normalize(s: str) -> str:
    """Lowercase, strip accents, collapse spaces."""
    s = s.lower().strip()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


def _find_column(df_cols: list[str], aliases: list[str]) -> str | None:
    normalized = {_normalize(c): c for c in df_cols}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


@dataclass
class MappingResult:
    df: pd.DataFrame
    column_map: dict[str, str]        # logical_name → actual_column
    unmapped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    file_type: str = ""               # 'extracto' | 'facturas_emitidas' | 'facturas_recibidas'


# ── Loader ───────────────────────────────────────────────────────────────────

def load_file(path: str | Path, sheet: int | str = 0) -> pd.DataFrame:
    """Load Excel or CSV into a raw DataFrame."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
    elif suffix == ".csv":
        for enc in ("utf-8-sig", "latin-1", "utf-8"):
            try:
                df = pd.read_csv(path, header=None, dtype=str, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"No se pudo leer {path.name} con ninguna codificación.")
    else:
        raise ValueError(f"Formato no soportado: {suffix}. Use .xlsx, .xls o .csv")

    # Detect header row (first row with >= 3 non-null string cells)
    for i, row in df.iterrows():
        non_null = row.dropna().astype(str).str.strip().str.len() > 0
        if non_null.sum() >= 3:
            df.columns = df.iloc[i].astype(str).str.strip()
            df = df.iloc[i + 1:].reset_index(drop=True)
            break

    df = df.dropna(how="all")
    return df


def auto_map_extracto(df: pd.DataFrame) -> MappingResult:
    """Auto-detect columns for a bank statement."""
    cols = df.columns.tolist()
    mapping = {}
    unmapped = []

    for logical, aliases in [
        ("fecha", _FECHA_ALIASES),
        ("descripcion", _DESCRIPCION_ALIASES),
        ("debito", _DEBITO_ALIASES),
        ("credito", _CREDITO_ALIASES),
        ("saldo", _SALDO_ALIASES),
        ("referencia", _REFERENCIA_ALIASES),
    ]:
        found = _find_column(cols, aliases)
        if found:
            mapping[logical] = found
        elif logical in ("fecha", "descripcion"):
            unmapped.append(logical)

    return MappingResult(df=df, column_map=mapping, unmapped=unmapped, file_type="extracto")


def auto_map_facturas(df: pd.DataFrame, tipo: str = "emitidas") -> MappingResult:
    """Auto-detect columns for an invoice file."""
    cols = df.columns.tolist()
    mapping = {}
    unmapped = []

    for logical, aliases in [
        ("nro_factura", _NRO_FACTURA_ALIASES),
        ("tipo", _TIPO_ALIASES),
        ("fecha_emision", _FECHA_EMISION_ALIASES),
        ("fecha_vencimiento", _FECHA_VTO_ALIASES),
        ("cuit", _CUIT_ALIASES),
        ("razon_social", _RAZON_SOCIAL_ALIASES),
        ("neto", _NETO_ALIASES),
        ("iva", _IVA_ALIASES),
        ("percepciones", _PERCEPCIONES_ALIASES),
        ("total", _TOTAL_ALIASES),
    ]:
        found = _find_column(cols, aliases)
        if found:
            mapping[logical] = found
        elif logical in ("nro_factura", "fecha_emision", "cuit", "razon_social", "total"):
            unmapped.append(logical)

    file_type = f"facturas_{tipo}"
    return MappingResult(df=df, column_map=mapping, unmapped=unmapped, file_type=file_type)


# ── Parsers ──────────────────────────────────────────────────────────────────

def _parse_amount(val: Any) -> float:
    """Convert Argentine number strings like '1.234,56' or '1234.56' to float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = str(val).strip().replace(" ", "").replace("\xa0", "")
    if not s:
        return 0.0
    # Remove currency symbols
    s = re.sub(r"[^\d.,\-]", "", s)
    # Detect format: if comma before dot → AR format 1.234,56
    if re.search(r"\d\.\d{3},", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.search(r"\d,\d{3}\.", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(val: Any) -> str | None:
    """Return ISO date string YYYY-MM-DD or None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y",
        "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            from datetime import datetime
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_extracto_rows(result: MappingResult, cuenta_id: int, archivo: str) -> list[dict]:
    """Convert mapped DataFrame rows into dicts ready to insert into movimientos."""
    df = result.df
    cm = result.column_map
    rows = []

    for _, row in df.iterrows():
        fecha = _parse_date(row.get(cm.get("fecha", ""), None))
        if not fecha:
            continue

        descripcion = str(row.get(cm.get("descripcion", ""), "")).strip()
        if not descripcion:
            continue

        debito = _parse_amount(row.get(cm.get("debito", ""), 0))
        credito = _parse_amount(row.get(cm.get("credito", ""), 0))
        saldo = _parse_amount(row.get(cm.get("saldo", ""), None)) if "saldo" in cm else None
        referencia = str(row.get(cm.get("referencia", ""), "")).strip() if "referencia" in cm else None

        rows.append({
            "cuenta_id": cuenta_id,
            "fecha": fecha,
            "descripcion": descripcion,
            "debito": debito,
            "credito": credito,
            "saldo": saldo,
            "referencia": referencia,
            "archivo_origen": archivo,
            "conciliado": 0,
        })

    return rows


def parse_facturas_rows(result: MappingResult, archivo: str) -> list[dict]:
    """Convert mapped DataFrame rows into invoice dicts."""
    df = result.df
    cm = result.column_map
    rows = []
    is_emitida = result.file_type == "facturas_emitidas"

    for _, row in df.iterrows():
        nro = str(row.get(cm.get("nro_factura", ""), "")).strip()
        if not nro or nro.lower() in ("nan", "none", ""):
            continue

        fecha_emision = _parse_date(row.get(cm.get("fecha_emision", ""), None))
        if not fecha_emision:
            continue

        total = _parse_amount(row.get(cm.get("total", ""), 0))
        if total == 0:
            continue

        rec = {
            "nro_factura": nro,
            "tipo": str(row.get(cm.get("tipo", ""), "B")).strip().upper() or "B",
            "fecha_emision": fecha_emision,
            "fecha_vencimiento": _parse_date(row.get(cm.get("fecha_vencimiento", ""), None)),
            "neto": _parse_amount(row.get(cm.get("neto", ""), 0)),
            "iva": _parse_amount(row.get(cm.get("iva", ""), 0)),
            "percepciones": _parse_amount(row.get(cm.get("percepciones", ""), 0)),
            "total": total,
            "estado": "pendiente",
            "monto_cobrado": 0.0,
            "archivo_origen": archivo,
        }

        if is_emitida:
            rec["cuit_cliente"] = re.sub(r"\D", "", str(row.get(cm.get("cuit", ""), ""))).strip()
            rec["razon_social_cliente"] = str(row.get(cm.get("razon_social", ""), "")).strip()
            rec["condicion_pago"] = 30
        else:
            rec["cuit_proveedor"] = re.sub(r"\D", "", str(row.get(cm.get("cuit", ""), ""))).strip()
            rec["razon_social_proveedor"] = str(row.get(cm.get("razon_social", ""), "")).strip()
            rec["retenciones"] = 0.0

        rows.append(rec)

    return rows
