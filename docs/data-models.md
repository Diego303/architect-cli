# Modelos de datos

Todos los modelos de datos del sistema. Son la fuente de verdad para la comunicación entre componentes.

---

## Modelos de configuración (`config/schema.py`)

Todos usan Pydantic v2 con `extra = "forbid"` (claves desconocidas → error de validación).

### `LLMConfig`

```python
class LLMConfig(BaseModel):
    provider:       str   = "litellm"    # único proveedor soportado
    mode:           str   = "direct"     # "direct" | "proxy"
    model:          str   = "gpt-4o"     # cualquier modelo LiteLLM
    api_base:       str | None = None    # URL base custom (LiteLLM Proxy, Ollama, etc.)
    api_key_env:    str   = "LITELLM_API_KEY"  # nombre de la env var con la API key
    timeout:        int   = 60           # segundos por llamada al LLM
    retries:        int   = 2            # reintentos ante errores transitorios
    stream:         bool  = True         # streaming activo por defecto
    prompt_caching: bool  = False        # F14: marcar system con cache_control (Anthropic/OpenAI)
```

### `AgentConfig`

```python
class AgentConfig(BaseModel):
    system_prompt: str                        # inyectado como primer mensaje
    allowed_tools: list[str]  = []            # [] = todas las tools disponibles
    confirm_mode:  str        = "confirm-sensitive"  # "yolo"|"confirm-all"|"confirm-sensitive"
    max_steps:     int        = 20            # Pydantic default=20; en DEFAULT_AGENTS varía:
                                              #   plan=20, build=50, resume=15, review=20
```

### `LoggingConfig`

```python
class LoggingConfig(BaseModel):
    # v3: "human" = nivel de trazabilidad del agente (HUMAN=25)
    level:   str        = "human"  # "debug"|"info"|"human"|"warn"|"error"
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

### `HookConfig` (v3-M4)

```python
class HookConfig(BaseModel):
    name:          str           # identificador del hook (ej: "python-lint")
    command:       str           # comando shell a ejecutar; soporta {file} placeholder
    file_patterns: list[str]    # patrones glob (ej: ["*.py", "*.ts"])
    timeout:       int = 15     # ge=1, le=300 — segundos máximos
    enabled:       bool = True  # si False, el hook se ignora
```

### `HooksConfig` (v3-M4)

```python
class HooksConfig(BaseModel):
    post_edit: list[HookConfig] = []  # hooks ejecutados después de editar un archivo
```

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

### `CommandsConfig` (F13)

```python
class CommandsConfig(BaseModel):
    enabled:          bool       = True    # si False, run_command no se registra
    default_timeout:  int        = 30      # segundos por defecto (ge=1, le=600)
    max_output_lines: int        = 200     # líneas antes de truncar (ge=10, le=5000)
    blocked_patterns: list[str]  = []      # regexes extra a bloquear
    safe_commands:    list[str]  = []      # comandos adicionales clasificados como 'safe'
    allowed_only:     bool       = False   # si True, dangerous rechazados en execute()
```

Override desde CLI: `--allow-commands` (enabled=True) / `--no-commands` (enabled=False).

### `CostsConfig` (F14)

```python
class CostsConfig(BaseModel):
    enabled:      bool        = True   # si False, no se instancia CostTracker
    prices_file:  Path | None = None   # precios custom; si None, usa default_prices.json
    budget_usd:   float | None = None  # límite USD; BudgetExceededError si se supera
    warn_at_usd:  float | None = None  # umbral de aviso (log warning, sin detener)
```

Override desde CLI: `--budget FLOAT` (equivale a `budget_usd`).

### `LLMCacheConfig` (F14)

```python
class LLMCacheConfig(BaseModel):
    enabled:   bool = False              # si True, activa LocalLLMCache
    dir:       Path = Path("~/.architect/cache")  # directorio en disco
    ttl_hours: int  = 24                 # ge=1, le=8760 — horas de validez
```

Override desde CLI: `--cache` (enabled=True), `--no-cache` (enabled=False), `--cache-clear` (limpia antes de ejecutar).

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
    commands:   CommandsConfig   = CommandsConfig()   # F13
    costs:      CostsConfig      = CostsConfig()      # F14
    llm_cache:  LLMCacheConfig   = LLMCacheConfig()   # F14
    hooks:      HooksConfig      = HooksConfig()      # v3-M4
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
    usage:        dict | None        # {"prompt_tokens": N, "completion_tokens": N,
                                     #  "total_tokens": N, "cache_read_input_tokens": N}
```

