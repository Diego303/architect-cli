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

### `MCPServerConfig` / `MCPConfig`

```python
class MCPServerConfig(BaseModel):
    name:      str           # identificador; usado en prefijo: mcp_{name}_{tool}
    url:       str           # URL base HTTP del servidor MCP
    token_env: str | None = None   # env var con el Bearer token
    token:     str | None = None   # token inline (no recomendado en producción)

class MCPConfig(BaseModel):
    servers: list[MCPServerConfig] = []
```

### `IndexerConfig` (F10)

```python
class IndexerConfig(BaseModel):
    enabled:          bool       = True       # si False, no se indexa y no hay árbol en el prompt
    max_file_size:    int        = 1_000_000  # bytes; archivos más grandes se omiten
    exclude_dirs:     list[str]  = []         # dirs adicionales (además de .git, node_modules, etc.)
    exclude_patterns: list[str]  = []         # patrones adicionales (además de *.pyc, *.min.js, etc.)
    use_cache:        bool       = True       # caché en disco con TTL de 5 minutos
```

El indexador siempre excluye por defecto: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.tox`, `.pytest_cache`, `.mypy_cache`.

### `ContextConfig` (F11)

```python
class ContextConfig(BaseModel):
    max_tool_result_tokens: int  = 2000   # Nivel 1: truncar tool results largos (~4 chars/token)
    summarize_after_steps:  int  = 8      # Nivel 2: comprimir mensajes antiguos tras N pasos
    keep_recent_steps:      int  = 4      # Nivel 2: pasos recientes a preservar íntegros
    max_context_tokens:     int  = 80000  # Nivel 3: hard limit total (~4 chars/token)
    parallel_tools:         bool = True   # paralelizar tool calls independientes
```

Valores `0` desactivan el mecanismo correspondiente:
- `max_tool_result_tokens=0` → sin truncado de tool results.
- `summarize_after_steps=0` → sin compresión con LLM.
- `max_context_tokens=0` → sin ventana deslizante (peligroso para tareas largas).

### `EvaluationConfig` (F12)

```python
class EvaluationConfig(BaseModel):
    mode:                 Literal["off", "basic", "full"] = "off"
    max_retries:          int   = 2    # ge=1, le=5 — reintentos en modo "full"
    confidence_threshold: float = 0.8  # ge=0.0, le=1.0 — umbral para aceptar resultado
```

- `mode="off"`: sin evaluación (default, no consume tokens extra).
- `mode="basic"`: una llamada LLM extra tras la ejecución. Si no pasa, estado → `"partial"`.
- `mode="full"`: hasta `max_retries` ciclos de evaluación + corrección con nuevo prompt.

### `AppConfig` (raíz)

```python
class AppConfig(BaseModel):
    llm:        LLMConfig        = LLMConfig()
    agents:     dict[str, AgentConfig] = {}   # agentes custom del YAML
    logging:    LoggingConfig    = LoggingConfig()
    workspace:  WorkspaceConfig  = WorkspaceConfig()
    mcp:        MCPConfig        = MCPConfig()
    indexer:    IndexerConfig    = IndexerConfig()   # F10
    context:    ContextConfig    = ContextConfig()   # F11
    evaluation: EvaluationConfig = EvaluationConfig() # F12
```

---

## Modelos LLM (`llm/adapter.py`)

### `ToolCall`

Representa una tool call que el LLM solicita ejecutar.

```python
class ToolCall(BaseModel):
    id:        str             # ID único asignado por el LLM (ej: "call_abc123")
    name:      str             # nombre de la tool (ej: "edit_file")
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

El campo `status` puede ser modificado externamente por el `SelfEvaluator` (F12): si la evaluación falla en modo `basic`, el evaluador cambia `state.status = "partial"`.

---

## Evaluador (`core/evaluator.py`) — F12

### `EvalResult` (dataclass)

Resultado de una evaluación del agente por parte del `SelfEvaluator`.

```python
@dataclass
class EvalResult:
    completed:    bool              # ¿se completó la tarea correctamente?
    confidence:   float             # nivel de confianza [0.0, 1.0] (clampeado)
    issues:       list[str] = []    # lista de problemas detectados
    suggestion:   str = ""          # sugerencia para mejorar el resultado
    raw_response: str = ""          # respuesta cruda del LLM (debugging)
```

**Ejemplo de EvalResult con problemas**:
```python
EvalResult(
    completed=False,
    confidence=0.35,
    issues=["No se creó el archivo tests/test_utils.py", "Las imports no se actualizaron"],
    suggestion="Crea el archivo tests/test_utils.py con pytest y actualiza los imports en src/",
    raw_response='{"completed": false, "confidence": 0.35, ...}'
)
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

### Tools del filesystem

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

### Tools de edición (F9)

```python
class EditFileArgs(BaseModel):
    path:    str           # archivo a modificar
    old_str: str           # texto exacto a reemplazar (debe ser único en el archivo)
    new_str: str           # texto de reemplazo

class ApplyPatchArgs(BaseModel):
    path:  str             # archivo a modificar
    patch: str             # unified diff (formato --- +++ @@ ...)
```

### Tools de búsqueda (F10)

```python
class SearchCodeArgs(BaseModel):
    pattern:       str            # expresión regular Python
    path:          str = "."      # directorio de búsqueda
    file_pattern:  str = "*.py"   # glob para filtrar archivos
    context_lines: int = 2        # líneas de contexto por match
    max_results:   int = 50

class GrepArgs(BaseModel):
    pattern:        str            # texto literal
    path:           str = "."
    file_pattern:   str = "*"
    recursive:      bool = True
    case_sensitive: bool = True
    max_results:    int = 100

class FindFilesArgs(BaseModel):
    pattern:   str            # glob de nombre de archivo (ej: "*.yaml")
    path:      str = "."
    recursive: bool = True
```

---

## Modelos del indexador (`indexer/tree.py`) — F10

```python
@dataclass
class FileInfo:
    path:     Path     # ruta relativa al workspace root
    size:     int      # bytes
    ext:      str      # extensión (ej: ".py", ".ts", ".yaml")
    language: str      # nombre del lenguaje (ej: "Python", "TypeScript")
    lines:    int      # número de líneas (0 si no se pudo leer)

@dataclass
class RepoIndex:
    root:         Path
    files:        list[FileInfo]
    total_files:  int
    total_lines:  int
    languages:    dict[str, int]   # {lenguaje: nº de archivos}
    build_time_ms: float

    def format_tree(self) -> str:
        # Devuelve el árbol del workspace como string para el system prompt
        # ≤300 archivos → árbol detallado con conectores Unicode
        # >300 archivos → vista compacta agrupada por directorio raíz
```

El `RepoIndexer` construye el `RepoIndex` recorriendo el workspace con `os.walk()`, filtrando directorios y archivos excluidos. El `IndexCache` serializa/deserializa el índice en JSON con TTL de 5 minutos.

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
├── PatchError                      tools/patch.py
│   # Error al parsear o aplicar un unified diff en apply_patch
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
