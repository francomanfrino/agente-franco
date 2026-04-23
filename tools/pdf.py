"""
Generador de propuestas comerciales en PDF para el Agente de Franco.
Usa ReportLab para producir documentos profesionales.
"""

import os
import re
from datetime import datetime
from typing import List, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, Table, TableStyle, KeepTogether,
)

# Paleta de colores
C_PRIMARY  = HexColor("#1a365d")   # Azul oscuro — cabecera
C_ACCENT   = HexColor("#2b6cb0")   # Azul medio — subtítulos
C_LIGHT_BG = HexColor("#ebf8ff")   # Azul muy claro — infobar
C_TEXT     = HexColor("#2d3748")   # Gris oscuro — cuerpo
C_MUTED    = HexColor("#718096")   # Gris medio — footer

MONTHS_ES = {
    "January": "enero", "February": "febrero", "March": "marzo",
    "April": "abril", "May": "mayo", "June": "junio",
    "July": "julio", "August": "agosto", "September": "septiembre",
    "October": "octubre", "November": "noviembre", "December": "diciembre",
}


def _today_es() -> str:
    today = datetime.now().strftime("%d de %B de %Y")
    for en, es in MONTHS_ES.items():
        today = today.replace(en, es)
    return today


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-_ ]", "", name).strip() or "propuesta"


def _build_styles() -> dict:
    base = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "PTitle", parent=base["Title"],
            fontSize=22, textColor=white,
            spaceAfter=4, alignment=TA_CENTER,
            fontName="Helvetica-Bold",
        ),
        "subtitle_header": ParagraphStyle(
            "PSubtitleH", parent=base["Normal"],
            fontSize=13, textColor=white,
            alignment=TA_CENTER, fontName="Helvetica",
        ),
        "h1": ParagraphStyle(
            "PH1", parent=base["Heading1"],
            fontSize=15, textColor=C_PRIMARY,
            spaceBefore=18, spaceAfter=6,
            fontName="Helvetica-Bold",
        ),
        "h2": ParagraphStyle(
            "PH2", parent=base["Heading2"],
            fontSize=12, textColor=C_ACCENT,
            spaceBefore=12, spaceAfter=4,
            fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "PBody", parent=base["Normal"],
            fontSize=11, textColor=C_TEXT,
            spaceAfter=6, leading=17,
            alignment=TA_JUSTIFY, fontName="Helvetica",
        ),
        "bullet": ParagraphStyle(
            "PBullet", parent=base["Normal"],
            fontSize=11, textColor=C_TEXT,
            spaceAfter=4, leading=16,
            leftIndent=14, fontName="Helvetica",
        ),
        "label": ParagraphStyle(
            "PLabel", parent=base["Normal"],
            fontSize=10, textColor=C_ACCENT,
            spaceAfter=2, fontName="Helvetica-Bold",
        ),
        "footer": ParagraphStyle(
            "PFooter", parent=base["Normal"],
            fontSize=9, textColor=C_MUTED,
            alignment=TA_CENTER, fontName="Helvetica",
        ),
        "info": ParagraphStyle(
            "PInfo", parent=base["Normal"],
            fontSize=10, textColor=C_TEXT,
            fontName="Helvetica", leading=15,
        ),
    }


