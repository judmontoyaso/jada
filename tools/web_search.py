"""
tools/web_search.py — Búsqueda web usando DuckDuckGo (sin API key)
"""
from duckduckgo_search import DDGS


async def search(query: str, max_results: int = 5) -> dict:
    """
    Busca en la web usando DuckDuckGo y retorna una lista de resultados.
    No requiere API key.
    """
    try:
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

        return {"query": query, "results": formatted, "count": len(formatted)}

    except Exception as e:
        return {"error": f"Error en búsqueda web: {str(e)}", "results": []}
