"""
agent/agent.py — Loop principal del agente (Agno nativo)
Patrón: Coordinator + ReAct con Tool Group Routing
"""
import os
import re
import logging
import asyncio
import json
import time
from datetime import date, datetime
from pathlib import Path

from typing import Any, Dict, Optional
from dotenv import load_dotenv

from agno.agent import Agent as AgnoAgent
from agno.models.openai import OpenAIChat
from agno.models.nvidia import Nvidia
from agno.db.sqlite import SqliteDb
from agno.media import Image as AgnoImage

from agent.tools_registry import JadaTools
from agent.embeddings_router import get_router as get_embedding_router
from tools.gym_parser import expand_gym_notation

load_dotenv()

AGENT_NAME = os.getenv("AGENT_NAME", "Jada")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")
FUNCTION_MODEL = os.getenv("OPENAI_FUNCTION_MODEL", "gpt-5-mini")
VISION_MODEL = os.getenv("NVIDIA_VISION_MODEL", "meta/llama-3.2-11b-vision-instruct")
NVIDIA_MODEL = os.getenv("NVIDIA_FUNCTION_MODEL", "minimaxai/minimax-m2.5")
FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4.1")

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
    f"Eres {AGENT_NAME}. Tu personalidad está en soul.md abajo — síguela.\n\n"
    "## Cómo responder\n"
    "- Habla como una persona real, no como un robot. Sé breve y directa.\n"
    "- Usa las herramientas cuando necesites hacer algo (correo, notas, gym, calendario, etc). Simplemente úsalas.\n"
    "- Después de usar una herramienta, responde con el resultado en lenguaje natural. Ejemplo: 'Listo, nota guardada.' NO: 'He ejecutado note_save con los siguientes parámetros...'\n"
    "- Si algo falla, dilo simple: 'No pude guardar la nota, hubo un error.' No des stack traces.\n"
    "- Para recordatorios rápidos usa set_reminder. Para tareas recurrentes, cronjob_create.\n"
    "- Para noticias usa web_search. Para clima usa get_weather.\n\n"
    "## PROHIBIDO (tolerancia cero)\n"
    "- NUNCA muestres JSONs, payloads, parámetros internos ni nombres de funciones al usuario.\n"
    "- NUNCA narres lo que vas a hacer antes de hacerlo ('Voy a llamar a set_reminder...'). Solo hazlo y di el resultado.\n"
    "- NUNCA inventes resultados sin usar la herramienta. Si no llamaste la tool, no digas que lo hiciste.\n"
    "- NUNCA digas 'no tengo acceso' si la herramienta existe.\n"
    "- NUNCA termines con '¿Algo más?', '¿En qué más puedo ayudar?' o variantes.\n"
    "- NUNCA muestres tu razonamiento interno, chain of thought, ni proceso de decisión.\n\n"
    "## Formato\n"
    "- Respuestas cortas por defecto. Largo solo cuando el usuario lo necesita.\n"
    "- Markdown con moderación (listas/tablas solo para datos reales).\n"
    "- Responde en el idioma del usuario.\n",
)

import pytz

def _get_current_time_str() -> str:
    """Return current Bogotá time for the system prompt."""
    tz = pytz.timezone(os.getenv("TIMEZONE", "America/Bogota"))
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S")

def _build_instructions() -> str:
    """Build system prompt with live timestamp and playbook context."""
    from agent.playbook import playbook_manager
    playbook_ctx = playbook_manager.get_context(max_entries=10)
    base = f"{SYSTEM_PROMPT}\n\n{IDENTITY_CONTEXT}\n\nFecha y hora actual (Colombia): {_get_current_time_str()}"
    if playbook_ctx:
        base += f"\n\n## Lecciones aprendidas\n{playbook_ctx}"
    return base

