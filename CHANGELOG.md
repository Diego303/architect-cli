# Changelog

Todos los cambios notables en el proyecto architect serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y este proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

---

## [No Publicado]

### En Progreso
(F9 completada — sin cambios pendientes)

---

## [0.9.0] - 2026-02-19

### Fase 9 - Diff Inteligente y apply_patch ✅

#### Agregado

**`EditFileTool`** (`src/architect/tools/filesystem.py`):
- Tool `edit_file` para modificaciones parciales via str_replace exacto
- Valida que `old_str` aparezca exactamente una vez en el archivo
- Si `old_str` no existe → error `"no encontrado"` con sugerencia
- Si `old_str` aparece >1 veces → error con el conteo y sugerencia de añadir contexto
- Si `old_str` está vacío → error descriptivo con alternativas
- Genera diff en el output (vía `difflib.unified_diff`) para confirmación visual
- `sensitive = True`; requiere confirmación en modo `confirm-sensitive` o superior

**`ApplyPatchTool`** (`src/architect/tools/patch.py`):
- Tool `apply_patch` para parches unified diff con uno o más hunks
- **Parser puro-Python** (sin dependencias externas):
  - Regex `^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@` para cabeceras
  - Soporte de hunks de inserción pura (`orig_count=0`)
  - Offset acumulado entre hunks para ajustar posiciones
  - Validación de contexto con normalización de line endings (`rstrip("\n\r")`)
- **Fallback al comando `patch` del sistema** si el parser puro falla:
  - `patch --dry-run -f -i patch_file file_path` → validación sin modificar
  - `patch -f -i patch_file file_path` → aplicación real
- Las cabeceras `--- / +++` en el parche son opcionales
- `sensitive = True`

**`PatchError`** (`src/architect/tools/patch.py`):
- Excepción interna para errores de parseo/aplicación de parches

**Schemas nuevos** (`src/architect/tools/schemas.py`):
- `EditFileArgs` — `path`, `old_str`, `new_str` (todos requeridos excepto `new_str` que puede ser `""`)
- `ApplyPatchArgs` — `path`, `patch`

**Testing** (`scripts/test_phase9.py`) — 12 pruebas:
1. Importaciones de nuevas tools y `PatchError`
2. Versión 0.9.0 consistente en `__init__.py` y `pyproject.toml`
3. `EditFileTool` caso feliz — reemplazo y diff en output
4. `EditFileTool` old_str no encontrado — error descriptivo
5. `EditFileTool` old_str ambiguo — error con conteo
6. `EditFileTool` old_str vacío — error con alternativas
7. `ApplyPatchTool` single-hunk
8. `ApplyPatchTool` multi-hunk (2 hunks, posiciones no contiguas)
9. `ApplyPatchTool` inserción pura (`orig_count=0`)
10. `ApplyPatchTool` contexto incorrecto — falla con error claro
11. Jerarquía en descriptions de tools (`PREFERIR`, menciones cruzadas)
12. `EditFileTool` y `ApplyPatchTool` presentes en el registry

#### Modificado

**`WriteFileTool.description`** (`src/architect/tools/filesystem.py`):
- Ahora incluye orientación explícita: úsalo solo para archivos nuevos o reescritura total
- Referencia a `edit_file` y `apply_patch` como alternativas

**`BUILD_PROMPT`** (`src/architect/agents/prompts.py`):
- Nueva sección "Herramientas de Edición — Jerarquía de Uso" con tabla comparativa
- Guía detallada para `edit_file`, `apply_patch` y `write_file`
- El agente `build` ahora sabe cuándo preferir cada herramienta

**`src/architect/tools/setup.py`**:
- Registra `EditFileTool` y `ApplyPatchTool` en el registry por defecto

**`src/architect/tools/__init__.py`**:
- Exporta `EditFileTool`, `ApplyPatchTool`, `PatchError`, `EditFileArgs`, `ApplyPatchArgs`

#### Versión
- `src/architect/__init__.py`: `0.8.0` → `0.9.0`
- `pyproject.toml`: `0.8.0` → `0.9.0`
- `src/architect/cli.py`: `0.8.0` → `0.9.0` (3 sitios: `version_option` + 2 headers)

---

## [0.8.0] - 2026-02-19

### Fase 8 - Integración Final y Pulido ✅

#### Agregado

**Subcomando `architect agents`** (`src/architect/cli.py`):
- Lista los 4 agentes por defecto: `plan`, `build`, `resume`, `review`
- Muestra nombre, descripción y confirm_mode de cada agente
- Con `-c config.yaml`: incluye también los agentes custom del YAML
- Los defaults sobreescritos por el YAML se marcan con `*`
- Comando: `architect agents` / `architect agents -c config.yaml`

**Testing de integración (`scripts/test_phase8.py`)** — 7 pruebas:
1. **Importaciones**: verifica que los 23 módulos del proyecto importan sin errores
2. **Versión consistente**: comprueba que `__init__.py`, `pyproject.toml`, `--version` y `cli.py` headers muestran "0.8.0"
3. **CLI --help**: `architect --help`, `architect run --help` (con PROMPT/--dry-run/--mode/--json), `architect agents --help`, `architect validate-config --help`
4. **Subcomando agents**: verifica que los 4 agentes por defecto aparecen en la salida
5. **validate-config con example**: valida `config.example.yaml` y parsea correctamente (model, retries, stream, allow_delete)
6. **Inicialización completa sin LLM**: AppConfig, configure_logging, ToolRegistry, DEFAULT_AGENTS, GracefulShutdown, StepTimeout, ExecutionEngine, ContextBuilder
7. **dry-run sin API key**: verifica que falla con error de LLM (exit 1/4), no de config (exit 3)

#### Modificado

**Versión 0.8.0** — actualizada en todos los puntos:
- `src/architect/__init__.py` → `__version__ = "0.8.0"` (era "0.6.0")
- `pyproject.toml` → `version = "0.8.0"` (era "0.6.0")
- `src/architect/cli.py` → `@click.version_option(version="0.8.0")` (era "0.6.0")
- `src/architect/cli.py` → headers de ejecución muestran `architect v0.8.0`

**`config.example.yaml`** — reescrito completamente:
- Sección `llm`: explicación de provider/mode, todos los campos con comentarios, ejemplos de modelos (OpenAI, Anthropic, Gemini, Ollama, Together), `api_base` comentado, explicación detallada de `retries` (qué errores se reintentan y cuáles no), `stream` con notas sobre auto-desactivación
- Sección `agents`: explicación del sistema de merge, 3 agentes custom de ejemplo comentados (deploy, documenter, security) con system_prompt, allowed_tools, confirm_mode, max_steps
- Sección `logging`: tabla de niveles verbose (0-3), campo `file` comentado con ejemplo
- Sección `workspace`: explicación de confinamiento y path traversal, `allow_delete` con nota de seguridad
- Sección `mcp`: 4 ejemplos de servidores comentados (git, database, github+jira, internal), nota sobre `token` vs `token_env`
- Cabecera con versión 0.8.0 y explicación del orden de precedencia

