"""
agent/tools.py — Registro central de herramientas y dispatcher (Agno-style)

Los schemas se definen de forma compacta con el helper _fn() que genera
automáticamente el format OpenAI/NIM. Reduce ~60% el boilerplate.
"""
import asyncio
import json
from tools.shell import run_command
from tools.files import read_file, write_file, list_dir
from tools.web_search import search
from tools.browser import BrowserTool
from tools.gym_db import GymDB
from tools.notes import NotesDB
from tools.gym_parser import parse_workout_text
from tools.email_reader import list_emails, read_email, search_emails
from tools.email_sender import send_email
from tools.calendar_api import get_today_events, get_upcoming_events, add_event
from tools.summarizer import fetch_and_summarize
from tools.reminders import reminder_manager
from tools.deep_think import deep_think
from tools.samsung_tv import tv_control, tv_status, list_devices
from tools.weather import get_weather
from agent.scheduler import get_scheduler


# ─── Helper: genera schema NIM desde definición compacta ─────────────────────

def _fn(name: str, description: str, props: dict, required: list = None) -> dict:
    """
    Genera un schema de function calling en formato OpenAI/NIM.
    Cada propiedad en `props` puede ser:
      - Una tupla (type, description) para campos simples
      - Un dict completo para campos complejos (arrays, enums, etc.)
    """
    properties = {}
    for key, val in props.items():
        if isinstance(val, tuple):
            prop_type, prop_desc = val
            properties[key] = {"type": prop_type, "description": prop_desc}
        else:
            properties[key] = val  # dict completo (arrays, etc.)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


