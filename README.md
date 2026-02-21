# architect

Herramienta CLI headless y agéntica para orquestar agentes de IA sobre archivos locales y servicios MCP remotos. Diseñada para funcionar sin supervisión en CI, cron y pipelines.

---

## Instalación

**Requisitos**: Python 3.12+

```bash
# Desde el repositorio
git clone https://github.com/tu-usuario/architect-cli
cd architect-cli
pip install -e .

# Verificar instalación
architect --version
architect run --help
```

**Dependencias principales**: `litellm`, `click`, `pydantic`, `httpx`, `structlog`, `tenacity`

---

## Quickstart

```bash
# Configurar API key
export LITELLM_API_KEY="sk-..."

# Analizar un proyecto (solo lectura, seguro)
architect run "resume qué hace este proyecto" -a resume

# Revisar código
architect run "revisa main.py y encuentra problemas" -a review

# Generar un plan detallado (sin modificar archivos)
architect run "planifica cómo añadir tests al proyecto" -a plan

# Modificar archivos — build planifica y ejecuta en un solo paso
architect run "añade docstrings a todas las funciones de utils.py"

# Ejecutar sin confirmaciones (CI/automatización)
architect run "genera un archivo README.md para este proyecto" --mode yolo

# Ver qué haría sin ejecutar nada
architect run "reorganiza la estructura de carpetas" --dry-run

# Limitar tiempo total de ejecución
architect run "refactoriza el módulo de auth" --timeout 300
```

---

## Comandos

### `architect run` — ejecutar tarea

```
architect run PROMPT [opciones]
```

**Argumento**:
- `PROMPT` — Descripción de la tarea en lenguaje natural

**Opciones principales**:

| Opción | Descripción |
|--------|-------------|
| `-c, --config PATH` | Archivo de configuración YAML |
| `-a, --agent NAME` | Agente a usar: `plan`, `build`, `resume`, `review`, o custom |
| `-m, --mode MODE` | Modo de confirmación: `confirm-all`, `confirm-sensitive`, `yolo` |
| `-w, --workspace PATH` | Directorio de trabajo (workspace root) |
| `--dry-run` | Simular ejecución sin cambios reales |

**Opciones LLM**:

| Opción | Descripción |
|--------|-------------|
| `--model MODEL` | Modelo a usar (`gpt-4o`, `claude-sonnet-4-6`, etc.) |
| `--api-base URL` | URL base de la API |
| `--api-key KEY` | API key directa |
| `--no-stream` | Desactivar streaming |
| `--timeout N` | Tiempo máximo total de ejecución en segundos (watchdog global) |

**Opciones de output**:

| Opción | Descripción |
|--------|-------------|
| `-v / -vv / -vvv` | Nivel de verbose técnico (sin `-v` solo se muestran los pasos del agente) |
| `--log-level LEVEL` | Nivel de log: `human` (default), `debug`, `info`, `warn`, `error` |
| `--log-file PATH` | Guardar logs JSON estructurados en archivo |
| `--json` | Salida en formato JSON (compatible con `jq`) |
| `--quiet` | Modo silencioso (solo resultado final en stdout) |
| `--max-steps N` | Límite máximo de pasos del agente |
| `--budget N` | Límite de coste en USD (detiene el agente si se supera) |

**Opciones de evaluación**:

| Opción | Descripción |
|--------|-------------|
| `--self-eval off\|basic\|full` | Auto-evaluación del resultado: `off` (sin coste extra), `basic` (una llamada extra, marca como `partial` si falla), `full` (reintenta con prompt de corrección hasta `max_retries` veces) |

**Opciones MCP**:

| Opción | Descripción |
|--------|-------------|
| `--disable-mcp` | Desactivar conexión a servidores MCP |

---

### `architect agents` — listar agentes

```bash
architect agents                   # agentes por defecto
architect agents -c config.yaml   # incluye custom del YAML
```

Lista todos los agentes disponibles con su modo de confirmación.

---

### `architect validate-config` — validar configuración

```bash
architect validate-config -c config.yaml
```

Valida la sintaxis y los valores del archivo de configuración antes de ejecutar.

---

## Agentes

Un agente define el **rol**, las **tools disponibles** y el **nivel de confirmación**.

El agente por defecto es **`build`** (se usa automáticamente si no se especifica `-a`): analiza el proyecto, elabora un plan interno y lo ejecuta en un solo paso, sin necesitar un agente `plan` previo.

