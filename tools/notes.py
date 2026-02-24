"""
tools/notes.py — CRUD de notas personales en SQLite
"""
import aiosqlite
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Usa la misma DB de memoria para centralizar
NOTES_DB_PATH = os.getenv("MEMORY_DB_PATH", "memory.db")


class NotesDB:
    def __init__(self, db_path: str = NOTES_DB_PATH):
        self.db_path = db_path

    async def init(self):
        """Crear tabla de notas si no existe."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    tags        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_user
                ON notes (user_id)
            """)
            await db.commit()

    async def save_note(self, user_id: str, title: str, content: str, tags: str = "") -> dict:
        """Crear o actualizar una nota."""
        try:
            now = datetime.utcnow().isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """INSERT INTO notes (user_id, title, content, tags, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user_id, title, content, tags, now, now),
                )
                note_id = cursor.lastrowid
                await db.commit()
            return {"success": True, "note_id": note_id, "title": title}
        except Exception as e:
            return {"error": str(e)}

    async def get_notes(self, user_id: str, limit: int = 20) -> dict:
        """Listar las notas del usuario."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT id, title, tags, created_at, updated_at
                       FROM notes WHERE user_id = ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (user_id, limit),
                ) as cursor:
                    rows = [dict(row) for row in await cursor.fetchall()]
            return {"notes": rows, "count": len(rows)}
        except Exception as e:
            return {"error": str(e)}

    async def search_notes(self, user_id: str, query: str) -> dict:
        """Buscar notas por título, contenido o tags."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT id, title, content, tags, updated_at
                       FROM notes WHERE user_id = ?
                       AND (LOWER(title) LIKE LOWER(?) OR LOWER(content) LIKE LOWER(?) OR LOWER(tags) LIKE LOWER(?))
                       ORDER BY updated_at DESC LIMIT 10""",
                    (user_id, f"%{query}%", f"%{query}%", f"%{query}%"),
                ) as cursor:
                    rows = [dict(row) for row in await cursor.fetchall()]
            return {"query": query, "results": rows, "count": len(rows)}
        except Exception as e:
            return {"error": str(e)}

    async def delete_note(self, user_id: str, note_id: int) -> dict:
        """Eliminar una nota por ID."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM notes WHERE id = ? AND user_id = ?",
                    (note_id, user_id),
                )
                await db.commit()
                if cursor.rowcount == 0:
                    return {"error": f"Nota #{note_id} no encontrada"}
            return {"success": True, "deleted_id": note_id}
        except Exception as e:
            return {"error": str(e)}
