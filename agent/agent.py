"""
agent/agent.py — Loop principal del agente (Agno nativo)
"""
import os
import re
import logging
import asyncio
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
    "15. Si el usuario te pide un resumen de su día, o solo dice 'jada' o 'resumen', DEBES llamar a email_list(only_new=False), calendar_today y gym_get_recent ANTES de responder. Asegúrate de verificar los datos reales. NUNCA asumas eventos ni inventes historiales sin usar las herramientas.\n"
    "PROHIBIDO ABSOLUTO:\n"
    "- Terminar mensajes con '¿Algo más?', '¿Hay algo más en que pueda ayudarte?' o variantes. Nunca.\n"
    "- Decir 'no tengo acceso' a una herramienta que aparece en tu lista.\n"
    "- Inventar resultados de herramientas sin haberlas llamado.",
)

<<<<<<< HEAD
logger = logging.getLogger("jada")
audit_logger = logging.getLogger("jada.audit")

# ─── Categorías de Tools ──────────────────────────────────────────────────────
# Dividimos las tools en categorías para enviar solo las relevantes al LLM.
# Esto reduce el payload y evita 504 Gateway Timeouts en NVIDIA NIM.

# Tools que siempre se envían (core, ligeras)
CORE_TOOLS = {
    "remember_fact", "web_search", "run_command", "read_file", "write_file", "list_dir", "deep_think",
    # Email SIEMPRE disponible — el modelo DEBE llamar email_list y nunca alucinar resultados
    "email_list",
    # Cronjobs SIEMPRE disponibles
    "cronjob_list", "cronjob_create", "cronjob_delete", "cronjob_update", "cronjob_run_now",
}

# ID de usuario ficticio para mensajes del scheduler
SCHEDULER_USER_ID = "@scheduler:jada"

# Categorías opcionales — se activan si el mensaje matchea
TOOL_CATEGORIES = {
    "gym": {
        "keywords": ["gym", "entrena", "ejercicio", "workout", "rutina", "pecho", "pierna", "espalda",
                      "bíceps", "tríceps", "hombro", "push", "pull", "leg", "sentadilla", "press",
                      "curl", "peso", "serie", "rep", "músculo", "cardio", "fullbody", "stats",
                      "estadístic", "progres", "anotar", "registrar", "listo", "guarda", "fondos",
                      "apertura", "vuelos", "deltoid", "remo", "jalón", "dominada", "barra", "jada", "resumen"],
        "tools": {"gym_save_workout", "gym_start_session", "gym_add_exercise", "gym_end_session",
                  "gym_get_recent", "gym_exercise_history",
                  "gym_save_routine", "gym_get_routines", "gym_get_stats"},
    },
    "email": {
        "keywords": [
            # Palabras directas
            "correo", "correos", "email", "emails", "mail", "inbox", "bandeja",
            "gmail", "remitente", "asunto", "imap", "no leído", "no leidos",
            # Frases con 'correo'
            "mi correo", "mis correos", "mi email", "mis emails",
            "mensaje recibido", "mensajes recibidos", "recibidos", "enviados",
            "revisa mi", "leer correo", "lee mi",
            "último correo", "últimos correos", "correos de hoy", "correos nuevos",
            # Frases naturales sin 'correo' — estas eran las que fallaban
            "qué llegó", "que llego", "qué tengo nuevo", "que tengo nuevo",
            "qué hay nuevo", "hay algo nuevo", "qué recibí", "qué entró",
            "consulta los", "consulta mis", "nuevos mensajes",
            "los nuevos", "los últimos", "recientes",
            # Enviar
            "enviar correo", "manda un correo", "envía", "envíale",
            "escríbele", "mandar email", "enviar email",
        ],
        "tools": {"email_list", "email_read", "email_search", "email_send"},
    },
    "calendar": {
        "keywords": ["calendario", "evento", "eventos", "hoy", "agenda", "agendar", "cita", "reunión", "reunion",
                      "semana", "próximos eventos", "prueba technique", "prueba técnica", "jada", "resumen"],
        "tools": {"calendar_today", "calendar_upcoming", "calendar_add_event"},
    },
    "browser": {
        "keywords": ["browser", "navega", "abre", "página", "web", "url", "http",
                      "scraping", "click", "formulario", "sitio"],
        "tools": {"browser_navigate", "browser_get_text", "browser_click", "browser_fill"},
    },
    "summarize": {
        "keywords": ["resume", "resumen", "resumir", "resumeme", "resúmeme", "summarize",
                      "summary", "de qué trata", "qué dice", "artículo", "articulo",
                      "página web", "blog", "leer página"],
        "tools": {"summarize_url"},
    },
    "reminders": {
        "keywords": ["recuérdame", "recordar", "recordatorio", "avísame", "avisa",
                      "alarma", "timer", "temporizador", "en 5 min", "en 10 min",
                      "en 30 min", "en 1 hora", "en una hora", "dentro de",
                      "minutos", "después", "reminder"],
        "tools": {"set_reminder", "list_reminders", "cancel_reminders"},
    },
    "notes": {
        "keywords": ["nota", "notas", "note", "apunte", "guardar nota", "buscar nota"],
        "tools": {"note_save", "note_list", "note_search", "note_delete"},
    },
    "weather": {
        "keywords": ["clima", "tiempo", "temperatura", "lloverá", "lluvia", "grados", "weather", "sol", "pronóstico"],
        "tools": {"get_weather"},
    },
    "tv": {
        "keywords": ["tv", "tele", "televisor", "volumen", "enciende", "apaga", "apágalo", "enciéndelo", "silencia", "samsung", "hdmi", "fuente", "source", "ok", "home", "menú"],
        "tools": {"samsung_list_devices", "samsung_tv_status", "samsung_tv_control"},
    },
    "cronjobs": {
        "keywords": [
            # Palabras clave directas
            "cron", "cronjob", "tarea programada", "schedulea",
            # Patrones de tiempo recurrente  
            "cada minuto", "cada dos", "cada tres", "cada cinco", "cada diez",
            "cada 15", "cada 30", "cada 2", "cada 5", "cada 10",
            "cada día", "cada semana", "cada hora", "cada mes",
            "todos los días", "todos los lunes", "todos los martes",
            "diariamente", "semanalmente", "mensualmente",
            # Intención de automatización recurrente
            "automatiza", "automatizar", "automáticamente",
            "pón a revisar", "pon a revisar", "programa que", "programa una",
            "repite", "repíteme", "hazlo cada",
            # Gestión — listar
            "listar tareas", "mis tareas programadas", "qué tareas", "que tareas", "ver tareas",
            "mis programadas", "mis cronjobs",
            # Gestión — cancelar / borrar / pausar
            "cancela", "cancelar", "cancela el", "cancela esa", "cancela ese",
            "borra tarea", "borra ese", "borra esa", "eliminar tarea", "elimina ese", "elimina esa",
            "pausa", "pausar", "pausa ese", "pausa esa", "pausa el",
            "deshabilita", "desactiva", "detén el job", "detén la tarea",
            "activa el", "activa ese", "habilita el",
        ],
        "tools": {"cronjob_create", "cronjob_list", "cronjob_delete", "cronjob_update", "cronjob_run_now"},
    },
}


