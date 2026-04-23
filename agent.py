"""
Agente Personal de Franco
=========================
Asistente conversacional con acceso a Google Calendar, generación de PDFs
y envío de propuestas por email.

Uso:
    python agent.py

Primero configurá el .env y ejecutá setup_calendar.py si querés usar el calendario.
"""

import os
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv

from tools.calendar import list_events, create_event, update_event, delete_event, find_free_slots
from tools.pdf import generate_proposal_pdf
from tools.email import send_email

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    print("❌ Falta la variable ANTHROPIC_API_KEY en el .env")
    sys.exit(1)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

FRANCO_NAME = os.getenv("FRANCO_NAME", "Franco")

SYSTEM_PROMPT = f"""Sos el asistente personal de {FRANCO_NAME}. Tu rol es ser su mano derecha digital: organizás su agenda, redactás propuestas comerciales profesionales y las enviás por email.

**Personalidad:** sos directo, eficiente y amigable. Hablás en español rioplatense (vos/te). Cuando hay algo importante confirmás antes de actuar.

**Capacidades:**
- 📅 Gestionar el calendario: ver, crear, modificar y eliminar eventos de Google Calendar
- 📄 Redactar propuestas comerciales a partir de transcripciones o notas de reunión
- 🖨️ Generar las propuestas en PDF profesional listo para enviar
- 📧 Enviar emails con PDFs adjuntos

**Para propuestas desde transcripciones:**
1. Analizás la transcripción y extraés la información clave
2. Redactás una propuesta estructurada y profesional con estas secciones:
   - Introducción / Contexto
   - Alcance del trabajo / Entregables
   - Inversión / Tarifas
   - Próximos pasos / Timing
3. Llamás a `generate_proposal_pdf` con el contenido ya redactado
4. Ofrecés enviarla por email si {FRANCO_NAME} lo desea

**Formato del contenido para el PDF:**
Usá esta sintaxis en el texto que pasás a `generate_proposal_pdf`:
- `# Título` para secciones principales
- `## Subtítulo` para subsecciones
- `- ítem` para listas
- `**texto**` para negrita

**Sobre el calendario:**
- Cuando {FRANCO_NAME} pide ver su agenda, listás los eventos de los próximos días
- Si necesita el ID de un evento para modificarlo, primero listás los eventos y mostrás los IDs
- Los IDs se muestran entre corchetes en el listado de eventos
- Confirmás siempre antes de eliminar un evento

Fecha y hora actual: {{DATETIME}}
"""

# ── Definición de herramientas ─────────────────────────────────────────────────