**`README.md`** — reescrito completamente como documentación de usuario final:
- Instalación: requisitos Python 3.12+, `pip install -e .`, verificación, dependencias principales
- Quickstart: 7 ejemplos de uso reales (resume, review, plan, build, mixed, yolo, dry-run)
- Referencia `architect run`: tabla completa de opciones (principales, LLM, output, MCP)
- Referencia `architect agents` y `architect validate-config`
- Tabla de agentes: nombre, descripción, tools disponibles, confirm_mode
- Modo mixto: explicación del flujo plan→build
- Agentes custom: ejemplo YAML completo
- Modos de confirmación: tabla con comportamiento de cada modo
- Configuración: estructura YAML mínima, tabla de variables de entorno
- Salida y códigos de salida: separación stdout/stderr, tabla de 7 códigos, ejemplos bash
- Formato JSON (`--json`): ejemplo real con todos los campos
- Logging: ejemplos de todos los niveles (-v, -vv, -vvv, --quiet, --log-file, jq)
- MCP: YAML de configuración, ejemplo con/sin MCP
- CI/CD: GitHub Actions completo con verificación de resultado
- Arquitectura: diagrama ASCII del flujo interno, decisiones de diseño
- Seguridad: path traversal, allow_delete, MCP sensitive, API keys
- Proveedores LLM: ejemplos con OpenAI, Anthropic, Gemini, Ollama, LiteLLM Proxy
- Extensiones futuras

#### Características Implementadas

- ✅ Subcomando `architect agents` funcional (defaults + custom YAML)
- ✅ Versión 0.8.0 consistente en los 4 puntos del sistema
- ✅ `config.example.yaml` completamente documentado con todos los casos de uso
- ✅ README.md como documentación completa de usuario final
- ✅ Suite de integración: 7 pruebas que verifican el sistema completo sin API key

#### Uso

```bash
# Listar agentes disponibles
architect agents

# Listar agentes incluyendo custom del YAML
architect agents -c config.yaml

# Verificar la versión
architect --version

# Validar configuración
architect validate-config -c config.example.yaml

# Flujo completo (requiere API key)
LITELLM_API_KEY=sk-... architect run "analiza el proyecto" -a resume --quiet
```

#### Notas Técnicas

- `architect agents` muestra defaults aunque no haya config — no requiere API key ni YAML
- El subcomando re-usa `load_config()` con `config_path=None` cuando no se pasa `-c`
- Versión bump de 0.6.0 a 0.8.0 (salto intencional: F7 fue versión interna, F8 es el MVP)
- `test_phase8.py` verifica imports, CLI, y lógica de inicialización — no requiere LLM activo

#### MVP Completado

v0.8.0 es el MVP completo y funcional. Todas las fases del plan implementadas:
- F0: Scaffolding + config
- F1: Tools + execution engine
- F2: LLM adapter + agent loop
- F3: Sistema de agentes + mixed mode
- F4: MCP connector
- F5: Logging dual pipeline
- F6: Streaming + output final
- F7: Robustez y tolerancia a fallos
- F8: Integración final y pulido ✅

---

## [0.7.0] - 2026-02-19

### Fase 7 - Robustez y Tolerancia a Fallos ✅

#### Agregado

**StepTimeout (`src/architect/core/timeout.py`)** — nuevo archivo:
- Clase `StepTimeout` - Context manager de timeout por step
  - Usa `signal.SIGALRM` en sistemas POSIX (Linux/macOS)
  - No-op gracioso en Windows (sin SIGALRM), sin romper la ejecución
  - Parámetro `seconds=0` deshabilita el timeout completamente
  - Guarda y restaura el handler previo al salir (compatible con handlers anidados)
  - Cancela la alarma pendiente con `signal.alarm(0)` al salir limpiamente
- `StepTimeoutError(TimeoutError)` — excepción lanzada al expirar
  - Incluye el número de segundos en el mensaje
  - Subclase de `TimeoutError` (fácil de capturar específicamente)
- `_SIGALRM_SUPPORTED` — constante calculada al importar para detección de plataforma

**GracefulShutdown (`src/architect/core/shutdown.py`)** — nuevo archivo:
- Clase `GracefulShutdown` — gestión de señales de interrupción
  - Instala handlers para `SIGINT` y `SIGTERM` al instanciar
  - Primer disparo: muestra aviso en stderr, marca `_interrupted = True`
  - Segundo disparo `SIGINT`: `sys.exit(130)` inmediato (estándar POSIX)
  - `SIGTERM` siempre comportamiento graceful (para Docker/Kubernetes)
  - Propiedad `should_stop` — True si se recibió señal de interrupción
  - Método `reset()` — resetea el flag (útil para testing)
  - Método `restore_defaults()` — restaura `SIG_DFL` para cleanup

**Testing (`scripts/test_phase7.py`)** — 11 pruebas:
- StepTimeout sin timeout (seconds=0)
- StepTimeout dentro del límite
- StepTimeout expiración → StepTimeoutError
- StepTimeout restaura handler anterior
- GracefulShutdown estado inicial (should_stop=False)
- GracefulShutdown reset del flag
- AgentLoop acepta parámetros shutdown y step_timeout
- Retries LLM — _RETRYABLE_ERRORS contiene los tipos correctos
- Retries LLM — _call_with_retry ejecuta sin errores
- Tool errors como feedback (ExecutionEngine nunca lanza excepción)
- Integración estructural completa de F7

#### Modificado

**LLMAdapter (`src/architect/llm/adapter.py`)** — retries mejorados:
- Eliminado decorator `@retry(Exception)` (demasiado amplio, no configurable)
- `_RETRYABLE_ERRORS` — tupla con solo errores transitorios:
  - `litellm.RateLimitError` — límite de rate del proveedor
  - `litellm.ServiceUnavailableError` — servicio no disponible (503)
  - `litellm.APIConnectionError` — error de conexión de red
  - `litellm.Timeout` — timeout en la llamada HTTP
  - **NO incluye**: `AuthenticationError`, errores de configuración, etc.
- `_call_with_retry(fn, *args, **kwargs)` — método de instancia con Retrying:
  - `stop_after_attempt(config.retries + 1)` — usa `config.retries` real
  - `wait_exponential(multiplier=1, min=2, max=60)` — backoff progresivo
  - `before_sleep=self._on_retry_sleep` — callback de logging
  - `reraise=True` — propaga el último error
- `_on_retry_sleep(retry_state)` — logging estructurado antes de cada reintento:
  - Logea: `llm.retry`, attempt, wait_seconds, error, error_type
  - Usa `retry_state.next_action.sleep` para el tiempo de espera
- `completion()` refactorizado — usa `_call_with_retry` internamente

**AgentLoop (`src/architect/core/loop.py`)** — shutdown y timeout:
- Nuevos parámetros en `__init__`:
  - `shutdown: GracefulShutdown | None = None` — señal de interrupción
  - `step_timeout: int = 0` — segundos por step (0=sin límite)
- Comprobación de `shutdown.should_stop` al **inicio de cada iteración**:
  - Si True → `status="partial"`, mensaje descriptivo, `break`
- `StepTimeout(self.step_timeout)` envuelve la llamada al LLM (streaming y no-streaming)
- `StepTimeoutError` capturada específicamente:
  - `status="partial"`, mensaje con step number y segundos configurados
  - No propaga la excepción al llamador

**MixedModeRunner (`src/architect/core/mixed_mode.py`)** — shutdown y timeout:
- Nuevos parámetros: `shutdown` y `step_timeout`
- Los pasa a `plan_loop` y `build_loop` al instanciarlos
- Verificación adicional de `shutdown.should_stop` entre fase plan y build:
  - Si hubo shutdown durante plan → retorna `plan_state` inmediatamente

