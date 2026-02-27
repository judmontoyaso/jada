"""
agent/agent.py — Loop principal del agente (patrón ReAct: Reasoning + Acting)
Optimizado: selección inteligente de tools para reducir payload al LLM.
"""
import json
import os
import re
import time
import logging
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from agent.core import NvidiaLLM
from agent.memory import Memory
from agent.tools import TOOL_SCHEMAS, ToolDispatcher
from tools.gym_parser import expand_gym_notation

load_dotenv()

AGENT_NAME = os.getenv("AGENT_NAME", "Jada")
MAX_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "10"))


def _strip_thinking(text: str) -> str:
    """Eliminar bloques <think>...</think> que algunos modelos generan (ej: MiniMax M2.1)."""
    if not text:
        return text
    # Eliminar bloques <think>...</think> (incluyendo multiline)
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Eliminar tag <think> suelto sin cierre (modelo cortó a mitad)
    cleaned = re.sub(r'<think>.*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()

# ─── Cargar archivos de identidad (.agent/*.md) ──────────────────────────────

MAX_IDENTITY_CHARS = 800  # Límite para no sobrecargar el system prompt

def _load_identity_files() -> str:
    """Cargar soul.md y user.md, extraer solo datos clave (sin headers ni formato)."""
    agent_dir = Path(__file__).parent.parent / ".agent"
    lines = []
    
    for filename in ["soul.md", "user.md"]:
        filepath = agent_dir / filename
        if filepath.exists():
            try:
                for line in filepath.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    # Saltar headers, líneas vacías, y separadores
                    if not line or line.startswith("#") or line.startswith("---"):
                        continue
                    # Limpiar bullets
                    if line.startswith("- "):
                        line = line[2:]
                    lines.append(line)
            except Exception:
                pass
    
    text = "\n".join(lines)
    if len(text) > MAX_IDENTITY_CHARS:
        text = text[:MAX_IDENTITY_CHARS].rsplit("\n", 1)[0]
    return text

IDENTITY_CONTEXT = _load_identity_files()

SYSTEM_PROMPT = os.getenv(
    "AGENT_SYSTEM_PROMPT",
    f"Eres {AGENT_NAME}, un asistente de IA personal potente y directo. "
    "Tienes acceso a herramientas (tools/functions) para hacer ACCIONES REALES. "
    "REGLAS CRÍTICAS:\n"
    "1. SIEMPRE usa las herramientas disponibles para ejecutar acciones. NUNCA simules o inventes resultados.\n"
    "2. SÍ TIENES acceso al correo del usuario via IMAP. Cuando pregunte por correos, emails, mensajes recibidos, "
    "bandeja de entrada, o cualquier cosa relacionada con email: DEBES llamar email_list, email_read o email_search. "
    "NUNCA digas 'no tengo acceso a tu correo' ni 'no puedo leer emails'. SIEMPRE llama la herramienta.\n"
    "3. SÍ TIENES acceso al calendario via Google Calendar. DEBES llamar calendar_today o calendar_upcoming.\n"
    "4. Para guardar entrenamientos: pasa el texto EXACTO del usuario en 'ejercicios_raw'. NO interpretes los datos.\n"
    "5. Para buscar en la web, DEBES llamar web_search. No inventes información.\n"
    "6. Responde en el mismo idioma que el usuario.\n"
    "7. Cuando el usuario mencione datos importantes sobre sí mismo, usa remember_fact.\n"
    "8. Sé conciso. No generes menús de opciones innecesarios.\n"
    "9. Para anotar entrenamientos línea por línea: usa gym_start_session, gym_add_exercise, gym_end_session.\n"
    "10. Para guardar un entrenamiento completo en un solo mensaje: usa gym_save_workout con ejercicios_raw.\n"
    "11. Cuando el usuario mencione apagar, encender, o cambiar el volumen o HDMI del TV/televisor, usa SIEMPRE samsung_tv_control.",
)

logger = logging.getLogger("jada")
audit_logger = logging.getLogger("jada.audit")

# ─── Categorías de Tools ──────────────────────────────────────────────────────
# Dividimos las tools en categorías para enviar solo las relevantes al LLM.
# Esto reduce el payload y evita 504 Gateway Timeouts en NVIDIA NIM.

# Tools que siempre se envían (core, ligeras)
CORE_TOOLS = {"remember_fact", "web_search", "run_command", "read_file", "write_file", "list_dir", "deep_think"}

# ID de usuario ficticio para mensajes del scheduler
SCHEDULER_USER_ID = "@scheduler:jada"

# Categorías opcionales — se activan si el mensaje matchea
TOOL_CATEGORIES = {
    "gym": {
        "keywords": ["gym", "entrena", "ejercicio", "workout", "rutina", "pecho", "pierna", "espalda",
                      "bíceps", "tríceps", "hombro", "push", "pull", "leg", "sentadilla", "press",
                      "curl", "peso", "serie", "rep", "músculo", "cardio", "fullbody", "stats",
                      "estadístic", "progres", "anotar", "registrar", "listo", "guarda", "fondos",
                      "apertura", "vuelos", "deltoid", "remo", "jalón", "dominada", "barra"],
        "tools": {"gym_save_workout", "gym_start_session", "gym_add_exercise", "gym_end_session",
                  "gym_get_recent", "gym_exercise_history",
                  "gym_save_routine", "gym_get_routines", "gym_get_stats"},
    },
    "email": {
        "keywords": ["correo", "correos", "email", "emails", "mail", "inbox", "bandeja",
                      "mensaje recibido", "mensajes recibidos", "gmail", "remitente", "asunto",
                      "recibidos", "enviados", "último correo", "últimos correos",
                      "revisa mi", "leer correo", "lee mi", "mis correos", "mi correo",
                      "imap", "no leído", "no leidos", "enviar correo", "manda un correo",
                      "envía", "enviale", "escríbele", "mandar email", "enviar email"],
        "tools": {"email_list", "email_read", "email_search", "email_send"},
    },
    "calendar": {
        "keywords": ["calendario", "calendar", "evento", "agenda", "cita", "reunión",
                      "meeting", "schedule", "programado", "hoy tengo", "mañana tengo",
                      "semana", "próximos eventos"],
        "tools": {"calendar_today", "calendar_upcoming", "calendar_search"},
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
    "tv": {
        "keywords": ["tv", "tele", "televisor", "volumen", "enciende", "apaga", "apágalo", "enciéndelo", "silencia", "samsung", "hdmi", "fuente", "source", "ok", "home", "menú"],
        "tools": {"samsung_list_devices", "samsung_tv_status", "samsung_tv_control"},
    },
    "cronjobs": {
        "keywords": ["cron", "cronjob", "tarea programada", "programa", "schedulea", "crear tarea",
                      "cada día", "cada semana", "cada hora", "automatiza", "automatizar",
                      "listar tareas", "mis tareas", "borra tarea", "eliminar tarea"],
        "tools": {"cronjob_create", "cronjob_list", "cronjob_delete", "cronjob_update", "cronjob_run_now"},
    },
}


def _select_tools(message: str) -> list[dict]:
    """
    Selecciona solo las tools relevantes según el mensaje del usuario.
    Siempre incluye las tools core + categorías que matchean por keywords.
    """
    msg_lower = message.lower()

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


class Agent:
    def __init__(self):
        self.llm = NvidiaLLM()
        self.memory = Memory()
        self._send_callback = None  # Callback para enviar mensajes al room

    async def init(self):
        # Inyectar LLM en memoria para compresión con resúmenes inteligentes
        self.memory.set_llm(self.llm)
        await self.memory.init()

    async def run_scheduled(self, prompt: str, room_id: str) -> None:
        """
        Punto de entrada para el scheduler: ejecuta un prompt como si fuera
        un mensaje del usuario desde Matrix.
        Usa un user_id especial para identificar mensajes automáticos.
        """
        logger.info(f"⏰ Ejecutando tarea programada en room {room_id}: '{prompt[:80]}...'")
        try:
            response = await self.chat(prompt, SCHEDULER_USER_ID, room_id)
            # La respuesta se guarda en memoria — el bot la enviará al room
            # via el callback que inyecta matrix/client.py
            if hasattr(self, '_send_callback') and self._send_callback:
                await self._send_callback(room_id, response)
        except Exception as e:
            logger.error(f"❌ Error en tarea programada: {e}")

    def set_send_callback(self, callback) -> None:
        """Inyecta el callback para enviar mensajes al room de Matrix."""
        self._send_callback = callback

    async def chat(self, user_message: str, user_id: str, room_id: str) -> str:
        """
        Procesa un mensaje del usuario y retorna la respuesta del agente.
        Usa el patrón ReAct: el LLM puede llamar tools en múltiples iteraciones
        antes de dar la respuesta final.
        """
        # 0. Pre-procesar notación de gym si detecta patrones como 10x30x3
        if re.search(r'\d+x\d+x\d+', user_message) or 'con barra' in user_message.lower():
            original = user_message
            user_message = expand_gym_notation(user_message)
            if user_message != original:
                logger.info(f"🏋️ Notación gym expandida")

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

        # 5. Dispatcher de tools (con acceso a la memoria para remember_fact)
        dispatcher = ToolDispatcher(memory=self.memory, user_id=user_id, room_id=room_id)
        await dispatcher.init()

        # 6. Seleccionar tools relevantes según el mensaje
        tools = _select_tools(user_message)

        # 7. Loop ReAct — envuelto en try/except para que una falla del LLM
        #    no deje mensajes huérfanos en el historial
        try:
            final_text = await self._react_loop(messages, tools, dispatcher)
        except Exception as e:
            logger.error(f"❌ Error en LLM: {e}")
            final_text = "⚠️ No pude procesar tu mensaje (el modelo no respondió). Intenta de nuevo."

        # 8. Limpiar pensamientos del modelo y guardar
        final_text = _strip_thinking(final_text)

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