TOOLS = [
    {
        "name": "list_events",
        "description": "Lista los próximos eventos del calendario de Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Días hacia adelante para buscar. Por defecto 7.",
                    "default": 7,
                }
            },
        },
    },
    {
        "name": "create_event",
        "description": "Crea un nuevo evento en Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":          {"type": "string",  "description": "Título del evento"},
                "start_datetime": {"type": "string",  "description": "Inicio en ISO 8601, ej: 2024-03-15T10:00:00"},
                "end_datetime":   {"type": "string",  "description": "Fin en ISO 8601"},
                "description":    {"type": "string",  "description": "Descripción (opcional)"},
                "attendees":      {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de emails de invitados (opcional)",
                },
                "location":       {"type": "string",  "description": "Ubicación (opcional)"},
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
                "event_id":       {"type": "string", "description": "ID del evento (visible entre corchetes al listar)"},
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
        "description": "Elimina un evento del calendario usando su ID.",
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
        "description": "Busca franjas horarias libres en una fecha para agendar algo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date":             {"type": "string",  "description": "Fecha en formato YYYY-MM-DD"},
                "duration_minutes": {"type": "integer", "description": "Duración necesaria en minutos"},
                "start_hour":       {"type": "integer", "description": "Inicio del horario laboral (por defecto 9)", "default": 9},
                "end_hour":         {"type": "integer", "description": "Fin del horario laboral (por defecto 19)",   "default": 19},
            },
            "required": ["date", "duration_minutes"],
        },
    },
    {
        "name": "generate_proposal_pdf",
        "description": (
            "Genera una propuesta comercial profesional en PDF. "
            "Primero redactá el contenido completo de la propuesta en el campo 'transcription', "
            "usando la sintaxis de markdown (# secciones, ## subsecciones, - listas, **negrita**)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transcription":   {"type": "string", "description": "Contenido completo y redactado de la propuesta en formato markdown"},
                "client_name":     {"type": "string", "description": "Nombre del cliente"},
                "project_title":   {"type": "string", "description": "Título del proyecto o propuesta"},
                "output_filename": {"type": "string", "description": "Nombre base del archivo PDF (sin extensión)", "default": "propuesta"},
            },
            "required": ["transcription", "client_name", "project_title"],
        },
    },
    {
        "name": "send_email",
        "description": "Envía un email, opcionalmente con un PDF adjunto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to":              {"type": "string", "description": "Email del destinatario"},
                "subject":         {"type": "string", "description": "Asunto del email"},
                "body":            {"type": "string", "description": "Cuerpo del email en texto plano"},
                "attachment_path": {"type": "string", "description": "Ruta completa al PDF a adjuntar (opcional)"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

# ── Dispatcher de herramientas ─────────────────────────────────────────────────

TOOL_MAP = {
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
        return f"Error en parámetros de {name}: {e}"
    except Exception as e:
        return f"Error ejecutando {name}: {e}"

# ── Helpers de UI ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
DIM    = "\033[2m"


def print_banner():
    print(f"\n{BOLD}{CYAN}{'═'*58}{RESET}")
    print(f"{BOLD}{CYAN}   🤖 Agente Personal de {FRANCO_NAME}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*58}{RESET}")
    print(f"{DIM}  Calendario · Propuestas PDF · Email{RESET}")
    print(f"{DIM}  Escribí 'salir' para terminar.{RESET}\n")


def print_tool_call(name: str):
    icons = {
        "list_events":           "📅",
        "create_event":          "📅✏️",
        "update_event":          "📅🔄",
        "delete_event":          "📅🗑️",
        "find_free_slots":       "📅🔍",
        "generate_proposal_pdf": "📄",
        "send_email":            "📧",
    }
    icon = icons.get(name, "🔧")
    print(f"  {YELLOW}{icon} [{name}]...{RESET}", flush=True)

# ── Loop principal ─────────────────────────────────────────────────────────────

def chat():
    messages = []
    print_banner()

    while True:
        try:
            user_input = input(f"{BOLD}{GREEN}{FRANCO_NAME}:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n{CYAN}Asistente:{RESET} ¡Hasta luego, {FRANCO_NAME}! 👋\n")
            break

        if not user_input:
            continue

        if user_input.lower() in ("salir", "exit", "quit", "bye", "chau"):
            print(f"\n{CYAN}Asistente:{RESET} ¡Hasta luego, {FRANCO_NAME}! 👋\n")
            break

        messages.append({"role": "user", "content": user_input})

        system = SYSTEM_PROMPT.replace(
            "{DATETIME}", datetime.now().strftime("%d/%m/%Y %H:%M")
        )

        # ── Agentic loop ───────────────────────────────────────────────────────
        while True:
            print(f"\n{CYAN}Asistente:{RESET} ", end="", flush=True)

            # Streaming para UX más fluida
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=system,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                response = stream.get_final_message()

            print()  # salto de línea tras el stream

            # Guardar respuesta del asistente
            messages.append({"role": "assistant", "content": response.content})

            # Revisar si hay llamadas a herramientas
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason == "end_turn" or not tool_uses:
                break  # respuesta final, salir del loop interno

            # Ejecutar herramientas y recolectar resultados
            tool_results = []
            for tu in tool_uses:
                print_tool_call(tu.name)
                result = run_tool(tu.name, tu.input)
                print(f"  {DIM}{result[:120]}{'…' if len(result) > 120 else ''}{RESET}")
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tu.id,
                    "content":     result,
                })

            messages.append({"role": "user", "content": tool_results})

        print()  # espacio entre turnos


if __name__ == "__main__":
    chat()
