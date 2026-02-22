# Referencia de configuración

## Sistema de capas

La configuración se resuelve en 4 capas (menor a mayor prioridad):

```
1. Defaults de Pydantic (código)
        ↓
2. Archivo YAML (-c config.yaml)
        ↓
3. Variables de entorno (ARCHITECT_*)
        ↓
4. Flags de CLI (--model, --workspace, etc.)
```

El `deep_merge()` de `config/loader.py` combina las capas de forma recursiva: los dicts anidados se fusionan en lugar de reemplazarse. Así puedes sobreescribir `llm.model` desde CLI sin perder `llm.timeout` del YAML.

---

## Variables de entorno

| Variable | Campo de config | Ejemplo |
|----------|-----------------|---------|
| `LITELLM_API_KEY` | Leída por LiteLLM directamente (no por architect) | `sk-...` |
| `ARCHITECT_MODEL` | `llm.model` | `gpt-4o` |
| `ARCHITECT_API_BASE` | `llm.api_base` | `http://localhost:8000` |
| `ARCHITECT_LOG_LEVEL` | `logging.level` | `debug` |
| `ARCHITECT_WORKSPACE` | `workspace.root` | `/home/user/project` |

`LITELLM_API_KEY` es la API key por defecto. Si necesitas una variable diferente, configura `llm.api_key_env` en el YAML.

---

## Flags de CLI que sobreescriben config

| Flag | Campo sobrescrito |
|------|-------------------|
| `--model MODEL` | `llm.model` |
| `--api-base URL` | `llm.api_base` |
| `--api-key KEY` | `llm.api_key_env` → key directa |
| `--timeout N` | Timeout total de sesión (watchdog). **No** sobreescribe `llm.timeout` (per-request) |
| `--no-stream` | `llm.stream = False` |
| `--workspace PATH` | `workspace.root` |
| `--max-steps N` | `agent_config.max_steps` |
| `--mode MODE` | `agent_config.confirm_mode` |
| `-v / -vv / -vvv` | `logging.verbose` (count) |
| `--log-level LEVEL` | `logging.level` |
| `--log-file PATH` | `logging.file` |
| `--self-eval MODE` | `evaluation.mode` (off/basic/full) |
| `--allow-commands` | `commands.enabled = True` |
| `--no-commands` | `commands.enabled = False` |
| `--budget FLOAT` | `costs.budget_usd` |
| `--cache` | `llm_cache.enabled = True` |
| `--no-cache` | `llm_cache.enabled = False` |

---

## Schema YAML completo

