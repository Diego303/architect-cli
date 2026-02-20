# 📋 Seguimiento de Implementación - architect CLI

Este documento registra el progreso de implementación del proyecto architect siguiendo el plan definido en `Plan_Implementacion.md`.

---

## Estado General

- **Inicio**: 2026-02-18
- **Fase Actual**: F12 Completada — Self-Evaluation (Critic Agent)
- **Estado**: ✅ v0.12.0 — SelfEvaluator (basic + full) + --self-eval CLI flag

---

## Fases Completadas

### ✅ F0 - Scaffolding y Configuración (Completada: 2026-02-18)

**Objetivo**: Proyecto instalable con `pip install -e .`, CLI que responde a `--help`, config cargando correctamente.

**Progreso**: 100%

#### Tareas Completadas
- [x] 0.1 - Crear pyproject.toml
- [x] 0.2 - Implementar Schema de Configuración (Pydantic)
- [x] 0.3 - Implementar Config Loader (deep merge)
- [x] 0.4 - Implementar CLI base (Click)
- [x] 0.5 - Crear estructura de directorios completa
- [x] 0.6 - Crear config.example.yaml

#### Archivos Creados
- `pyproject.toml` - Configuración del proyecto con hatchling
- `src/architect/config/schema.py` - Modelos Pydantic para configuración
- `src/architect/config/loader.py` - Cargador de configuración con deep merge
- `src/architect/config/__init__.py` - Exports del módulo config
- `src/architect/cli.py` - CLI principal con Click
- `src/architect/__init__.py` - Inicialización del paquete
- `src/architect/__main__.py` - Entry point para `python -m architect`
- `config.example.yaml` - Archivo de ejemplo de configuración
- `.gitignore` - Configuración de archivos ignorados
- Estructura completa de directorios para todas las fases

#### Entregable
✅ `pip install -e .` funciona, `architect run --help` muestra ayuda, `architect run "test" -c config.yaml` carga config y la imprime en debug.

---

### ✅ F1 - Tools y Execution Engine (Completada: 2026-02-18)

**Objetivo**: Sistema de tools local funcional con validación, políticas de confirmación y dry-run.

**Progreso**: 100%

#### Tareas Completadas
- [x] 1.1 - Base Tool (ABC)
- [x] 1.2 - Schemas de Tools (Pydantic)
- [x] 1.3 - Validación de Paths (Seguridad)
- [x] 1.4 - Tools del Filesystem
- [x] 1.5 - Tool Registry
- [x] 1.6 - Políticas de Confirmación
- [x] 1.7 - Execution Engine
- [x] 1.8 - Setup de logging básico

#### Archivos Creados
- `src/architect/tools/base.py` - BaseTool (ABC) y ToolResult
- `src/architect/tools/schemas.py` - Modelos Pydantic para argumentos
- `src/architect/tools/filesystem.py` - 4 tools (read_file, write_file, delete_file, list_files)
- `src/architect/tools/registry.py` - ToolRegistry con métodos de gestión
- `src/architect/tools/setup.py` - Helper para registrar filesystem tools
- `src/architect/tools/__init__.py` - Exports del módulo tools
- `src/architect/execution/validators.py` - Validación de paths con seguridad
- `src/architect/execution/policies.py` - Políticas de confirmación (yolo, confirm-all, confirm-sensitive)
- `src/architect/execution/engine.py` - ExecutionEngine central
- `src/architect/execution/__init__.py` - Exports del módulo execution
- `src/architect/logging/setup.py` - Configuración básica de structlog
- `src/architect/logging/__init__.py` - Exports del módulo logging
- `scripts/test_phase1.py` - Script de prueba de la Fase 1

#### Componentes Implementados

**Tools del Filesystem (4 tools)**:
- `read_file` - Lee archivos con validación de path
- `write_file` - Escribe archivos (overwrite/append) con creación de directorios
- `delete_file` - Elimina archivos con protección configurable
- `list_files` - Lista archivos con soporte para patrones glob y recursión

**ToolRegistry**:
- Registro centralizado de tools
- Métodos: register(), get(), list_all(), get_schemas(), filter_by_names()
- Generación automática de JSON Schema para OpenAI function calling

**Validación de Seguridad**:
- `validate_path()` - Prevención de path traversal (../../etc/passwd)
- Confinamiento al workspace con Path.resolve()
- Validación de existencia de archivos y directorios
- Creación automática de directorios padres

**Políticas de Confirmación**:
- Tres modos: yolo, confirm-all, confirm-sensitive
- Detección de TTY para entornos headless
- Prompts interactivos con opciones y/n/abort
- NoTTYError con mensaje claro para CI/CD

**ExecutionEngine**:
- Pipeline completo: buscar → validar → confirmar → ejecutar → loggear
- Soporte para dry-run (simulación)
- Manejo robusto de errores (nunca lanza excepciones)
- Logging estructurado con structlog
- Sanitización de argumentos largos para logs

#### Entregable
✅ Sistema de tools completo y funcional. `python scripts/test_phase1.py` ejecuta pruebas de todas las tools con validación, políticas y dry-run.

---

### ✅ F2 - LLM Adapter + Agent Loop (Completada: 2026-02-18)

**Objetivo**: Loop de agente completo que envía mensajes al LLM, recibe tool calls, las ejecuta, y devuelve resultados.

**Progreso**: 100%

#### Tareas Completadas
- [x] 2.1 - LLM Adapter con LiteLLM
- [x] 2.2 - Agent State (inmutable)
- [x] 2.3 - Context Builder
- [x] 2.4 - Core Agent Loop
- [x] 2.5 - Integración con CLI

#### Archivos Creados
- `src/architect/llm/adapter.py` - LLMAdapter con LiteLLM, retries y normalización
- `src/architect/llm/__init__.py` - Exports del módulo LLM
- `src/architect/core/state.py` - AgentState, StepResult, ToolCallResult (inmutables)
- `src/architect/core/context.py` - ContextBuilder para mensajes OpenAI
- `src/architect/core/loop.py` - AgentLoop principal con ciclo completo
- `src/architect/core/__init__.py` - Exports del módulo core
- `scripts/test_phase2.py` - Script de prueba del agent loop completo
- `src/architect/cli.py` - Actualizado con integración del agent loop

