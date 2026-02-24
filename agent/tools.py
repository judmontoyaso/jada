"""
agent/tools.py — Registro central de herramientas y dispatcher
Define los schemas JSON para function calling y despacha las llamadas.
"""
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
from tools.calendar_reader import get_today_events, get_upcoming_events, search_events
from tools.summarizer import fetch_and_summarize
from tools.reminders import reminder_manager
from tools.deep_think import deep_think
from tools.samsung_tv import tv_control, tv_status, list_devices

# ─── Schemas de tools para NVIDIA NIM (OpenAI function calling format) ────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Ejecuta un comando de shell/terminal en el sistema. Retorna stdout, stderr y código de salida.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "El comando a ejecutar"},
                    "timeout": {"type": "integer", "description": "Timeout en segundos (default: 30)", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee el contenido de un archivo del sistema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta o relativa del archivo"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea o sobreescribe un archivo. Puede añadir al final si append=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del archivo"},
                    "content": {"type": "string", "description": "Contenido a escribir"},
                    "append": {"type": "boolean", "description": "Si true, añade al final del archivo", "default": False},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Lista el contenido (archivos y carpetas) de un directorio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del directorio (default: directorio actual)", "default": "."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca información en la web usando DuckDuckGo. Retorna títulos, URLs y snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta de búsqueda"},
                    "max_results": {"type": "integer", "description": "Número máximo de resultados (default: 5)", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navega a una URL en el browser. Úsalo para abrir páginas web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL a abrir (debe incluir https://)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_text",
            "description": "Extrae el texto visible de la página actualmente abierta en el browser.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Hace click en un elemento de la página usando un selector CSS o texto visible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Selector CSS o texto del elemento"},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Rellena un campo de formulario en la página actual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Selector CSS del campo"},
                    "text": {"type": "string", "description": "Texto a escribir"},
                },
                "required": ["selector", "text"],
            },
        },
    },
    # ─── Samsung TV (SmartThings) ───────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "samsung_list_devices",
            "description": "Lista todos los dispositivos disponibles en SmartThings (incluye TVs).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "samsung_tv_status",
            "description": "Obtiene el estado actual del TV (encendido/apagado).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID del dispositivo TV (obtenido de samsung_list_devices)"},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "samsung_tv_control",
            "description": "Controla el Samsung TV: enciéndelo, apágalo, sube/baja volumen o silencia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID del dispositivo TV"},
                    "command": {"type": "string", "description": "Comando: 'on', 'off', 'up', 'down', 'mute', 'unmute'"},
                },
                "required": ["device_id", "command"],
            },
        },
    },
    # ─── Gym Tools ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "gym_save_workout",
            "description": (
                "Guarda un entrenamiento COMPLETO de gym en MongoDB. Usa esto cuando el usuario "
                "manda TODOS los ejercicios en un solo mensaje. Pasa el texto de ejercicios "
                "EXACTAMENTE como lo escribió el usuario en 'ejercicios_raw'. "
                "NO intentes interpretar la notación tú mismo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre descriptivo (ej: 'Push - Pecho, Hombros y Tríceps')"},
                    "fecha": {"type": "string", "description": "Fecha YYYY-MM-DD, 'ayer', o 'hoy'"},
                    "tipo": {"type": "string", "description": "push, pull, pierna, fullbody, cardio, etc."},
                    "grupos_musculares": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Grupos trabajados: ['pecho', 'hombros', 'triceps']",
                    },
                    "ejercicios_raw": {
                        "type": "string",
                        "description": (
                            "Texto EXACTO del usuario con los ejercicios, copiado tal cual. "
                            "NO modifiques ni interpretes los datos."
                        ),
                    },
                    "notas": {"type": "string", "description": "Notas generales del entrenamiento"},
                },
                "required": ["nombre", "fecha", "ejercicios_raw"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_start_session",
            "description": (
                "Inicia una sesión de gym para registrar ejercicios uno por uno. "
                "Usa esto cuando el usuario dice 'voy a anotar mi entrenamiento' o similar. "
                "Después de iniciar, el usuario mandará ejercicios línea por línea. "
                "Al final, usa gym_end_session para guardar todo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre del entrenamiento (ej: 'Push - Pecho y Tríceps')"},
                    "fecha": {"type": "string", "description": "Fecha YYYY-MM-DD, 'ayer', o 'hoy'"},
                    "tipo": {"type": "string", "description": "push, pull, pierna, fullbody, cardio, etc."},
                    "grupos_musculares": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Grupos trabajados",
                    },
                },
                "required": ["nombre", "fecha", "tipo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_add_exercise",
            "description": (
                "Agrega uno o más ejercicios a la sesión de gym activa. "
                "Pasa el texto EXACTO del usuario. NO interpretes la notación. "
                "Solo funciona si hay una sesión activa (gym_start_session)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ejercicio_raw": {
                        "type": "string",
                        "description": "Texto EXACTO del usuario con el/los ejercicio(s), tal cual.",
                    },
                },
                "required": ["ejercicio_raw"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_end_session",
            "description": (
                "Finaliza la sesión de gym activa y guarda todos los ejercicios en MongoDB. "
                "Usa esto cuando el usuario dice 'listo', 'ya', 'guarda', 'eso es todo', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "notas": {"type": "string", "description": "Notas adicionales del entrenamiento"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_get_recent",
            "description": "Obtiene los últimos entrenamientos registrados en la base de datos de gym.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número de entrenamientos a retornar (default: 10)", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_exercise_history",
            "description": "Ver el historial y progresión de un ejercicio específico (peso, series, reps a lo largo del tiempo).",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_name": {"type": "string", "description": "Nombre del ejercicio (ej: 'Sentadilla', 'Press banca')"},
                    "limit": {"type": "integer", "description": "Número de registros a retornar", "default": 10},
                },
                "required": ["exercise_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_save_routine",
            "description": "Guarda una rutina de entrenamiento generada para usarla después.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre de la rutina"},
                    "description": {"type": "string", "description": "Descripción y objetivo de la rutina"},
                    "exercises": {
                        "type": "array",
                        "description": "Ejercicios de la rutina",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "muscle_group": {"type": "string"},
                                "sets": {"type": "integer"},
                                "reps": {"type": "string"},
                                "rest_seconds": {"type": "integer"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["name", "exercises"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_get_routines",
            "description": "Obtiene todas las rutinas guardadas en la base de datos.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gym_get_stats",
            "description": "Obtiene estadísticas de gym: total de entrenamientos, ejercicios más frecuentes, etc.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # ─── Notes Tools ───────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "note_save",
            "description": "Guarda una nota personal del usuario. Puede tener título, contenido y tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título de la nota"},
                    "content": {"type": "string", "description": "Contenido de la nota (markdown)"},
                    "tags": {"type": "string", "description": "Tags separados por coma (ej: 'ideas,proyecto,urgente')"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_list",
            "description": "Lista las notas del usuario ordenadas por fecha de actualización.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número de notas a retornar (default: 20)", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_search",
            "description": "Busca notas por título, contenido o tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Término de búsqueda"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_delete",
            "description": "Elimina una nota por su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "ID de la nota a eliminar"},
                },
                "required": ["note_id"],
            },
        },
    },
    # ─── Email (solo lectura) ────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "email_list",
            "description": "Lista los últimos correos electrónicos del usuario (solo lectura). Muestra remitente, asunto y fecha.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Carpeta IMAP (default: INBOX)", "default": "INBOX"},
                    "limit": {"type": "integer", "description": "Número de correos a retornar (default: 10)", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_read",
            "description": "Lee el contenido completo de un correo electrónico por su ID numérico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string", "description": "ID del correo (obtenido de email_list)"},
                    "folder": {"type": "string", "description": "Carpeta IMAP (default: INBOX)", "default": "INBOX"},
                },
                "required": ["email_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_search",
            "description": "Busca correos electrónicos por asunto o remitente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar en asunto o remitente"},
                    "folder": {"type": "string", "description": "Carpeta IMAP (default: INBOX)", "default": "INBOX"},
                    "limit": {"type": "integer", "description": "Número máximo de resultados", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    # ─── Calendar (solo lectura) ───────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "calendar_today",
            "description": "Obtiene los eventos del calendario de hoy.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_upcoming",
            "description": "Obtiene los próximos eventos del calendario en los siguientes N días.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Días hacia adelante (default: 7)", "default": 7},
                    "limit": {"type": "integer", "description": "Máximo de eventos (default: 15)", "default": 15},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_search",
            "description": "Busca eventos en el calendario por título, descripción o ubicación.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar"},
                    "limit": {"type": "integer", "description": "Máximo de resultados", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    # ─── Email Send ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "email_send",
            "description": "Envía un correo electrónico. Puede enviar emails a cualquier dirección.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Dirección de email del destinatario"},
                    "subject": {"type": "string", "description": "Asunto del correo"},
                    "body": {"type": "string", "description": "Cuerpo del correo (texto plano)"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    # ─── Summarizer ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "summarize_url",
            "description": (
                "Descarga el contenido de una URL (página web, artículo, blog) y extrae el texto. "
                "Usa esto cuando el usuario pida un resumen de una página web o artículo. "
                "Retorna el texto extraído para que lo resumas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL de la página a resumir"},
                },
                "required": ["url"],
            },
        },
    },
    # ─── Deep Think (sub-agente MiniMax) ────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "deep_think",
            "description": (
                "Delega una tarea compleja a un modelo de razonamiento profundo (MiniMax M2.1). "
                "Usa esto para: análisis detallado, planificación, generación de código complejo, "
                "debugging, comparaciones profundas, o cualquier tarea que requiera pensar mucho. "
                "NO uses esto para preguntas simples o saludos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "La tarea o pregunta que requiere razonamiento profundo",
                    },
                    "context": {
                        "type": "string",
                        "description": "Contexto adicional: código, datos, texto a analizar (opcional)",
                    },
                },
                "required": ["task"],
            },
        },
    },
    # ─── Reminders ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Programa un recordatorio. Después del delay especificado, "
                "se enviará un mensaje al chat con el texto del recordatorio. "
                "Usa esto cuando el usuario diga 'recuérdame', 'avísame', 'en X minutos', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Texto del recordatorio"},
                    "delay_seconds": {
                        "type": "integer",
                        "description": "Segundos de espera antes de enviar el recordatorio. Ej: 300 = 5 min, 3600 = 1 hora",
                    },
                },
                "required": ["message", "delay_seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "Lista los recordatorios activos (pendientes).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminders",
            "description": "Cancela todos los recordatorios activos.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # ─── Memory ────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Guarda un hecho importante sobre el usuario en la memoria a largo plazo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "Hecho a recordar sobre el usuario"},
                },
                "required": ["fact"],
            },
        },
    },
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
                return await run_command(args["command"], args.get("timeout", 30))

            # Files
            case "read_file":
                return await read_file(args["path"])
            case "write_file":
                return await write_file(args["path"], args["content"], args.get("append", False))
            case "list_dir":
                return await list_dir(args.get("path", "."))

            # Web
            case "web_search":
                return await search(args["query"], args.get("max_results", 5))

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
                return tv_status(args["device_id"])
            case "samsung_tv_control":
                return tv_control(args["device_id"], args["command"])

            # Gym — Entrenamiento completo en un solo mensaje
            case "gym_save_workout":
                raw_text = args.get("ejercicios_raw", "")
                if raw_text:
                    exercises = parse_workout_text(raw_text)
                else:
                    exercises = args.get("ejercicios", [])
                
                return await self._gym.save_workout(
                    name=args["nombre"],
                    date_str=args["fecha"],
                    exercises=exercises,
                    tipo=args.get("tipo", ""),
                    grupos_musculares=args.get("grupos_musculares"),
                    notes=args.get("notas", ""),
                )

            # Gym — Sesión línea por línea
            case "gym_start_session":
                if self._gym_session:
                    return {"error": "Ya hay una sesión activa. Usa gym_end_session primero."}
                self._gym_session = {
                    "nombre": args["nombre"],
                    "fecha": args["fecha"],
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
                total = len(self._gym_session["ejercicios"])
                added_names = [e["nombre"] for e in parsed]
                return {
                    "success": True,
                    "added": added_names,
                    "added_count": len(parsed),
                    "total_exercises": total,
                }

            case "gym_end_session":
                if not self._gym_session:
                    return {"error": "No hay sesión de gym activa."}
                session = self._gym_session
                self._gym_session = None  # Limpiar sesión
                
                if not session["ejercicios"]:
                    return {"error": "La sesión no tiene ejercicios. No se guardó nada."}
                
                result = await self._gym.save_workout(
                    name=session["nombre"],
                    date_str=session["fecha"],
                    exercises=session["ejercicios"],
                    tipo=session["tipo"],
                    grupos_musculares=session["grupos_musculares"],
                    notes=args.get("notas", ""),
                )
                total_series = sum(e["series"] for e in session["ejercicios"])
                result["total_exercises"] = len(session["ejercicios"])
                result["total_series"] = total_series
                return result
            case "gym_get_recent":
                return await self._gym.get_recent_workouts(args.get("limit", 10))
            case "gym_exercise_history":
                return await self._gym.get_exercise_history(
                    args["exercise_name"], args.get("limit", 10)
                )
            case "gym_save_routine":
                return await self._gym.save_routine(
                    args["name"], args.get("description", ""), args["exercises"]
                )
            case "gym_get_routines":
                return await self._gym.get_routines()
            case "gym_get_stats":
                return await self._gym.get_stats()

            # Notes
            case "note_save":
                return await self._notes.save_note(
                    self._user_id, args["title"], args["content"], args.get("tags", "")
                )
            case "note_list":
                return await self._notes.get_notes(self._user_id, args.get("limit", 20))
            case "note_search":
                return await self._notes.search_notes(self._user_id, args["query"])
            case "note_delete":
                return await self._notes.delete_note(self._user_id, args["note_id"])

            # Email (solo lectura)
            case "email_list":
                return await list_emails(args.get("folder", "INBOX"), args.get("limit", 10))
            case "email_read":
                return await read_email(args["email_id"], args.get("folder", "INBOX"))
            case "email_search":
                return await search_emails(args["query"], args.get("folder", "INBOX"), args.get("limit", 10))

            # Calendar (solo lectura)
            case "calendar_today":
                return await get_today_events()
            case "calendar_upcoming":
                return await get_upcoming_events(args.get("days", 7), args.get("limit", 15))
            case "calendar_search":
                return await search_events(args["query"], args.get("limit", 10))

            # Email Send
            case "email_send":
                return await send_email(args["to"], args["subject"], args["body"])

            # Summarizer
            case "summarize_url":
                return await fetch_and_summarize(args["url"])

            # Reminders
            case "set_reminder":
                return await reminder_manager.add_reminder(
                    args["message"], args["delay_seconds"],
                    self._room_id or "unknown", self._user_id or "unknown"
                )
            case "list_reminders":
                return await reminder_manager.list_reminders(self._room_id)
            case "cancel_reminders":
                return await reminder_manager.cancel_all(self._room_id)

            # Deep Think (sub-agente MiniMax)
            case "deep_think":
                return await deep_think(args["task"], args.get("context", ""))

            # Memory
            case "remember_fact":
                if self._memory and self._user_id:
                    await self._memory.save_fact(self._user_id, args["fact"])
                return {"success": True, "fact_saved": args["fact"]}

            case _:
                return {"error": f"Tool desconocida: '{tool_name}'"}