"""
agent/agent.py — Loop principal del agente (Agno nativo)
"""
import os
import re
import logging
from datetime import date
from pathlib import Path

from typing import Any
from dotenv import load_dotenv

from agno.agent import Agent as AgnoAgent
from agno.models.nvidia import Nvidia
from agno.db.sqlite import SqliteDb

from agent.tools_registry import JadaTools
from tools.gym_parser import expand_gym_notation

load_dotenv()

AGENT_NAME = os.getenv("AGENT_NAME", "Jada")
PRIMARY_MODEL = os.getenv("NVIDIA_MODEL", "moonshotai/kimi-k2-thinking")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

logger = logging.getLogger("jada")

# ─── Cargar archivos de identidad (.agent/*.md) ──────────────────────────────
MAX_IDENTITY_CHARS = 8000

def _load_identity_files() -> str:
    """Cargar soul.md y user.md completos para el contexto de identidad."""
    agent_dir = Path(__file__).parent.parent / ".agent"
    sections = []

    for filename in ["soul.md", "user.md"]:
        filepath = agent_dir / filename
        if filepath.exists():
            try:
                content = filepath.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(content)
            except Exception:
                pass

    text = "\n\n---\n\n".join(sections)
    if len(text) > MAX_IDENTITY_CHARS:
        text = text[:MAX_IDENTITY_CHARS].rsplit("\n", 1)[0]
    return text

IDENTITY_CONTEXT = _load_identity_files()

SYSTEM_PROMPT = os.getenv(
    "AGENT_SYSTEM_PROMPT",
    f"Eres {AGENT_NAME}, un agente de IA personal. Tu identidad, personalidad y estilo vienen definidos en tu soul.md (más abajo). "
    "Tienes acceso a herramientas reales. "
    "REGLAS CRÍTICAS (no negociables):\n"
    "1. SIEMPRE usa las herramientas disponibles para ejecutar acciones. NUNCA simules ni inventes resultados.\n"
    "2. NUNCA digas 'no tengo acceso a X' si la herramienta existe en tu lista. Si está en la lista, Úsala.\n"
    "3. Para correo: llamar email_list / email_read / email_search. Siempre.\n"
    "4. Para calendario: llamar calendar_today / calendar_upcoming. Siempre.\n"
    "5. Para tareas programadas (cronjobs): FLUJO OBLIGATORIO: primero cronjob_list para obtener el job_id, "
    "luego cronjob_delete / cronjob_update / cronjob_run_now con ese id.\n"
    "6. Para gym: gym_save_workout con el texto EXACTO del usuario en 'ejercicios_raw'.\n"
    "8. Para enviar emails: usa email_send.\n"
    "9. Para noticias: SIEMPRE usa web_search con una query relevante. NUNCA inventes URLs ni resultados genéricos. Si no sabes, dinos: 'No encontré'.\n"
    "10. Para clima o temperatura: usa get_weather.\n"
    "11. Para agendar reuniones o eventos en Google Calendar: Pide título y hora (ej: 'Reunión de equipo a las 3pm'), luego calcula la fecha/hora en ISO 8601 basado en la hora local y SIEMPRE usa calendar_add_event. No asumas éxito sin el JSON.\n"
    "-----------\n"
    "== REGLA DE TOLERANCIA CERO A ALUCINACIONES DE ACCIONES ==\n"
    "NUNCA bajo NINGUNA circunstancia afirmes haber realizado una acción si no llamaste a la herramienta correspondiente y recibiste un JSON de éxito.\n"
    "Si la herramienta falla, di que falló. Si no tienes la herramienta en tu lista actual, di que no puedes hacerlo. NUNCA TE INVENTES RESULTADOS EXISTOSOS (ej: 'Evento agregado al calendario') SI NO HAS USADO LA TOOL.\n"
    "-----------\n"
    "12. Responde en el idioma del usuario.\n"
    "13. Sé conciso. Respuestas cortas cuando sea posible.\n"
    "14. Para TV: samsung_tv_control.\n"
    "PROHIBIDO ABSOLUTO:\n"
    "- Terminar mensajes con '¿Algo más?', '¿Hay algo más en que pueda ayudarte?' o variantes. Nunca.\n"
    "- Decir 'no tengo acceso' a una herramienta que aparece en tu lista.\n"
    "- Inventar resultados de herramientas sin haberlas llamado.",
)

