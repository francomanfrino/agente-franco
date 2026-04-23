"""
Google Calendar integration para el Agente de Franco.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]

MONTHS_ES = {
    "January": "enero", "February": "febrero", "March": "marzo",
    "April": "abril", "May": "mayo", "June": "junio",
    "July": "julio", "August": "agosto", "September": "septiembre",
    "October": "octubre", "November": "noviembre", "December": "diciembre",
}
DAYS_ES = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado",
    "Sunday": "domingo",
}


def _get_service():
    """Devuelve el servicio autenticado de Google Calendar."""
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "google_token.json")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    "No se encontró google_credentials.json. "
                    "Ejecutá 'python setup_calendar.py' primero para configurar el acceso."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _format_dt(dt_str: str) -> str:
    """Formatea una fecha ISO a formato legible en español."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        day_name = dt.strftime("%A")
        month_name = dt.strftime("%B")
        day_name_es = DAYS_ES.get(day_name, day_name)
        month_es = MONTHS_ES.get(month_name, month_name)
        return dt.strftime(f"{day_name_es} %d de {month_es} %Y, %H:%M")
    except Exception:
        return dt_str


def list_events(days: int = 7) -> str:
    """Lista los próximos eventos del calendario."""
    try:
        service = _get_service()
    except FileNotFoundError as e:
        return f"⚠️ {e}"

    tz = os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires")
    now = datetime.utcnow()
    end = now + timedelta(days=days)

    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat() + "Z",
            timeMax=end.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
            maxResults=30,
        ).execute()

        events = result.get("items", [])

        if not events:
            return f"📅 No tenés eventos agendados en los próximos {days} días."

        lines = [f"📅 Eventos en los próximos {days} días ({len(events)} en total):\n"]
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date", ""))
            title = ev.get("summary", "Sin título")
            location = ev.get("location", "")
            ev_id = ev["id"]

            start_str = _format_dt(start) if "T" in start else start

            line = f"  • [{ev_id[:10]}] {start_str} — {title}"
            if location:
                line += f"  📍 {location}"
            lines.append(line)

        return "\n".join(lines)

    except HttpError as e:
        return f"Error al leer el calendario: {e}"


def create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    attendees: Optional[List[str]] = None,
    location: str = "",
) -> str:
    """Crea un evento en Google Calendar."""
    try:
        service = _get_service()
    except FileNotFoundError as e:
        return f"⚠️ {e}"

    tz = os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires")

    body = {
        "summary": title,
        "start": {"dateTime": start_datetime, "timeZone": tz},
        "end": {"dateTime": end_datetime, "timeZone": tz},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    try:
        ev = service.events().insert(calendarId="primary", body=body).execute()
        return (
            f"✅ Evento creado exitosamente.\n"
            f"   Título: {title}\n"
            f"   Inicio: {start_datetime}\n"
            f"   ID: {ev['id']}\n"
            f"   Link: {ev.get('htmlLink', 'N/A')}"
        )
    except HttpError as e:
        return f"Error al crear evento: {e}"


def update_event(
    event_id: str,
    title: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Actualiza un evento existente."""
    try:
        service = _get_service()
    except FileNotFoundError as e:
        return f"⚠️ {e}"

    tz = os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires")

    try:
        ev = service.events().get(calendarId="primary", eventId=event_id).execute()

        if title:
            ev["summary"] = title
        if description is not None:
            ev["description"] = description
        if location is not None:
            ev["location"] = location
        if start_datetime:
            ev["start"] = {"dateTime": start_datetime, "timeZone": tz}
        if end_datetime:
            ev["end"] = {"dateTime": end_datetime, "timeZone": tz}

        updated = service.events().update(
            calendarId="primary", eventId=event_id, body=ev
        ).execute()

        return (
            f"✅ Evento actualizado: '{updated.get('summary', 'Sin título')}'\n"
            f"   Link: {updated.get('htmlLink', 'N/A')}"
        )
    except HttpError as e:
        return f"Error al actualizar evento: {e}"


def delete_event(event_id: str) -> str:
    """Elimina un evento del calendario."""
    try:
        service = _get_service()
    except FileNotFoundError as e:
        return f"⚠️ {e}"

    try:
        ev = service.events().get(calendarId="primary", eventId=event_id).execute()
        title = ev.get("summary", "Sin título")
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return f"✅ Evento eliminado: '{title}'"
    except HttpError as e:
        return f"Error al eliminar evento: {e}"


def find_free_slots(
    date: str,
    duration_minutes: int,
    start_hour: int = 9,
    end_hour: int = 19,
) -> str:
    """Busca franjas horarias libres en una fecha dada."""
    try:
        service = _get_service()
    except FileNotFoundError as e:
        return f"⚠️ {e}"

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        tz_offset = "-03:00"  # Argentina
        day_start = date_obj.replace(hour=start_hour, minute=0, second=0)
        day_end = date_obj.replace(hour=end_hour, minute=0, second=0)

        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat() + tz_offset,
            timeMax=day_end.isoformat() + tz_offset,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])

        busy = []
        for ev in events:
            s_str = ev["start"].get("dateTime")
            e_str = ev["end"].get("dateTime")
            if s_str and e_str:
                s = datetime.fromisoformat(s_str).replace(tzinfo=None)
                e = datetime.fromisoformat(e_str).replace(tzinfo=None)
                busy.append((s, e))
        busy.sort()

        free_slots = []
        current = day_start
        for b_start, b_end in busy:
            if current + timedelta(minutes=duration_minutes) <= b_start:
                free_slots.append((current, b_start))
            current = max(current, b_end)
        if current + timedelta(minutes=duration_minutes) <= day_end:
            free_slots.append((current, day_end))

        if not free_slots:
            return f"😔 No hay franjas libres el {date} para {duration_minutes} minutos entre las {start_hour}:00 y las {end_hour}:00."

        lines = [f"🟢 Franjas libres el {date} para {duration_minutes} min:\n"]
        for s, e in free_slots[:8]:
            lines.append(f"   • {s.strftime('%H:%M')} → {e.strftime('%H:%M')}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error buscando horarios libres: {e}"
