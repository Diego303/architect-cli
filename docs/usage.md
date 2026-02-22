# Formas de uso — architect CLI

Guía práctica de uso real: desde el caso más simple hasta configuraciones avanzadas para CI/CD, múltiples proyectos y equipos. Incluye todos los flags, combinaciones de logging y patrones de automatización.

---

## Índice

1. [Instalación y setup inicial](#1-instalación-y-setup-inicial)
2. [Uso básico sin configuración](#2-uso-básico-sin-configuración)
3. [Selección de agente (-a)](#3-selección-de-agente--a)
4. [Modos de confirmación (--mode)](#4-modos-de-confirmación---mode)
5. [Flags de output: --json, --quiet, --dry-run](#5-flags-de-output---json---quiet---dry-run)
6. [Flags de logging: -v, --log-level, --log-file](#6-flags-de-logging--v---log-level---log-file)
7. [Uso sin logs (silencioso)](#7-uso-sin-logs-silencioso)
8. [Flags de LLM: --model, --api-base, --api-key, --timeout](#8-flags-de-llm---model---api-base---api-key---timeout)
9. [Archivos de configuración](#9-archivos-de-configuración)
10. [Configuraciones por entorno](#10-configuraciones-por-entorno)
11. [MCP: herramientas remotas](#11-mcp-herramientas-remotas)
12. [Herramientas de edición incremental (F9)](#12-herramientas-de-edición-incremental-f9)
13. [Indexer y herramientas de búsqueda (F10)](#13-indexer-y-herramientas-de-búsqueda-f10)
14. [Gestión del context window (F11)](#14-gestión-del-context-window-f11)
15. [Auto-evaluación --self-eval (F12)](#15-auto-evaluación---self-eval-f12)
16. [Ejecución de comandos --allow-commands (F13)](#16-ejecución-de-comandos---allow-commands-f13)
17. [Seguimiento de costes --show-costs (F14)](#17-seguimiento-de-costes---show-costs-f14)
18. [Hooks del lifecycle (v4-A1)](#18-hooks-del-lifecycle-v4-a1)
19. [Uso en scripts y pipes](#19-uso-en-scripts-y-pipes)
20. [CI/CD: GitHub Actions, GitLab, cron](#20-cicd-github-actions-gitlab-cron)
21. [Multi-proyecto: workspace y config por proyecto](#21-multi-proyecto-workspace-y-config-por-proyecto)
22. [Agentes custom en YAML](#22-agentes-custom-en-yaml)
23. [Comandos auxiliares](#23-comandos-auxiliares)
24. [Referencia rápida de flags](#24-referencia-rápida-de-flags)
25. [Guardrails (v4-A2)](#25-guardrails-v4-a2)
26. [Skills y .architect.md (v4-A3)](#26-skills-y-architectmd-v4-a3)
27. [Memoria procedural (v4-A4)](#27-memoria-procedural-v4-a4)

---

## 1. Instalación y setup inicial

```bash
# Clonar e instalar (modo editable)
git clone https://github.com/tu-usuario/architect-cli
cd architect-cli
pip install -e .

# Verificar instalación
architect --version   # architect, version 0.16.2
architect --help

# Configurar API key (mínimo requerido para llamadas LLM)
export LITELLM_API_KEY="sk-..."

# Verificar que funciona (no necesita API key para esto)
architect agents
architect validate-config -c config.example.yaml
```

**Archivos relevantes en el setup inicial:**

```
architect-cli/
├── config.example.yaml   ← punto de partida para tu config.yaml
├── pyproject.toml        ← dependencias del proyecto
└── src/architect/        ← código fuente
```

Copiar el ejemplo como base:

```bash
cp config.example.yaml config.yaml
# Editar config.yaml según tus necesidades
```

---

## 2. Uso básico sin configuración

El caso más simple: solo la API key en env, sin ningún archivo YAML.

```bash
export LITELLM_API_KEY="sk-..."

# Analizar un proyecto (solo lectura — safe)
architect run "explica qué hace este proyecto y su estructura"

# Leer y resumir un archivo
architect run "lee main.py y explica qué hace cada función" -a resume

# Revisar código
architect run "revisa src/utils.py y detecta problemas potenciales" -a review

# Planificar una tarea (sin ejecutar nada)
architect run "planifica cómo añadir autenticación JWT al proyecto" -a plan
```

Sin `-c config.yaml`, architect usa todos los defaults:
- Modelo: `gpt-4o`
- Workspace: directorio actual (`.`)
- Streaming: activo
- `allow_delete`: deshabilitado
- Confirmación: según el agente elegido
- Indexer: habilitado (construye árbol del proyecto automáticamente)

---

## 3. Selección de agente (`-a`)

```bash
# Sin -a → agente build directamente (default desde v0.15.0)
architect run "refactoriza el módulo de autenticación"

# Agente específico con -a / --agent
architect run "PROMPT" -a plan       # solo analiza, nunca modifica
architect run "PROMPT" -a build      # crea y modifica archivos
architect run "PROMPT" -a resume     # lee y resume, sin confirmaciones
architect run "PROMPT" -a review     # revisión de código

# Agente custom definido en config.yaml
architect run "PROMPT" -a deploy -c config.yaml
architect run "PROMPT" -a security-audit -c config.yaml
```

**¿Cuándo usar cada agente?**

| Situación | Agente recomendado |
|-----------|-------------------|
| Entender un proyecto nuevo | `resume` o `review` |
| Detectar bugs o problemas | `review` |
| Planificar antes de ejecutar | `plan` |
| Crear archivos o refactorizar | `build` o modo mixto |
| Tarea compleja que requiere análisis previo | `plan` primero, luego `build` |
| Tarea ya clara y bien definida | `build` (default, sin `-a`) |

---

## 4. Modos de confirmación (`--mode`)

Controla si architect pide confirmación antes de cada acción sobre archivos.

```bash
# confirm-all: confirma absolutamente todo (read Y write)
architect run "PROMPT" -a build --mode confirm-all

# confirm-sensitive: solo confirma escrituras y deletes (default del agente build)
architect run "PROMPT" -a build --mode confirm-sensitive

# yolo: sin confirmaciones (para CI o cuando confías en el agente)
architect run "PROMPT" -a build --mode yolo

# Ejemplos de uso según contexto
architect run "añade docstrings a utils.py" -a build --mode yolo         # desarrollo
architect run "reorganiza carpetas del proyecto" -a build --mode confirm-sensitive  # producción
architect run "analiza dependencias" -a resume --mode yolo               # solo lectura, seguro
```

**Nota sobre TTY**: `--mode confirm-all` y `--mode confirm-sensitive` requieren terminal interactiva. En scripts o CI sin TTY, usar `--mode yolo` o `--dry-run`.

```bash
# En CI: siempre yolo o dry-run
architect run "PROMPT" --mode yolo
architect run "PROMPT" --dry-run
```

El flag `--mode` sobreescribe el `confirm_mode` del agente. Si el agente tiene `confirm_mode: confirm-all` en YAML pero pasas `--mode yolo`, prevalece el flag de CLI.

**Nota sobre parallel tools**: con `--mode yolo`, las tool calls independientes se ejecutan en paralelo automáticamente (hasta 4 en paralelo). Con `--mode confirm-sensitive`, si alguna tool es sensible (`write_file`, `edit_file`, etc.) se vuelve secuencial para permitir confirmación interactiva.

---

## 5. Flags de output: `--json`, `--quiet`, `--dry-run`

### `--dry-run` — simular sin ejecutar

```bash
# Ver qué haría el agente sin que lo haga
architect run "elimina todos los archivos .tmp del proyecto" -a build --dry-run

# Dry-run con verbose para ver el plan completo
architect run "refactoriza config.py para usar dataclasses" -a build --dry-run -v

# Dry-run en CI para validar el prompt antes de ejecutar en prod
architect run "actualiza imports obsoletos" --mode yolo --dry-run
```

Con `--dry-run`:
- Las tool calls se ejecutan en modo simulación.
- Los mensajes devueltos al LLM son `[DRY-RUN] Se ejecutaría: write_file(path=...)`.
- El LLM puede seguir razonando sobre los resultados como si fuera real.
- Ningún archivo se modifica.

### `--json` — output estructurado

```bash
# Output JSON en stdout (logs en stderr)
architect run "resume el proyecto" -a resume --quiet --json

# Parsear con jq
architect run "resume el proyecto" -a resume --quiet --json | jq .status
architect run "resume el proyecto" -a resume --quiet --json | jq .output
architect run "resume el proyecto" -a resume --quiet --json | jq .steps
architect run "resume el proyecto" -a resume --quiet --json | jq '.tools_used[].name'
```

Formato del JSON:
```json
{
  "status":           "success",
  "output":           "El proyecto consiste en...",
  "steps":            3,
  "tools_used": [
    {"name": "read_file", "success": true},
    {"name": "edit_file", "success": true},
    {"name": "search_code", "success": true}
  ],
  "duration_seconds": 8.5,
  "model":            "gpt-4o-mini"
}
```

`--json` desactiva el streaming automáticamente (los chunks no se envían a stderr).

### `--quiet` — solo el resultado final

```bash
# Sin logs, solo stdout con la respuesta
architect run "genera el contenido de un .gitignore para Python" -a build --quiet

# Redirigir el resultado a un archivo
architect run "genera el contenido de un .gitignore para Python" -a build --quiet > .gitignore

# Combinado con --json para pipes limpios
architect run "resume el proyecto" -a resume --quiet --json | jq -r .output
```

`--quiet` mueve el log level a ERROR (solo errores en stderr). La respuesta del agente sigue yendo a stdout.

---

## 6. Flags de logging: `-v`, `--log-level`, `--log-file`

### Niveles de verbose

```bash
# Sin -v: solo pasos del agente con iconos en stderr (nivel HUMAN, WARNING técnico)
architect run "PROMPT" -a resume

# -v: steps del agente y tool calls (INFO level)
architect run "PROMPT" -a build -v

# -vv: argumentos de tools y respuestas LLM (DEBUG level)
architect run "PROMPT" -a build -vv

# -vvv: todo, incluyendo HTTP requests y payloads completos
architect run "PROMPT" -a build -vvv
```

Ejemplo de output con `-v`:
```
[INFO] agent.loop.start  agent=build step_timeout=0
[INFO] agent.step.start  step=1
[INFO] agent.tool_call.execute  tool=search_code pattern="def validate" file_pattern="*.py"
[INFO] agent.tool_call.complete tool=search_code success=True chars=842
[INFO] agent.tool_call.execute  tool=edit_file path=src/utils.py
[INFO] agent.tool_call.complete tool=edit_file success=True
[INFO] eval.basic.start   prompt_preview="refactoriza validate_path..."
[INFO] eval.basic.complete completed=True confidence=92%
[INFO] agent.complete     status=success steps=2
```

### `--log-level` — nivel base del logger

```bash
# Solo errores (más restrictivo)
architect run "PROMPT" --log-level error

# Debug completo (equivalente a -vvv, pero sin --verbose count)
architect run "PROMPT" --log-level debug
```

### `--log-file` — guardar logs en archivo JSON

```bash
# Guardar logs en archivo JSON Lines
architect run "PROMPT" -a build -v --log-file logs/session.jsonl

# El archivo captura DEBUG completo independientemente del verbose de consola
architect run "PROMPT" --log-file logs/session.jsonl     # consola quiet, archivo DEBUG

# Analizar los logs después
cat logs/session.jsonl | jq 'select(.event == "agent.tool_call.execute")'
cat logs/session.jsonl | jq 'select(.level == "error")'
cat logs/session.jsonl | jq 'select(.event | startswith("eval."))'
cat logs/session.jsonl | jq -r '.event + " " + (.step | tostring)' 2>/dev/null
```

---

## 7. Uso sin logs (silencioso)

Para scripts, pipes y automatización donde solo importa el resultado.

```bash
# Resultado limpio en stdout, sin ningún log en stderr
architect run "resume el proyecto en 3 líneas" -a resume --quiet

# Resultado a archivo, errores a /dev/null
architect run "genera README.md" -a build --quiet 2>/dev/null

# Solo JSON parseado, silencio total
architect run "analiza dependencias" -a resume --quiet --json 2>/dev/null | jq -r .output

# Verificar si tuvo éxito sin ver nada
architect run "valida la configuración" -a resume --quiet 2>/dev/null
echo "Exit code: $?"   # 0=éxito, 1=fallo, 2=parcial, 3=config error...
```

**Resumen de rutas de output:**

```
Modo normal:    stderr ← [streaming + logs]    stdout ← [resultado final]
--quiet:        stderr ← [solo errores]         stdout ← [resultado final]
--json:         stderr ← [logs según -v]        stdout ← [JSON completo]
--quiet --json: stderr ← [solo errores]         stdout ← [JSON completo]
```

---

## 8. Flags de LLM: `--model`, `--api-base`, `--api-key`, `--timeout`

### Cambiar modelo

```bash
# OpenAI
architect run "PROMPT" --model gpt-4o
architect run "PROMPT" --model gpt-4o-mini           # más barato
architect run "PROMPT" --model o1-mini               # razonamiento

# Anthropic
architect run "PROMPT" --model claude-opus-4-6       # más capaz
architect run "PROMPT" --model claude-sonnet-4-6     # balance
architect run "PROMPT" --model claude-haiku-4-5-20251001  # más rápido

# Google Gemini
architect run "PROMPT" --model gemini/gemini-2.0-flash
architect run "PROMPT" --model gemini/gemini-1.5-pro

# Ollama (local, sin API key)
architect run "PROMPT" --model ollama/llama3 --api-base http://localhost:11434
architect run "PROMPT" --model ollama/mistral --api-base http://localhost:11434
architect run "PROMPT" --model ollama/codellama --api-base http://localhost:11434
```

### Timeout y reintentos

```bash
# Timeout de 120 segundos para la SESIÓN COMPLETA (watchdog)
architect run "PROMPT" --timeout 120

# Tareas largas: aumentar timeout de sesión
architect run "analiza todo el código fuente del repositorio" -a resume --timeout 300

# Tareas rápidas en CI: timeout corto para fallar pronto
architect run "resume README" -a resume --timeout 30
```

**Nota**: `--timeout` controla el timeout **total de la sesión** (watchdog), no el timeout por llamada individual al LLM. El timeout per-request se configura en el YAML con `llm.timeout` (default: 60s). Esto permite tener sesiones largas (`--timeout 300`) sin que cada llamada al LLM tenga un timeout excesivo.

---

## 9. Archivos de configuración

### Estructura mínima de `config.yaml`

```yaml
llm:
  model: gpt-4o-mini
  api_key_env: LITELLM_API_KEY
  timeout: 60

workspace:
  root: .
  allow_delete: false
```

### `config.yaml` de desarrollo (con verbose y self-eval)

```yaml
llm:
  model: gpt-4o-mini
  api_key_env: LITELLM_API_KEY
  timeout: 60
  retries: 1
  stream: true

workspace:
  root: .
  allow_delete: false

logging:
  level: debug
  verbose: 2
  file: logs/dev.jsonl

indexer:
  enabled: true
  use_cache: true

context:
  max_tool_result_tokens: 2000
  parallel_tools: true

evaluation:
  mode: basic              # evalúa siempre en desarrollo
  confidence_threshold: 0.75

agents:
  build:
    confirm_mode: confirm-sensitive
    max_steps: 10
```

### `config.yaml` para producción / automatización

```yaml
llm:
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
  timeout: 120
  retries: 3
  stream: false

workspace:
  root: /ruta/al/proyecto
  allow_delete: false

logging:
  level: warn
  verbose: 0
  file: /var/log/architect/run.jsonl

indexer:
  enabled: true
  use_cache: true

context:
  max_tool_result_tokens: 2000
  max_context_tokens: 80000
  parallel_tools: true

evaluation:
  mode: full               # con reintentos en producción
  max_retries: 2
  confidence_threshold: 0.8

agents:
  build:
    confirm_mode: yolo
    max_steps: 30
```

### Usar `-c` para especificar el archivo

```bash
# Config por defecto (usa defaults si no hay YAML)
architect run "PROMPT"

# Config explícita
architect run "PROMPT" -c config.yaml
architect run "PROMPT" -c /etc/architect/prod.yaml

# Config + overrides de CLI (CLI siempre gana)
architect run "PROMPT" -c config.yaml --model gpt-4o --mode yolo --self-eval basic
```

---

## 10. Configuraciones por entorno

### Variables de entorno como override

```bash
ARCHITECT_MODEL=gpt-4o architect run "PROMPT"
ARCHITECT_WORKSPACE=/otro/proyecto architect run "PROMPT"
ARCHITECT_LOG_LEVEL=debug architect run "PROMPT"
```

### Múltiples configs con alias en shell

```bash
# En ~/.bashrc o ~/.zshrc
alias architect-dev='architect -c ~/configs/architect-dev.yaml'
alias architect-prod='architect -c ~/configs/architect-prod.yaml --mode confirm-all'
alias aresume='architect run -a resume --mode yolo --quiet'
alias areview='architect run -a review --mode yolo'

# Uso
aresume "explica este proyecto"
areview "revisa src/auth.py"
architect-dev run "refactoriza config.py" -a build
```

---

## 11. MCP: herramientas remotas

MCP (Model Context Protocol) permite al agente usar tools en servidores remotos.

```yaml
mcp:
  servers:
    - name: github
      url: http://localhost:3001
      token_env: GITHUB_TOKEN

    - name: database
      url: https://mcp.empresa.com/db
      token_env: DB_MCP_TOKEN
```

```bash
# Las tools MCP se descubren automáticamente
architect run "crea un PR con los cambios actuales" --mode yolo

# Deshabilitar MCP
architect run "PROMPT" --disable-mcp

# Ver tools MCP disponibles
architect agents -c config.yaml
```

Las tools MCP reciben el nombre `mcp_{servidor}_{nombre_tool}`. Con `parallel_tools=true`, las tool calls MCP independientes se ejecutan en paralelo, lo que es especialmente útil dado que son llamadas de red.

**Auto-inyección en `allowed_tools`**: A partir de v0.16.2, las tools MCP descubiertas se inyectan automáticamente en el `allowed_tools` del agente activo. No necesitas listarlas manualmente en la configuración del agente — basta con configurar los servidores MCP y las tools estarán disponibles para cualquier agente.

---

## 12. Herramientas de edición incremental (F9)

A partir de v0.9.0, el agente `build` tiene herramientas de edición más precisas que `write_file`:

### `edit_file` — sustitución exacta de texto

El agente puede modificar un bloque específico de código sin reescribir el archivo completo.

```bash
# Ejemplo: el agente usará edit_file para cambiar una función
architect run "cambia la función calculate() en utils.py para que acepte parámetros float" \
  -a build --mode yolo
```

El agente internamente:
1. Lee el archivo con `read_file`
2. Identifica el bloque a cambiar
3. Llama a `edit_file` con el texto exacto a reemplazar y el nuevo texto
4. Verifica el resultado

**Ventajas sobre `write_file`**:
- Consume menos tokens (solo manda el bloque cambiado, no el archivo completo)
- Menor riesgo de perder código no relacionado
- El diff del cambio queda en el historial del LLM

### `apply_patch` — unified diff

Para múltiples cambios en un archivo:

```bash
# Ejemplo: el agente aplica varios cambios a la vez
architect run "actualiza la API de logging en todos los módulos" -a build --mode yolo
```

El agente puede generar un unified diff y aplicarlo directamente.

### Controlar la estrategia de edición

El `BUILD_PROMPT` incluye una tabla de prioridades que el agente sigue:

```
1. edit_file   — un solo cambio contiguo (preferido)
2. apply_patch — múltiples cambios o diff preexistente
3. write_file  — archivos nuevos o reorganización completa
```

No hay un flag de CLI para forzar una estrategia — el agente decide según la tarea.

---

## 13. Indexer y herramientas de búsqueda (F10)

A partir de v0.10.0, el agente conoce la estructura del proyecto desde el primer momento.

### El árbol del proyecto en el system prompt

Al iniciar, architect indexa el workspace y añade automáticamente el árbol al system prompt:

```
🏗️  architect v0.12.0
📝 Prompt: refactoriza el módulo de autenticación
🤖 Modelo: gpt-4o-mini
📁 Workspace: /home/user/mi-proyecto
```

El agente ve algo como esto en su context:

```
## Estructura del Proyecto

Workspace: /home/user/mi-proyecto
Archivos: 47 archivos | 3,241 líneas
Lenguajes: Python (23), YAML (8), Markdown (6)

src/
├── auth/
│   ├── __init__.py     Python    12 líneas
│   ├── jwt.py          Python    89 líneas
│   └── middleware.py   Python    134 líneas
└── utils/
    └── validators.py   Python    67 líneas
```

Esto reduce el número de llamadas a `list_files` y permite planes más precisos desde el principio.

### Mostrar el árbol del índice con verbose

```bash
# -v muestra estadísticas del índice al iniciar
architect run "analiza el proyecto" -a resume -v

# Salida de ejemplo:
# 🗂️  Índice: 47 archivos, 3,241 líneas (23ms)
```

### Configurar el indexer

```yaml
indexer:
  enabled: true
  max_file_size: 1000000     # omitir archivos > 1MB
  use_cache: true            # caché de 5 minutos en disco

  # Excluir dirs adicionales (además de .git, node_modules, etc.)
  exclude_dirs:
    - vendor
    - .terraform
    - migrations/auto

  # Excluir patrones adicionales (además de *.pyc, *.min.js, etc.)
  exclude_patterns:
    - "*.generated.py"
    - "*.pb.go"
    - "*.lock"
```

```bash
# Deshabilitar indexer (el agente aún puede usar search_code, grep, find_files)
# En config.yaml: indexer.enabled: false
```

### Herramientas de búsqueda disponibles

Los agentes pueden usar estas tools durante su ejecución:

```bash
# El agente las usará internamente — ejemplos de lo que haría

# search_code: regex con contexto
# "Encuentra todos los usos de validate_path con contexto"
# → busca con patrón regex, devuelve líneas con N líneas de contexto

# grep: texto literal
# "Encuentra todas las importaciones de jwt"
# → busca texto exacto, más rápido que regex

# find_files: por nombre
# "Encuentra todos los archivos de configuración YAML"
# → busca por patrón de nombre de archivo
```

**Cuándo el agente usa cada tool** (instruido en el prompt):
- `search_code` — buscar implementaciones, patrones de código, usos de una función
- `grep` — buscar texto literal, imports, strings específicos
- `find_files` — localizar archivos por nombre o extensión

```bash
# Forzar uso de herramientas de búsqueda en el prompt
architect run "usa search_code para encontrar todos los lugares donde se llama a validate()" \
  -a review --quiet
```

---

## 14. Gestión del context window (F11)

A partir de v0.11.0, architect gestiona automáticamente el contexto para tareas largas.

### Cómo funciona (sin acción del usuario)

El `ContextManager` actúa en 3 niveles automáticamente:

1. **Truncado de tool results** (siempre activo): si un `read_file` devuelve 500 líneas, el agente recibe las primeras 40 + las últimas 20 con un marcador.
2. **Compresión con LLM** (tras 8+ pasos): cuando el agente ha hecho muchos pasos, los más antiguos se resumen en un párrafo.
3. **Ventana deslizante** (hard limit): si el total supera 80k tokens estimados, se eliminan los mensajes más antiguos.

### Configurar según el modelo

```yaml
context:
  max_tool_result_tokens: 2000   # tokens max por tool result (~8000 chars)

  # Para tareas muy largas: comprimir antes
  summarize_after_steps: 5       # default: 8
  keep_recent_steps: 3           # default: 4

  # Ajustar límite al modelo usado:
  max_context_tokens: 80000      # gpt-4o/mini
  # max_context_tokens: 150000   # claude-sonnet-4-6 (más grande)
  # max_context_tokens: 0        # desactivar (peligroso para tareas largas)

  parallel_tools: true           # tool calls independientes en paralelo
```

### Desactivar el parallel execution

```bash
# En config.yaml:
# context.parallel_tools: false

# O crear un agente que no lo use:
# agents:
#   build:
#     confirm_mode: confirm-all  # también desactiva paralelo (interacción TTY)
```

### Ver cuándo se activa la compresión

```bash
# Con -vv, verás logs de contexto
architect run "tarea larga con muchos pasos" -a build -vv

# Logs relevantes:
# [DEBUG] context.compress.start    tool_exchanges=9 threshold=8
# [DEBUG] context.compress.complete old_msgs=18 summary_len=342
# [DEBUG] context.window.enforce    estimated_tokens=85000 max=80000 removed=2
```

---

## 15. Auto-evaluación `--self-eval` (F12)

A partir de v0.12.0, architect puede verificar automáticamente si la tarea se completó correctamente.

### Modo `basic` — una evaluación extra

```bash
# El LLM evalúa el resultado tras completar la tarea
architect run "genera tests unitarios para src/auth.py" -a build --self-eval basic

# Output de ejemplo:
# 🏗️  architect v0.12.0
# ...
# 🔍 Evaluando resultado...
# ✓ Evaluación: completado (92% confianza)
```

Si la evaluación detecta problemas:
```
🔍 Evaluando resultado...
⚠️  Evaluación: incompleto (41% confianza)
   - No se crearon los tests para el método login()
   - Los imports de pytest faltan en el archivo generado
   Sugerencia: Añade tests para login() y el import pytest al principio
```

En este caso el estado cambia a `partial` (exit code 2).

**Coste**: ~500 tokens extra por la llamada de evaluación. Sin efecto en los archivos.

### Modo `full` — evaluación con reintentos automáticos

```bash
# Evalúa y, si falla, reintenta hasta 2 veces con un prompt de corrección
architect run "migra database.py de SQLite a PostgreSQL" -a build --self-eval full

# Output de ejemplo:
# 🔍 Evaluando resultado...
# (1er intento: falla → reintenta)
# (2do intento: pasa)
# ✓ Evaluación full completada (estado: success)
```

**Cuándo usar `full`**:
- Tareas complejas donde un error parcial es costoso
- Cuando el LLM puede necesitar ver el resultado de sus propias acciones para corregir
- CI/CD donde se prefiere reintentar antes de fallar

**Coste**: hasta `max_retries * (ejecución_completa + evaluación)`. Usar con criterio.

### Configurar en YAML (persistente)

```yaml
evaluation:
  mode: basic              # siempre evalúa (override con --self-eval off)
  confidence_threshold: 0.8
  max_retries: 2           # solo para modo full
```

```bash
# CLI siempre sobreescribe el YAML
architect run "PROMPT" --self-eval off    # desactiva aunque YAML diga basic/full
architect run "PROMPT" --self-eval full   # activa aunque YAML diga off
```

### Casos de uso prácticos

```bash
# Generación de código con verificación
architect run "genera una clase Python completa para manejar conexiones Redis" \
  -a build --mode yolo --self-eval basic

# Tests críticos — verificar que se crearon correctamente
architect run "escribe tests de integración para el módulo de pagos" \
  -a build --mode yolo --self-eval full

# Documentación — verificar que está completa
architect run "documenta toda la API pública de src/api.py con docstrings" \
  -a build --mode yolo --self-eval basic

# Combinado con --json para pipelines
architect run "refactoriza el módulo auth" \
  --mode yolo --quiet --json --self-eval basic \
  | jq '{status, output, steps}'
```

### Interpretar exit codes con self-eval

```bash
architect run "PROMPT" --self-eval basic --quiet
case $? in
  0) echo "Completado y verificado por el evaluador" ;;
  2) echo "Completado parcialmente — el evaluador detectó problemas" ;;
  1) echo "El agente falló antes de llegar a la evaluación" ;;
esac
```

---

## 16. Ejecución de comandos `--allow-commands` (F13)

A partir de v0.13.0, el agente `build` puede ejecutar comandos del sistema: tests, linters, compiladores y scripts.

### Habilitar la tool `run_command`

```bash
# Habilitado por defecto si commands.enabled: true en config
# Habilitar con flag (override de config)
architect run "ejecuta los tests y corrije los errores" -a build --allow-commands --mode yolo

# Deshabilitar aunque esté en config
architect run "PROMPT" -a build --no-commands
```

### Qué puede ejecutar el agente

El `BUILD_PROMPT` instruye al agente a usar `run_command` para verificar su propio trabajo:

```bash
# El agente ejecuta esto internamente tras modificar código:
# run_command(command="pytest tests/ -x", timeout=60)
# run_command(command="mypy src/", timeout=30)
# run_command(command="ruff check .", timeout=15)
```

### Clasificación de sensibilidad

| Tipo | Ejemplos | Confirmación en `confirm-sensitive` | Confirmación en `yolo` |
|------|----------|-------------------------------------|------------------------|
| `safe` | `ls`, `cat`, `git status`, `git log`, `grep`, `python --version` | No | No |
| `dev` | `pytest`, `mypy`, `ruff`, `make`, `npm run test`, `cargo build` | **Sí** | No |
| `dangerous` | Cualquier otro comando no reconocido | **Sí** | No |

```bash
# Con --mode yolo: TODOS los comandos se ejecutan sin confirmación
# (la seguridad contra destructivos la garantiza la blocklist — Capa 1)
# Con --mode confirm-sensitive: solo comandos 'dev' y 'dangerous' piden confirmación
architect run "crea tests y verifica que pasan" -a build --allow-commands --mode yolo
```

### Seguridad integrada

La tool siempre bloquea: `rm -rf /`, `rm -rf ~`, `sudo`, `chmod 777`, `curl|bash`, `dd of=/dev/`, `mkfs` y otros comandos destructivos, independientemente del modo de confirmación.

```bash
# Bloqueado siempre (BlockedCommandError):
# run_command("sudo apt-get install ...")    → bloqueado
# run_command("rm -rf /tmp/proyecto")       → ¡ATENCIÓN! rm -rf sin / no está bloqueado → 'dangerous'
# run_command("curl -s url | bash")         → bloqueado
```

### Configurar en YAML

```yaml
commands:
  enabled: true
  default_timeout: 60       # timeout por defecto en segundos
  max_output_lines: 200     # límite de líneas de output
  safe_commands:
    - "my-custom-lint.sh"   # comandos adicionales clasificados como 'safe'
  blocked_patterns:
    - "git push"            # bloquear operaciones git destructivas
  allowed_only: false       # si true, solo safe/dev permitidos en execute()
```

### Flujo típico del agente con run_command

```
1. edit_file(path="src/auth.py", ...)           → modifica el archivo
2. run_command(command="mypy src/auth.py")      → verifica tipos
3. run_command(command="pytest tests/test_auth.py -x")  → ejecuta tests
4. (si hay errores) → lee el output, corrige, repite
```

---

## 17. Seguimiento de costes `--show-costs` (F14)

A partir de v0.14.0, architect registra el coste de cada llamada al LLM y puede detener la ejecución si se supera un presupuesto.

### Ver el coste de una ejecución

```bash
# Mostrar resumen al terminar (funciona con streaming y sin streaming)
architect run "PROMPT" -a build --show-costs

# También se activa con -v (verbose)
architect run "PROMPT" -a build -v

# Output de ejemplo:
# 💰 Coste: $0.0042 (12,450 in / 3,200 out / 500 cached)
```

A partir de v0.16.2, `--show-costs` funciona correctamente tanto en modo streaming (default) como sin streaming (`--no-stream` o `--json`). En streaming, se solicita `stream_options: {include_usage: true}` al provider para obtener el uso real de tokens; si el provider no lo soporta, se estima el uso con `litellm.token_counter`.

### Presupuesto máximo

```bash
# Detener si se superan $0.50
architect run "tarea larga" -a build --mode yolo --budget 0.50

# Si se supera el presupuesto:
# Estado: partial
# Output: "Presupuesto excedido: $0.5023 > $0.5000 USD"
# Exit code: 2
```

### El coste en el JSON output

```bash
architect run "PROMPT" --quiet --json | jq .costs
# {
#   "total_input_tokens": 12450,
#   "total_output_tokens": 3200,
#   "total_cached_tokens": 500,
#   "total_tokens": 15650,
#   "total_cost_usd": 0.004213,
#   "by_source": {
#     "agent": 0.003800,
#     "eval": 0.000413
#   }
# }
```

### Prompt caching — ahorro de tokens

```yaml
# config.yaml
llm:
  model: claude-sonnet-4-6
  api_key_env: ANTHROPIC_API_KEY
  prompt_caching: true   # ahorra 50-90% en el system prompt en llamadas repetidas
```

Con `prompt_caching: true`, el system prompt (incluyendo el árbol del indexer) se cachea automáticamente en el proveedor. Los `cached_tokens` aparecen en el resumen de costes y se cobran a precio reducido.

### Cache local de LLM para desarrollo

```bash
# Activar cache local (evita llamadas repetidas al LLM con los mismos mensajes)
architect run "PROMPT" -a build --cache

# Limpiar cache antes de ejecutar
architect run "PROMPT" -a build --cache --cache-clear

# Desactivar aunque esté en config.yaml
architect run "PROMPT" --no-cache
```

```yaml
# config.yaml — habilitar para todo el equipo de desarrollo
llm_cache:
  enabled: true         # false en producción
  dir: ~/.architect/cache
  ttl_hours: 24         # entradas válidas por 24 horas
```

**ATENCIÓN**: el cache local es solo para desarrollo. Retorna respuestas anteriores exactas — si el contexto real ha cambiado, la respuesta puede estar obsoleta.

### Configurar presupuesto en YAML

```yaml
costs:
  enabled: true
  budget_usd: 2.0      # máximo $2 por ejecución
  warn_at_usd: 1.0     # aviso (sin detener) al alcanzar $1
  # prices_file: custom_prices.json  # precios custom si usas un proxy
```

### Interpretar costes en CI

```bash
architect run "PROMPT" --mode yolo --quiet --json --budget 1.0 \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
costs = data.get('costs', {})
print(f\"Status: {data['status']}\")
print(f\"Coste: \${costs.get('total_cost_usd', 0):.4f}\")
print(f\"Tokens: {costs.get('total_tokens', 0):,}\")
"
```

---

## 18. Hooks del lifecycle (v4-A1)

A partir de v0.16.0, architect soporta un sistema completo de hooks en **10 eventos del lifecycle**. El sistema es retrocompatible con los `post_edit` hooks de v0.15.x.

### Eventos disponibles

| Evento | Cuándo se ejecuta | Tipo |
|--------|-------------------|------|
| `pre_tool_use` | Antes de ejecutar cada tool call | Pre-hook (puede BLOCK) |
| `post_tool_use` | Después de ejecutar cada tool call | Post-hook |
| `pre_llm_call` | Antes de cada llamada al LLM | Pre-hook (puede BLOCK) |
| `post_llm_call` | Después de cada respuesta del LLM | Post-hook |
| `session_start` | Al iniciar la sesión del agente | Notificación |
| `session_end` | Al terminar la sesión del agente | Notificación |
| `on_error` | Cuando ocurre un error en el loop | Notificación |
| `budget_warning` | Cuando se alcanza `warn_at_usd` | Notificación |
| `context_compress` | Cuando se comprime el contexto | Notificación |
| `agent_complete` | Cuando el agente termina su tarea | Notificación |

### Protocolo de exit codes

Los hooks se ejecutan como subprocesos del sistema y se comunican mediante exit codes:

| Exit code | Decisión | Descripción |
|:---------:|----------|-------------|
| `0` | **ALLOW** | Permite la acción. stdout puede contener JSON con `additionalContext` o `updatedInput` |
| `2` | **BLOCK** | Bloquea la acción (solo pre-hooks). stderr contiene la razón |
| Otro | **Error** | Se logea como warning, no rompe el loop. La acción se permite |

### Configurar hooks en YAML

```yaml
hooks:
  # Hooks del lifecycle completo (v4-A1)
  pre_tool_use:
    - name: validate-path
      command: "python3 scripts/validate.py"
      matcher: "write_file|edit_file"    # regex para filtrar tools
      timeout: 5

  post_tool_use:
    - name: python-lint
      command: "ruff check {file} --no-fix"
      file_patterns: ["*.py"]
      timeout: 15
    - name: python-typecheck
      command: "mypy {file} --no-error-summary"
      file_patterns: ["*.py"]
      timeout: 30

  session_start:
    - name: notify-start
      command: "echo 'Sesión iniciada'"
      async: true                        # ejecutar en background sin bloquear

  on_error:
    - name: log-error
      command: "logger -t architect 'Error en sesión'"

  # Retrocompatibilidad v3-M4: post_edit se mapea a post_tool_use
  # con matcher automático para edit_file/write_file/apply_patch
  post_edit:
    - name: legacy-lint
      command: "ruff check {file}"
      file_patterns: ["*.py"]
      timeout: 15
```

### Campos de cada hook

```yaml
- name: mi-hook             # nombre descriptivo
  command: "mi-script.sh"   # comando shell a ejecutar
  matcher: "*"              # regex/glob para filtrar tools (default: "*")
  file_patterns: ["*.py"]   # patrones glob para filtrar archivos
  timeout: 10               # segundos (1-300, default: 10)
  async: false              # true = ejecutar en background sin bloquear
  enabled: true             # false = ignorar este hook
```

### Variables de entorno inyectadas

Los hooks reciben contexto via variables de entorno `ARCHITECT_*`:

| Variable | Contenido |
|----------|-----------|
| `ARCHITECT_EVENT` | Nombre del evento (e.g., `pre_tool_use`) |
| `ARCHITECT_WORKSPACE` | Directorio raíz del workspace |
| `ARCHITECT_TOOL` | Nombre de la tool (en eventos de tools) |
| `ARCHITECT_FILE` | Path del archivo (si aplica) |
| `ARCHITECT_EDITED_FILE` | Path del archivo editado (retrocompat v3) |

Además, `{file}` en el comando se reemplaza con el path del archivo editado.

### Ejemplo: pre-hook que bloquea

```bash
#!/bin/bash
# scripts/validate-no-secrets.sh
# Bloquea si el archivo contiene API keys
if grep -qE "(sk-|AKIA)" "$ARCHITECT_FILE" 2>/dev/null; then
    echo "Archivo contiene posibles secretos" >&2
    exit 2   # BLOCK
fi
exit 0       # ALLOW
```

```yaml
hooks:
  pre_tool_use:
    - name: no-secrets
      command: "bash scripts/validate-no-secrets.sh"
      matcher: "write_file|edit_file"
      file_patterns: ["*.py", "*.env"]
```

### Ejemplo: post-hook con lint automático

```yaml
hooks:
  post_tool_use:
    - name: python-lint
      command: "ruff check {file} --no-fix"
      file_patterns: ["*.py"]
      timeout: 15
```

El agente edita `src/main.py`:
1. `edit_file` ejecuta el cambio — OK
2. Hook `python-lint` ejecuta `ruff check src/main.py` — 1 error
3. El LLM ve: `[Hook python-lint: FALLO (exit 1)] src/main.py:15:5: F841...`
4. El LLM corrige el error automáticamente con otro `edit_file`

### Hooks async (no bloqueantes)

```yaml
hooks:
  session_end:
    - name: notify-slack
      command: "curl -s -X POST $SLACK_WEBHOOK -d '{\"text\": \"Sesión completada\"}'"
      async: true    # no bloquea la finalización
```

Los hooks con `async: true` se ejecutan en un thread daemon en background. No bloquean el loop ni esperan resultado.

---

## 19. Uso en scripts y pipes

### Capturar resultado en variable

```bash
# Capturar solo el resultado (stdout)
RESULTADO=$(architect run "resume el proyecto en 1 línea" -a resume --quiet)
echo "El proyecto es: $RESULTADO"

# Con JSON
JSON=$(architect run "analiza el proyecto" -a resume --quiet --json)
STATUS=$(echo "$JSON" | jq -r .status)
OUTPUT=$(echo "$JSON" | jq -r .output)
STEPS=$(echo "$JSON" | jq -r .steps)
echo "Status: $STATUS, Steps: $STEPS"
```

### Verificar código de salida

```bash
architect run "tarea" --mode yolo --quiet
case $? in
  0)   echo "Completado con éxito" ;;
  1)   echo "El agente falló" ;;
  2)   echo "Completado parcialmente (o evaluador falló)" ;;
  3)   echo "Error de configuración" ;;
  4)   echo "Error de autenticación (API key)" ;;
  5)   echo "Timeout" ;;
  130) echo "Interrumpido (Ctrl+C)" ;;
esac
```

### Generar archivos directamente

```bash
# Generar y guardar resultado
architect run "genera un .gitignore completo para un proyecto Python con pytest" \
  -a build --mode yolo --quiet > .gitignore

# Generar README
architect run "genera un README.md para este proyecto basándote en el código fuente" \
  -a build --mode yolo --quiet > README_generated.md

# Generar tests con verificación
architect run "genera tests unitarios para src/utils.py usando pytest" \
  -a build --mode yolo --self-eval basic --quiet > tests/test_utils.py
```

### Encadenar con otras herramientas

```bash
# Analizar y enviar resultado a un servicio
architect run "analiza vulnerabilidades de seguridad en el código" \
  -a review --quiet --json \
  | jq -r .output \
  | curl -s -X POST https://api.miservicio.com/reports \
    -H "Content-Type: text/plain" --data-binary @-

# Procesar múltiples archivos
for file in src/*.py; do
  echo "=== Revisando $file ==="
  architect run "revisa $file en busca de bugs y code smells" \
    -a review --quiet -w "$(dirname "$file")"
done

# Verificar si la auto-evaluación pasó
architect run "genera la documentación de la API" -a build --self-eval basic --quiet --json \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data['status'] == 'partial':
    print('ADVERTENCIA: documentación incompleta', file=sys.stderr)
    sys.exit(2)
print(data['output'])
"
```

---

## 20. CI/CD: GitHub Actions, GitLab, cron

### GitHub Actions

```yaml
# .github/workflows/architect.yml
name: Architect AI Task

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 9 * * 1'   # todos los lunes a las 9:00

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install architect
        run: pip install -e .

      - name: Run architect with self-eval
        env:
          LITELLM_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          architect run "revisa los cambios del último commit y detecta posibles bugs" \
            -a review \
            --mode yolo \
            --self-eval basic \
            --quiet \
            --json \
            -c ci/architect.yaml \
            | tee result.json

      - name: Check result
        run: |
          STATUS=$(cat result.json | jq -r .status)
          OUTPUT=$(cat result.json | jq -r .output)
          echo "$OUTPUT"
          if [ "$STATUS" = "failed" ]; then
            echo "::error::Architect falló: $STATUS"
            exit 1
          fi
          if [ "$STATUS" = "partial" ]; then
            echo "::warning::Architect completó parcialmente (evaluación detectó problemas)"
          fi

      - name: Upload logs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: architect-logs
          path: logs/
```

### Config para CI (`ci/architect.yaml`)

```yaml
llm:
  model: gpt-4o-mini
  api_key_env: LITELLM_API_KEY
  timeout: 120
  retries: 3
  stream: false            # sin streaming en CI

workspace:
  root: .
  allow_delete: false

logging:
  verbose: 0
  level: warn
  file: logs/ci-run.jsonl

indexer:
  enabled: true
  use_cache: false         # en CI siempre reconstruir (cada run es fresco)

context:
  parallel_tools: true

evaluation:
  mode: basic              # evaluar en CI
  confidence_threshold: 0.7  # más permisivo en CI
```

### GitLab CI

```yaml
# .gitlab-ci.yml
architect-review:
  stage: test
  image: python:3.12
  before_script:
    - pip install -e .
  script:
    - |
      architect run "revisa los archivos modificados en este MR" \
        -a review \
        --mode yolo \
        --self-eval basic \
        --quiet \
        --json \
        -c ci/architect.yaml \
        > result.json
    - cat result.json | python3 -c "
      import json,sys
      r = json.load(sys.stdin)
      print(r['output'])
      sys.exit(0 if r['status'] in ['success','partial'] else 1)
      "
  variables:
    LITELLM_API_KEY: $OPENAI_API_KEY
  artifacts:
    paths:
      - result.json
      - logs/
    when: always
```

### Cron job (análisis periódico)

```bash
#!/bin/bash
# /usr/local/bin/architect-review.sh

export LITELLM_API_KEY="sk-..."
cd /ruta/al/proyecto

FECHA=$(date +%Y%m%d)
LOG_FILE="logs/review-${FECHA}.jsonl"

architect run "analiza el estado actual del proyecto, detecta deuda técnica y genera un reporte" \
  -a review \
  --mode yolo \
  --self-eval basic \
  --quiet \
  --json \
  --log-file "$LOG_FILE" \
  -c ci/architect.yaml \
  > "reports/review-${FECHA}.json"

STATUS=$(cat "reports/review-${FECHA}.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
echo "[$(date)] Review completado: status=$STATUS log=$LOG_FILE"
```

---

## 21. Multi-proyecto: workspace y config por proyecto

### Workspace explícito con `-w`

```bash
# Trabajar en un proyecto diferente al CWD
architect run "resume qué hace este proyecto" -a resume -w /ruta/a/otro-proyecto

# Con config del proyecto
architect run "refactoriza el módulo principal" -a build \
  -w /ruta/a/proyecto \
  -c /ruta/a/proyecto/architect.yaml

# Múltiples proyectos con el mismo config base
BASE_CONFIG=~/configs/architect-base.yaml
architect run "analiza el proyecto" -a resume -w ~/projects/proyecto-a -c $BASE_CONFIG
architect run "analiza el proyecto" -a resume -w ~/projects/proyecto-b -c $BASE_CONFIG
```

### Config por proyecto (en la raíz de cada repo)

```yaml
# mi-proyecto/architect.yaml
llm:
  model: claude-sonnet-4-6
  api_key_env: ANTHROPIC_API_KEY
  timeout: 90

workspace:
  root: .
  allow_delete: true

indexer:
  exclude_dirs:
    - vendor
    - .terraform

context:
  max_context_tokens: 150000   # Claude tiene ventana más grande

evaluation:
  mode: full
  max_retries: 2

agents:
  build:
    max_steps: 30
  migrator:
    system_prompt: |
      Eres un experto en migrar este proyecto de Python 2 a Python 3.
    allowed_tools:
      - read_file
      - search_code
      - edit_file
      - write_file
    confirm_mode: confirm-sensitive
    max_steps: 50
```

```bash
# Desde dentro del proyecto
architect run "migra auth.py a Python 3" -a migrator -c architect.yaml
```

---

## 22. Agentes custom en YAML

### Definir y usar un agente custom completo

```yaml
# config.yaml
agents:
  # Agente de deployment
  deploy:
    system_prompt: |
      Eres un agente de deployment especializado.

      Tu trabajo es preparar el código para producción:
      1. Verifica que existan tests (usa find_files y read_file)
      2. Revisa la configuración de producción
      3. Lee CI/CD files para entender el pipeline
      4. Genera un reporte ANTES de hacer cualquier cambio

      NUNCA modifiques archivos de producción sin haber generado el reporte primero.
    allowed_tools:
      - read_file
      - list_files
      - search_code
      - write_file
    confirm_mode: confirm-all
    max_steps: 15

  # Agente de documentación
  documenter:
    system_prompt: |
      Eres un agente de documentación técnica.
      Lee el código y genera documentación clara y bien estructurada.
      - Usa docstrings para funciones y clases
      - Genera archivos .md cuando sea apropiado
      - No modifiques lógica del código
    allowed_tools:
      - read_file
      - search_code
      - edit_file
      - write_file
      - list_files
    confirm_mode: confirm-sensitive
    max_steps: 20

  # Agente de auditoría de seguridad (solo lectura)
  security:
    system_prompt: |
      Eres un experto en seguridad de software.
      Analiza el código en busca de:
      - Inyección SQL, XSS, CSRF
      - Secretos hardcoded (API keys, passwords)
      - Validación de input de usuario
      - Dependencias con CVEs conocidos

      Usa grep para buscar patrones peligrosos y search_code para analizar el código.
      Genera un reporte priorizado: CRÍTICO > ALTO > MEDIO > BAJO.
    allowed_tools:
      - read_file
      - list_files
      - grep
      - search_code
      - find_files
    confirm_mode: yolo
    max_steps: 25
```

```bash
# Usar agentes custom
architect run "prepara el release 1.2.0" -a deploy -c config.yaml
architect run "documenta el módulo de autenticación" -a documenter -c config.yaml --self-eval basic
architect run "audita la seguridad de toda la aplicación" -a security -c config.yaml
```

### Override parcial de un agente por defecto

```yaml
# Solo cambia lo que necesitas; el resto hereda del default
agents:
  build:
    confirm_mode: confirm-all   # más estricto que el default (confirm-sensitive)
    max_steps: 15               # más pasos que el default (20)
    # system_prompt, allowed_tools → heredan del DEFAULT_AGENTS["build"]
```

---

## 23. Comandos auxiliares

### `architect agents` — listar agentes disponibles

```bash
# Ver agentes por defecto
architect agents

# Con config: incluye agentes custom
architect agents -c config.yaml

# Salida de ejemplo:
# Agentes disponibles:
#   plan      [confirm-all]        Analiza y planifica sin ejecutar
#   build     [confirm-sensitive]  Crea y modifica archivos del workspace
#   resume    [yolo]               Lee y resume información del proyecto
#   review    [yolo]               Revisa código y genera feedback
#   deploy  * [confirm-all]        (definido en config.yaml)
#   security  [yolo]               (definido en config.yaml)
```

### `architect validate-config` — validar configuración

```bash
# Validar un archivo de configuración
architect validate-config -c config.yaml
# → "Configuración válida: model=gpt-4o-mini, workspace=., retries=2"
# Exit 0

# Validar con todas las nuevas secciones
architect validate-config -c config.example.yaml
# → "Configuración válida: model=gpt-4o-mini, workspace=., retries=2, agentes=0, MCP servers=0"
```

### `architect skill` — gestión de skills (v4-A3)

```bash
# Listar skills instaladas y locales
architect skill list

# Crear una skill local nueva
architect skill create mi-skill
# → Crea .architect/skills/mi-skill/SKILL.md con plantilla

# Instalar skill desde GitHub
architect skill install usuario/repo
architect skill install usuario/repo/path/to/skill

# Desinstalar una skill
architect skill remove nombre-skill
```

---

## 24. Referencia rápida de flags

### `architect run PROMPT [OPTIONS]`

```
Identificación
  -c, --config PATH         Archivo YAML de configuración
  -a, --agent NAME          Agente: plan, build, resume, review, o custom

Ejecución
  -m, --mode MODE           confirm-all | confirm-sensitive | yolo
  -w, --workspace PATH      Directorio de trabajo
  --dry-run                 Simular sin ejecutar cambios reales
  --max-steps N             Límite máximo de pasos del agente

LLM
  --model MODEL             Modelo (gpt-4o, claude-sonnet-4-6, ollama/llama3...)
  --api-base URL            URL base de la API (Proxy, Ollama, custom)
  --api-key KEY             API key directa (mejor usar env var)
  --no-stream               Esperar respuesta completa (sin streaming)
  --timeout N               Timeout total de sesión en segundos (watchdog)

Output
  --json                    Output JSON en stdout (desactiva streaming)
  --quiet                   Solo errores en stderr, resultado en stdout
  -v / -vv / -vvv           Verbose: steps / debug / todo

Logging
  --log-level LEVEL         debug | info | warn | error
  --log-file PATH           Guardar logs JSON en archivo .jsonl

MCP
  --disable-mcp             No conectar a servidores MCP configurados

Auto-evaluación (F12)
  --self-eval MODE          off | basic | full (default: usa config YAML)

Ejecución de comandos (F13)
  --allow-commands          Habilitar run_command (sobreescribe config YAML)
  --no-commands             Deshabilitar run_command (sobreescribe config YAML)

Costes y caché (F14)
  --budget FLOAT            Límite de gasto en USD (detiene si se supera)
  --show-costs              Mostrar resumen de costes al final (también con -v)
  --cache                   Activar cache local de respuestas LLM
  --no-cache                Desactivar cache local de respuestas LLM
  --cache-clear             Limpiar cache local antes de ejecutar

Hooks y guardrails (v4)
  (hooks y guardrails se configuran exclusivamente via YAML — sin flags de CLI)
```

### Combinaciones más comunes

```bash
# Análisis rápido (sin confirmar nada)
architect run "PROMPT" -a resume --quiet

# Revisión de código con detalle
architect run "PROMPT" -a review -v

# Tarea automatizada (CI/scripts)
architect run "PROMPT" --mode yolo --quiet --json

# Con evaluación automática (recomendado para tareas importantes)
architect run "PROMPT" -a build --mode yolo --self-eval basic

# Debug completo de una ejecución
architect run "PROMPT" -a build -vvv --log-file debug.jsonl --no-stream

# Simulación antes de ejecutar
architect run "PROMPT" -a build --dry-run -v

# Con modelo específico, self-eval y timeout largo
architect run "PROMPT" -a build --model gpt-4o --timeout 300 --mode yolo --self-eval full

# Proyecto externo con config propia
architect run "PROMPT" -a build -w /ruta/proyecto -c /ruta/proyecto/architect.yaml

# Pipeline completo: ejecutar, evaluar, capturar JSON
architect run "PROMPT" --mode yolo --self-eval basic --quiet --json \
  | jq '{status, steps, output: .output[:200]}'

# Con comandos habilitados y presupuesto limitado
architect run "PROMPT" -a build --allow-commands --budget 0.5 --show-costs

# Desarrollo con cache local (evita llamadas repetidas al LLM)
architect run "PROMPT" -a build --cache --show-costs

# CI con presupuesto estricto y output JSON (incluye costs en el JSON)
architect run "PROMPT" --mode yolo --allow-commands --budget 1.0 --quiet --json
```

---

## 25. Guardrails (v4-A2)

A partir de v0.16.0, architect incluye un motor de **guardrails deterministas** que se evalúan ANTES de los hooks. Son reglas de seguridad que no pueden ser desactivadas por el LLM.

### Configurar en YAML

```yaml
guardrails:
  enabled: true

  # Archivos protegidos (glob patterns)
  protected_files:
    - ".env"
    - "*.pem"
    - "*.key"
    - "secrets/**"

  # Comandos bloqueados (regex patterns)
  blocked_commands:
    - "git push --force"
    - "docker rm -f"
    - "kubectl delete"

  # Límites de edición por sesión
  max_files_modified: 10       # máximo archivos distintos modificados
  max_lines_changed: 500       # máximo líneas cambiadas acumuladas
  max_commands_executed: 20    # máximo comandos ejecutados

  # Forzar tests después de N ediciones
  require_test_after_edit: true

  # Reglas de código (análisis estático simple)
  code_rules:
    - pattern: "eval\\("
      message: "Uso de eval() detectado — potencial riesgo de seguridad"
      severity: block            # block | warn

    - pattern: "TODO|FIXME|HACK"
      message: "Marcador temporal encontrado"
      severity: warn

  # Quality gates (se ejecutan al completar el agente)
  quality_gates:
    - name: lint
      command: "ruff check src/"
      required: true             # true = bloquea si falla
      timeout: 60

    - name: tests
      command: "pytest tests/ -x --tb=short"
      required: true
      timeout: 120

    - name: typecheck
      command: "mypy src/ --no-error-summary"
      required: false            # solo informativo
      timeout: 60
```

### Orden de evaluación

```
Guardrails (determinista, primero)
  ↓
Hooks pre_tool_use (shell scripts, pueden BLOCK)
  ↓
Ejecución de la tool
  ↓
Hooks post_tool_use (lint, typecheck, etc.)
```

Los guardrails se evalúan **siempre antes** que los hooks. Si un guardrail bloquea, ni siquiera se ejecutan los hooks.

### Qué protege cada guardrail

| Guardrail | Protección |
|-----------|-----------|
| `protected_files` | Bloquea write/edit/delete en archivos sensibles |
| `blocked_commands` | Bloquea `run_command` con patrones peligrosos |
| `max_files_modified` | Limita el alcance de cambios por sesión |
| `max_lines_changed` | Evita refactorizaciones masivas no intencionadas |
| `max_commands_executed` | Previene loops infinitos de ejecución |
| `require_test_after_edit` | Fuerza al agente a ejecutar tests periódicamente |
| `code_rules` | Detecta patrones peligrosos en código escrito |
| `quality_gates` | Verificación final de calidad al completar |

### Ejemplo: equipo con políticas estrictas

```yaml
guardrails:
  enabled: true
  protected_files: [".env", "*.pem", "deploy/**", "Dockerfile"]
  blocked_commands: ["git push", "docker build"]
  max_files_modified: 5
  max_lines_changed: 200
  require_test_after_edit: true
  quality_gates:
    - name: tests
      command: "pytest tests/ -x"
      required: true
      timeout: 120
```

---

## 26. Skills y .architect.md (v4-A3)

A partir de v0.16.0, architect soporta un sistema de **skills** de dos niveles para inyectar contexto específico del proyecto en el system prompt del agente.

### Nivel 1: Contexto del proyecto (siempre activo)

Architect busca automáticamente estos archivos en la raíz del workspace:

```
.architect.md    ← preferido
AGENTS.md        ← alternativa
CLAUDE.md        ← alternativa
```

Si existe alguno, su contenido se inyecta al inicio del system prompt como `# Instrucciones del Proyecto`.

```markdown
<!-- .architect.md -->
# Convenciones del Proyecto

- Usar snake_case en Python, camelCase en TypeScript
- Siempre incluir docstrings en funciones públicas
- Tests en tests/ con nombre test_*.py
- No usar print() para debug, usar logging
```

### Nivel 2: Skills activadas por glob

Las skills son carpetas en `.architect/skills/` o `.architect/installed-skills/` con un archivo `SKILL.md`:

```
.architect/
├── skills/
│   ├── django-patterns/
│   │   └── SKILL.md
│   └── api-docs/
│       └── SKILL.md
└── installed-skills/
    └── react-best-practices/
        └── SKILL.md
```

#### Formato de SKILL.md

```markdown
---
name: django-patterns
description: "Patrones Django para este proyecto"
globs: ["*.py", "**/views.py", "**/models.py"]
---

# Patrones Django

- Usar class-based views para CRUD
- Validar con serializers, nunca en views
- Queries con select_related/prefetch_related
```

El YAML frontmatter define cuándo se activa la skill (por `globs`). Si el agente está trabajando con archivos que coinciden con los globs, la skill se inyecta automáticamente.

### Gestión de skills

```bash
# Crear skill local
architect skill create mi-patron
# → .architect/skills/mi-patron/SKILL.md (plantilla)

# Instalar desde GitHub (sparse checkout)
architect skill install usuario/repo
architect skill install usuario/repo/skills/mi-skill

# Listar todas
architect skill list
# Salida:
# Skills disponibles:
#   django-patterns  [local]     .architect/skills/django-patterns/
#   react-best       [installed] .architect/installed-skills/react-best/

# Desinstalar
architect skill remove react-best
```

### Configurar en YAML

```yaml
skills:
  auto_discover: true      # descubrir skills automáticamente (default: true)
  inject_by_glob: true     # inyectar skills según archivos activos (default: true)
```

---

## 27. Memoria procedural (v4-A4)

A partir de v0.16.0, architect puede detectar correcciones del usuario y almacenarlas como **memoria procedural** que persiste entre sesiones.

### Cómo funciona

1. El usuario corrige al agente: *"No, usa const en vez de var"*
2. Architect detecta el patrón de corrección automáticamente
3. Lo guarda en `.architect/memory.md` con timestamp
4. En sesiones futuras, el contenido de `memory.md` se inyecta en el system prompt

### Patrones de detección

Architect detecta 6 tipos de correcciones en español:

| Tipo | Ejemplo |
|------|---------|
| Corrección directa | "No, usa const" / "No utilices var" |
| Negación | "Eso no es correcto" / "Eso está mal" |
| Clarificación | "En realidad es así..." / "De hecho..." |
| Debería ser | "Debería ser snake_case" / "El correcto es..." |
| Enfoque incorrecto | "No funciona así" / "Así no" |
| Regla absoluta | "Siempre usa TypeScript" / "Nunca pongas secrets en código" |

### Archivo de memoria

```markdown
<!-- .architect/memory.md (auto-generado, editable manualmente) -->
# Memoria del Proyecto

> Auto-generado por architect. Editable manualmente.

- [2026-02-22] Correccion: No uses var, usa const en todo el proyecto
- [2026-02-22] Patron: Siempre incluir error handling en try-catch
- [2026-02-23] Correccion: El comando correcto es pnpm, no npm
```

### Configurar en YAML

```yaml
memory:
  enabled: true                    # activar memoria procedural (default: false)
  auto_detect_corrections: true    # detectar correcciones automáticamente (default: true)
```

### Uso manual

El archivo `.architect/memory.md` es editable manualmente. Puedes añadir reglas que quieras que el agente siempre recuerde:

```markdown
- [2026-02-22] Patron: En este proyecto usamos pnpm, nunca npm ni yarn
- [2026-02-22] Patron: Los tests van en __tests__/ al lado del código fuente
- [2026-02-22] Patron: Usar zod para validación de schemas, no joi
```