**CLI (`src/architect/cli.py`)** — GracefulShutdown integrado:
- `shutdown = GracefulShutdown()` — instanciado al inicio de `run()`
- Handler inline de SIGINT de F6 eliminado (reemplazado por la clase)
- `shutdown=shutdown` pasado a `AgentLoop` y `MixedModeRunner`
- `step_timeout=kwargs.get("timeout") or 0` — usa el flag `--timeout` del CLI
- `if shutdown.should_stop: sys.exit(EXIT_INTERRUPTED)` al finalizar
- Import `signal` eliminado (ya no necesario en CLI)

**Exports (`src/architect/core/__init__.py`)**:
- Añadido: `GracefulShutdown`, `StepTimeout`, `StepTimeoutError`

#### Características Implementadas

- ✅ StepTimeout: SIGALRM en POSIX, no-op en Windows, restaura handlers
- ✅ GracefulShutdown: SIGINT graceful + inmediato, SIGTERM graceful
- ✅ Retries selectivos: solo errores transitorios, no errores de auth
- ✅ Logging en cada reintento (intento, espera, tipo de error)
- ✅ config.retries usado realmente para configurar max_attempts
- ✅ AgentLoop comprueba shutdown antes de cada step
- ✅ AgentLoop envuelve LLM en StepTimeout
- ✅ MixedModeRunner propaga shutdown y timeout a ambos loops
- ✅ CLI usa GracefulShutdown class (código más limpio)

#### Notas Técnicas

- `SIGALRM` no disponible en Windows — StepTimeout es no-op, no rompe nada
- `_call_with_retry` es método de instancia (puede acceder a `self.config.retries`)
- El logger en `_on_retry_sleep` usa `self.log` (componente y modelo ya vinculados)
- `GracefulShutdown` instanciado antes de cargar config — captura Ctrl+C desde el inicio
- `step_timeout` usa el flag `--timeout` existente (re-usa config existente)
- Segundo SIGINT: `sys.exit(130)` — sale desde dentro del handler (no loop)

#### Próxima Fase

F8 - Integración Final y Pulido (Día 11-12)

---

## [0.6.0] - 2026-02-19

### Fase 6 - Streaming + Output Final ✅

#### Modificado

**CLI (`src/architect/cli.py`) - Streaming conectado y exit codes completos**:

- **Streaming activado por defecto**:
  - `use_stream` calculado automáticamente al inicio del comando `run`
  - Activo si: `config.llm.stream=True` AND NOT `--no-stream` AND NOT `--json`
  - Callback `on_stream_chunk` definido localmente: escribe a `sys.stderr` en tiempo real
  - Callback se pasa a `loop.run()` y `runner.run()` (ya soportaban el parámetro)
  - Newline final añadido a stderr tras el último chunk de streaming
  - Info del header muestra `📡 Streaming: sí/no` para claridad

- **Separación stdout/stderr completa**:
  - Toda la info de progreso (header, MCP stats, dry-run notice) → `err=True` (stderr)
  - Streaming chunks → `sys.stderr`
  - Separadores y estadísticas finales → `err=True` (stderr)
  - Resultado final del agente → `click.echo(state.final_output)` → **stdout**
  - `--json` output → `click.echo(json.dumps(...))` → **stdout**
  - Compatible con pipes: `architect run "..." --quiet --json | jq .`

- **Códigos de salida completos** (constantes definidas como módulo-level):
  - `EXIT_SUCCESS = 0` - Éxito
  - `EXIT_FAILED = 1` - Fallo del agente
  - `EXIT_PARTIAL = 2` - Parcial
  - `EXIT_CONFIG_ERROR = 3` - Error de configuración (FileNotFoundError)
  - `EXIT_AUTH_ERROR = 4` - Error de autenticación LLM
    - Detección por keywords: authenticationerror, api key, unauthorized, 401
  - `EXIT_TIMEOUT = 5` - Timeout
    - Detección por keywords: timeout, timed out, readtimeout
  - `EXIT_INTERRUPTED = 130` - Interrumpido por señal (estándar POSIX)

- **Manejo de SIGINT (graceful shutdown)**:
  - Handler instalado al inicio de `run()` con `signal.signal(SIGINT, ...)`
  - Primer Ctrl+C: muestra aviso, marca `interrupted=True`, continúa el step actual
  - Segundo Ctrl+C: `sys.exit(EXIT_INTERRUPTED)` inmediato
  - Al terminar: si `interrupted`, sale con código 130
  - `KeyboardInterrupt` como fallback en el bloque `except` principal
  - Estado del agente marcado como `partial` si fue interrumpido antes de terminar

- **Limpieza de imports**:
  - Eliminado `DEFAULT_AGENTS` (importado pero no usado directamente)
  - Añadido `json` y `signal` al top-level
  - Añadido `Callable` desde `typing`

- **Versión actualizada**:
  - `@click.version_option(version="0.6.0")` (era "0.1.0")
  - Headers de ejecución muestran `architect v0.6.0`
  - `validate_config` usa constantes `EXIT_CONFIG_ERROR` y `EXIT_FAILED`

**Testing (`scripts/test_phase6.py`)** - Suite completa nueva:
- Prueba 1: Formato JSON de `to_output_dict()` — verifica campos, tipos y valores
- Prueba 2: Constantes de exit codes — verifica los 7 códigos definidos
- Prueba 3: Streaming callback (mock) — simula chunks y verifica acumulación correcta
- Prueba 4: Separación stdout/stderr — documentación y verificación conceptual
- Prueba 5: Streaming real (opcional, requiere API key) — verifica chunks reales del LLM

#### Características Implementadas

- ✅ Streaming del LLM visible en terminal (stderr en tiempo real)
- ✅ `--no-stream` deshabilita streaming explícitamente
- ✅ Streaming auto-desactivado con `--json` y `--quiet`
- ✅ 7 códigos de salida con detección automática de tipo de error
- ✅ SIGINT: graceful (primer Ctrl+C) e inmediato (segundo Ctrl+C)
- ✅ Todo el output no-resultado va a stderr (stdout limpio para pipes)
- ✅ `--json` produce formato completo parseable por jq
- ✅ Versión actualizada a 0.6.0 en CLI y headers

#### Uso

```bash
# Streaming por defecto (se ve en terminal, no rompe pipes)
architect run "refactoriza main.py" -a build --mode yolo

# Sin streaming (útil para CI o logs más limpios)
architect run "tarea" --no-stream -v

# Salida JSON para pipes (streaming desactivado automáticamente)
architect run "resume el proyecto" --quiet --json | jq .status

# Logging a archivo + streaming visible
architect run "tarea compleja" -vv --log-file logs/run.jsonl

# Verificar exit codes
architect run "tarea" --mode yolo
echo "Exit code: $?"
# 0=success, 1=failed, 2=partial, 3=config error, 4=auth, 5=timeout, 130=Ctrl+C
```

#### Notas Técnicas

- Streaming chunks van a stderr: el stdout queda libre para el resultado/JSON
- El callback `on_stream_chunk` ya estaba soportado en `AgentLoop` y `MixedModeRunner`
- En mixed mode, solo la fase `build` usa streaming (plan es rápido y no necesita)
- Detección de errores de auth/timeout por keywords en el mensaje (compatible con LiteLLM)
- Signal handler es local al comando `run` para no afectar otros contextos
- `EXIT_INTERRUPTED = 130` sigue el estándar POSIX (128 + SIGINT=2)

#### Próxima Fase

F7 - Robustez y Tolerancia a Fallos (Día 10-11)

---

## [0.5.5] - 2026-02-18

### Fase 5 - Logging Completo ✅

#### Agregado

