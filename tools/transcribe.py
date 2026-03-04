"""
tools/transcribe.py — Transcripción de audio con Groq Whisper
Soporta archivos grandes (reuniones, podcasts) con chunking automático via ffmpeg.
"""
import os
import subprocess
import logging
from groq import Groq

logger = logging.getLogger("tools.transcribe")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")

# Límite de Groq free tier: 25MB por archivo
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
# Duración de cada chunk en segundos (5 min ≈ ~5MB en 16kHz mono WAV)
CHUNK_DURATION = 300  # 5 minutos


def get_groq_client() -> Groq:
    """Crea un cliente Groq (lazy init)."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY no configurada en .env")
    return Groq(api_key=GROQ_API_KEY)


def _get_audio_duration(file_path: str) -> float:
    """Obtiene la duración del audio en segundos usando ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _optimize_audio(input_path: str, output_path: str) -> bool:
    """Convierte audio a 16kHz mono WAV (óptimo para Whisper, reduce tamaño ~60%)."""
    try:
        subprocess.run(
            ["ffmpeg", "-i", input_path, "-ar", "16000", "-ac", "1",
             "-map", "0:a:", output_path, "-y", "-loglevel", "quiet"],
            timeout=120, check=True
        )
        return True
    except Exception as e:
        logger.error(f"Error optimizando audio: {e}")
        return False


def _split_audio(file_path: str, chunk_duration: int = CHUNK_DURATION) -> list[str]:
    """Divide un audio largo en chunks de N segundos."""
    duration = _get_audio_duration(file_path)
    if duration <= 0:
        return [file_path]

    chunks = []
    start = 0
    i = 0
    tmp_dir = os.path.dirname(file_path)

    while start < duration:
        output = os.path.join(tmp_dir, f"chunk_{i}.wav")
        try:
            subprocess.run(
                ["ffmpeg", "-i", file_path,
                 "-ss", str(start), "-t", str(chunk_duration),
                 "-ar", "16000", "-ac", "1",
                 output, "-y", "-loglevel", "quiet"],
                timeout=120, check=True
            )
            chunks.append(output)
        except Exception as e:
            logger.error(f"Error dividiendo audio en chunk {i}: {e}")
            break
        start += chunk_duration
        i += 1

    logger.info(f"✂️ Audio dividido en {len(chunks)} chunks ({duration:.0f}s total)")
    return chunks


def _transcribe_single(client: Groq, file_path: str, language: str = "es") -> str:
    """Transcribe un solo archivo de audio."""
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=f,
            model=WHISPER_MODEL,
            language=language,
            response_format="text",
            temperature=0.0,
        )
    return result.strip() if isinstance(result, str) else str(result).strip()


async def transcribe_audio(file_path: str, language: str = "es") -> str:
    """
    Transcribe un archivo de audio usando Groq Whisper.
    Si el archivo es >25MB o >10 min, lo divide en chunks automáticamente.
    """
    if not os.path.exists(file_path):
        return f"Error: archivo no encontrado: {file_path}"

    try:
        client = get_groq_client()
        file_size = os.path.getsize(file_path)
        duration = _get_audio_duration(file_path)

        # Caso 1: archivo pequeño — transcribir directo
        if file_size <= MAX_FILE_SIZE and duration <= CHUNK_DURATION * 2:
            # Optimizar formato si no es WAV
            if not file_path.endswith(".wav"):
                optimized = file_path + ".opt.wav"
                if _optimize_audio(file_path, optimized):
                    text = _transcribe_single(client, optimized, language)
                    os.remove(optimized)
                    logger.info(f"🎤 Transcrito: {text[:80]}...")
                    return text

            text = _transcribe_single(client, file_path, language)
            logger.info(f"🎤 Transcrito: {text[:80]}...")
            return text

        # Caso 2: archivo grande — dividir en chunks
        logger.info(f"📦 Audio grande ({file_size / 1024 / 1024:.1f}MB, {duration:.0f}s) — chunking...")
        chunks = _split_audio(file_path)

        if not chunks:
            return "Error: no se pudo dividir el audio"

        transcriptions = []
        for i, chunk in enumerate(chunks):
            try:
                text = _transcribe_single(client, chunk, language)
                if text:
                    transcriptions.append(text)
                logger.info(f"🎤 Chunk {i + 1}/{len(chunks)} transcrito")
            except Exception as e:
                logger.error(f"Error en chunk {i + 1}: {e}")
                transcriptions.append(f"[chunk {i + 1} falló]")
            finally:
                # Limpiar chunk temporal
                try:
                    os.remove(chunk)
                except Exception:
                    pass

        full_text = " ".join(transcriptions)
        logger.info(f"🎤 Transcripción completa: {len(full_text)} chars, {len(chunks)} chunks")
        return full_text

    except Exception as e:
        logger.error(f"❌ Error transcribiendo audio: {e}")
        return f"Error al transcribir: {e}"
