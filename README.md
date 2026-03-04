# 🖤 Jada — Personal AI Agent

> Agente de IA personal con patrón Coordinator + ReAct + Tool Group Routing. Matrix como interfaz, multi-LLM como cerebro, embeddings como radar.

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

## Patrón de Diseño Agéntico

Basado en el [Coordinator Pattern](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system?hl=es) de Google Cloud, con **Tool Group Routing** para minimizar tokens y latencia.

```mermaid
graph TD
    subgraph "Entrada"
        M["👤 Usuario (Matrix)"]
        A["🎤 Audio (Whisper)"]
        C["⏰ Cronjob"]
        H["💓 Heartbeat"]
    end

    M --> R["🧠 Agent.chat()"]
    A -->|"Groq Whisper<br/>STT"| R
    C --> R
    H --> R

    R --> D{"🔍 Intent Detection"}

    D -->|"1. Keywords<br/>(0ms)"| KW{"Match?"}
    KW -->|"Sí"| GRP["📦 Tool Groups<br/>3-8 tools"]
    KW -->|"No"| EMB["🧠 Embedding<br/>Router (277ms)<br/>MiniLM multilingual"]
    EMB -->|"Match ≥ 0.38"| GRP
    EMB -->|"No match"| CHAT["💬 Chat Agent<br/>0 tools → ~2s"]

    GRP --> ROUTE{"LLM Router"}
    ROUTE -->|"web/email/storage/think"| NV["🟢 MiniMax M2.5<br/>(NVIDIA NIM, $0)"]
    ROUTE -->|"otros"| GPT["🔵 GPT-5-mini<br/>(OpenAI)"]

    D -->|"Imagen"| VIS["👁️ Vision Agent<br/>Mistral Large 3"]

    CHAT -->|"Timeout"| FB{"⚠️ Failover"}
    NV -->|"Timeout"| FB
    GPT -->|"Timeout"| FB

    FB -->|"Retry"| FALL["🔄 Fallback<br/>GPT-4.1"]
    FALL --> OUT["📤 Matrix"]
    CHAT --> OUT
    NV --> OUT
    GPT --> OUT
    VIS --> OUT
```

### ¿Por qué este patrón?

| Decisión | Razón |
|---|---|
| **Tool Group Routing** | "Guarda nota" → solo 4 tools (notes), no 48+. Ahorra ~91% de tokens |
| **Multi-LLM** | MiniMax (gratis) para web/email/storage; GPT-5-mini para el resto |
| **Keywords + Embeddings** | Keywords para el 95% rápido; embeddings (MiniLM) para intenciones indirectas |
| **Coordinator (no multi-agent)** | Un solo punto de entrada simplifica debugging y estado |
| **ReAct loop** | El LLM razona → ejecuta tool → observa resultado → responde |
| **Failover automático** | Si el LLM primario falla (timeout 45s), GPT-4.1 toma el relevo |
| **Heartbeat proactivo** | Cada 2h decide si habla (chiste, consejo, pregunta) o se calla |

### Tool Groups

12 grupos de herramientas. Solo se inyectan los relevantes por request:

| Grupo | Tools | LLM | Ejemplo de activación |
|-------|-------|-----|-----------------------|
| `notes` | 4 | GPT | "guarda esta nota", "mis apuntes" |
| `email` | 4 | MiniMax | "correos sin leer", "envía un email" |
| `calendar` | 3 | GPT | "agenda reunión", "qué tengo hoy" |
| `gym` | 9 | GPT | "registra entrenamiento", "press banca" |
| `tv` | 3 | GPT | "prende la tele", "sube volumen" |
| `reminders` | 3 | GPT | "recuérdame en 5 min" |
| `cronjobs` | 5 | GPT | "programa tarea diaria" |
| `web` | 7 | MiniMax | "busca noticias", "clima", "resume URL" |
| `files` | 4 | GPT | "lee archivo", "ejecuta comando" |
| `media` | 3 | GPT | "genera una imagen de...", "envía foto" |
| `storage` | 6 | MiniMax | "sube archivo a la nube", "qué hay en storage" |
| `think` | 1 | MiniMax | "analiza esto en detalle" |

## Características

### Core
- **Personalidad** — Definida en `.agent/soul.md`. Humor negro, directa, técnica cuando toca.
- **Multi-LLM** — GPT-5-mini (primary), MiniMax M2.5 (gratis, tools), GPT-4.1 (fallback), Mistral Large 3 (vision).
- **Embedding Router** — `paraphrase-multilingual-MiniLM-L12-v2` detecta intenciones indirectas en 50+ idiomas.
- **Tool Group Routing** — Solo inyecta los tools relevantes (3-8 vs 48+). Ahorra ~90% de tokens.
- **ReAct loop** — Razona → activa tool → observa resultado → responde. No inventa.
- **Failover LLM** — GPT-5-mini → GPT-4.1 (automático en timeout).

