"""
tools/web_search.py — Búsqueda web usando DuckDuckGo (sin API key)
"""
from ddgs import DDGS


async def search(query: str, max_results: int = 5, search_type: str = "text") -> dict:
    """
    Busca en la web usando DuckDuckGo y retorna una lista de resultados.
    Si search_type="news", busca artículos de noticias recientes con fechas.
    No requiere API key.
    """
    if "noticia" in query.lower() and search_type == "text":
        search_type = "news"

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
                
                formatted = []
                for item in root.findall(".//item")[:max_results]:
                    formatted.append({
                        "title": item.findtext("title", ""),
                        "url": item.findtext("link", ""),
                        "snippet": item.findtext("description", ""),
                        "date": item.findtext("pubDate", ""),
                        "source": item.findtext("source", "")
                    })
            except Exception as e:
                return {"error": f"Error leyendo Google News RSS: {str(e)}", "results": []}

        else:
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

        return {"query": query, "type": search_type, "results": formatted, "count": len(formatted)}

    except Exception as e:
        return {"error": f"Error en búsqueda web: {str(e)}", "results": []}
