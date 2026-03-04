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
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from agno.media import Image as AgnoImage

from agent.tools_registry import JadaTools
from tools.gym_parser import expand_gym_notation

load_dotenv()

AGENT_NAME = os.getenv("AGENT_NAME", "Jada")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
FUNCTION_MODEL = os.getenv("OPENAI_FUNCTION_MODEL", "gpt-4.1-mini")
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4.1")
# LLM_TIMEOUT is now set per-instance in Agent.__init__ (self._llm_call_timeout)

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
    "5. Para tareas programadas (cronjobs): Puedes crearlas (cronjob_create) o listarlas (cronjob_list). Para modificar o borrar una, usa primero cronjob_list para obtener el job_id.\n"
    "6. Para gym: gym_save_workout con el texto EXACTO del usuario en 'ejercicios_raw'.\n"
    "8. Para enviar emails: usa email_send.\n"
    "9. Para noticias: SIEMPRE usa web_search con una query relevante. NUNCA inventes URLs ni resultados genéricos. Si no sabes, dinos: 'No encontré'.\n"
    "10. Para clima o temperatura: usa get_weather.\n"
    "11. Para agendar reuniones o eventos en Google Calendar: Pide título y hora (ej: 'Reunión de equipo a las 3pm'), luego calcula la fecha/hora en ISO 8601 basado en la hora local y SIEMPRE usa calendar_add_event. No asumas éxito sin el JSON.\n"
    "12. Para notas: usa note_save, note_list, note_search. Si vas a guardar una nota, USA la herramienta note_save. NUNCA digas que guardaste algo sin usar la herramienta.\n"
    "13. Para recordatorios rápidos (ej: 'en 5 minutos'): USA SIEMPRE set_reminder(message='...', time='5 minutos'). Es tu herramienta principal para esto.\n"
    "-----------\n"
    "== REGLA DE TOLERANCIA CERO A ALUCINACIONES DE ACCIONES ==\n"
    "NUNCA bajo NINGUNA circunstancia afirmes haber realizado una acción si no llamaste a la herramienta correspondiente y recibiste un JSON de éxito.\n"
    "Las notas y recordatorios SIEMPRE se gestionan usando herramientas. NUNCA busques en la base de datos local SQLite (memory.db) usando run_command ni digas al usuario que están ahí.\n"
    "Si la herramienta falla, di que falló. Si no tienes la herramienta en tu lista actual, debe aparecer como 'set_reminder'. Úsala.\n"
    "-----------\n"
    "14. Responde en el idioma del usuario.\n"
    "15. Sé conciso. Respuestas cortas cuando sea posible.\n"
    "16. Para TV: samsung_tv_control.\n"
    "17. Para recordatorios rápidos de una sola vez: USA set_reminder. Los cronjobs son para tareas recurrentes.\n"
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

def _build_instructions() -> str:
    """Build system prompt with live timestamp (not stale from module load)."""
    return f"{SYSTEM_PROMPT}\n\n{IDENTITY_CONTEXT}\n\nFecha y hora actual (Colombia): {_get_current_time_str()}"

