"""
tools/calendar_reader.py — Lectura de Google Calendar via URL ICS (solo lectura)
Descarga el .ics privado de Google Calendar y parsea los eventos.
NO requiere OAuth ni API keys — solo la URL privada del calendario.

Para obtener la URL:
  Google Calendar → Settings → [Tu calendario] → "Secret address in iCal format"
"""
import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CALENDAR_ICS_URL = os.getenv("GOOGLE_CALENDAR_ICS_URL", "")


def _parse_ics_events(ics_text: str) -> list[dict]:
    """Parsear eventos de un archivo ICS de forma ligera (sin dependencias externas)."""
    events = []
    current_event = None

    for line in ics_text.splitlines():
        line = line.strip()

        if line == "BEGIN:VEVENT":
            current_event = {}
        elif line == "END:VEVENT" and current_event is not None:
            events.append(current_event)
            current_event = None
        elif current_event is not None:
            if ":" in line:
                key, _, value = line.partition(":")

                # Manejar propiedades con parámetros (ej: DTSTART;VALUE=DATE:20260115)
                key_base = key.split(";")[0]

                if key_base == "SUMMARY":
                    current_event["title"] = value
                elif key_base == "DTSTART":
                    current_event["start_raw"] = value
                    current_event["start"] = _parse_ics_date(value)
                elif key_base == "DTEND":
                    current_event["end_raw"] = value
                    current_event["end"] = _parse_ics_date(value)
                elif key_base == "LOCATION":
                    current_event["location"] = value
                elif key_base == "DESCRIPTION":
                    # Unescaped ICS description
                    current_event["description"] = value.replace("\\n", "\n").replace("\\,", ",")[:500]
                elif key_base == "STATUS":
                    current_event["status"] = value

    return events


def _parse_ics_date(raw: str) -> str:
    """Convertir una fecha ICS a formato legible."""
    try:
        # Formato: 20260115T100000Z (datetime con zona)
        if "T" in raw:
            raw_clean = raw.replace("Z", "")
            dt = datetime.strptime(raw_clean[:15], "%Y%m%dT%H%M%S")
            if raw.endswith("Z"):
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M")
        else:
            # Formato: 20260115 (solo fecha, evento de todo el día)
            dt = datetime.strptime(raw[:8], "%Y%m%d")
            return dt.strftime("%Y-%m-%d") + " (todo el día)"
    except Exception:
        return raw


def _fetch_ics() -> str:
    """Descargar el archivo ICS del calendario."""
    if not CALENDAR_ICS_URL:
        raise ValueError(
            "GOOGLE_CALENDAR_ICS_URL no está configurado en .env. "
            "Ve a Google Calendar → Settings → [Tu calendario] → "
            "'Secret address in iCal format' y copia la URL."
        )

    req = Request(CALENDAR_ICS_URL, headers={"User-Agent": "Jada/1.0"})
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _get_today_events_sync() -> dict:
    """Obtener los eventos de hoy."""
    try:
        ics_text = _fetch_ics()
        all_events = _parse_ics_events(ics_text)

        today = datetime.now().strftime("%Y-%m-%d")
        today_events = [
            e for e in all_events
            if e.get("start", "").startswith(today)
        ]

        # Ordenar por hora
        today_events.sort(key=lambda e: e.get("start", ""))

        # Limpiar campos internos
        for e in today_events:
            e.pop("start_raw", None)
            e.pop("end_raw", None)

        return {"date": today, "events": today_events, "count": len(today_events)}
    except Exception as e:
        return {"error": f"Error obteniendo eventos de hoy: {str(e)}"}


def _get_upcoming_events_sync(days: int = 7, limit: int = 15) -> dict:
    """Obtener los próximos eventos en los siguientes N días."""
    try:
        ics_text = _fetch_ics()
        all_events = _parse_ics_events(ics_text)

        now = datetime.now()
        end_date = now + timedelta(days=days)
        now_str = now.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        upcoming = []
        for e in all_events:
            start = e.get("start", "")
            # Comparar como string (funciona para formato YYYY-MM-DD)
            if start >= now_str and start <= end_str + " 23:59":
                upcoming.append(e)

        # Ordenar por fecha
        upcoming.sort(key=lambda e: e.get("start", ""))
        upcoming = upcoming[:limit]

        # Limpiar
        for e in upcoming:
            e.pop("start_raw", None)
            e.pop("end_raw", None)

        return {
            "from": now_str,
            "to": end_str,
            "events": upcoming,
            "count": len(upcoming),
        }
    except Exception as e:
        return {"error": f"Error obteniendo próximos eventos: {str(e)}"}


def _search_events_sync(query: str, limit: int = 10) -> dict:
    """Buscar eventos por título o descripción."""
    try:
        ics_text = _fetch_ics()
        all_events = _parse_ics_events(ics_text)

        query_lower = query.lower()
        matches = []
        for e in all_events:
            title = e.get("title", "").lower()
            desc = e.get("description", "").lower()
            location = e.get("location", "").lower()
            if query_lower in title or query_lower in desc or query_lower in location:
                matches.append(e)

        # Ordenar por fecha y limitar
        matches.sort(key=lambda e: e.get("start", ""), reverse=True)
        matches = matches[:limit]

        # Limpiar
        for e in matches:
            e.pop("start_raw", None)
            e.pop("end_raw", None)

        return {"query": query, "events": matches, "count": len(matches)}
    except Exception as e:
        return {"error": f"Error buscando eventos: {str(e)}"}


# ─── Wrappers async ───────────────────────────────────────────────────────────

async def get_today_events() -> dict:
    """Eventos de hoy."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_today_events_sync)


async def get_upcoming_events(days: int = 7, limit: int = 15) -> dict:
    """Próximos eventos."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_upcoming_events_sync, days, limit)


async def search_events(query: str, limit: int = 10) -> dict:
    """Buscar eventos."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_events_sync, query, limit)
