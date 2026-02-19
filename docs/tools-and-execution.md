# Sistema de tools y ejecución

Describe cómo se definen, registran y ejecutan las herramientas que el agente puede usar.

---

## BaseTool — la interfaz de toda tool

Toda tool (local o MCP) implementa esta clase abstracta:

```python
class BaseTool(ABC):
    name:        str            # identificador único (ej: "write_file", "mcp_github_create_pr")
    description: str            # descripción para el LLM (debe ser precisa y concisa)
    args_model:  type[BaseModel]  # Pydantic model con los argumentos
    sensitive:   bool = False   # True → requiere confirmación en "confirm-sensitive"

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        # NUNCA lanza excepciones. Siempre retorna ToolResult.
        ...

    def get_schema(self) -> dict:
        # Genera el JSON Schema en formato OpenAI function-calling
        # {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    def validate_args(self, args: dict) -> BaseModel:
        # Valida args contra args_model; lanza ValidationError de Pydantic si falla
```

El `get_schema()` produce el formato que LiteLLM/OpenAI espera para tool calling. El `args_model` de Pydantic se convierte automáticamente a JSON Schema.

---

## Tools del filesystem

Todas viven en `tools/filesystem.py`. Reciben `workspace_root: Path` en `__init__` y lo pasan a `validate_path()` en cada operación.

| Clase | name | sensitive | Operación |
|-------|------|-----------|-----------|
| `ReadFileTool` | `read_file` | `False` | Lee el archivo como texto UTF-8 |
| `WriteFileTool` | `write_file` | `True` | Escribe o añade (overwrite/append); crea directorios padres |
| `DeleteFileTool` | `delete_file` | `True` | Elimina el archivo; falla si `allow_delete=False` |
| `ListFilesTool` | `list_files` | `False` | Lista archivos; soporta glob y recursión |

`DeleteFileTool` tiene una verificación adicional de `allow_delete`:
```python
def execute(self, path: str) -> ToolResult:
    if not self.allow_delete:
        return ToolResult(success=False,
                         output="Error: eliminación de archivos deshabilitada.",
                         error="allow_delete=False en WorkspaceConfig")
    ...
```

---

## Validación de paths — seguridad

`execution/validators.py` es la única puerta de seguridad para todas las operaciones de archivos.

```python
def validate_path(path: str, workspace_root: Path) -> Path:
    resolved = (workspace_root / path).resolve()
    if not resolved.is_relative_to(workspace_root.resolve()):
        raise PathTraversalError(f"Path '{path}' escapa del workspace")
    return resolved
```

El truco es `Path.resolve()`:
- Colapsa `../..` → ruta absoluta real.
- Resuelve symlinks → previene escapes vía symlinks.
- Hace que `../../etc/passwd` → `/etc/passwd`, que claramente no es `is_relative_to(workspace)`.

**Todos los paths del usuario pasan por `validate_path()` antes de cualquier operación de I/O.**

---

## ToolRegistry

Almacén central en memoria.

```python
class ToolRegistry:
    _tools: dict[str, BaseTool]

    register(tool, allow_override=False)
    # Lanza DuplicateToolError si ya existe y allow_override=False

    get(name) -> BaseTool
    # Lanza ToolNotFoundError si no existe

    list_all() -> list[BaseTool]     # ordenado por nombre
    get_schemas(allowed=None) -> list[dict]
    # allowed=None → schemas de todas las tools
    # allowed=["read_file","list_files"] → solo esas dos
    # Lanza ToolNotFoundError si algún nombre no existe

    filter_by_names(names) -> list[BaseTool]
    has_tool(name) -> bool
    count() -> int
    clear()  # para testing
```

`get_schemas(allowed_tools)` es el método crítico que se llama en cada iteración del loop para obtener los schemas que se envían al LLM.

---

## ExecutionEngine — el pipeline de ejecución

Punto de entrada obligatorio para TODA ejecución de tool. **Nunca lanza excepciones.**

```python
class ExecutionEngine:
    registry:  ToolRegistry
    config:    AppConfig
    dry_run:   bool = False
    policy:    ConfirmationPolicy

    def execute_tool_call(self, tool_name: str, args: dict) -> ToolResult:
```

### Los 7 pasos del pipeline

