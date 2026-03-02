# Troubleshooting y Diagnostico

Guia de resolucion de problemas para architect-cli v1.1.0. Organizada por sintomas: identifica el problema, diagnostica la causa y aplica la solucion concreta.

---

## Enfoque de diagnostico

Architect tiene tres fuentes principales de informacion para diagnosticar problemas:

1. **Output HUMAN** (stderr) -- el log visual con iconos que muestra lo que hace el agente paso a paso. Siempre activo excepto con `--quiet` o `--json`.
2. **Log JSON** (archivo) -- captura TODOS los eventos en formato JSON Lines. Se activa con `--log-file`. Es la herramienta mas potente para diagnostico.
3. **Console tecnico** (stderr) -- logs tecnicos controlados por `-v`/`-vv`/`-vvv`.

**Patron recomendado**: ante cualquier problema, reproduce con `--log-file` y usa `jq` para filtrar:

```bash
architect run "tarea" --log-file debug.jsonl -vv
cat debug.jsonl | jq 'select(.event == "agent.tool_call.execute")'
```

---

## 1. Errores de conexion y LLM

### 1.1 Error de autenticacion (exit code 4)

**Sintoma**: el agente termina inmediatamente con `exit code 4` y mensaje `Authentication failed` o `Invalid API key`.

**Causa**: la API key no esta configurada, es invalida o ha expirado.

**Solucion**:

```bash
# Verificar que la variable de entorno esta definida
echo $LITELLM_API_KEY

# O usar la key de OpenAI/Anthropic directamente
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Pasar por CLI (una sola ejecucion)
architect run "tarea" --api-key "sk-..."

# Verificar en config YAML que api_key_env apunta a la variable correcta
# .architect.yaml
llm:
  api_key_env: "OPENAI_API_KEY"  # nombre de la env var
```

Si usas un proxy o servidor local, verifica tambien `--api-base`.

### 1.2 Timeout en llamada al LLM

**Sintoma**: output HUMAN muestra `LLM error: timeout` (icono ❌) o el log JSON tiene `event: "agent.llm_error"` con error conteniendo "timeout" o "timed out".

> **Nota v1.1.0**: Los mensajes HUMAN ahora están en inglés por defecto. Con `language: es`, se muestran en español. Ver [`i18n.md`](i18n.md).

**Causa**: el timeout por defecto de LLM es 60 segundos (`llm.timeout: 60`). Modelos grandes o prompts muy largos pueden tardar mas. Conexion lenta al proveedor.

**Solucion**:

```yaml
# .architect.yaml
llm:
  timeout: 120   # aumentar a 120 segundos
  retries: 3     # aumentar reintentos (default: 2)
```

```bash
# Diagnosticar con log detallado
architect run "tarea" --log-file debug.jsonl -vvv
cat debug.jsonl | jq 'select(.event | startswith("agent.llm"))'
```

### 1.3 Modelo no encontrado

**Sintoma**: error `Model not found` o `Invalid model` al inicio. Exit code 3 (config error).

**Causa**: el nombre del modelo no existe en el proveedor configurado, o el proveedor no soporta ese modelo.

**Solucion**:

```bash
# Verificar que el modelo es valido para el proveedor
# OpenAI: gpt-4o, gpt-4o-mini, gpt-4.1, etc.
# Anthropic: claude-sonnet-4-6, claude-opus-4-6, etc.
# Para modelos via LiteLLM proxy, usar prefijo: openai/gpt-4o, anthropic/claude-sonnet-4-6

architect run "tarea" --model gpt-4o
architect run "tarea" --model anthropic/claude-sonnet-4-6
```

```yaml
# .architect.yaml
llm:
  model: "gpt-4o"         # nombre exacto del modelo
  api_base: null           # null para usar el proveedor directo
```

### 1.4 Rate limiting (429)

**Sintoma**: log JSON muestra errores HTTP 429 repetidos. El agente puede recuperarse automaticamente gracias a los retries, pero si persiste, se detiene con `LLM_ERROR`.

**Causa**: demasiadas requests al proveedor en poco tiempo. Comun en ejecuciones paralelas o con modelos de baja cuota.

**Solucion**:

```yaml
# .architect.yaml
llm:
  retries: 3           # aumentar reintentos con backoff
  timeout: 120         # dar mas tiempo para que el backoff funcione
```

```bash
# En ejecuciones paralelas, reducir workers
architect parallel --workers 2 --task "..."

# Verificar cuota en el dashboard del proveedor
# OpenAI: platform.openai.com/usage
# Anthropic: console.anthropic.com
```

### 1.5 API base incorrecto

**Sintoma**: error `Connection refused` o `Could not resolve host`. El agente no puede conectar al LLM.

**Causa**: `api_base` apunta a un servidor inexistente, no accesible, o usa un protocolo incorrecto.

**Solucion**:

