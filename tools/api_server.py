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
class DailyMetric(BaseModel):
    date: str
    total_tokens: int
    total_runs: int
    avg_latency_s: float

@app.get("/api/v1/metrics/daily", response_model=List[DailyMetric], tags=["Metrics"])
def get_daily_metrics(days: int = 7):
    """Returns aggregated token usage and run counts grouped by day."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # SQLite date() function extracts YYYY-MM-DD from the ISO8601 created_at string
        cursor.execute("""
            SELECT 
                date(created_at) as run_date,
                SUM(total_tokens) as tokens,
                COUNT(*) as runs,
                AVG(latency_s) as avg_latency
            FROM run_metrics 
            GROUP BY run_date
            ORDER BY run_date DESC
            LIMIT ?
        """, (days,))
        
        return [
            DailyMetric(
                date=row["run_date"],
                total_tokens=row["tokens"],
                total_runs=row["runs"],
                avg_latency_s=round(row["avg_latency"], 3) if row["avg_latency"] else 0.0
            ) 
            for row in cursor.fetchall() if row["run_date"]
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

class ModelSpeed(BaseModel):
    model_id: str
    total_runs: int
    avg_latency_s: float
    avg_total_time_s: float

@app.get("/api/v1/metrics/models", response_model=List[ModelSpeed], tags=["Metrics"])
def get_model_speeds():
    """Returns average latency and processing times grouped by LLM model."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                model_id,
                COUNT(*) as runs,
                AVG(latency_s) as avg_latency,
                AVG(total_time_s) as avg_total_time
            FROM run_metrics 
            GROUP BY model_id
            ORDER BY runs DESC
        """)
        return [
            ModelSpeed(
                model_id=row["model_id"],
                total_runs=row["runs"],
                avg_latency_s=round(row["avg_latency"], 3) if row["avg_latency"] else 0.0,
                avg_total_time_s=round(row["avg_total_time"], 3) if row["avg_total_time"] else 0.0
            ) 
            for row in cursor.fetchall() if row["model_id"]
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

class ToolUsage(BaseModel):
    tool_name: str
    times_used: int

@app.get("/api/v1/metrics/tools", response_model=List[ToolUsage], tags=["Metrics"])
def get_tools_usage():
    """Parses tool usage and returns the ranking of most utilized tools."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT tools_used FROM run_metrics WHERE tools_used != '' AND tools_used IS NOT NULL")
        tool_counts = {}
        for row in cursor.fetchall():
            tools_str = row["tools_used"]
            for tool in tools_str.split(","):
                tool = tool.strip()
                if tool:
                    tool_counts[tool] = tool_counts.get(tool, 0) + 1
        
        # Sort top 20 by usage
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        return [ToolUsage(tool_name=k, times_used=v) for k, v in sorted_tools]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

@app.get("/api/v1/messages/{session_id}", response_model=List[RecentMessage], tags=["Data"])
def get_session_messages(session_id: str):
    """Returns the full conversation history for a specific room (session_id)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT runs FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        
        if not row or not row['runs']:
            raise HTTPException(status_code=404, detail="Session not found or empty")
            
        runs_list = json.loads(row['runs'])
        msgs = []
        
        for run in runs_list:
            req = run.get('request', {})
            resp = run.get('response', {})
            
            if req and req.get('content'):
                msgs.append(RecentMessage(
                    role="user",
                    content=str(req['content']),
                    room_id=session_id,
                    timestamp=str(run.get('created_at', ''))
                ))
            if resp and resp.get('message', {}).get('content'):
                msgs.append(RecentMessage(
                    role="assistant",
                    content=str(resp['message']['content']),
                    room_id=session_id,
                    timestamp=str(run.get('created_at', ''))
                ))
        return msgs
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
        # Efficient tail implementation to avoid loading massive files into RAM
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            filesize = f.tell()
            block_size = 1024
            position = filesize
            found_lines = []
            
            # Read from end to start
            while position > 0 and len(found_lines) <= lines:
                read_size = min(block_size, position)
                position -= read_size
                f.seek(position)
                block = f.read(read_size)
                
                # Split and add
                lines_in_block = block.split(b'\n')
                
                if found_lines:
                    found_lines[0] = lines_in_block[-1] + found_lines[0]
                    found_lines = lines_in_block[:-1] + found_lines
                else:
                    found_lines = lines_in_block
                    
            # Decode the required last 'lines' rows
            content = [line.decode("utf-8", errors="replace") for line in found_lines[-lines:] if line]
            return {"lines": content}
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
