"""
agent/agent.py — Loop principal del agente (Agno nativo)
"""
import os
import re
import logging
import asyncio
import json
import time
from datetime import date
from pathlib import Path

from typing import Any, Dict, Optional
from dotenv import load_dotenv

from agno.agent import Agent as AgnoAgent
from agno.models.nvidia import Nvidia
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from agno.media import Image as AgnoImage

from agent.tools_registry import JadaTools
from tools.gym_parser import expand_gym_notation

load_dotenv()

AGENT_NAME = os.getenv("AGENT_NAME", "Jada")
CHAT_MODEL = os.getenv("NVIDIA_CHAT_MODEL", "moonshotai/kimi-k2-thinking")
FUNCTION_MODEL = os.getenv("NVIDIA_FUNCTION_MODEL", "minimax/minimax-m2.5")
VISION_MODEL = os.getenv("NVIDIA_VISION_MODEL", "meta/llama-3.2-11b-vision-instruct")
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

# ─── System Prompt ───────────────────────────────────────────────────────────
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
    "12. Para notas: usa note_save, note_list, note_search. Si vas a guardar una nota, USA la herramienta note_save. NUNCA digas que guardaste algo sin usar la herramienta.\n"
    "-----------\n"
    "== REGLA DE TOLERANCIA CERO A ALUCINACIONES DE ACCIONES ==\n"
    "NUNCA bajo NINGUNA circunstancia afirmes haber realizado una acción si no llamaste a la herramienta correspondiente y recibiste un JSON de éxito.\n"
    "Las notas SIEMPRE se guardan y buscan usando mongo/herramientas (note_list, note_save). NUNCA busques en la base de datos local SQLite (memory.db) usando run_command ni digas al usuario que están ahí.\n"
    "Si la herramienta falla, di que falló. Si no tienes la herramienta en tu lista actual, di que no puedes hacerlo. NUNCA TE INVENTES RESULTADOS EXISTOSOS (ej: 'Evento agregado al calendario' o 'Nota guardada') SI NO HAS USADO LA TOOL.\n"
    "SI UNA HERRAMIENTA DEVUELVE UNA LISTA VACÍA O 0 RESULTADOS, DEBES INFORMAR AL USUARIO EXPLÍCITAMENTE (ej: 'No encontré historial para ese ejercicio'). ESTÁ ESTRICTAMENTE PROHIBIDO DEVOLVER UNA RESPUESTA VACÍA.\n"
    "-----------\n"
    "12. Responde en el idioma del usuario.\n"
    "13. Sé conciso. Respuestas cortas cuando sea posible.\n"
    "14. Para TV: samsung_tv_control.\n"
    "15. Si el usuario te pide un resumen de su día, o solo dice 'jada' o 'resumen', DEBES llamar a email_list(unread_only=False), calendar_today y gym_get_recent ANTES de responder. Asegúrate de verificar los datos reales. NUNCA asumas eventos ni inventes historiales sin usar las herramientas.\n"
    "PROHIBIDO ABSOLUTO:\n"
    "- Terminar mensajes con '¿Algo más?', '¿Hay algo más en que pueda ayudarte?' o variantes. Nunca.\n"
    "- Decir 'no tengo acceso' a una herramienta que aparece en tu lista.\n"
    "- Inventar resultados de herramientas sin haberlas llamado.",
)

import pytz
from datetime import datetime

TIMEZONE = os.getenv("TIMEZONE", "UTC")

def _get_current_time_str() -> str:
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")

COMPLETE_INSTRUCTIONS = f"{SYSTEM_PROMPT}\n\n{IDENTITY_CONTEXT}\n\nFecha y hora actual (Colombia): {_get_current_time_str()}"

