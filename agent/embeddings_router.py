"""
agent/embeddings_router.py — Semantic tool group router using all-MiniLM-L6-v2

Embeds example phrases per tool group at startup (~80MB RAM).
At runtime, encodes the user message and finds the closest groups via cosine similarity.
Used as fallback when keyword matching finds no groups.
"""
import logging
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("jada.embeddings")

# ── Example phrases per tool group ──
# More examples = better coverage of indirect/natural phrasing
GROUP_EXAMPLES: dict[str, list[str]] = {
    "notes": [
        "guarda esta nota", "anota esto", "apúntame algo",
        "escribe esto en mis notas", "qué notas tengo guardadas", "busca en mis notas",
        "borra esa nota que guardé", "dame mis apuntes guardados",
        "guárdame esta información como nota", "quiero guardar un apunte",
        "necesito escribir algo para no olvidarlo",
    ],
    "email": [
        "qué correos tengo", "revisa mi email", "manda un correo electrónico",
        "envíale un email a juan", "tengo correos sin leer", "buscar un email",
        "léeme ese correo electrónico", "responde ese mail", "escríbele por correo",
        "qué me llegó al buzón de correo", "envía un mensaje por email",
    ],
    "calendar": [
        "agenda una reunión", "qué eventos tengo en el calendario",
        "ponme una cita en la agenda", "cuándo es mi próxima reunión agendada",
        "agéndame algo para la tarde", "tengo algo programado en el calendario",
        "bloquear un espacio en la agenda", "cuándo estoy libre según mi calendario",
    ],
    "gym": [
        "registra mi entrenamiento", "hice pierna hoy", "cuánto peso levanté",
        "press banca 80kg 4x10", "mi rutina de hoy", "estadísticas de gym",
        "qué ejercicios hice la semana pasada", "guarda este workout",
        "empezar sesión de entrenamiento", "curl bicep 15kg",
        "sentadilla con barra", "muéstrame mi progreso de pecho",
    ],
    "tv": [
        "prende la tele", "apaga el televisor", "sube el volumen",
        "baja el volumen del tv", "pon netflix", "cambia de canal",
        "estado del samsung", "silencia la tv", "enciende el televisor",
    ],
    "reminders": [
        "recuérdame en 5 minutos", "pon una alarma", "avísame a las 3",
        "no dejes que se me olvide", "recordatorio para mañana",
        "pon un timer de 10 minutos", "necesito que me recuerdes algo",
        "recuérdame botar los zapatos", "despiértame en una hora",
    ],
    "cronjobs": [
        "programa una tarea diaria", "quiero que todos los días hagas esto",
        "crea un cronjob", "ejecutar algo cada hora", "tareas programadas",
        "qué tareas automáticas tengo", "elimina esa tarea recurrente",
        "cambia la frecuencia del job", "ejecuta esa tarea ahora",
    ],
    "web": [
        "busca información sobre", "qué dice google de", "noticias de hoy",
        "investiga sobre", "resumen de esta página", "abre esta url",
        "qué clima hace", "va a llover hoy", "temperatura en bogotá",
        "pronóstico del tiempo", "buscar en internet", "resúmeme este artículo",
    ],
    "files": [
        "lee ese archivo", "crea un archivo", "lista los archivos",
        "ejecuta este comando", "corre esto en terminal", "qué hay en esta carpeta",
        "edita el archivo config", "muestra el contenido de",
    ],
    "media": [
        "genera una imagen", "dibuja un gato", "crea una ilustración",
        "hazme un dibujo", "genera arte de", "quiero una imagen de",
    ],
    "think": [
        "analiza esto en detalle", "piensa profundamente sobre",
        "necesito un análisis completo", "ahonda en este tema",
        "dame una opinión detallada", "evalúa las opciones",
    ],
}

# Similarity threshold — below this, no group matches
SIMILARITY_THRESHOLD = 0.38


class EmbeddingRouter:
    """Semantic router for tool groups using sentence embeddings."""

    def __init__(self):
        self._model = None
        self._group_embeddings: dict[str, np.ndarray] = {}
        self._ready = False

    def load(self):
        """Load model and pre-compute group embeddings. Call once at startup."""
        try:
            logger.info("🧠 Cargando modelo de embeddings (multilingual-MiniLM)...")
            self._model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

            # Pre-compute average embedding per group
            for group, examples in GROUP_EXAMPLES.items():
                embeddings = self._model.encode(examples, normalize_embeddings=True)
                # Store the centroid (average) of all example embeddings
                self._group_embeddings[group] = np.mean(embeddings, axis=0)

            self._ready = True
            logger.info(f"✅ Embedding router listo ({len(self._group_embeddings)} grupos, {sum(len(v) for v in GROUP_EXAMPLES.values())} ejemplos)")
        except Exception as e:
            logger.error(f"❌ Error cargando embedding router: {e}")
            self._ready = False

    def route(self, message: str, top_k: int = 2) -> list[str]:
        """
        Find the most relevant tool groups for a message.
        Returns list of group names sorted by relevance.
        """
        if not self._ready or not message.strip():
            return []

        try:
            # Encode the user message
            msg_embedding = self._model.encode(message, normalize_embeddings=True)

            # Compute cosine similarity with each group centroid
            scores: list[tuple[str, float]] = []
            for group, group_emb in self._group_embeddings.items():
                similarity = float(np.dot(msg_embedding, group_emb))
                if similarity >= SIMILARITY_THRESHOLD:
                    scores.append((group, similarity))

            # Sort by similarity (highest first) and return top_k
            scores.sort(key=lambda x: x[1], reverse=True)
            result = [g for g, _ in scores[:top_k]]

            if result:
                top_scores = ", ".join(f"{g}={s:.2f}" for g, s in scores[:top_k])
                logger.info(f"🧠 Embedding route: [{top_scores}]")

            return result

        except Exception as e:
            logger.error(f"❌ Embedding route error: {e}")
            return []


# Singleton instance
_router: EmbeddingRouter | None = None


def get_router() -> EmbeddingRouter:
    """Get or create the global embedding router."""
    global _router
    if _router is None:
        _router = EmbeddingRouter()
        _router.load()
    return _router
