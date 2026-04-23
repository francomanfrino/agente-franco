"""
Google Drive + Sheets — lectura de archivos para el agente de Franco.

Funciones disponibles:
- get_price_list()         Lista de precios desde un Sheet especifico (con cache)
- search_drive_files()     Busca archivos por nombre/contenido en Drive
- read_drive_file()        Lee el contenido de un archivo (Docs, Sheets, PDFs, txt)
- list_drive_folder()      Lista archivos en una carpeta (o la raiz)
"""

import io
import os
import time
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

# Limite de caracteres que se pasa a Claude para no agotar tokens
MAX_FILE_CHARS = 60_000

_cache: tuple[str, float] | None = None
CACHE_TTL_SECONDS = int(os.getenv("DRIVE_CACHE_TTL", "1800"))


# ── Autenticacion ──────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    token_path = os.getenv("GOOGLE_DRIVE_TOKEN_PATH", "google_drive_token.json")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    "No se encontro google_credentials.json. "
                    "Ejecuta setup_drive.py primero."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return creds


def _drive_service():
    return build("drive", "v3", credentials=_get_credentials())


def _sheets_service():
    return build("sheets", "v4", credentials=_get_credentials())


# ── Lista de precios (Sheets con cache) ───────────────────────────────────────

def _sheet_name_by_gid(sheets_service, spreadsheet_id: str, gid: int) -> str:
    meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("sheetId") == gid:
            return props.get("title", "")
    raise ValueError(f"No se encontro ninguna pestana con GID {gid} en el spreadsheet.")


def _fetch_sheet(spreadsheet_id: str, gid: int) -> str:
    sheets = _sheets_service()
    sheet_name = _sheet_name_by_gid(sheets, spreadsheet_id, gid)
    log.info(f"Leyendo pestana '{sheet_name}' (GID {gid})...")

    result = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_name)
        .execute()
    )

    rows = result.get("values", [])
    if not rows:
        return "(la hoja esta vacia)"

    col_count = max(len(row) for row in rows)
    col_widths = [0] * col_count
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    lines = []
    for idx, row in enumerate(rows):
        padded = []
        for i in range(col_count):
            cell = str(row[i]) if i < len(row) else ""
            padded.append(cell.ljust(col_widths[i]))
        lines.append("  ".join(padded).rstrip())
        if idx == 0:
            lines.append("-" * sum(col_widths) + "-" * (col_count - 1) * 2)

    return "\n".join(lines)


def get_price_list() -> str:
    global _cache

    spreadsheet_id = os.getenv("DRIVE_PRICE_LIST_ID", "").strip()
    gid_str        = os.getenv("DRIVE_PRICE_LIST_GID", "").strip()

    if not spreadsheet_id:
        return ""

    gid = int(gid_str) if gid_str.isdigit() else 0
    now = time.time()

    if _cache is not None:
        content, ts = _cache
        if now - ts < CACHE_TTL_SECONDS:
            return content

    try:
        content = _fetch_sheet(spreadsheet_id, gid)
        _cache = (content, now)
        log.info(f"Lista de precios actualizada ({len(content)} chars).")
        return content
    except Exception as e:
        log.warning(f"No se pudo leer la lista de precios: {e}")
        if _cache is not None:
            return _cache[0]
        return ""


def invalidate_cache():
    global _cache
    _cache = None


# ── Busqueda y lectura general de Drive ────────────────────────────────────────

