"""
tools/notes.py — CRUD de notas personales en MongoDB
"""
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGO_DB", "jada_db")
MONGO_COLLECTION = "notes"

class NotesDB:
    def __init__(self):
        self.client = MongoClient(MONGO_URI) if MONGO_URI else None
        self.db = self.client[MONGO_DB] if self.client else None
        self.collection = self.db[MONGO_COLLECTION] if self.db is not None else None

    async def init(self):
        """No requiere crear tablas, pero verificamos conexión a Mongo."""
        if not self.client:
            raise ConnectionError("MONGO_URI no está configurado en el archivo .env")
        # Aseguramos un índice para búsquedas de texto eficientes 
        # (Aunque aquí usaremos regex por simplicidad para igualar el comportamiento anterior)
        pass

    async def save_note(self, user_id: str, title: str, content: str, tags: str = "") -> dict:
        """Crear o actualizar una nota en MongoDB."""
        try:
            now = datetime.utcnow().isoformat()
            
            note_doc = {
                "user_id": user_id,
                "title": title,
                "content": content,
                "tags": tags,
                "created_at": now,
                "updated_at": now
            }
            
            # Operación bloqueante, la subimos a un executor de asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.collection.insert_one, note_doc)
            
            return {
                "success": True, 
                "note_id": str(result.inserted_id), 
                "title": title
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_notes(self, user_id: str, limit: int = 20) -> dict:
        """Listar las notas del usuario."""
        try:
            def _fetch_notes():
                # find() devuelve cursor, ordenado DESC por updated_at
                cursor = self.collection.find({"user_id": user_id}).sort("updated_at", -1).limit(limit)
                rows = []
                for doc in cursor:
                    doc["id"] = str(doc.pop("_id"))
                    rows.append(doc)
                return rows

            loop = asyncio.get_event_loop()
            rows = await loop.run_in_executor(None, _fetch_notes)
            
            return {"notes": rows, "count": len(rows)}
        except Exception as e:
            return {"error": str(e)}

    async def search_notes(self, user_id: str, query: str) -> dict:
        """Buscar notas por título, contenido o tags usando RegEx."""
        try:
            def _search():
                # Búsqueda case-insensitive ($options: "i") en varios campos usando $or
                regex_pattern = {"$regex": query, "$options": "i"}
                q_filter = {
                    "user_id": user_id,
                    "$or": [
                        {"title": regex_pattern},
                        {"content": regex_pattern},
                        {"tags": regex_pattern}
                    ]
                }
                cursor = self.collection.find(q_filter).sort("updated_at", -1).limit(10)
                
                rows = []
                for doc in cursor:
                    doc["id"] = str(doc.pop("_id"))
                    rows.append(doc)
                return rows

            loop = asyncio.get_event_loop()
            rows = await loop.run_in_executor(None, _search)
            
            return {"query": query, "results": rows, "count": len(rows)}
        except Exception as e:
            return {"error": str(e)}

    async def delete_note(self, user_id: str, note_id: str) -> dict:
        """Eliminar una nota por ObjectId."""
        try:
            from bson.errors import InvalidId
            try:
                obj_id = ObjectId(note_id)
            except InvalidId:
                return {"error": f"ID de nota inválido: {note_id}"}
                
            def _delete():
                return self.collection.delete_one({"_id": obj_id, "user_id": user_id})
                
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _delete)
            
            if result.deleted_count == 0:
                return {"error": f"Nota #{note_id} no encontrada o no pertenece al usuario"}
            
            return {"success": True, "deleted_id": note_id}
        except Exception as e:
            return {"error": str(e)}