```yaml
# ==============================================================================
# LLM
# ==============================================================================
llm:
  provider: litellm        # siempre "litellm"
  mode: direct             # "direct" | "proxy" (LiteLLM Proxy Server)
  model: gpt-4o-mini       # cualquier modelo LiteLLM

  # api_base: http://localhost:8000   # custom endpoint (Proxy, Ollama, etc.)

  api_key_env: LITELLM_API_KEY       # env var con la API key

  timeout: 60              # segundos por llamada al LLM
  retries: 2               # reintentos en errores transitorios (no auth)
  stream: true             # streaming por defecto; desactivado con --no-stream/--json/--quiet
  prompt_caching: false    # marca system prompt con cache_control → ahorro 50-90% en Anthropic/OpenAI

# ==============================================================================
# Agentes (custom o overrides de defaults)
# ==============================================================================
agents:
  # Override parcial de un default:
  build:
    confirm_mode: confirm-all    # solo sobreescribe este campo
    max_steps: 10

  # Agente completamente nuevo:
  deploy:
    system_prompt: |
      Eres un agente de deployment especializado.
      ...
    allowed_tools:
      - read_file
      - list_files
      - write_file
    confirm_mode: confirm-all
    max_steps: 15

# ==============================================================================
# Logging
# ==============================================================================
logging:
  level: human             # "debug" | "info" | "human" | "warn" | "error"
                           # v3: "human" muestra la trazabilidad del agente
  verbose: 0               # 0=solo human logs, 1=info, 2=debug, 3+=all
  # file: logs/architect.jsonl   # JSON Lines; DEBUG completo siempre

# ==============================================================================
# Workspace
# ==============================================================================
workspace:
  root: .                  # directorio raíz; todas las ops de archivos confinadas aquí
  allow_delete: false      # true = habilitar delete_file tool

# ==============================================================================
# MCP (Model Context Protocol — herramientas remotas)
# ==============================================================================
mcp:
  servers:
    - name: github
      url: http://localhost:3001
      token_env: GITHUB_TOKEN         # env var con Bearer token

    - name: database
      url: https://mcp.example.com/db
      token_env: DB_TOKEN

    # token inline (no recomendado en producción):
    # - name: internal
    #   url: http://internal:8080
    #   token: "hardcoded-token"

# ==============================================================================
# Indexer — árbol del repositorio en el system prompt (F10)
# ==============================================================================
indexer:
  enabled: true            # false = sin árbol en el prompt; las search tools siguen disponibles
  max_file_size: 1000000   # bytes; archivos más grandes se omiten del índice
  exclude_dirs: []         # dirs adicionales a excluir (además de .git, node_modules, etc.)
  # exclude_dirs:
  #   - vendor
  #   - .terraform
  exclude_patterns: []     # patrones adicionales a excluir (además de *.pyc, *.min.js, etc.)
  # exclude_patterns:
  #   - "*.generated.py"
  #   - "*.pb.go"
  use_cache: true          # caché del índice en disco, TTL de 5 minutos

# ==============================================================================
# Context — gestión del context window (F11)
# ==============================================================================
context:
  # Nivel 1: truncar tool results largos
  max_tool_result_tokens: 2000   # ~4 chars/token; 0 = desactivar truncado

  # Nivel 2: comprimir pasos antiguos con el LLM
  summarize_after_steps: 8       # 0 = desactivar compresión
  keep_recent_steps: 4           # pasos recientes a preservar íntegros

  # Nivel 3: hard limit del context window total
  max_context_tokens: 80000      # 0 = sin límite (peligroso para tareas largas)
  # Referencia: gpt-4o/mini → 80000, claude-sonnet-4-6 → 150000

  # Tool calls paralelas
  parallel_tools: true           # false = siempre secuencial

# ==============================================================================
# Evaluation — auto-evaluación del resultado (F12)
# ==============================================================================
evaluation:
  mode: off                # "off" | "basic" | "full"
                           # Override desde CLI: --self-eval basic|full
  max_retries: 2           # reintentos en modo "full" (rango: 1-5)
  confidence_threshold: 0.8  # umbral de confianza para aceptar resultado (0.0-1.0)

# ==============================================================================
# Commands — ejecución de comandos del sistema (F13)
# ==============================================================================
commands:
  enabled: true            # false = no registrar run_command; --allow-commands/--no-commands
  default_timeout: 30      # segundos por defecto (1-600)
  max_output_lines: 200    # líneas de stdout/stderr antes de truncar (10-5000)
  blocked_patterns: []     # regexes extra a bloquear (además de los built-in)
  # blocked_patterns:
  #   - "git push --force"
  #   - "docker rm"
  safe_commands: []        # comandos adicionales clasificados como 'safe'
  allowed_only: false      # si true, solo safe/dev; dangerous rechazados en execute()

# ==============================================================================
# Costs — seguimiento de costes de llamadas al LLM (F14)
# ==============================================================================
costs:
  enabled: true            # false = sin tracking de costes
  # prices_file: my_prices.json  # precios custom (mismo formato que default_prices.json)
  # budget_usd: 1.0        # detener si se superan $1.00; Override: --budget 1.0
  # warn_at_usd: 0.5       # log warning al alcanzar $0.50

# ==============================================================================
# LLM Cache — cache local de respuestas LLM para desarrollo (F14)
# ==============================================================================
llm_cache:
  enabled: false           # true = activar; Override: --cache / --no-cache
  dir: ~/.architect/cache  # directorio donde guardar las entradas
  ttl_hours: 24            # validez de cada entrada (1-8760 horas)

# ==============================================================================
# Hooks — lifecycle completo (v4-A1, retrocompat v3-M4)
# ==============================================================================
hooks:
  # Pre-hooks: se ejecutan ANTES de la acción. Exit code 2 = BLOCK.
  pre_tool_use:
    - name: validate-secrets
      command: "bash scripts/check-secrets.sh"
      matcher: "write_file|edit_file"      # regex para filtrar tools
      file_patterns: ["*.py", "*.env"]
      timeout: 5

  # Post-hooks: se ejecutan DESPUÉS de la acción.
  post_tool_use:
    - name: python-lint
      command: "ruff check {file} --no-fix"    # {file} se reemplaza con el path editado
      file_patterns: ["*.py"]                    # patrones glob
      timeout: 15                                # segundos (1-300, default: 10)
      enabled: true                              # false = ignorar este hook
    - name: python-typecheck
      command: "mypy {file} --no-error-summary"
      file_patterns: ["*.py"]
      timeout: 30

  # Hooks de sesión (notificación, no pueden bloquear)
  session_start: []
  session_end: []
  on_error: []
  agent_complete: []
  budget_warning: []
  context_compress: []

  # Pre/post LLM call
  pre_llm_call: []
  post_llm_call: []

  # Retrocompatibilidad v3-M4: post_edit se mapea a post_tool_use
  # con matcher automático para edit_file/write_file/apply_patch
  post_edit:
    - name: legacy-lint
      command: "ruff check {file}"
      file_patterns: ["*.py"]
      timeout: 15

  # Campos de cada hook:
  # name:          str           — nombre descriptivo
  # command:       str           — comando shell ({file} se reemplaza)
  # matcher:       str = "*"    — regex/glob para filtrar tools
  # file_patterns: list[str]    — patrones glob para filtrar archivos
  # timeout:       int = 10     — segundos (1-300)
  # async:         bool = false — true = ejecutar en background sin bloquear
  # enabled:       bool = true  — false = ignorar

# ==============================================================================
# Guardrails — seguridad determinista (v4-A2)
# ==============================================================================
guardrails:
  enabled: false              # true = activar guardrails
  protected_files: []         # globs: [".env", "*.pem", "secrets/**"]
  blocked_commands: []        # regexes: ["git push --force", "docker rm"]
  max_files_modified: null    # límite de archivos distintos por sesión (null = sin límite)
  max_lines_changed: null     # límite de líneas cambiadas acumuladas
  max_commands_executed: null  # límite de comandos ejecutados
  require_test_after_edit: false  # forzar test cada N ediciones

  code_rules: []              # reglas de análisis estático simple
  # - pattern: "eval\\("
  #   message: "Uso de eval() detectado"
  #   severity: block          # block | warn

  quality_gates: []           # verificación final al completar
  # - name: tests
  #   command: "pytest tests/ -x"
  #   required: true           # true = bloquea si falla
  #   timeout: 120

# ==============================================================================
# Skills — contexto de proyecto y workflows (v4-A3)
# ==============================================================================
skills:
  auto_discover: true         # descubrir skills en .architect/skills/ automáticamente
  inject_by_glob: true        # inyectar skills según archivos activos

# ==============================================================================
# Memory — memoria procedural (v4-A4)
# ==============================================================================
memory:
  enabled: false              # true = activar detección de correcciones
  auto_detect_corrections: true  # detectar correcciones automáticamente en mensajes del usuario
```