class Agent:
    """Wrapper para instanciar agno.agent.Agent e integrar el router de Matrix."""

    # ── Keywords that trigger tools (case-insensitive, searched in msg_lower) ──
    TOOL_KEYWORDS = [
        # Notes
        "nota", "notas", "guarda", "guardar", "guardarme", "anota", "anotar", "apunta",
        # Email
        "email", "correo", "correos", "inbox", "envía", "enviar", "enviale", "manda",
        # Calendar
        "agenda", "calendario", "cita", "reunión", "evento", "agendar", "agendam",
        # Gym
        "gym", "entrenamiento", "entrenar", "ejercicio", "rutina", "pesas", "repeticiones",
        "series", "pierna", "press", "curl", "sentadilla",
        # TV / SmartThings
        "tv", "televisor", "tele", "samsung", "prende", "apaga", "volumen",
        # Reminders / Cronjobs
        "recordatorio", "recordar", "recuérdame", "recuerdame", "minutos", "hora",
        "cronjob", "tarea programada", "programar",
        # Weather
        "clima", "temperatura", "lluvia", "pronóstico",
        # Web / Browse
        "busca", "buscar", "noticias", "google", "web",
        # Files / Shell
        "archivo", "carpeta", "ejecuta", "comando", "terminal",
        # Summarizer
        "resumen", "resume", "resumir", "url", "http",
        # Image gen
        "genera", "generar", "dibuja", "imagen",
        # Summary triggers (these need tools)
        "resumen del día", "resumen de hoy",
        # Deep think
        "ahonda", "analiza",
    ]

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
        
        # ── Timeout per LLM call (NOT the total think timeout) ──
        self._llm_call_timeout = int(os.getenv("LLM_TIMEOUT", "45"))

        # Instanciar modelos OpenAI
        self.primary_model = OpenAIChat(
            id=FUNCTION_MODEL,
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=1,
            timeout=self._llm_call_timeout,
        )
        self.fallback_model = OpenAIChat(
            id=FALLBACK_MODEL,
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=1,
            timeout=self._llm_call_timeout,
        )
        self.vision_model = OpenAIChat(
            id=VISION_MODEL,
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=1,
            timeout=self._llm_call_timeout,
        )

        # ── Build instructions dynamically (live timestamp) ──
        instructions = _build_instructions()

        # 1. Chat-only Agent (NO TOOLS) — fast, for pure conversation
        #    Sending 0 tool schemas means much fewer tokens → much faster API response
        self.chat_agent = AgnoAgent(
            model=self.primary_model,
            description=instructions,
            db=self._memory_db,
            add_history_to_context=True, 
            num_history_messages=10,
            markdown=True,
        )

        # 2. Tool Agent (WITH TOOLS) — for action requests
        self.tool_agent = AgnoAgent(
            model=self.primary_model,
            description=instructions,
            db=self._memory_db,
            add_history_to_context=True, 
            num_history_messages=10,
            tools=[self._tools],
            markdown=True,
        )

        # 3. Fallback Agent (Kimi K2 + TOOLS) — slower but smarter, used on retry
        self.fallback_agent = AgnoAgent(
            model=self.fallback_model,
            description=instructions,
            db=self._memory_db,
            add_history_to_context=True, 
            num_history_messages=10,
            tools=[self._tools],
            markdown=True
        )

        # 4. Vision Agent (Llama 3.2) — multimodal, no tools
        self.vision_agent = AgnoAgent(
            model=self.vision_model,
            description=instructions,
            db=self._memory_db,
            add_history_to_context=True, 
            num_history_messages=10,
            markdown=True
        )

    def _needs_tools(self, msg_lower: str) -> bool:
        """Detect if the message requires tool execution."""
        return any(kw in msg_lower for kw in self.TOOL_KEYWORDS)

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
        Punto de entrada principal. Decide si el mensaje necesita tools o no,
        y enruta al agente apropiado para minimizar latencia.
        """
        # 1. Expand Gym notation
        if re.search(r'\d+x\d+x\d+', user_message) or 'con barra' in user_message.lower():
            original = user_message
            user_message = expand_gym_notation(user_message)
            if user_message != original:
                logger.info(f"🏋️ Notación gym expandida")

        # 2. Forzar uso de tools si el usuario pide resumen general
        msg_lower = user_message.strip().lower()
        if msg_lower in ["jada", "resumen", "resumen del día", "resumen de hoy", "hoy"]:
            user_message = f"{user_message}\n\n[SISTEMA INTERNO: El usuario ha pedido un resumen general. ESTÁS OBLIGADO a ejecutar inmediatamente las herramientas 'email_list' (con unread_only=False), 'calendar_today' (o 'calendar_upcoming') y 'gym_get_recent'. NUNCA respondas asumiendo datos ni inventes eventos; consulta siempre la base de datos a través de tus herramientas primero.]"

        # 3. Inject context into JadaTools (thread-safe setter)
        self._tools.set_context(user_id=user_id, room_id=room_id, bot=self.bot)

        # 4. Refresh instructions with live timestamp for the agent about to be used
        live_instructions = _build_instructions()

        # 5. Use room_id as the session_id to maintain context
        lock = self._get_session_lock(room_id)
        async with lock:
            try:
                # Preparar contenido multimodal si hay imágenes
                media_files = []
                if images:
                    for img_path in images:
                        if os.path.exists(img_path):
                            media_files.append(AgnoImage(filepath=img_path))

                # ── Agent selection based on intent ──
                current_images = None
                needs_tools = self._needs_tools(msg_lower)

                if images:
                    logger.info(f"👁️ Vision → {VISION_MODEL}")
                    target_agent = self.vision_agent
                    current_images = media_files[:1]
                elif needs_tools:
                    logger.info(f"🛠️ Tools → {FUNCTION_MODEL} (44 tools)")
                    target_agent = self.tool_agent
                else:
                    logger.info(f"💬 Chat → {FUNCTION_MODEL} (sin tools, rápido)")
                    target_agent = self.chat_agent

                # Update agent instructions with live timestamp
                target_agent.description = live_instructions

                logger.info(f"📤 arun() → {target_agent.model.id}, tools: {needs_tools}, imgs: {len(current_images) if current_images else 0}")
                
                # ── Execute with failover ──
                response = await self._run_with_failover(
                    user_message, room_id, target_agent, current_images, live_instructions
                )
                
                final_text = self._strip_thinking(response.content)
                if not final_text:
                    final_text = "⚠️ Procesé tu mensaje pero la consulta no arrojó los datos esperados (o hubo un corte de red). Intenta formular la pregunta otra vez."
                
                return final_text or "..."
                
            except Exception as e:
                logger.error(f"❌ Error en Agno Agent: {e}")
                return "⚠️ Ocurrió un error al procesar tu solicitud."

    async def _run_with_failover(self, message: str, room_id: str, target_agent, images=None, instructions: str = ""):
        """
        Intenta ejecutar con el agente primario. Si falla (timeout/error),
        reintenta con el agente fallback (Kimi K2).
        """
        try:
            response = await asyncio.wait_for(
                target_agent.arun(message, session_id=room_id, images=images),
                timeout=self._llm_call_timeout
            )
            logger.info(f"📩 Respuesta de {target_agent.model.id}: {response.content[:100]}...")
            return response
        except (asyncio.TimeoutError, Exception) as e:
            if target_agent == self.vision_agent:
                # No fallback for vision — just re-raise
                raise
            logger.warning(f"⚠️ Primario ({target_agent.model.id}) falló: {e}. Intentando fallback...")
            # Switch to fallback agent
            fallback = self.fallback_agent
            fallback.description = instructions or _build_instructions()
            try:
                response = await asyncio.wait_for(
                    fallback.arun(message, session_id=room_id),
                    timeout=self._llm_call_timeout
                )
                logger.info(f"📩 Fallback ({fallback.model.id}): {response.content[:100]}...")
                return response
            except Exception as e2:
                logger.error(f"❌ Fallback también falló: {e2}")
                raise e2
