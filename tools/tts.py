"""
tools/tts.py — Text-to-Speech usando Deepgram (aura-2-gloria-es)

Genera audio MP3 a partir de texto para respuestas de voz en Matrix.
Usa la API REST directamente (sin dependencia de SDK version).
"""
import os
import logging
import asyncio
import hashlib
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
TTS_MODEL = "aura-2-gloria-es"
TTS_DIR = Path("/tmp/jada_tts")
MAX_TEXT_LENGTH = 500
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"


async def text_to_audio(text: str, filename: str = "") -> str | None:
    """
    Convierte texto a audio MP3 usando Deepgram REST API.
    Returns: path al archivo MP3, o None si falla.
    """
    if not DEEPGRAM_API_KEY:
        logger.warning("DEEPGRAM_API_KEY no configurado")
        return None

    if not text or len(text) > MAX_TEXT_LENGTH:
        return None

    TTS_DIR.mkdir(parents=True, exist_ok=True)

    if not filename:
        h = hashlib.md5(text.encode()).hexdigest()[:8]
        filename = f"jada_voice_{h}.mp3"

    filepath = str(TTS_DIR / filename)

    try:
        def _generate():
            import httpx as _httpx
            resp = _httpx.post(
                DEEPGRAM_TTS_URL,
                params={"model": TTS_MODEL, "encoding": "mp3"},
                headers={
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"text": text},
                timeout=15,
            )
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)

        await asyncio.to_thread(_generate)
        logger.info(f"🔊 TTS generado: {filepath} ({len(text)} chars)")
        return filepath

    except Exception as e:
        logger.error(f"❌ TTS error: {e}")
        return None


def should_use_voice(text: str) -> bool:
    """Decide si una respuesta debería ser voz.
    Solo retorna True si el texto es corto y no tiene formato complejo.
    Usado internamente por reminders/heartbeat. Para chat normal,
    se necesita que el usuario pida explícitamente audio.
    """
    if not text or not DEEPGRAM_API_KEY:
        return False
    if len(text) > MAX_TEXT_LENGTH:
        return False
    # No usar voz si tiene tablas, listas largas, code blocks, URLs
    markers = ["```", "| ", "http", "- **", "\n- ", "\n1.", "\n2."]
    if any(m in text for m in markers):
        return False
    return True


def user_wants_voice(message: str) -> bool:
    """Detecta si el usuario pidió respuesta por audio."""
    msg = message.lower()
    triggers = ["responde con audio", "dime con voz", "en audio", "por voz",
                "háblame", "hablame", "dilo con voz", "mándalo en audio"]
    return any(t in msg for t in triggers)