```bash
# Verificar que el servidor responde
curl https://tu-servidor.com/v1/models

# Corregir en la configuracion
architect run "tarea" --api-base "https://tu-servidor.com/v1"
```

```yaml
# .architect.yaml
llm:
  api_base: "https://tu-servidor.com/v1"
  mode: "proxy"    # usar "proxy" si es un servidor LiteLLM o compatible OpenAI
```

---

## 2. El agente no termina / loops infinitos

### 2.1 max_steps demasiado alto o sin configurar

**Sintoma**: el agente ejecuta decenas o cientos de pasos sin terminar. El output HUMAN muestra `Paso 50`, `Paso 51`... sin fin.

**Causa**: `max_steps` por defecto es 50 para el agente `build` (20 para `plan` y `review`, 15 para `resume`). Si la tarea es ambigua, el LLM puede no encontrar un punto de parada.

**Solucion**:

```yaml
# .architect.yaml -- limitar pasos
agents:
  build:
    max_steps: 30    # tope razonable

# Usar tambien budget y timeout como safety nets complementarios
costs:
  budget_usd: 2.00   # max $2 por ejecucion
```

```bash
# Desde CLI
architect run "tarea" --max-steps 25 --budget 1.50 --timeout 300
```

### 2.2 Sin safety nets configurados

**Sintoma**: el agente se ejecuta indefinidamente consumiendo tokens y dinero. No hay mensajes de `safety.*` en los logs.

**Causa**: no se configuraron limites de presupuesto, timeout ni max_steps adecuados.

**Solucion**: configura siempre los tres safety nets:

```yaml
# .architect.yaml -- configuracion defensiva
agents:
  build:
    max_steps: 30

costs:
  budget_usd: 5.00
  warn_at_usd: 3.00

# Timeout desde CLI (no hay config YAML para timeout global, se pasa como flag)
```

```bash
architect run "tarea" --max-steps 30 --budget 5.00 --timeout 600
```

### 2.3 Hooks fallando repetidamente causan loops

**Sintoma**: el agente repite el mismo paso una y otra vez. El output HUMAN muestra `Hook nombre: (warning)` repetidamente. El agente intenta corregir, el hook falla de nuevo, y asi sucesivamente.

**Causa**: un hook `post_tool_use` o un quality gate falla consistentemente, el LLM recibe el error como feedback e intenta corregir, pero la correccion tampoco pasa el hook.

**Solucion**:

```bash
# Diagnosticar: ver que hooks estan fallando
cat debug.jsonl | jq 'select(.event == "agent.hook.complete" and .success == false)'

# Verificar el hook manualmente
echo '{}' | ARCHITECT_EVENT=post_tool_use ARCHITECT_TOOL_NAME=edit_file bash -c 'tu-comando-de-hook'
echo $?  # debe ser 0 (ALLOW) o 2 (BLOCK)
```

```yaml
# Desactivar el hook problematico temporalmente
hooks:
  post_tool_use:
    - name: "mi-hook"
      command: "..."
      enabled: false    # <-- desactivar
```

Los hooks NUNCA rompen el loop (errores retornan ALLOW), pero si un quality gate requerido falla repetidamente, el agente sigue intentando. Revisa que los quality gates sean alcanzables:

```yaml
guardrails:
  quality_gates:
    - name: "tests"
      command: "pytest tests/ -x"
      required: true     # cambiar a false si bloquea
      timeout: 60
```

### 2.4 Context window llenandose

**Sintoma**: output HUMAN muestra `Comprimiendo contexto -- N intercambios` y `Ventana de contexto: eliminados N mensajes`. El agente se vuelve lento. Puede terminar con `StopReason: CONTEXT_FULL`.

**Causa**: la tarea es muy larga, las respuestas de tools son muy grandes, o la configuracion de context management no es suficiente.

**Solucion**:

```yaml
# .architect.yaml -- gestion de contexto agresiva
context:
  max_tool_result_tokens: 1500     # truncar results grandes
  summarize_after_steps: 6         # comprimir antes
  keep_recent_steps: 3             # conservar menos pasos
  max_context_tokens: 60000        # limite hard

# Usar un modelo con contexto mas grande
llm:
  model: "gpt-4o"  # 128k context
```

### 2.5 Quality gates contradicen la tarea

**Sintoma**: el agente completa la tarea pero los quality gates fallan, asi que el agente intenta "arreglar" el codigo y rompe lo que habia hecho. Se repite en bucle.

**Causa**: un quality gate (lint, tests, typecheck) falla por motivos no relacionados con la tarea actual, pero el agente recibe el error e intenta corregirlo.

**Solucion**:

```yaml
guardrails:
  quality_gates:
    - name: "lint"
      command: "ruff check src/ --select E,W"  # ser especifico en que reglas
      required: false   # no bloquear al agente
      timeout: 30

    - name: "tests-related"
      command: "pytest tests/test_specific.py -x"  # solo tests relevantes
      required: true
      timeout: 120
```

