"""
tools/api_server.py — FastAPI Server providing robust endpoints for the Vercel Dashboard.
Replaces the old HTTP SimpleRequestHandler.
"""
import os
import json
import logging
import sqlite3
import asyncio
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
MEMORY_DB = os.getenv("MEMORY_DB_PATH", "memory.db")
LOG_FILE = os.getenv("LOG_FILE", "jada.log")
START_TIME = datetime.now()

app = FastAPI(
    title="Jada Agent API",
    description="Internal API for Jada Dashboard and metrics tracking.",
    version="1.0.0"
)

# Permitir conexiones desde Vercel o local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# --- Models ---
class MetricOverview(BaseModel):
    total_messages: int
    total_facts: int
    total_tokens_used: int
    total_runs: int
    uptime_since: str
    active_rooms: int

class RecentRun(BaseModel):
    session_id: str
    model_id: str
    total_tokens: int
    latency_s: float
    total_time_s: float
    tools_used: str
    created_at: str

class RecentMessage(BaseModel):
    role: str
    content: str
    room_id: str
    timestamp: str

class SystemStatus(BaseModel):
    status: str
    uptime_seconds: float
    version: str

# --- Helpers ---
def get_db_connection():
    if not os.path.exists(MEMORY_DB):
        raise HTTPException(status_code=503, detail="Database not initialized yet")
    conn = sqlite3.connect(MEMORY_DB)
    conn.row_factory = sqlite3.Row
    return conn

# --- Endpoints ---

@app.get("/api/v1/status", response_model=SystemStatus, tags=["System"])
def get_status():
    """Returns general service health and uptime."""
    delta = datetime.now() - START_TIME
    return SystemStatus(
        status="online",
        uptime_seconds=delta.total_seconds(),
        version="0.5.2"
    )

@app.get("/api/v1/metrics/overview", response_model=MetricOverview, tags=["Metrics"])
def get_metrics_overview():
    """Returns generic counters and aggregated metric data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM sessions")
        msg_count = cursor.fetchone()[0]
        
        # Agno stores memories (facts) in the sessions JSON, or we might skip it if not custom tracked
        fact_count = 0 
        
        # Rooms can be mapped to session_id
        cursor.execute("SELECT COUNT(DISTINCT session_id) FROM sessions")
        room_count = cursor.fetchone()[0]

        tokens = 0
        runs = 0
        try:
            cursor.execute("SELECT SUM(total_tokens), COUNT(*) FROM run_metrics")
            res = cursor.fetchone()
            if res and res[0]:
                tokens = res[0]
                runs = res[1]
        except sqlite3.OperationalError:
            pass # Table might not exist if no runs yet
            
        return MetricOverview(
            total_messages=msg_count,
            total_facts=fact_count,
            total_tokens_used=tokens,
            total_runs=runs,
            active_rooms=room_count,
            uptime_since=START_TIME.isoformat()
        )
    finally:
        conn.close()

@app.get("/api/v1/metrics/recent", response_model=List[RecentRun], tags=["Metrics"])
def get_recent_metrics(limit: int = 50):
    """Returns performance metrics for recent LLM inferences (latency, tokens)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT session_id, model_id, total_tokens, latency_s, total_time_s, tools_used, created_at
            FROM run_metrics 
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        
        return [RecentRun(**dict(row)) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return [] # Table might be empty
    finally:
        conn.close()

@app.get("/api/v1/messages", response_model=List[RecentMessage], tags=["Data"])
def get_recent_messages(limit: int = 20):
    """Returns the last messages from the chat history."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Agno sessions schema stores history in `runs` JSON blob
        cursor.execute("""
            SELECT session_id, runs
            FROM sessions 
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        
        msgs = []
        for row in cursor.fetchall():
            try:
                runs_list = json.loads(row['runs']) if row['runs'] else []
                if runs_list and isinstance(runs_list, list):
                    last_run = runs_list[-1]
                    req = last_run.get('request', {})
                    resp = last_run.get('response', {})
                    if req and req.get('content'):
                        msgs.append(RecentMessage(
                            role="user",
                            content=str(req['content'])[:200],
                            room_id=row['session_id'],
                            timestamp=str(last_run.get('created_at', ''))
                        ))
                    if resp and resp.get('message', {}).get('content'):
                        msgs.append(RecentMessage(
                            role="assistant",
                            content=str(resp['message']['content'])[:200],
                            room_id=row['session_id'],
                            timestamp=str(last_run.get('created_at', ''))
                        ))
            except Exception as e:
                logger.error(f"Error parsing session data: {e}")
                
        # Limit to the requested capacity
        return msgs[:limit]
    finally:
        conn.close()

@app.get("/api/v1/logs", tags=["System"])
def get_recent_logs(lines: int = 100):
    """Reads the tail of jada.log to report recent system activity."""
    if not os.path.exists(LOG_FILE):
        raise HTTPException(status_code=404, detail="Log file directly not found")
        
    try:
        # Simple tail implementation
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().splitlines()
            return {"lines": content[-lines:]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read logs: {e}")

@app.get("/api/v1/cronjobs", tags=["System"])
def get_cronjobs():
    """Returns the current list of scheduled background tasks."""
    # Since scheduler lives in memory, we provide it via the app instance if attached
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        return {"cronjobs": list(scheduler.list_jobs())}
    return {"cronjobs": [], "note": "Scheduler instance not linked to web app"}

# --- Server Start ---
def start_api_server(scheduler_instance=None, port: int = DASHBOARD_PORT):
    """Lanza uvicorn en un Custom Task (Non-blocking para Main.py)."""
    app.state.scheduler = scheduler_instance
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    
    # Run uvicorn task asynchronously
    asyncio.create_task(server.serve())
    logger.info(f"📊 Dashboard API (FastAPI) disponible en http://localhost:{port}/docs")
    return server
