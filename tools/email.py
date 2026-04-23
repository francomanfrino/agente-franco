"""
Módulo de envío de email para el Agente de Franco.
Compatible con Gmail (App Password) y cualquier servidor SMTP.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional


def send_email(
    to: str,
    subject: str,
    body: str,
    attachment_path: Optional[str] = None,
) -> str:
    """
    Envía un email con texto plano, opcionalmente con un PDF adjunto.

    Args:
        to: Email del destinatario.
        subject: Asunto del email.
        body: Cuerpo del email (texto plano).
        attachment_path: Ruta local al archivo a adjuntar (opcional).

    Returns:
        Mensaje de confirmación o error.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    franco_name = os.getenv("FRANCO_NAME", "Franco")

    if not smtp_user or not smtp_pass:
        return (
            "⚠️ No están configuradas las credenciales de email.\n"
            "   Completá SMTP_USER y SMTP_PASSWORD en el archivo .env"
        )

    # Validación básica del adjunto
    if attachment_path:
        if not os.path.exists(attachment_path):
            return f"⚠️ No se encontró el archivo adjunto: {attachment_path}"
        if os.path.getsize(attachment_path) > 25 * 1024 * 1024:  # 25 MB
            return "⚠️ El archivo adjunto supera los 25 MB permitidos por Gmail."

    # Construcción del mensaje
    msg = MIMEMultipart()
    msg["From"]    = f"{franco_name} <{smtp_user}>"
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Adjunto opcional
    if attachment_path:
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = os.path.basename(attachment_path)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    # Envío
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to, msg.as_string())

        att_info = f"\n   📎 Adjunto: {os.path.basename(attachment_path)}" if attachment_path else ""
        return (
            f"✅ Email enviado exitosamente.\n"
            f"   Para: {to}\n"
            f"   Asunto: {subject}{att_info}"
        )

    except smtplib.SMTPAuthenticationError:
        return (
            "❌ Error de autenticación SMTP.\n"
            "   Para Gmail, asegurate de usar una App Password (no tu contraseña normal).\n"
            "   Generala en: https://myaccount.google.com/apppasswords"
        )
    except smtplib.SMTPRecipientsRefused:
        return f"❌ El destinatario fue rechazado: {to}"
    except smtplib.SMTPException as e:
        return f"❌ Error SMTP: {e}"
    except OSError as e:
        return f"❌ Error de red al conectar con {smtp_host}:{smtp_port} — {e}"
