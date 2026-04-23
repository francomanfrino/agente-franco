"""
Agente WhatsApp de Franco
=========================
Servidor webhook que recibe mensajes de WhatsApp via Twilio
y responde como un asistente humano usando Claude como cerebro.

Funciones:
- Responde consultas de clientes automaticamente
- Detecta cierres de venta (pedido confirmado + direccion)
- Guarda contactos y ventas en archivo (persiste aunque se reinicie)
- A las 23:37 genera un PDF con grafico y lo manda por WhatsApp a Franco
"""

import os
import sys
import json
import logging
from datetime import datetime, date
from collections import defaultdict

import anthropic
from flask import Flask, request, send_file
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from tools.drive import get_price_list
from tools.pedidos import crear_pedido

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuracion ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
TWILIO_ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")
FRANCO_WHATSAPP      = "whatsapp:+5492235185224"

FRANCO_NAME     = os.getenv("FRANCO_NAME", "Franco")
FRANCO_COMPANY  = os.getenv("FRANCO_COMPANY", "la empresa")
FRANCO_CALENDAR = os.getenv("FRANCO_CALENDAR_LINK", "")
ASSISTANT_NAME  = os.getenv("ASSISTANT_NAME", "Sol")
PUBLIC_URL      = os.getenv("PUBLIC_URL", "").rstrip("/")

if not ANTHROPIC_API_KEY:
    log.error("Falta ANTHROPIC_API_KEY en el .env")
    sys.exit(1)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

os.makedirs("reportes", exist_ok=True)

# ── Persistencia de datos diarios ──────────────────────────────────────────────

def _data_file(day: date = None) -> str:
    d = day or date.today()
    return os.path.join("reportes", f"data_{d.strftime('%Y%m%d')}.json")


def load_daily_data():
    """Carga los datos del dia desde el archivo JSON."""
    global daily_contacts, daily_sales, _current_day
    _current_day = date.today()
    path = _data_file()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        daily_contacts = set(data.get("contacts", []))
        daily_sales    = data.get("sales", [])
        log.info(f"Datos cargados: {len(daily_contacts)} contactos, {len(daily_sales)} ventas.")
    else:
        daily_contacts = set()
        daily_sales    = []
        log.info("Nuevo dia, datos en cero.")


def save_daily_data():
    """Guarda los datos del dia en el archivo JSON."""
    path = _data_file()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "date":     date.today().isoformat(),
            "contacts": list(daily_contacts),
            "sales":    daily_sales,
        }, f, ensure_ascii=False, indent=2)


def _reset_if_new_day():
    global daily_contacts, daily_sales, _current_day
    today = date.today()
    if today != _current_day:
        load_daily_data()


# Estado global
daily_contacts: set[str] = set()
daily_sales:    list[dict] = []
_current_day:   date = date.today()
conversations:  dict[str, list[dict]] = defaultdict(list)
MAX_HISTORY_TURNS = 20