class Agent:
    """Wrapper para instanciar agno.agent.Agent e integrar el router de Matrix."""

    # ── Keyword → Tool Group mapping ──
    # Each keyword maps to specific tool groups to inject
    KEYWORD_GROUPS: dict[str, list[str]] = {
        # Notes
        "nota": ["notes"], "notas": ["notes"], "guarda": ["notes"], "guardar": ["notes"],
        "guardarme": ["notes"], "anota": ["notes"], "anotar": ["notes"], "apunta": ["notes"],
        # Email
        "email": ["email"], "correo": ["email"], "correos": ["email"], "inbox": ["email"],
        "envía": ["email"], "enviar": ["email"], "enviale": ["email"], "manda": ["email"],
        # Calendar
        "agenda": ["calendar"], "calendario": ["calendar"], "cita": ["calendar"],
        "reunión": ["calendar"], "evento": ["calendar"], "agendar": ["calendar"],
        # Gym
        "gym": ["gym"], "entrenamiento": ["gym"], "entrenar": ["gym"],
        "ejercicio": ["gym"], "rutina": ["gym"], "pesas": ["gym"],
        "repeticiones": ["gym"], "series": ["gym"], "pierna": ["gym"],
        "press": ["gym"], "curl": ["gym"], "sentadilla": ["gym"],
        # TV
        "tv": ["tv"], "televisor": ["tv"], "tele": ["tv"], "samsung": ["tv"],
        "prende": ["tv"], "apaga": ["tv"], "volumen": ["tv"],
        # Reminders
        "recordatorio": ["reminders"], "recordar": ["reminders"],
        "recuérdame": ["reminders"], "recuerdame": ["reminders"],
        "minutos": ["reminders"], "alarma": ["reminders"],
        # Cronjobs
        "cronjob": ["cronjobs"], "tarea programada": ["cronjobs"],
        "programar": ["cronjobs"], "tareas programadas": ["cronjobs"],
        # Weather + Web
        "clima": ["web"], "temperatura": ["web"], "lluvia": ["web"],
        "pronóstico": ["web"], "busca": ["web"], "buscar": ["web"],
        "noticias": ["web"], "google": ["web"], "web": ["web"],
        # Files / Shell
        "archivo": ["files"], "carpeta": ["files"], "ejecuta": ["files"],
        "comando": ["files"], "terminal": ["files"],
        # Summarizer
        "resumen": ["web"], "resume": ["web"], "resumir": ["web"],
        "url": ["web"], "http": ["web"],
        # Image / Media
        "genera": ["media"], "generar": ["media"], "dibuja": ["media"], "imagen": ["media"],
        "foto": ["media"], "mándame": ["media"], "mandame": ["media"],
        "envía la imagen": ["media"], "manda la imagen": ["media"],
        "describe": ["media"], "describir": ["media"], "describeme": ["media"],
        "la imagen": ["media"], "última imagen": ["media"], "ultima imagen": ["media"],
        # Deep think
        "ahonda": ["think"], "analiza": ["think"],
        # Storage (Supabase)
        "sube": ["storage"], "subir": ["storage"], "subelo": ["storage"],
        "storage": ["storage"], "nube": ["storage"], "supabase": ["storage"],
        "descarga": ["storage"], "descargar": ["storage"],
        "compartir": ["storage"], "comparte": ["storage"],
        # Summary triggers (multiple groups)
        "resumen del día": ["email", "calendar", "gym"],
        "resumen de hoy": ["email", "calendar", "gym"],
    }

    def __init__(self, bot: Any = None):
        self._send_callback = None
        self.bot = bot
        self._tools = JadaTools(bot=self.bot)  # Full toolkit for DB init + scheduled tasks
        self._session_locks: Dict[str, asyncio.Lock] = {}
        
        self._memory_db = SqliteDb(
            session_table="sessions",
            db_url="sqlite:///memory.db"
        )
        
        self._llm_call_timeout = int(os.getenv("LLM_TIMEOUT", "45"))

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
        self.vision_model = Nvidia(
            id=VISION_MODEL,
            api_key=os.getenv("NVIDIA_API_KEY"),
        )
        self.nvidia_model = Nvidia(
            id=NVIDIA_MODEL,
            api_key=os.getenv("NVIDIA_API_KEY"),
        )

        # Groups that should use NVIDIA (MiniMax) instead of GPT
        self.NVIDIA_GROUPS = {'web', 'think', 'email', 'storage'}

        total_tools = sum(len(v) for v in JadaTools.GROUPS.values())
        logger.info(
            f"🤖 Agent inicializado:\n"
            f"  Primary:  {FUNCTION_MODEL}\n"
            f"  NVIDIA:   {NVIDIA_MODEL}\n"
            f"  Fallback: {FALLBACK_MODEL}\n"
            f"  Vision:   {VISION_MODEL}\n"
            f"  Tool groups: {len(JadaTools.GROUPS)} ({total_tools} tools total)"
        )

    def _detect_groups(self, msg_lower: str) -> list[str]:
        """Detect tool groups: keywords first, embedding fallback if no match."""
        # 1. Fast keyword matching
        groups: set[str] = set()
        for keyword, grps in self.KEYWORD_GROUPS.items():
            if keyword in msg_lower:
                groups.update(grps)
        if groups:
            return list(groups)

        # 2. Embedding fallback — catches indirect intents
        try:
            router = get_embedding_router()
            semantic_groups = router.route(msg_lower, top_k=2)
            if semantic_groups:
                logger.info(f"🧠 Embedding fallback: {semantic_groups}")
                return semantic_groups
        except Exception as e:
            logger.warning(f"⚠️ Embedding router error: {e}")

        return []

    def _build_agent(self, instructions: str, groups: list[str] | None = None):
        """Build an agent with scoped tools for this specific request."""
        if groups:
            scoped_tools = JadaTools(bot=self.bot, groups=groups)
            # Share DB connections (already initialized)
            scoped_tools.gym_db = self._tools.gym_db
            scoped_tools.notes_db = self._tools.notes_db
            scoped_tools._gym_session = self._tools._gym_session
            scoped_tools.set_context(
                user_id=self._tools.user_id,
                room_id=self._tools.room_id,
                bot=self.bot,
            )
            tool_count = len(scoped_tools.functions) + len(getattr(scoped_tools, 'async_functions', {}))
            
            # Choose model: NVIDIA groups → MiniMax, else → GPT
            use_nvidia = bool(set(groups) & self.NVIDIA_GROUPS)
            model = self.nvidia_model if use_nvidia else self.primary_model
            model_name = NVIDIA_MODEL if use_nvidia else FUNCTION_MODEL

            agent = AgnoAgent(
                model=model,
                description=instructions,
                db=self._memory_db,
                add_history_to_context=True,
                num_history_messages=6,
                tools=[scoped_tools],
                markdown=True,
            )
            return agent, scoped_tools, tool_count, model_name
        else:
            # Chat-only agent — no tools, minimum tokens
            agent = AgnoAgent(
                model=self.primary_model,
                description=instructions,
                db=self._memory_db,
                add_history_to_context=True,
                num_history_messages=6,
                markdown=True,
            )
            return agent, None, 0, FUNCTION_MODEL

    async def init(self):
        """Inicializa las conexiones a bases de datos y herramientas."""
        await self._tools.init_databases()
        # Re-queue pending reminders from MongoDB (survive restarts)
        from tools.reminders import reminder_manager
        try:
            await reminder_manager.load_pending_reminders()
        except Exception as e:
            logger.warning(f"⚠️ No se pudieron cargar recordatorios pendientes: {e}")
        # Pre-load embedding model in background (non-blocking)
        try:
            get_embedding_router()  # triggers lazy load
        except Exception as e:
            logger.warning(f"⚠️ Embedding router no cargó: {e}")
        logger.info("✅ Agent Tools & DB inicializado")

    async def run_scheduled(self, prompt: str, room_id: str) -> None:
        """Punto de entrada para cronjobs — usa ALL tools."""
        logger.info(f"⏰ Ejecutando tarea en room {room_id}: '{prompt[:80]}...'")
        try:
            response = await self.chat(prompt, "@scheduler:jada", room_id)
            if self._send_callback:
                await self._send_callback(room_id, response)
        except Exception as e:
            logger.error(f"❌ Error en tarea programada: {e}")

    def set_send_callback(self, callback) -> None:
        """Inyecta el callback de la sesión de Matrix."""
        self._send_callback = callback

    def _clean_response(self, text: str) -> str:
        """Clean LLM response: strip thinking tags and tool call artifacts."""
        if not text:
            return ""
        # 1. Remove <think> tags
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        cleaned = re.sub(r'<think>.*$', '', cleaned, flags=re.DOTALL)
        # 2. Remove CALL_TOOL_NAME: {...} patterns (tool call narration)
        cleaned = re.sub(r'CALL_\w+:\s*\{[^}]*\}', '', cleaned)
        # 3. Remove raw JSON result blocks ({"results":[...]} etc)
        cleaned = re.sub(r'\{"results"\s*:\s*\[.*?\]\}', '', cleaned, flags=re.DOTALL)
        # 4. Remove lines that are just JSON objects
        cleaned = re.sub(r'^\s*\{["\'].*?\}\s*$', '', cleaned, flags=re.MULTILINE)
        # 5. Collapse excessive blank lines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    async def _run_background_task(self, message: str, user_id: str, room_id: str, groups: list[str]):
        """Fire-and-forget: ejecuta un task lento en background y envía resultado via callback."""
        try:
            live_instructions = _build_instructions()
            self._tools.set_context(user_id=user_id, room_id=room_id, bot=self.bot)
            target_agent, _, tool_count, model_name = self._build_agent(live_instructions, groups)
            logger.info(f"🔄 Background task iniciado ({groups}, {tool_count} tools)")

            response = await asyncio.wait_for(
                target_agent.arun(message, session_id=room_id),
                timeout=180  # 3 min max for background tasks
            )
            result = self._clean_response(response.content)

            # Sync gym state if needed
            if 'gym' in groups and hasattr(target_agent, 'tools'):
                for t in (target_agent.tools or []):
                    if isinstance(t, JadaTools):
                        self._tools._gym_session = t._gym_session

            if result and self._send_callback:
                await self._send_callback(room_id, result)
                logger.info(f"📩 Background result enviado al room")
        except Exception as e:
            logger.error(f"❌ Background task falló: {e}")
            if self._send_callback:
                await self._send_callback(room_id, f"⚠️ La tarea en segundo plano falló: {str(e)[:100]}")

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
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def chat(self, user_message: str, user_id: str, room_id: str, images: Optional[list[str]] = None) -> str:
        """
        Punto de entrada principal. Detecta qué tool groups necesita
        y crea un agente con SOLO esos tools (3-8 en vez de 44).
        """
        # 1. Expand Gym notation
        if re.search(r'\d+x\d+x\d+', user_message) or 'con barra' in user_message.lower():
            original = user_message
            user_message = expand_gym_notation(user_message)
            if user_message != original:
                logger.info(f"🏋️ Notación gym expandida")

        # 2. Force tools for summary requests
        msg_lower = user_message.strip().lower()
        if msg_lower in ["jada", "resumen", "resumen del día", "resumen de hoy", "hoy"]:
            user_message = f"{user_message}\n\n[SISTEMA INTERNO: El usuario ha pedido un resumen general. ESTÁS OBLIGADO a ejecutar inmediatamente las herramientas 'email_list' (con unread_only=False), 'calendar_today' (o 'calendar_upcoming') y 'gym_get_recent'. NUNCA respondas asumiendo datos ni inventes eventos; consulta siempre la base de datos a través de tus herramientas primero.]"

        # 3. Inject context
        self._tools.set_context(user_id=user_id, room_id=room_id, bot=self.bot)

        # 4. Build live instructions
        live_instructions = _build_instructions()

        # 5. Detect which tool groups are needed
        groups = self._detect_groups(msg_lower)

        # 6. Process
        lock = self._get_session_lock(room_id)
        async with lock:
            try:
                # Handle images
                media_files = []
                if images:
                    for img_path in images:
                        if os.path.exists(img_path):
                            media_files.append(AgnoImage(filepath=img_path))

                current_images = None

                if images:
                    # Vision path → NVIDIA Llama 3.2 (FREE, no GPT tokens)
                    logger.info(f"👁️ Vision → {VISION_MODEL} (NVIDIA, gratis)")
                    target_agent = AgnoAgent(
                        model=self.vision_model,
                        description=live_instructions,
                        db=self._memory_db,
                        add_history_to_context=True,
                        num_history_messages=6,
                        markdown=True,
                    )
                    current_images = media_files[:1]
                elif groups:
                    # Check if this is a slow task that should run in background
                    slow_groups = {'think'}
                    if groups and set(groups) <= slow_groups and self._send_callback:
                        # Fire-and-forget: respond immediately, process in background
                        asyncio.create_task(
                            self._run_background_task(user_message, user_id, room_id, groups)
                        )
                        logger.info(f"🔄 Async → {groups} lanzado en background")
                        return "Dale, lo analizo y te aviso cuando termine. Puedes seguir hablando. 🧠"

                    # Tool path — create scoped agent with ONLY relevant tools
                    target_agent, scoped_tools, tool_count, model_name = self._build_agent(live_instructions, groups)
                    logger.info(f"🛠️ Tools → {model_name} ({tool_count} tools, groups: {groups})")
                else:
                    # Chat path — NO tools, fastest
                    target_agent, _, tool_count, model_name = self._build_agent(live_instructions, None)
                    logger.info(f"💬 Chat → {model_name} (0 tools, rápido)")

                # Execute with failover
                response = await self._run_with_failover(
                    user_message, room_id, target_agent, current_images, live_instructions, groups
                )
                
                final_text = self._clean_response(response.content)
                if not final_text:
                    final_text = "⚠️ Procesé tu mensaje pero la consulta no arrojó los datos esperados (o hubo un corte de red). Intenta formular la pregunta otra vez."
                
                # Sync gym session state back to main toolkit
                if groups and 'gym' in groups and hasattr(target_agent, 'tools'):
                    for t in (target_agent.tools or []):
                        if isinstance(t, JadaTools):
                            self._tools._gym_session = t._gym_session

                # ACE-lite: learn from interaction (background, non-blocking)
                if groups:
                    tool_names = groups  # Use groups as proxy for tools used
                    from agent.playbook import playbook_manager
                    asyncio.create_task(
                        playbook_manager.maybe_learn(user_message, tool_names, final_text)
                    )

                return final_text or "..."
                
            except Exception as e:
                logger.error(f"❌ Error en Agno Agent: {e}")
                return "⚠️ Ocurrió un error al procesar tu solicitud."

    async def _run_with_failover(self, message: str, room_id: str, target_agent, images=None, instructions: str = "", groups: list[str] | None = None):
        """
        Intenta ejecutar con el agente primario. Si falla (timeout/error),
        reintenta con fallback (GPT-4.1) con the same scoped tools.
        """
        try:
            response = await asyncio.wait_for(
                target_agent.arun(message, session_id=room_id, images=images),
                timeout=self._llm_call_timeout
            )
            logger.info(f"📩 Respuesta de {target_agent.model.id}: {response.content[:100]}...")
            return response
        except (asyncio.TimeoutError, Exception) as e:
            if images:
                raise  # No fallback for vision
            logger.warning(f"⚠️ Primario ({target_agent.model.id}) falló: {e}. Intentando fallback...")
            
            # Build fallback with same scoped tools
            if groups:
                scoped_tools = JadaTools(bot=self.bot, groups=groups)
                scoped_tools.gym_db = self._tools.gym_db
                scoped_tools.notes_db = self._tools.notes_db
                scoped_tools._gym_session = self._tools._gym_session
                scoped_tools.set_context(
                    user_id=self._tools.user_id,
                    room_id=self._tools.room_id,
                    bot=self.bot,
                )
                fallback = AgnoAgent(
                    model=self.fallback_model,
                    description=instructions or _build_instructions(),
                    db=self._memory_db,
                    add_history_to_context=True,
                    num_history_messages=6,
                    tools=[scoped_tools],
                    markdown=True,
                )
            else:
                fallback = AgnoAgent(
                    model=self.fallback_model,
                    description=instructions or _build_instructions(),
                    db=self._memory_db,
                    add_history_to_context=True,
                    num_history_messages=6,
                    markdown=True,
                )

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
