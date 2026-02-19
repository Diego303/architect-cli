# Formas de uso — architect CLI

Guía práctica de uso real: desde el caso más simple hasta configuraciones avanzadas para CI/CD, múltiples proyectos y equipos. Incluye todos los flags, combinaciones de logging, archivos de configuración y patrones de automatización.

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
12. [Uso en scripts y pipes](#12-uso-en-scripts-y-pipes)
13. [CI/CD: GitHub Actions, GitLab, cron](#13-cicd-github-actions-gitlab-cron)
14. [Multi-proyecto: workspace y config por proyecto](#14-multi-proyecto-workspace-y-config-por-proyecto)
15. [Agentes custom en YAML](#15-agentes-custom-en-yaml)
16. [Comandos auxiliares](#16-comandos-auxiliares)
17. [Referencia rápida de flags](#17-referencia-rápida-de-flags)

---

## 1. Instalación y setup inicial

```bash
# Clonar e instalar (modo editable)
git clone https://github.com/tu-usuario/architect-cli
cd architect-cli
pip install -e .

# Verificar instalación
architect --version   # architect, version 0.8.0
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
    {"name": "list_files", "success": true},
    {"name": "read_file",  "success": true}
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
[INFO] agent.tool_call.execute  tool=read_file path=src/main.py
[INFO] agent.tool_call.complete tool=read_file success=True chars=1243
[INFO] agent.step.start  step=2
[INFO] agent.complete     status=success steps=2
```

Ejemplo adicional con `-vv` (incluye todo lo de `-v` más):
```
[DEBUG] llm.completion.start  model=gpt-4o-mini messages=3 tools=4
[DEBUG] tool.execute.args     tool=write_file path=src/utils.py content="def foo():..."
[DEBUG] tool.execute.result   output="Archivo sobrescrito (234 bytes)"
```

### `--log-level` — nivel base del logger

```bash
# Solo errores (más restrictivo)
architect run "PROMPT" --log-level error

# Debug completo (equivalente a -vvv, pero sin --verbose count)
architect run "PROMPT" --log-level debug

# Combinado con -v (verbose controla la consola, log-level el base)
architect run "PROMPT" --log-level debug -v
```

### `--log-file` — guardar logs en archivo JSON

```bash
# Guardar logs en archivo JSON Lines (además de mostrar en consola)
architect run "PROMPT" -a build -v --log-file logs/session.jsonl

# El archivo captura DEBUG completo independientemente del verbose de consola
# (consola con -v = INFO, archivo = DEBUG siempre)
architect run "PROMPT" --log-file logs/session.jsonl     # consola quiet, archivo DEBUG

# Analizar los logs después
cat logs/session.jsonl | jq 'select(.event == "tool.call")'
cat logs/session.jsonl | jq 'select(.level == "error")'
cat logs/session.jsonl | jq -r '.event + " " + (.step | tostring)' 2>/dev/null
cat logs/session.jsonl | jq '.duration_ms' | awk '{sum+=$1} END {print sum "ms total"}'
```

Formato de cada línea del archivo `.jsonl`:
```json
{"timestamp": "2026-02-19T10:30:45.123456Z", "level": "info", "logger": "architect.core.loop", "event": "agent.step.start", "step": 1, "agent": "build"}
{"timestamp": "2026-02-19T10:30:46.891234Z", "level": "debug", "logger": "architect.tools.filesystem", "event": "tool.execute", "tool": "read_file", "path": "src/main.py", "chars": 1243}
```

---

## 7. Uso sin logs (silencioso)

Para scripts, pipes y automatización donde solo importa el resultado.

```bash
# Resultado limpio en stdout, sin ningún log en stderr
architect run "resume el proyecto en 3 líneas" -a resume --quiet

# Resultado a archivo, errores a /dev/null
architect run "genera README.md" -a build --quiet 2>/dev/null

# Resultado a archivo, errores a log
architect run "genera README.md" -a build --quiet 2>errors.log

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

# Together AI
architect run "PROMPT" --model together_ai/meta-llama/Llama-3-70b-chat-hf
```

### API key inline (no recomendado, mejor usar env var)

```bash
architect run "PROMPT" --api-key sk-...
# La key se pasa directamente a LiteLLM; NO se loggea
```

### API base custom (LiteLLM Proxy, endpoints propios)

```bash
# LiteLLM Proxy (equipo compartido)
architect run "PROMPT" --api-base http://proxy.interno:8000

# Endpoint compatible con OpenAI (local o cloud)
architect run "PROMPT" --model gpt-4o --api-base https://mi-openai-compatible.com/v1
```

### Timeout

```bash
# Timeout de 120 segundos por llamada al LLM (y por step)
architect run "PROMPT" --timeout 120

# Tareas largas: aumentar timeout
architect run "analiza todo el código fuente del repositorio" -a resume --timeout 300

# Tareas rápidas en CI: timeout corto para fallar pronto
architect run "resume README" -a resume --timeout 30
```

### Desactivar streaming

```bash
# --no-stream: espera respuesta completa (sin chunks en tiempo real)
architect run "PROMPT" --no-stream

# Útil cuando el terminal no soporta streaming o en tests
architect run "PROMPT" --no-stream --log-file debug.jsonl
```

---

## 9. Archivos de configuración

### Cuáles existen y para qué

```
config.example.yaml       ← plantilla completa con comentarios (no editar)
config.yaml               ← tu configuración local (gitignoreado habitualmente)
ci/architect.yaml         ← config específica para CI/CD
config/dev.yaml           ← config para desarrollo local
config/prod.yaml          ← config para producción
```

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

### `config.yaml` de desarrollo (con verbose)

```yaml
llm:
  model: gpt-4o-mini        # modelo económico para desarrollo
  api_key_env: LITELLM_API_KEY
  timeout: 60
  retries: 1                # menos reintentos en desarrollo (falla rápido)
  stream: true

workspace:
  root: .
  allow_delete: false       # prevenir borrados accidentales

logging:
  level: debug
  verbose: 2                # -vv por defecto
  file: logs/dev.jsonl      # guardar todos los logs

agents:
  build:
    confirm_mode: confirm-sensitive   # confirmar escrituras
    max_steps: 10                     # limitar para no gastar tokens
```

### `config.yaml` para producción / automatización

```yaml
llm:
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
  timeout: 120
  retries: 3                # más reintentos en producción
  stream: false             # sin streaming en pipelines

workspace:
  root: /ruta/al/proyecto
  allow_delete: false

logging:
  level: warn
  verbose: 0                # mínimo ruido
  file: /var/log/architect/run.jsonl

agents:
  build:
    confirm_mode: yolo      # sin confirmaciones en pipelines
    max_steps: 30
```

### `config.yaml` con Ollama local (sin API key)

```yaml
llm:
  model: ollama/llama3
  api_base: http://localhost:11434
  retries: 0
  timeout: 300              # modelos locales pueden ser lentos
  stream: true

workspace:
  root: .
  allow_delete: false

logging:
  verbose: 1
```

### Usar `-c` para especificar el archivo

```bash
# Config por defecto (busca config.yaml en CWD si existe; sino, usa defaults)
architect run "PROMPT"

# Config explícita
architect run "PROMPT" -c config.yaml
architect run "PROMPT" -c /etc/architect/prod.yaml
architect run "PROMPT" -c ~/configs/architect-dev.yaml

# Config + overrides de CLI (CLI siempre gana)
architect run "PROMPT" -c config.yaml --model gpt-4o --mode yolo
```

### Validar antes de usar

```bash
architect validate-config -c config.yaml
# Salida: "Configuración válida: model=gpt-4o-mini, workspace=., ..."
# Exit 0 si válida, exit 1 si inválida, exit 3 si archivo no encontrado
```

---

## 10. Configuraciones por entorno

### Variables de entorno como override

```bash
# Cambiar modelo sin tocar el YAML
ARCHITECT_MODEL=gpt-4o architect run "PROMPT"

# Cambiar workspace
ARCHITECT_WORKSPACE=/otro/proyecto architect run "PROMPT"

# Cambiar log level
ARCHITECT_LOG_LEVEL=debug architect run "PROMPT"

# Cambiar API base
ARCHITECT_API_BASE=http://proxy:8000 architect run "PROMPT"
```

### Múltiples configs con alias en shell

```bash
# En ~/.bashrc o ~/.zshrc

# Alias para desarrollo
alias architect-dev='architect -c ~/configs/architect-dev.yaml'

# Alias para producción (requiere confirmar todo)
alias architect-prod='architect -c ~/configs/architect-prod.yaml --mode confirm-all'

# Alias para análisis rápido (sin confirmaciones, modelo barato)
alias aresume='architect run -a resume --mode yolo --quiet'
alias areview='architect run -a review --mode yolo'

# Uso
aresume "explica este proyecto"
areview "revisa src/auth.py"
architect-dev run "refactoriza config.py" -a build
```

### `.envrc` con direnv (por proyecto)

```bash
# .envrc en la raíz del proyecto
export LITELLM_API_KEY="sk-..."
export ARCHITECT_MODEL="gpt-4o-mini"
export ARCHITECT_WORKSPACE="$(pwd)"
```

```bash
direnv allow   # activa .envrc automáticamente al entrar al directorio
architect run "analiza el proyecto" -a resume   # usa modelo y workspace del .envrc
```

---

## 11. MCP: herramientas remotas

MCP (Model Context Protocol) permite al agente usar tools en servidores remotos.

### Configuración en `config.yaml`

```yaml
mcp:
  servers:
    - name: github
      url: http://localhost:3001
      token_env: GITHUB_TOKEN

    - name: database
      url: https://mcp.empresa.com/db
      token_env: DB_MCP_TOKEN

    - name: jira
      url: http://jira-mcp:3002
      token_env: JIRA_TOKEN
```

```bash
# Las tools MCP se descubren automáticamente y están disponibles como locales
architect run "crea un PR con los cambios actuales" --mode yolo

# Deshabilitar MCP (ignorar servidores de config)
architect run "PROMPT" --disable-mcp

# Ver qué tools MCP hay disponibles (salen en --agents con config)
architect agents -c config.yaml
```

Las tools MCP reciben el nombre `mcp_{servidor}_{nombre_tool}`. Si el servidor `github` expone una tool `create_pr`, el agente la ve como `mcp_github_create_pr`.

---

## 12. Uso en scripts y pipes

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
  2)   echo "Completado parcialmente" ;;
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

# Generar tests
architect run "genera tests unitarios para src/utils.py usando pytest" \
  -a build --mode yolo --quiet > tests/test_utils.py
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
```

---

## 13. CI/CD: GitHub Actions, GitLab, cron

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

      - name: Run architect
        env:
          LITELLM_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          architect run "revisa los cambios del último commit y detecta posibles bugs" \
            -a review \
            --mode yolo \
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
  file: logs/ci-run.jsonl  # guardar logs para artifacts
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
# /etc/cron.d/architect-review
# Análisis semanal del proyecto los domingos a las 23:00
0 23 * * 0 deploy-user /usr/local/bin/architect-review.sh >> /var/log/architect-cron.log 2>&1
```

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
  --quiet \
  --json \
  --log-file "$LOG_FILE" \
  -c ci/architect.yaml \
  > "reports/review-${FECHA}.json"

STATUS=$(cat "reports/review-${FECHA}.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
echo "[$(date)] Review completado: status=$STATUS log=$LOG_FILE"
```

---

## 14. Multi-proyecto: workspace y config por proyecto

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

```
mi-proyecto/
├── architect.yaml      ← config específica del proyecto
├── config.example.yaml ← plantilla (opcional, copiada de architect-cli)
├── .gitignore          ← incluye architect.yaml si tiene tokens
└── src/
```

```yaml
# mi-proyecto/architect.yaml
llm:
  model: claude-sonnet-4-6      # este proyecto usa Claude
  api_key_env: ANTHROPIC_API_KEY
  timeout: 90

workspace:
  root: .
  allow_delete: true            # este proyecto permite borrado

agents:
  build:
    max_steps: 30               # tareas largas

  # Agente especializado para este proyecto
  migrator:
    system_prompt: |
      Eres un experto en migrar este proyecto de Python 2 a Python 3.
      Conoces las diferencias entre print statements, unicode handling, etc.
    allowed_tools:
      - read_file
      - write_file
      - list_files
    confirm_mode: confirm-sensitive
    max_steps: 50
```

```bash
# Desde dentro del proyecto
architect run "migra auth.py a Python 3" -a migrator -c architect.yaml
```

---

## 15. Agentes custom en YAML

### Definir y usar un agente custom completo

```yaml
# config.yaml
agents:
  # Agente de deployment
  deploy:
    system_prompt: |
      Eres un agente de deployment especializado.

      Tu trabajo es preparar el código para producción:
      1. Verifica que existan tests
      2. Revisa la configuración de producción
      3. Lee CI/CD files para entender el pipeline
      4. Genera un reporte ANTES de hacer cualquier cambio

      NUNCA modifiques archivos de producción sin haber generado el reporte primero.
    allowed_tools:
      - read_file
      - list_files
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
      - Principio de mínimo privilegio

      Genera un reporte priorizado: CRÍTICO > ALTO > MEDIO > BAJO.
    allowed_tools:
      - read_file
      - list_files
    confirm_mode: yolo
    max_steps: 25
```

```bash
# Usar agentes custom
architect run "prepara el release 1.2.0" -a deploy -c config.yaml
architect run "documenta el módulo de autenticación" -a documenter -c config.yaml
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

## 16. Comandos auxiliares

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

# Archivo no encontrado
architect validate-config -c no-existe.yaml
# Exit 3

# Config con error (campo desconocido, tipo incorrecto, etc.)
architect validate-config -c config-invalida.yaml
# → "Error de configuración: llm.retries debe ser int, recibido 'dos'"
# Exit 1
```

---

## 17. Referencia rápida de flags

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
```

### Combinaciones más comunes

```bash
# Análisis rápido (sin confirmar nada)
architect run "PROMPT" -a resume --quiet

# Revisión de código con detalle
architect run "PROMPT" -a review -v

# Tarea automatizada (CI/scripts)
architect run "PROMPT" --mode yolo --quiet --json

# Debug completo de una ejecución
architect run "PROMPT" -a build -vvv --log-file debug.jsonl --no-stream

# Simulación antes de ejecutar
architect run "PROMPT" -a build --dry-run -v

# Con modelo específico y timeout largo
architect run "PROMPT" -a build --model gpt-4o --timeout 300 --mode yolo

# Proyecto externo con config propia
architect run "PROMPT" -a build -w /ruta/proyecto -c /ruta/proyecto/architect.yaml
```