`cache_read_input_tokens` está disponible cuando el proveedor usa prompt caching (Anthropic). El `CostTracker` lo usa para calcular el coste reducido de tokens cacheados.

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

### `StopReason` (enum, v3)

```python
class StopReason(Enum):
    """Razón por la que se detuvo el agente."""
    LLM_DONE         = "llm_done"          # Natural: el LLM no pidió más tools
    MAX_STEPS         = "max_steps"         # Watchdog: límite de pasos alcanzado
    BUDGET_EXCEEDED   = "budget_exceeded"   # Watchdog: límite de coste superado
    CONTEXT_FULL      = "context_full"      # Watchdog: context window lleno
    TIMEOUT           = "timeout"           # Watchdog: tiempo total excedido
    USER_INTERRUPT    = "user_interrupt"    # El usuario hizo Ctrl+C / SIGTERM
    LLM_ERROR         = "llm_error"        # Error irrecuperable del LLM
```

Distingue terminacion natural (`LLM_DONE`) de paradas forzadas por safety nets. Se almacena en `AgentState.stop_reason` y se incluye en el output JSON.

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
    stop_reason:  StopReason | None = None  # v3: razón de parada (None mientras running)
    final_output: str | None = None    # respuesta final cuando status != "running"
    start_time:   float = field(...)
    model:        str | None = None    # modelo usado (para output)
    cost_tracker: CostTracker | None = None   # F14: tracker de costes (inyectado por CLI)

    # Propiedades computadas
    current_step:     int    # len(steps)
    total_tool_calls: int    # suma de todas las tool calls en todos los steps
    is_finished:      bool   # status != "running"

    def to_output_dict(self) -> dict:
        # Serialización para --json
        result = {
            "status":           self.status,
            "stop_reason":      self.stop_reason.value if self.stop_reason else None,
            "output":           self.final_output or "",
            "steps":            len(self.steps),
            "tools_used":       [...],  # lista de {name, args parciales, success}
            "duration_seconds": time.time() - self.start_time,
            "model":            self.model,
        }
        # F14: incluir costes si hay datos
        if self.cost_tracker and self.cost_tracker.has_data():
            result["costs"] = self.cost_tracker.summary()
        return result
```

El campo `status` puede ser modificado externamente por el `SelfEvaluator` (F12) o por `BudgetExceededError` (F14).

---

## Módulo de costes (`costs/`) — F14

### `ModelPricing` (dataclass)

```python
@dataclass
class ModelPricing:
    input_per_million:        float          # USD por millón de tokens de input
    output_per_million:       float          # USD por millón de tokens de output
    cached_input_per_million: float | None   # USD/M para tokens cacheados (None = usar input_per_million)
```

### `PriceLoader`

Carga precios desde `costs/default_prices.json` (o un archivo custom vía `CostsConfig.prices_file`).

```python
class PriceLoader:
    def __init__(self, custom_prices_file: Path | None = None): ...

    def get_prices(self, model: str) -> ModelPricing:
        # 1. Match exacto (ej: "gpt-4o" → prices["gpt-4o"])
        # 2. Match por prefijo (ej: "claude-sonnet-4-6-20250514" → prices["claude-sonnet-4-6"])
        # 3. Fallback genérico: input=3.0, output=15.0, cached=None
        # NUNCA lanza excepciones
```

Modelos embebidos en `default_prices.json`: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini`, `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5`, `gemini/gemini-2.0-flash`, `deepseek/deepseek-chat`, `ollama` (coste 0).

### `StepCost` (dataclass)

```python
@dataclass
class StepCost:
    step:          int    # número de step del agente
    model:         str    # modelo usado (ej: "gpt-4o")
    input_tokens:  int    # tokens de input totales (incluye cached)
    output_tokens: int    # tokens de output
    cached_tokens: int    # tokens servidos desde caché del proveedor
    cost_usd:      float  # coste en USD del step
    source:        str    # "agent" | "eval" | "summary"
```

### `CostTracker`