# ── System prompt ──────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    price_list = get_price_list()

    if price_list:
        price_section = f"""
LISTA DE PRECIOS ACTUAL:
------------------------
{price_list}
------------------------
Cuando un cliente pregunte por precios, usas esta informacion. Si algo no esta en la lista, dices que necesitas consultarlo con {FRANCO_NAME} y que te va a responder a la brevedad.
"""
    else:
        price_section = f"No tenes la lista de precios disponible. Si preguntan por precios, decis que lo consultas con {FRANCO_NAME}."

    calendar_section = (
        f"Si el cliente quiere coordinar una reunion o llamada, le compartes este link: {FRANCO_CALENDAR}"
        if FRANCO_CALENDAR
        else f"Si el cliente quiere coordinar una reunion o llamada, le dices que {FRANCO_NAME} los va a contactar para acordar un horario."
    )

    return f"""Sos {ASSISTANT_NAME}, asistente de {FRANCO_NAME} de {FRANCO_COMPANY}. Tu trabajo es atender a las personas que escriben por WhatsApp, entender que necesitan y ayudarlas.

COMO ESCRIBIS:
- Escribis exactamente como lo hace un humano por WhatsApp. Mensajes cortos, naturales, sin formato, sin listas con guiones, sin negritas. Una o dos oraciones por respuesta como maximo, salvo que el cliente necesite mas informacion.
- No usas signos de exclamacion al principio de las frases.
- No repetis el nombre del cliente en cada mensaje, eso suena robotico.
- Si el cliente escribe con mayusculas, errores o abreviaturas, no lo corrijas, respondele en el mismo tono informal.
- Nunca empezas el mensaje con "Claro que si", "Por supuesto", "Entendido" ni frases de call center.
- Siempre terminas el mensaje con un emoticon que pegue con el contexto. Uno solo, al final.

COMO MANEJÁS LAS CONSULTAS:
- Cuando alguien escribe por primera vez, te presentas brevemente y preguntas en que podes ayudar.
- Escuchas lo que necesitan, hacés las preguntas necesarias para entender bien la situacion.
- Cuando preguntan por precios, los das directamente si estan en la lista. No digas "voy a consultar" si ya tenes la informacion.
- Si algo no lo sabes o no esta en la lista, decis que lo consultas con {FRANCO_NAME} y que le responde personalmente.
- {calendar_section}

ZONAS Y DISTRIBUIDORES:
- Si el cliente es de San Juan o pide envio a San Juan, le decis que ahi tienen distribuidor propio y que lo pones en contacto con el para que lo atiendan directamente. No tomes el pedido vos, derive siempre al distribuidor de San Juan.
- Para el resto del pais, se atiende normalmente desde {FRANCO_COMPANY}.

{price_section}

CUANDO EL CLIENTE CONFIRMA UN PEDIDO:
- Una vez que el cliente confirmó qué quiere comprar (productos y cantidades), usás la herramienta `crear_pedido` para registrarlo en el sistema.
- Solo creás el pedido cuando el cliente lo confirmó explícitamente — no ante una consulta de precios.
- Después de crear el pedido, le confirmás al cliente el número de pedido y los próximos pasos (ej: coordinar entrega, pago).
- Si la herramienta falla, le decís que anotaste el pedido y que {FRANCO_NAME} lo va a confirmar personalmente.

SI TE PREGUNTAN SI SOS UN BOT:
Dices que sos la asistente de {FRANCO_NAME} y que el revisa todas las conversaciones. No confirmes ni niegues ser IA.

SI HAY UN PROBLEMA O UN CLIENTE ENOJADO:
Dices que le avisas a {FRANCO_NAME} ahora mismo para que lo atienda el personalmente.

Si el cliente escribe en otro idioma, respondele en ese idioma.

Fecha de hoy: {datetime.now().strftime("%d/%m/%Y")}
"""


# ── Deteccion de cierre de venta ───────────────────────────────────────────────

SALE_DETECTION_PROMPT = """Analizas conversaciones de WhatsApp de una empresa de alimentos y determinas si se cerro una venta.

Una venta esta CERRADA cuando el cliente:
1. Confirmo que quiere hacer un pedido (no solo pregunto precios)
2. Proporciono una direccion de entrega

Responde SOLO con un JSON sin markdown:
{"sale_closed": true/false, "products": "resumen breve de lo que pidio o vacio", "address": "la direccion o vacio", "client_name": "nombre si lo menciono o vacio"}"""


def detect_sale(phone_number: str, history: list[dict]) -> dict | None:
    if len(history) < 4:
        return None

    recent = history[-10:]
    conversation_text = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Asistente'}: {m['content']}"
        for m in recent
    )

    try:
        response = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=SALE_DETECTION_PROMPT,
            messages=[{"role": "user", "content": conversation_text}],
        )
        data = json.loads(response.content[0].text.strip())
        if data.get("sale_closed") and data.get("address"):
            return data
        return None
    except Exception:
        return None


# ── Generacion del PDF con grafico ─────────────────────────────────────────────

