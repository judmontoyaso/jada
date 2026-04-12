import asyncio
import logging
import time
import urllib.request
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os

# Ensure we can import from the parent directory where agent.py lives
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] VoiceBridge: %(message)s"
)
logger = logging.getLogger("voice_bridge")

app = FastAPI(title="Jada Voice Bridge", version="1.0.0")

# Enable CORS for all origins (prototype)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    # Store request body if it's a POST to /jada/chat to log it
    body_str = ""
    if request.url.path == "/jada/chat" and request.method == "POST":
        try:
            body_bytes = await request.body()
            body_str = body_bytes.decode('utf-8')
            if len(body_str) > 80:
                body_str = body_str[:77] + "..."
        except Exception:
            pass

    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    
    log_msg = f"{request.method} {request.url.path} completed in {process_time:.2f}ms."
    if body_str:
        log_msg = f"Received: '{body_str}' | {log_msg}"
        
    logger.info(log_msg)
    
    return response

@app.get("/health")
async def health_check():
    return {"status": "ok", "jada": "connected"}

# === AssemblyAI Token Endpoint ===
ASSEMBLYAI_KEY = "43af8e3c66b84226b1fb8650a9af033b"

@app.get("/assemblyai/token")
async def get_assemblyai_token():
    # AssemblyAI V3 Universal Streaming token endpoint
    url = "https://streaming.assemblyai.com/v3/token?expires_in_seconds=600"
    
    try:
        def fetch_token():
            req = urllib.request.Request(url)
            req.add_header('Authorization', ASSEMBLYAI_KEY)
            response = urllib.request.urlopen(req)
            return json.loads(response.read().decode('utf-8'))
        
        data = await asyncio.to_thread(fetch_token)
        return {"token": data.get("token")}
    except Exception as e:
        logger.error(f"Error fetching AssemblyAI token: {e}")
        raise HTTPException(status_code=500, detail="Could not generate AssemblyAI token.")

# Initialize a persistent Agent for the bridge
jado_agent = Agent()

@app.on_event("startup")
async def startup_event():
    # Initialize DB connections for the agent when the server starts
    logger.info("Initializing Agent databases...")
    await jado_agent.init()
    logger.info("Agent initialized successfully.")

@app.post("/jada/chat", response_model=ChatResponse)
async def chat_with_jada(request: ChatRequest):
    message = request.message
    if not message.strip():
        return ChatResponse(response="Por favor envía un mensaje válido.")

    try:
        # Enforce a 45-second timeout on the async chat call
        # We pass a dummy user_id and room_id specifically for voice interactions
        # voice_only=True bypasses some tool routing logic if intended by the architecture
        answer = await asyncio.wait_for(
            jado_agent.chat(
                user_message=message,
                user_id="@voice:web",
                room_id="voice_bridge_room",
                voice_only=False  # Allow tools for now, voice_only=True disables them
            ),
            timeout=45.0
        )
        return ChatResponse(response=str(answer))

    except asyncio.TimeoutError:
        logger.warning(f"Timeout (45s) triggered for message: '{message[:30]}...'")
        return ChatResponse(response="Timeout — JADA tardó demasiado.")
    except Exception as e:
        logger.error(f"Error processing chat: {str(e)}")
        return ChatResponse(response=f"Error interno en JADA: {str(e)}")

# This allows running directly via `python voice_bridge.py` for debugging
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