---

## Función `load_config()`

```python
def load_config(
    config_path: Path | None = None,
    cli_args: dict | None = None,
) -> AppConfig:
    # 1. Carga YAML (vacío si config_path=None)
    yaml_dict = load_yaml_config(config_path)

    # 2. Lee env vars ARCHITECT_*
    env_dict = load_env_overrides()

    # 3. Fusiona: yaml ← env
    merged = deep_merge(yaml_dict, env_dict)

    # 4. Aplica CLI flags
    if cli_args:
        merged = apply_cli_overrides(merged, cli_args)

    # 5. Valida con Pydantic (extra="forbid")
    return AppConfig(**merged)
```

Si el YAML tiene claves desconocidas, Pydantic lanza `ValidationError` → CLI muestra el error y sale con código 3 (EXIT_CONFIG_ERROR).

---

## Ejemplos de configuraciones comunes

### Mínima (solo API key en env)

```bash
export LITELLM_API_KEY=sk-...
architect run "analiza el proyecto" -a resume
```

### OpenAI con config explícita

```yaml
llm:
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
  timeout: 120
  retries: 3

workspace:
  root: /mi/proyecto
  allow_delete: false
```

### Anthropic Claude

```yaml
llm:
  model: claude-sonnet-4-6
  api_key_env: ANTHROPIC_API_KEY
  stream: true

context:
  max_context_tokens: 150000   # Claude tiene ventana más grande
```

### Ollama (local, sin API key)

