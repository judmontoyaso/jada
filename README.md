# 🖤 Jada — Personal AI Agent

> Agente de IA personal construido desde cero. Matrix como interfaz, NVIDIA NIM como cerebro, cafeína como combustible.

```
     ██╗ █████╗ ██████╗  █████╗
     ██║██╔══██╗██╔══██╗██╔══██╗
     ██║███████║██║  ██║███████║
██   ██║██╔══██║██║  ██║██╔══██║
╚█████╔╝██║  ██║██████╔╝██║  ██║
 ╚════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝
       Personal AI Agent — 5panes
```

## ¿Qué es Jada?

Jada es un agente de IA personal que vive en Matrix. Tiene humor negro, es directa, sarcástica con cariño, y útil de verdad. No pone "¿En qué más te puedo ayudar?" al final de cada mensaje. Ejecuta acciones reales, no simula.

## Características

- **Personalidad** — Definida en `.agent/soul.md`. Humor negro, directa, técnica cuando toca.
- **Heartbeat** — Se activa proactivamente cada X horas. Hace chistes, da consejos, pregunta algo. Configurable en `.agent/heartbeat.md`.
- **Cronjobs** — Tareas programadas en lenguaje natural. "Revisa mi correo cada 30 minutos."
- **Tools reales** — Correo (IMAP), Google Calendar, gym log (MongoDB), TV Samsung, web search, shell, notas.
- **ReAct loop** — Razona → activa tool → observa resultado → responde. No inventa.
- **Failover de LLM** — Kimi K2 Thinking → MiniMax M2.1 → LLaMA 70B.
- **Dashboard** — Next.js en `jada_dashboard/`. Logs en vivo, editor de MD, gestor de cronjobs.
- **Typing indicator** — "escribiendo..." real en Matrix mientras piensa.
- **Watchdog** — Si el LLM tarda >25s avisa que sigue viva. A los 90s se rinde con dignidad.

## Stack

| Capa | Tecnología |
|------|-----------|
| Interfaz | Matrix (matrix-nio) |
| LLM | NVIDIA NIM — Kimi K2 Thinking |
| LLM Client | **Agno** (`agno.models.nvidia`) — failover automático |
| Memoria | SQLite (historial) + MongoDB (gym) |
| Scheduler | croniter + asyncio |
| Dashboard | Next.js 16 + TypeScript |
| Runtime | Python 3.11+ / systemd |

## Estructura

```
jada/
├── .agent/             # Configuración del agente (en git)
│   ├── soul.md         # Personalidad de Jada
│   ├── user.md         # Información del usuario
│   ├── heartbeat.md    # Config del heartbeat proactivo
│   └── identity.md     # Identidad adicional
├── agent/
│   ├── agent.py        # Loop ReAct + tool selection
│   ├── core.py         # Cliente LLM con failover
│   ├── heartbeat.py    # Voz proactiva
│   ├── memory.py       # Historial + facts (SQLite)
│   ├── scheduler.py    # Cronjobs con croniter
│   └── tools.py        # Schemas + dispatcher
├── matrix/
│   └── client.py       # Bot Matrix con typing indicator
├── tools/              # Implementaciones de tools
│   ├── email.py        # IMAP Gmail
│   ├── calendar.py     # Google Calendar ICS
│   ├── gym_db.py       # MongoDB gym log
│   ├── shell.py        # Comandos de sistema
│   ├── web_search.py   # Brave Search API
│   └── ...
├── main.py             # Entrada principal
└── jada_dashboard/     # Dashboard Next.js
```

## Setup rápido

```bash
# 1. Clonar
git clone https://github.com/judmontoyaso/jada.git
cd jada

# 2. Entorno virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Dependencias
pip install -r requirements.txt

# 4. Configurar
cp .env.example .env
# Editar .env con tus credenciales

# 5. Arrancar
python main.py              # modo silencioso
python main.py --livelogs   # con logs en pantalla
```

## Variables de entorno (.env)

```env
# LLM
NVIDIA_API_KEY=nvapi-...
NVIDIA_MODEL=moonshotai/kimi-k2-thinking

# Matrix
MATRIX_HOMESERVER=https://matrix.tu-servidor.me
MATRIX_USER=@jada:matrix.tu-servidor.me
MATRIX_ACCESS_TOKEN=syt_...

# Correo (IMAP)
IMAP_SERVER=imap.gmail.com
IMAP_USER=tu@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx  # App Password

# MongoDB (gym log)
MONGO_URI=mongodb+srv://...

# Timeouts (opcionales)
JADA_THINK_TIMEOUT=90   # seg máx para responder
JADA_NUDGE_AFTER=25     # seg antes de avisar que sigue viva
```

## Correr en producción (systemd)

```ini
# /etc/systemd/system/jada.service
[Unit]
Description=Jada AI Agent
After=network.target

[Service]
User=root
WorkingDirectory=/opt/jada
ExecStart=/opt/jada/.venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/jada/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable jada
systemctl start jada
journalctl -u jada -f  # ver logs
```

## Comandos en Matrix

| Comando | Resultado |
|---------|-----------|
| `consulta mis correos` | Lista bandeja de entrada |
| `revisa el calendario` | Eventos de hoy |
| `cancela el cronjob de correos` | Elimina tarea programada |
| `mis tareas programadas` | Lista cronjobs activos |
| `recuérdame X en 30 minutos` | Recordatorio |
| `/clear` | Borra historial del chat |
| `un chiste` | 50/50 de que sea bueno |

## Dashboard

```bash
cd jada_dashboard
npm install
npm run dev   # http://localhost:3000
```

---

*Construida con amor, cafeína y mucho stack trace. — 5panes*
