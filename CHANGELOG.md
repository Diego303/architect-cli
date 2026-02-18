# Changelog

Todos los cambios notables en el proyecto architect serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y este proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

---

## [No Publicado]

### En Progreso
- Fase 6 - CLI Streaming (pendiente de inicio)

---

## [0.6.0] - 2026-02-18

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
