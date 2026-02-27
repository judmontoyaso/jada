"""
tools/web_search.py — Búsqueda web robusta

Primario: Brave Search API (si BRAVE_API_KEY está configurada)
Fallback: DuckDuckGo (sin key, pero menos confiable) y Google News RSS
"""
import os
import asyncio
import logging
import httpx
from typing import Optional

logger = logging.getLogger("jada.websearch")

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


async def _brave_search(query: str, max_results: int = 5) -> Optional[list]:
    """Búsqueda usando Brave Search API."""
    if not BRAVE_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                BRAVE_SEARCH_URL,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": BRAVE_API_KEY,
                },
                params={"q": query, "count": max_results, "text_decorations": False},
            )
            resp.raise_for_status()
            data = resp.json()
            web_results = data.get("web", {}).get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", ""),
                }
                for r in web_results[:max_results]
            ]
    except Exception as e:
        logger.warning(f"Brave Search falló: {e}")
        return None


def _ddg_search(query: str, max_results: int = 5, search_type: str = "text") -> dict:
    """Búsqueda usando DuckDuckGo (sin API key) y Google News RSS. Síncrona."""
    if "noticia" in query.lower() and search_type == "text":
        search_type = "news"

    formatted = []
    try:
        if search_type == "news":
            import urllib.request
            import urllib.parse
            import xml.etree.ElementTree as ET
            import re
            
            # Limpiar query para RSS (eliminar palabras que dañan la búsqueda exacta)
            clean_query = re.sub(r'(?i)\b(noticias?|hoy|de|del|las|los|la|el|en|sobre|al|y|o|febrero|marzo|enero|2026|actualidad|ultimas|últimas|relevantes)\b', '', query)
            clean_query = " ".join(clean_query.split()) # Quitar espacios dobles
            if not clean_query:
                clean_query = "Colombia" # Fallback si limpió todo

            safe_query = urllib.parse.quote_plus(clean_query)
            # Buscar en Google News RSS en español (Latinoamérica)
            rss_url = f"https://news.google.com/rss/search?q={safe_query}&hl=es-419&gl=CO"
            try:
                req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()
                root = ET.fromstring(xml_data)
                
                for item in root.findall(".//item")[:max_results]:
                    formatted.append({
                        "title": item.findtext("title", ""),
                        "url": item.findtext("link", ""),
                        "snippet": item.findtext("description", ""),
                        "date": item.findtext("pubDate", ""),
                        "source": item.findtext("source", "")
                    })
            except Exception as e:
                logger.error(f"Error leyendo Google News RSS: {str(e)}")
                return []
        else:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                formatted = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                    for r in results
                ]
        return formatted
    except Exception as e:
        logger.warning(f"DuckDuckGo/News falló: {e}")
        return []


async def search(query: str, max_results: int = 5, search_type: str = "text") -> dict:
    """
    Busca en la web. Intenta Brave primero, luego DuckDuckGo/News.
    Retorna siempre la misma estructura.
    """
    engine = "brave" if BRAVE_API_KEY and search_type != "news" else "duckduckgo"

    # Intentar Brave primero solo para búsquedas de texto
    if BRAVE_API_KEY and search_type != "news":
        results = await _brave_search(query, max_results)
        if results:
            return {"query": query, "results": results, "count": len(results), "engine": "brave"}
        logger.warning("Brave falló, intentando DuckDuckGo...")

    # Fallback a DuckDuckGo/Google News RSS (en thread para no bloquear el event loop)
    results = await asyncio.get_event_loop().run_in_executor(
        None, _ddg_search, query, max_results, search_type
    )

    if results:
        return {"query": query, "results": results, "count": len(results), "engine": "duckduckgo_or_news"}

    return {
        "query": query,
        "results": [],
        "count": 0,
        "error": f"Sin resultados. Motores intentados: {'brave, ' if BRAVE_API_KEY else ''}duckduckgo/news",
    }
