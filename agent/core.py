"""
agent/core.py — Cliente LLM usando Agno + NVIDIA NIM API

Usa agno.models.nvidia.Nvidia para construir el cliente async,
manteniendo failover entre modelos y la interface compatible con el loop ReAct.
"""
import os
import logging
from dotenv import load_dotenv

# Agno Nvidia model (configura base_url, api_key, timeouts automáticamente)
from agno.models.nvidia import Nvidia

load_dotenv()

logger = logging.getLogger("jada")

# Timeout para NIM — agresivo para failover rápido
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

# Modelos en orden de preferencia (failover)
PRIMARY_MODEL = os.getenv("NVIDIA_MODEL", "moonshotai/kimi-k2-thinking")
FALLBACK_MODELS = [
    "minimaxai/minimax-m2.1",
    "meta/llama-3.1-70b-instruct",
]


class NvidiaLLM:
    """
    Cliente LLM que usa Agno (agno.models.nvidia.Nvidia) como proveedor,
    con failover automático entre modelos y compatibilidad con el loop ReAct.
    """

    def __init__(self):
        self.model = PRIMARY_MODEL
        self._api_key = os.getenv("NVIDIA_API_KEY")
        self._base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
        # Crear el async client via Agno (reutilizable, con timeout configurado)
        self._async_client = self._build_agno_client(PRIMARY_MODEL).get_async_client()

    def _build_agno_client(self, model_id: str) -> Nvidia:
        """Construir instancia Agno Nvidia para el modelo dado."""
        return Nvidia(
            id=model_id,
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=LLM_TIMEOUT,
            max_retries=1,
        )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ):
        """
        Envía mensajes al LLM con failover automático entre modelos.
        Usa Agno como proveedor; devuelve el mensaje del modelo compatible
        con el loop ReAct (response.content, response.tool_calls).
        """
        models_to_try = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        last_error = None

        for model in models_to_try:
            try:
                if model != self.model:
                    logger.warning(f"⚡ Failover: intentando con {model}")
                    # Rebuild async client para el modelo de fallback
                    async_client = self._build_agno_client(model).get_async_client()
                else:
                    async_client = self._async_client

                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 16384,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice

                response = await async_client.chat.completions.create(**kwargs)

                if model != self.model:
                    logger.info(f"✅ Failover exitoso con {model}")

                return response.choices[0].message

            except Exception as e:
                last_error = e
                error_code = getattr(e, "status_code", None) or str(e)[:60]
                logger.warning(f"❌ {model} falló: {error_code}")
                continue

        raise last_error
