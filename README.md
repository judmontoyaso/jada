# 🤖 Jada — Personal AI Agent

Un agente de IA personal conectado a **Matrix/Element**, usando modelos de **NVIDIA NIM API** como LLM. Sigue el patrón **ReAct** (Reasoning + Acting) con memoria persistente, herramientas modulares y soporte multi-room.

---

## 🚀 Estado actual

**Versión:** 0.4.0 — Email Send + Summarizer + Dashboard + Identity  
**Última actualización:** 2026-02-24  
**Modelo:** `minimaxai/minimax-m2.1` (con failover a `nvidia/llama-3.3-nemotron-super-49b-v1`)

El bot está **operativo** y conectado a Matrix. Puede recibir mensajes en rooms sin encriptación, procesarlos vía NVIDIA NIM, ejecutar herramientas y responder.

### ✅ Lo que funciona
- Conexión a Matrix (matrix-nio), auto-aceptar invitaciones
- Loop ReAct con function calling (hasta 10 iteraciones)
- Memoria persistente por room/usuario (SQLite)
- Selección inteligente de tools por categoría (reduce payload al LLM)
- **31 herramientas**: shell, archivos, browser, web search, gym (MongoDB), notas, memoria, email (leer + enviar), calendario, summarizer
- **Archivos de identidad** (`.agent/soul.md`, `.agent/user.md`) — personalidad y perfil del usuario
- Lectura de correo electrónico vía IMAP (Gmail con App Password)
- **Envío de correo** vía SMTP (Gmail)
- **Resumen de páginas web** (URL summarizer)
- **Dashboard web** en http://localhost:8080 (stats, memoria, actividad)
- Lectura de Google Calendar vía URL ICS privada
- Reacciones emoji (⏳ procesando → ✅ listo / ❌ error)
- Reintentos automáticos con backoff exponencial
- Gym tracker conectado a MongoDB Atlas con parser determinístico
- Rate limiting por usuario
- Message chunking para respuestas largas
- Aviso claro cuando se recibe un mensaje encriptado (E2EE no soportado en Windows)

### ⚠️ Limitaciones conocidas
- **E2EE no funciona en Windows** — `libolm` no compila. Usar rooms sin encriptación o correr en Docker/Linux
- **NVIDIA NIM requiere `type` en todos los campos** de tool schemas (usa Outlines para constrained generation)
- **NVIDIA NIM rechaza `content: ""`** en mensajes — se debe enviar `null` en lugar de string vacío
- **Latencia del LLM** — las respuestas pueden tardar 2-5 segundos

---

## ✅ Checklist de desarrollo

### 🏗️ Núcleo del agente
- [x] Cliente LLM con failover automático entre modelos (`agent/core.py`)
- [x] Loop ReAct principal con function calling (`agent/agent.py`)
- [x] Memoria persistente por room/usuario en SQLite (`agent/memory.py`)
- [x] Registry y dispatcher de herramientas (`agent/tools.py`)
- [x] Selección inteligente de tools por categoría (reduce payload)
- [x] Límite de tokens configurable en historial
- [x] Fix: `content: null` cuando LLM hace tool calls (NIM rechaza strings vacíos)
- [x] Sanitización de historial (eliminar msgs user consecutivos sin respuesta)
- [ ] Streaming de respuestas largas (chunked messages desde el LLM)
- [ ] Tests unitarios del agente

### 🔌 Integración Matrix
- [x] Bot Matrix con `matrix-nio` (`matrix/client.py`)
- [x] Respuesta en rooms autorizados (o todos si `MATRIX_ROOM_IDS` vacío)
- [x] Auto-aceptar invitaciones a rooms
- [x] Comando `/clear` / `!clear` para limpiar historial
- [x] Reacciones con emoji al procesar (⏳ → ✅ / ❌)
- [x] Handler de `MegolmEvent` con aviso al usuario
- [x] Reintentos automáticos en desconexión (backoff exponencial)
- [x] Rate limiting por usuario configurable
- [x] Message chunking para respuestas >2000 chars
- [ ] Soporte E2EE encryption (requiere `libolm` — solo funciona en Linux/Docker)
- [ ] Soporte multi-usuario por room (historial compartido vs individual)

### 🛠️ Herramientas (tools/)
- [x] **Shell** — ejecución de comandos con blocklist (`tools/shell.py`)
- [x] **Archivos** — leer, escribir, listar (`tools/files.py`)
- [x] **Browser** — Playwright headless: navegar, scraping, click, formularios (`tools/browser.py`)
- [x] **Web Search** — DuckDuckGo sin API key (`tools/web_search.py`)
- [x] **Gym DB** — MongoDB Atlas: guardar workouts, historial, rutinas, stats (`tools/gym_db.py`)
- [x] **Gym Parser** — Parser determinístico de notación de gym (`tools/gym_parser.py`)
- [x] **Notas** — CRUD markdown con tags en SQLite (`tools/notes.py`)
- [x] **Memoria** — `remember_fact` para datos del usuario
- [x] **Email** — Lectura vía IMAP: listar, leer, buscar correos (`tools/email_reader.py`)
- [x] **Calendario** — Google Calendar vía ICS: hoy, próximos, buscar (`tools/calendar_reader.py`)
- [ ] Calendario / recordatorios con notificaciones push
- [ ] Envío de emails (SMTP)
- [ ] Control de reproductores de música (Spotify API)
- [ ] Tool de resumen de documentos (PDF/TXT)
- [ ] Screenshot del browser (enviar imagen al room)

