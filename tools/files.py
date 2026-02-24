"""
tools/files.py — Leer, escribir y listar archivos del sistema
"""
import os
import aiofiles
from pathlib import Path


async def read_file(path: str) -> dict:
    """Leer el contenido de un archivo."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"error": f"Archivo no encontrado: {path}"}
        if not p.is_file():
            return {"error": f"La ruta no es un archivo: {path}"}

        async with aiofiles.open(p, "r", encoding="utf-8", errors="replace") as f:
            content = await f.read()

        return {"path": str(p), "content": content, "size_bytes": p.stat().st_size}
    except Exception as e:
        return {"error": f"Error leyendo archivo: {str(e)}"}


async def write_file(path: str, content: str, append: bool = False) -> dict:
    """Escribir o sobreescribir un archivo."""
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)  # Crear dirs si no existen
        mode = "a" if append else "w"

        async with aiofiles.open(p, mode, encoding="utf-8") as f:
            await f.write(content)

        return {
            "path": str(p),
            "success": True,
            "mode": "append" if append else "overwrite",
            "size_bytes": p.stat().st_size,
        }
    except Exception as e:
        return {"error": f"Error escribiendo archivo: {str(e)}"}


async def list_dir(path: str = ".") -> dict:
    """Listar el contenido de un directorio."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"error": f"Directorio no encontrado: {path}"}
        if not p.is_dir():
            return {"error": f"La ruta no es un directorio: {path}"}

        items = []
        for item in sorted(p.iterdir()):
            items.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size_bytes": item.stat().st_size if item.is_file() else None,
            })

        return {"path": str(p), "items": items, "count": len(items)}
    except Exception as e:
        return {"error": f"Error listando directorio: {str(e)}"}
