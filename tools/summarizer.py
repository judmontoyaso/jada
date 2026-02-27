"""
tools/summarizer.py — Resumen de páginas web y texto largo
Descarga una URL, extrae el texto, y lo prepara para que el LLM lo resuma.
"""
import os
import re
import logging
import asyncio
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = int(os.getenv("SUMMARIZER_MAX_CHARS", "12000"))


class _HTMLTextExtractor(HTMLParser):
    """Extractor simple de texto desde HTML."""
    
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "header", "footer", "nav", "aside"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True
        elif tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._text.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._text)
        # Limpiar espacios excesivos
        raw = re.sub(r'\n\s*\n', '\n\n', raw)
        raw = re.sub(r'[ \t]+', ' ', raw)
        return raw.strip()


def _fetch_url_text_sync(url: str) -> dict:
    """Descargar una URL y extraer el texto visible."""
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jada/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf",
        })
        
        with urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()

        # Detectar encoding
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip()
        else:
            charset = "utf-8"

        text = raw.decode(charset, errors="replace")

        # Si es HTML, extraer texto
        if "html" in content_type.lower():
            parser = _HTMLTextExtractor()
            parser.feed(text)
            text = parser.get_text()
        
        # Truncar si es muy largo
        if len(text) > MAX_CONTENT_CHARS:
            text = text[:MAX_CONTENT_CHARS] + "\n\n[... contenido truncado ...]"

        return {
            "url": url,
            "content": text,
            "length": len(text),
            "truncated": len(text) >= MAX_CONTENT_CHARS,
        }
    except URLError as e:
        return {"error": f"No se pudo acceder a {url}: {str(e)}"}
    except Exception as e:
        return {"error": f"Error procesando {url}: {str(e)}"}


async def fetch_and_summarize(url: str) -> dict:
    """Descargar URL y retornar el texto para que el LLM resuma."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_url_text_sync, url)
