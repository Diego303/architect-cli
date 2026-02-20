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
16. [Uso en scripts y pipes](#16-uso-en-scripts-y-pipes)
17. [CI/CD: GitHub Actions, GitLab, cron](#17-cicd-github-actions-gitlab-cron)
18. [Multi-proyecto: workspace y config por proyecto](#18-multi-proyecto-workspace-y-config-por-proyecto)
19. [Agentes custom en YAML](#19-agentes-custom-en-yaml)
20. [Comandos auxiliares](#20-comandos-auxiliares)
21. [Referencia rápida de flags](#21-referencia-rápida-de-flags)

---

## 1. Instalación y setup inicial

```bash
# Clonar e instalar (modo editable)
git clone https://github.com/tu-usuario/architect-cli
cd architect-cli
pip install -e .

# Verificar instalación
architect --version   # architect, version 0.12.0
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
# Sin -a → modo mixto automático (plan → build)
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
| Tarea compleja que requiere análisis previo | modo mixto (sin `-a`) |
| Tarea ya clara y bien definida | `build` directamente |

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
# Sin -v: solo errores en stderr (WARNING level)
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
# Timeout de 120 segundos por llamada al LLM (y por step)
architect run "PROMPT" --timeout 120

# Tareas largas: aumentar timeout
architect run "analiza todo el código fuente del repositorio" -a resume --timeout 300

# Tareas rápidas en CI: timeout corto para fallar pronto
architect run "resume README" -a resume --timeout 30
```

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

## 16. Uso en scripts y pipes

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

## 17. CI/CD: GitHub Actions, GitLab, cron

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

## 18. Multi-proyecto: workspace y config por proyecto

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

## 19. Agentes custom en YAML

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

## 20. Comandos auxiliares

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

---

## 21. Referencia rápida de flags

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
  --timeout N               Timeout en segundos por llamada al LLM

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
```
