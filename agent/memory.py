"""
agent/memory.py — Memoria persistente con SQLite (historial + hechos del usuario)
"""
import aiosqlite
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("MEMORY_DB_PATH", "memory.db")
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "8000"))


class Memory:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def init(self):
        """Crear tablas si no existen."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id     TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    timestamp   TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT NOT NULL,
                    fact        TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_room
                ON messages (room_id, user_id)
            """)
            await db.commit()

    async def save_message(self, room_id: str, user_id: str, role: str, content: str):
        """Guardar un mensaje en el historial."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (room_id, user_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (room_id, user_id, role, content, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_history(
        self, room_id: str, user_id: str, limit: int = 20
    ) -> list[dict]:
        """
        Obtener los últimos N mensajes del historial.
        Trunca desde los más antiguos si el total de chars supera MAX_HISTORY_CHARS.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT role, content FROM messages
                WHERE room_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (room_id, user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()

        # Orden cronológico
        messages = [{"role": row[0], "content": row[1]} for row in reversed(rows)]

        # Truncar por límite de caracteres (desde los más antiguos)
        if MAX_HISTORY_CHARS > 0:
            total_chars = sum(len(m["content"]) for m in messages)
            while messages and total_chars > MAX_HISTORY_CHARS:
                removed = messages.pop(0)
                total_chars -= len(removed["content"])

        return messages

    async def save_fact(self, user_id: str, fact: str):
        """Guardar un hecho importante sobre el usuario."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO facts (user_id, fact, created_at) VALUES (?, ?, ?)",
                (user_id, fact, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_facts(self, user_id: str) -> list[str]:
        """Obtener todos los hechos conocidos del usuario."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT fact FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def clear_history(self, room_id: str, user_id: str):
        """Limpiar el historial de un usuario en un room."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM messages WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            )
            await db.commit()
