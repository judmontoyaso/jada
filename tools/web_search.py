"""
tools/web_search.py — Búsqueda web robusta

Primario: Brave Search API (si BRAVE_API_KEY está configurada)
Fallback: DuckDuckGo (sin key, pero menos confiable)
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


def _ddg_search(query: str, max_results: int = 5) -> Optional[list]:
    """Búsqueda usando DuckDuckGo (sin API key). Síncrona."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]
    except Exception as e:
        logger.warning(f"DuckDuckGo falló: {e}")
        return None


async def search(query: str, max_results: int = 5) -> dict:
    """
    Busca en la web. Intenta Brave primero, luego DuckDuckGo.
    Retorna siempre la misma estructura.
    """
    engine = "brave" if BRAVE_API_KEY else "duckduckgo"

    # Intentar Brave primero
    if BRAVE_API_KEY:
        results = await _brave_search(query, max_results)
        if results:
            return {"query": query, "results": results, "count": len(results), "engine": "brave"}
        logger.warning("Brave falló, intentando DuckDuckGo...")

    # Fallback a DuckDuckGo (en thread para no bloquear el event loop)
    results = await asyncio.get_event_loop().run_in_executor(
        None, _ddg_search, query, max_results
    )

    if results:
        return {"query": query, "results": results, "count": len(results), "engine": "duckduckgo"}

    return {
        "query": query,
        "results": [],
        "count": 0,
        "error": f"Sin resultados. Motores intentados: {'brave, ' if BRAVE_API_KEY else ''}duckduckgo",
    }