### Voice (I/O)
- **STT (entrada)** — Mensajes de voz transcritos con Groq Whisper (`whisper-large-v3-turbo`). Soporta chunking para audios largos.
- **TTS (salida)** — Deepgram `aura-2-gloria-es` para respuestas por voz. Se activa en:
  - 💓 Heartbeats (chistes, consejos proactivos)
  - 🗣️ Petición explícita del usuario ("háblame", "dime en audio", "responde por voz")
  - Fallback automático a texto si el audio falla o la respuesta es muy larga.

### Cloud Storage
- **Supabase Storage** — Protocolo S3 vía boto3. Subir, listar, descargar y eliminar archivos desde el chat.
- URLs públicas para compartir archivos entre dispositivos (cel, PC, web).
- Keywords: "sube", "descarga", "storage", "nube", "comparte".

### Gym Room
- **Room dedicado** (`#gimnasio`) — Escribe ejercicios naturalmente, sin comandos de inicio.
- Jada buferea en silencio (reacción 🏋️ por mensaje).
- `/guardar` — MiniMax parsea el batch → estructura JSON → guarda en MongoDB.
- `/resumen` — Muestra buffer actual. `/cancelar` — Descarta.

### Proactividad
- **Heartbeat** — Se activa cada 2h. Chistes, consejos, preguntas. Config en `.agent/heartbeat.md`. Responde por voz.
- **Cronjobs** — Tareas programadas en lenguaje natural. Resúmenes de noticias, check de correo, etc.
- **Nudge inteligente** — Si tarda >20s avisa que sigue viva. A los 90s se rinde con dignidad.

### Herramientas
- **Correo** — IMAP (lectura) + SMTP (envío) Gmail.
- **Calendar** — Google Calendar API (OAuth2).
- **Gym** — MongoDB gym log con parser de notación (`3x10x80`).
- **Notas** — CRUD en MongoDB.
- **TV Samsung** — SmartThings API.
- **Web** — DuckDuckGo + Google News RSS. Clima: wttr.in → Open-Meteo (fallback).
- **Imagen** — Stable Diffusion 3 (NVIDIA NIM).
- **Shell** — Comandos de sistema (whitelist).
- **Browser** — Navegador headless.
- **Recordatorios** — Timer rápidos en minutos/horas.

## Stack

| Capa | Tecnología |
|------|-----------:|
| Interfaz | Matrix (matrix-nio) |
| LLM Primary | OpenAI — GPT-5-mini |
| LLM Tools (gratis) | MiniMax M2.5 (NVIDIA NIM) |
| LLM Fallback | OpenAI — GPT-4.1 |
| LLM Vision | Mistral Large 3 (NVIDIA NIM) |
| STT (voz entrada) | Groq Whisper — `whisper-large-v3-turbo` |
| TTS (voz salida) | Deepgram — `aura-2-gloria-es` |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` (local, CPU) |
| Framework | **Agno** (`agno.models.openai` + `agno.agent`) |
| Memoria | SQLite (historial) + MongoDB Atlas (gym, notas, reminders) |
| Cloud Storage | Supabase Storage (S3 protocol / boto3) |
| Scheduler | croniter + asyncio |
| Dashboard | Next.js + TypeScript |
| Runtime | Python 3.12 / systemd / Ubuntu 24.04 |

## Estructura

```
jada/
├── .agent/                     # Configuración del agente
│   ├── soul.md                 # Personalidad de Jada
│   ├── user.md                 # Info del usuario (Juan)
│   └── heartbeat.md            # Config del heartbeat proactivo
├── agent/
│   ├── agent.py                # Coordinator + ReAct + Tool Group Routing
│   ├── tools_registry.py       # 48+ tools en 12 grupos (Agno Toolkit)
│   ├── embeddings_router.py    # Router semántico (MiniLM multilingual)
│   ├── heartbeat.py            # Voz proactiva (cada 2h, con TTS)
│   ├── scheduler.py            # Cronjobs con croniter
│   └── playbook.py             # ACE-lite: aprendizaje por interacción
├── matrix/
│   └── client.py               # Bot Matrix + audio/imagen/texto/voz + gym room
├── tools/                      # Implementaciones de tools
│   ├── transcribe.py           # Groq Whisper STT + chunking
│   ├── tts.py                  # Deepgram TTS (aura-2-gloria-es)
│   ├── supabase_storage.py     # Cloud storage (S3 protocol / boto3)
│   ├── notes.py                # CRUD notas (MongoDB)
│   ├── email_reader.py         # IMAP Gmail (lectura)
│   ├── email_sender.py         # SMTP Gmail (envío)
│   ├── calendar_api.py         # Google Calendar API (OAuth2)
│   ├── gym_db.py               # MongoDB gym log
│   ├── gym_parser.py           # Parser notación gym (3x10x80)
│   ├── samsung_tv.py           # SmartThings API
│   ├── web_search.py           # DuckDuckGo / Google News RSS
│   ├── weather.py              # Clima: wttr.in → Open-Meteo (fallback)
│   ├── image_gen.py            # Stable Diffusion 3 (NVIDIA NIM)
│   ├── reminders.py            # Recordatorios rápidos
│   ├── deep_think.py           # Modelo de razonamiento profundo
│   ├── shell.py                # Comandos de sistema (whitelist)
│   ├── browser.py              # Navegador headless
│   ├── files.py                # Lectura/escritura de archivos
│   └── summarizer.py           # Extractor de texto de URLs
├── tests/                      # Tests
├── main.py                     # Entrada principal
├── cronjobs.json               # Estado de tareas programadas
└── jada_dashboard/             # Dashboard Next.js
```

## Setup rápido

```bash
# 1. Clonar
git clone https://github.com/judmontoyaso/jada.git
cd jada