def search_drive_files(query: str, max_results: int = 10) -> str:
    """
    Busca archivos en Google Drive.
    query: texto a buscar en el nombre o contenido del archivo.
    Devuelve una lista formateada con nombre, tipo e ID de cada resultado.
    """
    try:
        drive = _drive_service()

        # Busca en nombre y fullText
        q = f"(name contains '{query}' or fullText contains '{query}') and trashed = false"
        response = (
            drive.files()
            .list(
                q=q,
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, size)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = response.get("files", [])
        if not files:
            return f"No se encontraron archivos que coincidan con '{query}'."

        lines = [f"Archivos encontrados para '{query}' ({len(files)} resultados):\n"]
        for f in files:
            tipo = _mime_label(f.get("mimeType", ""))
            modified = f.get("modifiedTime", "")[:10]
            lines.append(f"  - {f['name']} [{tipo}] | ID: {f['id']} | Modificado: {modified}")

        return "\n".join(lines)

    except HttpError as e:
        return f"Error buscando en Drive: {e}"
    except Exception as e:
        return f"Error: {e}"


def read_drive_file(file_id: str) -> str:
    """
    Lee el contenido de un archivo de Google Drive dado su ID.
    Soporta: Google Docs, Google Sheets, Google Slides, PDFs, texto plano, CSV.
    """
    try:
        drive = _drive_service()

        # Obtener metadata del archivo
        meta = drive.files().get(fileId=file_id, fields="id, name, mimeType").execute()
        name     = meta.get("name", file_id)
        mime     = meta.get("mimeType", "")

        log.info(f"Leyendo '{name}' (tipo: {mime})")

        content = _export_or_download(drive, file_id, name, mime)

        if len(content) > MAX_FILE_CHARS:
            content = content[:MAX_FILE_CHARS]
            content += f"\n\n[... archivo truncado a {MAX_FILE_CHARS} caracteres ...]"

        return f"=== {name} ===\n\n{content}"

    except HttpError as e:
        return f"Error leyendo el archivo: {e}"
    except Exception as e:
        return f"Error: {e}"


def list_drive_folder(folder_id: str = None, max_results: int = 25) -> str:
    """
    Lista los archivos en una carpeta de Drive.
    Si folder_id es None, lista la raiz ('My Drive').
    """
    try:
        drive = _drive_service()

        if folder_id:
            q = f"'{folder_id}' in parents and trashed = false"
        else:
            q = "'root' in parents and trashed = false"

        response = (
            drive.files()
            .list(
                q=q,
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime)",
                orderBy="folder,name",
            )
            .execute()
        )

        files = response.get("files", [])
        if not files:
            return "La carpeta esta vacia o no se encontraron archivos."

        location = f"carpeta {folder_id}" if folder_id else "raiz de Drive"
        lines = [f"Archivos en {location} ({len(files)} elementos):\n"]

        for f in files:
            tipo     = _mime_label(f.get("mimeType", ""))
            modified = f.get("modifiedTime", "")[:10]
            lines.append(f"  - {f['name']} [{tipo}] | ID: {f['id']} | {modified}")

        return "\n".join(lines)

    except HttpError as e:
        return f"Error listando carpeta: {e}"
    except Exception as e:
        return f"Error: {e}"


# ── Helpers internos ───────────────────────────────────────────────────────────

_GOOGLE_EXPORT_TYPES = {
    "application/vnd.google-apps.document":     "text/plain",
    "application/vnd.google-apps.spreadsheet":  "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

_DIRECT_DOWNLOAD_TYPES = {
    "text/plain",
    "text/csv",
    "text/html",
    "application/json",
    "application/xml",
    "text/xml",
}


def _export_or_download(drive, file_id: str, name: str, mime: str) -> str:
    # Google Workspace nativo (Docs, Sheets, Slides)
    if mime in _GOOGLE_EXPORT_TYPES:
        export_mime = _GOOGLE_EXPORT_TYPES[mime]
        request = drive.files().export_media(fileId=file_id, mimeType=export_mime)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")

    # Texto plano y formatos directos
    if mime in _DIRECT_DOWNLOAD_TYPES:
        request = drive.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")

    # PDF: intentar extraer con pdfplumber
    if mime == "application/pdf":
        return _read_pdf_from_drive(drive, file_id, name)

    return (
        f"Tipo de archivo no soportado para lectura directa: {mime}\n"
        f"Podes exportarlo manualmente o convertirlo a Google Docs."
    )


def _read_pdf_from_drive(drive, file_id: str, name: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        return (
            "No se puede leer PDFs: falta la libreria 'pdfplumber'.\n"
            "Instala con: pip install pdfplumber"
        )

    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    buf.seek(0)
    try:
        with pdfplumber.open(buf) as pdf:
            pages_text = []
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(f"--- Pagina {i} ---\n{text}")
            return "\n\n".join(pages_text) if pages_text else "(PDF sin texto extraible)"
    except Exception as e:
        return f"Error extrayendo texto del PDF: {e}"


def _mime_label(mime: str) -> str:
    labels = {
        "application/vnd.google-apps.document":     "Google Doc",
        "application/vnd.google-apps.spreadsheet":  "Google Sheet",
        "application/vnd.google-apps.presentation": "Google Slides",
        "application/vnd.google-apps.folder":       "Carpeta",
        "application/pdf":                           "PDF",
        "text/plain":                                "Texto",
        "text/csv":                                  "CSV",
        "image/jpeg":                                "Imagen JPG",
        "image/png":                                 "Imagen PNG",
    }
    return labels.get(mime, mime.split("/")[-1] if "/" in mime else mime)
