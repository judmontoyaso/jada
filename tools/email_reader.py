"""
tools/email_reader.py — Lectura de correo via IMAP (solo lectura)
Soporta Gmail con App Password. NO puede enviar, borrar ni modificar correos.
"""
import imaplib
import email
import email.message
import email.header
import os
import logging
import asyncio
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")


def _decode_header(raw: str) -> str:
    """Decodificar encabezado de email (puede tener encodings variados)."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _get_body(msg: email.message.Message, max_chars: int = 3000) -> str:
    """Extraer el cuerpo de texto del email."""
    body = ""
    html_body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
                except Exception:
                    continue
            elif content_type == "text/html":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
                except Exception:
                    continue
    else:
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            if content_type == "text/html":
                html_body = payload.decode(charset, errors="replace")
            else:
                body = payload.decode(charset, errors="replace")
        except Exception:
            body = "(no se pudo decodificar el cuerpo)"

    # Si no hay texto plano pero sí HTML, extraer texto del HTML
    if not body and html_body:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_body, "lxml")
            # Eliminar scripts y estilos
            for script in soup(["script", "style"]):
                script.extract()
            # Obtener texto limpio
            text = soup.get_text(separator="\n")
            lines = (line.strip() for line in text.splitlines())
            body = "\n".join(line for line in lines if line)
        except Exception as e:
            logger.warning(f"Error parseando HTML: {e}")
            body = html_body[:max_chars]

    return body[:max_chars].strip()


def _connect() -> imaplib.IMAP4_SSL:
    """Conectar al servidor IMAP."""
    if not IMAP_USER or not IMAP_PASSWORD:
        raise ValueError("IMAP_USER y IMAP_PASSWORD deben estar configurados en .env")

    conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    conn.login(IMAP_USER, IMAP_PASSWORD)
    return conn


def _list_emails_sync(folder: str = "INBOX", limit: int = 10, only_unseen: bool = False) -> dict:
    """Listar los últimos N correos de una carpeta, buscando por fecha reciente."""
    try:
        conn = _connect()
        conn.select(folder, readonly=True)

        if only_unseen:
            # Buscar correos no leídos
            _, data = conn.search(None, "UNSEEN")
            mail_ids = data[0].split()
        else:
            # Buscar correos de los últimos 7 días primero
            since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            _, data = conn.search(None, f"(SINCE {since_date})")
            mail_ids = data[0].split()

            # Si no hay correos recientes, ampliar a 30 días
            if not mail_ids:
                since_date = (datetime.now() - timedelta(days=30)).strftime("%d-%b-%Y")
                _, data = conn.search(None, f"(SINCE {since_date})")
                mail_ids = data[0].split()

            # Si aún no hay nada, traer todos (fallback)
            if not mail_ids:
                _, data = conn.search(None, "ALL")
                mail_ids = data[0].split()

        # Tomar los últimos N (IDs más altos = más recientes en IMAP)
        recent_ids = mail_ids[-limit:] if len(mail_ids) > limit else mail_ids
        recent_ids = list(reversed(recent_ids))  # Más recientes primero

        emails = []
        for mid in recent_ids:
            _, msg_data = conn.fetch(mid, "(RFC822.HEADER FLAGS)")
            if not msg_data or not msg_data[0]:
                continue

            # Extraer headers y flags
            raw_headers = None
            flags = ""
            for item in msg_data:
                if isinstance(item, tuple):
                    raw_headers = item[1]
                elif isinstance(item, bytes):
                    # El formato de flags puede variar, tratamos de encontrarlo
                    flags = item.decode(errors="ignore")

            if not raw_headers:
                continue

            msg = email.message_from_bytes(raw_headers)
            is_read = "\\Seen" in flags

            date_str = msg.get("Date", "")
            try:
                parsed_date = parsedate_to_datetime(date_str).strftime("%Y-%m-%d %H:%M")
            except Exception:
                parsed_date = date_str[:25]

            emails.append({
                "id": mid.decode(),
                "from": _decode_header(msg.get("From", "")),
                "subject": _decode_header(msg.get("Subject", "(sin asunto)")),
                "date": parsed_date,
                "is_read": is_read,
            })

        conn.close()
        conn.logout()

        now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        return {
            "folder": folder,
            "emails": emails,
            "count": len(emails),
            "total_in_period": len(mail_ids),
            "fetched_at": now,
            "only_unseen": only_unseen,
        }
    except Exception as e:
        return {"error": f"Error leyendo correos: {str(e)}"}


def _read_email_sync(email_id: str, folder: str = "INBOX") -> dict:
    """Leer el contenido de un correo específico."""
    try:
        conn = _connect()
        conn.select(folder, readonly=True)

        _, msg_data = conn.fetch(email_id.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            return {"error": f"Correo #{email_id} no encontrado"}

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        date_str = msg.get("Date", "")
        try:
            parsed_date = parsedate_to_datetime(date_str).strftime("%Y-%m-%d %H:%M")
        except Exception:
            parsed_date = date_str[:25]

        result = {
            "id": email_id,
            "from": _decode_header(msg.get("From", "")),
            "to": _decode_header(msg.get("To", "")),
            "subject": _decode_header(msg.get("Subject", "(sin asunto)")),
            "date": parsed_date,
            "body": _get_body(msg),
        }

        conn.close()
        conn.logout()

        return result
    except Exception as e:
        return {"error": f"Error leyendo correo: {str(e)}"}


def _search_emails_sync(query: str, folder: str = "INBOX", limit: int = 10) -> dict:
    """Buscar correos por asunto o remitente."""
    try:
        conn = _connect()
        conn.select(folder, readonly=True)

        # Intentar buscar por asunto primero, luego por remitente
        results_set = set()

        # Buscar por asunto
        _, data = conn.search(None, f'(SUBJECT "{query}")')
        if data[0]:
            results_set.update(data[0].split())

        # Buscar por remitente
        _, data = conn.search(None, f'(FROM "{query}")')
        if data[0]:
            results_set.update(data[0].split())

        # Convertir a lista ordenada (más recientes primero)
        result_ids = sorted(results_set, key=lambda x: int(x), reverse=True)[:limit]

        emails = []
        for mid in result_ids:
            _, msg_data = conn.fetch(mid, "(RFC822.HEADER)")
            if not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            date_str = msg.get("Date", "")
            try:
                parsed_date = parsedate_to_datetime(date_str).strftime("%Y-%m-%d %H:%M")
            except Exception:
                parsed_date = date_str[:25]

            emails.append({
                "id": mid.decode(),
                "from": _decode_header(msg.get("From", "")),
                "subject": _decode_header(msg.get("Subject", "(sin asunto)")),
                "date": parsed_date,
            })

        conn.close()
        conn.logout()

        return {"query": query, "emails": emails, "count": len(emails)}
    except Exception as e:
        return {"error": f"Error buscando correos: {str(e)}"}


# ─── Wrappers async (IMAP es síncrono, lo envolvemos con run_in_executor) ─────

async def list_emails(folder: str = "INBOX", limit: int = 10, only_unseen: bool = False) -> dict:
    """Listar los últimos N correos."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_emails_sync, folder, limit, only_unseen)


async def read_email(email_id: str, folder: str = "INBOX") -> dict:
    """Leer un correo específico por ID."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read_email_sync, email_id, folder)


async def search_emails(query: str, folder: str = "INBOX", limit: int = 10) -> dict:
    """Buscar correos por asunto o remitente."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_emails_sync, query, folder, limit)