---

## 3. El agente produce resultados incorrectos

### 3.1 Prompt demasiado vago o ambiguo

**Sintoma**: el agente completa (exit code 0, `StopReason: LLM_DONE`) pero el resultado no es lo que se esperaba. Hace cambios en archivos incorrectos o genera codigo irrelevante.

**Causa**: el prompt no es suficientemente especifico. El agente infiere la intencion incorrectamente.

**Solucion**:

```bash
# Ser explicito sobre que hacer, donde y como
architect run "En src/auth/login.py, refactorizar la funcion validate_token() \
  para que use pyjwt en lugar de jose. Mantener la misma interfaz publica. \
  Actualizar los tests en tests/test_auth.py"

# Para tareas complejas, usar un heredoc o archivo via shell
architect run "$(cat spec.md)"
```

### 3.2 Agente incorrecto seleccionado

**Sintoma**: el agente planifica en lugar de construir, o construye sin planificar una tarea compleja.

**Causa**: el agente por defecto es `build`. Puede que la tarea requiera `plan` (para tareas grandes) o `review` (para revisar codigo).

**Solucion**:

```bash
# Usar agente explicito
architect run "..." --agent plan      # planificacion
architect run "..." --agent build     # construccion (default)
architect run "..." --agent review    # revision de codigo
architect run "..." --agent resume    # reanudar tarea interrumpida
```

### 3.3 Falta .architect.md en el proyecto

**Sintoma**: el agente no sigue las convenciones del proyecto. Usa tabs en lugar de espacios, importa librerias no permitidas, no sigue el patron de arquitectura.

**Causa**: no hay un archivo `.architect.md` en la raiz del proyecto que le indique las convenciones al agente. El agente usa sus propios defaults.

**Solucion**: crear `.architect.md` en la raiz del workspace con las convenciones:

```markdown
# Convenciones del Proyecto

- Python 3.12+, usar typing estricto
- Formato: black (100 chars), ruff para linting
- Tests con pytest, minimo 80% cobertura
- No usar print(), siempre structlog
- Imports absolutos, nunca relativos
```

### 3.4 Modelo demasiado debil para la tarea

**Sintoma**: el agente completa pero el codigo tiene bugs evidentes, no compila, o ignora instrucciones claras del prompt.

**Causa**: modelos pequenos (gpt-4o-mini, claude-haiku) pueden no ser suficientes para tareas complejas de refactorizacion o arquitectura.

**Solucion**:

```bash
# Usar un modelo mas capaz
architect run "tarea compleja" --model gpt-4o
architect run "tarea compleja" --model anthropic/claude-sonnet-4-6
```

### 3.5 Contexto demasiado grande causa alucinaciones

**Sintoma**: el agente mezcla contenido de archivos diferentes, inventa funciones que no existen, o referencia codigo que fue eliminado por la compresion de contexto.

**Causa**: cuando el contexto se acerca al limite, los modelos pueden perder precision. La compresion de contexto puede eliminar informacion relevante.

**Solucion**:

```yaml
# Ser mas agresivo con truncado para mantener precision
context:
  max_tool_result_tokens: 1000   # menos contenido por tool result
  keep_recent_steps: 5           # mantener mas pasos recientes intactos
  summarize_after_steps: 5       # comprimir mas pronto

# Dividir la tarea en pasos mas pequenos
# O usar pipelines para secuenciar sub-tareas
```

```bash
# Usar pipeline para tareas grandes
architect pipeline workflow.yaml
```

---

## 4. Errores de tools

### 4.1 Path traversal bloqueado

**Sintoma**: output HUMAN muestra `ERROR: Path validation failed` o `Path outside workspace`. El tool result contiene un error sobre path traversal.

**Causa**: el agente intenta acceder a un archivo fuera del `workspace_root`. Todas las operaciones de filesystem validan que el path este dentro del workspace.

**Solucion**:

```bash
# Verificar que el workspace es correcto
architect run "tarea" --workspace /ruta/al/proyecto

# Si necesitas acceder a archivos fuera del workspace, ajusta el workspace root
architect run "tarea" --workspace /ruta/padre
```

```yaml
# .architect.yaml
workspace:
  root: "."   # relativo al directorio de ejecucion
```

### 4.2 Tool no disponible para el agente

**Sintoma**: log JSON muestra `tool_not_found` o `Tool 'X' not found in registry`. El agente intenta usar una tool que no tiene asignada.

**Causa**: cada agente tiene una lista `allowed_tools`. Si la tool no esta en la lista, no puede usarla. El agente `review` solo tiene tools de lectura.

**Solucion**:

```yaml
# .architect.yaml -- asignar tools al agente
agents:
  build:
    allowed_tools:
      - read_file
      - write_file
      - edit_file
      - apply_patch
      - search_code
      - grep
      - find_files
      - run_command
      - dispatch_subagent
```