```yaml
llm:
  model: ollama/llama3
  api_base: http://localhost:11434
  retries: 0    # local, sin necesidad de reintentos
  timeout: 300  # modelos locales pueden ser lentos

context:
  parallel_tools: false   # sin paralelismo en modelos locales lentos
```

### LiteLLM Proxy (equipos)

```yaml
llm:
  mode: proxy
  model: gpt-4o-mini
  api_base: http://proxy.interno:8000
  api_key_env: LITELLM_PROXY_KEY
```

### CI/CD (modo yolo, sin confirmaciones, con evaluación)

```yaml
llm:
  model: gpt-4o-mini
  timeout: 120
  retries: 3
  stream: false

workspace:
  root: .

logging:
  verbose: 0
  level: warn

evaluation:
  mode: basic              # evalúa el resultado en CI
  confidence_threshold: 0.7  # menos estricto que en interactivo
```

```bash
architect run "actualiza imports obsoletos en src/" \
  --mode yolo --quiet --json \
  -c ci/architect.yaml
```

### Repos grandes (con optimización de contexto)

```yaml
indexer:
  exclude_dirs:
    - vendor
    - .terraform
    - coverage
  exclude_patterns:
    - "*.generated.py"
    - "*.pb.go"
  use_cache: true

context:
  max_tool_result_tokens: 1000   # más agresivo en repos grandes
  summarize_after_steps: 5       # comprimir más rápido
  keep_recent_steps: 3
  max_context_tokens: 60000      # más conservador
  parallel_tools: true
```

### Con ejecución de comandos (F13) y costes (F14)

```yaml
llm:
  model: claude-sonnet-4-6
  api_key_env: ANTHROPIC_API_KEY
  prompt_caching: true     # ahorra tokens en llamadas repetidas al mismo system prompt

commands:
  enabled: true
  default_timeout: 60
  max_output_lines: 200
  safe_commands:
    - "pnpm test"
    - "cargo check"

costs:
  enabled: true
  budget_usd: 2.0          # máximo $2 por ejecución
  warn_at_usd: 1.0         # aviso al alcanzar $1

# Cache local para desarrollo: evita llamadas repetidas al LLM
llm_cache:
  enabled: false           # activar con --cache en CLI durante desarrollo
  ttl_hours: 24
```

```bash
# Con cache local activo y presupuesto desde CLI
architect run "PROMPT" -a build --cache --budget 1.5 --show-costs
```

### Con hooks del lifecycle (v4-A1)

```yaml
hooks:
  post_tool_use:
    - name: python-lint
      command: "ruff check {file} --no-fix"
      file_patterns: ["*.py"]
      timeout: 15
    - name: python-typecheck
      command: "mypy {file} --no-error-summary"
      file_patterns: ["*.py"]
      timeout: 30
  pre_tool_use:
    - name: no-secrets
      command: "bash scripts/check-secrets.sh"
      matcher: "write_file|edit_file"
      timeout: 5
```

```bash
# Los hooks se ejecutan automaticamente — el LLM ve el output de lint/typecheck
# y puede auto-corregir errores. Pre-hooks pueden bloquear acciones.
architect run "refactoriza utils.py" -a build --mode yolo -c config.yaml
```

### Con guardrails (v4-A2)

```yaml
guardrails:
  enabled: true
  protected_files: [".env", "*.pem", "deploy/**"]
  blocked_commands: ["git push", "docker rm"]
  max_files_modified: 10
  max_lines_changed: 500
  require_test_after_edit: true
  code_rules:
    - pattern: "eval\\("
      message: "No usar eval()"
      severity: block
  quality_gates:
    - name: tests
      command: "pytest tests/ -x"
      required: true
      timeout: 120
```

### Con skills y memoria (v4-A3/A4)

```yaml
skills:
  auto_discover: true
  inject_by_glob: true

memory:
  enabled: true
  auto_detect_corrections: true
```

### Config completa con self-eval

```yaml
llm:
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
  timeout: 120

workspace:
  root: .

indexer:
  enabled: true
  use_cache: true

context:
  max_tool_result_tokens: 2000
  summarize_after_steps: 8
  max_context_tokens: 80000
  parallel_tools: true

evaluation:
  mode: full               # reintentar automáticamente si falla
  max_retries: 2
  confidence_threshold: 0.85
```

```bash
# O usar solo el flag de CLI (ignora evaluation.mode del YAML)
architect run "genera tests para src/auth.py" -a build --self-eval full
```
