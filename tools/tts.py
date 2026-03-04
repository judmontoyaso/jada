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


def _clean_for_tts(text: str) -> str:
    """Limpia texto para que el TTS no lea emojis, markdown ni símbolos raros."""
    import re
    # 1. Quitar emojis (unicode emoji ranges)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0000200D"             # zero width joiner
        "\U00002600-\U000026FF"  # misc symbols
        "\U0001FA00-\U0001FAFF"  # extended symbols
        "\U00002B50"             # star
        "\U0000231A-\U0000231B"  # watch/hourglass
        "\U000023E9-\U000023F3"  # media controls
        "\U000025AA-\U000025FE"  # geometric shapes
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)
    # 2. Quitar markdown: **bold**, *italic*, __underline__, `code`, ~~strike~~
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)     # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)          # *italic*
    text = re.sub(r'__(.+?)__', r'\1', text)          # __underline__
    text = re.sub(r'_(.+?)_', r'\1', text)            # _italic_
    text = re.sub(r'~~(.+?)~~', r'\1', text)          # ~~strike~~
    text = re.sub(r'`(.+?)`', r'\1', text)            # `code`
    # 3. Quitar bullet points y headers markdown
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # ### headers
    text = re.sub(r'^\s*[-•]\s+', '', text, flags=re.MULTILINE) # - bullets
    # 4. Limpiar espacios múltiples
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


async def text_to_audio(text: str, filename: str = "") -> str | None:
    """
    Convierte texto a audio MP3 usando Deepgram REST API.
    Returns: path al archivo MP3, o None si falla.
    """
    if not DEEPGRAM_API_KEY:
        logger.warning("DEEPGRAM_API_KEY no configurado")
        return None

    # Limpiar texto para TTS (sin emojis ni markdown)
    text = _clean_for_tts(text)

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
    import re
    msg = message.lower()
    # Regex patterns con palabras de relleno opcionales (un, una, el, la, esto, este)
    filler = r'(?:\s+(?:un|una|el|la|esto|este|eso|ese))?\s+'
    patterns = [
        rf'\b(?:en|con|por){filler}(?:audio|voz)\b',
        r'\b(?:háblame|hablame|háblale|hablale)\b',
        rf'\b(?:responde|dime|dilo){filler}(?:audio|voz)\b',
        rf'\b(?:manda|mándame|mandame|envía|envia|envíale){filler}(?:audio|voz)\b',
        rf'\b(?:mándalo|mandalo){filler}(?:audio|voz)\b',
        r'\bresponde\b.*\baudio\b',
    ]
    return any(re.search(p, msg) for p in patterns)


def strip_voice_intent(message: str) -> str:
    """Remueve frases de intención de audio del mensaje para que el LLM no se confunda."""
    import re
    filler = r'(?:\s+(?:un|una|el|la|esto|este|eso|ese))?\s+'
    patterns = [
        # "responde esto con un audio" / "responde en audio" / "responde esto en un audio"
        rf'(?i)\b(?:responde|dime|dilo)\s+(?:esto\s+)?(?:en|con|por){filler}(?:audio|voz)\b\.?\s*',
        # "envía un audio" / "mándame un audio"
        rf'(?i)\b(?:manda|mándame|mandame|envía|envia|envíale){filler}(?:audio|voz)\b\.?\s*',
        # "en audio" / "con un audio" / "por voz" standalone
        rf'(?i)\b(?:en|con|por){filler}(?:audio|voz)\b\.?\s*',
        # "háblame" / "hablame"
        r'(?i)\b(?:háblame|hablame|háblale|hablale)\b\.?\s*',
    ]
    result = message
    for pat in patterns:
        result = re.sub(pat, ' ', result)
    result = re.sub(r'\s{2,}', ' ', result).strip()
    result = re.sub(r'^[.,;:\-!?]+\s*', '', result).strip()
    return result if result else message