```bash
# Ver tools disponibles con verbose
architect run "tarea" -v --log-file debug.jsonl
cat debug.jsonl | jq 'select(.event | contains("tool")) | .tool'
```

### 4.3 edit_file: old_str no es unico

**Sintoma**: tool result contiene error `old_str not found` o `old_str matches multiple locations`. La edicion falla.

**Causa**: `edit_file` usa string replacement exacto. Si `old_str` aparece mas de una vez o no existe exactamente como se pasa, falla.

**Solucion**: esto lo resuelve el propio agente, pero si ocurre repetidamente:

```bash
# Verificar el contenido exacto del archivo
cat -A archivo.py  # muestra tabs y espacios

# El agente deberia usar un old_str mas largo y unico
# Si persiste, indicar al agente que use apply_patch en lugar de edit_file
architect run "Usa apply_patch en lugar de edit_file para los cambios en archivo.py"
```

### 4.4 apply_patch: contexto no coincide

**Sintoma**: tool result contiene `patch failed` o `context mismatch`. El patch no se puede aplicar.

**Causa**: las lineas de contexto del unified diff no coinciden con el contenido actual del archivo. El archivo fue modificado entre que el agente lo leyo y genero el patch.

**Solucion**: el agente normalmente reintenta leyendo el archivo de nuevo. Si persiste:

```bash
# Diagnosticar con el log
cat debug.jsonl | jq 'select(.tool == "apply_patch") | {args: .args, error: .error}'
```

El agente deberia usar `read_file` antes de `apply_patch` para obtener el contenido actualizado.

### 4.5 run_command bloqueado o timeout

**Sintoma**: tool result contiene `Command blocked` (comando en la lista de bloqueados) o `Command timed out after Ns`.

**Causa**: el comando coincide con un patron bloqueado (built-in o custom) o excede el timeout.

**Solucion**:

```yaml
# .architect.yaml
commands:
  enabled: true
  default_timeout: 60       # aumentar timeout (default: 30)
  max_output_lines: 500     # aumentar output (default: 200)

  # Anadir comandos seguros
  safe_commands:
    - "npm test"
    - "cargo build"

  # Anadir patrones bloqueados adicionales
  blocked_patterns:
    - "docker rm"

  # Solo permitir comandos safe/dev (modo restrictivo)
  allowed_only: false   # true = solo safe+dev
```

### 4.6 delete_file no permitido

**Sintoma**: tool result contiene `Delete not allowed` o `File deletion disabled`.

**Causa**: por defecto, `allow_delete` esta desactivado en la configuracion de workspace.

**Solucion**:

```yaml
# .architect.yaml
workspace:
  allow_delete: true   # permitir eliminacion de archivos
```

---

## 5. Problemas de hooks y guardrails

### 5.1 Hook timeout

**Sintoma**: log muestra `hook.timeout` con el nombre del hook. El hook se ignora (retorna ALLOW por defecto).

**Causa**: el hook tarda mas que su timeout configurado (default: 10 segundos).

**Solucion**:

```yaml
hooks:
  post_tool_use:
    - name: "mi-linter"
      command: "ruff check --fix $ARCHITECT_FILE_PATH"
      timeout: 30   # aumentar (default: 10, max: 300)
```

```bash
# Verificar cuanto tarda el hook manualmente
time ruff check --fix src/main.py
```

### 5.2 Hook bloquea inesperadamente

**Sintoma**: output HUMAN muestra `Hook nombre: (warning)`. El agente recibe un mensaje de bloqueo del hook pero no deberia. La tool call no se ejecuta.

**Causa**: un pre-hook retorna exit code 2 (BLOCK) cuando no deberia. El stderr del hook contiene la razon de bloqueo.

**Solucion**:

```bash
# Ejecutar el hook manualmente para ver que pasa
export ARCHITECT_EVENT=pre_tool_use
export ARCHITECT_TOOL_NAME=edit_file
export ARCHITECT_WORKSPACE=$(pwd)
echo '{"path": "src/main.py"}' | bash -c 'tu-comando-de-hook'
echo "Exit code: $?"  # 0=ALLOW, 2=BLOCK

# Verificar en el log JSON
cat debug.jsonl | jq 'select(.event == "hook.error" or .event == "agent.hook.complete")'
```

**Protocolo de exit codes de hooks**:
- Exit 0 = ALLOW (permitir la accion)
- Exit 2 = BLOCK (bloquear, stderr = razon)
- Otro = Error del hook (se logea WARNING, no bloquea)

### 5.3 Guardrail bloquea acceso a archivos

**Sintoma**: tool result contiene `Sensitive file blocked by guardrail: X (pattern: Y)` o `Protected file blocked by guardrail: X (pattern: Y)` (con `language: es`: `Archivo sensible bloqueado por guardrail: X (patrón: Y)`).

