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
from typing import Any, Optional
from collections import defaultdict
from dotenv import load_dotenv
from nio import (
    AsyncClient,
    AsyncClientConfig,
    LoginResponse,
    RoomMessageText,
    RoomMessageImage,
    RoomMessageAudio,
    InviteEvent,
    MegolmEvent,
    DownloadResponse,
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
    def __init__(self, agent_class):
        self.agent = agent_class(bot=self)
        self.client = AsyncClient(
            HOMESERVER,
            BOT_USER,
            config=AsyncClientConfig(max_limit_exceeded=0, max_timeouts=0, store_sync_tokens=False),
        )
        self._start_token = None
        self._start_time = time.time()
        # Rate limiting: {user_id: [timestamp, ...]}
        self._user_timestamps = defaultdict(list)
        # Deduplicación: event_ids ya procesados (evita doble respuesta si hay 2 instancias)
        self._processed_events: set[str] = set()
        self._MAX_PROCESSED = 500  # evitar memory leak en sesiones largas
        # Flag: True cuando el bot ya terminó el sync inicial y está listo
        self._ready = False

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

        # Registrar callbacks antes del sync inicial para no perder mensajes nuevos
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.client.add_event_callback(self._on_image, RoomMessageImage)
        self.client.add_event_callback(self._on_audio, RoomMessageAudio)
        self.client.add_event_callback(self._on_invite, InviteEvent)
        self.client.add_event_callback(self._on_megolm, MegolmEvent)
        
        # Log joined rooms
        rooms = self.client.rooms
        logger.info(f"🏘️ Rooms unidos: {list(rooms.keys())}") if rooms else logger.info("🏘️ No estoy en ningún room.")

        # Conectar el sistema de recordatorios al chat
        from tools.reminders import reminder_manager
        reminder_manager.set_send_callback(self._send)

        # Sync inicial — recolecta estado sin procesar mensajes
        await self.client.sync(timeout=0)
        self._start_token = self.client.next_batch
        # Ahora sí estamos listos para procesar mensajes NUEVOS
        self._ready = True
        
        # Log joined rooms
        rooms = self.client.rooms
        logger.info(f"🏘️ Rooms unidos: {list(rooms.keys())}") if rooms else logger.info("🏘️ No estoy en ningún room.")

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

    async def _on_image(self, room, event: RoomMessageImage):
        """Callback para imágenes nuevas."""
        if not self._ready:
            return
        # Ignorar mensajes de antes del inicio
        if self._start_token and event.server_timestamp < self._get_start_ms():
            return
        if event.sender == BOT_USER:
            return
        if ALLOWED_ROOMS and room.room_id not in ALLOWED_ROOMS:
            return

        logger.info(f"🖼️ [{room.room_id}] {event.sender} envió una imagen: {event.body}")

        # Crear carpeta temporal para descargas si no existe
        tmp_dir = "/tmp/jada_images"
        os.makedirs(tmp_dir, exist_ok=True)
        
        file_path = os.path.join(tmp_dir, f"{event.event_id}_{event.body}")
        
        try:
            # Descargar la imagen
            resp = await self.client.download(event.url)
            if isinstance(resp, DownloadResponse):
                with open(file_path, "wb") as f:
                    f.write(resp.body)
                
                logger.info(f"✅ Imagen descargada en: {file_path}")
                
                # Procesar con el agente
                await self._set_typing(room.room_id, typing=True)
                response = await self.agent.chat(
                    user_message=event.body or "Analiza esta imagen",
                    user_id=event.sender,
                    room_id=room.room_id,
                    images=[file_path]
                )
                await self._send(room.room_id, response)
                await self._react(room.room_id, event.event_id, "👀")
            else:
                logger.error(f"❌ Error descargando imagen: {resp}")
        except Exception as e:
            logger.exception(f"Error procesando imagen: {e}")
            await self._send(room.room_id, f"⚠️ Error al procesar la imagen: {str(e)}")
        finally:
            await self._set_typing(room.room_id, typing=False)

    async def _on_audio(self, room, event: RoomMessageAudio):
        """Callback para mensajes de voz / audio."""
        if not self._ready:
            return
        if self._start_token and event.server_timestamp < self._get_start_ms():
            return
        if event.sender == BOT_USER:
            return
        if ALLOWED_ROOMS and room.room_id not in ALLOWED_ROOMS:
            return

        logger.info(f"🎤 [{room.room_id}] {event.sender} envió audio: {event.body}")

        # Deduplicar
        if event.event_id in self._processed_events:
            return
        self._processed_events.add(event.event_id)

        tmp_dir = "/tmp/jada_audio"
        os.makedirs(tmp_dir, exist_ok=True)

        # Determinar extensión del archivo
        ext = ".ogg"  # Matrix suele enviar ogg
        if event.body and "." in event.body:
            ext = os.path.splitext(event.body)[1]
        file_path = os.path.join(tmp_dir, f"{event.event_id}{ext}")

        try:
            # Descargar audio
            resp = await self.client.download(event.url)
            if not isinstance(resp, DownloadResponse):
                logger.error(f"❌ Error descargando audio: {resp}")
                return

            with open(file_path, "wb") as f:
                f.write(resp.body)
            logger.info(f"✅ Audio descargado: {file_path} ({len(resp.body)} bytes)")

            # Transcribir con Groq Whisper
            await self._set_typing(room.room_id, typing=True)
            from tools.transcribe import transcribe_audio
            transcription = await transcribe_audio(file_path)

            if not transcription or transcription.startswith("Error"):
                logger.error(f"❌ Transcripción falló: {transcription}")
                await self._send(room.room_id, "⚠️ No pude transcribir el audio.")
                return

            logger.info(f"🎤 Transcripción: {transcription[:80]}...")

            # Enviar transcripción al agente como si fuera un mensaje de texto
            response = await self.agent.chat(
                user_message=transcription,
                user_id=event.sender,
                room_id=room.room_id,
            )
            await self._send(room.room_id, response)
            await self._react(room.room_id, event.event_id, "🎤")

        except Exception as e:
            logger.exception(f"Error procesando audio: {e}")
            await self._send(room.room_id, f"⚠️ Error al procesar el audio: {str(e)}")
        finally:
            await self._set_typing(room.room_id, typing=False)
            # Limpiar archivo temporal
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    async def _on_message(self, room, event: RoomMessageText):
        """Callback para mensajes nuevos en rooms."""
        # Ignorar TODOS los mensajes hasta que el bot esté listo (sync inicial completo)
        if not self._ready:
            return
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
            await self.agent.clear_history(room.room_id)
            await self._send(room.room_id, "🗑️ Historial borrado.")
            return

        logger.info(f"📨 [{room.room_id}] {event.sender}: {message[:80]}")

        # Deduplicar: ignorar si ya lo procesamos (protege contra doble instancia)
        if event.event_id in self._processed_events:
            logger.debug(f"Evento duplicado ignorado: {event.event_id}")
            return
        self._processed_events.add(event.event_id)
        # Limpiar set si crece demasiado
        if len(self._processed_events) > self._MAX_PROCESSED:
            self._processed_events = set(list(self._processed_events)[-self._MAX_PROCESSED // 2:])

        # Timeouts configurables
        THINK_TIMEOUT   = int(os.getenv("JADA_THINK_TIMEOUT", "90"))   # seg máx para responder
        NUDGE_AFTER     = int(os.getenv("JADA_NUDGE_AFTER",   "25"))   # seg antes de avisar

        # Mensajes de progreso si tarda (humor negro incluído)
        NUDGE_MSGS = [
            "_Todavía estoy aquí, sólo pensando muy fuerte..._",
            "_Procesando. Mi GPU imaginaria está ardiendo._",
            "_Sigo viva. Esto está tardando más de lo normal._",
        ]
        import random as _rnd

        nudge_sent = False
        async def _nudge():
            """Avisa al usuario si la respuesta tarda demasiado (1 solo mensaje)."""
            nonlocal nudge_sent
            await asyncio.sleep(NUDGE_AFTER)
            if not nudge_sent:
                nudge_sent = True
                try:
                    await self._send(room.room_id, _rnd.choice(NUDGE_MSGS))
                except Exception:
                    pass

        nudge_task = asyncio.create_task(_nudge())
        try:
            # Mostrar indicador "escribiendo..." mientras procesa
            await self._set_typing(room.room_id, typing=True)
            response = await asyncio.wait_for(
                self.agent.chat(
                    user_message=message,
                    user_id=event.sender,
                    room_id=room.room_id,
                ),
                timeout=THINK_TIMEOUT,
            )
            nudge_task.cancel()
            await self._react(room.room_id, event.event_id, "✅")
        except asyncio.TimeoutError:
            nudge_task.cancel()
            logger.warning(f"⏱️ Timeout ({THINK_TIMEOUT}s) procesando mensaje de {event.sender}")
            response = (
                f"⚠️ Me trové pensando por más de {THINK_TIMEOUT}s y decidí rendirme. "
                "La API de NIM está lenta hoy. Intenta de nuevo."
            )
            await self._react(room.room_id, event.event_id, "❌")
        except Exception as e:
            nudge_task.cancel()
            logger.exception(f"Error en agente: {e}")
            response = f"⚠️ Error procesando tu mensaje: {str(e)}"
            await self._react(room.room_id, event.event_id, "❌")
        finally:
            # Siempre apagar el typing indicator
            await self._set_typing(room.room_id, typing=False)

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

    async def send_message(self, room_id: str, text: str):
        """Alias público de _send para uso externo (scheduler, tests)."""
        await self._send(room_id, text)

    async def send_image(self, room_id: str, file_path: str, body: str = "image.png"):
        """Sube y envía una imagen a un room de Matrix."""
        try:
            mxc_url = await self._upload_file(file_path)
            if not mxc_url:
                raise Exception("No se pudo obtener la URL MXC del archivo.")
            
            import os
            from PIL import Image
            
            # Obtener dimensiones e info básica
            with Image.open(file_path) as img:
                width, height = img.size
                size = os.path.getsize(file_path)
            
            content = {
                "body": body,
                "info": {
                    "size": size,
                    "mimetype": "image/png",
                    "w": width,
                    "h": height
                },
                "msgtype": "m.image",
                "url": mxc_url
            }
            
            await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content
            )
            logger.info(f"🖼️ Imagen enviada a {room_id}: {file_path}")
        except Exception as e:
            logger.error(f"❌ Error enviando imagen: {e}")
            await self._send(room_id, f"⚠️ Error al enviar la imagen: {str(e)}")

    async def _upload_file(self, file_path: str) -> str:
        """Sube un archivo al homeserver y retorna su URL MXC."""
        import magic
        mime = magic.Magic(mime=True)
        content_type = mime.from_file(file_path)
        
        with open(file_path, "rb") as f:
            resp = await self.client.upload(
                f,
                content_type=content_type,
                filename=os.path.basename(file_path)
            )
            
        from nio import UploadResponse
        # Fix: handle tuple (UploadResponse, Error) returned by some nio versions
        actual_resp = resp[0] if isinstance(resp, tuple) else resp

        if isinstance(actual_resp, UploadResponse):
            return actual_resp.content_uri
        else:
            logger.error(f"Error subiendo archivo: {resp}")
            return ""

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

    async def _set_typing(self, room_id: str, typing: bool, timeout: int = 30000):
        """Enviar indicador de escritura ('escribiendo...') al room."""
        try:
            await self.client.room_typing(room_id, typing_state=typing, timeout=timeout)
        except Exception as e:
            logger.debug(f"No se pudo enviar typing indicator: {e}")

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
        return int(self._start_time * 1000) - 60_000  # 1 minuto de gracia


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