def _select_tools(message: str, history: list[dict] = None) -> list[dict]:
    """
    Selecciona solo las tools relevantes según el mensaje del usuario
    Y los últimos mensajes del historial (para mantener contexto en follow-ups).
    Siempre incluye las tools core + categorías que matchean por keywords.
    """
    msg_lower = message.lower()

    # También analizar últimos 6 mensajes del historial para contexto
    if history:
        recent_texts = [m.get("content", "") or "" for m in history[-6:] if m.get("role") in ("user", "assistant")]
        msg_lower = msg_lower + " " + " ".join(t.lower() for t in recent_texts)

    active_tool_names = set(CORE_TOOLS)

    for category, config in TOOL_CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword in msg_lower:
                active_tool_names.update(config["tools"])
                logger.debug(f"🔧 Categoría '{category}' activada por keyword '{keyword}'")
                break

    # Si no matcheó nada específico, enviar solo las core (conversación simple)
    if active_tool_names == CORE_TOOLS:
        logger.info(f"🔧 Conversación simple — solo {len(CORE_TOOLS)} tools core")

    # Filtrar schemas
    selected = [t for t in TOOL_SCHEMAS if t["function"]["name"] in active_tool_names]
    logger.info(f"🔧 Tools seleccionadas: {len(selected)}/{len(TOOL_SCHEMAS)}")
    return selected
=======
# Build the complete instructions
COMPLETE_INSTRUCTIONS = f"{SYSTEM_PROMPT}\n\n{IDENTITY_CONTEXT}\n\nFecha actual: {date.today().isoformat()}"
>>>>>>> origin/feature/migration-agno


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

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Obtiene o crea un lock de asyncio para una sesión específica."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

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