**Sistema de Logging Dual Pipeline**:
- `src/architect/logging/setup.py` - Reescritura completa del sistema de logging
  - Función `configure_logging()` - Configuración completa con dual pipeline
    - Pipeline 1: Archivo → JSON estructurado (JSON Lines)
      - FileHandler con encoding UTF-8
      - JSONRenderer de structlog
      - Nivel: DEBUG (captura todo)
      - Formato: un JSON por línea para parsing fácil
      - Creación automática de directorio padre
    - Pipeline 2: Stderr → Humano legible
      - StreamHandler a sys.stderr
      - ConsoleRenderer con colores automáticos (solo si TTY)
      - Nivel: según verbose/quiet
      - Formato: timestamp, nivel, logger, mensaje, campos extra
    - Procesadores compartidos:
      - merge_contextvars - Contexto global
      - add_log_level - Nivel de logging
      - add_logger_name - Nombre del logger
      - TimeStamper (ISO 8601, UTC)
      - StackInfoRenderer - Stack traces
      - format_exc_info - Formateo de excepciones
    - Configuración independiente:
      - Archivo siempre captura DEBUG completo
      - Stderr filtrado por verbose/quiet
      - Ambos pipelines pueden coexistir
    - ProcessorFormatter para dual rendering:
      - wrap_for_formatter en procesadores
      - formatter diferente por handler
      - JSON para archivo, Console para stderr

  - Función `_verbose_to_level()` - Mapeo de verbose a nivel logging
    - Niveles claros y progresivos:
      - 0 (sin -v) → WARNING (solo problemas)
      - 1 (-v) → INFO (steps del agente, tool calls principales)
      - 2 (-vv) → DEBUG (argumentos, respuestas LLM detalladas)
      - 3+ (-vvv) → DEBUG completo (incluyendo HTTP, internals)
    - Diseñado para debugging incremental

  - Función `configure_logging_basic()` - Backward compatibility
    - Para código de fases anteriores
    - Llama a configure_logging() con defaults razonables
    - level="info", verbose=1, file=None

  - Función `get_logger()` - Obtención de logger estructurado
    - Retorna structlog.BoundLogger
    - Logger estructurado con typing completo
    - Soporte para contexto y campos extra

  - Características del sistema:
    - Logs a stderr (stdout libre para output final)
    - JSON Lines en archivo (un JSON por línea)
    - Colores automáticos solo en TTY
    - Quiet mode: solo ERROR level
    - JSON output mode compatible (reduce logging)
    - Configuración vía LoggingConfig Pydantic
    - Sin handlers duplicados (clear antes de configurar)
    - Reset de structlog defaults cada vez

**Testing**:
- `scripts/test_phase5.py` - Suite completa de pruebas de logging
  - Prueba 1: Niveles de logging (verbose 0-3)
    - Genera logs en los 4 niveles (debug, info, warning, error)
    - Muestra comportamiento de cada verbose level
    - Verifica filtrado correcto por nivel

  - Prueba 2: Logging a archivo JSON
    - Crea archivo temporal .jsonl
    - Genera logs con contexto estructurado:
      - agent.step.start/complete
      - tool.call con argumentos
      - tool.result con success
    - Lee y muestra JSON generado
    - Verifica formato JSON Lines
    - Limpieza automática de archivos temporales

  - Prueba 3: Modo quiet
    - Configura con quiet=True
    - Genera debug, info, warning (no deberían verse)
    - Genera error (sí debería verse)
    - Verifica que solo ERROR se muestra

  - Prueba 4: Logging estructurado con contexto
    - Simula ejecución real de agent loop
    - Eventos: agent.loop.start, agent.step.start, llm.completion.start
    - Tool calls con múltiples steps
    - Contexto coherente (step, agent, prompt)
    - Muestra uso realista del sistema

  - Prueba 5: Dual pipeline simultáneo
    - Archivo JSON + stderr humano al mismo tiempo
    - Genera logs que van a ambos destinos
    - Compara output en stderr vs archivo JSON
    - Verifica que formatos son diferentes pero contenido igual
    - Demuestra independencia de los pipelines

  - Output formateado con:
    - Headers con caracteres box drawing
    - Separadores visuales
    - Notas técnicas al final
    - Explicación de cada test

**Integración CLI**:
- `src/architect/cli.py` - CLI actualizado para usar logging completo
  - Import actualizado: `from .logging import configure_logging`
  - Configuración temprana de logging (después de load_config)
  - Llamada a `configure_logging()` con:
    - config.logging (LoggingConfig completo)
    - json_output desde CLI args
    - quiet desde CLI args
  - Logging configurado ANTES de crear componentes
  - Todos los componentes pueden usar get_logger() desde el inicio
  - Flags CLI pasados correctamente:
    - --verbose (count) → config.logging.verbose
    - --log-file → config.logging.file
    - --log-level → config.logging.level
    - --json → json_output parameter
    - --quiet → quiet parameter

- `src/architect/logging/__init__.py` - Exports actualizados
  - Mantiene exports anteriores para compatibilidad
  - configure_logging_basic() disponible
  - get_logger() como interfaz principal

#### Características Implementadas

- ✅ Dual pipeline completo (archivo JSON + stderr humano)
- ✅ Verbose levels progresivos (0-3+)
- ✅ Quiet mode funcional (solo errores)
- ✅ JSON Lines format para archivos
- ✅ Console renderer con colores automáticos
- ✅ Logs a stderr (stdout libre para pipes)
- ✅ Configuración vía Pydantic (type-safe)
- ✅ Procesadores compartidos entre pipelines
- ✅ Backward compatibility con configure_logging_basic()
- ✅ Suite de pruebas completa (5 tests)
- ✅ Integración completa con CLI

#### Mejoras

- 🔄 Sistema de logging profesional y robusto
- 🔄 Debugging incremental con -v, -vv, -vvv
- 🔄 Logs estructurados para análisis automatizado
- 🔄 Output humano para desarrollo y debugging
- 🔄 Compatible con pipes y redirecciones
- 🔄 Colores solo cuando tiene sentido (TTY detection)

#### Uso

```bash
# Logging normal (INFO level, -v)
architect run "analiza proyecto" -v

# Debugging detallado (DEBUG level, -vv)
architect run "construye módulo" -a build -vv

# Debugging completo (DEBUG+, -vvv)
architect run "tarea compleja" -vvv

# Modo silencioso (solo errores)
architect run "deploy" --quiet

# Con archivo de logs JSON
architect run "refactoriza" -v --log-file logs/session.jsonl

# Analizar logs después
cat logs/session.jsonl | jq -r 'select(.event=="tool.call") | .tool'
```

```yaml
# config.yaml
logging:
  level: info
  verbose: 1
  file: logs/architect.jsonl
```

#### Notas Técnicas

- Logs van a stderr, output final a stdout (compatible con pipes)
- JSON Lines (`.jsonl`): un JSON por línea, fácil de parsear línea a línea
- Dual pipeline usa ProcessorFormatter de structlog
- Procesadores compartidos aseguran consistencia
- Colores automáticos con `sys.stderr.isatty()` detection
- Verbose progresivo: WARNING → INFO → DEBUG → DEBUG completo
- Quiet mode útil para CI/CD (solo errores)
- File logging captura todo (DEBUG), stderr se filtra
- Backward compatible con fases anteriores

#### Próxima Fase

F6 - CLI Streaming (Día 9-10)

---

## [0.5.0] - 2026-02-18

### Fase 4 - MCP Connector ✅

#### Agregado