#### Componentes Implementados

**LLMAdapter**:
- Configuración automática de LiteLLM (direct/proxy mode)
- Gestión de API keys desde variables de entorno
- Retries automáticos con tenacity (backoff exponencial)
- Normalización de respuestas a formato interno (LLMResponse)
- Soporte para tool calling (OpenAI format)
- Logging estructurado de todas las operaciones
- Parsing robusto de argumentos (JSON string o dict)

**Agent State**:
- `AgentState` - Estado mutable del agente con mensajes, steps y status
- `StepResult` - Resultado inmutable de cada step (LLM + tool calls)
- `ToolCallResult` - Resultado inmutable de cada tool call
- Estados: running, success, partial, failed
- Métodos de conveniencia: current_step, total_tool_calls, is_finished
- Método to_output_dict() para serialización JSON

**ContextBuilder**:
- Construcción de mensajes iniciales (system + user)
- Formato OpenAI para tool calling (assistant + tool messages)
- Manejo de tool results con IDs correctos
- Soporte para dry-run en mensajes
- Serialización de argumentos a JSON

**AgentLoop**:
- Loop principal: LLM → tool calls → execute → results → repeat
- Detección de terminación (finish_reason="stop")
- Ejecución de múltiples tool calls por step
- Manejo de límite de pasos (max_steps)
- Manejo robusto de errores del LLM
- Logging estructurado de todo el proceso
- Sanitización de argumentos largos para logs
- Estados finales: success, partial, failed

**Integración CLI**:
- Comando `architect run` completamente funcional
- Configuración de agente simple por defecto
- Soporte para dry-run, quiet, json output
- Códigos de salida correctos (0=success, 1=failed, 2=partial)
- Output formateado y legible

#### Entregable
✅ Agent loop completo funcional. `architect run "crea un archivo hello.txt con 'hola mundo'" --mode yolo` ejecuta la tarea completa (requiere API key configurada).

---

### ✅ F3 - Sistema de Agentes (Completada: 2026-02-18)

**Objetivo**: Agentes configurables desde YAML, modo mixto plan+build por defecto, agentes custom.

**Progreso**: 100%

#### Tareas Completadas
- [x] 3.1 - Prompts de agentes por defecto
- [x] 3.2 - Registry de agentes
- [x] 3.3 - Mixed Mode Runner (plan→build)
- [x] 3.4 - Integración con CLI
- [x] 3.5 - Sistema de merge de configuración

#### Archivos Creados
- `src/architect/agents/prompts.py` - System prompts especializados
- `src/architect/agents/registry.py` - Registry y resolución de agentes
- `src/architect/agents/__init__.py` - Exports del módulo agents
- `src/architect/core/mixed_mode.py` - MixedModeRunner para plan→build
- `src/architect/core/__init__.py` - Actualizado con MixedModeRunner
- `scripts/test_phase3.py` - Script de prueba del sistema de agentes
- `src/architect/cli.py` - Actualizado con sistema completo de agentes

#### Componentes Implementados

**Agentes por Defecto (4 agentes)**:
- `plan` - Análisis y planificación sin ejecución
  - allowed_tools: read_file, list_files
  - confirm_mode: confirm-all
  - max_steps: 10
  - Prompt especializado en descomposición de tareas
- `build` - Construcción y modificación de archivos
  - allowed_tools: read_file, write_file, delete_file, list_files
  - confirm_mode: confirm-sensitive
  - max_steps: 20
  - Prompt especializado en ejecución cuidadosa
- `resume` - Análisis y resumen sin modificación
  - allowed_tools: read_file, list_files
  - confirm_mode: yolo
  - max_steps: 10
  - Prompt especializado en análisis estructurado
- `review` - Revisión de código y mejoras
  - allowed_tools: read_file, list_files
  - confirm_mode: yolo
  - max_steps: 15
  - Prompt especializado en feedback constructivo

**Agent Registry**:
- `DEFAULT_AGENTS` - Dict con 4 agentes pre-configurados
- `get_agent()` - Resuelve agente con merge de fuentes
  - Orden: defaults → YAML → CLI overrides
  - Validación con AgentNotFoundError
- `list_available_agents()` - Lista agentes disponibles
- `resolve_agents_from_yaml()` - Convierte YAML a AgentConfig
- Merge inteligente: sobrescribir solo campos especificados

**Mixed Mode Runner**:
- Flujo automático plan → build
- Fase 1: Ejecuta agente 'plan' con prompt original
- Si plan falla → retorna estado de plan
- Fase 2: Ejecuta agente 'build' con prompt enriquecido
  - Incluye plan generado como contexto
  - Instrucciones para seguir el plan
- Logging estructurado de ambas fases
- Retorna estado final de build

**Integración CLI**:
- Detección automática de modo mixto (sin --agent)
- Selección de agente con --agent
- Merge de CLI overrides (--mode, --max-steps)
- Validación de agentes disponibles con mensajes útiles
- Output diferenciado para mixed mode vs single agent
- Versión actualizada a v0.3.0

#### Entregable
✅ Sistema de agentes completo y funcional.
- `architect run "analiza este proyecto" -a review` usa agente review
- `architect run "refactoriza main.py"` ejecuta plan→build automáticamente
- Agentes custom desde YAML funcionan (merge con defaults)

---

### ✅ F4 - MCP Connector (Completada: 2026-02-18)

**Objetivo**: Conectar a servidores MCP remotos, descubrir tools dinámicamente, y hacerlas indistinguibles de las locales.

**Progreso**: 100%

#### Tareas Completadas
- [x] 4.1 - Cliente HTTP para MCP (JSON-RPC)
- [x] 4.2 - MCP Tool Adapter (BaseTool wrapper)
- [x] 4.3 - Descubrimiento y registro de tools
- [x] 4.4 - Integración con CLI
- [x] 4.5 - Manejo de errores y fallback

#### Archivos Creados
- `src/architect/mcp/client.py` - Cliente HTTP con protocolo JSON-RPC 2.0
- `src/architect/mcp/adapter.py` - MCPToolAdapter (hereda de BaseTool)
- `src/architect/mcp/discovery.py` - MCPDiscovery para registro automático
- `src/architect/mcp/__init__.py` - Exports del módulo MCP
- `scripts/test_phase4.py` - Suite de pruebas del sistema MCP
- `src/architect/cli.py` - Actualizado con descubrimiento MCP