<<<<<<< HEAD
        # 0.5 Forzar uso de tools si el usuario pide resumen general
        msg_lower = user_message.strip().lower()
        if msg_lower in ["jada", "resumen", "resumen del día", "resumen de hoy", "hoy"]:
            user_message = f"{user_message}\n\n[SISTEMA INTERNO: El usuario ha pedido un resumen general. ESTÁS OBLIGADO a ejecutar inmediatamente las herramientas 'email_list' (con only_new=False), 'calendar_today' (o 'calendar_upcoming') y 'gym_get_recent'. NUNCA respondas asumiendo datos ni inventes eventos; consulta siempre la base de datos a través de tus herramientas primero.]"

        # 1. Guardar el mensaje del usuario en memoria (ya expandido)
        await self.memory.save_message(room_id, user_id, "user", user_message)

        # 2. Recuperar historial y hechos del usuario
        history = await self.memory.get_history(room_id, user_id, limit=20)
        facts = await self.memory.get_facts(user_id)

        # 2.5 Sanitizar historial — eliminar mensajes user consecutivos sin respuesta
        clean_history = []
        for msg in history:
            if msg["role"] == "user" and clean_history and clean_history[-1]["role"] == "user":
                # Reemplazar el user anterior (no tiene respuesta)
                clean_history[-1] = msg
            else:
                clean_history.append(msg)
        
        if len(clean_history) != len(history):
            logger.info(f"🧹 Historial sanitizado: {len(history)} → {len(clean_history)} msgs")
        history = clean_history

        # 3. Construir el system prompt con contexto
        facts_text = ""
        if facts:
            facts_str = "\n".join(f"  - {f}" for f in facts)
            facts_text = f"\n\nLo que sé sobre ti:\n{facts_str}"

        identity_text = ""
        if IDENTITY_CONTEXT:
            identity_text = f"\n\n{IDENTITY_CONTEXT}"

        system = (
            f"{SYSTEM_PROMPT}"
            f"{identity_text}"
            f"{facts_text}"
            f"\n\nFecha actual: {date.today().isoformat()}"
        )

        # 4. Construir lista de mensajes
        messages = [{"role": "system", "content": system}] + history

        # 5. Dispatcher de tools — reusar instancia, actualizar contexto por mensaje
        self._dispatcher.set_context(user_id=user_id, room_id=room_id)

        # 6. Seleccionar tools relevantes según el mensaje
        tools = _select_tools(user_message, history)

        # 7. Loop ReAct — envuelto en try/except para que una falla del LLM
        #    no deje mensajes huérfanos en el historial
        try:
            final_text = await self._react_loop(messages, tools, self._dispatcher)
        except Exception as e:
            logger.error(f"❌ Error en LLM: {e}")
            final_text = "⚠️ No pude procesar tu mensaje (el modelo no respondió). Intenta de nuevo."

        # 8. Limpiar pensamientos del modelo y guardar
        final_text = _strip_thinking(final_text)
        if not final_text:
            final_text = "⚠️ Procesé tu mensaje pero la consulta no arrojó los datos esperados (o hubo un corte de red). Intenta formular la pregunta otra vez."

        # 9. Guardar la respuesta del asistente en memoria
        await self.memory.save_message(room_id, user_id, "assistant", final_text)

        return final_text

    async def _react_loop(
        self, messages: list[dict], tools: list[dict], dispatcher: ToolDispatcher
    ) -> str:
        """Loop ReAct interno. Lanza excepción si el LLM falla."""
        for iteration in range(MAX_ITERATIONS):
            response = await self.llm.chat(messages, tools=tools)

            # ¿El LLM quiere usar una o más tools?
            if response.tool_calls:
                # Añadir la respuesta del asistente (con tool_calls) al historial temporal
                messages.append({
                    "role": "assistant",
                    "content": response.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in response.tool_calls
                    ],
                })

                # Ejecutar cada tool call y añadir sus resultados
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    # Audit: medir tiempo de ejecución
                    t0 = time.perf_counter()
                    tool_result = await dispatcher.dispatch(tool_name, args)
                    elapsed_ms = (time.perf_counter() - t0) * 1000

                    # Audit log
                    args_short = json.dumps(args, ensure_ascii=False)[:200]
                    result_short = tool_result[:200]
                    audit_logger.info(
                        f"[TOOL] {tool_name}({args_short}) → {result_short} ({elapsed_ms:.0f}ms)"
                    )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    })

                    # Después de ejecutar un tool, expandir las tools disponibles
                    if tool_name not in CORE_TOOLS:
                        tools = TOOL_SCHEMAS

                # Continuar el loop para que el LLM procese los resultados
                continue

            # ¿El LLM dio una respuesta final (sin tool calls)?
            return response.content or "..."

        # Si se agotaron las iteraciones
        return "⚠️ Alcancé el límite de iteraciones. Intenta con algo más específico."
=======
        # 2. Inject context directly into JadaTools
        self._tools.user_id = user_id
        self._tools.room_id = room_id
        self._tools.bot = self.bot

        # 3. Use room_id as the session_id to maintain context between the different chats.
        # Use a lock to prevent concurrent LLM calls for the same session (interference between user and cron)
        lock = self._get_session_lock(room_id)
        async with lock:
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
>>>>>>> origin/feature/migration-agno
