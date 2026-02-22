# Guía Rápida — Architect CLI

Instalación, configuración mínima y los comandos más útiles para el día a día.

---

## Instalación

```bash
git clone -b main --single-branch https://github.com/Diego303/architect-cli.git
cd architect-cli && pip install -e .

# Verificar
architect --version
```

---

## Configuración mínima

### API key directa (OpenAI, Anthropic, etc.)

```bash
export LITELLM_API_KEY="sk-..."
```

### Con LiteLLM Proxy (equipos)

Crea un `config.yaml`:

```yaml
llm:
  mode: proxy
  model: gpt-4o
  api_base: http://litellm-proxy:8000
  api_key_env: LITELLM_API_KEY
  prompt_caching: true
```

```bash
architect run "tu tarea" -c config.yaml
```

### Cambiar modelo sin config

```bash
# Via env var
export ARCHITECT_MODEL="claude-sonnet-4-6"

# O via flag
architect run "..." --model gpt-4o-mini
```

---

## Agentes disponibles

| Agente | Qué hace | Modifica archivos |
|--------|----------|-------------------|
| `build` | Implementa código (default) | Sí |
| `plan` | Analiza y planifica sin tocar nada | No |
| `review` | Revisa código y da feedback | No |
| `resume` | Resume y sintetiza información | No |

```bash
architect run "..." -a plan      # Solo planificar
architect run "..." -a review    # Solo revisar
architect run "..."              # build por defecto
```

---

## Ejemplos de uso

### Desarrollo con feedback visual (modo interactivo)

El modo por defecto: streaming + logs humanos en stderr. El agente pide confirmación antes de escribir archivos.

```bash
architect run "añade validación de email a user.py con tests"
```

Verás en tiempo real lo que hace el agente:
```
─── architect · build · gpt-4o ─────────────────

🔄 Step 1 — Llamada al LLM
🔧 search_code("email.*valid", file_pattern="*.py")
🔧 read_file("src/user.py")
🔄 Step 2 — Llamada al LLM
🔧 edit_file("src/user.py", ...)     ← Te pide confirmación
🔧 write_file("tests/test_user.py")  ← Te pide confirmación
✅ Completado

─── Resultado ──────────────────────────────────

Estado: success | Steps: 3 | Tool calls: 5
```

### Desarrollo autónomo (modo yolo)

Sin confirmaciones. Ideal para tareas donde confías en el agente.

```bash
architect run "refactoriza utils.py para usar dataclasses" --mode yolo
```

### Desarrollo con ejecución de tests

Permite que el agente ejecute comandos (pytest, linters) para verificar su trabajo.

```bash
architect run \
  "corrige el bug en parser.py y ejecuta pytest para verificar" \
  --mode yolo --allow-commands
```

### Desarrollo con auto-verificación completa

El agente implementa, verifica con hooks, y se auto-evalúa al final.

```bash
architect run \
  "implementa un endpoint GET /health con test" \
  --mode yolo --allow-commands --self-eval basic
```

### Review de código

```bash
architect run \
  "revisa src/auth/ en busca de bugs, vulnerabilidades y code smells" \
  -a review
```

### Explorar un proyecto desconocido

```bash
architect run "explica la arquitectura de este proyecto" -a resume
```

### Planificación sin ejecutar

```bash
architect run \
  "¿cómo implementarías autenticación JWT en este proyecto?" \
  -a plan
```

### Generar documentación

```bash
architect run \
  "añade docstrings Google Style a todas las funciones de src/services/" \
  --mode yolo
```

---

## Salida para scripts y CI

### JSON parseable

```bash
architect run "resume el proyecto" \
  --mode yolo --quiet --json | jq '.final_output'
```

### Logs a archivo + JSON a stdout

```bash
architect run "..." \
  --mode yolo --json --log-file debug.jsonl > result.json
```

### Exit codes

| Código | Significado |
|--------|-------------|
| 0 | Tarea completada |
| 1 | Falló |
| 2 | Parcial (budget/timeout/self-eval) |
| 3 | Error de configuración |
| 4 | Error de autenticación |
| 5 | Timeout |
| 130 | Interrumpido (Ctrl+C) |

