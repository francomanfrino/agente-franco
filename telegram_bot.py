"""
Agente Personal de Franco — Bot de Telegram
============================================
Recibe mensajes de Franco por Telegram, los procesa con Claude
y puede leer/analizar archivos del Google Drive de la empresa.

Uso:
    python telegram_bot.py

Requiere:
    TELEGRAM_BOT_TOKEN     — token del bot (de @BotFather)
    TELEGRAM_ALLOWED_USERS — IDs separados por comas (ej: 123456,789012)
    ANTHROPIC_API_KEY
    GOOGLE_DRIVE_TOKEN_PATH / GOOGLE_CREDENTIALS_PATH  (ya configurados)
"""

import asyncio
import base64
import logging
import os
import sys
from datetime import datetime
from io import BytesIO

import anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from tools.calendar import list_events, create_event, update_event, delete_event, find_free_slots
from tools.pdf import generate_proposal_pdf
from tools.email import send_email
from tools.drive import search_drive_files, read_drive_file, list_drive_folder

load_dotenv()

# ── Escritura de tokens desde env vars (para deploy en Railway/servidor) ───────

def _write_token_from_env(env_var: str, file_path: str):
    """Si el archivo no existe pero hay una env var con su contenido, lo escribe."""
    if os.path.exists(file_path):
        return
    content = os.getenv(env_var, "").strip()
    if content:
        with open(file_path, "w") as f:
            f.write(content)
        log.info(f"Token escrito desde variable de entorno: {file_path}")

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuracion ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS_RAW    = os.getenv("TELEGRAM_ALLOWED_USERS", "")
FRANCO_NAME          = os.getenv("FRANCO_NAME", "Franco")

if not ANTHROPIC_API_KEY:
    log.error("Falta ANTHROPIC_API_KEY en el .env")
    sys.exit(1)

if not TELEGRAM_BOT_TOKEN:
    log.error("Falta TELEGRAM_BOT_TOKEN en el .env")
    sys.exit(1)

ALLOWED_USER_IDS: set[int] = set()
if ALLOWED_USERS_RAW:
    for uid in ALLOWED_USERS_RAW.split(","):
        uid = uid.strip()
        if uid.isdigit():
            ALLOWED_USER_IDS.add(int(uid))

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Historial de conversaciones ───────────────────────────────────────────────

# { telegram_user_id: [{"role": ..., "content": ...}, ...] }
conversations: dict[int, list[dict]] = {}
MAX_HISTORY_TURNS = 30

# ── System prompt ──────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    return f"""Sos el asistente personal de {FRANCO_NAME}. Hablás por Telegram. Tu rol es ser su mano derecha digital: analizás documentos y datos de su empresa en Google Drive, organizás su agenda, redactás propuestas y las enviás por email.

**Personalidad:** directo, eficiente, amigable. Español rioplatense (vos/te). Confirmás antes de actuar en cosas importantes.

**Capacidades:**
- 📂 Drive: buscar archivos, leer documentos (Google Docs, Sheets, PDFs), listar carpetas
- 📅 Calendario: ver, crear, modificar y eliminar eventos
- 📄 Propuestas: redactar en PDF a partir de transcripciones o notas
- 📧 Email: enviar emails con PDF adjunto

**Cuando {FRANCO_NAME} pide analizar datos del Drive:**
1. Si no tiene el ID del archivo, usás `search_drive_files` para encontrarlo
2. Luego `read_drive_file` para leer el contenido
3. Analizás lo que te pidieron y respondés con claridad
4. Si hay tablas o números, los presentás en formato limpio y fácil de leer

**Para respuestas en Telegram:** usás texto plano sin markdown complejo. Podés usar **negrita** y _cursiva_ pero nada más. Mensajes claros y directos.

