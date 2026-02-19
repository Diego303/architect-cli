# Guía para IA — cómo modificar architect

Esta guía está dirigida a modelos de IA (y desarrolladores) que necesitan entender el sistema para aplicar cambios correctamente. Cubre los invariantes críticos, los patrones establecidos y dónde añadir cada tipo de extensión.

---

## Invariantes que NUNCA deben romperse

### 1. Las tools nunca lanzan excepciones

```python
# ✓ CORRECTO — toda tool
def execute(self, **kwargs) -> ToolResult:
    try:
        result = do_something()
        return ToolResult(success=True, output=str(result))
    except Exception as e:
        return ToolResult(success=False, output=f"Error: {e}", error=str(e))

# ✗ INCORRECTO
def execute(self, **kwargs) -> ToolResult:
    result = do_something()  # puede lanzar → rompe el loop del agente
    return ToolResult(success=True, output=str(result))
```

El `ExecutionEngine` tiene un `try/except` exterior como backstop, pero las tools deben manejar sus propios errores. El loop del agente espera `ToolResult`, no excepciones.

### 2. Toda operación de archivo pasa por `validate_path()`

```python
# ✓ CORRECTO
def execute(self, path: str, **kwargs) -> ToolResult:
    try:
        safe_path = validate_path(path, self.workspace_root)
        content = safe_path.read_text()
        ...

# ✗ INCORRECTO — bypass de seguridad
def execute(self, path: str, **kwargs) -> ToolResult:
    content = Path(path).read_text()  # path traversal posible
```

### 3. stdout solo para el resultado final y JSON

```python
# ✓ CORRECTO
click.echo("Error: archivo no encontrado", err=True)   # → stderr
click.echo(state.final_output)                          # → stdout
click.echo(json.dumps(output_dict))                     # → stdout

# ✗ INCORRECTO
click.echo(f"Procesando {filename}...")                 # contamina stdout
print(f"Step {n} completado")                           # rompe pipes
```

### 4. Los errores de tools vuelven al LLM, no terminan el loop

```python
# ✓ CORRECTO — en ExecutionEngine
result = engine.execute_tool_call(name, args)
# result.success puede ser False; el loop continúa
ctx.append_tool_results(messages, [tc], [result])
# El LLM recibe el error y decide qué hacer

# ✗ INCORRECTO
result = engine.execute_tool_call(name, args)
if not result.success:
    state.status = "failed"   # el LLM no tuvo oportunidad de recuperarse
    break
```

### 5. La versión debe ser consistente en 4 sitios

Cuando hagas un bump de versión, actualiza los 4:
1. `src/architect/__init__.py` → `__version__ = "X.Y.Z"`
2. `pyproject.toml` → `version = "X.Y.Z"`
3. `src/architect/cli.py` → `@click.version_option(version="X.Y.Z")`
4. `src/architect/cli.py` → headers de ejecución con `vX.Y.Z`

---

## Patrones establecidos

### Añadir una nueva tool local

1. Define el modelo de argumentos en `tools/schemas.py`:

```python
class MyToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path:    str
    option:  str | None = None
```

2. Implementa la tool en `tools/filesystem.py` (o un nuevo archivo):

```python
class MyTool(BaseTool):
    name        = "my_tool"
    description = "Descripción clara para el LLM de qué hace esta tool."
    args_model  = MyToolArgs
    sensitive   = False   # True si modifica el sistema

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def execute(self, path: str, option: str | None = None) -> ToolResult:
        try:
            safe_path = validate_path(path, self.workspace_root)
            # ... lógica ...
            return ToolResult(success=True, output="Resultado...")
        except PathTraversalError as e:
            return ToolResult(success=False, output=str(e), error=str(e))
        except Exception as e:
            return ToolResult(success=False, output=f"Error inesperado: {e}", error=str(e))
```

3. Registra en `tools/setup.py`:

```python
def register_filesystem_tools(registry, workspace_config):
    root = workspace_config.root.resolve()
    registry.register(ReadFileTool(root))
    registry.register(WriteFileTool(root))
    registry.register(DeleteFileTool(root, workspace_config.allow_delete))
    registry.register(ListFilesTool(root))
    registry.register(MyTool(root))   # ← añade aquí
```

4. Si la tool debe estar disponible para todos los agentes, no hay que hacer nada más. Si solo para algunos, añade `"my_tool"` al `allowed_tools` del agente correspondiente.

---

### Añadir un nuevo agente por defecto

En `agents/registry.py`:

```python
DEFAULT_AGENTS: dict[str, AgentConfig] = {
    "plan":   AgentConfig(...),
    "build":  AgentConfig(...),
    "resume": AgentConfig(...),
    "review": AgentConfig(...),
    "test":   AgentConfig(           # ← nuevo agente
        system_prompt=TEST_PROMPT,   # añade en prompts.py
        allowed_tools=["read_file", "list_files", "write_file"],
        confirm_mode="confirm-sensitive",
        max_steps=15,
    ),
}
```

En `agents/prompts.py`:

```python
TEST_PROMPT = """
Eres un agente de testing especializado.
Tu trabajo es analizar código y generar tests unitarios.
...
"""
```

---

### Añadir un nuevo subcomando CLI

```python
# En cli.py, después del grupo principal

@main.command("mi-comando")
@click.option("-c", "--config", "config_path", type=click.Path(exists=False), default=None)
@click.option("--opcion", default=None)
def mi_comando(config_path, opcion):
    """Descripción del comando para --help."""
    try:
        config = load_config(config_path=Path(config_path) if config_path else None)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    # ... lógica ...
    click.echo("Resultado")   # → stdout
```

---

### Añadir un campo a la configuración

