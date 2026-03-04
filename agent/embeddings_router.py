"""
agent/embeddings_router.py — Router semántico usando NVIDIA NIM Embeddings API

Reemplaza sentence-transformers local (~400MB RAM) con API remota (~0 RAM).
Usa nvidia/nv-embedqa-e5-v5 (1024 dims) vía integrate.api.nvidia.com.

Pre-computa centroides de tool groups y guarda en disco.
En runtime: embed query → cosine similarity → best group.
"""
import os
import json
import logging
import numpy as np
import requests
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
EMBED_MODEL = "nvidia/nv-embedqa-e5-v5"
EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"
SIMILARITY_THRESHOLD = 0.38
CENTROIDS_PATH = Path(__file__).parent.parent / "data" / "tool_centroids.json"

# Example phrases per tool group (for centroid computation)
GROUP_EXAMPLES = {
    "notes": [
        "guarda esta nota", "anota esto", "apunta que", "guardar información",
        "recordar esto", "agregar nota", "escribe esto", "toma nota",
    ],
    "email": [
        "revisa el correo", "envía un email", "lee los correos",
        "qué hay en el inbox", "mandar un correo", "responde ese email",
    ],
    "calendar": [
        "qué tengo hoy", "agenda del día", "crear evento", "programar reunión",
        "cita con el dentista", "mi calendario", "próximos eventos",
    ],
    "gym": [
        "registrar entrenamiento", "cuántas series hice", "rutina de hoy",
        "agregar ejercicio", "mi progreso en el gym", "historial de entreno",
    ],
    "tv": [
        "prende la tele", "apaga el televisor", "sube el volumen",
        "cambia de canal", "estado del tv samsung",
    ],
    "reminders": [
        "recuérdame en 30 minutos", "pon una alarma", "avísame cuando",
        "recordatorio para mañana", "no me dejes olvidar",
    ],
    "web": [
        "busca en internet", "qué dice google sobre", "noticias de hoy",
        "investiga sobre", "cómo está el clima", "resumen de esta url",
    ],
    "files": [
        "ejecuta este comando", "lee este archivo", "lista la carpeta",
        "qué hay en el directorio", "crea un archivo",
    ],
    "media": [
        "genera una imagen de", "dibuja un gato", "crea una foto artística",
        "mándame la imagen", "envía el archivo",
    ],
    "think": [
        "analiza esto en detalle", "piensa profundamente sobre",
        "dame un análisis exhaustivo", "reflexiona sobre",
    ],
    "cronjobs": [
        "crea una tarea programada", "lista los cronjobs",
        "programar algo para cada hora", "borrar tarea automática",
    ],
}


def _embed_texts(texts: list[str], input_type: str = "query") -> list[list[float]]:
    """Call NVIDIA NIM embedding API."""
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "input": texts,
        "model": EMBED_MODEL,
        "input_type": input_type,
    }
    resp = requests.post(EMBED_URL, json=data, headers=headers, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    return [item["embedding"] for item in result["data"]]


class EmbeddingRouter:
    """Routes user queries to tool groups using cosine similarity."""

    def __init__(self):
        self._centroids: dict[str, np.ndarray] = {}
        self._loaded = False

    def _load_or_compute_centroids(self):
        """Load pre-computed centroids from disk, or compute and save."""
        if self._loaded:
            return

        # Try loading from cache
        if CENTROIDS_PATH.exists():
            try:
                raw = json.loads(CENTROIDS_PATH.read_text())
                self._centroids = {k: np.array(v) for k, v in raw.items()}
                self._loaded = True
                logger.info(f"🧠 Centroides cargados desde cache ({len(self._centroids)} groups)")
                return
            except Exception as e:
                logger.warning(f"⚠️ Error leyendo centroides: {e}")

        # Compute centroids
        logger.info("🧠 Calculando centroides de tool groups via NVIDIA NIM...")
        for group, examples in GROUP_EXAMPLES.items():
            try:
                embeddings = _embed_texts(examples, input_type="passage")
                centroid = np.mean(embeddings, axis=0)
                centroid = centroid / np.linalg.norm(centroid)  # normalize
                self._centroids[group] = centroid
            except Exception as e:
                logger.warning(f"⚠️ Error embeddings para {group}: {e}")

        # Save to cache
        try:
            CENTROIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
            raw = {k: v.tolist() for k, v in self._centroids.items()}
            CENTROIDS_PATH.write_text(json.dumps(raw))
            logger.info(f"🧠 Centroides guardados en {CENTROIDS_PATH}")
        except Exception as e:
            logger.warning(f"⚠️ No se pudieron guardar centroides: {e}")

        self._loaded = True

    def route(self, query: str, top_k: int = 2) -> list[str]:
        """Embed query and find closest tool groups above threshold."""
        self._load_or_compute_centroids()

        if not self._centroids:
            return []

        try:
            q_emb = np.array(_embed_texts([query], input_type="query")[0])
            q_emb = q_emb / np.linalg.norm(q_emb)

            scores = {}
            for group, centroid in self._centroids.items():
                scores[group] = float(np.dot(q_emb, centroid))

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            matches = [g for g, s in ranked[:top_k] if s >= SIMILARITY_THRESHOLD]

            if matches:
                top_score = ranked[0][1]
                logger.info(f"🧠 Embedding match: {matches} (top score: {top_score:.3f})")

            return matches
        except Exception as e:
            logger.warning(f"⚠️ Error en embedding route: {e}")
            return []


# Singleton
_router: Optional[EmbeddingRouter] = None


def get_embedding_router() -> EmbeddingRouter:
    global _router
    if _router is None:
        _router = EmbeddingRouter()
    return _router


# Alias for backward compatibility
def get_router() -> EmbeddingRouter:
    return get_embedding_router()
