"""
tools/reminders.py — Sistema de recordatorios asincrónicos
Permite programar recordatorios que se envían al room de Matrix después de un delay.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Reminder:
    """Un recordatorio programado."""
    message: str
    delay_seconds: int
    room_id: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.now)
    task: asyncio.Task = field(default=None, repr=False)

    @property
    def fire_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.delay_seconds)

    @property
    def remaining(self) -> int:
        return max(0, int((self.fire_at - datetime.now()).total_seconds()))


class ReminderManager:
    """Gestiona recordatorios asincrónicos."""

    def __init__(self):
        self._reminders: list[Reminder] = []
        self._send_callback = None  # Se configura desde MatrixBot

    def set_send_callback(self, callback):
        """Configurar la función de envío (se llama desde MatrixBot)."""
        self._send_callback = callback

    async def add_reminder(self, message: str, delay_seconds: int, room_id: str, user_id: str) -> dict:
        """Programar un recordatorio."""
        if delay_seconds < 5:
            return {"error": "El delay mínimo es 5 segundos."}
        if delay_seconds > 86400:
            return {"error": "El delay máximo es 24 horas (86400 segundos)."}
        if not self._send_callback:
            return {"error": "El sistema de recordatorios no está conectado al chat."}

        reminder = Reminder(
            message=message,
            delay_seconds=delay_seconds,
            room_id=room_id,
            user_id=user_id,
        )

        # Crear task asíncrono
        reminder.task = asyncio.create_task(self._fire_reminder(reminder))
        self._reminders.append(reminder)

        # Formato legible
        if delay_seconds >= 3600:
            time_str = f"{delay_seconds // 3600}h {(delay_seconds % 3600) // 60}min"
        elif delay_seconds >= 60:
            time_str = f"{delay_seconds // 60}min"
        else:
            time_str = f"{delay_seconds}s"

        logger.info(f"⏰ Recordatorio programado en {time_str}: {message[:50]}")

        return {
            "success": True,
            "message": f"⏰ Recordatorio programado para dentro de {time_str}",
            "fire_at": reminder.fire_at.strftime("%H:%M:%S"),
            "delay_seconds": delay_seconds,
            "reminder_text": message,
        }

    async def list_reminders(self, room_id: str = None) -> dict:
        """Listar recordatorios activos."""
        # Limpiar recordatorios completados
        self._reminders = [r for r in self._reminders if r.task and not r.task.done()]

        active = self._reminders
        if room_id:
            active = [r for r in active if r.room_id == room_id]

        if not active:
            return {"reminders": [], "message": "No hay recordatorios activos."}

        return {
            "reminders": [
                {
                    "message": r.message,
                    "fire_at": r.fire_at.strftime("%H:%M:%S"),
                    "remaining_seconds": r.remaining,
                }
                for r in active
            ],
            "count": len(active),
        }

    async def cancel_all(self, room_id: str = None) -> dict:
        """Cancelar todos los recordatorios."""
        cancelled = 0
        remaining = []
        for r in self._reminders:
            if room_id and r.room_id != room_id:
                remaining.append(r)
                continue
            if r.task and not r.task.done():
                r.task.cancel()
                cancelled += 1
        self._reminders = remaining
        return {"cancelled": cancelled, "message": f"Se cancelaron {cancelled} recordatorios."}

    async def _fire_reminder(self, reminder: Reminder):
        """Esperar el delay y luego enviar el recordatorio."""
        try:
            await asyncio.sleep(reminder.delay_seconds)
            text = f"⏰ **Recordatorio:** {reminder.message}"
            if self._send_callback:
                await self._send_callback(reminder.room_id, text)
            logger.info(f"⏰ Recordatorio enviado: {reminder.message[:50]}")
        except asyncio.CancelledError:
            logger.info(f"⏰ Recordatorio cancelado: {reminder.message[:50]}")
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