| Agente | Descripción | Tools | Confirmación | Pasos |
|--------|-------------|-------|-------------|-------|
| `build` | Planifica y ejecuta modificaciones | todas (edición, búsqueda, lectura, `run_command`) | `confirm-sensitive` | 50 |
| `plan` | Analiza y genera un plan detallado | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 20 |
| `resume` | Lee y resume información | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 15 |
| `review` | Revisión de código y mejoras | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 20 |

**Agentes custom** en `config.yaml`:

```yaml
agents:
  deploy:
    system_prompt: |
      Eres un agente de deployment...
    allowed_tools:
      - read_file
      - list_files
      - run_command
    confirm_mode: confirm-all
    max_steps: 10
```

---

## Modos de confirmación

| Modo | Comportamiento |
|------|---------------|
| `confirm-all` | Toda acción requiere confirmación interactiva |
| `confirm-sensitive` | Solo acciones que modifican el sistema (write, delete) |
| `yolo` | Ejecución completamente automática (para CI/scripts) |

> En entornos sin TTY (`--mode confirm-sensitive` en CI), el sistema lanza un error claro. Usa `--mode yolo` o `--dry-run` en pipelines.

---

## Configuración

Copia `config.example.yaml` como punto de partida:

```bash
cp config.example.yaml config.yaml
```

Estructura mínima:

```yaml
llm:
  model: gpt-4o-mini          # o claude-sonnet-4-6, ollama/llama3, etc.
  api_key_env: LITELLM_API_KEY
  timeout: 60
  retries: 2
  stream: true

workspace:
  root: .
  allow_delete: false

logging:
  level: human                 # human (default), debug, info, warn, error
  verbose: 0
```

### Variables de entorno

| Variable | Equivalente config | Descripción |
|----------|--------------------|-------------|
| `LITELLM_API_KEY` | `llm.api_key_env` | API key del proveedor LLM |
| `ARCHITECT_MODEL` | `llm.model` | Modelo LLM |
| `ARCHITECT_API_BASE` | `llm.api_base` | URL base de la API |
| `ARCHITECT_LOG_LEVEL` | `logging.level` | Nivel de logging |
| `ARCHITECT_WORKSPACE` | `workspace.root` | Directorio de trabajo |

---

## Salida y códigos de salida

**Separación stdout/stderr**:
- Streaming del LLM → **stderr** (no rompe pipes)
- Logs y progreso → **stderr**
- Resultado final del agente → **stdout**
- `--json` output → **stdout**

```bash
# Parsear resultado con jq
architect run "resume el proyecto" --quiet --json | jq .status

# Capturar resultado, ver logs
architect run "analiza main.py" -v 2>logs.txt

# Solo resultado (sin logs)
architect run "genera README" --quiet --mode yolo
```

**Códigos de salida**:

| Código | Significado |
|--------|-------------|
| `0` | Éxito (`success`) |
| `1` | Fallo del agente (`failed`) |
| `2` | Parcial — hizo algo pero no completó (`partial`) |
| `3` | Error de configuración |
| `4` | Error de autenticación LLM |
| `5` | Timeout |
| `130` | Interrumpido (Ctrl+C) |

---

## Formato JSON (`--json`)

```bash
architect run "analiza el proyecto" -a review --quiet --json
```

```json
{
  "status": "success",
  "stop_reason": null,
  "output": "El proyecto consiste en...",
  "steps": 3,
  "tools_used": [
    {"name": "list_files", "success": true},
    {"name": "read_file", "path": "src/main.py", "success": true}
  ],
  "duration_seconds": 8.5,
  "model": "gpt-4o-mini",
  "costs": {"total_usd": 0.0023, "prompt_tokens": 4200, "completion_tokens": 380}
}
```

**`stop_reason`**: indica por qué terminó el agente. `null` = terminó naturalmente. Otros valores: `max_steps`, `timeout`, `budget_exceeded`, `context_full`, `user_interrupt`, `llm_error`.

Cuando un watchdog activa (`max_steps`, `timeout`, etc.), el agente recibe una instrucción de cierre y hace una última llamada al LLM para resumir qué completó y qué queda pendiente antes de terminar.

---

## Logging

Por defecto, architect muestra los pasos del agente en un formato legible con iconos:

```
🔄 Paso 1 → Llamada al LLM (6 mensajes)
   ✓ LLM respondió con 2 tool calls

   🔧 read_file → src/main.py
      ✓ OK

   🔧 edit_file → src/main.py (3→5 líneas)
      ✓ OK
      🔍 Hook ruff: ✓

🔄 Paso 2 → Llamada al LLM (10 mensajes)
   ✓ LLM respondió con texto final

✅ Agente completado (2 pasos)
   Razón: LLM decidió que terminó
   Coste: $0.0042
```

