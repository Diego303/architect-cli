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
| `--timeout N` | `llm.timeout` (también se usa como `step_timeout`) |
| `--no-stream` | `llm.stream = False` |
| `--workspace PATH` | `workspace.root` |
| `--max-steps N` | `agent_config.max_steps` |
| `--mode MODE` | `agent_config.confirm_mode` |
| `-v / -vv / -vvv` | `logging.verbose` (count) |
| `--log-level LEVEL` | `logging.level` |
| `--log-file PATH` | `logging.file` |
| `--self-eval MODE` | `evaluation.mode` (off/basic/full) |

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
  level: info              # "debug" | "info" | "warn" | "error"
  verbose: 0               # 0=warn, 1=info, 2=debug, 3+=all (equiv. -v, -vv, -vvv)
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