class Agent:
    """Wrapper para instanciar agno.agent.Agent e integrar el router de Matrix."""
    def __init__(self, bot: Any = None):
        self._send_callback = None
        self.bot = bot
        self._tools = JadaTools(bot=self.bot)
        self._session_locks: Dict[str, asyncio.Lock] = {}
        
        # SQLite DB automatically created/managed by Agno
        self._memory_db = SqliteDb(
            session_table="sessions",
            db_url="sqlite:///memory.db"
        )
        
        # Instanciar modelos especializados
        self.chat_model = Nvidia(
            id=CHAT_MODEL,
            api_key=os.getenv("NVIDIA_API_KEY"),
            max_retries=1,
            timeout=LLM_TIMEOUT,
        )
        self.function_model = Nvidia(
            id=FUNCTION_MODEL,
            api_key=os.getenv("NVIDIA_API_KEY_SECONDARY") or os.getenv("NVIDIA_API_KEY"),
            max_retries=1,
            timeout=LLM_TIMEOUT * 2, # Minimax suele tardar más procesando tools
        )
        self.vision_model = OpenAIChat(
            id=VISION_MODEL,
            api_key=os.getenv("NVIDIA_API_KEY"),
            base_url="https://integrate.api.nvidia.com/v1",
            max_retries=1,
            timeout=LLM_TIMEOUT,
        )

        # 1. Agente de Charla (Kimi) - Enfocado en personalidad y rapidez
        self.chat_agent = AgnoAgent(
            model=self.chat_model,
            description=COMPLETE_INSTRUCTIONS,
            db=self._memory_db,
            add_history_to_context=False, # Temp fix: NIM no permite imágenes en el contexto histórico fácilmente
            num_history_messages=0,
            markdown=True
        )

        # 2. Agente de Funciones (Minimax) - Con herramientas habilitadas
        self.function_agent = AgnoAgent(
            model=self.function_model,
            description=COMPLETE_INSTRUCTIONS,
            db=self._memory_db,
            add_history_to_context=False, # Temp fix
            num_history_messages=0,
            tools=[self._tools],
            markdown=True,
        )

        # 3. Agente de Visión (Llama) - Multimodal habilitado
        self.vision_agent = AgnoAgent(
            model=self.vision_model,
            description=COMPLETE_INSTRUCTIONS,
            db=self._memory_db,
            add_history_to_context=False, # Temp fix: Solo 1 imagen por prompt permitida por NIM
            num_history_messages=0,
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

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Obtiene o crea un lock de asyncio para una sesión específica."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def chat(self, user_message: str, user_id: str, room_id: str, images: Optional[list[str]] = None) -> str:
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

        # 2. Forzar uso de tools si el usuario pide resumen general (Fix de HEAD)
        msg_lower = user_message.strip().lower()
        if msg_lower in ["jada", "resumen", "resumen del día", "resumen de hoy", "hoy"]:
            user_message = f"{user_message}\n\n[SISTEMA INTERNO: El usuario ha pedido un resumen general. ESTÁS OBLIGADO a ejecutar inmediatamente las herramientas 'email_list' (con unread_only=False), 'calendar_today' (o 'calendar_upcoming') y 'gym_get_recent'. NUNCA respondas asumiendo datos ni inventes eventos; consulta siempre la base de datos a través de tus herramientas primero.]"

        # 3. Inject context directly into JadaTools
        self._tools.user_id = user_id
        self._tools.room_id = room_id
        self._tools.bot = self.bot

        # 4. Use room_id as the session_id to maintain context between the different chats.
        # Use a lock to prevent concurrent LLM calls for the same session (interference between user and cron)
        lock = self._get_session_lock(room_id)
        async with lock:
            try:
                # Preparar contenido multimodal si hay imágenes
                media_files = []
                if images:
                    for img_path in images:
                        if os.path.exists(img_path):
                            media_files.append(AgnoImage(filepath=img_path))

                # Selección dinámica de agente especializado
                current_images = None
                if images:
                    logger.info(f"👁️ Usando agente de visión: {VISION_MODEL}")
                    target_agent = self.vision_agent
                    current_images = media_files[:1]
                elif any(word in msg_lower for word in ["email", "correo", "agenda", "calendario", "nota", "tv", "gym", "entrenamiento", "entrenar"]):
                    logger.info(f"🛠️ Usando agente de funciones (Minimax): {FUNCTION_MODEL}")
                    target_agent = self.function_agent
                else:
                    logger.info(f"✨ Usando agente de chat (Kimi): {CHAT_MODEL}")
                    target_agent = self.chat_agent

                logger.info(f"🚀 Ejecutando arun() con agente: {target_agent.model.id}, imágenes: {len(current_images) if current_images else 0}")
                
                response = await target_agent.arun(
                    user_message,
                    session_id=room_id,
                    images=current_images
                )
                logger.info(f"📩 Respuesta de Agno ({target_agent.model.id}): {response.content[:100]}...")
                
                final_text = self._strip_thinking(response.content)
                if not final_text:
                    final_text = "⚠️ Procesé tu mensaje pero la consulta no arrojó los datos esperados (o hubo un corte de red). Intenta formular la pregunta otra vez."
                
                return final_text or "..."
                
            except Exception as e:
                logger.error(f"❌ Error en Agno Agent: {e}")
                return "⚠️ Ocurrió un error al procesar tu solicitud."