**Cliente MCP (JSON-RPC 2.0)**:
- `src/architect/mcp/client.py` - Cliente HTTP completo para servidores MCP
  - Clase `MCPClient` - Cliente con protocolo JSON-RPC 2.0
  - Método `list_tools()` - Lista tools vía método 'tools/list'
    - Request JSON-RPC con id=1
    - Parsing de respuesta con manejo de errores
    - Retorna lista de definiciones de tools
  - Método `call_tool()` - Ejecuta tool vía método 'tools/call'
    - Request JSON-RPC con params: {name, arguments}
    - Manejo de errores RPC (error.code, error.message)
    - Retorna resultado de ejecución
  - Autenticación Bearer token:
    - Desde config.token (directo)
    - Desde variable de entorno (config.token_env)
    - Header: Authorization: Bearer {token}
  - Cliente httpx configurado:
    - base_url desde config
    - timeout: 30.0s
    - follow_redirects: true
    - Content-Type: application/json
  - Manejo robusto de errores:
    - `MCPError` - Error base
    - `MCPConnectionError` - Errores de conexión HTTP
    - `MCPToolCallError` - Errores de ejecución
  - Context manager support (__enter__, __exit__)
  - Logging estructurado:
    - mcp.client.initialized
    - mcp.list_tools.start/success
    - mcp.call_tool.start/success
    - mcp.*.connection_error, rpc_error

**MCP Tool Adapter**:
- `src/architect/mcp/adapter.py` - Adapter de tools MCP a BaseTool
  - Clase `MCPToolAdapter` - Hereda de BaseTool
  - Naming con prefijo: `mcp_{server}_{tool}` para evitar colisiones
  - Atributos:
    - name: nombre prefijado
    - description: desde tool_definition
    - sensitive: true (MCP tools son sensibles por defecto)
    - args_model: Pydantic generado dinámicamente
  - Método `_build_args_model()` - Genera Pydantic desde JSON Schema
    - Lee inputSchema.properties
    - Lee inputSchema.required
    - Crea campos con tipos apropiados
    - Usa create_model() de Pydantic
    - Campos opcionales: tipo | None con default None
    - Campos requeridos: tipo con ... (ellipsis)
  - Método `_json_schema_type_to_python()` - Mapeo de tipos:
    - string → str
    - integer → int
    - number → float
    - boolean → bool
    - array → list
    - object → dict
  - Método `execute()` - Ejecuta vía MCPClient
    - Delega a client.call_tool()
    - Extrae contenido con _extract_content()
    - Manejo de errores sin excepciones (ToolResult)
  - Método `_extract_content()` - Extracción robusta de resultados
    - Soporte para content como list (múltiples bloques)
    - Soporte para content como string
    - Soporte para content como dict
    - Fallbacks: output, result, JSON dump completo
    - Concatenación de bloques de texto

**Descubrimiento MCP**:
- `src/architect/mcp/discovery.py` - Sistema de descubrimiento automático
  - Clase `MCPDiscovery` - Descubridor y registrador
  - Método `discover_and_register()` - Proceso completo:
    - Itera sobre lista de MCPServerConfig
    - Para cada servidor:
      1. Crea MCPClient
      2. Lista tools con client.list_tools()
      3. Para cada tool: crea MCPToolAdapter y registra
      4. Si error: log warning y continúa (no rompe)
    - Retorna estadísticas:
      - servers_total, servers_success, servers_failed
      - tools_discovered, tools_registered
      - errors: lista de mensajes de error
  - Método `discover_server_info()` - Info sin registrar (diagnóstico)
    - Conecta y lista tools
    - Retorna dict con info: connected, tools_count, tools, error
    - Útil para testing y troubleshooting
  - Logging estructurado:
    - mcp.discovery.start/complete
    - mcp.discovery.server_start
    - mcp.discovery.tools_found
    - mcp.discovery.tool_registered
    - mcp.discovery.server_failed

**Testing**:
- `scripts/test_phase4.py` - Suite completa de pruebas MCP
  - Prueba 1: MCPClient directo
    - Conecta a servidor (localhost:3000)
    - Lista tools
    - Ejecuta una tool
  - Prueba 2: MCPDiscovery
    - Descubre de múltiples servidores
    - Muestra estadísticas
    - Lista tools en registry
  - Prueba 3: MCPToolAdapter
    - Crea adapter con tool definition mock
    - Verifica modelo de argumentos
    - Verifica schema para LLM
  - Prueba 4: Server info
    - Obtiene info sin registrar
    - Muestra connected, tools, error
  - Notas sobre cómo configurar servidor MCP real

**Integración CLI**:
- `src/architect/cli.py` - CLI actualizado con MCP
  - Import de MCPDiscovery
  - Descubrimiento automático después de filesystem tools:
    - Solo si NOT --disable-mcp
    - Solo si config.mcp.servers no vacío
    - Muestra mensaje: "🔌 Descubriendo tools MCP..."
    - Muestra resultado:
      - "✓ X tools MCP registradas desde Y servidor(es)"
      - "⚠️ Z servidor(es) no disponible(s)" (warning, no error)
  - Sistema gracefully degraded:
    - Si MCP falla, continúa con tools locales
    - No rompe la ejecución
  - Versión actualizada a v0.5.0

- `src/architect/mcp/__init__.py` - Exports completos

#### Características Implementadas

- ✅ Cliente MCP completo con JSON-RPC 2.0
- ✅ Autenticación Bearer token (directo o env var)
- ✅ Adapter que hace tools MCP indistinguibles de locales
- ✅ Generación dinámica de Pydantic desde JSON Schema
- ✅ Descubrimiento automático multi-servidor
- ✅ Estadísticas detalladas de descubrimiento
- ✅ Manejo robusto de errores (nunca rompe)
- ✅ Graceful degradation (funciona sin MCP)
- ✅ Logging estructurado completo
- ✅ Support para --disable-mcp flag

#### Mejoras

- 🔄 Sistema extensible con tools remotas
- 🔄 Tools MCP tratadas idénticamente a locales
- 🔄 Naming prefijado evita colisiones
- 🔄 Continúa funcionando si servidores MCP no disponibles

#### Uso

```yaml
# config.yaml
mcp:
  servers:
    - name: github
      url: http://localhost:3000
      token_env: GITHUB_MCP_TOKEN

    - name: database
      url: https://mcp.example.com/db
      token: hardcoded-token  # No recomendado
```

```bash
# Uso automático (tools MCP disponibles para agentes)
architect run "usa la tool X del servidor github" --mode yolo

# Deshabilitar MCP
architect run "tarea normal" --disable-mcp
```

#### Notas Técnicas

- JSON-RPC 2.0 estricto (jsonrpc: "2.0", id, method, params)
- Tools MCP son sensitive=true por defecto (operaciones remotas)
- Adapter crea Pydantic models dinámicos (validación automática)
- Descubrimiento es fail-safe (logs + continúa)
- Cliente HTTP con httpx (async-ready para futuro)

#### Próxima Fase

F5 - Logging Completo (Día 8-9)

---

## [0.4.0] - 2026-02-18

### Fase 3 - Sistema de Agentes ✅

#### Agregado

**Prompts de Agentes**:
- `src/architect/agents/prompts.py` - System prompts especializados por agente
  - `PLAN_PROMPT` - Agente de planificación y análisis
    - Enfoque en descomposición de tareas
    - Identificación de archivos y pasos
    - Formato estructurado: resumen, pasos, archivos, consideraciones
  - `BUILD_PROMPT` - Agente de construcción y modificación
    - Flujo incremental: leer → modificar → verificar
    - Énfasis en cambios conservadores
    - Verificación post-modificación
  - `RESUME_PROMPT` - Agente de análisis y resumen
    - Solo lectura (no modificación)
    - Análisis estructurado de proyectos
    - Output organizado con bullet points
  - `REVIEW_PROMPT` - Agente de revisión de código
    - Feedback constructivo y accionable
    - Priorización de problemas (crítico/importante/menor)
    - Aspectos: bugs, seguridad, performance, código limpio
  - `DEFAULT_PROMPTS` - Dict mapeando nombres a prompts