def _parse_content(text: str, styles: dict) -> List:
    """
    Convierte el texto estructurado en flowables de ReportLab.

    Marcadores soportados:
        # Título principal
        ## Sección
        ### Subsección
        - o • Bullet point
        **Texto en negrita**
        Línea en blanco → espacio
    """
    flowables = []

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()

        # Línea en blanco
        if not line:
            flowables.append(Spacer(1, 0.2 * cm))
            continue

        # Título # (h1)
        if re.match(r"^# (.+)$", line):
            content = re.sub(r"^# ", "", line)
            flowables.append(HRFlowable(
                width="100%", thickness=1.5, color=C_ACCENT, spaceAfter=3
            ))
            flowables.append(Paragraph(content, styles["h1"]))

        # Sección ## (h2)
        elif re.match(r"^## (.+)$", line):
            content = re.sub(r"^## ", "", line)
            flowables.append(Paragraph(content, styles["h2"]))

        # Subsección ### (tratada como h2 pequeño)
        elif re.match(r"^### (.+)$", line):
            content = re.sub(r"^### ", "", line)
            flowables.append(Paragraph(f"<b>{content}</b>", styles["body"]))

        # Bullet - o •
        elif re.match(r"^[-•] (.+)$", line):
            content = re.sub(r"^[-•] ", "", line)
            # inline bold
            content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", content)
            flowables.append(Paragraph(f"• {content}", styles["bullet"]))

        # Línea de solo negrita (label estilo)
        elif re.match(r"^\*\*(.+)\*\*$", line):
            content = re.sub(r"\*\*(.+)\*\*", r"\1", line)
            flowables.append(Paragraph(content, styles["label"]))

        # Párrafo normal
        else:
            # inline bold
            safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            flowables.append(Paragraph(safe, styles["body"]))

    return flowables


def generate_proposal_pdf(
    transcription: str,
    client_name: str,
    project_title: str,
    output_filename: str = "propuesta",
) -> str:
    """
    Genera una propuesta comercial en PDF a partir del contenido estructurado.

    Args:
        transcription: Contenido ya redactado/estructurado de la propuesta.
        client_name: Nombre del cliente destinatario.
        project_title: Título del proyecto o propuesta.
        output_filename: Nombre base del archivo (sin extensión).

    Returns:
        Mensaje con la ruta del PDF generado o el error.
    """
    output_dir = os.getenv("PDF_OUTPUT_DIR", "propuestas")
    os.makedirs(output_dir, exist_ok=True)

    safe_name = _safe_filename(output_filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = os.path.join(output_dir, f"{safe_name}_{timestamp}.pdf")

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=2.2 * cm,
        leftMargin=2.2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=project_title,
        author=os.getenv("FRANCO_NAME", "Franco"),
    )

    styles = _build_styles()
    story = []

    # ── CABECERA ────────────────────────────────────────────────────────────────
    header_rows = [
        [Paragraph("PROPUESTA COMERCIAL", styles["title"])],
        [Paragraph(project_title, styles["subtitle_header"])],
    ]
    header_table = Table(header_rows, colWidths=[17.1 * cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_PRIMARY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 22),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 22),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4 * cm))

    # ── BARRA DE INFO ────────────────────────────────────────────────────────────
    franco_name    = os.getenv("FRANCO_NAME", "Franco")
    franco_company = os.getenv("FRANCO_COMPANY", "")
    from_label = franco_name + (f" | {franco_company}" if franco_company else "")

    info_rows = [[
        Paragraph(f"<b>Para:</b>  {client_name}",  styles["info"]),
        Paragraph(f"<b>De:</b>  {from_label}",     styles["info"]),
        Paragraph(f"<b>Fecha:</b>  {_today_es()}", styles["info"]),
    ]]
    info_table = Table(info_rows, colWidths=[5.7 * cm, 7.2 * cm, 4.2 * cm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_LIGHT_BG),
        ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_ACCENT),
        ("LINEBEFORE",    (1, 0), (1, -1), 0.5, C_ACCENT),
        ("LINEBEFORE",    (2, 0), (2, -1), 0.5, C_ACCENT),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.6 * cm))

    # ── CONTENIDO PRINCIPAL ──────────────────────────────────────────────────────
    story.extend(_parse_content(transcription, styles))

    # ── FOOTER ──────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.2 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=C_PRIMARY, spaceAfter=6))

    footer_parts = [franco_name]
    if franco_company:
        footer_parts.append(franco_company)
    email = os.getenv("FRANCO_EMAIL", "")
    phone = os.getenv("FRANCO_PHONE", "")
    if email:
        footer_parts.append(email)
    if phone:
        footer_parts.append(phone)

    story.append(Paragraph("  |  ".join(footer_parts), styles["footer"]))

    # ── BUILD ────────────────────────────────────────────────────────────────────
    doc.build(story)

    abs_path = os.path.abspath(pdf_path)
    return f"✅ PDF generado: {abs_path}"