---

## Control de costes

```bash
# Límite de gasto
architect run "..." --budget 0.50

# Ver resumen de costes
architect run "..." --show-costs

# Modelo barato para tareas simples
architect run "..." --model gpt-4o-mini
```

---

## Hooks del lifecycle (v4)

Hooks automáticos en 10 eventos. Los más comunes: lint después de editar y validación antes de escribir.

```yaml
# En config.yaml
hooks:
  post_tool_use:
    - name: lint
      command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
  pre_tool_use:
    - name: no-secrets
      command: "bash scripts/check-secrets.sh"
      matcher: "write_file|edit_file"
```

```bash
architect run "..." -c config.yaml --mode yolo
# Pre-hooks validan, post-hooks hacen lint automático
```

---

## Guardrails (v4)

Reglas deterministas de seguridad. Se evalúan ANTES que los hooks.

```yaml
guardrails:
  enabled: true
  protected_files: [".env", "*.pem"]
  max_files_modified: 10
  quality_gates:
    - name: tests
      command: "pytest tests/ -x"
      required: true
```

---

## Skills y memoria (v4)

Contexto del proyecto inyectado automáticamente en el system prompt.

```bash
# Crear .architect.md con convenciones del proyecto
# El agente lo lee automáticamente en cada sesión

# Gestión de skills
architect skill create mi-patron    # Crear skill local
architect skill install user/repo   # Instalar desde GitHub
architect skill list                # Listar skills
```

```yaml
# Activar memoria procedural (detecta correcciones y las recuerda)
memory:
  enabled: true
```

---

## Verbose y debugging

```bash
architect run "..." -v       # Info: workspace, modelo, streaming
architect run "..." -vv      # Debug: args completos, respuestas LLM
architect run "..." -vvv     # Full: HTTP, payloads, timing interno
```

---

## Referencia rápida de flags

```
architect run "PROMPT" [opciones]

Agentes y modos:
  -a, --agent NAME          build | plan | review | resume (default: build)
  -m, --mode MODE           yolo | confirm-sensitive | confirm-all
  --dry-run                 Simular sin cambios reales

LLM:
  --model MODEL             Override del modelo (gpt-4o, claude-sonnet-4-6, ...)
  --api-base URL            URL base de la API
  --api-key KEY             API key directa
  --no-stream               Desactivar streaming
  --timeout SECONDS         Timeout global

Output:
  --json                    Salida JSON estructurada a stdout
  --quiet                   Solo resultado, sin banner ni logs
  -v / -vv / -vvv           Verbosidad creciente

Costes:
  --budget USD              Límite de gasto por ejecución
  --show-costs              Mostrar resumen de costes

Ejecución:
  --allow-commands           Habilitar run_command
  --no-commands              Deshabilitar run_command
  --self-eval MODE           off | basic | full

Cache:
  --cache                   Activar cache local de LLM
  --no-cache                Desactivar cache
  --cache-clear             Limpiar cache antes de ejecutar

Config:
  -c, --config PATH         Archivo YAML de configuración
  -w, --workspace PATH      Directorio de trabajo
  --log-level LEVEL         debug | info | human | warn | error
  --log-file PATH           Archivo de logs JSON
```

---

## Ejemplo de config.yaml completa para desarrollo

```yaml
llm:
  model: gpt-4o
  stream: true
  prompt_caching: true

commands:
  enabled: true

hooks:
  post_tool_use:
    - name: lint
      command: "ruff check {file} --fix"
      file_patterns: ["*.py"]

guardrails:
  enabled: true
  protected_files: [".env"]
  quality_gates:
    - name: tests
      command: "pytest tests/ -x"
      required: true

skills:
  auto_discover: true

memory:
  enabled: true

costs:
  enabled: true
  budget_usd: 5.00
  warn_at_usd: 2.00
```

```bash
architect run "implementa feature X" -c config.yaml --mode yolo --show-costs
```
