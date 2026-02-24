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

**Opciones de output y reportes**:

| Opción | Descripción |
|--------|-------------|
| `-v / -vv / -vvv` | Nivel de verbose técnico (sin `-v` solo se muestran los pasos del agente) |
| `--log-level LEVEL` | Nivel de log: `human` (default), `debug`, `info`, `warn`, `error` |
| `--log-file PATH` | Guardar logs JSON estructurados en archivo |
| `--json` | Salida en formato JSON (compatible con `jq`) |
| `--quiet` | Modo silencioso (solo resultado final en stdout) |
| `--max-steps N` | Límite máximo de pasos del agente |
| `--budget N` | Límite de coste en USD (detiene el agente si se supera) |
| `--report FORMAT` | Genera reporte de ejecución: `json`, `markdown`, `github` |
| `--report-file PATH` | Guarda el reporte en archivo en vez de stdout |

**Opciones de sesiones y CI/CD**:

| Opción | Descripción |
|--------|-------------|
| `--session ID` | Reanuda una sesión guardada previamente |
| `--confirm-mode MODE` | Alias CI-friendly: `yolo`, `confirm-sensitive`, `confirm-all` |
| `--context-git-diff REF` | Inyecta `git diff REF` como contexto (ej: `origin/main`) |
| `--exit-code-on-partial N` | Exit code personalizado para status `partial` (default: 2) |

**Opciones de evaluación**:

| Opción | Descripción |
|--------|-------------|
| `--self-eval off\|basic\|full` | Auto-evaluación del resultado: `off` (sin coste extra), `basic` (una llamada extra, marca como `partial` si falla), `full` (reintenta con prompt de corrección hasta `max_retries` veces) |

**Opciones MCP**:

| Opción | Descripción |
|--------|-------------|
| `--disable-mcp` | Desactivar conexión a servidores MCP |

---

### `architect sessions` — listar sesiones guardadas

```bash
architect sessions
```

Muestra una tabla con todas las sesiones guardadas: ID, status, pasos, coste y tarea.

---

### `architect resume` — reanudar sesión

```bash
architect resume SESSION_ID [opciones]
```

Reanuda una sesión interrumpida. Carga el estado completo (mensajes, archivos modificados, coste acumulado) y continúa donde se dejó. Si el ID no existe, termina con exit code 3.

---

### `architect cleanup` — limpiar sesiones antiguas

```bash
architect cleanup                  # elimina sesiones > 7 días
architect cleanup --older-than 30  # elimina sesiones > 30 días
```

---

### `architect loop` — iteración automática (Ralph Loop)

```
architect loop PROMPT --check CMD [opciones]
```

Ejecuta un agente en bucle hasta que todos los checks (comandos shell) pasen. Cada iteración recibe un contexto limpio: solo la spec original, el diff acumulado, errores de la iteración anterior, y un progress.md auto-generado.

```bash
# Loop hasta que tests y lint pasen
architect loop "implementa la feature X" \
  --check "pytest tests/" \
  --check "ruff check src/" \
  --max-iterations 10 \
  --max-cost 5.0

# Con spec file y worktree aislado
architect loop "refactoriza el módulo auth" \
  --spec spec.md \
  --check "pytest" \
  --worktree \
  --model gpt-4o
```

| Opción | Descripción |
|--------|-------------|
| `--check CMD` | Comando de verificación (repetible, requerido) |
| `--spec PATH` | Archivo de especificación (se usa en vez del prompt) |
| `--max-iterations N` | Máximo de iteraciones (default: 25) |
| `--max-cost N` | Límite de coste en USD |
| `--max-time N` | Límite de tiempo en segundos |
| `--completion-tag TAG` | Tag que el agente emite al terminar (default: `COMPLETE`) |
| `--agent NAME` | Agente a usar (default: `build`) |
| `--model MODEL` | Modelo LLM |
| `--worktree` | Ejecutar en un git worktree aislado |
| `--quiet` | Solo resultado final |

---

### `architect pipeline` — ejecutar workflow YAML

```
architect pipeline FILE [opciones]
```

Ejecuta un workflow multi-step definido en YAML. Cada paso puede tener su propio agente, modelo, checks, condiciones y variables.

```bash
# Ejecutar pipeline
architect pipeline ci/pipeline.yaml --var project=myapp --var env=staging

# Ver plan sin ejecutar
architect pipeline ci/pipeline.yaml --dry-run

# Reanudar desde un step
architect pipeline ci/pipeline.yaml --from-step deploy
```

