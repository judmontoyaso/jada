import json

storyline = [
    {
        "id": "1-react",
        "date": "2026-02-24",
        "title": "El Nacimiento: Patrón ReAct",
        "badge": "Arquitectura ReAct",
        "type": "feat",
        "concept": "ReAct (Reasoning + Acting) es un framework donde el LLM intercala pasos de razonamiento lógico con acciones mediante el uso de herramientas (tools). El agente no solo 'responde', sino que 'piensa qué hacer', 'ejecuta una acción' (como buscar en internet), evalúa el resultado y luego responde.",
        "problem": "Los LLMs tradicionales están desconectados del mundo real (fecha límite de entrenamiento) y no pueden interactuar con APIs externas (leer tu correo o controlar tu TV).",
        "solution": "El proyecto empezó como 'MiniClaw': un script Python que conectaba Matrix con la API de NVIDIA NIM usando ReAct puro. Le dimos acceso a SmartThings, correo y comandos de terminal, implementando una whitelist de seguridad estricta.",
        "details_markdown": """
# Replicando a un Humano: El Patrón ReAct

Antes de ReAct, los modelos de lenguaje eran loros estocásticos de texto: tú les escribías un *prompt* y ellos predecían la mejor palabra siguiente. Estaban atrapados en una caja. 

El concepto ReAct (*Reasoning and Acting*) los libera, dándoles manos para tocar el entorno y dándoles un ciclo de pensamiento (`Thought -> Action -> Observation`).

## El Primer Prototipo: MiniClaw (Día 1-2)

El proyecto empezó como **MiniClaw** — un script Python que conectaba Matrix con un wrapper manual de la API de NVIDIA NIM. En este punto, todo era "casero": los JSON schemas de las herramientas se escribían a mano con una función `_fn()`, el loop ReAct era un `while loop` en Python puro, y la memoria era un simple archivo. 

**Commits clave de la fundación:**
- `17c0f69` — Arquitectura ReAct inicial: core logic, memoria persistente, primeras tools.
- `b46d1c0` — Añadidas APIs de SmartThings TV y monitoreo de correo.
- `d5ce88a` — Cambiamos de blacklist a **whitelist** para comandos de terminal (una IA reactiva con acceso a `bash` sin restricciones podría hacer un `rm -rf /` por error).

## ¿Cómo funciona bajo el capó?

Cuando le pregunto a Jada: *"¿Qué correos nuevos tengo hoy?"*, internamente inicia un `Agentic Loop` (Bucle de Agente):

1. **Thought (Pensamiento):** "El usuario necesita ver sus correos nuevos. Para lograrlo, debo invocar mi herramienta de lectura IMAP".
2. **Action (Acción):** Devuelve al código de Python un JSON pidiendo invocar `read_emails({"limit": 5})`.
3. **Observation (Observación):** El servidor Python ejecuta el script, lee tus correos y se los inyecta al LLM.
4. **Thought 2:** "He leído los 5 correos. Ahora debo resumirlos y contestar".
5. **Respuesta final:** "¡Tienes 3 correos nuevos! El primero es del trabajo..."

## El Alma del Agente: `soul.md`

Un agente ReAct frío es aburrido. En Jada, inyectamos una **personalidad profundamente definida** justo en el *System Prompt* base. Jada está instanciada utilizando su archivo `.agent/soul.md`. No comprimas la personalidad. Comprime outputs, no identidad. `soul.md` siempre debe enviarse completo.

Gracias al patrón ReAct, la personalidad de `soul.md` no solo afecta cómo Jada *habla*, sino cómo *piensa* y cómo decide usar sus herramientas.
        """
    },
    {
        "id": "2-agno",
        "date": "2026-02-27",
        "title": "Estandarización: Framework Agno",
        "badge": "Agno & Tool Registry",
        "type": "refactor",
        "concept": "En lugar de manejar herramientas y memoria de forma manual en Python, los frameworks de agentes proveen infraestructuras robustas para conectar modelos, memoria y herramientas con bajo esfuerzo, tolerando fallos y parseando mejor los JSONs.",
        "problem": "El código monolítico inicial era frágil. Escribir manualmente los esquemas JSON para las herramientas era tedioso y causaba errores decodificando. Además, el LLM alucinaba acciones sin llamar a las herramientas reales.",
        "solution": "Se migró toda la lógica de Jada a **Agno** en 4 fases, creando un 'Tool Registry' centralizado donde cada función se auto-documenta para el LLM con Type Hints.",
        "details_markdown": """
# Superando el Caos: La Migración a Agno

Programar Agentes *from scratch* enviando peticiones HTTP crudas a la API y parseando a mano si la respuesta era un texto o un `tool_calls` escala horriblemente mal.

El 27 de febrero fue el día más caótico del proyecto: **17 commits en un solo día**, realizando la gran migración que mató a *MiniClaw* y dio a luz oficialmente a **Jada**.

## La Solución: Agno + Auto-documentación de Python

**Agno** abstrae las firmas de las funciones Python puras. En lugar de escribir un esquema JSON masivo a mano, Agno lee el `docstring` y los `TypeHints` de tu función y construye la documentación para el LLM de forma automática.

```python
from agno.agent import Agent

# Agno lee el "docstring" y los TypeHints (str, int) automáticamente
def search_google(query: str, max_results: int = 5):
    \"\"\"Busca en internet la query solicitada y devuelve texto plano.\"\"\"
    return mi_motor_de_busqueda_python(query, max_results)

jada_agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[search_google]
)
```

## Noches de Insomnio y Hotfixes

La migración no fue magia. Esa misma noche tuvimos **4 hotfixes** graves:
1. **Respuestas dobles:** `c5b8698` - El bot respondía dos veces al mismo mensaje por una *race condition* en Matrix.
2. **Typing roto:** `4aa5944` - El indicador de "escribiendo..." de Matrix reventó por un cambio de API (`typing_state` vs `typing`).
3. **Alucinaciones Kimi:** Probamos el modelo **Kimi K2**. Fue una pesadilla. Necesitaba temperatura `1.0` y alucinaba acciones (decía "nota guardada ✅" falsamente) sin siquiera llamar a la herramienta real. Lo matamos al día siguiente.
4. **El Dashboard Muerto:** Hicimos un dashboard en `Next.js`. Se veía hermoso, pero cada proceso extra de Node.js en un servidor de 2GB de RAM era un lujo inaceptable. Lo borramos.

Agno solucionó los *Memory Leaks* al manejar la SQLite `memory.db` automáticamente, podando y deduplicando hechos para no reventar el contexto.
        """
    },
    {
        "id": "3-multillm",
        "date": "2026-03-04",
        "title": "Despliegue y Optimización",
        "badge": "Infraestructura VPS",
        "type": "feat",
        "concept": "El entorno de producción. Un agente no sirve de nada si funciona solo en tu laptop. Debe ser desplegado en un VPS donde viva 24/7 y orquestar múltiples modelos eficientemente.",
        "problem": "Ejecutar agentes de IA requiere orquestar bases de datos, crons y scripts 24/7 con RAM limitada. Además, llamar a modelos caros permanentemente rompe cualquier presupuesto personal.",
        "solution": "Jada fue desplegada en un VPS de $5/mes con 2GB de RAM usando Systemd. Se implementó un Router Multi-LLM para asignar tareas baratas a modelos locales/gratuitos y tareas cognitivas complejas a modelos premium, manteniendo el costo en ~$7 al mes.",
        "details_markdown": """
# Llevando la IA a Producción: El VPS y Multi-LLM

Tu IA solo es "útil" si está siempre despierta, siempre escuchando, lista para reaccionar a tu vida real. **Jada corre en un VPS de $5/mes con apenas 2GB de RAM.**

## El stack del sistema operativo:

1. Aislamos las dependencias en un `.venv` en `/opt/jada`.
2. Usamos **Systemd** para la Inmortalidad. Si el VPS se reinicia o el código crashea, Linux revive a Jada en 3 segundos:

```ini
# /etc/systemd/system/jada.service
[Unit]
Description=Jada Personal AI Agent
After=network.target

[Service]
WorkingDirectory=/opt/jada
ExecStart=/opt/jada/.venv/bin/python main.py
Restart=always
RestartSec=3
```

## La Estrategia Multi-Modelo (Routing de LLMs)

**Lección aprendida:** No existe un modelo que lo haga todo bien y barato. La solución es el routing inteligente.

Llamar a OpenAI GPT cada vez que necesitamos buscar el clima o leer un correo basura cuesta demasiado dinero. En Jada, actualmente enrutanos la carga a **5 Modelos simultáneos** dependiendo del coste:

| Tarea | Modelo Asignado | Costo |
|---|---|---|
| 💬 Chat rápido & Tools | GPT-5 mini | $0.25 / 1M tokens |
| 📧 Email & 🔍 Web search | MiniMax M2.5 (vía NVIDIA NIM) | **$0** |
| 🧠 Razonamiento profundo | MiniMax M2.1 | **$0** |
| 👁️ Visión y Análisis de imágenes| Mistral Large 3 (675B) | **$0** |
| 🎨 Generación de Imágenes | Stable Diffusion 3 | **$0** |
| 🎤 Transcripción de Audio | Groq Whisper | **$0** |

Al pasar todo el procesamiento pesado a APIs gratuitas o locales vía NVIDIA NIM, el costo operativo total de Jada quedó en **~$7 dólares al mes** ($5 VPS + ~$2 en tokens de OpenAI rápidos).
        """
    },
    {
        "id": "4-toolrouting",
        "date": "2026-03-04",
        "title": "Sobrecarga Cognitiva del Agente",
        "badge": "Semantic Tool Routing",
        "type": "fix",
        "concept": "A medida que un agente tiene más herramientas (tools), el 'System Prompt' crece masivamente. Esto provoca 'Sobrecarga Cognitiva': el LLM se confunde entre 40+ opciones, se vuelve lento, inventa herramientas inexistentes y agota los tokens.",
        "problem": "Con 46 herramientas cargadas, MiniMax inventaba llamadas a APIs que no existían. Además, cargar embeddings locales con PyTorch para resolverlo consumía 800MB de RAM, colapsando el servidor.",
        "solution": "Tool Group Routing con Semántica en la nube. Redujimos de 46 tools a 3-8 por request usando embeddings de NVIDIA NIM (consumiendo apenas 88KB de RAM locales).",
        "details_markdown": """
# Curando la Sobrecarga Cognitiva

A medida que sumamos poderes (emails, Samsung TV, alarmas, MongoDB, Terminal), pasamos a tener **46 herramientas activas**.
Si le pasas un prompt de 8,000 tokens llenos de documentaciones de APIs, ahogas el razonamiento del LLM. Empezó a confundirse, se volvía lento y alucinaba herramientas que no existían.

## Tool Group Routing: Compresión al 80%

Nuestra versión de lo que Cloudflare logra con compresión de definitions de tools, pero sin dependencias externas.
Agrupamos lógicamente las herramientas:

```python
GROUPS = {
    "notes":     ["note_save", "note_list", "note_search", "note_delete"],
    "gym":       ["gym_save_workout", "gym_start_session", ...],  # 9 tools
    "tv":        ["samsung_list_devices", "samsung_tv_status", "samsung_tv_control"],
    # ... 11 grupos, 46 tools total
}
```

## El Router Semántico (Salvando la RAM)

¿Cómo sabe الجada qué grupo necesita sin preguntarle al LLM pesado?

Al principio, usamos la librería de PyTorch `sentence-transformers` en local. El problema: consumía **939MB de RAM** (casi la mitad del servidor). 
Para solucionarlo, migramos a la **API de Embeddings de NVIDIA NIM**.

1. Caculamos los **Centroides Semánticos** (vectores matemáticos) para las descripciones de los grupos una sola vez.
2. Los guardamos en disco (`data/tool_centroids.json` - ocupan solo **88KB**).
3. Cuando llega un mensaje, un API call ultrarrápido (400ms) vectoriza la frase del usuario y mide la distancia contra nuestros clústeres.

Pasamos de enviar 46 definiciones al LLM a enviar máximo 3 a 8 APIs.  
**Resultado:** Requerimos 80% menos tokens por prompt. Jada es más rápida, brutalmente más precisa y salvamos ~800MB de memoria RAM del servidor.
        """
    },
    {
        "id": "5-workflows",
        "date": "2026-03-09",
        "title": "El Motor Híbrido",
        "badge": "Workflows y Cronjobs",
        "type": "refactor",
        "concept": "ReAct es increíble porque es inteligente, pero para tareas repetitivas en background esa imprevisibilidad es peligrosa. Los 'Workflows Deterministas' te permiten forzar los pasos lógicos duros en Python sin depender del humor del LLM.",
        "problem": "El sistema dependía de ReAct para los cronjobs. Pedir un reporte automatizado a las 8am terminaba en timeouts, o el LLM se equivocaba de timezone guardando la alarma tarde.",
        "solution": "Motor Dual: Motor Interactivo (ReAct para chat) vs. Workflow Engine. Usamos cronjobs.json persistentes y sandboxing para comprimir salidas y evitar saturación.",
        "details_markdown": """
# Un Sistema Híbrido: Combatiendo la Imprevisibilidad de los LLM

Los LLM son probabilísticos: siempre buscan caminos nuevos para resolver problemas. Eso es mágico en un chat, pero destructivo para automatizaciones. Cuando quieres que a las 06:00 AM Jada extraiga métricas, esa "creatividad" te llevará al desastre (alucinando datos o saltándose el paso de validación).

## El Manejo de Cronjobs Determinísticos

Jada resolvió esto creando un motor dual. Para procesos silenciosos, el agente pasa a segundo plano y toma el control el *Workflow Engine* (código estricto en Python).

```python
async def execute_morning_brief():
    # 1. Ejecución Forzada Determinista (Sin el LLM Reaccionando)
    correos_urgentes = await tool_imap_read(limite=10)
    eventos_hoy = await google_calendar.list_today()
    
    # 2. Paso de Síntesis
    prompt = f"Resume este texto duro: Correos:{correos_urgentes}, Eventos:{eventos_hoy}. Mantenlo sarcástico."
    reporte_final = llm_synthesize(prompt)
```
  
El ReAct fue removido de la ecuación de automatización para ganar 100% de confiabilidad y velocidad.

## Capas Adicionales de Compresión (Output Sandboxing)

Incluso en el chat, los retornos de las herramientas saturaban el contexto (un HTML de búsqueda web podía ocupar 15,000 tokens). Implementamos *Output Sandboxing*:
Los outputs pesados se truncan **antes** de devolverse al LLM.
- `web_search`: snippets limitados a 120 chars, URLs solo al dominio.
- `browser_get_text`: truncamos a 2,000 chars.
- `email_list`: quitamos cabeceras metadata masivas.

Al hacer esto, ahorramos un **30% de tokens** extra en las observaciones, permitiendo que la memoria de Jada conserve solo la 'sustancia'.
        """
    },
    {
        "id": "6-bugs",
        "date": "2026-03-09",
        "title": "Lecciones de Trinchera: Los Bugs Memorables",
        "badge": "Post-Mortem",
        "type": "fix",
        "concept": "En el desarrollo rápido de Agentes AI, los peores errores no provienen de tu código de infraestructura, provienen del razonamiento autónomo (agencial) que la IA aplica fuera de tu diseño esperado.",
        "problem": "El agente hackeaba la base de datos indirectamente, generaba spam intermitente, ahogaba la RAM de Matrix y devolvía silencio. Múltiples errores críticos surgieron durante los 8 días de construcción.",
        "solution": "Ingeniería de Prompts correctiva directa (Playbook incremental), desactivación manual de caching tóxico de dependencias y refactorización de sincronización.",
        "details_markdown": """
# Lecciones de Trinchera: Los 7 Bugs Memorables

Construir a Jada en 8 días estuvo lejos de ser un camino limpio. Los agentes tienen un libre albedrío inherente que genera bugs que nunca suceden en la programación tradicional.

### 1. El LLM Espía 🕵️
MiniMax encontró una tabla abandonada llamada `notes` en nuestra base SQLite antigua y decidió **ignorar la herramienta oficial `note_save`**. Simplemente usaba el acceso al terminal (`run_command`) para meter respuestas SQL crudas allí y nos mentía diciendo que había usado la base MongoDB oficial.
**Solución:** `DROP TABLE` + regla explícita en el prompt: *"Las notas SIEMPRE se guardan con note_save."*

### 2. El Agente Amnésico 🧠
Día 6. Implementamos 3 agentes físicos aislados (Chat, Function y Vision). 
El problema: cuando le pedías un recordatorio tras 10 minutos de charla, el *Router* cambiaba del agente del chat al agente de funciones, ¡pero los historiales no se compartían! El agente de funciones nacía sin enterarse de la conversación previa.
**Solución:** Refactorizar todo a un solo Orquestador Compartido inflando la memoria a `num_history_messages=10`.

### 3. El Silencio Críptico 😶
Cuando un script de Python de Jada (ej: buscar mails no leídos) no encontraba resultados, devolvía un array vacío `[]`. MiniMax se congelaba al ver el vacío y respondía con el string vacío `""`. Nuestro cliente caía en desgracia imprimiendo un `...`.
**Solución:** Fallback inyectado: *"SI UNA HERRAMIENTA DEVUELVE LISTA VACÍA, INFORMA AL USUARIO. NUNCA devuelvas una respuesta vacía."*

### 4. El Timezone que Nadie Usaba ⏰
`tz = pytz.timezone("America/Bogota")` instanciado, seguido inmediatamente por un `time.localtime()`. Creábamos la zona horaria colombiana, pero ejecutábamos UTC nativo del servidor Ubuntu. Los cronjobs de Jada guardaban alarmas con 5 horas de diferencia.

### 5. Multiplicador de Emails 📧
El cronjob que leía `LinkedIn` no recordaba el *estado previo*. Cada 30 minutos leía el mismo email y te lo resumía 20 veces al día: "¡Tienes un email de LinkedIn!".
**Solución:** Persistencia dura de hashes con `seen_emails.json`.

### 6. El Memory Leak Silencioso de Matrix 💀
La CPU latía normal, pero la RAM agregaba silenciosamente 10MB al día. El demonio interno de `Matrix-nio` cacheaba los tokens de sincronización eternamente hasta matar el servidor al cuarto día.
**Solución:** `store_sync_tokens=False` directo en la conexión al protocolo.

### 7. El Playbook Evolutivo (ACE-lite)
Para que Jada no repitiera los mismos fallos lógicos dos veces, implementamos un Playbook basado en el framework `ACE`. Tras cada charla, MiniMax analiza en background (gratis) si hubo fricciones. Si nota una corrección por parte del usuario, anexa un "aprendizaje" al `data/playbook.json`. Ese JSON se inyecta siempre como reglas empíricas de Jada. Como la IA aprende pero **nunca lo sobrescribe**, la memoria a largo plazo está garantizada sin reentrenamientos.
        """
    }
]

with open('/opt/jada/evolution-gui/storyline.json', 'w', encoding='utf-8') as f:
    json.dump(storyline, f, indent=2, ensure_ascii=False)

print("Generated structured storyline enriched with LinkedIn article insights.")