#### Componentes Implementados

**MCPClient (JSON-RPC 2.0)**:
- Protocolo completo JSON-RPC 2.0 sobre HTTP
- Método `list_tools()` - Lista tools disponibles en servidor
- Método `call_tool()` - Ejecuta tool remota con argumentos
- Autenticación con Bearer token
  - Desde config directo (token)
  - Desde variable de entorno (token_env)
- Cliente HTTP con httpx
  - Timeout: 30s
  - Follow redirects
  - Headers personalizados
- Manejo robusto de errores:
  - MCPConnectionError para errores de conexión
  - MCPToolCallError para errores de ejecución
  - Logging estructurado de todas las operaciones
- Context manager support (with statement)

**MCPToolAdapter**:
- Hereda de BaseTool (interfaz idéntica a tools locales)
- Naming: `mcp_{server}_{tool}` para evitar colisiones
- Generación dinámica de Pydantic model desde JSON Schema
  - Método `_build_args_model()` - Convierte inputSchema a Pydantic
  - Método `_json_schema_type_to_python()` - Mapeo de tipos
  - Soporte para campos requeridos y opcionales
- Ejecución delegada al MCPClient
- Extracción robusta de contenido de respuestas MCP
  - Soporte para múltiples formatos de resultado
  - content como string, list, o dict
  - Fallbacks para compatibilidad
- Tools MCP marcadas como sensitive por defecto
- Manejo de errores sin excepciones (ToolResult)

**MCPDiscovery**:
- Método `discover_and_register()` - Descubre de múltiples servidores
  - Itera sobre lista de MCPServerConfig
  - Conecta a cada servidor y lista tools
  - Registra tools en ToolRegistry
  - Continúa en caso de error (no rompe por un servidor caído)
  - Retorna estadísticas detalladas
- Método `discover_server_info()` - Info sin registrar (diagnóstico)
- Logging completo del proceso de descubrimiento
- Estadísticas:
  - servers_total, servers_success, servers_failed
  - tools_discovered, tools_registered
  - Lista de errores con detalles

**Integración CLI**:
- Descubrimiento automático al iniciar
- Soporte para `--disable-mcp` flag
- Output informativo:
  - Número de servidores consultados
  - Tools registradas exitosamente
  - Servidores no disponibles (warning, no error)
- Continúa funcionando si MCP no está disponible
- Versión actualizada a v0.5.0

#### Entregable
✅ Sistema MCP completo y funcional. Con un servidor MCP configurado, las tools remotas están disponibles automáticamente para los agentes (indistinguibles de las locales).

---

### ✅ F5 - Logging Completo (Completada: 2026-02-18)

**Objetivo**: Logging estructurado JSON para archivos, logs humanos para stdout, niveles de verbose controlados.

**Progreso**: 100%

#### Tareas Completadas
- [x] 5.1 - Configuración completa de structlog
- [x] 5.2 - Dual pipeline (archivo JSON + stderr humano)
- [x] 5.3 - Niveles de verbose (-v, -vv, -vvv)
- [x] 5.4 - Formato JSON estructurado
- [x] 5.5 - Logs a stderr (stdout solo para output)
- [x] 5.6 - Integración con CLI

#### Archivos Creados/Actualizados
- `src/architect/logging/setup.py` - Configuración completa reescrita
- `src/architect/logging/__init__.py` - Exports actualizados
- `scripts/test_phase5.py` - Suite de pruebas de logging
- `src/architect/cli.py` - Integración con configure_logging()

#### Componentes Implementados

**Configuración Completa de Structlog**:
- Función `configure_logging()` - Setup completo con dos pipelines
- Función `_verbose_to_level()` - Mapeo verbose → logging level
- Función `get_logger()` - Obtener logger estructurado
- `configure_logging_basic()` - Backward compatibility

**Dual Pipeline**:
- Pipeline 1: Archivo → JSON estructurado
  - Solo si config.file está configurado
  - Siempre nivel DEBUG (captura todo)
  - Formato JSON Lines (un JSON por línea)
  - JSONRenderer de structlog
- Pipeline 2: Stderr → Humano legible
  - Controlado por verbose/quiet
  - ConsoleRenderer con colores (si TTY)
  - Logs a stderr (NO stdout)

**Procesadores Compartidos**:
- `merge_contextvars` - Contexto de structlog
- `add_log_level` - Añade nivel de log
- `add_logger_name` - Añade nombre del logger
- `TimeStamper(fmt="iso", utc=True)` - Timestamp ISO UTC
- `StackInfoRenderer()` - Info de stack para debugging
- `format_exc_info` - Formateo de excepciones

**Niveles de Verbose**:
- `0` (sin -v): WARNING - Solo problemas
- `1` (-v): INFO - Steps, tool calls, operaciones principales
- `2` (-vv): DEBUG - Args, respuestas LLM, detalles
- `3+` (-vvv): DEBUG completo - Todo, incluyendo HTTP

**Modo Quiet**:
- Solo errores (ERROR level)
- Útil para scripts y automation
- Compatible con --json output

**Formato JSON Estructurado**:
```json
{
  "timestamp": "2026-02-18T10:30:45.123456Z",
  "level": "info",
  "logger": "architect.core.loop",
  "event": "agent.step.start",
  "step": 1,
  "agent": "build"
}
```

**Integración CLI**:
- Configuración antes de cargar componentes
- Usa config.logging completo
- Pasa json_output y quiet flags
- Versión mantenida en v0.5.0

#### Entregable
✅ Sistema de logging completo y funcional. `architect run "..." -vvv --log-file run.jsonl` produce logs legibles en terminal y JSON estructurado en archivo.

---

---

### ✅ F6 - Streaming + Output Final (Completada: 2026-02-19)

**Objetivo**: Streaming del LLM visible en terminal, salida JSON estructurada, códigos de salida correctos.

**Progreso**: 100%

