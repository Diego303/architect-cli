# 📋 Seguimiento de Implementación - architect CLI

Este documento registra el progreso de implementación del proyecto architect siguiendo el plan definido en `Plan_Implementacion.md`.

---

## Estado General

- **Inicio**: 2026-02-18
- **Fase Actual**: F8 Completada — MVP listo
- **Estado**: ✅ MVP completado (v0.8.0)

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

## Próximas Fases

MVP completado. Posibles extensiones futuras:
- Persistencia de estado (reanudar ejecuciones parciales)
- Multi-agente (agentes que delegan en otros)
- Plugin system (tools desde paquetes Python externos)
- Prompt caching para desarrollo
- Métricas: tokens usados, coste estimado, duración por step

---

## Notas y Decisiones

- Stack tecnológico confirmado: Python 3.12+, Click, PyYAML, Pydantic v2, LiteLLM, httpx, structlog
- Arquitectura sync-first con async donde sea necesario
- No se usará LangChain/LangGraph (ver justificación en plan)
