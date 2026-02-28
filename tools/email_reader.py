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
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:
            body = "(no se pudo decodificar el cuerpo)"

    return body[:max_chars].strip()


def _connect() -> imaplib.IMAP4_SSL:
    """Conectar al servidor IMAP."""
    if not IMAP_USER or not IMAP_PASSWORD:
        raise ValueError("IMAP_USER y IMAP_PASSWORD deben estar configurados en .env")

    conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    conn.login(IMAP_USER, IMAP_PASSWORD)
    return conn


import json

SEEN_EMAILS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seen_emails.json")

def _load_seen_emails() -> set:
    """Cargar los IDs de correos ya notificados."""
    if not os.path.exists(SEEN_EMAILS_FILE):
        return set()
    try:
        with open(SEEN_EMAILS_FILE, "r") as f:
            return set(json.load(f))
    except Exception as e:
        logger.error(f"Error leyendo seen_emails.json: {e}")
        return set()

def _save_seen_emails(seen: set) -> None:
    """Guardar los IDs de correos ya notificados."""
    try:
        # Mantener solo los últimos 500 para que no crezca infinitamente
        seen_list = list(seen)[-500:]
        with open(SEEN_EMAILS_FILE, "w") as f:
            json.dump(seen_list, f)
    except Exception as e:
        logger.error(f"Error guardando seen_emails.json: {e}")

def _list_emails_sync(folder: str = "INBOX", limit: int = 10, only_new: bool = False) -> dict:
    """Listar los últimos N correos de una carpeta, buscando por fecha reciente."""
    try:
        conn = _connect()
        conn.select(folder, readonly=True)

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

        seen_emails = _load_seen_emails() if only_new else set()

        # Tomar los últimos N (IDs más altos = más recientes en IMAP) ANTES de filtrar
        recent_ids = mail_ids[-limit:] if len(mail_ids) > limit else mail_ids
        recent_ids = list(reversed(recent_ids))  # Más recientes primero

        # Ahora filtramos los que ya hemos visto de ese lote más reciente
        if only_new:
            recent_ids = [mid for mid in recent_ids if mid.decode() not in seen_emails]

        emails = []
        new_seen_emails = set(seen_emails)

        for mid in recent_ids:
            mid_str = mid.decode()
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
                "id": mid_str,
                "from": _decode_header(msg.get("From", "")),
                "subject": _decode_header(msg.get("Subject", "(sin asunto)")),
                "date": parsed_date,
            })
            
            if only_new:
                new_seen_emails.add(mid_str)

        conn.close()
        conn.logout()

        if only_new and new_seen_emails:
            _save_seen_emails(new_seen_emails)

        now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        return {
            "folder": folder,
            "emails": emails,
            "count": len(emails),
            "total_in_period": len(mail_ids),
            "fetched_at": now,
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

async def list_emails(folder: str = "INBOX", limit: int = 10, only_new: bool = False) -> dict:
    """Listar los últimos N correos."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_emails_sync, folder, limit, only_new)


async def read_email(email_id: str, folder: str = "INBOX") -> dict:
    """Leer un correo específico por ID."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read_email_sync, email_id, folder)


async def search_emails(query: str, folder: str = "INBOX", limit: int = 10) -> dict:
    """Buscar correos por asunto o remitente."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_emails_sync, query, folder, limit)
