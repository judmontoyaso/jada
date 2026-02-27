"""
matrix/client.py — Bot de Matrix usando matrix-nio (async)
Conecta al homeserver, escucha mensajes en los rooms configurados
y los enrutá al agente Jada.

Incluye: rate limiting, streaming de respuestas largas, cleanup de sesión.
"""
import asyncio
import os
import time
import logging
from collections import defaultdict
from dotenv import load_dotenv
from nio import (
    AsyncClient,
    AsyncClientConfig,
    LoginResponse,
    RoomMessageText,
    InviteEvent,
    MegolmEvent,
)

load_dotenv()

logger = logging.getLogger(__name__)

HOMESERVER     = os.getenv("MATRIX_HOMESERVER", "https://matrix.org")
BOT_USER       = os.getenv("MATRIX_USER", "@jada:matrix.org")
BOT_PASSWORD   = os.getenv("MATRIX_PASSWORD", "")
ACCESS_TOKEN   = os.getenv("MATRIX_ACCESS_TOKEN", "")
ROOM_IDS_RAW   = os.getenv("MATRIX_ROOM_IDS", "")
ALLOWED_ROOMS  = set(r.strip() for r in ROOM_IDS_RAW.split(",") if r.strip())
AGENT_NAME     = os.getenv("AGENT_NAME", "Jada")

# Retry config
MAX_RETRY_DELAY = 60
INITIAL_RETRY_DELAY = 5

# Rate limiting
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "15"))

# Streaming: mensajes más largos que esto se dividen en chunks
MAX_MSG_LENGTH = int(os.getenv("MAX_MSG_LENGTH", "2000"))


