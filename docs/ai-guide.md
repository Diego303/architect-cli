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

Esto incluye el output del `SelfEvaluator` — todos los avisos de evaluación van a `stderr`.

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
4. `src/architect/cli.py` → headers de ejecución con `vX.Y.Z` (aparece 2 veces, una por modo)

### 6. El ContextManager nunca lanza excepciones

### 7. `CostTracker.record()` y `PriceLoader.get_prices()` nunca lanzan (salvo `BudgetExceededError`)

```python
# ✓ CORRECTO — CostTracker
def record(self, step, model, usage, source="agent") -> None:
    # ... calcula coste ...
    if self._budget_usd and self.total_cost_usd > self._budget_usd:
        raise BudgetExceededError(...)  # ← única excepción permitida

# PriceLoader siempre retorna un ModelPricing (fallback genérico si modelo desconocido)
# LocalLLMCache.get() siempre retorna None si falla (no rompe el adapter)
# LocalLLMCache.set() falla silenciosamente
```

### 8. `run_command` no usa `tool.sensitive` para confirmar

La herramienta `run_command` tiene `sensitive=True` como atributo base, pero `ExecutionEngine` **no usa ese atributo** para esta tool. En su lugar llama a `_should_confirm_command()` que consulta `tool.classify_sensitivity(command)` dinámicamente. Si añades nueva lógica de confirmación, asegúrate de mantener este bypass intacto.

### 9. Los hooks post-edit nunca lanzan excepciones

`PostEditHooks.run_for_tool()` y `run_for_file()` capturan todas las excepciones internamente. `subprocess.TimeoutExpired` retorna un `HookRunResult` formateado con el error de timeout. Otras excepciones logean un warning y retornan `None`. El resultado del hook (si existe) se concatena al `ToolResult` para que el LLM pueda auto-corregir.

`maybe_compress()` falla silenciosamente si el LLM no está disponible. `enforce_window()` y `truncate_tool_result()` son operaciones puramente de strings. Ninguna de las tres debe propagar excepciones al loop.

```python
# ✓ CORRECTO — en maybe_compress
try:
    summary = self._summarize_steps(old_msgs, llm)
except Exception:
    self.log.warning("context.compress.failed")
    return messages  # retorna original sin cambios
```

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

2. Implementa la tool en `tools/filesystem.py` o un nuevo archivo:

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
    # ...tools existentes...
    registry.register(MyTool(root))   # ← añade aquí
```

4. Si la tool debe estar disponible para todos los agentes, no hay que hacer nada más. Si solo para algunos, añade `"my_tool"` al `allowed_tools` del agente correspondiente.

---

### Añadir una tool de búsqueda (sin `workspace_root`)

Para tools que no necesitan confinamiento de paths (ej: búsqueda en el workspace completo):

```python
# En tools/search.py
class MySearchTool(BaseTool):
    name        = "my_search"
    description = "Busca X en el código del workspace."
    args_model  = MySearchArgs
    sensitive   = False

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def execute(self, pattern: str, path: str = ".") -> ToolResult:
        try:
            base = validate_path(path, self.workspace_root)
            # búsqueda dentro de base...
            return ToolResult(success=True, output=results_str)
        except Exception as e:
            return ToolResult(success=False, output=str(e), error=str(e))
```

Añadir en `register_search_tools()` en `tools/setup.py`.

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
        allowed_tools=["read_file", "list_files", "search_code", "write_file"],
        confirm_mode="confirm-sensitive",
        max_steps=15,
    ),
}
```

En `agents/prompts.py`:

```python
TEST_PROMPT = """
Eres un agente de testing especializado.
Tu trabajo es analizar código y generar tests unitarios con pytest.
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
5. Actualiza `docs/config-reference.md`.

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
| Nueva tool local (filesystem) | `tools/schemas.py`, `tools/filesystem.py`, `tools/setup.py` |
| Nueva tool de búsqueda | `tools/schemas.py`, `tools/search.py`, `tools/setup.py` |
| Nueva tool MCP | Solo configurar servidor en `config.yaml`; el adapter es genérico |
| Nuevo agente por defecto | `agents/prompts.py`, `agents/registry.py` |
| Comportamiento del loop | `core/loop.py` |
| Gestión del context window | `core/context.py` → `ContextManager` |
| Lógica de evaluación | `core/evaluator.py` → `SelfEvaluator` |
| Indexación del repositorio | `indexer/tree.py` → `RepoIndexer` |
| Caché del índice | `indexer/cache.py` → `IndexCache` |
| Modo mixto plan→build | `core/mixed_mode.py` |
| Nuevo campo de configuración | `config/schema.py`, `config/loader.py`, `cli.py`, `config.example.yaml` |
| Nuevo subcomando CLI | `cli.py` |
| Retries del LLM | `llm/adapter.py` → `_RETRYABLE_ERRORS`, `_call_with_retry` |
| Streaming | `llm/adapter.py` → `completion_stream()`, `core/loop.py` → sección stream |
| Exit codes | `cli.py` (constantes + detección en except) |
| Señales del OS | `core/shutdown.py` (SIGINT/SIGTERM), `core/timeout.py` (SIGALRM) |
| Logging | `logging/setup.py` |
| Formato mensajes al LLM | `core/context.py` → `ContextBuilder` |
| Pruning de contexto | `core/context.py` → `ContextManager` |
| Serialización JSON output | `core/state.py` → `AgentState.to_output_dict()` |
| Seguridad de paths | `execution/validators.py` |
| Políticas de confirmación | `execution/policies.py` |
| Descubrimiento MCP | `mcp/discovery.py` |
| Cliente HTTP MCP | `mcp/client.py` |
| Adaptador MCP | `mcp/adapter.py` |
| Ejecución de comandos (F13) | `tools/commands.py` → `RunCommandTool` |
| Clasificación de comandos (F13) | `tools/commands.py` → `classify_sensitivity()` |
| Confirmación dinámica run_command | `execution/engine.py` → `_should_confirm_command()` |
| Precios de modelos (F14) | `costs/prices.py` → `PriceLoader`, `costs/default_prices.json` |
| Tracking de costes (F14) | `costs/tracker.py` → `CostTracker` |
| Budget enforcement (F14) | `costs/tracker.py` → `BudgetExceededError` |
| Cache local LLM (F14) | `llm/cache.py` → `LocalLLMCache` |
| Prompt caching headers (F14) | `llm/adapter.py` → `_prepare_messages_with_caching()` |
| Post-edit hooks (v3-M4) | `core/hooks.py` → `PostEditHooks`, `config/schema.py` → `HookConfig` |
| Human logging (v3-M5) | `logging/human.py` → `HumanLog`, `HumanFormatter`, `HumanLogHandler` |
| Pipeline structlog (v0.15.3) | `logging/setup.py` → siempre `wrap_for_formatter`, nunca `ConsoleRenderer` directo |
| Nivel HUMAN (25) | `logging/levels.py` |
| Human log integration en loop | `core/loop.py` → `self.hlog = HumanLog(self.log)` |
| Hook execution in engine | `execution/engine.py` → `run_post_edit_hooks()` |
| StopReason enum | `core/state.py` → `StopReason` |

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

### MixedModeRunner crea dos engines distintos (legacy)

El modo mixto plan→build ya no es el default (v3-M3). La CLI usa `build` directamente como agente por defecto. Si usas `MixedModeRunner` programáticamente, no reutilices el mismo `ExecutionEngine` para plan y build. El plan necesita `confirm_mode="confirm-all"` y tools limitadas; el build necesita `confirm_mode="confirm-sensitive"` y todas las tools. El `ContextManager` sí se **comparte** entre ambas fases.

### `validate_path()` con paths absolutos

`validate_path("/etc/passwd", workspace)` también lanza `PathTraversalError`. El cálculo `(workspace_root / "/etc/passwd").resolve()` resulta en `/etc/passwd` directamente (Python ignora workspace_root cuando el path es absoluto), y luego `is_relative_to(workspace)` falla. La protección funciona correctamente para paths absolutos.

### Tenacity `reraise=True`

El `_call_with_retry` tiene `reraise=True`. Esto significa que después de agotar los reintentos, la excepción original se propaga. El loop la captura y marca `status="failed"`. Sin `reraise=True`, tenacity lanzaría su propia `RetryError`.

### `StepTimeout` no funciona en Windows

`signal.SIGALRM` no existe en Windows. `StepTimeout` es transparentemente un no-op. Si necesitas timeout en Windows, habría que usar un thread con `threading.Timer`, pero eso implica complejidad de threading que el diseño sync-first evita conscientemente.

### `model_copy(update=..., exclude_unset=True)` en el registry

El merge de agentes usa `exclude_unset=True` para saber qué campos el YAML realmente especificó (vs los que tienen valor por tener un default). Esto permite que un override parcial no pisee con valores default campos que el usuario no quiso cambiar.

### `edit_file` requiere `old_str` único

Si el `old_str` aparece más de una vez en el archivo, `EditFileTool` devuelve un error. El agente debe incluir suficiente contexto en `old_str` para que sea único. Si hay múltiples ocurrencias, usar `apply_patch` con hunks específicos de línea.

### Parallel tool calls y `confirm-sensitive`

Con `confirm-sensitive`, si **cualquier** tool call del lote es `sensitive=True`, **todo el lote se ejecuta secuencialmente**. Esto es conservador por diseño: la interacción con el usuario no es thread-safe y mezclar confirmaciones en paralelo crearía confusión.

### `SelfEvaluator` solo evalúa `status == "success"`

Si el agente ya terminó con `"partial"` o `"failed"`, el `SelfEvaluator` no se ejecuta. La evaluación solo tiene sentido cuando el agente cree que terminó correctamente.

### ContextManager Nivel 2 puede llamar al LLM

`maybe_compress()` hace una llamada extra al LLM para resumir pasos antiguos. Esto significa:
1. Consume tokens extra (generalmente pequeño).
2. Puede fallar si hay errores de red/auth → falla silenciosamente.
3. El resumen se marca con `[Resumen de pasos anteriores]` para que el LLM sepa que es una síntesis.

En tests, pasar `context_manager=None` para evitar la llamada al LLM en la compresión.

### `RepoIndexer` excluye archivos >1MB

Archivos muy grandes (datasets, binarios, etc.) se omiten del índice pero siguen siendo accesibles con `read_file`. El agente los verá en el árbol como omitidos, pero puede leerlos explícitamente. Para repos con archivos grandes válidos, ajustar `indexer.max_file_size`.

### Orden de mensajes en `enforce_window`

El Nivel 3 elimina pares `messages[2:4]` (el assistant + tool más antiguos después del user inicial). Nunca elimina `messages[0]` (system) ni `messages[1]` (user original). Si hay menos de 4 mensajes, no se elimina nada. Los pares se eliminan de 2 en 2 para mantener la coherencia del formato OpenAI.

### `run_command` y stdin

`RunCommandTool.execute()` pasa `stdin=subprocess.DEVNULL` explícitamente. Los comandos que requieren input interactivo (ej: `git commit` sin `-m`, `vim`, `nano`) fallarán. El agente debe usar flags no-interactivos en sus comandos.

### Prompt caching y proveedores no-Anthropic

`_prepare_messages_with_caching()` añade `cache_control` al system message. Si el proveedor no soporta este campo (ej: `ollama`, proveedores locales), LiteLLM simplemente lo ignorará al serializar la request — no produce errores. Solo actúa con `LLMConfig.prompt_caching=True`.

### `LocalLLMCache` y cambios de configuración

El cache es determinista por `(messages, tools)`. Si cambias el system prompt pero usas el mismo prompt de usuario, la clave es diferente (el system prompt es parte de `messages[0]`). Sin embargo, si cambias la versión del modelo en config pero los mensajes son iguales, el cache retorna la respuesta antigua (que fue generada con el modelo previo). En desarrollo esto es intencional; en producción, usar `--no-cache`.

### `BudgetExceededError` y el estado del agente

Cuando se lanza `BudgetExceededError`, el loop pone `state.status = "partial"` y sale. El `CostTracker` **ya registró** el step que causó el exceso. El output JSON incluye `costs` con el total acumulado incluyendo el step que excedió el presupuesto.

### PostEditHooks nunca rompen el loop

Los hooks siempre retornan `None` o un string, nunca lanzan excepciones. Si un hook supera el timeout (`subprocess.TimeoutExpired`) o falla por cualquier otra razon, se logea un warning y se retorna un mensaje de error formateado. Ese mensaje se inyecta como parte del resultado del tool para que el LLM lo vea y pueda auto-corregir. El loop del agente nunca se interrumpe por un hook fallido.

### HumanLog va por pipeline separado

Los eventos con nivel HUMAN (25) se enrutan exclusivamente al `HumanLogHandler` en stderr, NO al handler de consola técnico. El handler de consola excluye explícitamente los eventos HUMAN. Esto significa que `-v` (INFO) NO muestra los human logs — los human logs se muestran siempre (con iconos: 🔄🔧🌐✅⚡❌📦🔍) a menos que se use `--quiet` o `--json`.

**Importante**: structlog SIEMPRE usa `wrap_for_formatter` como procesador final (v0.15.3). Si se cambia a `ConsoleRenderer` directo, el `HumanLogHandler` dejará de funcionar porque recibe strings pre-renderizados en lugar del event dict. La extracción del event dict depende de que `record.msg` sea un `dict`.

### `_graceful_close()` hace una ultima llamada al LLM

Cuando un watchdog se dispara (max_steps, budget, timeout, context_full), el loop llama a `_graceful_close()` que inyecta un mensaje `[SISTEMA]` y hace una ultima llamada al LLM SIN tools para obtener un resumen de lo hecho hasta ese punto. La excepcion es `USER_INTERRUPT` (Ctrl+C), que corta inmediatamente sin llamada extra. Si la llamada final al LLM falla, se usa un mensaje mecanico como output.