### 🧠 Memoria
- [x] Historial de conversación por room + usuario (SQLite)
- [x] Hechos del usuario (`remember_fact`) — persistentes por user_id
- [ ] Búsqueda semántica en memoria (embeddings)
- [ ] Expiración configurable del historial
- [ ] Exportar/importar memoria

### 🔒 Seguridad
- [x] Blocklist de comandos peligrosos (configurable)
- [x] Restricción de rooms autorizados
- [x] Logs de auditoría de tool calls (nombre, args, resultado, tiempo)
- [x] Rate limiting por usuario
- [x] Email y Calendar solo lectura (sin operaciones de escritura)
- [ ] Modo de solo lectura (read-only mode)
- [ ] Sanitización de output para prevenir injection

### ⚙️ DevOps
- [x] Variables de entorno vía `.env`
- [x] `requirements.txt` con todas las dependencias
- [x] `.gitignore` completo
- [x] Tests de seguridad (`tests/test_security.py`)
- [ ] Dockerizar el proyecto (Dockerfile + docker-compose)
- [ ] Script de instalación automática
- [ ] CI básico (lint + tests en push)
- [ ] Monitoreo de salud (health check endpoint)

### 🐞 Tareas pendientes (TODO)
- [ ] **Verificar email con nuevo App Password** — se regeneró la contraseña, confirmar que funciona
- [ ] **Probar modelo MiniMax M2.1** — verificar compatibilidad completa con function calling
- [x] **Fix email:** El LLM decía "no tengo acceso a tu correo" — corregido con system prompt reforzado y keywords mejorados
- [x] **Fix login Matrix:** Ahora usa access token directamente, fallback a password
- [x] **Limpieza de proyecto** — Eliminados: crypto_store/, venv/, tests/results.txt, gym.db, memory.db, Dockerfile, docker-compose.yml

---

## 📁 Estructura del proyecto

```
mini_claw/
├── main.py              # Punto de entrada (asyncio + dashboard)
├── .env                 # Tu configuración (NO subir a git)
├── .env.example         # Plantilla de configuración
├── .gitignore
├── requirements.txt
│
├── .agent/
│   ├── soul.md          # 🧠 Personalidad y principios del bot
│   └── user.md          # 👤 Perfil del usuario (identidad)
│
├── agent/
│   ├── core.py          # Cliente LLM (OpenAI-compatible, con failover)
│   ├── agent.py         # Loop ReAct + selección inteligente de tools + identidad
│   ├── memory.py        # Memoria persistente (SQLite)
│   └── tools.py         # Registry de schemas + dispatcher (31 tools)
│
├── tools/
│   ├── shell.py         # Ejecución de comandos del sistema
│   ├── files.py         # Leer, escribir, listar archivos
│   ├── browser.py       # Playwright: navegar, scraping, clicks
│   ├── web_search.py    # DuckDuckGo search
│   ├── gym_db.py        # 🏋️ Gym tracker (MongoDB Atlas)
│   ├── gym_parser.py    # Parser determinístico de notación de gym
│   ├── notes.py         # 📝 Notas personales (SQLite)
│   ├── email_reader.py  # 📧 Lectura de correo (IMAP/Gmail)
│   ├── email_sender.py  # 📩 Envío de correo (SMTP/Gmail)
│   ├── calendar_reader.py # 📅 Google Calendar (ICS)
│   ├── summarizer.py    # 📊 Resumen de páginas web
│   └── dashboard.py     # 📊 Dashboard web (HTTP server)
│
├── matrix/
│   └── client.py        # Bot Matrix (matrix-nio async)
│
└── tests/
    └── test_security.py # Tests de seguridad
```

---

## ⚙️ Instalación