class MatrixBot:
    def __init__(self, agent):
        self.agent = agent
        self.client = AsyncClient(
            HOMESERVER,
            BOT_USER,
            config=AsyncClientConfig(max_limit_exceeded=0, max_timeouts=0),
        )
        self._start_token = None
        # Rate limiting: {user_id: [timestamp, timestamp, ...]}
        self._user_timestamps = defaultdict(list)

    async def start(self):
        """Conectar al servidor Matrix e iniciar el loop de eventos con retry."""
        logger.info(f"🤖 Conectando como {BOT_USER} a {HOMESERVER}...")

        if ACCESS_TOKEN:
            # Usar access token directamente (sin necesidad de password)
            self.client.access_token = ACCESS_TOKEN
            self.client.user_id = BOT_USER
            self.client.device_id = "JADA"
            logger.info("✅ Conectado con access token.")
        else:
            # Fallback: login con contraseña
            resp = await self.client.login(BOT_PASSWORD)
            if not isinstance(resp, LoginResponse):
                raise RuntimeError(f"❌ Login fallido: {resp}")
            logger.info(f"✅ Conectado con password. Device ID: {self.client.device_id}")

        # Sync inicial para ignorar msgs históricos
        await self.client.sync(timeout=0)
        self._start_token = self.client.next_batch

        # Conectar el sistema de recordatorios al chat
        from tools.reminders import reminder_manager
        reminder_manager.set_send_callback(self._send)

        # Registrar callbacks
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.client.add_event_callback(self._on_invite, InviteEvent)
        self.client.add_event_callback(self._on_megolm, MegolmEvent)

        logger.info(f"👂 Escuchando en rooms: {ALLOWED_ROOMS or 'todos'}")

        # Loop con reintentos automáticos
        retry_delay = INITIAL_RETRY_DELAY
        try:
            while True:
                try:
                    await self.client.sync_forever(timeout=30000, full_state=False)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.warning(f"⚠️ Desconexión: {e}. Reintentando en {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
                    logger.info(f"🔄 Reintentando conexión...")
                else:
                    retry_delay = INITIAL_RETRY_DELAY
        finally:
            # Cleanup: cerrar la sesión correctamente
            await self._cleanup()

    async def _cleanup(self):
        """Cerrar la sesión de Matrix limpiamente."""
        try:
            await self.client.close()
            logger.info("🔒 Sesión de Matrix cerrada limpiamente")
        except Exception as e:
            logger.debug(f"Error cerrando sesión: {e}")

    def _check_rate_limit(self, user_id: str) -> bool:
        """Verificar si el usuario excede el rate limit. Retorna True si está permitido."""
        now = time.time()
        window = 60.0  # 1 minuto

        # Limpiar timestamps viejos
        self._user_timestamps[user_id] = [
            ts for ts in self._user_timestamps[user_id]
            if now - ts < window
        ]

        if len(self._user_timestamps[user_id]) >= RATE_LIMIT_PER_MINUTE:
            return False

        self._user_timestamps[user_id].append(now)
        return True

    async def _on_message(self, room, event: RoomMessageText):
        """Callback para mensajes nuevos en rooms."""
        # Ignorar mensajes de antes del inicio
        if self._start_token and event.server_timestamp < self._get_start_ms():
            return

        # Ignorar mensajes propios
        if event.sender == BOT_USER:
            return

        # Filtrar por rooms permitidos (si está configurado)
        if ALLOWED_ROOMS and room.room_id not in ALLOWED_ROOMS:
            return

        message = event.body.strip()
        if not message:
            return

        # Rate limiting
        if not self._check_rate_limit(event.sender):
            logger.warning(f"🚫 Rate limit excedido para {event.sender}")
            await self._send(room.room_id, "⚠️ Estás enviando mensajes muy rápido. Espera un momento.")
            return

        # Comandos especiales
        if message.lower() in ["/clear", "!clear"]:
            await self.agent.memory.clear_history(room.room_id, event.sender)
            await self._send(room.room_id, "🗑️ Historial borrado.")
            return

        logger.info(f"📨 [{room.room_id}] {event.sender}: {message[:80]}...")

        # Reacción ⏳ al recibir el mensaje
        await self._react(room.room_id, event.event_id, "⏳")

        try:
            response = await self.agent.chat(
                user_message=message,
                user_id=event.sender,
                room_id=room.room_id,
            )
            # Reacción ✅ al completar
            await self._react(room.room_id, event.event_id, "✅")
        except Exception as e:
            logger.exception(f"Error en agente: {e}")
            response = f"⚠️ Error procesando tu mensaje: {str(e)}"
            # Reacción ❌ en error
            await self._react(room.room_id, event.event_id, "❌")

        await self._send(room.room_id, response)

    async def _on_megolm(self, room, event: MegolmEvent):
        """Callback para mensajes encriptados que no se pueden descifrar."""
        if self._start_token and event.server_timestamp < self._get_start_ms():
            return
        if event.sender == BOT_USER:
            return

        logger.warning(
            f"🔒 Mensaje encriptado en [{room.room_id}] de {event.sender} — "
            f"No se puede descifrar (E2EE no soportado en Windows sin libolm)."
        )

        try:
            await self._send(
                room.room_id,
                "🔒 No puedo leer mensajes encriptados. "
                "Por favor, invítame a un room **sin encriptación** (E2EE desactivado)."
            )
        except Exception as e:
            logger.debug(f"No se pudo enviar aviso de E2EE: {e}")

    async def _on_invite(self, room, event: InviteEvent):
        """Aceptar invitaciones automáticamente."""
        logger.info(f"📩 Invitación a room {room.room_id}, aceptando...")
        await self.client.join(room.room_id)

    async def _send(self, room_id: str, text: str):
        """Enviar un mensaje de texto al room. Divide mensajes largos en chunks."""
        if len(text) <= MAX_MSG_LENGTH:
            await self._send_single(room_id, text)
        else:
            # Dividir en chunks respetando saltos de línea
            chunks = self._split_message(text, MAX_MSG_LENGTH)
            for i, chunk in enumerate(chunks):
                prefix = f"**(parte {i+1}/{len(chunks)})**\n" if len(chunks) > 1 else ""
                await self._send_single(room_id, prefix + chunk)
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)  # Delay entre chunks

    async def _send_single(self, room_id: str, text: str):
        """Enviar un mensaje individual al room."""
        try:
            await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": text,
                    "format": "org.matrix.custom.html",
                    "formatted_body": _markdown_to_html(text),
                },
            )
        except Exception as e:
            logger.error(f"❌ Error enviando mensaje a {room_id}: {e}")

    @staticmethod
    def _split_message(text: str, max_len: int) -> list[str]:
        """Dividir un mensaje largo en chunks, intentando cortar en saltos de línea."""
        chunks = []
        while len(text) > max_len:
            # Buscar el último salto de línea dentro del límite
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos == -1 or split_pos < max_len // 2:
                # Si no hay buen punto de corte, cortar en el espacio más cercano
                split_pos = text.rfind(" ", 0, max_len)
            if split_pos == -1:
                split_pos = max_len

            chunks.append(text[:split_pos].strip())
            text = text[split_pos:].strip()

        if text:
            chunks.append(text)

        return chunks

    async def _react(self, room_id: str, event_id: str, emoji: str):
        """Enviar una reacción emoji a un evento."""
        try:
            await self.client.room_send(
                room_id=room_id,
                message_type="m.reaction",
                content={
                    "m.relates_to": {
                        "rel_type": "m.annotation",
                        "event_id": event_id,
                        "key": emoji,
                    }
                },
            )
        except Exception as e:
            logger.debug(f"No se pudo enviar reacción {emoji}: {e}")

    def _get_start_ms(self) -> int:
        """Timestamp en ms de cuando arrancó el bot."""
        return int(time.time() * 1000) - 60_000  # 1 minuto de gracia


def _markdown_to_html(text: str) -> str:
    """Conversión básica de Markdown a HTML para el cliente Matrix."""
    import re
    # Negrita
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Cursiva
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Código inline
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Saltos de línea
    text = text.replace("\n", "<br>")
    return text
