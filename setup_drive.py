"""
Configuracion de Google Drive para el agente WhatsApp de Franco.

Ejecuta este script UNA sola vez para autorizar el acceso de solo lectura a Drive.

Pasos previos (si ya hiciste setup_calendar.py, el archivo google_credentials.json
ya lo tenes, solo ejecuta este script):

1. Asegurate de tener google_credentials.json en esta carpeta.
   Si no lo tenes:
   - Ir a https://console.cloud.google.com/
   - Proyecto existente -> APIs y servicios -> Biblioteca
   - Habilitar "Google Drive API"
   - Credenciales -> OAuth 2.0 -> Aplicacion de escritorio -> Descargar JSON
   - Renombrarlo como google_credentials.json

2. En Google Cloud Console, habilita la "Google Drive API" para el mismo proyecto.

3. Ejecuta: python setup_drive.py
"""

import os
import sys

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def main():
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
    token_path = os.getenv("GOOGLE_DRIVE_TOKEN_PATH", "google_drive_token.json")

    print("\nConfiguracion de Google Drive")
    print("=" * 40)

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.valid:
            print(f"Ya tenes un token valido en '{token_path}'.")
            print("No necesitas hacer nada mas.\n")
            return
        if creds and creds.expired and creds.refresh_token:
            print("El token expiro, renovando...")
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            print(f"Token renovado y guardado en '{token_path}'.\n")
            return

    if not os.path.exists(creds_path):
        print(f"No se encontro '{creds_path}'.")
        print()
        print("Pasos para obtenerlo:")
        print("  1. Ir a https://console.cloud.google.com/")
        print("  2. APIs y servicios -> Biblioteca -> Habilitar 'Google Drive API'")
        print("  3. Credenciales -> OAuth 2.0 -> Aplicacion de escritorio")
        print("  4. Descargar JSON -> renombrarlo como 'google_credentials.json'")
        print("  5. Colocarlo en esta carpeta y volver a ejecutar este script")
        print()
        sys.exit(1)

    print(f"Usando credenciales de: '{creds_path}'")
    print("Se abrira el navegador para que autorices el acceso de lectura a Drive...")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print()
    print(f"Autorizacion exitosa.")
    print(f"Token guardado en: '{token_path}'")
    print()

    file_id = os.getenv("DRIVE_PRICE_LIST_ID", "").strip()
    if not file_id:
        print("Recordatorio: agrega DRIVE_PRICE_LIST_ID en tu .env con el ID")
        print("de tu documento de precios en Drive.")
        print("Lo encontras en la URL del documento:")
        print("  https://docs.google.com/document/d/ESTE_ES_EL_ID/edit")
    else:
        print(f"Lista de precios configurada con ID: {file_id}")
        print("Probando lectura...")
        try:
            from tools.drive import get_price_list
            content = get_price_list()
            preview = content[:200].replace("\n", " ") if content else "(vacio)"
            print(f"Lectura exitosa. Primeros 200 chars: {preview}")
        except Exception as e:
            print(f"Error al leer el archivo: {e}")

    print()
    print("Ya podes iniciar el agente de WhatsApp con: python whatsapp_server.py")
    print()


if __name__ == "__main__":
    main()