### 1. Requisitos previos
- Python 3.10+
- Servidor Matrix/Element con una cuenta para el bot
- API Key de [NVIDIA NIM](https://build.nvidia.com/)
- MongoDB Atlas (para gym tracker) — o cualquier instancia MongoDB
- Gmail App Password (para lectura de correo) — [Crear aquí](https://myaccount.google.com/apppasswords)
- Google Calendar ICS URL privada (para calendario)

### 2. Instalar dependencias

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
playwright install chromium
```

### 3. Configurar el entorno

```bash
copy .env.example .env
```

Edita `.env` con tus datos:

```env
# LLM
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxx
NVIDIA_MODEL=minimaxai/minimax-m2.1

# Matrix
MATRIX_HOMESERVER=https://tu-servidor.com
MATRIX_USER=@miniclaw:tu-servidor.com
MATRIX_PASSWORD=tu-password
MATRIX_ROOM_IDS=              # vacío = escuchar en todos los rooms

# MongoDB (gym tracker)
MONGO_URI=mongodb://[tu-uri-de-conexion-aqui]
MONGO_DB=n8n_memoria
MONGO_GYM_COLLECTION=gimnasio

# Gmail (IMAP, solo lectura)
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
IMAP_USER=tu-email@gmail.com
IMAP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Google Calendar
GOOGLE_CALENDAR_ICS_URL=https://calendar.google.com/calendar/ical/...
```

### 4. Ejecutar

```bash
python main.py
```

---

## 💬 Uso desde Element/Matrix

### Comandos especiales
| Comando | Acción |
|---|---|
| Mensaje normal | El agente procesa, usa tools si necesita, y responde |
| `/clear` o `!clear` | Borra el historial de la conversación |

### ⚠️ Rooms encriptados
El bot **no puede leer mensajes encriptados** (E2EE) en Windows. Crea rooms **sin encriptación** para interactuar con el bot.

---

## 🏋️ Gym Tracker (MongoDB)

Conectado a **MongoDB Atlas** — colección `gimnasio`. Parser determinístico para notación de gym.

### Ejemplos
```
"Hoy hice push: press banca 4x10 a 40kg, press inclinado 4x10 a 20kg"
"¿Cuántos entrenamientos tengo registrados?"
"Muéstrame mis últimos 5 entrenamientos"
"¿Cómo va mi progresión en sentadilla?"
"Genera una rutina de pecho y tríceps"
"Dame mis estadísticas de gym"
```

### Schema de documento MongoDB
```json
{
  "id": "2026-01-15-push",
  "nombre": "Push - Pecho, Hombro y Tríceps",
  "tipo": "push",
  "fecha": "2026-01-15",
  "grupos_musculares": ["pecho", "hombros", "triceps"],
  "ejercicios": [
    {
      "nombre": "Press de pecho en máquina",
      "series": 4,
      "repeticiones": 10,
      "peso_kg": [20, 40]
    }
  ]
}
```

---

## 📧 Email (solo lectura)

```
"Revisa mis correos"
"¿Tengo correos nuevos?"
"Busca correos de Google"
"Lee el correo #5"
```

Conectado vía **IMAP** (Gmail con App Password). Solo lectura — no puede enviar, borrar ni modificar correos.

---

## 📅 Calendario

```
"¿Qué tengo hoy en el calendario?"
"¿Cuáles son mis próximos eventos?"
"Busca eventos sobre reunión"
```

Conectado vía **Google Calendar ICS URL** privada. Solo lectura.

---

## 📝 Notas personales

```
"Guarda una nota: Ideas proyecto — usar websockets para real-time"
"Lista mis notas"
"Busca notas sobre proyecto"
"Borra la nota #3"
```

---

## 🧠 Memoria

```
"Recuerda que mi nombre es Juan y entreno en el gimnasio Smart Fit"
"¿Qué sabes sobre mí?"
```

El bot guarda hechos con `remember_fact` y los incluye automáticamente en cada conversación.

---

## 🌐 Web y Sistema

```
"Busca en la web el clima de hoy en Medellín"
"Abre https://ejemplo.com y dime qué dice"
"Ejecuta 'dir' en esta carpeta"
"Lee el archivo config.json"
```

---

## 🛡️ Seguridad

- Los comandos peligrosos se bloquean vía `BLOCKED_COMMANDS` en `.env`
- El bot solo responde en los rooms definidos en `MATRIX_ROOM_IDS` (vacío = todos)
- Tu API key nunca sale del servidor (todo corre local)
- Cada tool call se registra en logs de auditoría con nombre, args, resultado y tiempo de ejecución
- Rate limiting configurable por usuario
- Email y Calendario son estrictamente solo lectura

---

## 🐛 Bugs conocidos y resueltos

| Bug | Estado | Solución |
|---|---|---|
| NVIDIA NIM rechaza `content: ""` | ✅ Resuelto | Enviar `null` en lugar de string vacío |
| Tool schema sin `type` causa 500 | ✅ Resuelto | Todos los campos ahora tienen `type` |
| E2EE no funciona en Windows | ⚡ Workaround | Usar rooms sin encriptación |
| `Unclosed client session` al cerrar | ⚡ Cosmético | No afecta funcionalidad |
| LLM dice "no tengo acceso al correo" | 🔧 En progreso | System prompt reforzado + keywords mejorados |
| `.env` corrupto con datos de gym | ✅ Resuelto | Datos de entrenamiento eliminados del archivo |
