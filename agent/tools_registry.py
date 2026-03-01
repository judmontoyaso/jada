"""
agent/tools_registry.py — Traductor de las funciones nativas a Agno Tools.

Aquí registramos todas las funciones de `tools/` en la clase base de Agno `Tool` 
para que el Agente infiera automáticamente los schemas Pydantic y las invoque.
"""
import asyncio
from typing import Optional, List, Dict, Any

from agno.tools import Toolkit
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


class JadaTools(Toolkit):
    """
    Agrupa todas las herramientas del sistema Jada para el Agente Agno.
    Agno convierte los Docstrings y Type Hints de estos métodos en JSON Schemas.
    """

    def __init__(self, user_id: str = "", room_id: str = "", bot: Any = None):
        super().__init__(name="jada_tools")
        self.user_id = user_id
        self.room_id = room_id
        self.bot = bot
        
        # Conexiones DB que requiere await init()
        self.gym_db = GymDB()
        self.notes_db = NotesDB()
        self._gym_session: Optional[Dict[str, Any]] = None

        # Registrar dinámicamente qué métodos estarán expuestos al LLM
        self.register(self.run_command)
        self.register(self.read_file)
        self.register(self.write_file)
        self.register(self.list_dir)
        self.register(self.web_search)
        self.register(self.get_weather)
        self.register(self.browser_navigate)
        self.register(self.browser_get_text)
        self.register(self.browser_click)
        self.register(self.browser_fill)
        self.register(self.samsung_list_devices)
        self.register(self.samsung_tv_status)
        self.register(self.samsung_tv_control)
        
        # Gym
        self.register(self.gym_save_workout)
        self.register(self.gym_start_session)
        self.register(self.gym_add_exercise)
        self.register(self.gym_end_session)
        self.register(self.gym_get_recent)
        self.register(self.gym_exercise_history)
        self.register(self.gym_save_routine)
        self.register(self.gym_get_routines)
        self.register(self.gym_get_stats)

        # Notas
        self.register(self.note_save)
        self.register(self.note_list)
        self.register(self.note_search)
        self.register(self.note_delete)

        # Email
        self.register(self.email_list)
        self.register(self.email_read)
        self.register(self.email_search)
        self.register(self.email_send)

        # Calendario
        self.register(self.calendar_today)
        self.register(self.calendar_upcoming)
        self.register(self.calendar_add_event)

        # Otros
        self.register(self.summarize_url)
        self.register(self.deep_think)
        
        # Recordatorios
        self.register(self.set_reminder)
        self.register(self.list_reminders)
        self.register(self.cancel_reminders)
        
        # Cronjobs
        self.register(self.cronjob_create)
        self.register(self.cronjob_list)
        self.register(self.cronjob_delete)
        self.register(self.cronjob_update)
        self.register(self.cronjob_run_now)
        self.register(self.generate_image)


    async def init_databases(self):
        """Inicializa las conexiones a bases de datos antes del primer uso."""
        await self.gym_db.init()
        await self.notes_db.init()

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
        import json; return json.dumps(await search(query, max_results, search_type), ensure_ascii=False)

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
        import json; return json.dumps(await browser.get_page_text(), ensure_ascii=False)

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
        import json; return json.dumps(await list_emails(folder, limit, unread_only), ensure_ascii=False)

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
    async def set_reminder(self, message: str, delay_seconds: int) -> str:
        """
        Programa un recordatorio. Después del delay, se enviará un mensaje al chat.
        
        Args:
            message: Texto del recordatorio
            delay_seconds: Segundos de espera. Ej: 300=5min, 3600=1hora
        """
        import json; return json.dumps(await reminder_manager.add_reminder(
            message, delay_seconds, self.room_id or "unknown", self.user_id or "unknown"
        ), ensure_ascii=False)

    async def list_reminders(self) -> str:
        """Lista los recordatorios activos (pendientes)."""
        import json; return json.dumps(await reminder_manager.list_reminders(self.room_id), ensure_ascii=False)

    async def cancel_reminders(self) -> str:
        """Cancela todos los recordatorios activos."""
        import json; return json.dumps(await reminder_manager.cancel_all(self.room_id), ensure_ascii=False)
        
    # ── Cronjobs (tareas programadas del agente) ───────────────────────────────────
    def cronjob_create(self, name: str, cron_expr: str, prompt: str, description: str = "", timezone: str = "UTC") -> str:
        """
        Crea una tarea programada para el agente. El agente ejecutará el 'prompt' automáticamente según la expresión cron.
        
        Args:
            name: Nombre de la tarea (ej: 'Noticias mañaneras')
            cron_expr: Expresión cron: '* * * * *' = minuto hora día mes dia_semana
            prompt: Qué debe hacer el agente cuando se ejecute la tarea
            timezone: Timezone (default: UTC, ej: America/Bogota)
        """
        from agent.scheduler import get_scheduler
        import time as _time
        import json
        
        sched = get_scheduler()
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
        """Lista todas las tareas programadas del agente. USA ESTO PRIMERO para obtener el job_id antes de modificar o borrar."""
        from agent.scheduler import get_scheduler
        import json
        sched = get_scheduler()
        if not sched:
            return json.dumps({"error": "Scheduler no inicializado."}, ensure_ascii=False)
        return json.dumps({"jobs": sched.list_jobs(), "status": sched.get_status()}, ensure_ascii=False)

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
        La imagen se enviará automáticamente al chat.
        
        Args:
            prompt: Descripción detallada de la imagen (en inglés o español).
            aspect_ratio: Relación de aspecto (default: "1:1"). Opciones: "16:9", "9:16", "21:9", "2:3", "3:2", "4:5", "5:4", "9:21".
        """
        import json
        res = generate_image(prompt, aspect_ratio)
        if res["success"] and self.bot:
            # Enviar la imagen de forma asíncrona
            asyncio.create_task(self.bot.send_image(self.room_id, res["file_path"], f"Generado: {prompt[:50]}..."))
            return json.dumps({"success": True, "message": "🎨 Generando y enviando imagen..."}, ensure_ascii=False)
        return json.dumps(res, ensure_ascii=False)
