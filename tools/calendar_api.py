import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Necesitamos permisos de leer y escribir eventos
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')
TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', 'token.json')

def _get_calendar_service():
    """Obtiene el servicio autenticado de Google Calendar API."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # Si no hay credenciales o expiraron, intentamos refrescar el token
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Sobreescribimos con el token fresquito
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        else:
            raise RuntimeError(
                "Credenciales de Google no válidas. Debes ejecutar "
                "`python tools/google_auth.py` en la terminal primero para loguearte."
            )

    return build('calendar', 'v3', credentials=creds)


def _get_today_events_sync() -> dict:
    """Obtener los eventos de hoy desde la API."""
    try:
        service = _get_calendar_service()
        
        # Desde la medianoche de hoy
        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        # Formato ISO requerido por Google: 2026-02-27T00:00:00Z
        time_min = start_of_day.astimezone().isoformat()
        time_max = end_of_day.astimezone().isoformat()

        events_result = service.events().list(
            calendarId='primary', timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])

        today_events = []
        for event in events:
            # Los eventos de todo el día solo tienen 'date', los demás 'dateTime'
            start = event['start'].get('dateTime', event['start'].get('date'))
            today_events.append({
                "title": event.get('summary', 'Sin título'),
                "start": start,
                "location": event.get('location', ''),
                "description": event.get('description', '')[:500] if event.get('description') else ''
            })

        return {"date": start_of_day.strftime("%Y-%m-%d"), "events": today_events, "count": len(today_events)}
    except Exception as e:
        logger.error(f"Error obteniendo eventos de hoy: {str(e)}")
        return {"error": f"Error obteniendo eventos de hoy: {str(e)}"}


def _get_upcoming_events_sync(days: int = 7, limit: int = 15) -> dict:
    """Obtener los próximos N eventos desde la API."""
    try:
        service = _get_calendar_service()
        
        now = datetime.now()
        time_min = now.astimezone().isoformat()
        end_date = now + timedelta(days=days)
        time_max = end_date.astimezone().isoformat()

        events_result = service.events().list(
            calendarId='primary', timeMin=time_min, timeMax=time_max,
            maxResults=limit, singleEvents=True,
            orderBy='startTime').execute()
        events = events_result.get('items', [])

        upcoming = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            upcoming.append({
                "title": event.get('summary', 'Sin título'),
                "start": start,
                "location": event.get('location', ''),
                "description": event.get('description', '')[:500] if event.get('description') else ''
            })

        return {
            "from": now.strftime("%Y-%m-%d"),
            "to": end_date.strftime("%Y-%m-%d"),
            "events": upcoming,
            "count": len(upcoming),
        }
    except Exception as e:
        logger.error(f"Error obteniendo próximos eventos: {str(e)}")
        return {"error": f"Error obteniendo próximos eventos: {str(e)}"}


def _add_event_sync(title: str, start_datetime: str, end_datetime: str, description: str = "") -> dict:
    """
    Agrega un nuevo evento al calendario primario.
    Start/End format: ISO 8601 (e.g. '2026-02-28T14:00:00-05:00')
    """
    try:
        service = _get_calendar_service()
        
        event_body = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_datetime,
                # Usa la zona horaria del equipo si no viaja en el ISO
                'timeZone': datetime.now().astimezone().tzname() or 'America/Bogota',
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': datetime.now().astimezone().tzname() or 'America/Bogota',
            },
        }

        event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        return {
            "success": True,
            "message": f"Evento creado satisfactoriamente",
            "event_id": event.get('id'),
            "link": event.get('htmlLink')
        }
    except Exception as e:
        logger.error(f"Error al agregar evento: {str(e)}")
        return {"error": f"Error agregando el evento: {str(e)}"}

# ─── Wrappers async ───────────────────────────────────────────────────────────

async def get_today_events() -> dict:
    """Eventos de hoy via API."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_today_events_sync)


async def get_upcoming_events(days: int = 7, limit: int = 15) -> dict:
    """Próximos eventos via API."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_upcoming_events_sync, days, limit)


async def add_event(title: str, start_datetime: str, end_datetime: str, description: str = "") -> dict:
    """Agregar un evento al Google Calendar via API."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _add_event_sync, title, start_datetime, end_datetime, description)
