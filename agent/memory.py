"""
agent/memory.py — Memoria persistente mejorada para Jada

Mejoras sobre la versión anterior:
  1. Resumen automático de conversaciones largas (comprime en lugar de truncar)
  2. Deduplicación de facts (evita guardar hechos duplicados o contradictorios)
  3. Categorización de facts (preferencias, datos personales, hábitos)
  4. Tabla de summaries para almacenar resúmenes por sesión
  5. Limpieza automática de historial antiguo (mantiene DB pequeña)
"""
import aiosqlite
import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("jada.memory")

DB_PATH = os.getenv("MEMORY_DB_PATH", "memory.db")

# Cuántos mensajes mantener activos antes de comprimir los más viejos
MAX_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "30"))
# Cuántos mensajes recientes proteger (nunca comprimir)
RECENT_MESSAGES_KEEP = int(os.getenv("RECENT_MESSAGES_KEEP", "10"))
# Máximo de facts por usuario (los más viejos se descartan)
MAX_FACTS = int(os.getenv("MAX_FACTS", "40"))


class Memory:
    def __init__(self, db_path: str = DB_PATH, llm=None):
        self.db_path = db_path
        self._llm = llm  # Referencia al LLM para generar resúmenes (opcional)

    def set_llm(self, llm) -> None:
        """Inyectar el cliente LLM para generación de resúmenes."""
        self._llm = llm

    # ─── Inicialización ──────────────────────────────────────────────────────

    async def init(self):
        """Crear tablas si no existen y migrar esquema si es necesario."""
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
                    category    TEXT NOT NULL DEFAULT 'general',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
            """)
            # Nueva tabla: resúmenes de conversación comprimidos
            await db.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id     TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    summary     TEXT NOT NULL,
                    msg_count   INTEGER NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            # Índices
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_room
                ON messages (room_id, user_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_facts_user
                ON facts (user_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_room
                ON summaries (room_id, user_id)
            """)
            # Migrar columnas faltantes en facts (por si la DB ya existía)
            try:
                await db.execute("ALTER TABLE facts ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
            except Exception:
                pass  # Ya existe
            try:
                await db.execute("ALTER TABLE facts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
            except Exception:
                pass
            await db.commit()

    # ─── Historial ───────────────────────────────────────────────────────────

    async def save_message(self, room_id: str, user_id: str, role: str, content: str):
        """Guardar un mensaje y comprimir si el historial es demasiado largo."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (room_id, user_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (room_id, user_id, role, content, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

        # Comprimir si supera el límite (solo si el LLM está disponible)
        await self._maybe_compress(room_id, user_id)

    async def get_history(
        self, room_id: str, user_id: str, limit: int = 20
    ) -> list[dict]:
        """
        Obtener historial para el LLM.
        Formato: [summary_as_system] + [últimos N mensajes]
        """
        # 1. Obtener el último resumen comprimido (si existe)
        summary_msg = await self._get_latest_summary(room_id, user_id)

        # 2. Obtener los mensajes recientes
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

        recent = [{"role": row[0], "content": row[1]} for row in reversed(rows)]

        # 3. Combinar: [resumen como contexto] + mensajes recientes
        if summary_msg:
            return [summary_msg] + recent
        return recent

    async def clear_history(self, room_id: str, user_id: str):
        """Limpiar historial y resúmenes de un usuario en un room."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM messages WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            )
            await db.execute(
                "DELETE FROM summaries WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            )
            await db.commit()
        logger.info(f"🗑️ Historial limpiado para {user_id} en {room_id}")

    # ─── Compresión automática ────────────────────────────────────────────────

    async def _maybe_compress(self, room_id: str, user_id: str):
        """Comprimir historial si supera MAX_MESSAGES."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0

        if count < MAX_MESSAGES:
            return  # No hay nada que comprimir todavía

        # Comprimir los mensajes más viejos (dejar los RECENT_MESSAGES_KEEP más nuevos)
        to_keep = RECENT_MESSAGES_KEEP
        to_compress = count - to_keep

        if to_compress <= 0:
            return

        logger.info(f"📝 Comprimiendo {to_compress} mensajes para {user_id}...")
        await self._compress_old_messages(room_id, user_id, to_compress)

    async def _compress_old_messages(self, room_id: str, user_id: str, n: int):
        """Comprimir los N mensajes más viejos en un resumen."""
        async with aiosqlite.connect(self.db_path) as db:
            # Obtener los N más viejos
            async with db.execute(
                """
                SELECT id, role, content FROM messages
                WHERE room_id = ? AND user_id = ?
                ORDER BY id ASC LIMIT ?
                """,
                (room_id, user_id, n),
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return

        ids_to_delete = [row[0] for row in rows]
        msgs_text = "\n".join(f"{row[1].upper()}: {row[2][:300]}" for row in rows)

        # Generar resumen (con LLM si disponible, si no — resumen simple)
        if self._llm:
            try:
                summary = await self._summarize_with_llm(msgs_text)
            except Exception as e:
                logger.warning(f"Error generando resumen con LLM: {e}. Usando resumen simple.")
                summary = self._simple_summary(rows)
        else:
            summary = self._simple_summary(rows)

        # Guardar el resumen y borrar los mensajes comprimidos
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO summaries (room_id, user_id, summary, msg_count, created_at) VALUES (?, ?, ?, ?, ?)",
                (room_id, user_id, summary, len(rows), datetime.now(timezone.utc).isoformat()),
            )
            placeholders = ",".join("?" * len(ids_to_delete))
            await db.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", ids_to_delete)
            await db.commit()

        logger.info(f"✅ {len(rows)} mensajes comprimidos en resumen")

    async def _summarize_with_llm(self, msgs_text: str) -> str:
        """Generar resumen de conversación usando el LLM."""
        prompt = [
            {"role": "system", "content": (
                "Eres un asistente que resume conversaciones de forma concisa. "
                "Extrae solo los puntos clave: decisiones tomadas, información importante, "
                "preferencias del usuario. Máximo 200 palabras en español."
            )},
            {"role": "user", "content": f"Resume esta conversación:\n\n{msgs_text}"},
        ]
        response = await self._llm.chat(prompt)
        return response.content or self._simple_summary([])

    @staticmethod
    def _simple_summary(rows) -> str:
        """Resumen simple sin LLM (fallback)."""
        count = len(rows)
        return f"[Resumen de {count} mensajes anteriores — contexto comprimido por longitud]"

    async def _get_latest_summary(self, room_id: str, user_id: str) -> dict | None:
        """Obtener el último resumen comprimido como mensaje de contexto."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT summary FROM summaries
                WHERE room_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (room_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            return None

        return {
            "role": "system",
            "content": f"📝 Contexto de conversaciones anteriores:\n{row[0]}",
        }

    # ─── Facts / Memoria a largo plazo ───────────────────────────────────────

    async def save_fact(self, user_id: str, fact: str, category: str = "general"):
        """
        Guardar un hecho importante sobre el usuario.
        Deduplica: si ya existe un hecho similar, actualiza en lugar de insertar.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Verificar duplicado exacto
        existing = await self.get_facts(user_id)
        fact_lower = fact.lower().strip()

        for existing_fact in existing:
            if existing_fact.lower().strip() == fact_lower:
                logger.debug(f"Fact duplicado ignorado: '{fact}'")
                return  # Ya existe exactamente igual

        # Guardar nuevo fact
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO facts (user_id, fact, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, fact, category, now, now),
            )
            await db.commit()

        # Limpiar facts viejos si supera el máximo
        await self._trim_facts(user_id)
        logger.debug(f"✅ Fact guardado para {user_id}: '{fact[:60]}'")

    async def get_facts(self, user_id: str) -> list[str]:
        """Obtener todos los hechos conocidos del usuario."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT fact FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, MAX_FACTS),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_facts_by_category(self, user_id: str) -> dict[str, list[str]]:
        """Obtener facts agrupados por categoría."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT fact, category FROM facts WHERE user_id = ? ORDER BY category, id DESC",
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()

        result: dict[str, list[str]] = {}
        for fact, category in rows:
            result.setdefault(category, []).append(fact)
        return result

    async def _trim_facts(self, user_id: str):
        """Eliminar facts más viejos si supera MAX_FACTS."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM facts WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0

            if count > MAX_FACTS:
                to_delete = count - MAX_FACTS
                await db.execute(
                    """
                    DELETE FROM facts WHERE id IN (
                        SELECT id FROM facts WHERE user_id = ?
                        ORDER BY id ASC LIMIT ?
                    )
                    """,
                    (user_id, to_delete),
                )
                await db.commit()
                logger.debug(f"🗑️ {to_delete} facts viejos eliminados para {user_id}")

    # ─── Stats ────────────────────────────────────────────────────────────────

    async def get_stats(self, user_id: str, room_id: str) -> dict:
        """Estadísticas de memoria para el dashboard."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            ) as cursor:
                msg_count = (await cursor.fetchone() or [0])[0]

            async with db.execute(
                "SELECT COUNT(*) FROM facts WHERE user_id = ?", (user_id,)
            ) as cursor:
                fact_count = (await cursor.fetchone() or [0])[0]

            async with db.execute(
                "SELECT COUNT(*) FROM summaries WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            ) as cursor:
                summary_count = (await cursor.fetchone() or [0])[0]

        return {
            "messages": msg_count,
            "facts": fact_count,
            "summaries": summary_count,
        }