Fecha y hora actual: {datetime.now().strftime("%d/%m/%Y %H:%M")}
"""

# ── Definicion de tools ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_drive_files",
        "description": "Busca archivos en Google Drive de la empresa por nombre o contenido. Usá esto cuando necesitás encontrar un documento específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "Texto a buscar (nombre del archivo o palabras clave del contenido)"},
                "max_results": {"type": "integer", "description": "Máximo de resultados (por defecto 10)", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_drive_file",
        "description": "Lee el contenido completo de un archivo de Drive dado su ID. Soporta Google Docs, Google Sheets, PDFs y archivos de texto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "ID del archivo en Google Drive"},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "list_drive_folder",
        "description": "Lista los archivos en una carpeta de Drive. Si no se especifica folder_id, lista la raíz del Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id":   {"type": "string",  "description": "ID de la carpeta (opcional, si no se pone lista la raíz)"},
                "max_results": {"type": "integer", "description": "Máximo de archivos a listar (por defecto 25)", "default": 25},
            },
        },
    },
    {
        "name": "list_events",
        "description": "Lista los próximos eventos del calendario de Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Días hacia adelante para buscar. Por defecto 7.", "default": 7}
            },
        },
    },
    {
        "name": "create_event",
        "description": "Crea un nuevo evento en Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":          {"type": "string", "description": "Título del evento"},
                "start_datetime": {"type": "string", "description": "Inicio en ISO 8601, ej: 2024-03-15T10:00:00"},
                "end_datetime":   {"type": "string", "description": "Fin en ISO 8601"},
                "description":    {"type": "string", "description": "Descripción (opcional)"},
                "attendees":      {"type": "array",  "items": {"type": "string"}, "description": "Emails de invitados (opcional)"},
                "location":       {"type": "string", "description": "Ubicación (opcional)"},
            },
            "required": ["title", "start_datetime", "end_datetime"],
        },
    },
    {
        "name": "update_event",
        "description": "Modifica un evento existente en Google Calendar usando su ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id":       {"type": "string", "description": "ID del evento"},
                "title":          {"type": "string", "description": "Nuevo título (opcional)"},
                "start_datetime": {"type": "string", "description": "Nueva fecha/hora de inicio (opcional)"},
                "end_datetime":   {"type": "string", "description": "Nueva fecha/hora de fin (opcional)"},
                "description":    {"type": "string", "description": "Nueva descripción (opcional)"},
                "location":       {"type": "string", "description": "Nueva ubicación (opcional)"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Elimina un evento del calendario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID del evento a eliminar"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "find_free_slots",
        "description": "Busca franjas horarias libres en una fecha.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date":             {"type": "string",  "description": "Fecha en YYYY-MM-DD"},
                "duration_minutes": {"type": "integer", "description": "Duración en minutos"},
                "start_hour":       {"type": "integer", "description": "Inicio del horario laboral (por defecto 9)",  "default": 9},
                "end_hour":         {"type": "integer", "description": "Fin del horario laboral (por defecto 19)", "default": 19},
            },
            "required": ["date", "duration_minutes"],
        },
    },
    {
        "name": "generate_proposal_pdf",
        "description": "Genera una propuesta comercial en PDF.",
        "input_schema": {
            "type": "object",
            "properties": {
                "transcription":   {"type": "string", "description": "Contenido completo de la propuesta en markdown"},
                "client_name":     {"type": "string", "description": "Nombre del cliente"},
                "project_title":   {"type": "string", "description": "Título del proyecto"},
                "output_filename": {"type": "string", "description": "Nombre del archivo PDF (sin extensión)", "default": "propuesta"},
            },
            "required": ["transcription", "client_name", "project_title"],
        },
    },
    {
        "name": "send_email",
        "description": "Envía un email, opcionalmente con PDF adjunto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to":              {"type": "string", "description": "Email del destinatario"},
                "subject":         {"type": "string", "description": "Asunto"},
                "body":            {"type": "string", "description": "Cuerpo del email"},
                "attachment_path": {"type": "string", "description": "Ruta al PDF adjunto (opcional)"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

TOOL_MAP = {
    "search_drive_files":    search_drive_files,
    "read_drive_file":       read_drive_file,
    "list_drive_folder":     list_drive_folder,
    "list_events":           list_events,
    "create_event":          create_event,
    "update_event":          update_event,
    "delete_event":          delete_event,
    "find_free_slots":       find_free_slots,
    "generate_proposal_pdf": generate_proposal_pdf,
    "send_email":            send_email,
}


def run_tool(name: str, inputs: dict) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return f"Herramienta desconocida: {name}"
    try:
        return fn(**inputs)
    except TypeError as e:
        return f"Error en parametros de {name}: {e}"
    except Exception as e:
        return f"Error ejecutando {name}: {e}"


# ── Llamada a Claude ───────────────────────────────────────────────────────────

def get_agent_response(user_id: int, user_message: str) -> str:
    history = conversations.setdefault(user_id, [])
    history.append({"role": "user", "content": user_message})

    if len(history) > MAX_HISTORY_TURNS * 2:
        conversations[user_id] = history[-(MAX_HISTORY_TURNS * 2):]
        history = conversations[user_id]

    try:
        while True:
            response = claude_client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=build_system_prompt(),
                tools=TOOLS,
                messages=history,
            )

            history.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason == "end_turn" or not tool_uses:
                reply = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    "No pude generar una respuesta."
                )
                return reply.strip()

            tool_results = []
            for tu in tool_uses:
                log.info(f"Tool: {tu.name} | inputs: {str(tu.input)[:120]}")
                result = run_tool(tu.name, tu.input)
                log.info(f"  → {result[:120]}")
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tu.id,
                    "content":     result,
                })

            history.append({"role": "user", "content": tool_results})

    except anthropic.APIError as e:
        log.error(f"Error de API Claude: {e}")
        return "Hubo un problema con el servicio. Intenta de nuevo en un momento."


# ── Handlers de Telegram ──────────────────────────────────────────────────────

def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # Si no hay whitelist configurada, acepta todos
    return user_id in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("No tenés acceso a este bot.")
        return
    await update.message.reply_text(
        f"Hola {FRANCO_NAME}! Estoy listo.\n\n"
        "Podés preguntarme sobre archivos de Drive, tu calendario, pedirme que redacte propuestas o envíe emails.\n\n"
        "Ejemplos:\n"
        "• \"Buscame el informe de ventas de marzo\"\n"
        "• \"¿Qué tengo en el calendario esta semana?\"\n"
        "• \"Listame los archivos en Drive\""
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    conversations.pop(user_id, None)
    await update.message.reply_text("Historial borrado. Empezamos de cero.")


async def cmd_drive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    result = list_drive_folder()
    await update.message.reply_text(result[:4096])


async def cmd_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Genera y manda el reporte. Uso: /reporte o /reporte 24-04-2026"""
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return

    from datetime import date
    fecha = None
    if context.args:
        try:
            fecha = datetime.strptime(context.args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text("Formato de fecha incorrecto. Usá: /reporte 24-04-2026")
            return
    else:
        fecha = date.today()

    await update.message.reply_text(f"Generando reporte del {fecha.strftime('%d/%m/%Y')}... un momento ⏳")
    await update.message.chat.send_action(ChatAction.TYPING)
    asyncio.create_task(enviar_reporte_diario(context.bot, fecha))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if not _is_allowed(user_id):
        await update.message.reply_text("No tenés acceso a este bot.")
        log.warning(f"Acceso denegado para user_id={user_id}")
        return

    user_message = update.message.text.strip()
    if not user_message:
        return

    log.info(f"[{user_id}] → {user_message[:80]}")

    # Mostrar "escribiendo..." mientras procesa
    await update.message.chat.send_action(ChatAction.TYPING)

    # Correr la llamada bloqueante en un thread separado para no bloquear el event loop
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, get_agent_response, user_id, user_message)

    log.info(f"[{user_id}] ← {reply[:80]}")

    # Telegram tiene un limite de 4096 caracteres por mensaje
    if len(reply) <= 4096:
        await update.message.reply_text(reply)
    else:
        # Dividir en chunks
        for i in range(0, len(reply), 4096):
            await update.message.reply_text(reply[i:i+4096])


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if not _is_allowed(user_id):
        await update.message.reply_text("No tenés acceso a este bot.")
        return

    caption = update.message.caption or "Analizá esta imagen y decime qué ves."
    log.info(f"[{user_id}] foto recibida | caption: {caption[:60]}")

    await update.message.chat.send_action(ChatAction.TYPING)

    # Descargar la foto en mejor resolución disponible
    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    buf = BytesIO()
    await photo_file.download_to_memory(buf)
    image_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    history = conversations.setdefault(user_id, [])

    # Armar el mensaje con imagen para Claude
    image_message = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": caption},
        ],
    }
    history.append(image_message)

    try:
        response = claude_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=build_system_prompt(),
            messages=history,
        )
        reply = next(
            (b.text for b in response.content if hasattr(b, "text")),
            "No pude analizar la imagen."
        ).strip()

        # Guardar en historial como texto para no acumular base64
        history.pop()
        history.append({"role": "user", "content": f"[imagen enviada] {caption}"})
        history.append({"role": "assistant", "content": reply})

    except Exception as e:
        log.error(f"Error analizando imagen: {e}")
        reply = "No pude analizar la imagen. Intenta de nuevo."

    log.info(f"[{user_id}] ← {reply[:80]}")

    if len(reply) <= 4096:
        await update.message.reply_text(reply)
    else:
        for i in range(0, len(reply), 4096):
            await update.message.reply_text(reply[i:i+4096])