Las tools MCP se distinguen visualmente: `🌐 mcp_github_search → query (MCP: github)`

```bash
# Solo pasos legibles (default — nivel HUMAN)
architect run "..."

# Nivel HUMAN + logs técnicos por step
architect run "..." -v

# Detalle completo (args, respuestas LLM)
architect run "..." -vv

# Todo (HTTP, payloads)
architect run "..." -vvv

# Sin logs (resultado solo)
architect run "..." --quiet

# Logs a archivo JSON + consola
architect run "..." -v --log-file logs/session.jsonl

# Analizar logs después
cat logs/session.jsonl | jq 'select(.event == "tool.call")'
```

**Pipelines de logging independientes**:
- **HUMAN** (stderr, default): pasos, tool calls, hooks — formato legible con iconos, sin ruido técnico
- **Técnico** (stderr, con `-v`): debug de LLM, tokens, retries — excluye mensajes HUMAN
- **JSON file** (archivo, con `--log-file`): todos los eventos estructurados

Ver [`docs/logging.md`](docs/logging.md) para detalles de la arquitectura de logging.

---

## Post-Edit Hooks

Los hooks se ejecutan automáticamente después de cada operación de edición (`edit_file`, `write_file`, `apply_patch`). El resultado se añade al contexto del agente para que pueda corregir errores.

```yaml
hooks:
  post_edit:
    - name: ruff
      command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
      timeout: 15

    - name: mypy
      command: "mypy {file} --ignore-missing-imports"
      file_patterns: ["*.py"]
      timeout: 30

    - name: prettier
      command: "prettier --write {file}"
      file_patterns: ["*.ts", "*.tsx", "*.json"]
      timeout: 10
```

- `{file}` se reemplaza por el path del archivo editado
- También disponible como variable de entorno `ARCHITECT_EDITED_FILE`
- Un hook que falla (exit code != 0) devuelve su output al LLM como feedback

---

## Control de costes

```yaml
costs:
  budget_usd: 2.0         # Detiene el agente si supera $2
  warn_at_usd: 1.5        # Avisa en logs al llegar a $1.5
```

```bash
# Límite de presupuesto por CLI
architect run "..." --budget 1.0
```

El coste acumulado aparece en el output `--json` bajo `costs`. Cuando se supera el presupuesto, el agente recibe una instrucción de cierre y hace un último resumen antes de terminar (`stop_reason: "budget_exceeded"`).

---

## MCP (Model Context Protocol)

Conecta architect a herramientas remotas vía HTTP:

```yaml
mcp:
  servers:
    - name: github
      url: http://localhost:3001
      token_env: GITHUB_TOKEN

    - name: database
      url: https://mcp.example.com/db
      token_env: DB_TOKEN
```

Las tools MCP se descubren automáticamente al iniciar y son indistinguibles de las tools locales para el agente. Si un servidor no está disponible, el agente continúa sin esas tools.

```bash
# Con MCP
architect run "abre un PR con los cambios" --mode yolo

# Sin MCP
architect run "analiza el proyecto" --disable-mcp
```

---

## Uso en CI/CD

```yaml
# GitHub Actions
- name: Refactorizar código
  run: |
    architect run "actualiza los imports obsoletos en src/" \
      --mode yolo \
      --quiet \
      --json \
      --budget 3.0 \
      -c ci/architect.yaml \
    | tee result.json

- name: Verificar resultado
  run: |
    STATUS=$(cat result.json | jq -r .status)
    if [ "$STATUS" != "success" ]; then
      echo "architect falló con status: $STATUS ($(cat result.json | jq -r .stop_reason))"
      exit 1
    fi
```

```yaml
# config para CI (ci/architect.yaml)
llm:
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  retries: 3
  timeout: 120

workspace:
  root: .

logging:
  level: human
  verbose: 0

hooks:
  post_edit:
    - name: lint
      command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
```

---

## Seguridad

- **Path traversal**: todas las operaciones de archivos están confinadas al `workspace.root`. Intentos de acceder a `../../etc/passwd` son bloqueados.
- **delete_file** requiere `workspace.allow_delete: true` explícito en config.
- **run_command**: lista de comandos bloqueados (`rm -rf`, `dd`, `mkfs`, etc.) y whitelist de comandos de desarrollo seguros. El directorio de trabajo está siempre confinado al workspace.
- **Tools MCP** son marcadas como sensibles por defecto (requieren confirmación en `confirm-sensitive`).
- **API keys** nunca se loggean, solo el nombre de la variable de entorno.