**Causa**: el archivo coincide con un patron en `guardrails.sensitive_files` (bloquea lectura y escritura) o `guardrails.protected_files` (bloquea solo escritura).

**Solucion**:

```yaml
guardrails:
  enabled: true

  # sensitive_files: bloquea LECTURA y ESCRITURA (v1.1.0)
  # Usar para archivos con secrets que el LLM no deberia ni leer
  sensitive_files:
    - ".env*"
    - "*.pem"
    - "*.key"
    - "secrets.*"

  # protected_files: bloquea solo ESCRITURA
  # Usar para archivos que el LLM puede leer pero no modificar
  protected_files:
    - "Dockerfile"
    - "docker-compose*.yml"
    - "deploy/**"
    # Verificar que no hay patrones demasiado amplios
    # Por ejemplo "*.json" bloquearia TODOS los JSON
```

```bash
# Ver que archivos estan bloqueados (sensibles y protegidos)
cat debug.jsonl | jq 'select(.event == "guardrail.sensitive_file_blocked" or .event == "guardrail.file_blocked")'
```

### 5.4 Code rules bloquean ediciones

**Sintoma**: el agente escribe codigo pero recibe una advertencia o bloqueo con el mensaje de una code rule. El log muestra `guardrail.code_rule_violation`.

**Causa**: el contenido escrito por el agente coincide con un patron regex de una code rule con severity `block`.

**Solucion**:

```yaml
guardrails:
  code_rules:
    - pattern: "import os\\.system"
      message: "Usar subprocess en lugar de os.system"
      severity: "warn"     # "warn" adjunta aviso, "block" impide write

    - pattern: "TODO|FIXME|HACK"
      message: "No dejar TODOs en el codigo"
      severity: "warn"     # cambiar de "block" a "warn" si es demasiado estricto
```

### 5.5 Limite de archivos o lineas modificados

**Sintoma**: tool result contiene `Limite de archivos modificados alcanzado` o `Limite de lineas cambiadas alcanzado`.

**Causa**: el guardrail `max_files_modified` o `max_lines_changed` ha sido alcanzado durante la sesion.

**Solucion**:

```yaml
guardrails:
  max_files_modified: 20    # aumentar o poner null para sin limite
  max_lines_changed: 2000   # aumentar o poner null
  max_commands_executed: 50  # aumentar o poner null
```

---

## 6. Problemas en features avanzadas

### 6.1 Sesiones: no se puede reanudar

**Sintoma**: `architect resume <id>` muestra `session not found` o carga una sesion corrupta.

**Causa**: la sesion no existe en `.architect/sessions/`, el archivo JSON esta corrupto, o la sesion se limpio automaticamente.

**Solucion**:

```bash
# Listar sesiones disponibles
architect sessions

# Verificar que el directorio existe
ls -la .architect/sessions/

# Si la sesion fue limpiada, verificar la configuracion de cleanup
```

```yaml
# .architect.yaml -- conservar sesiones mas tiempo
sessions:
  auto_save: true
  cleanup_after_days: 30   # default: 7 dias
```

**Nota**: si una sesion tiene mas de 50 mensajes, se trunca a los 30 mas recientes al guardarse. Esto puede afectar al resume si se perdio contexto importante.

### 6.2 Ralph Loop: nunca converge

**Sintoma**: el Ralph Loop ejecuta todas las iteraciones sin que los checks pasen. El archivo `.architect/ralph-progress.md` muestra FAIL en todas las iteraciones.

**Causa**: los checks son demasiado estrictos, la tarea es demasiado compleja para una sola iteracion, o el agente no recibe suficiente contexto de errores anteriores.

**Solucion**:

```bash
# Revisar el progreso
cat .architect/ralph-progress.md

# Verificar que los checks funcionan con el codigo actual
pytest tests/ -x          # ejecutar el check manualmente
ruff check src/           # ejecutar el check manualmente

# Usar opciones mas conservadoras
architect loop "tarea" \
  --check "pytest tests/test_specific.py -x" \
  --max-iterations 10 \
  --max-cost 5.00 \
  --model gpt-4o
```

**Causas comunes de no convergencia**:
- El check falla por razones no relacionadas con la tarea (tests rotos pre-existentes).
- El agente no incluye el tag `COMPLETE` en su respuesta (requerido para converger).
- La tarea requiere cambios en multiples archivos que el agente no puede resolver en una sola iteracion.
- El timeout de checks (120s) es insuficiente para test suites grandes.

### 6.3 Parallel: conflictos de worktree

**Sintoma**: error `Error creating worktree` al iniciar ejecucion paralela. O los worktrees quedan huerfanos despues de una ejecucion interrumpida.

**Causa**: worktrees de ejecuciones anteriores no se limpiaron. Git no permite crear un worktree si la branch ya existe o el directorio esta ocupado.

