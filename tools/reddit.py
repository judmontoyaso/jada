"""
tools/reddit.py — Consultar Reddit usando RSS feeds (sin auth, sin bloqueos).

Reddit bloquea la API JSON desde IPs de servidores, pero los RSS feeds funcionan.
"""
import asyncio
import logging
import xml.etree.ElementTree as ET
from html import unescape
import re

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "Jada/1.0 (personal assistant bot)"
BASE = "https://www.reddit.com"
TIMEOUT = 15

# Namespace para Atom feeds de Reddit
NS = {"atom": "http://www.w3.org/2005/Atom"}


def _get_rss(endpoint: str) -> str:
    """GET al RSS feed de Reddit."""
    url = f"{BASE}{endpoint}"
    if not url.endswith(".rss"):
        url += ".rss"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _clean_html(text: str) -> str:
    """Limpia HTML básico del contenido RSS."""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:300] if text else ""


def _parse_rss(xml_text: str, limit: int = 10) -> list[dict]:
    """Parsea el RSS de Reddit (formato Atom)."""
    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", NS)
    posts = []
    for entry in entries[:limit]:
        title = entry.findtext("atom:title", "", NS)
        link = entry.findtext("atom:link", "", NS)
        # El link está en el atributo href
        link_elem = entry.find("atom:link", NS)
        url = link_elem.get("href", "") if link_elem is not None else ""
        author = entry.findtext("atom:author/atom:name", "", NS)
        content = entry.findtext("atom:content", "", NS)
        updated = entry.findtext("atom:updated", "", NS)
        category = entry.findtext("atom:category", "", NS)
        cat_elem = entry.find("atom:category", NS)
        subreddit = cat_elem.get("label", "") if cat_elem is not None else ""

        posts.append({
            "title": title,
            "subreddit": f"r/{subreddit}" if subreddit and not subreddit.startswith("r/") else (subreddit or ""),
            "url": url,
            "author": author.replace("/u/", "") if author else "",
            "updated": updated,
            "preview": _clean_html(content),
        })
    return posts


# ─── Funciones públicas (async) ─────────────────────────────────────────────

async def reddit_trending(limit: int = 10) -> list[dict]:
    """Posts trending globales (r/popular)."""
    xml = await asyncio.to_thread(_get_rss, "/r/popular/.rss")
    return _parse_rss(xml, limit)


async def reddit_subreddit(subreddit: str, sort: str = "hot",
                           limit: int = 10) -> list[dict]:
    """Posts de un subreddit específico.

    sort: hot, new, top, rising
    """
    endpoint = f"/r/{subreddit}/{sort}.rss" if sort != "hot" else f"/r/{subreddit}.rss"
    xml = await asyncio.to_thread(_get_rss, endpoint)
    return _parse_rss(xml, limit)


async def reddit_search(query: str, subreddit: str = "",
                        limit: int = 10) -> list[dict]:
    """Busca posts en Reddit por palabras clave."""
    if subreddit:
        endpoint = f"/r/{subreddit}/search.rss?q={query}&restrict_sr=on&limit={limit}"
    else:
        endpoint = f"/search.rss?q={query}&limit={limit}"
    xml = await asyncio.to_thread(
        lambda: requests.get(
            f"{BASE}{endpoint}",
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        ).text
    )
    return _parse_rss(xml, limit)
