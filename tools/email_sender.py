"""
tools/email_sender.py — Envío de correo via SMTP (Gmail)
Soporta Gmail con App Password. Puede enviar emails con asunto, cuerpo y destinatario.
"""
import smtplib
import os
import logging
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("IMAP_USER", "")  # Reusar las mismas credenciales de IMAP
SMTP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
SENDER_NAME = os.getenv("AGENT_NAME", "Jada")


def _send_email_sync(to: str, subject: str, body: str, html: bool = False) -> dict:
    """Enviar un email via SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        return {"error": "IMAP_USER e IMAP_PASSWORD deben estar configurados en .env para enviar emails"}

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"
        msg["To"] = to
        msg["Subject"] = subject

        # Cuerpo del email
        if html:
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg.attach(MIMEText(body, "plain", "utf-8"))

        # Conectar y enviar
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to, msg.as_string())

        logger.info(f"📧 Email enviado a {to}: {subject}")
        return {
            "success": True,
            "to": to,
            "subject": subject,
            "message": f"Email enviado exitosamente a {to}",
        }
    except smtplib.SMTPAuthenticationError:
        return {"error": "Autenticación SMTP fallida. Verifica tu App Password de Gmail."}
    except Exception as e:
        return {"error": f"Error enviando email: {str(e)}"}


async def send_email(to: str, subject: str, body: str, html: bool = False) -> dict:
    """Enviar email (wrapper async)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_email_sync, to, subject, body, html)
