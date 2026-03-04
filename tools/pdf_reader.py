"""
tools/pdf_reader.py — Leer y analizar archivos PDF.

Extrae texto de PDFs; para PDFs basados en imagen (planos, escaneos),
convierte páginas a imágenes para análisis con visión.
"""
import os
import logging
import asyncio
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_PAGES_TEXT = 30              # Máx páginas para extracción de texto
MAX_PAGES_VISION = 3             # Máx páginas para renderizar como imagen
MAX_TEXT_CHARS = 8000            # Truncar texto extraído


def _extract_text_sync(file_path: str, max_pages: int = MAX_PAGES_TEXT) -> dict:
    """Extrae texto de un PDF usando PyMuPDF."""
    try:
        import pymupdf

        p = Path(file_path).resolve()
        if not p.exists():
            return {"error": f"Archivo no encontrado: {file_path}"}
        if p.stat().st_size > MAX_PDF_SIZE:
            return {"error": f"PDF muy grande ({p.stat().st_size / 1024 / 1024:.1f}MB, máx 50MB)"}

        doc = pymupdf.open(str(p))
        total_pages = len(doc)
        pages_to_read = min(total_pages, max_pages)

        all_text = []
        for i in range(pages_to_read):
            page = doc[i]
            text = page.get_text()
            if text.strip():
                all_text.append(f"--- Página {i + 1} ---\n{text.strip()}")

        doc.close()

        full_text = "\n\n".join(all_text)
        truncated = False
        if len(full_text) > MAX_TEXT_CHARS:
            full_text = full_text[:MAX_TEXT_CHARS] + "\n... [texto truncado]"
            truncated = True

        return {
            "success": True,
            "file": p.name,
            "total_pages": total_pages,
            "pages_read": pages_to_read,
            "text": full_text if full_text else "(Sin texto extraíble — probablemente es un PDF de imágenes/escaneo)",
            "has_text": bool(full_text.strip()),
            "truncated": truncated,
        }
    except Exception as e:
        logger.error(f"Error leyendo PDF: {e}")
        return {"error": f"Error leyendo PDF: {str(e)}"}


def _render_pages_sync(file_path: str, max_pages: int = MAX_PAGES_VISION,
                       dpi: int = 150) -> dict:
    """Renderiza páginas de PDF como imágenes PNG para análisis con visión."""
    try:
        import pymupdf

        p = Path(file_path).resolve()
        if not p.exists():
            return {"error": f"Archivo no encontrado: {file_path}"}

        doc = pymupdf.open(str(p))
        total_pages = len(doc)
        pages_to_render = min(total_pages, max_pages)

        output_dir = "/tmp/jada_pdf_pages"
        os.makedirs(output_dir, exist_ok=True)

        image_paths = []
        zoom = dpi / 72  # 72 DPI is default
        mat = pymupdf.Matrix(zoom, zoom)

        for i in range(pages_to_render):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(output_dir, f"{p.stem}_p{i + 1}.png")
            pix.save(img_path)
            image_paths.append(img_path)

        doc.close()

        return {
            "success": True,
            "file": p.name,
            "total_pages": total_pages,
            "rendered_pages": pages_to_render,
            "image_paths": image_paths,
        }
    except Exception as e:
        logger.error(f"Error renderizando PDF: {e}")
        return {"error": f"Error renderizando PDF: {str(e)}"}


# ─── Async wrappers ─────────────────────────────────────────────────────────

async def read_pdf(file_path: str, max_pages: int = MAX_PAGES_TEXT) -> dict:
    """Extrae texto de un archivo PDF."""
    return await asyncio.to_thread(_extract_text_sync, file_path, max_pages)


async def render_pdf_pages(file_path: str, max_pages: int = MAX_PAGES_VISION) -> dict:
    """Renderiza páginas de un PDF como imágenes PNG."""
    return await asyncio.to_thread(_render_pages_sync, file_path, max_pages)
