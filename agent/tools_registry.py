"""
agent/tools_registry.py — Traductor de las funciones nativas a Agno Tools.

Aquí registramos todas las funciones de `tools/` en la clase base de Agno `Tool` 
para que el Agente infiera automáticamente los schemas Pydantic y las invoque.
"""
import asyncio
import json
from typing import Optional, List, Dict, Any

import logging
from agno.tools import Toolkit

logger = logging.getLogger(__name__)
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
from tools.image_gen import generate_image
from tools.supabase_storage import upload_file, list_files, download_file, delete_file
from tools.pdf_reader import read_pdf, render_pdf_pages
from tools.reddit import reddit_trending, reddit_subreddit, reddit_search


class JadaTools(Toolkit):
    """
    Agrupa todas las herramientas del sistema Jada para el Agente Agno.
    Agno convierte los Docstrings y Type Hints de estos métodos en JSON Schemas.
    """

    # ── Tool groups: maps group_name → list of method names ──
    GROUPS = {
        "notes": ["note_save", "note_list", "note_search", "note_delete"],
        "email": ["email_list", "email_read", "email_search", "email_send"],
        "calendar": ["calendar_today", "calendar_upcoming", "calendar_add_event"],
        "gym": ["gym_save_workout", "gym_start_session", "gym_add_exercise",
                "gym_end_session", "gym_get_recent", "gym_exercise_history",
                "gym_save_routine", "gym_get_routines", "gym_get_stats"],
        "tv": ["samsung_list_devices", "samsung_tv_status", "samsung_tv_control"],
        "reminders": ["set_reminder", "list_reminders", "cancel_reminders"],
        "cronjobs": ["cronjob_create", "cronjob_list", "cronjob_delete",
                     "cronjob_update", "cronjob_run_now"],
        "web": ["web_search", "get_weather", "summarize_url", "browser_navigate",
                "browser_get_text", "browser_click", "browser_fill"],
        "files": ["run_command", "read_file", "write_file", "list_dir"],
        "media": ["generate_image", "send_file", "describe_image"],
        "storage": ["storage_upload", "storage_list", "storage_download", "storage_delete", "read_file", "send_file", "read_pdf", "describe_image"],
        "think": ["deep_think"],
        "reddit": ["reddit_trending", "reddit_subreddit", "reddit_search"],
    }

    def __init__(self, user_id: str = "", room_id: str = "", bot: Any = None,
                 groups: list[str] | None = None):
        super().__init__(name="jada_tools")
        self.user_id = user_id
        self.room_id = room_id
        self.bot = bot
        
        # Conexiones DB que requiere await init()
        self.gym_db = GymDB()
        self.notes_db = NotesDB()
        self._gym_session: Optional[Dict[str, Any]] = None

        if groups is not None:
            # ── Selective registration: only register tools from specified groups ──
            self._register_groups(groups)
        else:
            # ── Full registration: all 44 tools ──
            self._register_all()

    def _register_groups(self, groups: list[str]):
        """Register only tools from the specified groups."""
        method_names: set[str] = set()
        for g in groups:
            method_names.update(self.GROUPS.get(g, []))
        for name in method_names:
            method = getattr(self, name, None)
            if method:
                self.register(method)

    def _register_all(self):
        """Register all tools (full toolkit)."""
        all_groups = list(self.GROUPS.keys())
        self._register_groups(all_groups)

    @staticmethod
    def _compress_output(tool_name: str, raw_output: str, max_chars: int = 1500) -> str:
        """Compress tool outputs to reduce context tokens sent to the LLM."""
        import json
        if len(raw_output) < 400:
            return raw_output
        try:
            data = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError):
            # Plain text — truncate
            if len(raw_output) > max_chars:
                return raw_output[:max_chars] + "\n... [truncado]"
            return raw_output

        # Web search: trim snippets, strip URLs to domain
        if tool_name in ("web_search",) and "results" in data:
            from urllib.parse import urlparse
            for r in data["results"]:
                if "snippet" in r and len(r["snippet"]) > 120:
                    r["snippet"] = r["snippet"][:120] + "..."
                if "url" in r:
                    try:
                        r["url"] = urlparse(r["url"]).netloc
                    except Exception:
                        pass
            data.pop("engine", None)

        # Email: trim long "from" headers
        if tool_name in ("email_list", "email_search") and "emails" in data:
            for e in data["emails"]:
                if "from" in e and len(e["from"]) > 60:
                    e["from"] = e["from"][:60] + "..."
            data.pop("fetched_at", None)
            data.pop("total_in_period", None)

        # Browser text: cap at 2000 chars
        if tool_name == "browser_get_text" and isinstance(data, dict):
            for k in data:
                if isinstance(data[k], str) and len(data[k]) > 2000:
                    data[k] = data[k][:2000] + "\n... [truncado]"

        compressed = json.dumps(data, ensure_ascii=False)
        if len(compressed) > max_chars:
            return compressed[:max_chars] + "..."
        return compressed


    async def init_databases(self):
        """Inicializa las conexiones a bases de datos antes del primer uso."""
        await self.gym_db.init()
        await self.notes_db.init()

    def set_context(self, user_id: str, room_id: str, bot: Any = None):
        """Set per-request context (user, room, bot) for tool execution."""
        self.user_id = user_id
        self.room_id = room_id
        if bot is not None:
            self.bot = bot

    # ── Shell ──────────────────────────────────────────────────────────────────
    def run_command(self, command: str, timeout: int = 30) -> str:
        """
        Ejecuta un comando de shell/terminal en el sistema (modo whitelist). 
        Retorna stdout, stderr y código de salida.
        
        Args:
            command: Comando a ejecutar
            timeout: Timeout en segundos (default: 30)
        """
        # Agno Tool functions are sync by default. Our tools are mostly async.
        # So we wrap them in a helper or make the Tool async compatible if agno supports it.
        # (Agno natively supports `async def` methods since v2.x!)
        pass # Placeholder here, the definition will be async downstairs

    async def run_command(self, command: str, timeout: int = 30) -> str:
        """
        Ejecuta un comando de shell/terminal en el sistema (modo whitelist). 
        Retorna stdout, stderr y código de salida.
        
        Args:
            command: Comando a ejecutar
            timeout: Timeout en segundos (default: 30)
        """
        import json
        res = await run_command(command, timeout, self.user_id or "unknown")
        return json.dumps(res, ensure_ascii=False)

    # ── Archivos ───────────────────────────────────────────────────────────────
    async def read_file(self, path: str) -> str:
        """Lee el contenido de un archivo del sistema."""
        import json; return json.dumps(await read_file(path), ensure_ascii=False)

    async def write_file(self, path: str, content: str, append: bool = False) -> str:
        """Crea o sobreescribe un archivo. Puede añadir al final si append=True."""
        import json; return json.dumps(await write_file(path, content, append), ensure_ascii=False)

    async def list_dir(self, path: str = ".") -> str:
        """Lista el contenido (archivos y carpetas) de un directorio."""
        import json; return json.dumps(await list_dir(path), ensure_ascii=False)

    # ── Web ────────────────────────────────────────────────────────────────────
    async def web_search(self, query: str, max_results: int = 5, search_type: str = "text") -> str:
        """
        Busca información en la web usando DuckDuckGo o Google News. Retorna títulos, URLs y snippets.
        
        Args:
            query: Consulta de búsqueda (Si es noticias, usa SOLO palabras clave como 'Colombia' o 'Tecnología', SIN fechas ni palabras como 'hoy')
            max_results: Número máximo de resultados
            search_type: Tipo de búsqueda: 'text' o 'news'
        """
        import json
        raw = json.dumps(await search(query, max_results, search_type), ensure_ascii=False)
        return self._compress_output("web_search", raw)

    def get_weather(self, location: str = "Medellin") -> str:
        """
        Obtiene el clima actual, temperatura y posibilidad de lluvia de una ciudad.
        """
        import json; return json.dumps(get_weather(location), ensure_ascii=False)

    # ── Browser ────────────────────────────────────────────────────────────────
    async def browser_navigate(self, url: str) -> str:
        """Navega a una URL en el browser. Úsalo para abrir páginas web."""
        browser = await BrowserTool.get_instance()
        import json; return json.dumps(await browser.navigate(url), ensure_ascii=False)

    async def browser_get_text(self) -> str:
        """Extrae el texto visible de la página actualmente abierta en el browser."""
        browser = await BrowserTool.get_instance()
        import json
        raw = json.dumps(await browser.get_page_text(), ensure_ascii=False)
        return self._compress_output("browser_get_text", raw, max_chars=2000)

    async def browser_click(self, selector: str) -> str:
        """Hace click en un elemento de la página usando un selector CSS o texto visible."""
        browser = await BrowserTool.get_instance()
        import json; return json.dumps(await browser.click(selector), ensure_ascii=False)

    async def browser_fill(self, selector: str, text: str) -> str:
        """Rellena un campo de formulario en la página actual."""
        browser = await BrowserTool.get_instance()
        import json; return json.dumps(await browser.fill(selector, text), ensure_ascii=False)

    # ── Samsung TV (SmartThings) ───────────────────────────────────────────────
    def samsung_list_devices(self) -> str:
        """Lista todos los dispositivos disponibles en SmartThings (incluye TVs)."""
        import json; return json.dumps(list_devices(), ensure_ascii=False)

    def samsung_tv_status(self, device_id: Optional[str] = None) -> str:
        """Obtiene el estado actual del TV (encendido/apagado)."""
        import json; return json.dumps(tv_status(device_id), ensure_ascii=False)

    def samsung_tv_control(self, command: str, device_id: Optional[str] = None) -> str:
        """
        Controla el Samsung TV: enciéndelo, apágalo, sube/baja volumen o silencia.
        
        Args:
            command: Comando: 'on', 'off', 'up', 'down', 'mute', 'unmute', 'ok', 'back', 'home', 'menu', 'source', 'hdmi1', 'hdmi2', 'hdmi3'
            device_id: ID del dispositivo TV (Opcional)
        """
        import json; return json.dumps(tv_control(action=command, device_name=device_id), ensure_ascii=False)

    # ── Gym ────────────────────────────────────────────────────────────────────
    async def gym_save_workout(
        self, 
        nombre: str, 
        fecha: str, 
        ejercicios_raw: str, 
        tipo: str = "", 
        grupos_musculares: Optional[List[str]] = None, 
        notas: str = "",
        ejercicios: Optional[List[dict]] = None
    ) -> str:
        """
        Guarda un entrenamiento COMPLETO de gym en MongoDB. Usa esto cuando el usuario
        manda TODOS los ejercicios en un solo mensaje. 
        
        Args:
            nombre: Nombre descriptivo (ej: 'Push - Pecho, Hombros y Tríceps')
            fecha: Fecha YYYY-MM-DD, 'ayer', o 'hoy'
            ejercicios_raw: Texto EXACTO del usuario con los ejercicios, copiado tal cual. NO modifiques ni interpretes los datos.
            tipo: push, pull, pierna, fullbody, cardio, etc.
            grupos_musculares: Grupos trabajados: ['pecho', 'hombros', 'triceps']
            notas: Notas generales del entrenamiento
        """
        import json
        raw_text = ejercicios_raw
        parsed_exercises = parse_workout_text(raw_text) if raw_text else (ejercicios or [])
        res = await self.gym_db.save_workout(
            name=nombre, date_str=fecha,
            exercises=parsed_exercises, tipo=tipo,
            grupos_musculares=grupos_musculares,
            notes=notas,
        )
        return json.dumps(res, ensure_ascii=False)

    async def gym_start_session(
        self, 
        nombre: str, 
        fecha: str, 
        tipo: str, 
        grupos_musculares: Optional[List[str]] = None
    ) -> str:
        """
        Inicia una sesión de gym para registrar ejercicios uno por uno.
        Úsalo cuando el usuario quiere anotar ejercicios línea por línea.
        Después usa gym_add_exercise y al final gym_end_session.
        
        Args:
            nombre: Nombre del entrenamiento (ej: 'Push - Pecho y Tríceps')
            fecha: Fecha YYYY-MM-DD, 'ayer', o 'hoy'
            tipo: push, pull, pierna, fullbody, cardio, etc.
            grupos_musculares: Grupos trabajados
        """
        import json
        if self._gym_session:
            return json.dumps({"error": "Ya hay una sesión activa. Usa gym_end_session primero."}, ensure_ascii=False)
        self._gym_session = {
            "nombre": nombre, "fecha": fecha,
            "tipo": tipo,
            "grupos_musculares": grupos_musculares or [],
            "ejercicios": [],
        }
        return json.dumps({
            "success": True,
            "message": f"Sesión iniciada: {nombre}",
            "tip": "Manda ejercicios uno por uno. Di 'listo' para guardar.",
        }, ensure_ascii=False)

    async def gym_add_exercise(self, ejercicio_raw: str) -> str:
        """
        Agrega uno o más ejercicios a la sesión de gym activa. 
        
        Args:
            ejercicio_raw: Texto EXACTO del usuario con el/los ejercicio(s), tal cual.
        """
        import json
        if not self._gym_session:
            return json.dumps({"error": "No hay sesión de gym activa. Usa gym_start_session primero."}, ensure_ascii=False)
        parsed = parse_workout_text(ejercicio_raw)
        if not parsed:
            return json.dumps({"error": f"No pude parsear: '{ejercicio_raw}'. Revisa el formato."}, ensure_ascii=False)
        self._gym_session["ejercicios"].extend(parsed)
        return json.dumps({
            "success": True,
            "added": [e["nombre"] for e in parsed],
            "added_count": len(parsed),
            "total_exercises": len(self._gym_session["ejercicios"]),
        }, ensure_ascii=False)

    async def gym_end_session(self, notas: str = "") -> str:
        """
        Finaliza la sesión de gym activa y guarda todos los ejercicios en MongoDB.
        
        Args:
            notas: Notas adicionales del entrenamiento
        """
        import json
        if not self._gym_session:
            return json.dumps({"error": "No hay sesión de gym activa."}, ensure_ascii=False)
        session = self._gym_session
        self._gym_session = None
        if not session["ejercicios"]:
            return json.dumps({"error": "La sesión no tiene ejercicios. No se guardó nada."}, ensure_ascii=False)
        result = await self.gym_db.save_workout(
            name=session["nombre"], date_str=session["fecha"],
            exercises=session["ejercicios"], tipo=session["tipo"],
            grupos_musculares=session["grupos_musculares"],
            notes=notas,
        )
        result["total_exercises"] = len(session["ejercicios"])
        result["total_series"] = sum(e["series"] for e in session["ejercicios"])
        return json.dumps(result, ensure_ascii=False)

    async def gym_get_recent(self, limit: int = 10) -> str:
        """Obtiene los últimos entrenamientos registrados en la base de datos de gym."""
        import json; return json.dumps(await self.gym_db.get_recent_workouts(limit), ensure_ascii=False)

    async def gym_exercise_history(self, exercise_name: str, limit: int = 10) -> str:
        """
        Ver el historial y progresión de un ejercicio específico (peso, series, reps a lo largo del tiempo).
        
        Args:
            exercise_name: Nombre del ejercicio (ej: 'Sentadilla', 'Press banca')
        """
        import json; return json.dumps(await self.gym_db.get_exercise_history(exercise_name, limit), ensure_ascii=False)

    async def gym_save_routine(self, name: str, exercises: List[dict], description: str = "") -> str:
        """Guarda una rutina de entrenamiento generada para usarla después."""
        import json; return json.dumps(await self.gym_db.save_routine(name, description, exercises), ensure_ascii=False)

    async def gym_get_routines(self) -> str:
        """Obtiene todas las rutinas guardadas en la base de datos."""
        import json; return json.dumps(await self.gym_db.get_routines(), ensure_ascii=False)

    async def gym_get_stats(self) -> str:
        """Obtiene estadísticas de gym: total entrenamientos, ejercicios más frecuentes, etc."""
        import json; return json.dumps(await self.gym_db.get_stats(), ensure_ascii=False)

    # ── Notas ──────────────────────────────────────────────────────────────────
    async def note_save(self, title: str, content: str, tags: str = "") -> str:
        """Guarda una nota personal del usuario. Puede tener título, contenido (markdown) y tags (separados por coma)."""
        import json; return json.dumps(await self.notes_db.save_note(self.user_id, title, content, tags), ensure_ascii=False)

    async def note_list(self, limit: int = 20) -> str:
        """Lista las notas del usuario ordenadas por fecha de actualización."""
        import json; return json.dumps(await self.notes_db.get_notes(self.user_id, limit), ensure_ascii=False)

    async def note_search(self, query: str) -> str:
        """Busca notas por título, contenido o tags."""
        import json; return json.dumps(await self.notes_db.search_notes(self.user_id, query), ensure_ascii=False)

    async def note_delete(self, note_id: str) -> str:
        """Elimina una nota por su ID."""
        import json; return json.dumps(await self.notes_db.delete_note(self.user_id, note_id), ensure_ascii=False)

    # ── Email ──────────────────────────────────────────────────────────────────
    async def email_list(self, folder: str = "INBOX", limit: int = 10, unread_only: bool = False) -> str:
        """Lista los últimos correos electrónicos del usuario (solo lectura). Muestra remitente, asunto y fecha. Usa unread_only=True para ver solo los no leídos."""
        import json
        raw = json.dumps(await list_emails(folder, limit, unread_only), ensure_ascii=False)
        return self._compress_output("email_list", raw)

    async def email_read(self, email_id: str, folder: str = "INBOX") -> str:
        """Lee el contenido completo de un correo electrónico por su ID numérico."""
        import json; return json.dumps(await read_email(email_id, folder), ensure_ascii=False)

    async def email_search(self, query: str, folder: str = "INBOX", limit: int = 10) -> str:
        """Busca correos electrónicos por asunto o remitente."""
        import json; return json.dumps(await search_emails(query, folder, limit), ensure_ascii=False)

    async def email_send(self, to: str, subject: str, body: str) -> str:
        """Envía un correo electrónico a cualquier dirección."""
        import json; return json.dumps(await send_email(to, subject, body), ensure_ascii=False)

    # ── Calendario ─────────────────────────────────────────────────────────────
    async def calendar_today(self) -> str:
        """Obtiene los eventos del calendario de hoy."""
        import json; return json.dumps(await get_today_events(), ensure_ascii=False)

    async def calendar_upcoming(self, days: int = 7, limit: int = 15) -> str:
        """Obtiene los próximos eventos del calendario en los siguientes N días."""
        import json; return json.dumps(await get_upcoming_events(days, limit), ensure_ascii=False)

    async def calendar_add_event(self, title: str, start_datetime: str, end_datetime: str, description: str = "") -> str:
        """
        Agenda un NUEVO evento o reunión en el calendario de Google del usuario.
        
        Args:
            title: Título del evento o reunión
            start_datetime: Fecha y hora de inicio (Formato ISO 8601, ej: '2026-02-28T14:00:00')
            end_datetime: Fecha y hora de fin (Formato ISO 8601, ej: '2026-02-28T15:00:00')
        """
        import json; return json.dumps(await add_event(title, start_datetime, end_datetime, description), ensure_ascii=False)

    # ── Summarizer ─────────────────────────────────────────────────────────────
    async def summarize_url(self, url: str) -> str:
        """Descarga el contenido de una URL (página web, artículo, blog) y extrae el texto. Úsalo para resumir URLs."""
        import json; return json.dumps(await fetch_and_summarize(url), ensure_ascii=False)

    # ── Deep Think ─────────────────────────────────────────────────────────────
    async def deep_think(self, task: str, context: str = "") -> str:
        """Delega una tarea compleja a un modelo de razonamiento profundo. Para análisis detallado, debugging."""
        import json; return json.dumps(await deep_think(task, context), ensure_ascii=False)

    # ── Recordatorios ──────────────────────────────────────────────────────────
    async def set_reminder(self, message: str, delay_seconds: Optional[int] = None, time: Optional[str] = None) -> str:
        """
        Programa un recordatorio rápido. 
        
        Args:
            message: Mensaje del recordatorio.
            delay_seconds: Segundos de espera (opcional si usas 'time').
            time: Tiempo en texto (ej: '5 minutos', '1 hora', '30s').
        """
        import json
        from tools.reminders import parse_time_expression
        
        seconds = delay_seconds
        if time:
            parsed = parse_time_expression(time)
            if parsed:
                seconds = parsed
                
        if seconds is None:
            return json.dumps({"error": "Debes proporcionar 'delay_seconds' (int) o 'time' (str)."}, ensure_ascii=False)

        return json.dumps(await reminder_manager.add_reminder(
            message, seconds, self.room_id or "unknown", self.user_id or "unknown"
        ), ensure_ascii=False)

    async def list_reminders(self) -> str:
        """Lista los recordatorios activos (pendientes)."""
        import json; return json.dumps(await reminder_manager.list_reminders(self.room_id), ensure_ascii=False)

    async def cancel_reminders(self) -> str:
        """Cancela todos los recordatorios activos."""
        import json; return json.dumps(await reminder_manager.cancel_all(self.room_id), ensure_ascii=False)
        
    # ── Cronjobs (tareas programadas del agente) ───────────────────────────────────
    def cronjob_create(self, name: str, cron_expr: str, prompt: str, description: str = "", timezone: Optional[str] = None) -> str:
        """
        Crea una tarea programada para el agente. El agente ejecutará el 'prompt' automáticamente según la expresión cron.
        
        Args:
            name: Nombre de la tarea (ej: 'Noticias mañaneras')
            cron_expr: Expresión cron: '* * * * *' = minuto hora día mes dia_semana
            prompt: Qué debe hacer el agente cuando se ejecute la tarea
            timezone: Timezone (ej: America/Bogota, default: viene del .env o UTC)
        """
        from agent.scheduler import get_scheduler
        import time as _time
        import json
        import os
        
        sched = get_scheduler()
        timezone = timezone or os.getenv("TIMEZONE", "UTC")
        if not sched:
            return json.dumps({"error": "Scheduler no inicializado. Reinicia Jada."}, ensure_ascii=False)
            
        job_id = f"cron-{int(_time.time())}"
        job = sched.add_job(
            job_id=job_id,
            name=name,
            cron_expr=cron_expr,
            prompt=prompt,
            room_id=self.room_id or "unknown",
            description=description,
            timezone_str=timezone,
        )
        if job.get("_duplicate"):
            return json.dumps({
                "success": False,
                "duplicate": True,
                "existing_id": job["id"],
                "message": f"⚠️ Ya existe una tarea igual: '{job['name']}' (ID: {job['id']}). No se creó un duplicado.",
            }, ensure_ascii=False)
        return json.dumps({"success": True, "job": job, "message": f"✅ Tarea '{name}' creada con ID {job['id']}"}, ensure_ascii=False)

    def cronjob_list(self) -> str:
        """Lista todas las tareas programadas del agente. USA ESTO PRIMERO para obtener el job_id"""
        from agent.scheduler import get_scheduler
        import json
        sched = get_scheduler()
        if not sched:
            return json.dumps({"error": "Scheduler no inicializado."}, ensure_ascii=False)
        return json.dumps({"jobs": sched.list_jobs(), "status": sched.get_status()}, ensure_ascii=False)

    async def delete_file(self, url_or_path: str) -> str:
        """Elimina un archivo de Supabase Storage mediante su URL o path en el bucket."""
        import json
        is_success, error_msg = await delete_file(url_or_path, self.user_id)
        if not is_success:
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        return json.dumps({"success": True, "message": "Archivo eliminado"}, ensure_ascii=False)

    def cronjob_delete(self, job_id: str) -> str:
        """Elimina permanentemente una tarea programada dado su job_id."""
        from agent.scheduler import get_scheduler
        import json
        sched = get_scheduler()
        if not sched:
            return json.dumps({"error": "Scheduler no inicializado."}, ensure_ascii=False)
        deleted = sched.delete_job(job_id)
        return json.dumps({"success": deleted, "message": f"Tarea {'eliminada' if deleted else 'no encontrada'}"}, ensure_ascii=False)

    def cronjob_update(self, job_id: str, name: Optional[str] = None, cron_expr: Optional[str] = None, prompt: Optional[str] = None, enabled: Optional[bool] = None) -> str:
        """Actualiza una tarea programada dado su job_id."""
        from agent.scheduler import get_scheduler
        import json
        sched = get_scheduler()
        if not sched:
            return json.dumps({"error": "Scheduler no inicializado."}, ensure_ascii=False)
            
        update_args = {}
        if name is not None: update_args["name"] = name
        if cron_expr is not None: update_args["cron_expr"] = cron_expr
        if prompt is not None: update_args["prompt"] = prompt
        if enabled is not None: update_args["enabled"] = enabled
        
        updated = sched.update_job(job_id, **update_args)
        return json.dumps({"success": bool(updated), "job": updated}, ensure_ascii=False)

    def cronjob_run_now(self, job_id: str) -> str:
        """Ejecuta una tarea programada ahora mismo, sin esperar su próxima ejecución."""
        from agent.scheduler import get_scheduler
        import json
        sched = get_scheduler()
        if not sched:
            return json.dumps({"error": "Scheduler no inicializado."}, ensure_ascii=False)
        job = sched.get_job(job_id)
        if not job:
            return json.dumps({"error": f"Tarea '{job_id}' no encontrada"}, ensure_ascii=False)
        asyncio.create_task(sched._execute_job(job))
        return json.dumps({"success": True, "message": f"⏰ Tarea '{job['name']}' ejecutándose ahora"}, ensure_ascii=False)

    async def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> str:
        """
        Genera una imagen artística usando Inteligencia Artificial (Stable Diffusion 3).
        Úsala SIEMPRE que el usuario pida crear, generar o dibujar una imagen.
        La imagen se genera Y SE ENVÍA AUTOMÁTICAMENTE al chat.
        
        Args:
            prompt: Descripción detallada de la imagen (en inglés o español).
            aspect_ratio: Relación de aspecto (default: "1:1"). Opciones: "16:9", "9:16", "21:9", "2:3", "3:2", "4:5", "5:4", "9:21".
        """
        import json
        res = generate_image(prompt, aspect_ratio)
        if res["success"] and self.bot:
            try:
                await self.bot.send_image(self.room_id, res["file_path"], f"🎨 {prompt[:80]}")
                return json.dumps({"success": True, "message": "Imagen generada y enviada al chat."}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"success": True, "file_path": res["file_path"], "message": f"Imagen generada en {res['file_path']} pero error al enviar: {e}"}, ensure_ascii=False)
        return json.dumps(res, ensure_ascii=False)

    async def send_file(self, file_path: str) -> str:
        """
        Envía un archivo del servidor al chat de Matrix.
        Úsala cuando el usuario pida enviar, mandar o mostrar un archivo, imagen o documento que está en el servidor.
        También cuando generes una imagen y el usuario pida que la envíes.
        Rutas comunes: /opt/jada/tmp/images/ para imágenes generadas.
        
        Args:
            file_path: Ruta absoluta del archivo en el servidor (ej: /opt/jada/tmp/images/gen_123.png)
        """
        import os
        if not os.path.exists(file_path):
            # Try to find the most recent image if path looks like tmp/images
            if 'images' in file_path or 'tmp' in file_path:
                img_dir = '/opt/jada/tmp/images'
                if os.path.exists(img_dir):
                    files = sorted(os.listdir(img_dir), reverse=True)
                    if files:
                        file_path = os.path.join(img_dir, files[0])
                    else:
                        return json.dumps({"error": "No hay imágenes generadas."}, ensure_ascii=False)
                else:
                    return json.dumps({"error": f"Archivo no encontrado: {file_path}"}, ensure_ascii=False)
            else:
                return json.dumps({"error": f"Archivo no encontrado: {file_path}"}, ensure_ascii=False)
        
        if not self.bot:
            return json.dumps({"error": "No hay conexión al chat."}, ensure_ascii=False)
        
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                await self.bot.send_image(self.room_id, file_path, os.path.basename(file_path))
            else:
                await self.bot.send_file(self.room_id, file_path)
            return json.dumps({"success": True, "message": f"✅ Archivo enviado: {os.path.basename(file_path)}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Error enviando archivo: {str(e)}"}, ensure_ascii=False)

    async def describe_image(self, file_path: str, question: str = "Describe esta imagen en detalle en español.") -> str:
        """
        Analiza y describe una imagen del servidor usando IA de visión (Mistral Large 3 via NVIDIA).
        Úsala cuando el usuario pida describir, analizar o explicar una imagen que está en el servidor.
        Para imágenes generadas por Jada, la ruta suele ser /opt/jada/tmp/images/
        Si el usuario dice "la última imagen", busca la más reciente en esa carpeta.
        También para analizar páginas renderizadas de PDFs (ruta: /tmp/jada_pdf_pages/).
        
        Args:
            file_path: Ruta absoluta de la imagen (ej: /opt/jada/tmp/images/gen_123.png, /tmp/jada_pdf_pages/planos_p1.png)
            question: Pregunta o instrucción sobre la imagen (default: describir en español).
        """
        import json, os, base64, requests, asyncio

        # Auto-find latest image if path doesn't exist
        if not os.path.exists(file_path):
            if 'images' in file_path or 'tmp' in file_path or 'última' in file_path.lower() or file_path == 'latest':
                img_dir = '/opt/jada/tmp/images'
                if os.path.exists(img_dir):
                    files = sorted([f for f in os.listdir(img_dir) if f.endswith(('.png', '.jpg', '.jpeg', '.webp'))], reverse=True)
                    if files:
                        file_path = os.path.join(img_dir, files[0])
                    else:
                        return json.dumps({"error": "No hay imágenes generadas."}, ensure_ascii=False)

        if not os.path.exists(file_path):
            return json.dumps({"error": f"Archivo no encontrado: {file_path}"}, ensure_ascii=False)

        def _call_vision():
            with open(file_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

            ext = os.path.splitext(file_path)[1].lower()
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}.get(ext.strip('.'), "image/png")

            vision_model = os.getenv("NVIDIA_VISION_MODEL", "mistralai/mistral-large-3-675b-instruct-2512")
            api_key = os.getenv("NVIDIA_API_KEY", "")

            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                json={
                    "model": vision_model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                    ]}],
                    "max_tokens": 1500,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        try:
            description = await asyncio.to_thread(_call_vision)
            return json.dumps({
                "success": True,
                "description": description,
                "file": os.path.basename(file_path),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Error analizando imagen: {str(e)}"}, ensure_ascii=False)

    # ── PDF ─────────────────────────────────────────────────────────────────

    async def read_pdf(self, file_path: str, max_pages: int = 30) -> str:
        """Lee y extrae el texto de un archivo PDF. Usa esto para analizar PDFs.
        Si el PDF no tiene texto (planos, escaneos), renderiza las páginas como imágenes.
        En ese caso, usa describe_image con la ruta de la imagen renderizada para analizar el contenido.

        Args:
            file_path: Ruta local del PDF (ej: /opt/jada/tmp/planos.pdf, /tmp/jada_files/doc.pdf)
            max_pages: Máximo de páginas a leer (default: 30)
        """
        import json
        result = await read_pdf(file_path, max_pages)

        # Si tiene texto, retornar directamente
        if result.get("has_text"):
            text = result.get("text", "")
            if len(text) > 3000:
                result["text"] = text[:3000] + "\n... [truncado]"
            return json.dumps(result, ensure_ascii=False)

        # Si no tiene texto (PDF de imágenes), renderizar páginas como imágenes
        if result.get("success") and not result.get("has_text"):
            try:
                render_result = await render_pdf_pages(file_path, max_pages=3)
                if render_result.get("success") and render_result.get("image_paths"):
                    result["rendered_pages"] = render_result["image_paths"]
                    result["hint"] = "Este PDF es de imágenes. Usa describe_image con la ruta de rendered_pages para analizar su contenido visual."
            except Exception as e:
                logger.error(f"Error renderizando PDF: {e}")
                result["render_error"] = str(e)

        return json.dumps(result, ensure_ascii=False)

    # ── Reddit ─────────────────────────────────────────────────────────────

    async def reddit_trending(self, limit: int = 10) -> str:
        """Muestra los posts más populares/trending de Reddit ahora mismo.

        Args:
            limit: Número de posts a mostrar (default: 10, máx 25)
        """
        import json
        posts = await reddit_trending(min(limit, 25))
        return json.dumps(posts, ensure_ascii=False)

    async def reddit_subreddit(self, subreddit: str, sort: str = "hot",
                               limit: int = 10, time_filter: str = "day") -> str:
        """Muestra posts de un subreddit específico.

        Args:
            subreddit: Nombre del subreddit sin r/ (ej: technology, programming, colombia)
            sort: Orden — hot, new, top, rising (default: hot)
            limit: Número de posts (default: 10)
            time_filter: Para sort=top: hour, day, week, month, year, all
        """
        import json
        posts = await reddit_subreddit(subreddit, sort, min(limit, 25), time_filter)
        return json.dumps(posts, ensure_ascii=False)

    async def reddit_search(self, query: str, subreddit: str = "",
                            limit: int = 10, sort: str = "relevance") -> str:
        """Busca posts en Reddit por palabras clave.

        Args:
            query: Términos de búsqueda
            subreddit: Buscar solo en este subreddit (opcional, vacío = todo Reddit)
            limit: Número de resultados (default: 10)
            sort: relevance, hot, top, new, comments
        """
        import json
        posts = await reddit_search(query, subreddit, min(limit, 25), sort)
        return json.dumps(posts, ensure_ascii=False)

    # ── Storage (Supabase) ─────────────────────────────────────────────────

    async def storage_upload(self, file_path: str, remote_name: str = "",
                             folder: str = "") -> str:
        """Sube un archivo local al storage en la nube. Retorna URL pública para compartir.

        Args:
            file_path: Ruta local del archivo a subir.
            remote_name: Nombre con el que guardar en la nube (opcional, usa el nombre original si vacío).
            folder: Carpeta en el storage donde guardar (opcional).
        """
        result = await upload_file(file_path, remote_name or None, folder)
        return json.dumps(result, ensure_ascii=False)

    async def storage_list(self, folder: str = "", limit: int = 20) -> str:
        """Lista archivos almacenados en la nube.

        Args:
            folder: Carpeta a listar (vacío = raíz del bucket).
            limit: Máximo de archivos a retornar.
        """
        result = await list_files(folder, limit)
        return json.dumps(result, ensure_ascii=False)

    async def storage_download(self, remote_path: str, dest_path: str = "") -> str:
        """Descarga un archivo de la nube al servidor.

        Args:
            remote_path: Ruta del archivo en el storage (ej: 'docs/informe.pdf').
            dest_path: Ruta local donde guardar (opcional, usa /opt/jada/tmp/).
        """
        result = await download_file(remote_path, dest_path or None)
        return json.dumps(result, ensure_ascii=False)

    async def storage_delete(self, remote_path: str) -> str:
        """Elimina un archivo del storage en la nube.

        Args:
            remote_path: Ruta del archivo a eliminar (ej: 'docs/viejo.pdf').
        """
        result = await delete_file(remote_path)
        return json.dumps(result, ensure_ascii=False)
