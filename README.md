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

# Planificar una tarea
architect run "planifica cómo añadir tests al proyecto" -a plan

# Modificar archivos (con confirmación)
architect run "añade docstrings a todas las funciones de utils.py" -a build

# Modo mixto automático (plan → build)
architect run "refactoriza el módulo de config para usar dataclasses"

# Ejecutar sin confirmaciones (CI/automatización)
architect run "genera un archivo README.md para este proyecto" --mode yolo

# Ver qué haría sin ejecutar nada
architect run "reorganiza la estructura de carpetas" --dry-run
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
| `--timeout N` | Timeout en segundos (también aplica como timeout por step) |

**Opciones de output**:

| Opción | Descripción |
|--------|-------------|
| `-v / -vv / -vvv` | Nivel de verbose (más `-v` = más detalle) |
| `--log-level LEVEL` | Nivel de log: `debug`, `info`, `warn`, `error` |
| `--log-file PATH` | Guardar logs JSON estructurados en archivo |
| `--json` | Salida en formato JSON (compatible con `jq`) |
| `--quiet` | Modo silencioso (solo resultado final en stdout) |
| `--max-steps N` | Límite máximo de pasos del agente |

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

Un agente define el **rol**, las **tools disponibles** y el **nivel de confirmación**:

| Agente | Descripción | Tools | Confirmación |
|--------|-------------|-------|-------------|
| `plan` | Analiza y genera un plan detallado | `read_file`, `list_files` | `confirm-all` |
| `build` | Crea y modifica archivos | todas | `confirm-sensitive` |
| `resume` | Lee y resume información | `read_file`, `list_files` | `yolo` |
| `review` | Revisión de código y mejoras | `read_file`, `list_files` | `yolo` |

**Modo mixto** (sin `-a`): ejecuta `plan → build` automáticamente. El plan generado se inyecta como contexto al agente build.

**Agentes custom** en `config.yaml`:

```yaml
agents:
  deploy:
    system_prompt: |
      Eres un agente de deployment...
    allowed_tools:
      - read_file
      - list_files
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
  verbose: 1
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
  "output": "El proyecto consiste en...",
  "steps": 3,
  "tools_used": [
    {"name": "list_files", "success": true},
    {"name": "read_file", "path": "src/main.py", "success": true}
  ],
  "duration_seconds": 8.5,
  "model": "gpt-4o-mini"
}
```

---

## Logging

```bash
# Sin logs (resultado solo)
architect run "..." --quiet

# Pasos y tool calls
architect run "..." -v

# Detalle completo (args, respuestas LLM)
architect run "..." -vv

# Todo (HTTP, payloads)
architect run "..." -vvv

# Logs a archivo JSON + consola
architect run "..." -v --log-file logs/session.jsonl

# Analizar logs después
cat logs/session.jsonl | jq 'select(.event == "tool.call")'
```

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
      -c ci/architect.yaml \
    | tee result.json

- name: Verificar resultado
  run: |
    STATUS=$(cat result.json | jq -r .status)
    if [ "$STATUS" != "success" ]; then
      echo "architect falló con status: $STATUS"
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
  verbose: 0
```

---

## Seguridad

- **Path traversal**: todas las operaciones de archivos están confinadas al `workspace.root`. Intentos de acceder a `../../etc/passwd` son bloqueados.
- **delete_file** requiere `workspace.allow_delete: true` explícito en config.
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
    ├── configure_logging()    stderr dual-pipeline (consola + JSON)
    ├── ToolRegistry           tools locales + MCP remotas
    ├── LLMAdapter             LiteLLM con retries selectivos
    │
    └── AgentLoop (o MixedModeRunner)
            │
            ├── [check shutdown]    SIGINT/SIGTERM graceful
            ├── [StepTimeout]       SIGALRM por step
            ├── llm.completion()    → streaming chunks a stderr
            ├── engine.execute()    → validar → confirmar → ejecutar
            └── ctx.append_results() → siguiente iteración
```

**Decisiones de diseño**:
- Sync-first (predecible, debuggable)
- Sin LangChain/LangGraph (el loop es simple, ~150 líneas)
- Pydantic como fuente de verdad para schemas y validación
- Errores de tools devueltos al LLM como resultado (no rompen el loop)
- stdout limpio para pipes, todo lo demás a stderr

---

## Extensiones futuras

- Persistencia de estado (reanudar ejecuciones parciales)
- Multi-agente (agentes que delegan en otros)
- Plugin system (tools desde paquetes Python externos)
- Prompt caching para desarrollo
- Métricas: tokens usados, coste estimado, duración por step
