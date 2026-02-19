# Modelos de datos

Todos los modelos de datos del sistema. Son la fuente de verdad para la comunicación entre componentes.

---

## Modelos de configuración (`config/schema.py`)

Todos usan Pydantic v2 con `extra = "forbid"` (claves desconocidas → error de validación).

### `LLMConfig`

```python
class LLMConfig(BaseModel):
    provider:    str   = "litellm"    # único proveedor soportado
    mode:        str   = "direct"     # "direct" | "proxy"
    model:       str   = "gpt-4o"     # cualquier modelo LiteLLM
    api_base:    str | None = None    # URL base custom (LiteLLM Proxy, Ollama, etc.)
    api_key_env: str   = "LITELLM_API_KEY"  # nombre de la env var con la API key
    timeout:     int   = 60           # segundos por llamada al LLM
    retries:     int   = 2            # reintentos ante errores transitorios
    stream:      bool  = True         # streaming activo por defecto
```

### `AgentConfig`

```python
class AgentConfig(BaseModel):
    system_prompt: str                        # inyectado como primer mensaje
    allowed_tools: list[str]  = []            # [] = todas las tools disponibles
    confirm_mode:  str        = "confirm-sensitive"  # "yolo"|"confirm-all"|"confirm-sensitive"
    max_steps:     int        = 20            # máximo de iteraciones del loop
```

### `LoggingConfig`

```python
class LoggingConfig(BaseModel):
    level:   str        = "info"   # "debug"|"info"|"warn"|"error"
    file:    Path|None  = None     # ruta al archivo .jsonl (opcional)
    verbose: int        = 0        # 0=warn, 1=info, 2=debug, 3+=all
```

### `WorkspaceConfig`

```python
class WorkspaceConfig(BaseModel):
    root:         Path  = Path(".")   # workspace root; todas las ops confinadas aquí
    allow_delete: bool  = False       # gate para delete_file tool
```

### `MCPServerConfig`

```python
class MCPServerConfig(BaseModel):
    name:      str           # identificador; usado en prefijo: mcp_{name}_{tool}
    url:       str           # URL base HTTP del servidor MCP
    token_env: str | None = None   # env var con el Bearer token
    token:     str | None = None   # token inline (no recomendado en producción)
```

### `MCPConfig`

```python
class MCPConfig(BaseModel):
    servers: list[MCPServerConfig] = []
```

### `AppConfig` (raíz)

```python
class AppConfig(BaseModel):
    llm:       LLMConfig     = LLMConfig()
    agents:    dict[str, AgentConfig] = {}   # agentes custom del YAML
    logging:   LoggingConfig = LoggingConfig()
    workspace: WorkspaceConfig = WorkspaceConfig()
    mcp:       MCPConfig     = MCPConfig()
```

---

## Modelos LLM (`llm/adapter.py`)

### `ToolCall`

Representa una tool call que el LLM solicita ejecutar.

```python
class ToolCall(BaseModel):
    id:        str             # ID único asignado por el LLM (ej: "call_abc123")
    name:      str             # nombre de la tool (ej: "write_file")
    arguments: dict[str, Any]  # argumentos ya parseados (adapter maneja JSON string → dict)
```

### `LLMResponse`

Respuesta normalizada del LLM, independientemente del proveedor.

```python
class LLMResponse(BaseModel):
    content:      str | None         # texto de respuesta (None si hay tool_calls)
    tool_calls:   list[ToolCall]     # lista de tool calls solicitadas ([] si ninguna)
    finish_reason: str               # "stop" | "tool_calls" | "length" | ...
    usage:        dict | None        # {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
```

El `finish_reason` más importante:
- `"stop"` + `tool_calls=[]`: el agente terminó. `content` es la respuesta final.
- `"tool_calls"` o `"stop"` + `tool_calls != []`: hay tools que ejecutar.
- `"length"`: el LLM se quedó sin tokens; el loop puede continuar.

### `StreamChunk`

Chunk de streaming de texto.

```python
class StreamChunk(BaseModel):
    type: str   # "content" siempre (para futura extensión)
    data: str   # fragmento de texto del LLM
```