#### Tareas Completadas
- [x] 6.1 - Conectar streaming en CLI (activo por defecto, desactivable con --no-stream)
- [x] 6.2 - Callback de streaming a stderr (no rompe pipes)
- [x] 6.3 - Streaming desactivado en modo --json y --quiet
- [x] 6.4 - Salida JSON estructurada completa (to_output_dict ya implementado)
- [x] 6.5 - Separación stdout/stderr completa (logs+streaming → stderr, resultado+JSON → stdout)
- [x] 6.6 - Códigos de salida completos (0-5 + 130)
- [x] 6.7 - Manejo de SIGINT con graceful shutdown (código 130)
- [x] 6.8 - Detección de errores de autenticación (exit 4) y timeouts (exit 5)
- [x] 6.9 - Versión actualizada a v0.6.0
- [x] 6.10 - Script de prueba scripts/test_phase6.py

#### Archivos Modificados
- `src/architect/cli.py` - Actualizado con streaming, exit codes, SIGINT handler
- `scripts/test_phase6.py` - Script de prueba de la Fase 6 (nuevo)

#### Componentes Implementados

**Streaming en CLI**:
- `use_stream` calculado: activo por defecto si `config.llm.stream=True`
- Desactivado con `--no-stream`, `--json` o si `quiet=True`
- Callback `on_stream_chunk` escribe chunks a `sys.stderr` en tiempo real
- Newline final añadido a stderr tras el streaming
- Streaming activo en ambos modos (single agent y mixed mode)
- En mixed mode, solo la fase build usa streaming (plan es silencioso)

**Separación stdout/stderr**:
- Logs estructurados → stderr
- Info de progreso (modelo, workspace, etc.) → stderr
- Streaming del LLM → stderr
- Resultado final del agente → **stdout**
- `--json` output → **stdout** (parseable con `jq`)
- Compatibilidad con pipes: `architect run "..." --quiet --json | jq .`

**Códigos de Salida Completos**:
- `0` (EXIT_SUCCESS) - Éxito
- `1` (EXIT_FAILED) - Fallo del agente
- `2` (EXIT_PARTIAL) - Parcial (hizo algo pero no completó)
- `3` (EXIT_CONFIG_ERROR) - Error de configuración / archivo no encontrado
- `4` (EXIT_AUTH_ERROR) - Error de autenticación LLM (detección por keywords)
- `5` (EXIT_TIMEOUT) - Timeout en llamadas LLM
- `130` (EXIT_INTERRUPTED) - Interrumpido por SIGINT (Ctrl+C)

**Manejo de SIGINT**:
- Primer Ctrl+C: avisa, marca `interrupted=True`, deja terminar el step actual
- Segundo Ctrl+C: salida inmediata con código 130
- `KeyboardInterrupt` como fallback de seguridad
- Estado marcado como `partial` si fue interrumpido

**Formato JSON** (`--json`):
```json
{
  "status": "success",
  "output": "He creado el archivo...",
  "steps": 3,
  "tools_used": [
    {"name": "read_file", "path": "main.py", "success": true},
    {"name": "write_file", "path": "output.py", "success": true}
  ],
  "duration_seconds": 12.5,
  "model": "gpt-4.1"
}
```

#### Entregable
✅ Streaming visible en terminal (stderr), `--json` produce salida parseable en stdout, `echo $?` retorna códigos correctos. Pipes funcionan: `architect run "..." --quiet --json | jq .`

---

---

### ✅ F7 - Robustez y Tolerancia a Fallos (Completada: 2026-02-19)

**Objetivo**: El sistema no se cae ante errores. Se recupera, informa, y termina limpiamente.

**Progreso**: 100%

#### Tareas Completadas
- [x] 7.1 - Retries LLM mejorados (solo errores transitorios + before_sleep logging + config.retries)
- [x] 7.2 - StepTimeout context manager con SIGALRM (POSIX) y no-op en Windows
- [x] 7.3 - GracefulShutdown class (SIGINT + SIGTERM, graceful first / immediate second)
- [x] 7.4 - AgentLoop integrado con shutdown y step_timeout
- [x] 7.5 - MixedModeRunner integrado con shutdown y step_timeout
- [x] 7.6 - CLI actualizado: usa GracefulShutdown, pasa timeout a loops
- [x] 7.7 - Exports actualizados en core/__init__.py
- [x] 7.8 - Script de prueba scripts/test_phase7.py

#### Archivos Creados/Modificados
- `src/architect/core/timeout.py` - StepTimeout context manager (nuevo)
- `src/architect/core/shutdown.py` - GracefulShutdown class (nuevo)
- `src/architect/core/__init__.py` - Exports actualizados
- `src/architect/llm/adapter.py` - Retries mejorados con _call_with_retry()
- `src/architect/core/loop.py` - Shutdown check + StepTimeout en cada iteración
- `src/architect/core/mixed_mode.py` - Pasa shutdown y step_timeout a loops
- `src/architect/cli.py` - Usa GracefulShutdown, eliminado handler inline
- `scripts/test_phase7.py` - Suite de pruebas (nuevo)

#### Componentes Implementados

**StepTimeout** (`core/timeout.py`):
- Context manager que envuelve cada step del agent loop
- Usa `signal.SIGALRM` en POSIX (Linux/macOS/CI)
- No-op gracioso en Windows (sin SIGALRM) — el código no se rompe
- Restaura el handler previo al salir (compatible con handlers anidados)
- Lanza `StepTimeoutError` (subclase de `TimeoutError`) al expirar

**GracefulShutdown** (`core/shutdown.py`):
- Instala handlers para SIGINT y SIGTERM al instanciar
- Primer disparo: avisa al usuario en stderr, marca `should_stop=True`
- Segundo disparo (SIGINT): `sys.exit(130)` inmediato
- `should_stop` property consultada por AgentLoop antes de cada step
- Métodos `reset()` y `restore_defaults()` para testing y cleanup
- Se comparte entre AgentLoop y MixedModeRunner

**Retries LLM mejorados** (`llm/adapter.py`):
- `_RETRYABLE_ERRORS` — solo errores transitorios: RateLimitError, ServiceUnavailableError, APIConnectionError, Timeout
- `_call_with_retry(fn)` — ejecuta fn con tenacity.Retrying configurable
  - `stop_after_attempt(config.retries + 1)` — usa `config.retries` real
  - `wait_exponential(min=2, max=60)` — backoff progresivo
  - `before_sleep=self._on_retry_sleep` — logging antes de cada reintento