| Opción | Descripción |
|--------|-------------|
| `--var KEY=VALUE` | Variable para el pipeline (repetible) |
| `--from-step NAME` | Reanudar desde un step específico |
| `--dry-run` | Mostrar plan sin ejecutar |
| `-c, --config PATH` | Archivo de configuración YAML |
| `--quiet` | Solo resultado final |

**Formato del YAML de pipeline**:

```yaml
name: mi-pipeline
steps:
  - name: analyze
    agent: plan
    prompt: "Analiza el proyecto {{project}} en entorno {{env}}"
    output_var: analysis

  - name: implement
    agent: build
    prompt: "Implementa: {{analysis}}"
    model: gpt-4o
    checks:
      - "pytest tests/"
      - "ruff check src/"
    checkpoint: true

  - name: deploy
    agent: build
    prompt: "Deploy a {{env}}"
    condition: "env == 'production'"
```

---

### `architect parallel` — ejecución paralela

```
architect parallel --task CMD [opciones]
```

Ejecuta múltiples tareas en paralelo, cada una en un git worktree aislado.

```bash
# Tres tareas en paralelo
architect parallel \
  --task "añade tests a auth.py" \
  --task "añade tests a users.py" \
  --task "añade tests a billing.py" \
  --workers 3

# Con modelos diferentes por worker
architect parallel \
  --task "optimiza queries" \
  --task "mejora logging" \
  --models gpt-4o,claude-sonnet-4-6
```

| Opción | Descripción |
|--------|-------------|
| `--task CMD` | Tarea a ejecutar (repetible) |
| `--workers N` | Número de workers paralelos (default: 3) |
| `--models LIST` | Modelos separados por coma (round-robin entre workers) |
| `--agent NAME` | Agente a usar (default: `build`) |
| `--budget-per-worker N` | Límite de coste por worker |
| `--timeout-per-worker N` | Límite de tiempo por worker |
| `--quiet` | Solo resultado final |

```bash
# Limpiar worktrees después de ejecutar
architect parallel-cleanup
```

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
| `yolo` | Sin confirmaciones — ni tools ni comandos (para CI/scripts). La seguridad se garantiza por la blocklist de comandos destructivos |

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

## Hooks del Lifecycle

Sistema completo de hooks que se ejecutan en 10 puntos del lifecycle del agente. Permiten interceptar, bloquear o modificar operaciones.

```yaml
hooks:
  pre_tool_use:
    - command: "python scripts/validate_tool.py"
      matcher: "write_file|edit_file"
      timeout: 5

  post_tool_use:
    - command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
      timeout: 15
    - command: "mypy {file} --ignore-missing-imports"
      file_patterns: ["*.py"]
      timeout: 30

  session_start:
    - command: "echo 'Session started'"
      async: true

  agent_complete:
    - command: "python scripts/post_run.py"
```

**Eventos disponibles**: `pre_tool_use`, `post_tool_use`, `pre_llm_call`, `post_llm_call`, `session_start`, `session_end`, `on_error`, `budget_warning`, `context_compress`, `agent_complete`

**Protocolo de exit codes**:
- `0` = ALLOW (continuar; si stdout contiene JSON con `updatedInput`, se modifica el input)
- `2` = BLOCK (abortar la operación)
- Otro = error (warning en logs, se continúa)

**Variables de entorno** inyectadas: `ARCHITECT_EVENT`, `ARCHITECT_TOOL`, `ARCHITECT_WORKSPACE`, `ARCHITECT_FILE` (si aplica)

**Backward compatible**: la sección `post_edit` sigue funcionando y se mapea a `post_tool_use` con matcher de tools de edición.

---

## Guardrails

Capa de seguridad determinista evaluada **antes** que los hooks. No desactivable por el LLM.

```yaml
guardrails:
  protected_files:
    - "*.env"
    - "secrets/**"
    - ".git/**"
  blocked_commands:
    - "rm -rf /"
    - "DROP TABLE"
  max_files_per_session: 20
  max_lines_changed: 5000
  code_rules:
    - pattern: "TODO|FIXME"
      severity: warn
      message: "Código con TODOs pendientes"
    - pattern: "eval\\("
      severity: block
      message: "eval() no permitido"
  quality_gates:
    - name: tests
      command: "pytest --tb=short -q"
      required: true
    - name: lint
      command: "ruff check src/"
      required: false
```

**Quality gates**: se ejecutan cuando el agente declara completado. Si un gate `required` falla, el agente recibe feedback y sigue trabajando hasta que pase.

