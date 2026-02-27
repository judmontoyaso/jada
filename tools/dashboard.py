"""
tools/dashboard.py — Dashboard web para Jada
Sirve una página HTML con stats del agente, memoria y actividad reciente.
Se levanta en un puerto local (default: 8080).
"""
import os
import json
import logging
import asyncio
import sqlite3
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
MEMORY_DB = os.getenv("MEMORY_DB_PATH", "memory.db")


def _get_stats() -> dict:
    """Obtener estadísticas del bot desde SQLite."""
    stats = {
        "total_messages": 0,
        "total_facts": 0,
        "rooms": [],
        "recent_messages": [],
        "facts": [],
        "uptime_since": datetime.now().isoformat(),
    }

    try:
        if not os.path.exists(MEMORY_DB):
            return stats

        conn = sqlite3.connect(MEMORY_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Total mensajes
        try:
            cursor.execute("SELECT COUNT(*) FROM messages")
            stats["total_messages"] = cursor.fetchone()[0]
        except Exception:
            pass

        # Rooms activos
        try:
            cursor.execute("SELECT DISTINCT room_id FROM messages")
            stats["rooms"] = [row[0] for row in cursor.fetchall()]
        except Exception:
            pass

        # Últimos 20 mensajes
        try:
            cursor.execute("""
                SELECT role, content, room_id, user_id, timestamp 
                FROM messages 
                ORDER BY id DESC LIMIT 20
            """)
            stats["recent_messages"] = [
                {
                    "role": row["role"],
                    "content": row["content"][:200] if row["content"] else "",
                    "room_id": row["room_id"],
                    "user_id": row["user_id"],
                    "timestamp": row["timestamp"],
                }
                for row in cursor.fetchall()
            ]
        except Exception:
            pass

        # Facts del usuario
        try:
            cursor.execute("SELECT user_id, fact, created_at FROM facts ORDER BY id DESC")
            stats["facts"] = [
                {
                    "user_id": row["user_id"],
                    "fact": row["fact"],
                    "created_at": row["created_at"],
                }
                for row in cursor.fetchall()
            ]
            stats["total_facts"] = len(stats["facts"])
        except Exception:
            pass

        conn.close()
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")

    return stats


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jada Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a25;
            --bg-card-hover: #22222f;
            --text-primary: #e8e8ef;
            --text-secondary: #8888a0;
            --text-muted: #55556a;
            --accent: #6366f1;
            --accent-glow: rgba(99, 102, 241, 0.15);
            --green: #22c55e;
            --orange: #f59e0b;
            --red: #ef4444;
            --blue: #3b82f6;
            --border: rgba(255,255,255,0.06);
            --radius: 12px;
        }

        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }

        /* Header */
        .header {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 2.5rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
        }
        .header .logo {
            font-size: 2.5rem;
            filter: drop-shadow(0 0 12px var(--accent-glow));
        }
        .header h1 {
            font-size: 1.8rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent), #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header .status {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--green);
            font-size: 0.85rem;
            font-weight: 500;
        }
        .header .status::before {
            content: '';
            width: 8px; height: 8px;
            background: var(--green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            transition: all 0.2s;
        }
        .stat-card:hover {
            background: var(--bg-card-hover);
            border-color: rgba(99, 102, 241, 0.2);
            transform: translateY(-2px);
        }
        .stat-card .label {
            font-size: 0.8rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }
        .stat-card .value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent);
        }
        .stat-card .sub {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 0.25rem;
        }

        /* Sections */
        .section {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            margin-bottom: 1.5rem;
            overflow: hidden;
        }
        .section-header {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-weight: 600;
        }
        .section-header .icon { font-size: 1.2rem; }
        .section-body { padding: 1rem 1.5rem; }

        /* Messages */
        .message {
            display: flex;
            gap: 1rem;
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--border);
        }
        .message:last-child { border-bottom: none; }
        .message .role {
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            white-space: nowrap;
            height: fit-content;
        }
        .message .role.user { background: rgba(59,130,246,0.15); color: var(--blue); }
        .message .role.assistant { background: rgba(99,102,241,0.15); color: var(--accent); }
        .message .content {
            font-size: 0.85rem;
            color: var(--text-secondary);
            word-break: break-word;
        }
        .message .meta {
            margin-left: auto;
            font-size: 0.7rem;
            color: var(--text-muted);
            white-space: nowrap;
        }

        /* Facts */
        .fact {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.6rem 0;
            border-bottom: 1px solid var(--border);
        }
        .fact:last-child { border-bottom: none; }
        .fact .bullet {
            color: var(--accent);
            font-weight: bold;
            margin-top: 2px;
        }
        .fact .text { font-size: 0.9rem; }

        /* Refresh */
        .refresh-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }
        .refresh-bar .time { font-size: 0.8rem; color: var(--text-muted); }
        .btn {
            background: var(--accent);
            color: white;
            border: none;
            padding: 0.5rem 1.2rem;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn:hover { opacity: 0.85; transform: translateY(-1px); }

        .empty { 
            text-align: center; 
            padding: 2rem; 
            color: var(--text-muted);
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span class="logo">🤖</span>
            <h1>Jada Dashboard</h1>
            <div class="status">Online</div>
        </div>

        <div class="refresh-bar">
            <span class="time" id="lastUpdate">Cargando...</span>
            <button class="btn" onclick="loadData()">⟳ Actualizar</button>
        </div>

        <div class="stats-grid" id="statsGrid"></div>

        <div class="section">
            <div class="section-header">
                <span class="icon">🧠</span> Hechos del usuario
            </div>
            <div class="section-body" id="factsList"></div>
        </div>

        <div class="section">
            <div class="section-header">
                <span class="icon">💬</span> Actividad reciente
            </div>
            <div class="section-body" id="messagesList"></div>
        </div>
    </div>

    <script>
        async function loadData() {
            try {
                const resp = await fetch('/api/stats');
                const data = await resp.json();
                renderStats(data);
                renderFacts(data.facts || []);
                renderMessages(data.recent_messages || []);
                document.getElementById('lastUpdate').textContent = 
                    `Última actualización: ${new Date().toLocaleTimeString()}`;
            } catch (e) {
                console.error('Error cargando datos:', e);
            }
        }

        function renderStats(data) {
            const grid = document.getElementById('statsGrid');
            grid.innerHTML = `
                <div class="stat-card">
                    <div class="label">Mensajes totales</div>
                    <div class="value">${data.total_messages || 0}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Hechos guardados</div>
                    <div class="value">${data.total_facts || 0}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Rooms activos</div>
                    <div class="value">${(data.rooms || []).length}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Modelo</div>
                    <div class="value" style="font-size:0.9rem">MiniMax M2.1</div>
                    <div class="sub">NVIDIA NIM</div>
                </div>
            `;
        }

        function renderFacts(facts) {
            const el = document.getElementById('factsList');
            if (!facts.length) {
                el.innerHTML = '<div class="empty">No hay hechos guardados aún</div>';
                return;
            }
            el.innerHTML = facts.map(f => `
                <div class="fact">
                    <span class="bullet">→</span>
                    <span class="text">${escapeHtml(f.fact)}</span>
                </div>
            `).join('');
        }

        function renderMessages(messages) {
            const el = document.getElementById('messagesList');
            if (!messages.length) {
                el.innerHTML = '<div class="empty">No hay mensajes recientes</div>';
                return;
            }
            el.innerHTML = messages.map(m => `
                <div class="message">
                    <span class="role ${m.role}">${m.role}</span>
                    <span class="content">${escapeHtml(m.content)}</span>
                    <span class="meta">${m.timestamp || ''}</span>
                </div>
            `).join('');
        }

        function escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }

        // Auto-refresh cada 30s
        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """Handler HTTP para el dashboard."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/stats":
            stats = _get_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Silenciar logs HTTP."""
        pass


def start_dashboard(port: int = DASHBOARD_PORT):
    """Iniciar el dashboard en un thread separado."""
    try:
        server = HTTPServer(("0.0.0.0", port), DashboardHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"📊 Dashboard disponible en http://localhost:{port}")
        return server
    except OSError as e:
        logger.warning(f"⚠️ No se pudo iniciar el dashboard en puerto {port}: {e}")
        return None