- `_on_retry_sleep(retry_state)` — logea intento, espera y tipo de error
- AuthenticationError y otros errores fatales **no se reintentan**

**AgentLoop actualizado** (`core/loop.py`):
- Nuevos parámetros: `shutdown: GracefulShutdown | None` y `step_timeout: int = 0`
- Comprobación de `shutdown.should_stop` **antes de cada step** → termina limpiamente
- `StepTimeout(self.step_timeout)` envuelve toda la llamada al LLM (streaming o no)
- `StepTimeoutError` capturada → `status=partial` con mensaje descriptivo

**MixedModeRunner actualizado** (`core/mixed_mode.py`):
- Acepta `shutdown` y `step_timeout`
- Los pasa a los loops internos (`plan_loop` y `build_loop`)
- Comprueba `shutdown.should_stop` entre fase plan y fase build

**CLI actualizado** (`cli.py`):
- Instancia `GracefulShutdown()` al inicio (antes de cargar config)
- Pasa `shutdown=shutdown` y `step_timeout=kwargs.get("timeout") or 0` a runners
- Elimina el handler SIGINT inline de F6
- Al finalizar: `if shutdown.should_stop → sys.exit(130)`
- Eliminado import `signal` (ya no necesario en CLI)

#### Entregable
✅ El sistema se recupera de errores de LLM (retries selectivos), errores de tools (feedback al agente), timeouts por step (termina limpiamente), y SIGINT/SIGTERM (graceful shutdown).

---

### ✅ F8 - Integración Final y Pulido (Completada: 2026-02-19)

**Objetivo**: MVP completo, cohesionado y bien documentado. Versión 0.8.0 lista para uso real.

**Progreso**: 100%

#### Tareas Completadas
- [x] 8.1 - Subcomando `architect agents` para listar agentes disponibles
- [x] 8.2 - Versión 0.8.0 consistente en todos los puntos (pyproject.toml, __init__.py, CLI headers, version_option)
- [x] 8.3 - `config.example.yaml` reescrito completamente con documentación exhaustiva
- [x] 8.4 - `README.md` reescrito como documentación de usuario final completa
- [x] 8.5 - Script de pruebas de integración `scripts/test_phase8.py` (7 pruebas)

#### Archivos Modificados
- `src/architect/cli.py` - Añadido subcomando `agents`, versión 0.8.0 en todos los puntos
- `src/architect/__init__.py` - `__version__` actualizado a "0.8.0"
- `pyproject.toml` - `version` actualizado a "0.8.0"
- `config.example.yaml` - Reescrito completamente
- `README.md` - Reescrito completamente
- `scripts/test_phase8.py` - Nuevo: suite de pruebas de integración

#### Componentes Implementados

**Subcomando `architect agents`** (`cli.py`):
- Lista los 4 agentes por defecto (plan, build, resume, review) con descripción y confirm_mode
- Si se proporciona `-c config.yaml`, incluye también los agentes custom definidos en YAML
- Marca con `*` los defaults que han sido sobreescritos por el YAML
- Output limpio y tabular para uso interactivo

**Versión 0.8.0 consistente**:
- `src/architect/__init__.py` → `__version__ = "0.8.0"`
- `pyproject.toml` → `version = "0.8.0"`
- `cli.py` → `@click.version_option(version="0.8.0")`
- `cli.py` → headers de ejecución muestran `architect v0.8.0`
- `config.example.yaml` → comentario de versión en cabecera

**`config.example.yaml` reescrito**:
- Secciones: `llm`, `agents`, `logging`, `workspace`, `mcp`
- Documentación inline exhaustiva para cada campo
- Ejemplos comentados de agentes custom (deploy, documenter, security)
- Múltiples ejemplos de servidores MCP
- Explicación del orden de precedencia de configuración
- Ejemplos de todos los proveedores LLM soportados

**`README.md` reescrito** — documentación completa de usuario final:
- Instalación y quickstart con comandos reales
- Referencia completa de `architect run` (tabla de opciones)
- Referencia de `architect agents` y `architect validate-config`
- Tabla de agentes con tools y confirm_mode
- Modos de confirmación (tabla)
- Configuración: estructura YAML mínima + variables de entorno (tabla)
- Salida y códigos de salida (tabla completa)
- Formato JSON (`--json`) con ejemplo real
- Logging: todos los niveles con ejemplos bash
- Integración MCP: YAML + uso
- Uso en CI/CD: GitHub Actions completo
- Arquitectura: diagrama ASCII del flujo
- Seguridad: path traversal, allow_delete, MCP, API keys
- Proveedores LLM: OpenAI, Anthropic, Gemini, Ollama, LiteLLM Proxy

**`scripts/test_phase8.py`** — 7 pruebas de integración:
1. Importaciones de todos los módulos (23 módulos)
2. Versión consistente (\_\_init\_\_.py, pyproject.toml, CLI --version, cli.py headers)
3. CLI --help: `architect --help`, `architect run --help`, `architect agents --help`, `architect validate-config --help`
4. Subcomando `architect agents`: muestra los 4 agentes por defecto
5. `validate-config` con `config.example.yaml`: parsea y valida correctamente
6. Inicialización completa sin LLM: AppConfig, logging, ToolRegistry, GracefulShutdown, StepTimeout, ExecutionEngine, ContextBuilder
7. `dry-run` sin API key: falla con error de LLM (no de configuración)

#### Entregable
✅ MVP completo en v0.8.0. `architect agents` lista agentes, `architect validate-config -c config.example.yaml` valida el ejemplo, `architect run --help` muestra referencia completa. Documentación de usuario final lista en README.md.

---

### ✅ F9 - Diff Inteligente y apply_patch (Completada: 2026-02-19)

**Objetivo**: Añadir herramientas de edición incremental para que el LLM pueda modificar archivos sin reescribirlos completos, reduciendo errores y tokens consumidos.

**Progreso**: 100%