**Solucion**:

```bash
# Limpiar worktrees y branches de ejecuciones anteriores
architect parallel-cleanup

# Limpiar manualmente si el comando falla
git worktree list                            # ver worktrees activos
git worktree remove .architect-parallel-1 --force
git worktree remove .architect-parallel-2 --force
git worktree prune                           # limpiar huerfanos
git branch -D architect/parallel-1           # eliminar branches
git branch -D architect/parallel-2
```

### 6.4 Pipeline: YAML con campos incorrectos (v1.1.0)

**Sintoma**: al ejecutar `architect pipeline`, se muestra `Error de validación: Pipeline 'file.yaml' tiene errores de validación:` seguido de una lista de errores, y el proceso sale con exit code 3.

**Causa**: el YAML del pipeline tiene campos incorrectos, prompts vacíos, o campos desconocidos. Desde v1.1.0, el pipeline valida el YAML antes de ejecutar.

**Solucion**:

```bash
# Revisar el mensaje de error — lista TODOS los problemas de una vez
architect pipeline pipeline.yaml
# Validation error: Pipeline 'pipeline.yaml' has validation errors:
#   analyze: unknown field 'task' (did you mean 'prompt'?)
#   analyze: missing 'prompt' or empty
```

**Errores comunes**:
- `task:` en vez de `prompt:` — usar `prompt:` (el hint lo indica)
- Prompt vacío `prompt: ""` — cada step necesita un prompt con contenido
- Campos inventados (`priority:`, `description:`) — solo los 9 campos válidos: `name`, `agent`, `prompt`, `model`, `checkpoint`, `condition`, `output_var`, `checks`, `timeout`
- Steps como strings en vez de objetos YAML

### 6.5 Pipeline: variables no se resuelven

**Sintoma**: el prompt del pipeline contiene literalmente `{{variable}}` en lugar del valor esperado. El agente recibe el template sin resolver.

**Causa**: la variable no esta definida ni en el YAML del pipeline ni en los `--var` de CLI. Las variables no definidas se dejan como estan (no se resuelven).

**Solucion**:

```yaml
# pipeline.yaml
name: mi-pipeline
variables:
  target_dir: "src/"           # definir valor por defecto
  test_command: "pytest"

steps:
  - name: build
    prompt: "Construir en {{target_dir}}"  # se resuelve con "src/"
```

```bash
# Pasar variables desde CLI (sobreescriben las del YAML)
architect pipeline pipeline.yaml --var target_dir=lib/ --var test_command="npm test"

# Verificar resolucion con dry-run
architect pipeline pipeline.yaml --dry-run
```

### 6.6 Checkpoints: no se crean

**Sintoma**: `architect history` no muestra checkpoints. El log no tiene eventos `checkpoint.created`.

**Causa**: checkpoints no estan habilitados en config, no hay cambios para commitear (git status limpio), o git no esta inicializado.

**Solucion**:

```yaml
# .architect.yaml
checkpoints:
  enabled: true
  every_n_steps: 5   # crear checkpoint cada 5 pasos
```

```bash
# Verificar que hay un repositorio git
git status

# Verificar que hay cambios para commitear
git status --porcelain

# Buscar checkpoints existentes manualmente
git log --oneline --grep="architect:checkpoint"
```

**Nota**: los checkpoints son git commits con prefijo `architect:checkpoint`. Si el workspace no tiene cambios staged, no se crea commit. Si `git add -A` no captura nada nuevo, el checkpoint se salta silenciosamente.

### 6.7 Auto-review: no detecta issues

**Sintoma**: el auto-review siempre reporta "Sin issues encontrados" aunque hay problemas evidentes.

**Causa**: el diff es demasiado grande (se trunca a 8000 caracteres), el reviewer no tiene suficiente contexto, o el modelo del reviewer es demasiado debil.

**Solucion**:

```yaml
# .architect.yaml
auto_review:
  enabled: true
  review_model: "gpt-4o"       # usar modelo capaz para review
  max_fix_passes: 2             # intentar corregir hasta 2 veces
```

---

## 7. Problemas de CI/CD

### 7.1 No hay TTY para modo confirmacion

**Sintoma**: error `NoTTYError` o `Cannot confirm: no TTY available`. Exit code 1.

**Causa**: en CI/CD no hay terminal interactivo. El modo de confirmacion `confirm-all` o `confirm-sensitive` requiere input del usuario.

**Solucion**:

```bash
# Usar modo yolo (sin confirmacion) en CI
architect run "tarea" --confirm-mode yolo

# O el alias corto
architect run "tarea" -m yolo
```

```yaml
# .architect.yaml para CI
agents:
  build:
    confirm_mode: "yolo"
```

### 7.2 Exit codes en pipelines CI

**Sintoma**: el pipeline CI falla o pasa cuando no deberia. Los exit codes de architect no se interpretan correctamente.