def _fn_empty(name: str, description: str) -> dict:
    """Schema para tools sin parámetros."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


# ─── Schemas de tools para NVIDIA NIM ────────────────────────────────────────

TOOL_SCHEMAS = [

    # ── Shell ──────────────────────────────────────────────────────────────────
    _fn("run_command",
        "Ejecuta un comando de shell/terminal en el sistema (modo whitelist). Retorna stdout, stderr y código de salida.",
        {"command": ("string", "Comando a ejecutar"),
         "timeout": ("integer", "Timeout en segundos (default: 30)")},
        required=["command"]),

    # ── Archivos ───────────────────────────────────────────────────────────────
    _fn("read_file",
        "Lee el contenido de un archivo del sistema.",
        {"path": ("string", "Ruta absoluta o relativa del archivo")},
        required=["path"]),

    _fn("write_file",
        "Crea o sobreescribe un archivo. Puede añadir al final si append=true.",
        {"path": ("string", "Ruta del archivo"),
         "content": ("string", "Contenido a escribir"),
         "append": ("boolean", "Si true, añade al final del archivo")},
        required=["path", "content"]),

    _fn("list_dir",
        "Lista el contenido (archivos y carpetas) de un directorio.",
        {"path": ("string", "Ruta del directorio (default: directorio actual)")}),

    # ── Web ────────────────────────────────────────────────────────────────────
    _fn("web_search",
        "Busca información en la web usando DuckDuckGo o Google News. Retorna títulos, URLs y snippets.",
        {"query": ("string", "Consulta de búsqueda (Si es noticias, usa SOLO palabras clave como 'Colombia' o 'Tecnología', SIN fechas ni palabras como 'hoy')"),
         "max_results": ("integer", "Número máximo de resultados (default: 5)"),
         "search_type": ("string", "Tipo de búsqueda: 'text' o 'news'")},
        required=["query", "search_type"]),

    _fn("get_weather",
        "Obtiene el clima actual, temperatura y posibilidad de lluvia de una ciudad.",
        {"location": ("string", "Nombre de la ciudad (default: Medellin)")}),

    # ── Browser ────────────────────────────────────────────────────────────────
    _fn("browser_navigate",
        "Navega a una URL en el browser. Úsalo para abrir páginas web.",
        {"url": ("string", "URL a abrir (debe incluir https://)")},
        required=["url"]),

    _fn_empty("browser_get_text",
              "Extrae el texto visible de la página actualmente abierta en el browser."),

    _fn("browser_click",
        "Hace click en un elemento de la página usando un selector CSS o texto visible.",
        {"selector": ("string", "Selector CSS o texto del elemento")},
        required=["selector"]),

    _fn("browser_fill",
        "Rellena un campo de formulario en la página actual.",
        {"selector": ("string", "Selector CSS del campo"),
         "text": ("string", "Texto a escribir")},
        required=["selector", "text"]),

    # ── Samsung TV (SmartThings) ───────────────────────────────────────────────
    _fn_empty("samsung_list_devices",
              "Lista todos los dispositivos disponibles en SmartThings (incluye TVs)."),

    _fn("samsung_tv_status",
        "Obtiene el estado actual del TV (encendido/apagado).",
        {"device_id": ("string", "ID del dispositivo TV (Opcional)")}),

    _fn("samsung_tv_control",
        "Controla el Samsung TV: enciéndelo, apágalo, sube/baja volumen o silencia.",
        {"device_id": ("string", "ID del dispositivo TV (Opcional)"),
         "command": ("string", "Comando: 'on', 'off', 'up', 'down', 'mute', 'unmute', 'ok', 'back', 'home', 'menu', 'source', 'hdmi1', 'hdmi2', 'hdmi3'")},
        required=["command"]),

    # ── Gym ────────────────────────────────────────────────────────────────────
    _fn("gym_save_workout",
        ("Guarda un entrenamiento COMPLETO de gym en MongoDB. Usa esto cuando el usuario "
         "manda TODOS los ejercicios en un solo mensaje. Pasa el texto EXACTAMENTE como "
         "lo escribió el usuario en 'ejercicios_raw'. NO interpretes la notación tú mismo."),
        {"nombre": ("string", "Nombre descriptivo (ej: 'Push - Pecho, Hombros y Tríceps')"),
         "fecha": ("string", "Fecha YYYY-MM-DD, 'ayer', o 'hoy'"),
         "tipo": ("string", "push, pull, pierna, fullbody, cardio, etc."),
         "grupos_musculares": {"type": "array", "items": {"type": "string"},
                               "description": "Grupos trabajados: ['pecho', 'hombros', 'triceps']"},
         "ejercicios_raw": ("string", "Texto EXACTO del usuario con los ejercicios, copiado tal cual. NO modifiques ni interpretes los datos."),
         "notas": ("string", "Notas generales del entrenamiento")},
        required=["nombre", "fecha", "ejercicios_raw"]),

    _fn("gym_start_session",
        ("Inicia una sesión de gym para registrar ejercicios uno por uno. "
         "Úsalo cuando el usuario quiere anotar ejercicios línea por línea. "
         "Después usa gym_add_exercise y al final gym_end_session."),
        {"nombre": ("string", "Nombre del entrenamiento (ej: 'Push - Pecho y Tríceps')"),
         "fecha": ("string", "Fecha YYYY-MM-DD, 'ayer', o 'hoy'"),
         "tipo": ("string", "push, pull, pierna, fullbody, cardio, etc."),
         "grupos_musculares": {"type": "array", "items": {"type": "string"},
                               "description": "Grupos trabajados"}},
        required=["nombre", "fecha", "tipo"]),

    _fn("gym_add_exercise",
        "Agrega uno o más ejercicios a la sesión de gym activa. Pasa el texto EXACTO del usuario.",
        {"ejercicio_raw": ("string", "Texto EXACTO del usuario con el/los ejercicio(s), tal cual.")},
        required=["ejercicio_raw"]),

    _fn("gym_end_session",
        "Finaliza la sesión de gym activa y guarda todos los ejercicios en MongoDB.",
        {"notas": ("string", "Notas adicionales del entrenamiento")}),

    _fn("gym_get_recent",
        "Obtiene los últimos entrenamientos registrados en la base de datos de gym.",
        {"limit": ("integer", "Número de entrenamientos a retornar (default: 10)")}),

    _fn("gym_exercise_history",
        "Ver el historial y progresión de un ejercicio específico (peso, series, reps a lo largo del tiempo).",
        {"exercise_name": ("string", "Nombre del ejercicio (ej: 'Sentadilla', 'Press banca')"),
         "limit": ("integer", "Número de registros a retornar")},
        required=["exercise_name"]),

    _fn("gym_save_routine",
        "Guarda una rutina de entrenamiento generada para usarla después.",
        {"name": ("string", "Nombre de la rutina"),
         "description": ("string", "Descripción y objetivo de la rutina"),
         "exercises": {"type": "array", "description": "Ejercicios de la rutina",
                       "items": {"type": "object", "properties": {
                           "name": {"type": "string"}, "muscle_group": {"type": "string"},
                           "sets": {"type": "integer"}, "reps": {"type": "string"},
                           "rest_seconds": {"type": "integer"}, "notes": {"type": "string"}}}}},
        required=["name", "exercises"]),

    _fn_empty("gym_get_routines", "Obtiene todas las rutinas guardadas en la base de datos."),
    _fn_empty("gym_get_stats", "Obtiene estadísticas de gym: total entrenamientos, ejercicios más frecuentes, etc."),

    # ── Notas ──────────────────────────────────────────────────────────────────
    _fn("note_save",
        "Guarda una nota personal del usuario. Puede tener título, contenido y tags.",
        {"title": ("string", "Título de la nota"),
         "content": ("string", "Contenido de la nota (markdown)"),
         "tags": ("string", "Tags separados por coma (ej: 'ideas,proyecto,urgente')")},
        required=["title", "content"]),

    _fn("note_list",
        "Lista las notas del usuario ordenadas por fecha de actualización.",
        {"limit": ("integer", "Número de notas a retornar (default: 20)")}),

    _fn("note_search",
        "Busca notas por título, contenido o tags.",
        {"query": ("string", "Término de búsqueda")},
        required=["query"]),

    _fn("note_delete",
        "Elimina una nota por su ID.",
        {"note_id": ("string", "ID de la nota a eliminar")},
        required=["note_id"]),

    # ── Email ──────────────────────────────────────────────────────────────────
    _fn("email_list",
        "Lista los últimos correos electrónicos del usuario (solo lectura). Muestra remitente, asunto y fecha.",
        {"folder": ("string", "Carpeta IMAP (default: INBOX)"),
         "limit": ("integer", "Número de correos a retornar (default: 10)")}),

    _fn("email_read",
        "Lee el contenido completo de un correo electrónico por su ID numérico.",
        {"email_id": ("string", "ID del correo (obtenido de email_list)"),
         "folder": ("string", "Carpeta IMAP (default: INBOX)")},
        required=["email_id"]),

    _fn("email_search",
        "Busca correos electrónicos por asunto o remitente.",
        {"query": ("string", "Texto a buscar en asunto o remitente"),
         "folder": ("string", "Carpeta IMAP (default: INBOX)"),
         "limit": ("integer", "Número máximo de resultados")},
        required=["query"]),

    _fn("email_send",
        "Envía un correo electrónico a cualquier dirección.",
        {"to": ("string", "Dirección de email del destinatario"),
         "subject": ("string", "Asunto del correo"),
         "body": ("string", "Cuerpo del correo (texto plano)")},
        required=["to", "subject", "body"]),

    # ── Calendario ─────────────────────────────────────────────────────────────
    _fn_empty("calendar_today", "Obtiene los eventos del calendario de hoy."),

    _fn("calendar_upcoming",
        "Obtiene los próximos eventos del calendario en los siguientes N días.",
        {"days": ("integer", "Días hacia adelante (default: 7)"),
         "limit": ("integer", "Máximo de eventos (default: 15)")}),

    _fn("calendar_add_event",
        "Agenda un NUEVO evento o reunión en el calendario de Google del usuario.",
        {"title": ("string", "Título del evento o reunión"),
         "start_datetime": ("string", "Fecha y hora de inicio (Formato ISO 8601, ej: '2026-02-28T14:00:00')"),
         "end_datetime": ("string", "Fecha y hora de fin (Formato ISO 8601, ej: '2026-02-28T15:00:00')"),
         "description": ("string", "Descripción opcional del evento (sin usar si no lo mencionan)")},
        required=["title", "start_datetime", "end_datetime"]),

    # ── Summarizer ─────────────────────────────────────────────────────────────
    _fn("summarize_url",
        ("Descarga el contenido de una URL (página web, artículo, blog) y extrae el texto. "
         "Úsalo cuando el usuario pida un resumen de una página web."),
        {"url": ("string", "URL de la página a resumir")},
        required=["url"]),

    # ── Deep Think ─────────────────────────────────────────────────────────────
    _fn("deep_think",
        ("Delega una tarea compleja a un modelo de razonamiento profundo. "
         "Úsalo para: análisis detallado, planificación, código complejo, debugging. "
         "NO uses esto para preguntas simples o saludos."),
        {"task": ("string", "La tarea o pregunta que requiere razonamiento profundo"),
         "context": ("string", "Contexto adicional: código, datos, texto a analizar (opcional)")},
        required=["task"]),

    # ── Recordatorios ──────────────────────────────────────────────────────────
    _fn("set_reminder",
        ("Programa un recordatorio. Después del delay, se enviará un mensaje al chat. "
         "Úsalo cuando el usuario diga 'recuérdame', 'avísame', 'en X minutos', etc."),
        {"message": ("string", "Texto del recordatorio"),
         "delay_seconds": ("integer", "Segundos de espera. Ej: 300=5min, 3600=1hora")},
        required=["message", "delay_seconds"]),

    _fn_empty("list_reminders", "Lista los recordatorios activos (pendientes)."),
    _fn_empty("cancel_reminders", "Cancela todos los recordatorios activos."),

    # ── Memoria ────────────────────────────────────────────────────────────────
    _fn("remember_fact",
        "Guarda un hecho importante sobre el usuario en la memoria a largo plazo.",
        {"fact": ("string", "Hecho a recordar sobre el usuario"),
         "category": ("string", "Categoría: 'preferencia', 'personal', 'habito', 'trabajo', 'general' (default: general)")},
        required=["fact"]),

    # ── Cronjobs (tareas programadas del agente) ───────────────────────────────────
    _fn("cronjob_create",
        ("Crea una tarea programada para el agente. El agente ejecutará el 'prompt' "
         "automáticamente según la expresión cron. Ejemplo: '0 8 * * *' = cada día a las 8am."),
        {"name": ("string", "Nombre de la tarea (ej: 'Noticias mañaneras')"),
         "cron_expr": ("string", "Expresión cron: '* * * * *' = minuto hora día mes dia_semana"),
         "prompt": ("string", "Qué debe hacer el agente cuando se ejecute la tarea"),
         "description": ("string", "Descripción opcional de la tarea"),
         "timezone": ("string", "Timezone (default: UTC, ej: America/Bogota)")},
        required=["name", "cron_expr", "prompt"]),

    _fn_empty("cronjob_list",
        ("Lista todas las tareas programadas del agente. "
         "USA ESTO PRIMERO para obtener el job_id antes de eliminar, pausar o modificar cualquier tarea.")),

    _fn("cronjob_delete",
        ("Elimina permanentemente una tarea programada. "
         "FLUJO CORRECTO: 1) llama cronjob_list para obtener el job_id, "
         "2) llama cronjob_delete con ese job_id. "
         "NUNCA uses run_command ni curl para esto."),
        {"job_id": ("string", "ID exacto de la tarea, obtenido de cronjob_list (ej: 'cron-1234567890')")},
        required=["job_id"]),

    _fn("cronjob_update",
        ("Actualiza una tarea programada: cambia nombre, cron, prompt, o activa/pausa. "
         "FLUJO CORRECTO: 1) llama cronjob_list para obtener el job_id, "
         "2) llama cronjob_update con ese job_id y los campos a cambiar. "
         "Para pausar una tarea usa enabled=false. Para reactivar usa enabled=true."),
        {"job_id": ("string", "ID de la tarea, obtenido de cronjob_list"),
         "name": ("string", "Nuevo nombre (opcional)"),
         "cron_expr": ("string", "Nueva expresión cron (opcional)"),
         "prompt": ("string", "Nuevo prompt (opcional)"),
         "enabled": ("boolean", "true=activar, false=pausar (opcional)")},
        required=["job_id"]),

    _fn("cronjob_run_now",
        ("Ejecuta una tarea programada ahora mismo, sin esperar su próxima ejecución. "
         "FLUJO CORRECTO: 1) llama cronjob_list para obtener el job_id, "
         "2) llama cronjob_run_now con ese job_id."),
        {"job_id": ("string", "ID de la tarea a ejecutar ahora, obtenido de cronjob_list")},
        required=["job_id"]),
]


# ─── Dispatcher ───────────────────────────────────────────────────────────────

class ToolDispatcher:
    def __init__(self, memory=None, user_id: str = "", room_id: str = ""):
        self._gym = GymDB()
        self._notes = NotesDB()
        self._memory = memory
        self._user_id = user_id
        self._room_id = room_id
        self._gym_session = None  # Buffer de sesión: {nombre, fecha, tipo, grupos, ejercicios}

    @property
    def has_gym_session(self) -> bool:
        return self._gym_session is not None

    async def init(self):
        await self._gym.init()
        await self._notes.init()

    def set_context(self, user_id: str, room_id: str) -> None:
        """Actualiza el contexto por mensaje (user_id, room_id) sin reinicializar conexiones."""
        self._user_id = user_id
        self._room_id = room_id

    async def dispatch(self, tool_name: str, args: dict) -> str:
        """Ejecuta la tool solicitada y retorna el resultado como string JSON."""
        try:
            result = await self._execute(tool_name, args)
        except Exception as e:
            result = {"error": f"Error interno en tool '{tool_name}': {str(e)}"}

        return json.dumps(result, ensure_ascii=False, indent=2)

    async def _execute(self, tool_name: str, args: dict) -> dict:
        match tool_name:
            # Shell
            case "run_command":
                return await run_command(
                    args["command"], args.get("timeout", 30), self._user_id or "unknown"
                )

            # Files
            case "read_file":
                return await read_file(args["path"])
            case "write_file":
                return await write_file(args["path"], args["content"], args.get("append", False))
            case "list_dir":
                return await list_dir(args.get("path", "."))

            # Web
            case "web_search":
                return await search(args["query"], args.get("max_results", 5), args.get("search_type", "text"))
            case "get_weather":
                return get_weather(args.get("location", "Medellin"))

            # Browser
            case "browser_navigate":
                browser = await BrowserTool.get_instance()
                return await browser.navigate(args["url"])
            case "browser_get_text":
                browser = await BrowserTool.get_instance()
                return await browser.get_page_text()
            case "browser_click":
                browser = await BrowserTool.get_instance()
                return await browser.click(args["selector"])
            case "browser_fill":
                browser = await BrowserTool.get_instance()
                return await browser.fill(args["selector"], args["text"])

            # Samsung TV (SmartThings)
            case "samsung_list_devices":
                return list_devices()
            case "samsung_tv_status":
                return tv_status(args.get("device_id"))
            case "samsung_tv_control":
                return tv_control(action=args["command"], device_name=args.get("device_id"))

            # Gym — Entrenamiento completo
            case "gym_save_workout":
                raw_text = args.get("ejercicios_raw", "")
                exercises = parse_workout_text(raw_text) if raw_text else args.get("ejercicios", [])
                return await self._gym.save_workout(
                    name=args["nombre"], date_str=args["fecha"],
                    exercises=exercises, tipo=args.get("tipo", ""),
                    grupos_musculares=args.get("grupos_musculares"),
                    notes=args.get("notas", ""),
                )

            # Gym — Sesión línea por línea
            case "gym_start_session":
                if self._gym_session:
                    return {"error": "Ya hay una sesión activa. Usa gym_end_session primero."}
                self._gym_session = {
                    "nombre": args["nombre"], "fecha": args["fecha"],
                    "tipo": args["tipo"],
                    "grupos_musculares": args.get("grupos_musculares", []),
                    "ejercicios": [],
                }
                return {
                    "success": True,
                    "message": f"Sesión iniciada: {args['nombre']}",
                    "tip": "Manda ejercicios uno por uno. Di 'listo' para guardar.",
                }

            case "gym_add_exercise":
                if not self._gym_session:
                    return {"error": "No hay sesión de gym activa. Usa gym_start_session primero."}
                raw = args["ejercicio_raw"]
                parsed = parse_workout_text(raw)
                if not parsed:
                    return {"error": f"No pude parsear: '{raw}'. Revisa el formato."}
                self._gym_session["ejercicios"].extend(parsed)
                return {
                    "success": True,
                    "added": [e["nombre"] for e in parsed],
                    "added_count": len(parsed),
                    "total_exercises": len(self._gym_session["ejercicios"]),
                }

            case "gym_end_session":
                if not self._gym_session:
                    return {"error": "No hay sesión de gym activa."}
                session = self._gym_session
                self._gym_session = None
                if not session["ejercicios"]:
                    return {"error": "La sesión no tiene ejercicios. No se guardó nada."}
                result = await self._gym.save_workout(
                    name=session["nombre"], date_str=session["fecha"],
                    exercises=session["ejercicios"], tipo=session["tipo"],
                    grupos_musculares=session["grupos_musculares"],
                    notes=args.get("notas", ""),
                )
                result["total_exercises"] = len(session["ejercicios"])
                result["total_series"] = sum(e["series"] for e in session["ejercicios"])
                return result

            case "gym_get_recent":
                return await self._gym.get_recent_workouts(args.get("limit", 10))
            case "gym_exercise_history":
                return await self._gym.get_exercise_history(
                    args["exercise_name"], args.get("limit", 10))
            case "gym_save_routine":
                return await self._gym.save_routine(
                    args["name"], args.get("description", ""), args["exercises"])
            case "gym_get_routines":
                return await self._gym.get_routines()
            case "gym_get_stats":
                return await self._gym.get_stats()

            # Notes
            case "note_save":
                return await self._notes.save_note(
                    self._user_id, args["title"], args["content"], args.get("tags", ""))
            case "note_list":
                return await self._notes.get_notes(self._user_id, args.get("limit", 20))
            case "note_search":
                return await self._notes.search_notes(self._user_id, args["query"])
            case "note_delete":
                return await self._notes.delete_note(self._user_id, args["note_id"])

            # Email
            case "email_list":
                return await list_emails(args.get("folder", "INBOX"), args.get("limit", 10))
            case "email_read":
                return await read_email(args["email_id"], args.get("folder", "INBOX"))
            case "email_search":
                return await search_emails(
                    args["query"], args.get("folder", "INBOX"), args.get("limit", 10))
            case "email_send":
                return await send_email(args["to"], args["subject"], args["body"])

            # Calendar
            case "calendar_today":
                return await get_today_events()
            case "calendar_upcoming":
                return await get_upcoming_events(args.get("days", 7), args.get("limit", 15))
            case "calendar_add_event":
                return await add_event(
                    args["title"], args["start_datetime"], args["end_datetime"], args.get("description", "")
                )

            # Summarizer
            case "summarize_url":
                return await fetch_and_summarize(args["url"])

            # Reminders
            case "set_reminder":
                return await reminder_manager.add_reminder(
                    args["message"], args["delay_seconds"],
                    self._room_id or "unknown", self._user_id or "unknown",
                )
            case "list_reminders":
                return await reminder_manager.list_reminders(self._room_id)
            case "cancel_reminders":
                return await reminder_manager.cancel_all(self._room_id)

            # Deep Think
            case "deep_think":
                return await deep_think(args["task"], args.get("context", ""))

            # Memory
            case "remember_fact":
                if self._memory and self._user_id:
                    await self._memory.save_fact(
                        self._user_id, args["fact"], args.get("category", "general")
                    )
                return {"success": True, "fact_saved": args["fact"], "category": args.get("category", "general")}

            # Cronjobs — tareas programadas del agente
            case "cronjob_create":
                sched = get_scheduler()
                if not sched:
                    return {"error": "Scheduler no inicializado. Reinicia Jada."}
                import time as _time
                job_id = f"cron-{int(_time.time())}"
                job = sched.add_job(
                    job_id=job_id,
                    name=args["name"],
                    cron_expr=args["cron_expr"],
                    prompt=args["prompt"],
                    room_id=self._room_id or "unknown",
                    description=args.get("description", ""),
                    timezone_str=args.get("timezone", "UTC"),
                )
                if job.get("_duplicate"):
                    return {
                        "success": False,
                        "duplicate": True,
                        "existing_id": job["id"],
                        "message": f"⚠️ Ya existe una tarea igual: '{job['name']}' (ID: {job['id']}). No se creó un duplicado.",
                    }
                return {"success": True, "job": job, "message": f"✅ Tarea '{args['name']}' creada con ID {job['id']}"}

            case "cronjob_list":
                sched = get_scheduler()
                if not sched:
                    return {"error": "Scheduler no inicializado."}
                return {"jobs": sched.list_jobs(), "status": sched.get_status()}

            case "cronjob_delete":
                sched = get_scheduler()
                if not sched:
                    return {"error": "Scheduler no inicializado."}
                deleted = sched.delete_job(args["job_id"])
                return {"success": deleted, "message": f"Tarea {'eliminada' if deleted else 'no encontrada'}"}

            case "cronjob_update":
                sched = get_scheduler()
                if not sched:
                    return {"error": "Scheduler no inicializado."}
                update_args = {k: v for k, v in args.items() if k != "job_id"}
                updated = sched.update_job(args["job_id"], **update_args)
                return {"success": bool(updated), "job": updated}

            case "cronjob_run_now":
                sched = get_scheduler()
                if not sched:
                    return {"error": "Scheduler no inicializado."}
                job = sched.get_job(args["job_id"])
                if not job:
                    return {"error": f"Tarea '{args['job_id']}' no encontrada"}
                asyncio.create_task(sched._execute_job(job))
                return {"success": True, "message": f"⏰ Tarea '{job['name']}' ejecutándose ahora"}

            case _:
                return {"error": f"Tool desconocida: '{tool_name}'"}