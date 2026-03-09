"""
tools/metrics.py — Recolección de métricas de ejecución del modelo (tokens, latencia, herramientas)
Guarda la información de cada run de Jada (chat, hearbeat, crons) en memory.db.
"""
import logging
import sqlite3
import os
from datetime import datetime, timezone
from agno.agent import RunResponse

logger = logging.getLogger("jada.metrics")
MEMORY_DB = os.getenv("MEMORY_DB_PATH", "memory.db")


def init_metrics_db():
    """Asegura que la tabla de métricas existe en SQLite."""
    try:
        conn = sqlite3.connect(MEMORY_DB)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                model_id TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                latency_s REAL,
                total_time_s REAL,
                tools_used TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error inicializando DB de métricas: {e}")


def track_run_metrics(session_id: str, model_id: str, run_response: RunResponse, tools_used: list[str] = None):
    """Extrae las métricas del RunResponse de Agno y lo guarda en la base de datos."""
    if not run_response or not run_response.metrics:
        return
    
    try:
        metrics = run_response.metrics
        input_tokens = metrics.get("input_tokens", 0)
        output_tokens = metrics.get("output_tokens", 0)
        total_tokens = metrics.get("total_tokens", input_tokens + output_tokens)
        
        # Agno metrics times are in seconds
        latency = metrics.get("time_to_first_token", 0.0)
        total_time = metrics.get("time", 0.0)
        
        tools_str = ",".join(tools_used) if tools_used else ""
        now_str = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(MEMORY_DB)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO run_metrics 
            (session_id, model_id, input_tokens, output_tokens, total_tokens, latency_s, total_time_s, tools_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, model_id, input_tokens, output_tokens, total_tokens, latency, total_time, tools_str, now_str))
        conn.commit()
        conn.close()
        logger.debug(f"📊 Métricas guardadas: {total_tokens} tokens, {total_time:.2f}s ({model_id})")
    except Exception as e:
        logger.error(f"Error guardando métricas del run: {e}")

# Asegurar init al cargar el módulo
init_metrics_db()
