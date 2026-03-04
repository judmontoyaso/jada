"""
tools/reminders.py — Sistema de recordatorios con persistencia en MongoDB

- Los recordatorios se guardan en MongoDB (colección 'reminders')
- Al arrancar, los que aún no dispararon se re-encolan como asyncio tasks
- Así sobreviven reinicios del servicio

Flujo:
  1. set_reminder() → guarda en MongoDB → crea asyncio.sleep task
  2. Al reiniciar → load_pending_reminders() → re-encola todos los pendientes
  3. _fire_reminder() → espera hasta fire_at, envía mensaje, marca como done
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import pytz
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TIMEZONE = os.getenv("TIMEZONE", "America/Bogota")
TZ = pytz.timezone(TIMEZONE)


def _now_local() -> datetime:
    """Hora actual en zona Colombia (naive para comparaciones simples)."""
    return datetime.now(TZ).replace(tzinfo=None)


class ReminderManager:
    """Gestiona recordatorios con persistencia en MongoDB."""

    COLLECTION = "reminders"

    def __init__(self):
        self._send_callback = None
        self._voice_callback = None
        self._tasks: dict[str, asyncio.Task] = {}  # reminder_id → Task
        self._db = None

    def set_send_callback(self, callback):
        self._send_callback = callback

    def set_voice_callback(self, callback):
        """callback(room_id, text) → bool: True if sent as audio."""
        self._voice_callback = callback

    def _get_col(self):
        """Get MongoDB collection (sync — wrap with asyncio.to_thread)."""
        if self._db is None:
            uri = os.getenv("MONGO_URI", "")
            db_name = os.getenv("MONGO_DB", "n8n_memoria")
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self._db = client[db_name]
        return self._db[self.COLLECTION]

    async def load_pending_reminders(self):
        """Re-encola recordatorios pendientes desde MongoDB (llamar al iniciar)."""
        try:
            col = self._get_col()
            now = _now_local()
            pending = await asyncio.to_thread(lambda: list(col.find({"done": False})))
            re_queued = 0
            for doc in pending:
                fire_at = doc["fire_at"]
                if isinstance(fire_at, str):
                    fire_at = datetime.fromisoformat(fire_at)
                if fire_at < now:
                    fire_at = now + timedelta(seconds=2)
                delay = max(0, (fire_at - now).total_seconds())
                self._tasks[str(doc["_id"])] = asyncio.create_task(
                    self._fire_reminder(str(doc["_id"]), doc["message"], doc["room_id"], delay)
                )
                re_queued += 1
            if re_queued:
                logger.info(f"⏰ {re_queued} recordatorio(s) pendiente(s) re-encolado(s) desde MongoDB")
        except Exception as e:
            logger.error(f"⚠️ Error cargando recordatorios: {e}")

    async def add_reminder(self, message: str, delay_seconds: int, room_id: str, user_id: str) -> dict:
        """Programa un recordatorio y lo guarda en MongoDB."""
        if delay_seconds < 5:
            return {"error": "El delay mínimo es 5 segundos."}
        if delay_seconds > 86400:
            return {"error": "El delay máximo es 24 horas (86400 segundos)."}
        if not self._send_callback:
            return {"error": "El sistema de recordatorios no está conectado al chat."}

        fire_at = _now_local() + timedelta(seconds=delay_seconds)

        # Persist to MongoDB
        try:
            col = self._get_col()
            result = await asyncio.to_thread(lambda: col.insert_one({
                "message": message,
                "room_id": room_id,
                "user_id": user_id,
                "delay_seconds": delay_seconds,
                "fire_at": fire_at.isoformat(),
                "created_at": _now_local().isoformat(),
                "done": False,
            }))
            reminder_id = str(result.inserted_id)
        except Exception as e:
            logger.error(f"⚠️ Error guardando recordatorio en MongoDB: {e}")
            reminder_id = f"mem_{id(message)}"

        # Schedule asyncio task
        self._tasks[reminder_id] = asyncio.create_task(
            self._fire_reminder(reminder_id, message, room_id, delay_seconds)
        )

        # Human-readable time string
        if delay_seconds >= 3600:
            time_str = f"{delay_seconds // 3600}h {(delay_seconds % 3600) // 60}min"
        elif delay_seconds >= 60:
            time_str = f"{delay_seconds // 60}min"
        else:
            time_str = f"{delay_seconds}s"

        logger.info(f"⏰ Recordatorio guardado en {time_str}: {message[:50]}")
        return {
            "success": True,
            "message": f"⏰ Recordatorio guardado para dentro de {time_str}",
            "fire_at": fire_at.strftime("%H:%M"),
            "delay_seconds": delay_seconds,
            "reminder_text": message,
        }

    async def list_reminders(self, room_id: str = None) -> dict:
        """Lista recordatorios activos (desde MongoDB + tasks en memoria)."""
        try:
            col = self._get_col()
            query = {"done": False}
            if room_id:
                query["room_id"] = room_id
            docs = await asyncio.to_thread(lambda: list(col.find(query)))

            if not docs:
                return {"reminders": [], "message": "No hay recordatorios activos."}

            now = _now_local()
            reminders = []
            for doc in docs:
                fire_at = doc["fire_at"]
                if isinstance(fire_at, str):
                    fire_at = datetime.fromisoformat(fire_at)
                remaining = max(0, int((fire_at - now).total_seconds()))
                reminders.append({
                    "message": doc["message"],
                    "fire_at": fire_at.strftime("%H:%M"),
                    "remaining_seconds": remaining,
                })

            return {"reminders": reminders, "count": len(reminders)}
        except Exception as e:
            logger.error(f"Error listando recordatorios: {e}")
            return {"reminders": [], "message": f"Error listando: {e}"}

    async def cancel_all(self, room_id: str = None) -> dict:
        """Cancela todos los recordatorios activos."""
        cancelled = 0
        for task_id, task in list(self._tasks.items()):
            if task and not task.done():
                task.cancel()
                cancelled += 1
        self._tasks.clear()

        try:
            col = self._get_col()
            query = {"done": False}
            if room_id:
                query["room_id"] = room_id
            result = await asyncio.to_thread(lambda: col.update_many(query, {"$set": {"done": True}}))
            cancelled = max(cancelled, result.modified_count)
        except Exception as e:
            logger.warning(f"Error cancelando en MongoDB: {e}")

        return {"cancelled": cancelled, "message": f"Se cancelaron {cancelled} recordatorios."}

    async def _fire_reminder(self, reminder_id: str, message: str, room_id: str, delay_seconds: float):
        """Espera el delay y envía el recordatorio."""
        try:
            await asyncio.sleep(delay_seconds)
            text = f"⏰ **Recordatorio:** {message}"
            if self._send_callback:
                await self._send_callback(room_id, text)
            logger.info(f"⏰ Recordatorio enviado: {message[:50]}")

            # Mark as done in MongoDB
            try:
                from bson import ObjectId
                col = self._get_col()
                await asyncio.to_thread(lambda: col.update_one({"_id": ObjectId(reminder_id)}, {"$set": {"done": True}}))
            except Exception:
                pass  # Memory-only reminders don't have a valid ObjectId
        except asyncio.CancelledError:
            logger.info(f"⏰ Recordatorio cancelado: {message[:50]}")
        except Exception as e:
            logger.error(f"Error enviando recordatorio: {e}")


def parse_time_expression(text: str) -> int | None:
    """
    Parsear expresiones de tiempo del usuario.
    Soporta: '5 min', '2 horas', '30 segundos', '1h30m', '90s', etc.
    Retorna segundos o None si no se puede parsear.
    """
    text = text.lower().strip()

    # Limpiar conectores como "en", "dentro de", "por"
    text = re.sub(r'^(en\s+|dentro\s+de\s+|por\s+)', '', text)

    # Patrón: "1h30m", "2h", "30m", "90s"
    match = re.match(r'^(\d+)\s*h(?:oras?)?\s*(?:(\d+)\s*m(?:in(?:utos?)?)?)?$', text)
    if match:
        hours = int(match.group(1))
        mins = int(match.group(2) or 0)
        return hours * 3600 + mins * 60

    # Patrón: "30 minutos", "5 min", "2 horas"
    match = re.match(r'^(\d+)\s*(s(?:eg(?:undos?)?)?|m(?:in(?:utos?)?)?|h(?:oras?)?)$', text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)[0]
        if unit == 's':
            return value
        elif unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 3600

    # Patrón: solo número (asume minutos)
    if text.isdigit():
        return int(text) * 60

    return None


# Singleton global
reminder_manager = ReminderManager()
