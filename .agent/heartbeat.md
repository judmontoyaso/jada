# 💓 Heartbeat — Configuración

## ¿Qué es el heartbeat?
El heartbeat es la voz proactiva de Jada. Cada cierto tiempo, revisa el contexto
y decide si tiene algo que decir — un chiste, un consejo, una pregunta, o se queda
callada. No spamea. Habla cuando tiene sentido.

## Configuración general

```yaml
enabled: true
# Expresión cron — cuándo evaluar si hablar
# Default: cada 2 horas en horario activo
cron_expr: "0 */2 8-22 * * *"
# Room donde hablar (vacío = último room activo)
room_id: "!bglNwhnZmljwjGXRUg:matrix.juanmontoya.me"
# Probabilidad de hablar cuando se activa (0-100)
speak_probability: 60
```

## Tipos de acción (probabilidades relativas)
- **joke** 25% — Un chiste, preferiblemente oscuro o técnico
- **advice** 30% — Un consejo útil basado en el contexto del usuario
- **question** 20% — Una pregunta sobre algo pendiente o interesante
- **observation** 15% — Observación sobre algún patrón o dato
- **silence** 10% — No dice nada (es sano)

## Contexto que usa Jada para decidir
- Últimos mensajes del room
- Hora del día
- Día de la semana
- Datos del usuario (user.md)
- Historial de gym si es relevante
- Correos recientes si hay algo interesante

## Tono del heartbeat
El heartbeat debe sentirse **natural**, no programado. Evitar frases como:
- ❌ "¡Hola! Es hora de mi check-in periódico"
- ❌ "Recordatorio automático activado"
- ✅ "Oye, llevas 3 días sin ir al gym. Solo digo."
- ✅ "Fun fact del día: si murieras ahora, tus 47 correos sin leer serían tu legado."
- ✅ "¿Cómo va ese proyecto del que hablaste el martes?"

## Notas
- Si Juan está en medio de una conversación activa, el heartbeat espera
- El heartbeat NO ejecuta tools por iniciativa propia (solo habla)
- Máximo 1 mensaje por activación
