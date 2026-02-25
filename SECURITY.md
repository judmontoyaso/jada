# Política de Seguridad - MiniClaw

## 📋 Resumen

MiniClaw es un asistente de IA con acceso a comandos del sistema. Esta documento describe las medidas de seguridad implementadas.

## 🔒 Medidas de Protección

### 1. Ejecución de Comandos

| Medida | Descripción |
|--------|-------------|
| Whitelist de comandos | Solo comandos específicos NO peligrosos |
| Bloqueo por patrones | Detecta `;`, `|`, `$()`, `>` y otros shell metacharacters |
| Límite de entrada | Máx 10,000 caracteres por comando |
| Timeout | 30 segundos máximo por comando |
| Output limitado | 50KB stdout, 5KB stderr |
| Seshell restringida | `/bin/bash` con límites |

**Comandos bloqueados:**
- `rm -rf` (eliminación recursiva)
- `format` (formatear discos)
- `del /f` (forzar delete Windows)
- `shutdown`/`reboot` (apagar sistema)
- `mkfs` (crear filesystem)
- `chmod 777` (permisos inseguros)
- `chown` (cambiar propietario)
- `sudo su` (escalación de privilegios)
- `passwd` (cambiar contraseñas)

### 2. Rate Limiting

- **Por defecto:** 10 mensajes/minuto
- **Burst:** Máximo 3 mensajes seguidos
- Cooldown después de burst excedido

### 3. Variables de Entorno

- **NUNCA** committear `.env` con claves reales
- `.env.example` contiene solo ejemplos
- API keys de producción en variables de entorno del sistema

### 4. Rate Limiting de Rate Limiting

- Timeout de sesión: 1 hora de inactividad
- Longitud máxima de entrada: 10,000 caracteres

### 5. Usuarios Bloqueados

Lista configurable de usuarios que no pueden ejecutar comandos.

## ⚠️ Limitaciones Conocidas

1. **E2EE no funciona en Windows** - Usar rooms sin encriptación
2. **No ejecutar como root** - El bot debería correr como usuario sin privilegios
3. **Validar URLs** - Antes de hacer web scraping, verificar que sea HTTPS

## 🐛 Reportar Vulnerabilidades

Si encuentras una vulnerabilidad de seguridad:
1. **NO** crear issue público
2. Contactar directamente a los maintainers
3. Describir el problema con steps para reproducir

## 📝 Changelog de Seguridad

### v0.4.1 (2026-02-25)
- ✅ Agregado detección de shell metacharacters
- ✅ Limitación de output (50KB stdout, 5KB stderr)
- ✅ Validación de longitud de entrada
- ✅ rate limiting más estricto (10/min, burst 3)
- ✅ Ofuscación de API keys en .env.example
- ✅ Agregado BLOCKED_USERS config
- ✅ SESSION_TIMEOUT configurable
