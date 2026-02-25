"""
tools/gym_db.py — Herramienta para gestionar entrenamientos de gym en MongoDB
Conecta a la colección `gimnasio` en MongoDB Atlas.
Conexión lazy: solo se conecta cuando se usa una tool de gym.

Schema de un documento:
{
    "id": "2026-01-15-push",
    "nombre": "Push - Pecho, Hombro y Tríceps",
    "tipo": "push",
    "fecha": "2026-01-15",
    "grupos_musculares": ["pecho", "hombros", "triceps"],
    "ejercicios": [
        {"nombre": "Press de pecho", "series": 4, "repeticiones": 10, "peso_kg": 40},
        ...
    ]
}
"""
import os
import json
import logging
from datetime import date
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://localhost:27017/n8n_memoria",
)
MONGO_DB = os.getenv("MONGO_DB", "n8n_memoria")
MONGO_COLLECTION = os.getenv("MONGO_GYM_COLLECTION", "gimnasio")


class GymDB:
    def __init__(self):
        self.client = None
        self.collection = None
        self._connected = False

    async def init(self):
        """No-op — la conexión es lazy para no agregar latencia en cada mensaje."""
        pass

    def _ensure_connected(self):
        """Conectar a MongoDB solo cuando se necesite (lazy)."""
        if self._connected:
            return
        try:
            self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            db = self.client[MONGO_DB]
            self.collection = db[MONGO_COLLECTION]
            self.client.server_info()
            count = self.collection.count_documents({})
            logger.info(f"🏋️ MongoDB gym conectado — {count} entrenamientos encontrados")
            self._connected = True
        except Exception as e:
            logger.error(f"❌ Error conectando a MongoDB gym: {e}")
            raise

    def _serialize_doc(self, doc: dict) -> dict:
        """Convertir un documento de MongoDB a un dict serializable."""
        if doc is None:
            return None
        doc["_id"] = str(doc["_id"])
        return doc

    async def save_workout(
        self,
        name: str,
        date_str: str,
        exercises: list[dict],
        tipo: str = "",
        grupos_musculares: list[str] = None,
        notes: str = "",
    ) -> dict:
        """
        Guardar un entrenamiento con sus ejercicios.
        exercises: [{"nombre": "Sentadilla", "series": 4, "repeticiones": 10, "peso_kg": 60}]
        """
        try:
            self._ensure_connected()
            
            # Fix: normalizar fechas relativas
            from datetime import date, timedelta
            fecha_lower = date_str.strip().lower()
            if fecha_lower in ("hoy", "today"):
                date_str = date.today().isoformat()
            elif fecha_lower in ("ayer", "yesterday"):
                date_str = (date.today() - timedelta(days=1)).isoformat()
            elif fecha_lower in ("anteayer", "antier"):
                date_str = (date.today() - timedelta(days=2)).isoformat()
            logger.info(f"📅 Fecha normalizada: {fecha_lower} → {date_str}")
            
            # Fix: el LLM a veces pasa strings JSON en vez de listas
            import json as _json
            if isinstance(exercises, str):
                try:
                    exercises = _json.loads(exercises)
                except _json.JSONDecodeError:
                    return {"error": "exercises debe ser una lista JSON válida"}
            
            if isinstance(grupos_musculares, str):
                try:
                    grupos_musculares = _json.loads(grupos_musculares)
                except _json.JSONDecodeError:
                    grupos_musculares = [g.strip() for g in grupos_musculares.split(",")]

            workout_id = f"{date_str}-{tipo}" if tipo else f"{date_str}-workout"

            doc = {
                "id": workout_id,
                "nombre": name,
                "tipo": tipo or "general",
                "fecha": date_str,
                "grupos_musculares": grupos_musculares or [],
                "ejercicios": exercises,
            }
            if notes:
                doc["notas"] = notes

            result = self.collection.insert_one(doc)
            logger.info(f"💾 Entrenamiento guardado: {workout_id} ({len(exercises)} ejercicios)")
            return {
                "success": True,
                "workout_id": workout_id,
                "mongo_id": str(result.inserted_id),
                "exercises_saved": len(exercises),
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_recent_workouts(self, limit: int = 10) -> dict:
        """Obtener los últimos N entrenamientos."""
        try:
            self._ensure_connected()
            docs = list(
                self.collection.find({})
                .sort("fecha", DESCENDING)
                .limit(limit)
            )
            workouts = [self._serialize_doc(d) for d in docs]
            return {"workouts": workouts, "count": len(workouts)}
        except Exception as e:
            return {"error": str(e)}

    async def get_exercise_history(self, exercise_name: str, limit: int = 10) -> dict:
        """Ver el historial de un ejercicio específico (progresión de peso/reps)."""
        try:
            self._ensure_connected()
            import re
            pattern = re.compile(exercise_name, re.IGNORECASE)

            docs = list(
                self.collection.find(
                    {"ejercicios.nombre": {"$regex": pattern}}
                )
                .sort("fecha", DESCENDING)
                .limit(limit)
            )

            history = []
            for doc in docs:
                for ej in doc.get("ejercicios", []):
                    if pattern.search(ej.get("nombre", "")):
                        history.append({
                            "fecha": doc.get("fecha"),
                            "workout": doc.get("nombre"),
                            "ejercicio": ej.get("nombre"),
                            "series": ej.get("series"),
                            "repeticiones": ej.get("repeticiones"),
                            "peso_kg": ej.get("peso_kg"),
                        })

            return {
                "exercise": exercise_name,
                "history": history,
                "count": len(history),
            }
        except Exception as e:
            return {"error": str(e)}

    async def save_routine(self, name: str, description: str = "", exercises: list[dict] = None) -> dict:
        """Guardar una rutina generada por el agente."""
        try:
            self._ensure_connected()
            doc = {
                "id": f"rutina-{name.lower().replace(' ', '-')}",
                "nombre": name,
                "tipo": "rutina",
                "fecha": date.today().isoformat(),
                "descripcion": description,
                "ejercicios": exercises or [],
                "es_rutina": True,
            }
            result = self.collection.insert_one(doc)
            return {"success": True, "routine_id": str(result.inserted_id)}
        except Exception as e:
            return {"error": str(e)}

    async def get_routines(self) -> dict:
        """Obtener todas las rutinas guardadas."""
        try:
            self._ensure_connected()
            docs = list(self.collection.find({"es_rutina": True}).sort("fecha", DESCENDING))
            routines = [self._serialize_doc(d) for d in docs]
            return {"routines": routines, "count": len(routines)}
        except Exception as e:
            return {"error": str(e)}

    async def get_stats(self) -> dict:
        """Estadísticas generales: total entrenamientos, ejercicios más usados."""
        try:
            self._ensure_connected()
            total_workouts = self.collection.count_documents({"es_rutina": {"$ne": True}})

            # Pipeline de agregación para encontrar ejercicios más frecuentes
            pipeline = [
                {"$match": {"es_rutina": {"$ne": True}}},
                {"$unwind": "$ejercicios"},
                {"$group": {"_id": "$ejercicios.nombre", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 5},
            ]
            top = list(self.collection.aggregate(pipeline))
            top_exercises = [{"name": t["_id"], "times": t["count"]} for t in top]

            # Total de ejercicios registrados
            pipeline_total = [
                {"$match": {"es_rutina": {"$ne": True}}},
                {"$unwind": "$ejercicios"},
                {"$count": "total"},
            ]
            total_result = list(self.collection.aggregate(pipeline_total))
            total_exercises = total_result[0]["total"] if total_result else 0

            return {
                "total_workouts": total_workouts,
                "total_exercises_logged": total_exercises,
                "top_exercises": top_exercises,
            }
        except Exception as e:
            return {"error": str(e)}