---

## Skills y .architect.md

El agente carga automáticamente contexto de proyecto desde `.architect.md`, `AGENTS.md` o `CLAUDE.md` en la raíz del workspace e inyecta su contenido en el system prompt.

**Skills especializadas** se descubren en `.architect/skills/` y `.architect/installed-skills/`:

```
.architect/
├── skills/
│   └── django/
│       └── SKILL.md        # frontmatter YAML + contenido
└── installed-skills/
    └── react-patterns/
        └── SKILL.md
```

Cada `SKILL.md` puede tener un frontmatter YAML con `globs` para activarse solo cuando los archivos relevantes están en juego:

```yaml
---
name: django
description: Patrones Django para el proyecto
globs: ["*.py", "*/models.py", "*/views.py"]
---
# Instrucciones para Django
Usa class-based views siempre que sea posible...
```

```bash
# Gestión de skills
architect skill list
architect skill create mi-skill
architect skill install github-user/repo/path/to/skill
architect skill remove mi-skill
```

---

## Memoria Procedural

El agente detecta correcciones del usuario y las persiste entre sesiones en `.architect/memory.md`.

```yaml
memory:
  enabled: true
  auto_detect_corrections: true
```

Cuando el usuario corrige al agente (ej. "no uses print, usa logging"), el patrón se guarda y se inyecta en futuras sesiones como contexto adicional en el system prompt.

El archivo `.architect/memory.md` es editable manualmente y sigue el formato:
```
- [2026-02-22] correction: No usar print(), usar logging
- [2026-02-22] pattern: Siempre ejecutar tests después de editar
```

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

El coste acumulado aparece en el output `--json` bajo `costs` y con `--show-costs` al final de la ejecución (funciona tanto en modo streaming como sin streaming). Cuando se supera el presupuesto, el agente recibe una instrucción de cierre y hace un último resumen antes de terminar (`stop_reason: "budget_exceeded"`).

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

Las tools MCP se descubren automáticamente al iniciar y se inyectan en el `allowed_tools` del agente activo (no necesitas listarlas en la config del agente). Son indistinguibles de las tools locales para el LLM. Si un servidor no está disponible, el agente continúa sin esas tools.

```bash
# Con MCP
architect run "abre un PR con los cambios" --mode yolo

# Sin MCP
architect run "analiza el proyecto" --disable-mcp
```

---

## Sesiones y Resume

El agente guarda su estado automáticamente después de cada paso. Si una ejecución se interrumpe (Ctrl+C, timeout, error), puedes reanudarla:

```bash
# Ejecutar una tarea larga
architect run "refactoriza todo el módulo de auth" --budget 5.0
# → Interrumpido por timeout o Ctrl+C

# Ver sesiones guardadas
architect sessions
# ID                     Status       Steps  Cost    Task
# 20260223-143022-a1b2   interrupted  12     $1.23   refactoriza todo el módulo de auth

# Reanudar donde se quedó
architect resume 20260223-143022-a1b2

# Limpiar sesiones antiguas
architect cleanup --older-than 7
```

Las sesiones se guardan en `.architect/sessions/` como archivos JSON. Mensajes largos (>50) se truncan automáticamente a los últimos 30 para mantener el tamaño manejable.

---

## Reportes de ejecución

Genera reportes detallados de lo que hizo el agente, en tres formatos:

```bash
# Reporte JSON (ideal para CI/CD)
architect run "añade tests" --mode yolo --report json

# Reporte Markdown (para documentación)
architect run "refactoriza utils" --mode yolo --report markdown --report-file report.md

# Comentario GitHub PR (con secciones collapsible)
architect run "revisa los cambios" --mode yolo --report github --report-file pr-comment.md
```

El reporte incluye: resumen (tarea, agente, modelo, status, duración, pasos, coste), archivos modificados con líneas añadidas/eliminadas, quality gates ejecutados, errores encontrados, timeline de cada paso y git diff.

---

## Ralph Loop (Iteración Automática)

El Ralph Loop ejecuta un agente iterativamente hasta que todos los checks pasen. Cada iteración usa un **contexto limpio** — el agente recibe solamente:

1. La spec original (archivo o prompt)
2. El diff acumulado de todas las iteraciones anteriores
3. Los errores de checks de la iteración anterior
4. Un `progress.md` auto-generado con el historial