#### Tareas Completadas
- [x] 9.1 - `EditFileArgs` y `ApplyPatchArgs` en `tools/schemas.py`
- [x] 9.2 - `EditFileTool` (str_replace) en `tools/filesystem.py`
- [x] 9.3 - Actualizar `WriteFileTool.description` con jerarquía de uso
- [x] 9.4 - Crear `tools/patch.py` con `ApplyPatchTool`, `PatchError`, `_Hunk`, parser puro-Python y fallback system `patch`
- [x] 9.5 - Actualizar `tools/setup.py`: registrar `EditFileTool` y `ApplyPatchTool`
- [x] 9.6 - Actualizar `tools/__init__.py`: exportar nuevas tools y `PatchError`
- [x] 9.7 - Añadir guía de jerarquía de edición en `BUILD_PROMPT` (`agents/prompts.py`)
- [x] 9.8 - Versión bump 0.8.0 → 0.9.0 en los 4 sitios
- [x] 9.9 - `scripts/test_phase9.py` (12 tests)

#### Archivos Creados
- `src/architect/tools/patch.py` — `ApplyPatchTool`, `PatchError`, `_Hunk`, `_parse_hunks()`, `_apply_hunks_to_lines()`, `_apply_patch_pure()`, `_apply_patch_system()`
- `scripts/test_phase9.py` — 12 tests unitarios de las nuevas tools

#### Archivos Modificados
- `src/architect/tools/schemas.py` — añadidos `EditFileArgs`, `ApplyPatchArgs`
- `src/architect/tools/filesystem.py` — añadido `EditFileTool`; `WriteFileTool.description` actualizado; `import difflib` añadido
- `src/architect/tools/setup.py` — registro de `EditFileTool`, `ApplyPatchTool`
- `src/architect/tools/__init__.py` — exportaciones actualizadas
- `src/architect/agents/prompts.py` — `BUILD_PROMPT` con tabla de jerarquía de edición y guías para `edit_file`, `apply_patch`, `write_file`
- `src/architect/__init__.py` — versión 0.9.0
- `pyproject.toml` — versión 0.9.0
- `src/architect/cli.py` — versión 0.9.0 en 3 sitios

#### Decisiones de Diseño

**Jerarquía de edición (menor a mayor impacto)**:
1. `edit_file` — str_replace exacto, un único bloque contiguo. Valida que `old_str` sea único; si aparece 0 o >1 veces, devuelve error descriptivo. Genera diff en el output.
2. `apply_patch` — unified diff con uno o más hunks. Parser puro-Python primero (sin dependencias externas); si falla, intenta con el comando `patch` del sistema.
3. `write_file` — reescritura total. Solo para archivos nuevos o reorganizaciones completas.

**Parser puro-Python de unified diff**:
- Regex `^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@` para cabeceras de hunk
- Offset acumulado entre hunks para manejar cambios de tamaño previos
- Caso especial: `orig_count=0` → inserción pura después de línea `orig_start`
- Validación de contexto con `rstrip("\n\r")` para robustez ante variaciones de line endings
- Fallback al comando `patch` del sistema con `--dry-run` previo

#### Entregable
✅ v0.9.0. El LLM (agente `build`) tiene acceso a `edit_file` y `apply_patch` como alternativas eficientes a `write_file`. El `BUILD_PROMPT` incluye una tabla de cuándo usar cada tool.

---

### ✅ F10 - Contexto Incremental Inteligente (Completada: 2026-02-20)

**Objetivo**: El agente conoce la estructura del repo al inicio y puede buscar código eficientemente sin leer archivos uno a uno.

**Progreso**: 100%

#### Tareas Completadas
- [x] 10.1 - `RepoIndexer` + `FileInfo` + `RepoIndex` en `indexer/tree.py`
- [x] 10.2 - `IndexCache` en `indexer/cache.py` (cache en disco con TTL)
- [x] 10.3 - `SearchCodeTool` (`search_code`) en `tools/search.py`
- [x] 10.4 - `GrepTool` (`grep`) con fallback a Python en `tools/search.py`
- [x] 10.5 - `FindFilesTool` (`find_files`) en `tools/search.py`
- [x] 10.6 - Schemas (`SearchCodeArgs`, `GrepArgs`, `FindFilesArgs`) en `tools/schemas.py`
- [x] 10.7 - `IndexerConfig` en `config/schema.py` + campo en `AppConfig`
- [x] 10.8 - `ContextBuilder` actualizado para aceptar `repo_index` e inyectarlo en system prompt
- [x] 10.9 - `register_search_tools()` y `register_all_tools()` en `tools/setup.py`
- [x] 10.10 - Agentes por defecto actualizados con search tools en `allowed_tools`
- [x] 10.11 - Prompts actualizados con guía de herramientas de búsqueda
- [x] 10.12 - CLI actualizado: indexa al inicio, pasa índice a ContextBuilder
- [x] 10.13 - Sección `indexer` en `config.example.yaml`
- [x] 10.14 - Versión bump 0.9.0 → 0.10.0 (4 sitios)
- [x] 10.15 - `scripts/test_phase10.py` (12 tests)

#### Archivos Creados
- `src/architect/indexer/__init__.py` — módulo indexer
- `src/architect/indexer/tree.py` — `RepoIndexer`, `FileInfo`, `RepoIndex`, `EXT_MAP`
- `src/architect/indexer/cache.py` — `IndexCache` con TTL
- `src/architect/tools/search.py` — `SearchCodeTool`, `GrepTool`, `FindFilesTool`
- `scripts/test_phase10.py` — 12 tests sin API key

#### Archivos Modificados
- `src/architect/tools/schemas.py` — añadidos `SearchCodeArgs`, `GrepArgs`, `FindFilesArgs`
- `src/architect/tools/setup.py` — añadidos `register_search_tools()`, `register_all_tools()`
- `src/architect/tools/__init__.py` — exportaciones actualizadas
- `src/architect/config/schema.py` — añadido `IndexerConfig` + campo `indexer` en `AppConfig`
- `src/architect/core/context.py` — `ContextBuilder.__init__(repo_index=None)` + inyección
- `src/architect/agents/registry.py` — search tools en `allowed_tools` de todos los agentes
- `src/architect/agents/prompts.py` — guía de herramientas de búsqueda en PLAN_PROMPT y BUILD_PROMPT
- `src/architect/cli.py` — indexación al inicio + `register_all_tools` + `ContextBuilder(repo_index=...)`
- `config.example.yaml` — sección `indexer` documentada
- `src/architect/__init__.py` — versión 0.10.0
- `pyproject.toml` — versión 0.10.0
- `src/architect/cli.py` — versión 0.10.0 en 3 sitios

