"""
agent/workflows.py — Motor de Workflows Deterministas para Jada

Permite ejecutar secuencias de tareas predefinidas (obtener clima, leer emails)
de manera lineal y segura sin depender del criterio impredecible de un LLM.
El LLM solo se usa en el paso final ('synthesis') para redactar el mensaje.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import asyncio
import logging
import time
import os

logger = logging.getLogger("jada.workflows")

@dataclass
class Step:
    id: str
    name: str
    # Una de estas dos — tool directa o prompt al LLM
    tool: Optional[str] = None             # nombre del método en JadaTools
    tool_params: dict = field(default_factory=dict)
    prompt_template: Optional[str] = None  # usa {step_id} para referenciar resultados anteriores
    model: str = "fast"                    # "fast" = GPT-5-mini, "deep" = fallbacks
    # Control de flujo
    on_error: str = "continue"             # "continue", "stop", "retry"
    max_retries: int = 1
    timeout: int = 30
    # Condición opcional — solo ejecuta si se cumple
    condition: Optional[str] = None        # ej: "email.count > 0"

@dataclass  
class WorkflowResult:
    step_id: str
    step_name: str
    success: bool
    data: Any
    error: Optional[str] = None
    duration_ms: int = 0


# ── Catálogo de workflows predefinidos ──────────────────────────────────

WORKFLOWS = {

    "resumen_lunes": {
        "name": "Resumen del lunes",
        "notify_progress": True,
        "steps": [
            Step(
                id="email",
                name="Revisar correos NO leídos",
                tool="email_list",
                tool_params={"limit": 15, "unread_only": True},
                on_error="continue",
            ),
            Step(
                id="gym",
                name="Revisar entrenamiento",
                tool="gym_get_recent",
                tool_params={"limit": 7},
                on_error="continue",
            ),
            Step(
                id="calendar",
                name="Ver calendario de la semana",
                tool="calendar_upcoming",
                tool_params={"days": 7},
                on_error="continue",
            ),
            Step(
                id="synthesis",
                name="Sintetizar",
                prompt_template=(
                    "Datos reales de Juan este lunes:\n\n"
                    "CORREOS (últimos 15 no leídos): {email}\n"
                    "GYM (última semana): {gym}\n"
                    "CALENDARIO (próximos 7 días): {calendar}\n\n"
                    "Crea un briefing de lunes conciso y directo.\n"
                    "Prioriza lo urgente y no divagues. Máximo 4-5 líneas.\n"
                    "Tono de Jada: directo, si no hay gym jode un poco. Si hay mucho correo, avisa del desastre.\n"
                    "Si un bloque de datos falla o no tiene info, ignóralo completamente."
                ),
                model="fast",
                on_error="stop",
            ),
        ]
    },

    "morning_brief": {
        "name": "Brief matutino rápido",
        "notify_progress": False,
        "steps": [
            Step(id="weather",   name="Clima",      tool="get_weather",     tool_params={"location": "Medellin"}),
            Step(id="calendar",  name="Agenda hoy", tool="calendar_today",  tool_params={}),
            Step(id="email",     name="No leídos",  tool="email_list",      tool_params={"unread_only": True, "limit": 5}),
            Step(
                id="synthesis", 
                name="Resumen final",      
                prompt_template="Reúne el clima={weather}, agenda={calendar}, emails_unread={email}. Dame un briefing matutino de 3 líneas directas. No introduzcas el mensaje.", 
                model="fast"
            ),
        ]
    },

    "gym_report": {
        "name": "Reporte de entrenamiento",
        "notify_progress": False,
        "steps": [
            Step(id="recent",  name="Últimos entrenos", tool="gym_get_recent",  tool_params={"limit": 10}),
            Step(id="stats",   name="Estadísticas",     tool="gym_get_stats",   tool_params={}),
            Step(
                id="synthesis",  
                name="Análisis",
                prompt_template="Tus registros: {recent}\nEstadísticas: {stats}\nEvalúa el progreso brevemente y propón un reto para la próxima sesión.", 
                model="fast"
            ),
        ]
    },

}


# ── Motor de ejecución ────────────────────────────────────────────────

class WorkflowEngine:
    
    def __init__(self, tools, send_callback=None):
        """
        tools: instancia de src/agent/tools.py (JadaTools)
        send_callback: función async opcional (room_id, str) para emitir feedback incremental.
        """
        self.tools = tools
        self.send_callback = send_callback
    
    async def run(self, workflow_id: str, room_id: str) -> str:
        """Ejecuta todos los pasos de un workflow de forma secuencial."""
        
        workflow = WORKFLOWS.get(workflow_id)
        if not workflow:
            return f"Error: Workflow '{workflow_id}' no encontrado en WORKFLOWS."
        
        logger.info(f"🔄 Iniciando workflow: '{workflow['name']}' en room {room_id}")
        
        context = {}
        results = []
        
        for step in workflow["steps"]:
            # Evaluar condición de ejecución (ej. skip si email está vacío)
            if step.condition and not self._eval_condition(step.condition, context):
                logger.info(f"⏭️ Workflow step '{step.id}' saltado (condición '{step.condition}' no cumplida).")
                continue
            
            # Notify in Matrix of intermediate steps if requested
            if workflow.get("notify_progress") and self.send_callback:
                try:
                    await self.send_callback(room_id, f"_{step.name}..._")
                except Exception as e:
                    logger.warning(f"Error enviando progreso a matrix: {e}")
            
            # Ejecutar paso exacto con self-correction
            result = await self._run_step(step, context)
            results.append(result)
            
            if result.success:
                context[step.id] = result.data
                logger.info(f"✅ Workflow Step '{step.id}' OK ({result.duration_ms}ms)")
            else:
                logger.warning(f"⚠️ Workflow Step '{step.id}' falló: {result.error}")
                context[step.id] = None
                
                if step.on_error == "stop":
                    logger.error(f"❌ Workflow '{workflow_id}' abortado en step '{step.id}'.")
                    return f"Tu workflow automático '{workflow['name']}' falló al cargar `{step.tool}`."
                # "continue" → simply proceed with next step
        
        # El resultado devuelto es la síntesis generada en el paso final (usualmente el LLM)
        synthesis = next((r for r in reversed(results) if r.step_id == "synthesis" and r.success), None)
        return synthesis.data if synthesis else "Workflow completado, pero el paso de síntesis falló o no fue configurado."
    
    async def _run_step(self, step: Step, context: dict) -> WorkflowResult:
        start = time.time()
        
        for attempt in range(step.max_retries + 1):
            try:
                if step.tool:
                    # 1. TOOL EJECUCIÓN DIRECTA
                    tool_fn = getattr(self.tools, step.tool, None)
                    if not tool_fn:
                        raise ValueError(f"La herramienta '{step.tool}' no existe en JadaTools.")
                    
                    import inspect
                    if inspect.iscoroutinefunction(tool_fn):
                        data = await asyncio.wait_for(
                            tool_fn(**step.tool_params),
                            timeout=step.timeout
                        )
                    else:
                        # Para herramientas síncronas como get_weather
                        loop = asyncio.get_running_loop()
                        data = await loop.run_in_executor(None, lambda: tool_fn(**step.tool_params))
                    
                elif step.prompt_template:
                    # 2. LLM SÍNTESIS
                    # Interpolar placeholders en el texto {email}, {calendar}, {weather}...
                    prompt = step.prompt_template
                    for key, val in context.items():
                        placeholder = "{" + key + "}"
                        # Si 'val' falló o es None, ponemos un texto nulo amistoso para el LLM.
                        text_val = str(val) if val is not None else "[Error obteniendo estos datos]"
                        prompt = prompt.replace(placeholder, text_val)
                    
                    from agno.agent import Agent as AgnoAgent
                    from agno.models.openai import OpenAIChat
                    
                    # Usar os.getenv de OPENAI_FUNCTION_MODEL mapeado al formato OpenAI de Agno
                    model_fast = os.getenv("OPENAI_FUNCTION_MODEL", "gpt-4o-mini")
                    model_fallback = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o")
                    model_id = model_fast if step.model == "fast" else model_fallback
                    
                    synth_agent = AgnoAgent(
                        model=OpenAIChat(id=model_id),
                        description=(
                            "Eres Jada. Estás actuando como orquestadora de workflows programados de Juan.\n"
                            "Analiza los datos incrustados firmemente y responde de la forma en que lo indica el prompt."
                        ),
                        markdown=True
                    )
                    
                    response = await asyncio.wait_for(
                        synth_agent.arun(prompt),
                        timeout=step.timeout
                    )
                    data = response.content
                else:
                    raise ValueError(f"Step '{step.id}' no define ni 'tool' ni 'prompt_template'.")
                
                ms = int((time.time() - start) * 1000)
                return WorkflowResult(step.id, step.name, True, data, duration_ms=ms)
                
            except asyncio.TimeoutError:
                if attempt < step.max_retries:
                    logger.debug(f"Timeout en step '{step.id}', reintentando ({attempt+1}/{step.max_retries})...")
                    await asyncio.sleep(2)
                    continue
                return WorkflowResult(step.id, step.name, False, None, f"Timeout after {step.timeout}s")
                
            except Exception as e:
                if attempt < step.max_retries:
                    logger.debug(f"Error en step '{step.id}' ({e}), reintentando...")
                    await asyncio.sleep(1)
                    continue
                return WorkflowResult(step.id, step.name, False, None, str(e))
    
    def _eval_condition(self, condition: str, context: dict) -> bool:
        """Evalúa condiciones de flujo, estilo expr('email.count > 0')."""
        try:
            return eval(condition, {"__builtins__": {}}, context)
        except Exception as e:
            logger.debug(f"Falla evauando condición '{condition}': {e}")
            return True  # Failsafe: if evaluating fails, just run the step.


# Singleton para instanciación limpia global
_engine = None

def get_workflow_engine(tools, send_callback=None) -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine(tools, send_callback)
    elif send_callback and not _engine.send_callback:
        _engine.send_callback = send_callback # Actualiza callback si es necesario
    return _engine