**Agent Registry**:
- `src/architect/agents/registry.py` - Sistema de gestión de agentes
  - `DEFAULT_AGENTS` - Dict con 4 agentes pre-configurados:
    - plan: confirm-all, read-only, 10 steps
    - build: confirm-sensitive, full access, 20 steps
    - resume: yolo, read-only, 10 steps
    - review: yolo, read-only, 15 steps
  - Función `get_agent()` - Resolución con merge multi-fuente
    - Precedencia: defaults → YAML → CLI overrides
    - Merge selectivo (solo campos especificados)
    - Validación con AgentNotFoundError descriptivo
  - Función `list_available_agents()` - Lista defaults + YAML
  - Función `resolve_agents_from_yaml()` - Convierte y valida YAML
  - Función `_merge_agent_config()` - Merge inteligente de configs
  - Función `_apply_cli_overrides()` - Aplica --mode y --max-steps
  - Clase `AgentNotFoundError` - Error con agentes disponibles

**Mixed Mode Runner**:
- `src/architect/core/mixed_mode.py` - Modo plan → build automático
  - Clase `MixedModeRunner` - Orquestador de flujo dual
  - Método `run()` - Ejecuta flujo completo:
    1. Fase plan: analiza tarea con agente plan
    2. Si plan falla → retorna estado de plan
    3. Fase build: ejecuta con prompt enriquecido
  - Método `_build_enriched_prompt()` - Construye contexto con plan
  - Prompt enriquecido incluye:
    - Petición original del usuario
    - Plan generado (completo)
    - Instrucciones para seguir el plan
  - Logging estructurado de ambas fases:
    - mixed_mode.start/complete
    - mixed_mode.phase.plan/build
    - mixed_mode.plan_complete
  - Manejo de plan sin output (fallback)

**Testing**:
- `scripts/test_phase3.py` - Suite completa de pruebas
  - Prueba 1: Registry de agentes (sin API key)
    - Lista DEFAULT_AGENTS
    - Prueba list_available_agents()
    - Prueba get_agent()
  - Prueba 2: Single agent mode con 'review'
    - Configuración completa
    - Ejecución con prompt real
    - Requiere API key
  - Prueba 3: Mixed mode plan→build
    - Configuración de ambos agentes
    - Dry-run habilitado
    - Flujo completo
    - Requiere API key

**Integración CLI**:
- `src/architect/cli.py` - CLI actualizado con sistema completo
  - Import de módulo agents (DEFAULT_AGENTS, get_agent, etc.)
  - Detección automática de mixed mode (sin --agent)
  - Flujo diferenciado:
    - Mixed mode: crea plan_engine + build_engine, ejecuta MixedModeRunner
    - Single agent: crea engine + loop, ejecuta AgentLoop
  - Selección de agente con validación:
    - get_agent() con manejo de AgentNotFoundError
    - Mensaje de error con lista de agentes disponibles
  - CLI overrides aplicados a agentes:
    - --mode → confirm_mode
    - --max-steps → max_steps
  - Output diferenciado:
    - Mixed mode: "🔀 Modo: mixto (plan → build)"
    - Single agent: "🎭 Agente: {nombre}"
  - Versión actualizada a v0.4.0

- `src/architect/agents/__init__.py` - Exports completos
- `src/architect/core/__init__.py` - Export de MixedModeRunner

#### Características Implementadas

- ✅ 4 agentes especializados pre-configurados
- ✅ Sistema de prompts especializados por rol
- ✅ Registry con merge multi-fuente (defaults → YAML → CLI)
- ✅ Mixed mode automático plan→build
- ✅ CLI con detección automática de modo
- ✅ Validación de agentes con mensajes útiles
- ✅ Soporte completo para agentes custom en YAML
- ✅ CLI overrides funcionando (--mode, --max-steps)

#### Mejoras

- 🔄 CLI ahora tiene comportamiento inteligente por defecto (mixed mode)
- 🔄 Agentes especializados para diferentes casos de uso
- 🔄 Sistema extensible para agentes custom
- 🔄 Merge selectivo permite sobrescribir solo lo necesario

#### Uso

```bash
# Modo mixto automático (plan → build)
architect run "refactoriza el módulo de config"

# Agente específico
architect run "analiza este proyecto" -a review
architect run "lee y resume main.py" -a resume
architect run "modifica config.yaml" -a build --mode yolo

# Override de configuración
architect run "tarea compleja" -a build --max-steps 30

# Con agente custom desde YAML
architect run "deploy a producción" -a deploy
```

#### Notas Técnicas

- Prompts diseñados para ser claros, directivos y especializados
- Mixed mode enriquece el prompt de build con el plan completo
- Registry permite defaults + YAML + CLI sin conflictos
- Agentes custom pueden sobrescribir defaults parcialmente
- Logging diferenciado entre mixed mode y single agent

#### Próxima Fase

F4 - MCP Connector (Día 6-8)

---

## [0.3.0] - 2026-02-18

### Fase 2 - LLM Adapter + Agent Loop ✅

#### Agregado

**LLM Adapter:**
- `src/architect/llm/adapter.py` - Adapter completo para LiteLLM
  - `LLMAdapter` - Clase principal con configuración y retries
  - `LLMResponse` (Pydantic) - Respuesta normalizada del LLM
  - `ToolCall` (Pydantic) - Representación de tool calls
  - Configuración automática de LiteLLM (mode: direct/proxy)
  - Gestión de API keys desde variables de entorno
  - Retries automáticos con tenacity (exponential backoff)
  - 3 intentos máximo (1 original + 2 retries)
  - Wait times: mín 2s, máx 30s, multiplicador 1
  - Normalización de respuestas de cualquier proveedor a formato interno
  - Soporte completo para OpenAI function/tool calling
  - Parsing robusto de argumentos (JSON string o dict)
  - Logging estructurado de todas las operaciones
  - Supresión de debug info de LiteLLM
  - Manejo de timeout configurable

- `src/architect/llm/__init__.py` - Exports del módulo LLM

**Agent State:**
- `src/architect/core/state.py` - Estructuras de datos inmutables
  - `AgentState` (dataclass) - Estado mutable del agente
    - messages: historial completo de mensajes
    - steps: lista de StepResult ejecutados
    - status: running | success | partial | failed
    - final_output: respuesta final del agente
    - Propiedades: current_step, total_tool_calls, is_finished
    - Método to_output_dict() para serialización JSON
  - `StepResult` (dataclass frozen) - Resultado inmutable de un step
    - step_number, llm_response, tool_calls_made, timestamp
  - `ToolCallResult` (dataclass frozen) - Resultado de tool call
    - tool_name, args, result, was_confirmed, was_dry_run, timestamp

**Context Builder:**
- `src/architect/core/context.py` - Constructor de mensajes para LLM
  - `ContextBuilder` - Clase para construir contexto OpenAI
  - Método `build_initial()` - Crea mensajes iniciales (system + user)
  - Método `append_tool_results()` - Añade resultados de tools
    - Formato correcto OpenAI: assistant message con tool_calls
    - Seguido de tool messages con resultados
    - IDs de tool calls correctamente mapeados
  - Método `append_assistant_message()` - Añade respuesta del assistant
  - Método `append_user_message()` - Añade mensaje del usuario
  - Soporte para dry-run en mensajes de tools
  - Serialización correcta de argumentos a JSON