```bash
# Iterar hasta que tests y lint pasen
architect loop "implementa autenticación JWT" \
  --check "pytest tests/test_auth.py" \
  --check "ruff check src/auth/" \
  --max-iterations 5 \
  --max-cost 3.0

# Con spec file detallado
architect loop "implementar según spec" \
  --spec requirements/auth-spec.md \
  --check "pytest" \
  --worktree
```

**Safety nets**: El loop se detiene si se agotan las iteraciones (`max_iterations`), el coste (`max_cost`) o el tiempo (`max_time`). El resultado indica el motivo de parada.

**Worktree**: Con `--worktree`, el loop ejecuta en un git worktree aislado. Si todos los checks pasan, el resultado incluye la ruta al worktree para inspección o merge.

---

## Pipeline Mode (Workflows Multi-Step)

Los pipelines definen workflows secuenciales donde cada paso puede tener su propio agente, modelo, checks y configuración.

**Características**:
- **Variables**: `{{nombre}}` en prompts, sustituidas desde `--var` o desde `output_var` de steps anteriores
- **Condiciones**: `condition` evalúa una expresión; el step se salta si es falsa
- **Output variables**: `output_var` captura la salida de un step como variable para los siguientes
- **Checks**: comandos shell post-step que verifican el resultado
- **Checkpoints**: `checkpoint: true` crea un git commit automático al completar el step
- **Resume**: `--from-step` permite reanudar un pipeline desde un step específico
- **Dry-run**: `--dry-run` muestra el plan sin ejecutar agentes

```yaml
# pipeline.yaml
name: feature-pipeline
steps:
  - name: plan
    agent: plan
    prompt: "Planifica cómo implementar {{feature}}"
    output_var: plan_output

  - name: implement
    agent: build
    prompt: "Ejecuta este plan: {{plan_output}}"
    model: gpt-4o
    checks:
      - "pytest tests/ -q"
    checkpoint: true

  - name: review
    agent: review
    prompt: "Revisa la implementación de {{feature}}"
    condition: "run_review == 'true'"
```

```bash
architect pipeline pipeline.yaml \
  --var feature="user auth" \
  --var run_review=true
```

---

## Ejecución Paralela

Ejecuta múltiples tareas en paralelo, cada una en un git worktree aislado con `ProcessPoolExecutor`.

```bash
architect parallel \
  --task "añade tests unitarios a auth.py" \
  --task "añade tests unitarios a users.py" \
  --task "añade tests unitarios a billing.py" \
  --workers 3 \
  --budget-per-worker 2.0
```

Cada worker:
- Se ejecuta en un git worktree independiente (aislamiento total)
- Puede usar un modelo diferente (con `--models` se asignan round-robin)
- Tiene su propio budget y timeout
- El resultado incluye archivos modificados, coste, duración y ruta al worktree

```bash
# Limpiar worktrees después
architect parallel-cleanup
```

---

## Checkpoints y Rollback

Los checkpoints son git commits con prefijo especial (`architect:checkpoint`) que permiten restaurar el workspace a un punto anterior. Se crean automáticamente en pipelines (con `checkpoint: true`) y pueden usarse en el Ralph Loop.

```bash
# Los checkpoints se crean automáticamente en pipelines con checkpoint: true
# Para ver checkpoints creados:
git log --oneline --grep="architect:checkpoint"
```

El `CheckpointManager` permite:
- **Crear** checkpoints (stage all + commit con prefijo)
- **Listar** checkpoints existentes parseando `git log`
- **Rollback** a un checkpoint específico (por step o commit hash)
- **Verificar** si hay cambios desde un checkpoint

---

## Auto-Review

Después de una ejecución de build, un reviewer con **contexto limpio** puede inspeccionar los cambios. El reviewer recibe solo el diff y la tarea original — sin historial del builder — y tiene acceso exclusivo a tools de lectura.

```yaml
# Activar auto-review en config
auto_review:
  enabled: true
  model: gpt-4o
```

El reviewer busca:
- Bugs y errores lógicos
- Problemas de seguridad
- Violaciones de convenciones del proyecto
- Mejoras de rendimiento o legibilidad
- Tests faltantes

Si encuentra issues, genera un prompt de corrección que puede alimentar al builder para un fix-pass.

---

## Uso en CI/CD

### Ejemplo básico — GitHub Actions

```yaml
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

### Ejemplo avanzado — con reportes, dry-run y git diff

```yaml
- name: Dry run primero (ver qué haría)
  run: |
    architect run "añade docstrings a todas las funciones" \
      --dry-run \
      --confirm-mode yolo \
      --json