def generate_daily_report_pdf() -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.graphics.shapes import Drawing, Rect, String, Line
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics import renderPDF

    today_str = date.today().strftime("%d/%m/%Y")
    filename  = f"resumen_{date.today().strftime('%Y%m%d')}.pdf"
    filepath  = os.path.join("reportes", filename)

    C_PRIMARY = HexColor("#1a365d")
    C_ACCENT  = HexColor("#2b6cb0")
    C_TEXT    = HexColor("#2d3748")
    C_LIGHT   = HexColor("#ebf8ff")
    C_GREEN   = HexColor("#276749")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", fontSize=18, textColor=C_PRIMARY,
                                  alignment=TA_CENTER, fontName="Helvetica-Bold", spaceAfter=6)
    sub_style   = ParagraphStyle("sub", fontSize=12, textColor=C_ACCENT,
                                  fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6)
    body_style  = ParagraphStyle("body", fontSize=10, textColor=C_TEXT,
                                  fontName="Helvetica", leading=14)
    footer_style = ParagraphStyle("footer", fontSize=8, textColor=HexColor("#718096"),
                                   alignment=TA_CENTER)

    doc = SimpleDocTemplate(filepath, pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm,
                             topMargin=2*cm, bottomMargin=2*cm)
    story = []

    # Encabezado
    story.append(Paragraph(FRANCO_COMPANY, title_style))
    story.append(Paragraph(f"Resumen de actividad — {today_str}", body_style))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY))
    story.append(Spacer(1, 0.4*cm))

    # Metricas
    n_contacts = len(daily_contacts)
    n_sales    = len(daily_sales)
    conversion = f"{int(n_sales/n_contacts*100)}%" if n_contacts > 0 else "—"

    story.append(Paragraph("Resumen del dia", sub_style))
    metrics = [
        ["Contactos recibidos", str(n_contacts)],
        ["Ventas cerradas",     str(n_sales)],
        ["Tasa de conversion",  conversion],
    ]
    t = Table(metrics, colWidths=[10*cm, 5*cm])
    t.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",  (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_LIGHT, white]),
        ("GRID",      (0, 0), (-1, -1), 0.5, HexColor("#cbd5e0")),
        ("PADDING",   (0, 0), (-1, -1), 7),
        ("FONTNAME",  (1, 0), (1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # Grafico de barras
    story.append(Paragraph("Grafico del dia", sub_style))

    drawing = Drawing(400, 160)
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 20
    chart.width  = 300
    chart.height = 120
    chart.data   = [[max(n_contacts, 1), max(n_sales, 0)]]
    chart.categoryAxis.categoryNames = ["Contactos", "Ventas cerradas"]
    chart.bars[0].fillColor = C_ACCENT
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(n_contacts + 1, 2)
    chart.valueAxis.valueStep = 1
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 9
    chart.valueAxis.labels.fontName    = "Helvetica"
    chart.valueAxis.labels.fontSize    = 9
    drawing.add(chart)
    story.append(drawing)
    story.append(Spacer(1, 0.5*cm))

    # Detalle de ventas
    story.append(Paragraph("Detalle de ventas cerradas", sub_style))

    if daily_sales:
        rows = [["Hora", "Numero", "Nombre", "Productos", "Direccion"]]
        for sale in daily_sales:
            rows.append([
                sale.get("time", ""),
                sale.get("phone", "").replace("whatsapp:+", ""),
                sale.get("client_name", "-"),
                sale.get("products", "-"),
                sale.get("address", "-"),
            ])
        t2 = Table(rows, colWidths=[1.8*cm, 3.2*cm, 3*cm, 4*cm, 4*cm])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("TEXTCOLOR",  (0, 0), (-1, 0), white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_LIGHT]),
            ("GRID",       (0, 0), (-1, -1), 0.5, HexColor("#cbd5e0")),
            ("PADDING",    (0, 0), (-1, -1), 5),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t2)
    else:
        story.append(Paragraph("No se registraron ventas cerradas hoy.", body_style))

    story.append(Spacer(1, 0.8*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cbd5e0")))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"Generado automaticamente por {ASSISTANT_NAME} a las {datetime.now().strftime('%H:%M')}",
        footer_style
    ))

    doc.build(story)
    log.info(f"PDF generado: {filepath}")
    return filepath, filename


# ── Envio del resumen diario ───────────────────────────────────────────────────