1. Añade el campo al modelo Pydantic en `config/schema.py`.
2. Si necesita ser configurable desde env vars, añade en `load_env_overrides()` en `config/loader.py`.
3. Si necesita flag de CLI, añade `@click.option` en `cli.py` y actualiza `apply_cli_overrides()` en `loader.py`.
4. Actualiza `config.example.yaml` con documentación del nuevo campo.

---

### Añadir soporte para un nuevo tipo de LLM error

En `llm/adapter.py`, `_RETRYABLE_ERRORS`:

```python
_RETRYABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.NuevoErrorTransitorio,   # ← si es transitorio, añadir aquí
)
```

Si el error es fatal (como auth errors), NO añadir a `_RETRYABLE_ERRORS`. Dejarlo propagar al loop, que lo captura y marca `status="failed"`.

Para detectar el tipo de error en la CLI (exit codes):

```python
# En cli.py, en el bloque except del comando run
except Exception as e:
    err_str = str(e).lower()
    if any(k in err_str for k in ["authenticationerror", "api key", "unauthorized", "401"]):
        sys.exit(EXIT_AUTH_ERROR)
    elif any(k in err_str for k in ["timeout", "timed out", "readtimeout"]):
        sys.exit(EXIT_TIMEOUT)
    elif "nuevo_tipo" in err_str:      # ← añadir aquí si necesitas exit code específico
        sys.exit(NUEVO_EXIT_CODE)
    else:
        sys.exit(EXIT_FAILED)
```

---

## Dónde está cada cosa

| ¿Qué necesito cambiar? | Archivo(s) |
|------------------------|------------|
| Nueva tool local | `tools/schemas.py`, `tools/filesystem.py` (o nuevo), `tools/setup.py` |
| Nueva tool MCP | Solo configurar servidor en `config.yaml`; el adapter es genérico |
| Nuevo agente por defecto | `agents/prompts.py`, `agents/registry.py` |
| Comportamiento del loop | `core/loop.py` |
| Modo mixto plan→build | `core/mixed_mode.py` |
| Nuevo campo de configuración | `config/schema.py`, `config/loader.py`, `cli.py`, `config.example.yaml` |
| Nuevo subcomando CLI | `cli.py` |
| Retries del LLM | `llm/adapter.py` → `_RETRYABLE_ERRORS`, `_call_with_retry` |
| Streaming | `llm/adapter.py` → `completion_stream()`, `core/loop.py` → sección stream |
| Exit codes | `cli.py` (constantes + detección en except) |
| Señales del OS | `core/shutdown.py` (SIGINT/SIGTERM), `core/timeout.py` (SIGALRM) |
| Logging | `logging/setup.py` |
| Formato mensajes al LLM | `core/context.py` |
| Serialización JSON output | `core/state.py` → `AgentState.to_output_dict()` |
| Seguridad de paths | `execution/validators.py` |
| Políticas de confirmación | `execution/policies.py` |
| Descubrimiento MCP | `mcp/discovery.py` |
| Cliente HTTP MCP | `mcp/client.py` |
| Adaptador MCP | `mcp/adapter.py` |

---

## Pitfalls frecuentes

### El LLM pide una tool que no está en `allowed_tools`

El `ExecutionEngine` devuelve `ToolResult(success=False, "Tool no encontrada")`. El LLM recibe ese error en el siguiente mensaje y puede intentar otra cosa. Esto es intencional — no es un bug.

### Streaming y tool calls en el mismo step

Cuando el LLM hace streaming, los chunks de texto llegan primero. Si luego hay tool calls, estas se acumulan internamente en el adapter y se devuelven en el `LLMResponse` final. El `on_stream_chunk` callback NO recibe chunks de tool calls, solo de texto.

### `allowed_tools = []` vs `allowed_tools = None`

- `[]` en `AgentConfig` → `registry.get_schemas([])` → lista vacía → el LLM no tiene tools.
- `None` → `registry.get_schemas(None)` → todas las tools registradas.

En los defaults, `allowed_tools=[]` (lista vacía) se trata como "todas las tools" en el registry:

```python
# En loop.py
tools_schema = registry.get_schemas(agent_config.allowed_tools or None)
# [] → or None → None → todas las tools
```

El `or None` es el truco. Una lista vacía `[]` es falsy en Python, por lo que se convierte en `None`.

### MixedModeRunner crea dos engines distintos

No reutilices el mismo `ExecutionEngine` para plan y build en modo mixto. El plan necesita `confirm_mode="confirm-all"` y tools limitadas; el build necesita `confirm_mode="confirm-sensitive"` y todas las tools. La CLI crea dos engines separados.

### `validate_path()` con paths absolutos

`validate_path("/etc/passwd", workspace)` también lanza `PathTraversalError`. El cálculo `(workspace_root / "/etc/passwd").resolve()` resulta en `/etc/passwd` directamente (Python ignora workspace_root cuando el path es absoluto), y luego `is_relative_to(workspace)` falla. La protección funciona correctamente para paths absolutos.

### Tenacity `reraise=True`

El `_call_with_retry` tiene `reraise=True`. Esto significa que después de agotar los reintentos, la excepción original se propaga. El loop la captura y marca `status="failed"`. Sin `reraise=True`, tenacity lanzaría su propia `RetryError`.

### `StepTimeout` no funciona en Windows

`signal.SIGALRM` no existe en Windows. `StepTimeout` es transparentemente un no-op. Si necesitas timeout en Windows, habría que usar un thread con `threading.Timer`, pero eso implica complejidad de threading que el diseño sync-first evita conscientemente.

### `model_copy(update=..., exclude_unset=True)` en el registry

El merge de agentes usa `exclude_unset=True` para saber qué campos el YAML realmente especificó (vs los que tienen valor por tener un default). Esto permite que un override parcial no pisee con valores default campos que el usuario no quiso cambiar.