# Build the complete instructions
COMPLETE_INSTRUCTIONS = f"{SYSTEM_PROMPT}\n\n{IDENTITY_CONTEXT}\n\nFecha actual: {date.today().isoformat()}"


class Agent:
    """Wrapper para instanciar agno.agent.Agent e integrar el router de Matrix."""
    def __init__(self, bot: Any = None):
        self._send_callback = None
        self.bot = bot
        self._tools = JadaTools(bot=self.bot)
        
        # SQLite DB automatically created/managed by Agno
        self._memory_db = SqliteDb(
            session_table="sessions",
            db_url="sqlite:///memory.db"
        )
        
        self.agent = AgnoAgent(
            model=Nvidia(
                id=PRIMARY_MODEL,
                api_key=os.getenv("NVIDIA_API_KEY"),
                base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                max_retries=1,
            ),
            description=COMPLETE_INSTRUCTIONS,
            db=self._memory_db,
            add_history_to_context=True,
            num_history_messages=10,
            tools=[self._tools],
            markdown=True
        )

    async def init(self):
        """Inicializa las conexiones a bases de datos y herramientas."""
        await self._tools.init_databases()
        logger.info("✅ Agent Tools & DB inicializado")

    async def run_scheduled(self, prompt: str, room_id: str) -> None:
        """Punto de entrada para cronjobs."""
        logger.info(f"⏰ Ejecutando tarea en room {room_id}: '{prompt[:80]}...'")
        try:
            # Reusar id ficticio para tareas automáticas de cron
            response = await self.chat(prompt, "@scheduler:jada", room_id)
            if self._send_callback:
                await self._send_callback(room_id, response)
        except Exception as e:
            logger.error(f"❌ Error en tarea programada: {e}")

    def set_send_callback(self, callback) -> None:
        """Inyecta el callback de la sesión de Matrix."""
        self._send_callback = callback

    def _strip_thinking(self, text: str) -> str:
        """Eliminar tags <think> que agno ya no filtra en texto raw."""
        if not text:
            return ""
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        cleaned = re.sub(r'<think>.*$', '', cleaned, flags=re.DOTALL)
        return cleaned.strip()

    async def clear_history(self, session_id: str) -> bool:
        """Borra el historial de una sesión (room) específica."""
        try:
            self._memory_db.delete_session(session_id)
            logger.info(f"🗑️ Historial borrado para sesión: {session_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error al borrar historial: {e}")
            return False

    async def chat(self, user_message: str, user_id: str, room_id: str) -> str:
        """
        Punto de entrada principal. El Agno Agent maneja automáticamente
        el loop de ReAct, el RAG de memoria y los Tools.
        """
        # 1. Expand Gym notation
        if re.search(r'\d+x\d+x\d+', user_message) or 'con barra' in user_message.lower():
            original = user_message
            user_message = expand_gym_notation(user_message)
            if user_message != original:
                logger.info(f"🏋️ Notación gym expandida")

        # 2. Inject context directly into JadaTools
        self._tools.user_id = user_id
        self._tools.room_id = room_id
        self._tools.bot = self.bot

        # 3. Use room_id as the session_id to maintain context between the different chats.
        try:
            # Provide user facts programmatically in future iterations if required, 
            # for now memory handles past raw conversation automatically.
            response = await self.agent.arun(
                user_message,
                session_id=room_id
            )
            
            final_text = self._strip_thinking(response.content)
            return final_text or "..."
            
        except Exception as e:
            logger.error(f"❌ Error en Agno Agent: {e}")
            return "⚠️ Ocurrió un error al procesar tu solicitud."