```python
class CostTracker:
    def __init__(
        self,
        price_loader: PriceLoader,
        budget_usd:   float | None = None,   # límite; BudgetExceededError si se supera
        warn_at_usd:  float | None = None,   # umbral de aviso (log warning, sin excepción)
    ): ...

    def record(self, step: int, model: str, usage: dict, source: str = "agent") -> None:
        # Extrae prompt_tokens, completion_tokens, cache_read_input_tokens
        # Calcula coste diferenciado: cached_tokens × cached_rate + no_cached × input_rate + output × output_rate
        # Lanza BudgetExceededError si total_cost_usd > budget_usd
        # NUNCA lanza otras excepciones

    # Propiedades de agregación
    total_input_tokens:  int    # suma de todos los input_tokens
    total_output_tokens: int    # suma de todos los output_tokens
    total_cached_tokens: int    # suma de todos los cached_tokens
    total_cost_usd:      float  # coste total en USD
    step_count:          int    # número de steps registrados

    def has_data(self) -> bool: ...     # True si step_count > 0
    def summary(self) -> dict: ...      # totales + desglose by_source
    def format_summary_line(self) -> str:  # "$0.0042 (12,450 in / 3,200 out / 500 cached)"
```

`summary()` retorna:
```python
{
    "total_input_tokens":  12450,
    "total_output_tokens": 3200,
    "total_cached_tokens": 500,
    "total_tokens":        15650,
    "total_cost_usd":      0.004213,
    "by_source":           {"agent": 0.003800, "eval": 0.000413},
}
```

### `BudgetExceededError`

Lanzada por `CostTracker.record()` cuando `total_cost_usd > budget_usd`. El `AgentLoop` la captura, pone `state.status = "partial"` y termina el loop.

```python
class BudgetExceededError(Exception):
    pass
```

---

## Post-Edit Hooks (`core/hooks.py`) -- v3-M4

### `HookRunResult` (dataclass, v3-M4)

Resultado de la ejecución de un hook post-edit individual.

```python
@dataclass
class HookRunResult:
    hook_name:  str    # nombre del hook (ej: "python-lint")
    success:    bool   # True si exit_code == 0
    output:     str    # stdout + stderr combinados (truncado a 1000 chars)
    exit_code:  int    # código de salida del proceso
```

`PostEditHooks` ejecuta los hooks configurados en `HooksConfig.post_edit` despues de cada operacion de edicion (`edit_file`, `write_file`, `apply_patch`). Los resultados se concatenan y se devuelven al LLM como parte del tool result para que pueda auto-corregir errores de lint o typecheck.

---

## Cache local LLM (`llm/cache.py`) — F14

### `LocalLLMCache`

```python
class LocalLLMCache:
    def __init__(self, cache_dir: Path, ttl_hours: int = 24): ...

    def get(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> LLMResponse | None:
        # Retorna LLMResponse si hay hit válido (no expirado)
        # Retorna None en miss, expiración o error — NUNCA lanza

    def set(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        response: LLMResponse,
    ) -> None:
        # Guarda response en disco — falla silenciosamente en error

    def clear(self) -> int: ...   # elimina todos los .json; retorna count
    def stats(self) -> dict: ...  # {entries, expired, total_size_bytes, dir}

    def _make_key(self, messages, tools) -> str:
        # SHA-256[:24] de json.dumps({"messages":..., "tools":...}, sort_keys=True)
        # Determinista independientemente del orden de claves
```

Un archivo `.json` por entrada en `cache_dir`. TTL basado en `mtime` del archivo. El `LLMAdapter` lo consulta antes de llamar a LiteLLM y guarda la respuesta si hay miss.

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

### Tool de ejecución de comandos (F13)

```python
class RunCommandArgs(BaseModel):
    command: str                     # comando a ejecutar (shell string)
    cwd:     str | None = None       # directorio de trabajo (relativo al workspace)
    timeout: int = 30                # segundos (ge=1, le=600)
    env:     dict[str, str] | None = None  # variables de entorno adicionales
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
├── StepTimeoutError(TimeoutError)  core/timeout.py
│   # Step del agente excedió el tiempo máximo configurado
│   # .seconds: int — tiempo en segundos que se superó
│
└── BudgetExceededError             costs/tracker.py
    # Coste total de la sesión superó el budget_usd configurado
    # Lanzada por CostTracker.record() → capturada por AgentLoop → state.status="partial"
```

Estas excepciones son para señalización interna — la mayoría se captura en `ExecutionEngine` o en `AgentLoop` y se convierte en un `ToolResult(success=False)` o en un cambio de status del agente, respectivamente. **Ninguna debería propagarse hasta el usuario final.**