**Agent Loop:**
- `src/architect/core/loop.py` - Ciclo principal del agente
  - `AgentLoop` - Clase principal del loop
  - Método `run()` - Ejecuta el ciclo completo:
    1. Enviar mensajes al LLM con tools disponibles
    2. Recibir respuesta (content o tool_calls)
    3. Si hay tool_calls, ejecutarlas todas
    4. Añadir resultados a mensajes
    5. Repetir hasta terminar o alcanzar max_steps
  - Detección de terminación correcta (finish_reason="stop" sin tool_calls)
  - Ejecución de múltiples tool calls en un solo step
  - Manejo de errores del LLM (status=failed)
  - Manejo de límite de pasos (status=partial)
  - Manejo de finish_reason="length" (continuar)
  - Logging estructurado de cada paso:
    - agent.loop.start/complete
    - agent.step.start
    - agent.tool_calls_received
    - agent.tool_call.execute/complete
    - agent.complete
    - agent.max_steps_reached
  - Sanitización de argumentos largos para logs
  - Integración completa con LLMAdapter y ExecutionEngine

- `src/architect/core/__init__.py` - Exports del módulo core

**Testing:**
- `scripts/test_phase2.py` - Script de prueba del agent loop completo
  - Configura LLMAdapter con modelo económico (gpt-4o-mini)
  - Crea agente simple con read_file y list_files
  - Ejecuta tarea: listar .md y leer README.md
  - Muestra resultados detallados con steps y tool calls
  - Requiere API key configurada (LITELLM_API_KEY)

**Integración CLI:**
- `src/architect/cli.py` - CLI actualizado con agent loop funcional
  - Import de todos los módulos necesarios (core, llm, execution, tools, logging)
  - Configuración de logging en cada ejecución
  - Creación de agente simple por defecto (TODO: fase 3 para agentes configurables)
  - System prompt por defecto razonable
  - allowed_tools: read_file, write_file, list_files, delete_file
  - Inicialización de tool registry con filesystem tools
  - Creación de ExecutionEngine con confirm_mode del CLI
  - Configuración de dry-run si está habilitado
  - Creación de LLMAdapter con configuración cargada
  - Creación de ContextBuilder y AgentLoop
  - Ejecución completa del agent loop con run()
  - Output formateado:
    - Header con info de configuración
    - Resultado final del agente
    - Estadísticas (status, steps, tool_calls)
  - Soporte para --json output
  - Códigos de salida correctos: 0 (success), 1 (failed), 2 (partial)

#### Características Implementadas

- ✅ LLMAdapter completo con LiteLLM y retries
- ✅ Normalización de respuestas multi-provider
- ✅ Agent state inmutable para debugging
- ✅ Context builder con formato OpenAI correcto
- ✅ Agent loop completo y funcional
- ✅ Manejo robusto de errores en todos los niveles
- ✅ Integración completa con ExecutionEngine de Fase 1
- ✅ CLI funcional end-to-end
- ✅ Logging estructurado completo
- ✅ Soporte para dry-run
- ✅ Códigos de salida apropiados

#### Mejoras

- 🔄 CLI ahora ejecuta tareas reales (antes solo mostraba config)
- 🔄 Sistema completamente funcional end-to-end
- 🔄 Manejo de múltiples tool calls por step
- 🔄 Detección inteligente de terminación

#### Notas Técnicas

- Formato OpenAI usado para tool calling (compatible con todos los providers via LiteLLM)
- Agent state es parcialmente inmutable (steps y results son frozen, state es mutable)
- Retries configurables via tenacity con backoff exponencial
- Logging estructurado en todos los componentes
- Streaming se implementará en Fase 6

#### Próxima Fase

F3 - Sistema de Agentes (Día 5-6)

---

## [0.2.0] - 2026-02-18

### Fase 1 - Tools y Execution Engine ✅

#### Agregado

**Sistema de Tools:**
- `src/architect/tools/base.py` - Clase base abstracta para todas las tools
  - `BaseTool` (ABC) con métodos: execute(), get_schema(), validate_args()
  - `ToolResult` (Pydantic) para resultados estructurados (success, output, error)
  - Generación automática de JSON Schema compatible con OpenAI function calling
  - Sistema de marcado de tools sensibles (sensitive=True/False)

- `src/architect/tools/schemas.py` - Modelos Pydantic para argumentos de tools
  - `ReadFileArgs` - Path del archivo a leer
  - `WriteFileArgs` - Path, content, mode (overwrite/append)
  - `DeleteFileArgs` - Path del archivo a eliminar
  - `ListFilesArgs` - Path, pattern (glob), recursive
  - Validación automática y mensajes de error claros

- `src/architect/tools/filesystem.py` - Tools para operaciones del filesystem
  - `ReadFileTool` - Lee archivos UTF-8 con validación de path
  - `WriteFileTool` - Escribe archivos (overwrite/append), crea directorios padres
  - `DeleteFileTool` - Elimina archivos, requiere allow_delete=true
  - `ListFilesTool` - Lista archivos/directorios, soporta glob y recursión
  - Todas las tools con manejo robusto de errores (nunca lanzan excepciones)
  - Mensajes de error descriptivos y accionables

- `src/architect/tools/registry.py` - Registro centralizado de tools
  - `ToolRegistry` - Clase para gestionar todas las tools disponibles
  - Métodos: register(), get(), list_all(), get_schemas(), filter_by_names()
  - Detección de duplicados con DuplicateToolError
  - Mensajes de error con sugerencias de tools disponibles
  - Generación de schemas filtrados por allowed_tools

- `src/architect/tools/setup.py` - Helpers para inicialización
  - `register_filesystem_tools()` - Registra todas las tools del filesystem
  - Configuración automática basada en WorkspaceConfig

**Sistema de Validación y Seguridad:**
- `src/architect/execution/validators.py` - Validadores críticos de seguridad
  - `validate_path()` - Prevención de path traversal (../../etc/passwd)
  - Usa Path.resolve() para resolver symlinks y paths relativos
  - Verifica confinamiento al workspace con is_relative_to()
  - `validate_file_exists()` - Verifica existencia de archivos
  - `validate_directory_exists()` - Verifica existencia de directorios
  - `ensure_parent_directory()` - Crea directorios padres automáticamente
  - Excepciones: PathTraversalError, ValidationError con mensajes claros

**Sistema de Políticas de Confirmación:**
- `src/architect/execution/policies.py` - Políticas de confirmación de acciones
  - `ConfirmationPolicy` - Tres modos: yolo, confirm-all, confirm-sensitive
  - Método `should_confirm()` - Determina si requiere confirmación
  - Método `request_confirmation()` - Prompt interactivo al usuario
  - Detección de TTY para entornos headless (CI, cron, pipelines)
  - `NoTTYError` con mensaje claro y soluciones para CI/CD
  - Prompts con opciones: y (sí), n (no), a (abortar todo)
  - Sanitización de argumentos largos para mostrar al usuario
  - Soporte para dry-run (skip confirmación en simulaciones)