# 2. Entorno virtual
python -m venv .venv
source .venv/bin/activate

# 3. Dependencias
pip install -r requirements.txt

# 4. Dependencias del sistema (audio)
sudo apt install ffmpeg -y

# 5. Configurar
cp .env.example .env
# Editar .env con tus credenciales (ver abajo)

# 6. Arrancar
python main.py              # modo silencioso
python main.py --livelogs   # con logs en pantalla
```

## Variables de entorno (.env)

```env
# LLM (OpenAI)
OPENAI_API_KEY=sk-proj-...
OPENAI_FUNCTION_MODEL=gpt-5-mini
OPENAI_FALLBACK_MODEL=gpt-4.1

# LLM (NVIDIA NIM — MiniMax, gratis)
NVIDIA_API_KEY=nvapi-...
NVIDIA_FUNCTION_MODEL=minimaxai/minimax-m2.5
NVIDIA_VISION_MODEL=mistralai/mistral-large-3-675b-instruct-2512

# Groq (Whisper STT)
GROQ_API_KEY=gsk_...
WHISPER_MODEL=whisper-large-v3-turbo

# Deepgram (TTS)
DEEPGRAM_API_KEY=...

# Matrix
MATRIX_HOMESERVER=https://matrix.tu-servidor.me
MATRIX_USER=@jada:matrix.tu-servidor.me
MATRIX_ACCESS_TOKEN=syt_...

# Correo (IMAP)
IMAP_SERVER=imap.gmail.com
IMAP_USER=tu@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx  # App Password

# MongoDB (gym + notas + reminders)
MONGO_URI=mongodb+srv://...

# Supabase Storage (S3 protocol)
SUPABASE_S3_ENDPOINT=https://xxx.storage.supabase.co/storage/v1/s3
SUPABASE_S3_ACCESS_KEY=...
SUPABASE_S3_SECRET_KEY=...
SUPABASE_BUCKET=jada_filestorage

# Timeouts
LLM_TIMEOUT=45              # seg por llamada LLM
JADA_THINK_TIMEOUT=90       # seg máx total para responder
JADA_NUDGE_AFTER=20         # seg antes de avisar que sigue viva
```

## Producción (systemd)

```ini
# /etc/systemd/system/jada.service
[Unit]
Description=Jada AI Agent — Personal AI by 5panes
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
| `guarda una nota: ...` | Guarda en MongoDB |
| `revisa el calendario` | Eventos de hoy |
| `recuérdame X en 30 minutos` | Recordatorio rápido |
| `mis tareas programadas` | Lista cronjobs activos |
| `prende la tele` | SmartThings TV |
| `clima en Medellín` | Pronóstico actual (wttr.in / Open-Meteo) |
| `genera una imagen de...` | Stable Diffusion 3 |
| `sube archivo.pdf a la nube` | → Supabase Storage + URL pública |
| `qué hay en el storage` | Lista archivos en la nube |
| `háblame del clima` | Respuesta por voz (Deepgram TTS) |
| 🎤 *mensaje de voz* | Transcripción + respuesta automática |
| `/clear` | Borra historial del chat |

### Room #gimnasio

| Acción | Resultado |
|--------|-----------|
| `press banca 4x10 80` | 🏋️ Bufereado |
| `curl 3x12 15` | 🏋️ Bufereado |
| `/guardar` | Parsea todo → MongoDB |
| `/resumen` | Muestra buffer actual |
| `/cancelar` | Descarta buffer |

## Dashboard

```bash
cd jada_dashboard
npm install
npm run dev   # http://localhost:3000
```

---

*Construida con amor, cafeína y mucho stack trace. — 5panes*