#### Decisiones de Diseño

**RepoIndexer**:
- Recorre el workspace con `os.walk()` modificando `dirnames` in-place (eficiente, poda el árbol)
- Ignorados por defecto: `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, etc.
- Archivos >1MB ignorados (configurable)
- `_format_tree_detailed()` para repos ≤300 archivos (árbol completo con conectores Unicode)
- `_format_tree_compact()` para repos >300 archivos (agrupado por directorio de primer nivel)

**IndexCache**:
- Archivo JSON por workspace (identificado por hash SHA-256 del path)
- TTL de 5 minutos (configurable); expirado → None → el indexador reconstruye
- Fallo silencioso: si no se puede escribir el cache, el sistema continúa

**SearchCodeTool**: regex con contexto (líneas antes/después). No sensible.
**GrepTool**: texto literal. Usa rg/grep del sistema si está disponible; Python puro como fallback.
**FindFilesTool**: glob sobre nombres de archivo. No sensible.

**ContextBuilder**: el `repo_index` se almacena en la instancia. `build_initial()` lo inyecta al final del system prompt como sección "## Estructura del Proyecto" con árbol y estadísticas de lenguajes.

**CLI**: el indexador se ejecuta después del setup de MCP y antes de crear el LLM adapter. Si `indexer.use_cache=true`, intenta recuperar del cache primero.

#### Entregable
✅ v0.10.0. El agente recibe el árbol del proyecto en su system prompt. Tiene acceso a `search_code`, `grep` y `find_files` para navegar el código eficientemente. En repos de 500+ archivos el agente encuentra lo que necesita sin listar directorios uno a uno.

---

### ✅ F11 - Optimización de Tokens y Parallel Tool Calls (Completada: 2026-02-20)

**Objetivo**: Evitar crashes por context window lleno en tareas largas. Speedup en tool calls independientes mediante paralelismo.

**Progreso**: 100%

#### Tareas Completadas
- [x] 11.1 - `ContextConfig` en `config/schema.py` + campo en `AppConfig`
- [x] 11.2 - `ContextManager` en `core/context.py` (3 niveles de pruning)
- [x] 11.3 - Nivel 1: `truncate_tool_result()` — truncado de tool results largos
- [x] 11.4 - Nivel 2: `maybe_compress()` — resumen de pasos antiguos con el LLM
- [x] 11.5 - Nivel 3: `enforce_window()` — hard limit de tokens totales
- [x] 11.6 - `ContextBuilder` integra `context_manager` para truncar tool results
- [x] 11.7 - `AgentLoop._execute_tool_calls_batch()` — parallel tool calls con ThreadPoolExecutor
- [x] 11.8 - `AgentLoop._should_parallelize()` — decisión de paralelismo
- [x] 11.9 - `AgentLoop` llama `maybe_compress()` y `enforce_window()` tras cada step
- [x] 11.10 - `MixedModeRunner` propaga `context_manager` a ambos loops
- [x] 11.11 - CLI crea `ContextManager` desde `config.context` y lo pasa a todo
- [x] 11.12 - Sección `context:` en `config.example.yaml`
- [x] 11.13 - Versión bump 0.10.0 → 0.11.0 (4 sitios)
- [x] 11.14 - `scripts/test_phase11.py` (22 tests)

#### Archivos Creados
- `scripts/test_phase11.py` — 22 tests sin API key

#### Archivos Modificados
- `src/architect/config/schema.py` — `ContextConfig` (5 campos) + campo `context` en `AppConfig`
- `src/architect/core/context.py` — `ContextManager` (3 métodos de pruning) + integración en `ContextBuilder`
- `src/architect/core/loop.py` — `_execute_tool_calls_batch()`, `_execute_single_tool()`, `_should_parallelize()` + context pruning en loop
- `src/architect/core/mixed_mode.py` — acepta y propaga `context_manager`
- `src/architect/core/__init__.py` — exporta `ContextManager`
- `src/architect/cli.py` — crea `ContextManager(config.context)` y lo pasa al loop
- `config.example.yaml` — sección `context:` documentada con los 5 campos
- `src/architect/__init__.py` — versión 0.11.0
- `pyproject.toml` — versión 0.11.0
- `src/architect/cli.py` — versión 0.11.0 en 3 sitios

#### Decisiones de Diseño

**ContextManager — 3 niveles progresivos**:
1. **Nivel 1 — truncate_tool_result()** (siempre activo): Preserva primeras 40 líneas + últimas 20. Inserta marcador `"[... N líneas omitidas ...]"`. Activo cuando `max_tool_result_tokens > 0` (default: 2000 tokens ≈ 8000 chars).
2. **Nivel 2 — maybe_compress()** (cuando hay demasiados pasos): Cuando los tool-exchanges superan `summarize_after_steps` (default: 8), comprime los pasos más antiguos en un párrafo usando el propio LLM. Conserva siempre `keep_recent_steps` (default: 4) pasos recientes íntegros. Falla silenciosamente si el LLM no está disponible.
3. **Nivel 3 — enforce_window()** (hard limit): Si el total estimado de tokens supera `max_context_tokens` (default: 80k), elimina pares de mensajes antiguos de 2 en 2 hasta que quepa. Siempre conserva system + user.

**Parallel Tool Calls**:
- Usa `ThreadPoolExecutor(max_workers=min(N, 4))` para ejecutar tool calls concurrentes
- Preserva el orden original de resultados usando `futures = {future: idx}` + `as_completed()`
- Desactivado cuando: `parallel_tools=False`, `confirm-all`, o herramienta sensible en `confirm-sensitive`
- Valor `yolo` o `confirm-sensitive` sin tools sensibles → paralelo habilitado automáticamente

**Integración ContextBuilder**:
- `ContextBuilder(context_manager=...)` — acepta manager opcional
- `_format_tool_result()` aplica truncado (Nivel 1) automáticamente si hay manager
- `AgentLoop` llama `maybe_compress()` + `enforce_window()` después de `append_tool_results()`

**Token estimation**: `len(str(messages)) // 4` — aproximación de ~4 chars/token válida para inglés y código.

#### Entregable
✅ v0.11.0. El contexto no explota en tareas de 15+ pasos. Los tool results largos se truncan automáticamente. Las tool calls paralelas funcionan automáticamente en modo yolo o cuando no hay herramientas sensibles.