---

## Proveedores LLM soportados

Cualquier proveedor soportado por [LiteLLM](https://docs.litellm.ai/docs/providers):

```bash
# OpenAI
LITELLM_API_KEY=sk-... architect run "..." --model gpt-4o

# Anthropic
LITELLM_API_KEY=sk-ant-... architect run "..." --model claude-sonnet-4-6

# Google Gemini
LITELLM_API_KEY=... architect run "..." --model gemini/gemini-2.0-flash

# Ollama (local, sin API key)
architect run "..." --model ollama/llama3 --api-base http://localhost:11434

# LiteLLM Proxy (para equipos)
architect run "..." --api-base http://proxy.internal:8000
```

---

## Arquitectura

```
architect run PROMPT
    │
    ├── load_config()          YAML + env vars + CLI flags
    ├── configure_logging()    3 pipelines: HUMAN + técnico + JSON file
    ├── ToolRegistry           tools locales (fs, edición, búsqueda, run_command) + MCP remotas
    ├── RepoIndexer            árbol del workspace → inyectado en system prompt
    ├── LLMAdapter             LiteLLM con retries selectivos + prompt caching
    ├── ContextManager         pruning: compress + enforce_window + is_critically_full
    ├── PostEditHooks          lint/test automático post-edición
    ├── CostTracker            coste acumulado + watchdog de presupuesto
    │
    └── AgentLoop (while True — el LLM decide cuándo parar)
            │
            ├── _check_safety_nets()   max_steps / budget / timeout / context_full
            │       └── si salta → _graceful_close(): última LLM call sin tools
            │                         el agente resume qué hizo y qué queda pendiente
            ├── context_manager.manage()     compress + enforce_window si necesario
            ├── llm.completion()             → streaming chunks a stderr
            ├── si no hay tool_calls         → LLM_DONE, fin natural
            ├── engine.execute_tool_calls()  → paralelo si posible → confirmar → ejecutar
            ├── engine.run_post_edit_hooks() → lint/test → feedback al LLM si falla
            └── repetir
```

**Razones de parada** (`stop_reason` en el output JSON):

| Razón | Descripción |
|-------|-------------|
| `null` / `llm_done` | El LLM decidió que terminó (terminación natural) |
| `max_steps` | Watchdog: límite de pasos alcanzado |
| `budget_exceeded` | Watchdog: límite de coste superado |
| `context_full` | Watchdog: context window lleno (>95%) |
| `timeout` | Watchdog: tiempo total excedido |
| `user_interrupt` | El usuario hizo Ctrl+C / SIGTERM (corte inmediato) |
| `llm_error` | Error irrecuperable del LLM |

**Decisiones de diseño**:
- Sync-first (predecible, debuggable; el loop principal es ~300 líneas sin magia)
- Sin LangChain/LangGraph (el loop es directo y controlado)
- Pydantic v2 como fuente de verdad para schemas y validación
- Errores de tools devueltos al LLM como resultado (no rompen el loop)
- stdout limpio para pipes, todo lo demás a stderr
- Watchdogs piden cierre limpio — el agente nunca termina a mitad de frase

---

## Historial de versiones

| Versión | Funcionalidad |
|---------|---------------|
| v0.9.0 | **Edición incremental**: `edit_file` (str-replace exacto) y `apply_patch` (unified diff) |
| v0.10.0 | **Indexer + búsqueda**: árbol del repo en el system prompt, `search_code`, `grep`, `find_files` |
| v0.11.0 | **Context management**: truncado de tool results, compresión de pasos con LLM, hard limit, parallel tool calls |
| v0.12.0 | **Self-evaluation**: `--self-eval basic/full` evalúa y reintenta automáticamente |
| v0.13.0 | **`run_command`**: ejecución de comandos (tests, linters) con 4 capas de seguridad |
| v0.14.0 | **Cost tracking**: `CostTracker`, `--budget`, prompt caching, `LocalLLMCache` |
| v0.15.0 | **v3-core** — rediseño del núcleo: `while True` loop, safety nets con cierre limpio, `PostEditHooks`, nivel de log HUMAN, `StopReason`, `ContextManager.manage()` |
| v0.15.2 | **Human logging con iconos** — formato visual alineado con plan v3: 🔄🔧🌐✅⚡❌📦🔍, distinción MCP, eventos nuevos (`llm_response`), coste en completado |
| v0.15.3 | **Fix pipeline structlog** — human logging funciona sin `--log-file`; `wrap_for_formatter` siempre activo |