# ── Scheduler — hooks del ciclo de vida del bot ───────────────────────────────

async def _on_startup(app: Application) -> None:
    """Arranca el scheduler cuando el event loop ya esta corriendo."""
    scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")
    scheduler.add_job(
        enviar_reporte_diario,
        trigger=CronTrigger(hour=18, minute=0, timezone="America/Argentina/Buenos_Aires"),
        args=[app.bot],
        id="reporte_diario",
        replace_existing=True,
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    log.info("Scheduler activo — reporte diario a las 18:00 (Argentina)")


async def _on_shutdown(app: Application) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown()


# ── Reporte diario automatico ─────────────────────────────────────────────────

async def _send_text(bot: Bot, uid: int, texto: str) -> None:
    """Manda un texto largo a un usuario, partiendolo si supera 4096 chars."""
    try:
        if len(texto) <= 4096:
            await bot.send_message(chat_id=uid, text=texto, parse_mode="Markdown")
        else:
            for i in range(0, len(texto), 4096):
                await bot.send_message(chat_id=uid, text=texto[i:i+4096], parse_mode="Markdown")
    except Exception as e:
        log.error(f"Error enviando mensaje a {uid}: {e}")


async def enviar_reporte_diario(bot: Bot, fecha=None) -> None:
    """Genera el reporte en dos partes y lo manda a todos los usuarios."""
    from tools.mtm_report import generar_reporte_excel
    from tools.sqlite_report import analizar_sistema, formatear_seccion_sistema
    from datetime import date as date_type

    if fecha is None:
        fecha = date_type.today()

    if not ALLOWED_USER_IDS:
        log.warning("No hay usuarios configurados para recibir el reporte.")
        return

    loop = asyncio.get_event_loop()

    # ── Parte 1: Excel (rapido) ────────────────────────────────────────────────
    try:
        texto_excel = await loop.run_in_executor(None, generar_reporte_excel, fecha)
    except Exception as e:
        log.error(f"Error generando reporte Excel: {e}")
        texto_excel = f"⚠️ Error generando reporte: {e}"

    for uid in ALLOWED_USER_IDS:
        await _send_text(bot, uid, texto_excel)

    # ── Parte 2: SQLite ────────────────────────────────────────────────────────
    try:
        datos_sistema = await loop.run_in_executor(None, analizar_sistema, fecha)
        texto_sistema = "\n".join(formatear_seccion_sistema(datos_sistema))
    except Exception as e:
        log.error(f"Error generando datos del sistema: {e}")
        texto_sistema = f"⚠️ Error leyendo sistema de gestión: {e}"

    for uid in ALLOWED_USER_IDS:
        await _send_text(bot, uid, texto_sistema)

    log.info("Reporte completo enviado.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    # Escribir tokens de Google desde env vars si estamos en un servidor
    _write_token_from_env("GOOGLE_DRIVE_TOKEN_JSON",    os.getenv("GOOGLE_DRIVE_TOKEN_PATH", "google_drive_token.json"))
    _write_token_from_env("GOOGLE_CALENDAR_TOKEN_JSON", os.getenv("GOOGLE_TOKEN_PATH", "google_token.json"))
    _write_token_from_env("GOOGLE_CREDENTIALS_JSON",    os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json"))

    log.info(f"Iniciando bot de Telegram para {FRANCO_NAME}...")

    if ALLOWED_USER_IDS:
        log.info(f"Usuarios permitidos: {ALLOWED_USER_IDS}")
    else:
        log.warning("TELEGRAM_ALLOWED_USERS no configurado — el bot acepta mensajes de cualquier usuario.")
        log.warning("Agregá tu Telegram user ID en el .env para mayor seguridad.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("drive", cmd_drive))
    app.add_handler(CommandHandler("reporte", cmd_reporte))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot corriendo en modo polling. Ctrl+C para detener.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
