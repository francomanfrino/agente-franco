"""
Export service: generates Excel workbooks and PDF reports.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def export_to_excel(data: dict[str, list[dict]], output_path: str | Path) -> None:
    """
    Export multiple sheets to a single .xlsx file.
    data = {"Sheet Name": [list of row dicts]}
    """
    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, rows in data.items():
            if not rows:
                df = pd.DataFrame()
            else:
                df = pd.DataFrame(rows)
                # Format money columns
                for col in df.columns:
                    if any(k in col.lower() for k in ["total","monto","saldo","neto","iva","debito","credito"]):
                        df[col] = pd.to_numeric(df[col], errors="coerce")
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

            # Auto-width columns
            ws = writer.sheets[sheet_name[:31]]
            for column in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in column), default=0)
                ws.column_dimensions[column[0].column_letter].width = min(max_len + 4, 50)


def export_cxc_to_pdf(facturas_vencidas: list[dict], empresa: dict,
                       output_path: str | Path) -> None:
    """Generate a PDF report of overdue receivables."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        )
    except ImportError:
        raise ImportError("reportlab no está instalado. Ejecutá: pip install reportlab")

    output_path = Path(output_path)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        rightMargin=1*cm, leftMargin=1*cm,
        topMargin=1.5*cm, bottomMargin=1*cm
    )
    styles = getSampleStyleSheet()
    elements = []

    # Header
    razon = empresa.get("razon_social", "") if empresa else ""
    titulo = Paragraph(
        f"<b>CUENTAS POR COBRAR VENCIDAS</b> — {razon}",
        styles["Heading1"]
    )
    fecha_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    subtitulo = Paragraph(f"Generado: {fecha_str}", styles["Normal"])
    elements += [titulo, subtitulo, Spacer(1, 0.5*cm)]

    # Table
    headers = ["Nro Factura", "Cliente", "CUIT", "Fecha Vto", "Total", "Cobrado", "Pendiente", "Días mora", "Estado"]
    COLOR_MAP = {"verde": colors.lightgreen, "amarillo": colors.yellow,
                 "naranja": colors.orange, "rojo": colors.salmon}

    table_data = [headers]
    row_colors = []
    for i, f in enumerate(facturas_vencidas, start=1):
        pendiente = f.get("total", 0) - f.get("monto_cobrado", 0)
        row = [
            f.get("nro_factura", ""),
            f.get("razon_social_cliente", "")[:30],
            f.get("cuit_cliente", ""),
            f.get("fecha_vencimiento", ""),
            f"${f.get('total', 0):,.2f}",
            f"${f.get('monto_cobrado', 0):,.2f}",
            f"${pendiente:,.2f}",
            str(f.get("dias_mora", "")),
            f.get("semaforo", ""),
        ]
        table_data.append(row)
        color = COLOR_MAP.get(f.get("semaforo", ""), colors.white)
        row_colors.append(("BACKGROUND", (0, i), (-1, i), color))

    col_widths = [3.5*cm, 6*cm, 3.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2*cm, 2*cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
    ] + row_colors
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)

    # Totals
    total_pendiente = sum(f.get("total", 0) - f.get("monto_cobrado", 0) for f in facturas_vencidas)
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(
        f"<b>TOTAL PENDIENTE DE COBRO: ${total_pendiente:,.2f}</b>",
        styles["Heading2"]
    ))

    doc.build(elements)


def get_bytes_excel(data: dict[str, list[dict]]) -> bytes:
    """Return Excel file as bytes (for in-memory use)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, rows in data.items():
            df = pd.DataFrame(rows) if rows else pd.DataFrame()
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return buf.getvalue()
