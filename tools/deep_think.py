"""
tools/deep_think.py — Sub-agente de razonamiento profundo (MiniMax M2.1)
El agente principal (Nemotron) delega tareas complejas a este modelo thinking.
Casos de uso: análisis, planificación, código complejo, resúmenes largos, debugging.
"""
import os
import logging
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

THINKING_MODEL = os.getenv("THINKING_MODEL", "minimaxai/minimax-m2.1")
THINKING_TIMEOUT = int(os.getenv("THINKING_TIMEOUT", "180"))  # Más tiempo para pensar


class DeepThinkAgent:
    """Sub-agente que usa un modelo de razonamiento para tareas complejas."""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("NVIDIA_API_KEY"),
            base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            timeout=httpx.Timeout(THINKING_TIMEOUT, connect=10.0),
            max_retries=1,
        )

    async def think(self, task: str, context: str = "") -> dict:
        """
        Enviar una tarea compleja al modelo thinking.
        
        Args:
            task: La tarea o pregunta que requiere razonamiento profundo
            context: Contexto adicional (datos, código, texto a analizar)
        
        Returns:
            dict con 'result' (respuesta) y 'model' usado
        """
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Eres un asistente de razonamiento profundo. "
                        "Analiza la tarea con cuidado, piensa paso a paso, "
                        "y da una respuesta completa y bien estructurada. "
                        "Responde en el mismo idioma que la pregunta."
                    ),
                },
                {
                    "role": "user",
                    "content": f"{task}\n\n{context}" if context else task,
                },
            ]

            logger.info(f"🧠 DeepThink invocado: {task[:80]}...")

            response = await self.client.chat.completions.create(
                model=THINKING_MODEL,
                messages=messages,
                temperature=0.4,
                max_tokens=65536,
            )

            result = response.choices[0].message.content or ""

            # Limpiar tags <think> del resultado
            import re
            result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL)
            result = re.sub(r'<think>.*$', '', result, flags=re.DOTALL)
            result = result.strip()

            logger.info(f"🧠 DeepThink completado ({len(result)} chars)")

            return {
                "result": result,
                "model": THINKING_MODEL,
                "chars": len(result),
            }

        except Exception as e:
            logger.error(f"🧠 DeepThink error: {e}")
            return {
                "error": f"El modelo de razonamiento no pudo completar la tarea: {str(e)[:100]}",
                "model": THINKING_MODEL,
            }


# Singleton
deep_thinker = DeepThinkAgent()


async def deep_think(task: str, context: str = "") -> str:
    """Wrapper para el dispatcher de tools."""
    result = await deep_thinker.think(task, context)
    if "error" in result:
        return result["error"]
    return result["result"]