def send_daily_report():
    _reset_if_new_day()
    today_str  = date.today().strftime("%d/%m/%Y")
    n_contacts = len(daily_contacts)
    n_sales    = len(daily_sales)
    conversion = f"{int(n_sales/n_contacts*100)}%" if n_contacts > 0 else "0%"

    log.info("Generando resumen diario...")

    texto = (
        f"Resumen {today_str}\n"
        f"Contactos: {n_contacts}\n"
        f"Ventas cerradas: {n_sales}\n"
        f"Conversion: {conversion}"
    )

    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=FRANCO_WHATSAPP,
            body=texto,
        )
        log.info("Texto del resumen enviado.")

        if PUBLIC_URL:
            filepath, filename = generate_daily_report_pdf()
            media_url = f"{PUBLIC_URL}/reportes/{filename}"
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=FRANCO_WHATSAPP,
                body="Reporte completo del dia:",
                media_url=[media_url],
            )
            log.info(f"PDF enviado: {media_url}")
        else:
            log.warning("PUBLIC_URL no configurada, no se manda el PDF.")

        log.info("Resumen diario enviado a Franco.")

    except Exception as e:
        log.error(f"Error enviando resumen: {e}")


# ── Definición de tools para Claude ───────────────────────────────────────────

CLAUDE_TOOLS = [
    {
        "name": "crear_pedido",
        "description": (
            "Crea un pedido en el sistema cuando el cliente confirmó qué quiere comprar. "
            "Usá esta herramienta solo cuando el cliente haya confirmado explícitamente que quiere hacer el pedido "
            "y hayas obtenido los productos y cantidades. "
            "El teléfono del cliente se provee automáticamente, no se lo pidas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Lista de productos del pedido.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "producto_id": {"type": "integer", "description": "ID del producto según la lista de precios."},
                            "cantidad":    {"type": "number",  "description": "Cantidad pedida (mayor que 0)."},
                            "descuento_porcentaje": {"type": "number", "description": "Descuento en porcentaje, por defecto 0."},
                            "paletizado":  {"type": "boolean", "description": "Si va paletizado, por defecto false."},
                        },
                        "required": ["producto_id", "cantidad"],
                    },
                },
                "forma_pago": {
                    "type": "string",
                    "description": "Forma de pago acordada con el cliente.",
                    "enum": ["EFECTIVO EN OFICINA", "TRANSFERENCIA", "EFECTIVO A RETIRAR", "DEPÓSITO CUENTA TERCEROS", "ECHEQ"],
                },
                "fecha_pago": {
                    "type": "string",
                    "description": "Fecha de pago en formato YYYY-MM-DD (opcional).",
                },
                "tipo_pedido": {
                    "type": "string",
                    "description": "Tipo de pedido, ej: 'Entrega directa' (opcional).",
                },
            },
            "required": ["items"],
        },
    }
]


# ── Llamada a Claude ───────────────────────────────────────────────────────────

