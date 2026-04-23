"""
Configuración de Google Calendar para el Agente Personal de Franco.

Ejecutá este script UNA sola vez para autorizar el acceso al calendario.

Pasos previos:
1. Entrá a https://console.cloud.google.com/
2. Creá un proyecto (o usá uno existente)
3. Activá la API: "APIs y servicios" → "Biblioteca" → buscá "Google Calendar API" → Habilitar
4. Creá credenciales OAuth 2.0:
   "APIs y servicios" → "Credenciales" → "+ Crear credenciales" → "ID de cliente OAuth 2.0"
   → Tipo: "Aplicación de escritorio" → Descargá el JSON
5. Renombrá el archivo descargado como "google_credentials.json" y colocalo en esta carpeta
6. Ejecutá: python setup_calendar.py
"""

import os
import sys

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main():
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "google_token.json")

    print("\n🔧 Configuración de Google Calendar")
    print("=" * 40)

    # Verificar si ya existe un token válido
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.valid:
            print(f"✅ Ya tenés un token válido en '{token_path}'.")
            print("   No necesitás hacer nada más.\n")
            return
        if creds and creds.expired and creds.refresh_token:
            print("🔄 El token expiró, renovando...")
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            print(f"✅ Token renovado y guardado en '{token_path}'.\n")
            return

    # Verificar que exista el archivo de credenciales
    if not os.path.exists(creds_path):
        print(f"❌ No se encontró '{creds_path}'.")
        print()
        print("Pasos para obtenerlo:")
        print("  1. Ir a https://console.cloud.google.com/")
        print("  2. Crear proyecto → Habilitar 'Google Calendar API'")
        print("  3. Credenciales → OAuth 2.0 → Aplicación de escritorio")
        print("  4. Descargar JSON → renombrarlo como 'google_credentials.json'")
        print("  5. Colocarlo en esta carpeta y volver a ejecutar este script")
        print()
        sys.exit(1)

    # Iniciar flujo OAuth
    print(f"📂 Usando credenciales de: '{creds_path}'")
    print("🌐 Se abrirá el navegador para que autorices el acceso al calendario...")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    with open(token_path, "w") as token_file:
        token_file.write(creds.to_json())

    print()
    print(f"✅ ¡Autorización exitosa!")
    print(f"   Token guardado en: '{token_path}'")
    print()
    print("   Ya podés usar el agente con el comando: python agent.py")
    print()


if __name__ == "__main__":
    main()
