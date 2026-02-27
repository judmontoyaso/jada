"""
agent/heartbeat.py — Voz proactiva de Jada

Lee .agent/heartbeat.md para configuración, usa el LLM para decidir
si hablar y qué decir. Se integra con el scheduler como un cronjob especial.
"""
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jada.heartbeat")

HEARTBEAT_CONFIG_FILE = Path(__file__).parent.parent / ".agent" / "heartbeat.md"


def _parse_heartbeat_config() -> dict:
    """Lee heartbeat.md y extrae configuración y texto de tono."""
    defaults = {
        "enabled": True,
        "cron_expr": "0 */2 * * *",
        "room_id": "",
        "speak_probability": 60,
        "tone_text": "",
    }
    if not HEARTBEAT_CONFIG_FILE.exists():
        return defaults

    content = HEARTBEAT_CONFIG_FILE.read_text(encoding="utf-8")

    def _get(key: str, default):
        m = re.search(rf"{key}:\s*(.+)", content)
        return m.group(1).strip().strip('"').strip("'") if m else default

    enabled_str = _get("enabled", "true").lower()

    # Extraer la sección de tono para pasarla al LLM
    tone_text = ""
    tone_match = re.search(r"## Tono del heartbeat(.+?)(?=##|$)", content, re.DOTALL)
    if tone_match:
        tone_text = tone_match.group(1).strip()

    return {
        "enabled": enabled_str not in ("false", "0", "no"),
        "cron_expr": _get("cron_expr", defaults["cron_expr"]),
        "room_id": _get("room_id", defaults["room_id"]).strip('"').strip("'"),
        "speak_probability": int(_get("speak_probability", 60)),
        "tone_text": tone_text,
    }


def _build_heartbeat_prompt(action_type: str, tone_text: str = "") -> str:
    """Construye el prompt para el heartbeat según el tipo de acción."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.strftime("%A")

    # Cargar soul.md para que el LLM mantenga la personalidad de Jada
    soul_path = Path(__file__).parent.parent / ".agent" / "soul.md"
    soul_text = ""
    if soul_path.exists():
        try:
            soul_text = soul_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    time_ctx = f"Son las {hour}:00 UTC, {weekday}."

    base = (
        f"Eres Jada. Tu personalidad:\n{soul_text}\n\n"
        f"Guías de tono para mensajes proactivos:\n{tone_text}\n\n"
        f"{time_ctx} Vas a enviar un mensaje proactivo a Juan. "
        f"Debe sentirse NATURAL, no como notificación automática. "
        f"Máximo 2-3 líneas. Sin saludos formales."
    ) if soul_text or tone_text else (
        f"Eres Jada, un agente de IA con humor negro y personalidad directa. "
        f"{time_ctx} Vas a enviar un mensaje proactivo al usuario (Juan). "
        f"Debe sentirse natural. Máximo 2-3 líneas. Sin saludos formales."
    )

    actions = {
        "joke": (
            f"{base}\n\nAcción: haz un chiste oscuro, técnico o sarcástico. "
            "Programación, IA, la muerte, el gym, o la vida. "
            "Bueno o tan malo que dé risa."
        ),
        "advice": (
            f"{base}\n\nAcción: da un consejo útil y directo. "
            "Productividad, salud, código, hábitos. Consejo + razón breve. Sin sermones."
        ),
        "question": (
            f"{base}\n\nAcción: haz una pregunta interesante o útil a Juan. "
            "Un proyecto, un hábito, algo que mencionó antes. Una sola pregunta. Directa."
        ),
        "observation": (
            f"{base}\n\nAcción: haz una observación sobre algo (el día, la semana, un patrón, algo random). "
            "Tono entre filosófico y sarcástico."
        ),
    }

    return actions.get(action_type, actions["observation"])


async def run_heartbeat(llm, send_callback, room_id: str) -> None:
    """
    Ejecuta un ciclo del heartbeat:
    1. Lee config de heartbeat.md
    2. Decide si hablar (por probabilidad)
    3. Elige tipo de acción
    4. Genera mensaje con el LLM
    5. Lo envía al room
    """
    config = _parse_heartbeat_config()

    if not config["enabled"]:
        logger.debug("Heartbeat desactivado en heartbeat.md")
        return

    # Usar room_id del config si no se pasa uno
    target_room = room_id or config["room_id"]
    if not target_room:
        logger.warning("Heartbeat: sin room_id configurado")
        return

    # Probabilidad de hablar
    prob = config["speak_probability"]
    roll = random.randint(1, 100)
    if roll > prob:
        logger.debug(f"Heartbeat: silencio esta vez (roll={roll} > prob={prob})")
        return

    # Elegir tipo de acción con pesos
    action_weights = {"joke": 25, "advice": 30, "question": 20, "observation": 15, "silence": 10}
    actions = list(action_weights.keys())
    weights = list(action_weights.values())
    action = random.choices(actions, weights=weights, k=1)[0]

    if action == "silence":
        logger.debug("Heartbeat: acción = silence")
        return

    logger.info(f"💓 Heartbeat activado — acción: {action}")

    # Generar mensaje con LLM (con soul + tono del heartbeat.md)
    try:
        prompt = _build_heartbeat_prompt(action, tone_text=config.get("tone_text", ""))
        response = await llm.chat([
            {"role": "system", "content": prompt},
            {"role": "user", "content": "go"},
        ])
        message = response.content
        if message:
            message = re.sub(r'<think>.*?</think>', '', message, flags=re.DOTALL).strip()
    except Exception as e:
        logger.error(f"Heartbeat: error generando mensaje: {e}")
        return

    if not message:
        return

    # Enviar al room
    try:
        await send_callback(target_room, message)
        logger.info(f"💓 Heartbeat enviado al room {target_room}")
    except Exception as e:
        logger.error(f"Heartbeat: error enviando mensaje: {e}")