**Causa**: architect usa exit codes especificos que el CI no distingue.

**Solucion**: manejar los exit codes explicitamente:

```bash
# En GitHub Actions / shell script
architect run "tarea" --confirm-mode yolo --json --budget 5.00
EXIT_CODE=$?

case $EXIT_CODE in
  0) echo "Exito total" ;;
  1) echo "Fallo" ; exit 1 ;;
  2) echo "Parcial — revisar output" ;;
  3) echo "Error de configuracion" ; exit 1 ;;
  4) echo "Error de autenticacion" ; exit 1 ;;
  5) echo "Timeout" ; exit 1 ;;
  130) echo "Interrumpido" ; exit 1 ;;
esac
```

```bash
# Usar --exit-code-on-partial para tratar partial como error
architect run "tarea" --confirm-mode yolo --exit-code-on-partial
# Ahora exit code 2 (partial) se convierte en exit code 1 (failed)
```

### 7.3 Output JSON: parsing incorrecto

**Sintoma**: el CI intenta parsear el output JSON pero falla. El JSON esta mezclado con logs o esta incompleto.

**Causa**: sin `--json`, el resultado va a stdout pero los logs HUMAN van a stderr. Si el CI captura ambos streams, se mezclan. O el agente se interrumpe antes de generar JSON completo.

**Solucion**:

```bash
# Asegurar output limpio JSON
architect run "tarea" --json --quiet 2>/dev/null > result.json

# --json: output JSON a stdout
# --quiet: suprimir logs HUMAN en stderr
# 2>/dev/null: suprimir todo stderr

# Parsear con jq
cat result.json | jq '.status'
cat result.json | jq '.costs.total_cost_usd'
```

### 7.4 Presupuesto agotado en CI

**Sintoma**: el agente termina con `StopReason: BUDGET_EXCEEDED`, exit code 2 (partial). La tarea queda incompleta.

**Causa**: el presupuesto configurado es insuficiente para la complejidad de la tarea. Los modelos grandes consumen mas tokens.

**Solucion**:

```bash
# Aumentar presupuesto
architect run "tarea" --budget 10.00 --confirm-mode yolo

# Usar prompt caching para reducir costes
```

```yaml
# .architect.yaml
costs:
  budget_usd: 10.00
  warn_at_usd: 7.00

llm:
  prompt_caching: true   # reduce coste 50-90% en llamadas repetidas
```

```bash
# Monitorizar costes en CI
architect run "tarea" --json --confirm-mode yolo > result.json
COST=$(cat result.json | jq '.costs.total_cost_usd // 0')
echo "Coste de la ejecucion: $${COST}"
```

### 7.5 Servidor MCP no accesible

**Sintoma**: log muestra errores de conexion MCP. Las tools MCP no se registran. El agente funciona pero sin las tools remotas.

**Causa**: el servidor MCP no esta accesible desde el entorno CI, el token ha expirado, o la URL es incorrecta.

**Solucion**:

```yaml
# .architect.yaml
mcp:
  servers:
    - name: "docs"
      url: "https://mcp-server.example.com"
      token_env: "MCP_DOCS_TOKEN"   # env var con el token
```

```bash
# Verificar conectividad
curl -v https://mcp-server.example.com

# Verificar que el token esta configurado
echo $MCP_DOCS_TOKEN

# En CI, configurar como secret
# GitHub Actions:
# env:
#   MCP_DOCS_TOKEN: ${{ secrets.MCP_DOCS_TOKEN }}
```

---

## 8. Diagnostico con logging

### 8.1 Capturar log completo

```bash
# Capturar TODO (JSON debug + console verbose)
architect run "tarea" --log-file session.jsonl -vvv
```

El archivo `session.jsonl` contiene cada evento como una linea JSON. Esto incluye llamadas LLM, tool calls, resultados, hooks, safety nets, y mas.

### 8.2 Consultas utiles con jq

```bash
# Ver todos los tool calls ejecutados
cat session.jsonl | jq 'select(.event == "agent.tool_call.execute") | {tool: .tool, args: .args}'

# Ver solo los errores de tools
cat session.jsonl | jq 'select(.event == "agent.tool_call.complete" and .success == false) | {tool: .tool, error: .error}'

# Ver llamadas al LLM y numero de mensajes
cat session.jsonl | jq 'select(.event == "agent.llm.call") | {step: .step, messages: .messages_count}'

# Ver todos los safety net triggers
cat session.jsonl | jq 'select(.event | startswith("safety."))'

# Ver costes por step
cat session.jsonl | jq 'select(.event == "cost_tracker.record") | {step: .step, model: .model, cost: .cost_usd, tokens_in: .input_tokens, tokens_out: .output_tokens}'

# Ver eventos de hooks
cat session.jsonl | jq 'select(.event | startswith("hook."))'

# Ver eventos de guardrails
cat session.jsonl | jq 'select(.event | startswith("guardrail."))'

# Ver compresion de contexto
cat session.jsonl | jq 'select(.event | startswith("context."))'

# Extraer el stop_reason final
cat session.jsonl | jq 'select(.event == "agent.loop.complete") | {status: .status, stop_reason: .stop_reason, steps: .total_steps}'

# Ver errores del LLM
cat session.jsonl | jq 'select(.event == "agent.llm_error") | .error'

# Resumen rapido: cuantos de cada tipo de evento
cat session.jsonl | jq -r '.event' | sort | uniq -c | sort -rn
```