---

### ✅ F12 - Self-Evaluation (Critic Agent) (Completada: 2026-02-20)

**Objetivo**: El agente evalúa automáticamente su propio resultado al terminar y, en modo `full`, reintenta con un prompt de corrección hasta conseguir un resultado aceptable.

**Progreso**: 100%

#### Tareas Completadas
- [x] 12.1 - `EvaluationConfig` en `config/schema.py` + campo `evaluation` en `AppConfig`
- [x] 12.2 - `EvalResult` dataclass en `core/evaluator.py`
- [x] 12.3 - `SelfEvaluator.evaluate_basic()` — una llamada LLM, parsea JSON, retorna `EvalResult`
- [x] 12.4 - `SelfEvaluator.evaluate_full()` — loop hasta `max_retries`, llama `run_fn` para corregir
- [x] 12.5 - `_parse_eval()` con 3 estrategias de parseo JSON + fallback conservador
- [x] 12.6 - `_summarize_steps()` — resume steps del agente en texto legible
- [x] 12.7 - `_build_correction_prompt()` — prompt de corrección con issues y sugerencia
- [x] 12.8 - Exports en `core/__init__.py` (`SelfEvaluator`, `EvalResult`)
- [x] 12.9 - Opción `--self-eval` en CLI (`off`|`basic`|`full`)
- [x] 12.10 - Integración en CLI: tras ejecución, si `self_eval_mode != "off"` → evalúa
- [x] 12.11 - `run_fn` capturado en ambas ramas (mixed mode y single agent)
- [x] 12.12 - Sección `evaluation:` en `config.example.yaml`
- [x] 12.13 - Versión bump 0.11.0 → 0.12.0 (4 sitios)
- [x] 12.14 - `scripts/test_phase12.py` (28 tests)

#### Archivos Creados
- `src/architect/core/evaluator.py` — `EvalResult`, `SelfEvaluator`, `_EVAL_SYSTEM_PROMPT`
- `scripts/test_phase12.py` — 28 tests unitarios sin API key

#### Archivos Modificados
- `src/architect/config/schema.py` — `EvaluationConfig` (3 campos) + campo `evaluation` en `AppConfig`
- `src/architect/core/__init__.py` — exporta `SelfEvaluator`, `EvalResult`
- `src/architect/cli.py` — opción `--self-eval`, integración completa post-ejecución, versión 0.12.0
- `config.example.yaml` — sección `evaluation:` documentada
- `src/architect/__init__.py` — versión 0.12.0
- `pyproject.toml` — versión 0.12.0

#### Componentes Implementados

**`EvalResult`** (dataclass):
- `completed: bool` — ¿se completó la tarea?
- `confidence: float` — nivel de confianza [0.0, 1.0]
- `issues: list[str]` — lista de problemas detectados
- `suggestion: str` — sugerencia de mejora
- `raw_response: str` — respuesta cruda del LLM (para debugging)

**`SelfEvaluator`**:
- `_EVAL_SYSTEM_PROMPT` — prompt estricto que pide JSON `{completed, confidence, issues, suggestion}`
- `evaluate_basic(prompt, state)` → `EvalResult`:
  - Construye contexto: prompt original + `state.final_output[:500]` + `_summarize_steps()`
  - Llama `llm.completion(messages, tools=None)` — sin tools para reducir tokens
  - Parsea respuesta con `_parse_eval()` (3 estrategias + fallback conservador)
- `evaluate_full(prompt, state, run_fn)` → `AgentState`:
  - Loop hasta `max_retries` veces
  - Si `completed=True` y `confidence >= threshold` → retorna estado (éxito)
  - Si no → construye `correction_prompt` y llama `run_fn(correction_prompt)`
  - Error en `run_fn` → detiene el loop silenciosamente
  - `run_fn: Callable[[str], AgentState]` — evita acoplamiento circular con AgentLoop

**`_parse_eval()` — 3 estrategias en orden**:
1. `json.loads(content)` directo — caso ideal
2. Regex `r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'` — bloque de código
3. Regex `r'\{[\s\S]*?\}'` — primer `{...}` válido en el texto

**Integración CLI**:
- `self_eval_mode = kwargs.get("self_eval") or config.evaluation.mode` — CLI overridea YAML
- Solo evalúa si `state.status == "success"` (no pierde tiempo en fallos obvios)
- Modo `basic`: si no pasa → `state.status = "partial"` + muestra issues
- Modo `full`: `run_fn` capturado en closure desde la rama ejecutada
- Output en stderr (no rompe pipes con `--json`)

#### Decisiones de Diseño

**`run_fn: Callable[[str], AgentState]`** en lugar de pasar `AgentLoop` directamente:
- Evita importaciones circulares
- Simplifica el API del evaluador (sin estado interno del loop)
- Permite al CLI resetear streaming a `False` para los reintentos

**`tools=None` en la llamada de evaluación**:
- El evaluador no necesita tool calls — solo texto
- Reduce tokens y latencia de la llamada de evaluación

**Modo `basic` marca como `partial`** en lugar de fallar:
- El output del agente puede ser útil aunque incompleto
- El usuario puede decidir qué hacer con el output
- Código de salida `2` (EXIT_PARTIAL) correcto según especificación

**Confidence threshold** (default: 0.8):
- Conservador: requiere 80% de confianza para aceptar
- Evita falsos positivos del evaluador
- Configurable en YAML y potencialmente por CLI en futuras versiones

#### Entregable
✅ v0.12.0. `architect run "tarea compleja" --self-eval basic` evalúa el resultado y marca como `partial` si detecta problemas. `--self-eval full` reintenta automáticamente hasta `max_retries` veces. El modo `off` (default) mantiene el comportamiento anterior sin coste extra de tokens.

---

## Próximas Fases

F12 completada. Siguiente según el plan:
- F13: run_command — ejecución de código con seguridad por capas
- F14: Cost tracking + prompt caching

---

## Notas y Decisiones

- Stack tecnológico confirmado: Python 3.12+, Click, PyYAML, Pydantic v2, LiteLLM, httpx, structlog
- Arquitectura sync-first con async donde sea necesario
- No se usará LangChain/LangGraph (ver justificación en plan)
