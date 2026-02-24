# Plan de Implementación — Sprint 2

## Tareas

### 1. 📧 Email Reader (IMAP, solo lectura)
- **Archivo:** `tools/email_reader.py`
- **Dependencia:** `aioimaplib` (async IMAP)
- **Tools:**
  - `email_list` — listar últimos N correos (remitente, asunto, fecha)
  - `email_read` — leer contenido de un correo por ID
  - `email_search` — buscar correos por asunto/remitente/fecha
- **Config .env:** `IMAP_SERVER`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_PORT`

### 2. 📅 Calendar Reader (CalDAV/ICS, solo lectura)
- **Archivo:** `tools/calendar_reader.py`
- **Dependencia:** `caldav`, `icalendar`
- **Tools:**
  - `calendar_today` — eventos de hoy
  - `calendar_upcoming` — próximos N eventos
  - `calendar_search` — buscar eventos por texto
- **Config .env:** `CALDAV_URL`, `CALDAV_USER`, `CALDAV_PASSWORD`

### 3. 📤 Streaming de respuestas largas
- **Archivo:** `matrix/client.py` → `_send()`
- Dividir mensajes > 2000 chars en chunks
- Enviar cada chunk como mensaje separado con delay

### 4. 🔧 Fix unclosed client session
- **Archivo:** `matrix/client.py`
- Agregar `await self.client.close()` en cleanup

### 5. 🛡️ Rate limiting por usuario
- **Archivo:** `matrix/client.py`
- Máximo N mensajes por minuto por usuario
- Config: `RATE_LIMIT_PER_MINUTE` en .env

### 6. 🧪 Tests de seguridad
- **Archivo:** `tests/test_security.py`
- Test: shell blocklist funciona
- Test: rate limiting rechaza exceso
- Test: tool schemas válidos
- Test: archivos fuera del directorio bloqueados
- Test: injection en comandos shell
- Test: email/calendar solo lectura (no write/delete)

## Orden de ejecución
1. Email Reader
2. Calendar Reader  
3. Streaming
4. Fix session + Rate limiting
5. Security tests
6. Actualizar tools.py, .env.example, README
