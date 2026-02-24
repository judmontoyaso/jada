"""
agent/core.py — Cliente LLM usando NVIDIA NIM API (OpenAI-compatible)
Incluye model failover: si el modelo principal falla, intenta con modelos alternativos.
"""
import os
import logging
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("miniclaw")

# Timeout para NIM — agresivo para failover rápido
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

# Modelos en orden de preferencia (failover)
# Llama: rápido, buen function calling. MiniMax: thinking model, lento pero poderoso.
PRIMARY_MODEL = os.getenv("NVIDIA_MODEL")
FALLBACK_MODELS = [
    "moonshotai/kimi-k2-thinking",
    "meta/llama-3.1-70b-instruct",
]


class NvidiaLLM:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("NVIDIA_API_KEY"),
            base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            timeout=httpx.Timeout(LLM_TIMEOUT, connect=10.0),
            max_retries=1,  # 1 retry por modelo → failover rápido
        )
        self.model = PRIMARY_MODEL

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ) -> dict:
        """
        Envía mensajes al LLM con failover automático entre modelos.
        Si el modelo principal da 504, prueba con los fallback.
        """
        models_to_try = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]

        last_error = None
        for model in models_to_try:
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 10048,
                }

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice

                if model != self.model:
                    logger.warning(f"⚡ Failover: intentando con {model}")

                response = await self.client.chat.completions.create(**kwargs)
                
                if model != self.model:
                    logger.info(f"✅ Failover exitoso con {model}")
                
                return response.choices[0].message

            except Exception as e:
                last_error = e
                error_code = getattr(e, 'status_code', None) or str(e)[:50]
                logger.warning(f"❌ {model} falló: {error_code}")
                continue

        # Si todos los modelos fallaron
        raise last_error