**Execution Engine:**
- `src/architect/execution/engine.py` - Motor central de ejecución de tools
  - `ExecutionEngine` - Orquestador con pipeline completo:
    1. Buscar tool en registry
    2. Validar argumentos con Pydantic
    3. Aplicar política de confirmación
    4. Ejecutar (o simular en dry-run)
    5. Loggear resultado con structlog
    6. Retornar ToolResult (nunca excepciones)
  - Método `execute_tool_call()` - Ejecución con manejo robusto de errores
  - Método `set_dry_run()` - Habilitar/deshabilitar simulación
  - Integración completa con ToolRegistry y ConfirmationPolicy
  - Logging estructurado de todas las operaciones
  - Sanitización de argumentos largos para logs
  - Captura defensiva de excepciones inesperadas

**Sistema de Logging:**
- `src/architect/logging/setup.py` - Configuración básica de structlog
  - `configure_logging_basic()` - Setup mínimo para desarrollo
  - Procesadores: contextvars, log_level, timestamp, console_renderer
  - Output a stderr (no rompe pipes)
  - Base para logging completo de Fase 5

**Testing y Validación:**
- `scripts/test_phase1.py` - Script de prueba completo de Fase 1
  - Prueba de ToolRegistry y registro de tools
  - Prueba de ExecutionEngine con modo yolo
  - Prueba de list_files con patrones glob
  - Prueba de read_file con archivo real
  - Prueba de dry-run mode
  - Prueba de validación de path traversal (seguridad)
  - Prueba de delete sin allow_delete
  - Prueba de generación de schemas para LLM
  - Output formateado y legible

**Exports y Módulos:**
- `src/architect/tools/__init__.py` - Exports completos del módulo tools
- `src/architect/execution/__init__.py` - Exports completos del módulo execution
- `src/architect/logging/__init__.py` - Exports del módulo logging

#### Características Implementadas

- ✅ Sistema completo de tools con 4 tools del filesystem
- ✅ ToolRegistry con gestión, filtrado y generación de schemas
- ✅ Validación robusta de paths con prevención de path traversal
- ✅ Políticas de confirmación configurables (yolo/confirm-all/confirm-sensitive)
- ✅ ExecutionEngine con pipeline completo y manejo de errores
- ✅ Soporte para dry-run (simulación sin efectos secundarios)
- ✅ Detección de entornos headless con mensajes claros
- ✅ Logging estructurado con structlog
- ✅ Integración completa entre todos los componentes
- ✅ Script de prueba funcional

#### Seguridad

- 🔒 Validación estricta de paths con Path.resolve()
- 🔒 Prevención de path traversal attacks
- 🔒 Confinamiento obligatorio al workspace
- 🔒 Tools sensibles requieren confirmación (configurable)
- 🔒 delete_file requiere allow_delete=true explícito
- 🔒 Manejo defensivo de excepciones (nunca crash)

#### Próxima Fase

F2 - LLM Adapter + Agent Loop (Día 3-5)

---

## [0.1.0] - 2026-02-18

### Fase 0 - Scaffolding y Configuración ✅

#### Agregado

**Infraestructura del Proyecto:**
- `pyproject.toml` - Configuración del proyecto usando hatchling como build backend
  - Dependencias: click, pyyaml, pydantic, litellm, httpx, structlog, tenacity
  - Scripts: comando `architect` disponible globalmente
  - Requerimiento: Python >=3.12
  - Dependencias opcionales de desarrollo (pytest, black, ruff, mypy)

**Sistema de Configuración:**
- `src/architect/config/schema.py` - Modelos Pydantic v2 para validación de configuración
  - `LLMConfig` - Configuración del proveedor LLM (modelo, API, timeouts, retries)
  - `AgentConfig` - Configuración de agentes (system prompt, tools, confirm_mode, max_steps)
  - `LoggingConfig` - Configuración de logging (level, file, verbose)
  - `WorkspaceConfig` - Configuración del workspace (root, allow_delete)
  - `MCPConfig` y `MCPServerConfig` - Configuración de servidores MCP
  - `AppConfig` - Configuración raíz que combina todas las secciones

- `src/architect/config/loader.py` - Cargador de configuración con deep merge
  - Función `deep_merge()` para merge recursivo de diccionarios
  - Función `load_yaml_config()` para cargar archivos YAML
  - Función `load_env_overrides()` para variables de entorno (ARCHITECT_*)
  - Función `apply_cli_overrides()` para argumentos CLI
  - Función `load_config()` - Pipeline completo: defaults → YAML → env → CLI → validación
  - Orden de precedencia correctamente implementado

- `src/architect/config/__init__.py` - Exports del módulo de configuración

**CLI (Command Line Interface):**
- `src/architect/cli.py` - CLI principal usando Click
  - Grupo principal `architect` con version option
  - Comando `run` con 20+ opciones configurables:
    - Configuración: `-c/--config`, `-a/--agent`, `-m/--mode`, `-w/--workspace`
    - Ejecución: `--dry-run`
    - LLM: `--model`, `--api-base`, `--api-key`, `--no-stream`, `--timeout`
    - MCP: `--mcp-config`, `--disable-mcp`
    - Logging: `-v/--verbose`, `--log-level`, `--log-file`
    - Output: `--json`, `--quiet`, `--max-steps`
  - Comando `validate-config` para validar archivos de configuración
  - Manejo de errores con códigos de salida apropiados
  - Soporte para salida JSON estructurada
  - Modo verbose para debugging

- `src/architect/__init__.py` - Inicialización del paquete con `__version__`
- `src/architect/__main__.py` - Entry point para `python -m architect`

**Documentación y Ejemplos:**
- `config.example.yaml` - Archivo de ejemplo completo con:
  - Configuración de LLM con múltiples ejemplos de modelos
  - Ejemplos de agentes custom (deploy, documenter)
  - Configuración de logging y workspace
  - Ejemplos de servidores MCP
  - Comentarios extensivos explicando cada sección
  - Notas sobre precedencia de configuración

**Estructura del Proyecto:**
- Estructura completa de directorios creada:
  - `src/architect/` - Código fuente principal
  - `src/architect/config/` - Sistema de configuración
  - `src/architect/agents/` - Sistema de agentes (preparado)
  - `src/architect/core/` - Agent loop y estado (preparado)
  - `src/architect/llm/` - Adapter de LLM (preparado)
  - `src/architect/tools/` - Tools del sistema (preparado)
  - `src/architect/mcp/` - Cliente MCP (preparado)
  - `src/architect/execution/` - Execution engine (preparado)
  - `src/architect/logging/` - Sistema de logging (preparado)
  - `tests/` - Tests (estructura preparada)
  - `scripts/` - Scripts auxiliares

**Control de Versiones:**
- `.gitignore` - Configuración completa para Python, IDEs, logs, config sensibles

**Seguimiento:**
- `SEGUIMIENTO.md` - Documento de seguimiento de implementación por fases
- `CHANGELOG.md` - Este archivo para documentar cambios

#### Características Implementadas

- ✅ Sistema de configuración completo con validación Pydantic
- ✅ Deep merge de configuración (YAML + env + CLI)
- ✅ CLI funcional con Click y 20+ opciones
- ✅ Estructura modular preparada para todas las fases
- ✅ Documentación inline completa
- ✅ Type hints en todo el código
- ✅ Manejo de errores con códigos de salida apropiados

#### Notas Técnicas

- Arquitectura sync-first según plan (async solo donde sea necesario)
- No se usa LangChain/LangGraph (según decisión técnica del plan)
- Pydantic v2 con `extra="forbid"` para validación estricta
- Python 3.12+ requerido (pattern matching, typing moderno, tomllib nativo)

#### Próxima Fase

F1 - Tools y Execution Engine (Día 2-3)