- name: Ejecutar con contexto del PR
  run: |
    architect run "revisa y mejora los cambios de este PR" \
      --confirm-mode yolo \
      --context-git-diff origin/main \
      --report github \
      --report-file pr-report.md \
      --budget 5.0 \
      --timeout 600 \
      --exit-code-on-partial 0

- name: Comentar en PR
  if: always()
  run: gh pr comment $PR_NUMBER --body-file pr-report.md
```

### Config para CI

```yaml
# ci/architect.yaml
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
- **run_command**: blocklist de comandos destructivos (`rm -rf /`, `sudo`, `dd`, `mkfs`, `curl|bash`, etc.) activa siempre, independientemente del modo de confirmación. Clasificación dinámica (safe/dev/dangerous) para políticas de confirmación en modos `confirm-sensitive` y `confirm-all`. El directorio de trabajo está siempre confinado al workspace.
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
    ├── HookExecutor           10 eventos del lifecycle, exit code protocol
    ├── GuardrailsEngine       seguridad determinista (before hooks)
    ├── SkillsLoader           .architect.md + skills por glob
    ├── ProceduralMemory       correcciones del usuario entre sesiones
    ├── CostTracker            coste acumulado + watchdog de presupuesto
    ├── SessionManager         persistencia de sesiones (save/load/resume)
    ├── DryRunTracker          registro de acciones sin ejecutar (--dry-run)
    ├── CheckpointManager      git commits con rollback (architect:checkpoint)
    │
    ├── RalphLoop              iteración automática hasta que checks pasen
    │       └── agent_factory() → AgentLoop fresco por iteración (contexto limpio)
    ├── PipelineRunner         workflows YAML multi-step con variables/condiciones
    │       └── agent_factory() → AgentLoop fresco por step
    ├── ParallelRunner         ejecución paralela en git worktrees aislados
    │       └── ProcessPoolExecutor → workers con `architect run` en worktrees
    ├── AutoReviewer           review post-build con contexto limpio (solo diff + tarea)
    │
    └── AgentLoop (while True — el LLM decide cuándo parar)
            │
            ├── _check_safety_nets()   max_steps / budget / timeout / context_full
            │       └── si salta → _graceful_close(): última LLM call sin tools
            │                         el agente resume qué hizo y qué queda pendiente
            ├── context_manager.manage()     compress + enforce_window si necesario
            ├── hooks: pre_llm_call          → interceptar antes de LLM
            ├── llm.completion()             → streaming chunks a stderr
            ├── hooks: post_llm_call         → interceptar después de LLM
            ├── si no hay tool_calls         → LLM_DONE, fin natural
            ├── guardrails.check()           → seguridad determinista (antes de hooks)
            ├── hooks: pre_tool_use          → ALLOW / BLOCK / MODIFY
            ├── engine.execute_tool_calls()  → paralelo si posible → confirmar → ejecutar
            ├── hooks: post_tool_use         → lint/test → feedback al LLM si falla
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
| v0.16.0 | **v4 Phase A** — hooks lifecycle (10 eventos, exit code protocol), guardrails deterministas, skills ecosystem (.architect.md), memoria procedural |
| v0.16.1 | **QA Phase A** — 228 verificaciones, 5 bugs corregidos (ToolResult import, CostTracker.total, YAML off, schema shadowing), 24 scripts alineados |
| v0.16.2 | **QA2** — `--show-costs` funciona con streaming, `--mode yolo` nunca pide confirmación (ni para `dangerous`), `--timeout` es watchdog de sesión (no sobreescribe `llm.timeout`), MCP tools auto-inyectadas en `allowed_tools`, `get_schemas` defensivo |
| v0.17.0 | **v4 Phase B** — sesiones persistentes con resume, reportes multi-formato (JSON/Markdown/GitHub PR), 10 flags CI/CD nativos (`--dry-run`, `--report`, `--session`, `--context-git-diff`, `--confirm-mode`, `--exit-code-on-partial`), dry-run/preview mode, 3 nuevos comandos (`sessions`, `resume`, `cleanup`) |
| v0.18.0 | **v4 Phase C** — Ralph Loop (iteración automática con checks), Pipeline Mode (workflows YAML multi-step con variables, condiciones, checkpoints), ejecución paralela en worktrees git, checkpoints con rollback, auto-review post-build con contexto limpio, 4 nuevos comandos (`loop`, `pipeline`, `parallel`, `parallel-cleanup`) |