def get_response(phone_number: str, user_message: str) -> str:
    _reset_if_new_day()

    is_new_contact = phone_number not in daily_contacts
    daily_contacts.add(phone_number)
    if is_new_contact:
        save_daily_data()

    history = conversations[phone_number]
    history.append({"role": "user", "content": user_message})

    if len(history) > MAX_HISTORY_TURNS * 2:
        conversations[phone_number] = history[-(MAX_HISTORY_TURNS * 2):]
        history = conversations[phone_number]

    try:
        # Loop de tool use: Claude puede pedir crear un pedido durante la conversación
        while True:
            response = claude_client.messages.create(
                model="claude-opus-4-6",
                max_tokens=400,
                system=build_system_prompt(),
                messages=history,
                tools=CLAUDE_TOOLS,
            )

            # Si Claude quiere usar una herramienta
            if response.stop_reason == "tool_use":
                # Guardamos el bloque de respuesta de Claude (puede tener texto + tool_use)
                history.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    if block.name == "crear_pedido":
                        args = block.input
                        # El teléfono siempre viene del número de WhatsApp del cliente
                        whatsapp_phone = phone_number.replace("whatsapp:", "")
                        result = crear_pedido(
                            telefono=whatsapp_phone,
                            items=args["items"],
                            forma_pago=args.get("forma_pago"),
                            fecha_pago=args.get("fecha_pago"),
                            tipo_pedido=args.get("tipo_pedido"),
                        )
                        log.info(f"Tool crear_pedido → {result}")

                        # Si se creó el pedido, lo registramos en las ventas del día
                        if result["ok"]:
                            already_sold = any(s["phone"] == phone_number for s in daily_sales)
                            if not already_sold:
                                daily_sales.append({
                                    "phone":       phone_number,
                                    "time":        datetime.now().strftime("%H:%M"),
                                    "products":    ", ".join(f"ID {i['producto_id']} x{i['cantidad']}" for i in args["items"]),
                                    "address":     "",
                                    "client_name": "",
                                    "pedido_id":   result.get("pedido_id"),
                                })
                                save_daily_data()

                        tool_results.append({
                            "type":        "tool_result",
                            "tool_use_id": block.id,
                            "content":     result["mensaje"],
                        })

                # Devolvemos el resultado al modelo para que formule la respuesta final
                history.append({"role": "user", "content": tool_results})
                continue  # Volvemos a llamar a Claude con el resultado del tool

            # Respuesta de texto final
            reply = next(
                (block.text for block in response.content if hasattr(block, "text")),
                f"Disculpa, no pude procesar tu mensaje. {FRANCO_NAME} te va a contactar a la brevedad."
            ).strip()
            history.append({"role": "assistant", "content": reply})
            return reply

    except anthropic.APIError as e:
        log.error(f"Error de API de Claude: {e}")
        return f"Disculpa, tuve un problema tecnico. {FRANCO_NAME} se va a poner en contacto con vos a la brevedad."


# ── Flask app ──────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.form.get("Body", "").strip()
    from_number  = request.form.get("From", "")

    if not incoming_msg or not from_number:
        return str(MessagingResponse()), 200

    log.info(f"[{from_number}] recibido: {incoming_msg[:80]}")
    reply = get_response(from_number, incoming_msg)
    log.info(f"[{from_number}] enviado: {reply[:80]}")

    resp = MessagingResponse()
    resp.message(reply)
    return str(resp), 200


@app.route("/reportes/<filename>", methods=["GET"])
def serve_report(filename: str):
    path = os.path.join("reportes", filename)
    if not os.path.exists(path):
        return {"error": "not found"}, 404
    return send_file(path, mimetype="application/pdf")


@app.route("/health", methods=["GET"])
def health():
    return {
        "status":        "ok",
        "assistant":     ASSISTANT_NAME,
        "contacts_hoy":  len(daily_contacts),
        "ventas_hoy":    len(daily_sales),
        "public_url":    PUBLIC_URL or "no configurada",
    }, 200


@app.route("/resumen", methods=["POST"])
def resumen_manual():
    send_daily_report()
    return {"status": "enviado"}, 200


@app.route("/conversations", methods=["GET"])
def list_conversations():
    summary = {}
    for number, history in conversations.items():
        summary[number] = {
            "messages":      len(history),
            "last":          history[-1]["content"][:60] if history else "",
            "venta_cerrada": any(s["phone"] == number for s in daily_sales),
        }
    return summary, 200


@app.route("/refresh-prices", methods=["POST"])
def refresh_prices():
    from tools.drive import invalidate_cache
    invalidate_cache()
    content = get_price_list()
    return {"status": "ok", "chars": len(content)}, 200


# ── Scheduler ─────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
scheduler.add_job(send_daily_report, "cron", hour=23, minute=37)

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("WHATSAPP_PORT", 5001))

    load_daily_data()

    log.info("Cargando lista de precios desde Drive...")
    prices = get_price_list()
    if prices:
        log.info(f"Lista de precios cargada ({len(prices)} chars).")
    else:
        log.warning("Lista de precios no disponible.")

    if not PUBLIC_URL:
        log.warning("PUBLIC_URL no configurada — el PDF no se va a adjuntar.")

    scheduler.start()
    log.info("Scheduler iniciado — resumen diario a las 23:37 (Argentina)")
    log.info(f"Asistente: {ASSISTANT_NAME} | Agente de: {FRANCO_NAME}")
    log.info(f"Webhook:        POST http://localhost:{port}/webhook")
    log.info(f"Resumen manual: POST http://localhost:{port}/resumen")

    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    finally:
        scheduler.shutdown()