---

## Estado del agente (`core/state.py`)

### `ToolCallResult` (frozen dataclass)

Resultado inmutable de una ejecución de tool.

```python
@dataclass(frozen=True)
class ToolCallResult:
    tool_name:    str
    args:         dict[str, Any]
    result:       ToolResult      # de tools/base.py
    was_confirmed: bool = True
    was_dry_run:  bool  = False
    timestamp:    float = field(default_factory=time.time)
```

### `StepResult` (frozen dataclass)

Resultado inmutable de una iteración completa del loop.

```python
@dataclass(frozen=True)
class StepResult:
    step_number:     int
    llm_response:    LLMResponse
    tool_calls_made: list[ToolCallResult]
    timestamp:       float = field(default_factory=time.time)
```

### `AgentState` (dataclass mutable)

Estado acumulado durante toda la ejecución del agente.

```python
@dataclass
class AgentState:
    messages:     list[dict]           # historial OpenAI (crece cada step)
    steps:        list[StepResult]     # historial de steps (append-only)
    status:       str = "running"      # "running" | "success" | "partial" | "failed"
    final_output: str | None = None    # respuesta final cuando status != "running"
    start_time:   float = field(...)
    model:        str | None = None    # modelo usado (para output)

    # Propiedades computadas
    current_step:     int    # len(steps)
    total_tool_calls: int    # suma de todas las tool calls en todos los steps
    is_finished:      bool   # status != "running"

    def to_output_dict(self) -> dict:
        # Serialización para --json
        return {
            "status":           self.status,
            "output":           self.final_output or "",
            "steps":            len(self.steps),
            "tools_used":       [...],  # lista de {name, args parciales, success}
            "duration_seconds": time.time() - self.start_time,
            "model":            self.model,
        }
```

---

## Tool result (`tools/base.py`)

### `ToolResult`

El único tipo de retorno posible de cualquier tool. Nunca se lanzan excepciones.

```python
class ToolResult(BaseModel):
    success: bool
    output:  str           # siempre presente; en fallo contiene descripción del error
    error:   str | None    # mensaje técnico de error (None en éxito)
```

---

## Modelos de argumentos de tools (`tools/schemas.py`)

Todos con `extra = "forbid"`.

```python
class ReadFileArgs(BaseModel):
    path: str                          # relativo al workspace root

class WriteFileArgs(BaseModel):
    path:    str
    content: str
    mode:    str = "overwrite"         # "overwrite" | "append"

class DeleteFileArgs(BaseModel):
    path: str

class ListFilesArgs(BaseModel):
    path:      str       = "."
    pattern:   str|None  = None        # glob (ej: "*.py", "**/*.md")
    recursive: bool      = False
```

---

## Jerarquía de errores

```
Exception
├── MCPError                        mcp/client.py
│   ├── MCPConnectionError          error de conexión HTTP al servidor MCP
│   └── MCPToolCallError            error en la ejecución de la tool remota
│
├── PathTraversalError              execution/validators.py
│   # Intento de acceso fuera del workspace (../../etc/passwd)
│
├── ValidationError                 execution/validators.py
│   # Archivo o directorio no encontrado durante validación
│
├── NoTTYError                      execution/policies.py
│   # Se necesita confirmación interactiva pero no hay TTY (CI/headless)
│
├── ToolNotFoundError               tools/registry.py
│   # Tool solicitada no registrada en el registry
│
├── DuplicateToolError              tools/registry.py
│   # Intento de registrar tool con nombre ya existente (sin allow_override=True)
│
├── AgentNotFoundError              agents/registry.py
│   # Nombre de agente no encontrado en DEFAULT_AGENTS ni en YAML
│
└── StepTimeoutError(TimeoutError)  core/timeout.py
    # Step del agente excedió el tiempo máximo configurado
    # .seconds: int — tiempo en segundos que se superó
```

Estas excepciones son para señalización interna — la mayoría se captura en `ExecutionEngine` o en `AgentLoop` y se convierte en un `ToolResult(success=False)` o en un cambio de status del agente, respectivamente. **Ninguna debería propagarse hasta el usuario final.**