### 8.3 Leer el output HUMAN (iconos)

El output HUMAN usa iconos para indicar el tipo de evento:

| Icono | Significado |
|-------|-------------|
| 🔄 | Step N: LLM call / closing |
| ✓ | Successful LLM response or tool OK |
| 🔧 | Local tool execution |
| 🌐 | MCP tool execution (remote) |
| 🔍 | Hook result |
| ✅ | Agent complete (success) |
| ⚡ | Agent stopped (partial or failed) |
| ⚠️ | Safety net triggered or warning |
| ❌ | LLM error |
| 📦 | Context compression/management |

### 8.4 Niveles de verbose (-v/-vv/-vvv)

| Flag | Nivel console | Que muestra |
|------|--------------|-------------|
| (ninguno) | WARNING | Solo output HUMAN (pasos del agente) + errores graves |
| `-v` | INFO | HUMAN + operaciones del sistema: config cargada, tools registradas, indexer |
| `-vv` | DEBUG | HUMAN + detalle tecnico: args completos, respuestas LLM, timing |
| `-vvv` | DEBUG | HUMAN + TODO: HTTP requests, payloads completos |

Los logs HUMAN se muestran **siempre** (excepto `--quiet`/`--json`), independientemente de `-v`.

```bash
# Para desarrollo/debug, usar -vv
architect run "tarea" -vv --log-file debug.jsonl

# Para CI, usar --quiet o --json
architect run "tarea" --json --quiet --confirm-mode yolo
```

---

## 9. Tabla rapida de exit codes

| Exit Code | Nombre | Descripcion | StopReason tipico |
|-----------|--------|-------------|-------------------|
| 0 | SUCCESS | Tarea completada exitosamente | `LLM_DONE` |
| 1 | FAILED | Tarea fallida (error irrecuperable) | `LLM_ERROR` |
| 2 | PARTIAL | Tarea parcialmente completada | `MAX_STEPS`, `BUDGET_EXCEEDED`, `CONTEXT_FULL`, `TIMEOUT` |
| 3 | CONFIG_ERROR | Error en la configuracion YAML o flags | -- |
| 4 | AUTH_ERROR | Fallo de autenticacion con el LLM | -- |
| 5 | TIMEOUT | Timeout global de la ejecucion | `TIMEOUT` |
| 130 | INTERRUPTED | Ctrl+C o SIGTERM | `USER_INTERRUPT` |

### Tabla de StopReason

| StopReason | Tipo | Descripcion | Accion recomendada |
|------------|------|-------------|-------------------|
| `LLM_DONE` | Natural | El LLM decidio que termino (no pidio mas tools) | Verificar que el resultado es correcto |
| `MAX_STEPS` | Safety net | Se alcanzo el limite de pasos | Aumentar `max_steps` o simplificar la tarea |
| `BUDGET_EXCEEDED` | Safety net | Se supero el presupuesto en USD | Aumentar `budget_usd` o usar modelo mas barato |
| `CONTEXT_FULL` | Safety net | La ventana de contexto se lleno | Ajustar `context` config o dividir la tarea |
| `TIMEOUT` | Safety net | Se supero el tiempo limite | Aumentar `--timeout` o simplificar la tarea |
| `USER_INTERRUPT` | Manual | El usuario pulso Ctrl+C / envio SIGTERM | El agente intenta cerrar gracefully y resumir |
| `LLM_ERROR` | Error | Error irrecuperable del LLM (despues de retries) | Verificar API key, modelo, conectividad |

---

## 10. Checklist rapido de diagnostico

Ante cualquier problema, seguir este orden:

1. **Verificar exit code**: `echo $?` despues de ejecutar.
2. **Leer output HUMAN**: buscar el ultimo icono de warning/error.
3. **Revisar con verbose**: repetir con `-vv`.
4. **Capturar log JSON**: repetir con `--log-file debug.jsonl`.
5. **Filtrar con jq**: usar las consultas de la seccion 8.2.
6. **Verificar config**: `architect run --dry-run "test" -v` para ver que config se carga.
7. **Probar hooks manualmente**: ejecutar los comandos de hooks fuera de architect.
8. **Revisar .architect.yaml**: validar con `python -c "from architect.config.loader import load_config; load_config('.')"`.
