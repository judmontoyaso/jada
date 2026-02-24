"""
tools/browser.py — Control de browser con Playwright (headless/headed)
"""
import os
import base64
from playwright.async_api import async_playwright, Browser, Page
from dotenv import load_dotenv

load_dotenv()

HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"


class BrowserTool:
    """Singleton-like browser controller. Un solo browser compartido."""

    _instance: "BrowserTool | None" = None

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    @classmethod
    async def get_instance(cls) -> "BrowserTool":
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance._start()
        return cls._instance

    async def _start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=HEADLESS)
        self._page = await self._browser.new_page()

    async def navigate(self, url: str) -> dict:
        """Navegar a una URL."""
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return {"success": True, "url": self._page.url, "title": await self._page.title()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_page_text(self, max_chars: int = 3000) -> dict:
        """Extraer texto visible de la página actual."""
        try:
            text = await self._page.inner_text("body")
            return {
                "url": self._page.url,
                "text": text[:max_chars],
                "truncated": len(text) > max_chars,
            }
        except Exception as e:
            return {"error": str(e)}

    async def click(self, selector: str) -> dict:
        """Hacer click en un elemento (CSS selector o texto)."""
        try:
            await self._page.click(selector, timeout=5000)
            return {"success": True, "selector": selector}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def fill(self, selector: str, text: str) -> dict:
        """Rellenar un campo de formulario."""
        try:
            await self._page.fill(selector, text, timeout=5000)
            return {"success": True, "selector": selector}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def screenshot(self) -> dict:
        """Capturar screenshot de la página actual (base64 PNG)."""
        try:
            screenshot_bytes = await self._page.screenshot(type="png")
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return {"success": True, "image_base64": b64, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_current_url(self) -> dict:
        return {"url": self._page.url if self._page else "No page open"}

    async def close(self):
        """Cerrar el browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        BrowserTool._instance = None