```
1. registry.get(tool_name)
   ✗ ToolNotFoundError → return ToolResult(success=False, "Tool no encontrada")

2. tool.validate_args(args)
   ✗ ValidationError → return ToolResult(success=False, "Argumentos inválidos: ...")

3. policy.should_confirm(tool)
   → True: policy.request_confirmation(tool_name, args, dry_run)
       ✗ NoTTYError → return ToolResult(success=False, "No hay TTY para confirmar")
       ✗ user cancela → return ToolResult(success=False, "Acción cancelada por usuario")

4. if dry_run:
   → return ToolResult(success=True, "[DRY-RUN] Se ejecutaría: tool_name(args)")

5. tool.execute(**validated_args.model_dump())
   (tool.execute() no lanza — si hay excepción interna, la tool la captura)

6. log resultado (structlog)

7. return ToolResult
```

Hay un `try/except Exception` exterior que captura cualquier error inesperado del paso 5 y lo convierte en `ToolResult(success=False)`.

El resultado de error se devuelve al agente como mensaje de tool, y el LLM puede decidir intentar otra cosa. **Los errores de tools no rompen el loop.**

---

## ConfirmationPolicy

Implementa la lógica de confirmación interactiva.

```python
class ConfirmationPolicy:
    mode: str   # "yolo" | "confirm-all" | "confirm-sensitive"

    def should_confirm(self, tool: BaseTool) -> bool:
        if mode == "yolo":             return False   # nunca confirma
        if mode == "confirm-all":      return True    # siempre confirma
        if mode == "confirm-sensitive": return tool.sensitive  # solo si sensitive=True
```

```python
    def request_confirmation(self, tool_name, args, dry_run=False) -> bool:
        if not sys.stdin.isatty():
            raise NoTTYError(
                "Modo confirm requiere TTY interactiva. "
                "En CI usa --mode yolo o --dry-run."
            )
        # Muestra: "¿Ejecutar 'write_file' con args=...? [y/n/a]"
        # 'y' → True (ejecutar)
        # 'n' → False (cancelar esta tool, continúa el loop)
        # 'a' → sys.exit(130) (abortar todo)
```

Sensibilidad por defecto de cada tool:
- `read_file`, `list_files` → `sensitive=False`
- `write_file`, `delete_file` → `sensitive=True`
- Todas las tools MCP → `sensitive=True`

---

## MCPToolAdapter — tools remotas como locales

`MCPToolAdapter` hereda de `BaseTool` y hace que una tool de un servidor MCP sea indistinguible de una tool local.

```python
class MCPToolAdapter(BaseTool):
    name = f"mcp_{server_name}_{original_name}"
    # Prefijo evita colisiones cuando dos servidores tienen tools con el mismo nombre

    sensitive = True   # todas las tools MCP son sensibles por defecto

    args_model = _build_args_model(tool_definition["inputSchema"])
    # Genera un Pydantic model dinámicamente desde el JSON Schema del servidor MCP

    def execute(self, **kwargs) -> ToolResult:
        result = client.call_tool(original_name, kwargs)
        return ToolResult(success=True, output=_extract_content(result))
```

El generador de `args_model` traduce tipos JSON Schema a Python:
```
"string"  → str
"integer" → int
"number"  → float
"boolean" → bool
"array"   → list
"object"  → dict
```

Campos requeridos → `(type, ...)` (Pydantic required).
Campos opcionales → `(type | None, None)` (Pydantic optional con default None).

---

## Ciclo de vida de una tool call

```
LLMResponse.tool_calls = [ToolCall(id="call_abc", name="write_file", arguments={...})]
                              │
                              ▼
ExecutionEngine.execute_tool_call("write_file", {path:"main.py", content:"..."})
  │
  ├─ registry.get("write_file")            → WriteFileTool
  ├─ validate_args({path:..., content:...}) → WriteFileArgs(path="main.py", content="...")
  ├─ policy.should_confirm(write_file)      → True (sensitive=True, mode=confirm-sensitive)
  ├─ request_confirmation("write_file", ...) → user: y
  ├─ write_file.execute(path="main.py", content="...", mode="overwrite")
  │     └─ validate_path("main.py", workspace) → /workspace/main.py ✓
  │     └─ /workspace/main.py.write_text("...")
  │     └─ ToolResult(success=True, output="Archivo main.py sobrescrito (42 bytes)")
  └─ return ToolResult

ContextBuilder.append_tool_results(messages, [ToolCall(...)], [ToolResult(...)])
  → messages += [
      {"role":"assistant", "tool_calls":[{"id":"call_abc","function":{...}}]},
      {"role":"tool", "tool_call_id":"call_abc", "content":"Archivo main.py sobrescrito..."}
    ]
```

El resultado de la tool (éxito o error) siempre vuelve al LLM como mensaje `tool`. El LLM decide qué hacer a continuación.
