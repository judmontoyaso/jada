"""
agent/playbook.py — ACE-lite: Aprendizaje incremental para Jada

Basado en el ACE Framework (Stanford, 2026).
Después de cada interacción con tools, analiza si hubo algo que aprender
y lo agrega al playbook como delta updates (nunca reescribe).

El playbook se inyecta en el system prompt como bullets de contexto.
"""
import json
import logging
import os
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PLAYBOOK_PATH = Path(__file__).parent.parent / "data" / "playbook.json"
MAX_ENTRIES = 50
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_FUNCTION_MODEL = os.getenv("NVIDIA_FUNCTION_MODEL", "minimaxai/minimax-m2.5")

REFLECTION_PROMPT = """Eres un analista de interacciones de un asistente de IA llamado Jada.
Analiza esta interacción y decide si hay algo que aprender.

SOLO genera lecciones si:
- El usuario corrigió a Jada
- Jada cometió un error o malinterpretó algo
- Se descubrió una preferencia del usuario
- Un tool falló y se encontró un workaround
- Se encontró un patrón útil para futuras interacciones

Si la interacción fue rutinaria (saludo, consulta simple exitosa), responde: {"lecciones": []}

Responde SOLO en JSON:
{"lecciones": [{"estrategia": "qué hacer", "cuando_usar": "en qué situación", "importancia": "alta|media|baja"}]}"""


class PlaybookManager:
    """Gestiona el playbook de aprendizaje incremental (ACE-lite)."""

    def __init__(self):
        self.entries: list[dict] = []
        self._loaded = False

    def _load(self):
        """Cargar playbook desde disco."""
        if self._loaded:
            return
        try:
            if PLAYBOOK_PATH.exists():
                self.entries = json.loads(PLAYBOOK_PATH.read_text())
                logger.info(f"📖 Playbook cargado: {len(self.entries)} entries")
        except Exception as e:
            logger.warning(f"⚠️ Error cargando playbook: {e}")
            self.entries = []
        self._loaded = True

    def _save(self):
        """Guardar playbook a disco."""
        try:
            PLAYBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
            PLAYBOOK_PATH.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"⚠️ Error guardando playbook: {e}")

    def get_context(self, max_entries: int = 15) -> str:
        """Devuelve bullets del playbook para inyectar en el system prompt."""
        self._load()
        if not self.entries:
            return ""

        # Priorizar alta > media > baja, luego por recencia
        sorted_entries = sorted(
            self.entries,
            key=lambda e: (
                {"alta": 3, "media": 2, "baja": 1}.get(e.get("importancia", "media"), 2),
                e.get("added_at", ""),
            ),
            reverse=True,
        )[:max_entries]

        bullets = []
        for e in sorted_entries:
            imp = e.get("importancia", "?").upper()
            estrategia = e.get("estrategia", "")
            cuando = e.get("cuando_usar", "")
            bullets.append(f"• [{imp}] {estrategia}" + (f" → Cuando: {cuando}" if cuando else ""))

        return "\n".join(bullets)

    async def maybe_learn(self, user_input: str, tool_names: list[str], response: str):
        """Analiza la interacción y extrae lecciones si las hay (background)."""
        self._load()

        # Solo analizar si hubo tool calls (no chat puro)
        if not tool_names:
            return

        # No analizar si la respuesta es muy corta (probablemente OK)
        if len(response) < 30:
            return

        try:
            interaction = (
                f"Usuario: {user_input[:200]}\n"
                f"Tools usadas: {', '.join(tool_names)}\n"
                f"Respuesta de Jada: {response[:300]}"
            )

            headers = {
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": NVIDIA_FUNCTION_MODEL,
                "messages": [
                    {"role": "system", "content": REFLECTION_PROMPT},
                    {"role": "user", "content": interaction},
                ],
                "max_tokens": 300,
                "temperature": 0.1,
            }

            # Ejecutar en thread para no bloquear
            resp = await asyncio.to_thread(
                lambda: requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    json=payload, headers=headers, timeout=30,
                )
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            # Limpiar posible markdown
            if "```" in content:
                import re
                content = re.sub(r'```json\s*', '', content)
                content = re.sub(r'```\s*', '', content)

            data = json.loads(content.strip())
            lecciones = data.get("lecciones", [])

            if not lecciones:
                return

            for leccion in lecciones:
                self._add_lesson(leccion)

            self._save()
            logger.info(f"📖 Playbook actualizado: +{len(lecciones)} lección(es), total={len(self.entries)}")

        except Exception as e:
            logger.debug(f"Playbook learn failed (non-critical): {e}")

    def _add_lesson(self, lesson: dict):
        """Delta append: agrega lección nueva o refina existente."""
        estrategia = lesson.get("estrategia", "")
        if not estrategia:
            return

        # Buscar duplicado por keywords
        words = set(estrategia.lower().split()[:5])
        for i, existing in enumerate(self.entries):
            existing_words = set(existing.get("estrategia", "").lower().split()[:5])
            overlap = len(words & existing_words)
            if overlap >= 3:  # Similar enough → refine
                self.entries[i]["refinamientos"] = self.entries[i].get("refinamientos", 0) + 1
                if lesson.get("importancia") == "alta":
                    self.entries[i].update(lesson)
                self.entries[i]["updated_at"] = datetime.now().isoformat()
                return

        # Nuevo entry
        lesson["added_at"] = datetime.now().isoformat()
        lesson["refinamientos"] = 0
        self.entries.append(lesson)

        # Podar si excede max
        if len(self.entries) > MAX_ENTRIES:
            # Eliminar las de baja importancia y más antiguas
            self.entries.sort(
                key=lambda e: (
                    {"alta": 3, "media": 2, "baja": 1}.get(e.get("importancia", "media"), 2),
                    e.get("refinamientos", 0),
                ),
            )
            self.entries = self.entries[-(MAX_ENTRIES):]


# Singleton
playbook_manager = PlaybookManager()
