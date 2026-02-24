# Sub-Agentes (Dispatch Subagent)

Sistema de delegación de sub-tareas a agentes especializados con contexto aislado.

Implementado en `src/architect/tools/dispatch.py`. Disponible desde v1.0.0 (Plan base v4 Phase D — D1).

---

## Concepto

El agente principal (`build`) puede delegar sub-tareas a agentes especializados mediante la tool `dispatch_subagent`. Cada sub-agente se ejecuta en un `AgentLoop` fresco con:

- **Contexto aislado**: no comparte el historial del agente principal
- **Tools limitadas**: cada tipo de sub-agente tiene un set restringido de tools
- **Límites estrictos**: máximo 15 pasos, resumen truncado a 1000 caracteres

Esto permite que el agente principal delegue tareas de exploración, testing o review sin contaminar su propio contexto ni consumir demasiado budget.

---

## Tipos de sub-agente

| Tipo | Tools disponibles | Uso típico |
|------|-------------------|------------|
| `explore` | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | Investigar código, buscar patrones, explorar estructura |
| `test` | Explore + `run_command` | Ejecutar tests, verificar comportamiento, correr linters |
| `review` | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | Revisar código, análisis de calidad, buscar bugs |

---

## Cómo funciona

```
AgentLoop (build)
  │
  ├─ LLM decide: dispatch_subagent(type="explore", task="busca todos los endpoints REST")
  │
  ├─ _subagent_factory() → crea AgentLoop fresco
  │     ├─ Tools: solo las del tipo seleccionado
  │     ├─ Max steps: 15
  │     ├─ Confirm mode: yolo
  │     └─ Context: solo el prompt de la sub-tarea
  │
  ├─ Sub-agente ejecuta y retorna resumen
  │     └─ Truncado a 1000 chars para no inflar contexto
  │
  └─ AgentLoop (build) continúa con la información
```

---

## API

### `DispatchSubagentTool`

Tool registrada como `dispatch_subagent` en el `ToolRegistry`.

```python
class DispatchSubagentArgs(BaseModel):
    agent_type: str    # "explore" | "test" | "review"
    task: str          # Descripción de la sub-tarea
    context: str = ""  # Contexto adicional (archivos relevantes, etc.)
```

### Constantes

```python
SUBAGENT_MAX_STEPS = 15
SUBAGENT_SUMMARY_MAX_CHARS = 1000
VALID_SUBAGENT_TYPES = {"explore", "test", "review"}

SUBAGENT_ALLOWED_TOOLS = {
    "explore": ["read_file", "list_files", "search_code", "grep", "find_files"],
    "test": ["read_file", "list_files", "search_code", "grep", "find_files", "run_command"],
    "review": ["read_file", "list_files", "search_code", "grep", "find_files"],
}
```

### `register_dispatch_tool()`

```python
# En tools/setup.py
def register_dispatch_tool(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
    agent_factory: Callable[..., AgentLoop],
) -> None:
```

Se llama desde `cli.py` después de crear el `AgentLoop` principal. Recibe una `agent_factory` que es un closure capturando todos los componentes necesarios (LLM, config, registry, guardrails, etc.).

---

## Wiring en CLI

El dispatch se conecta en `cli.py` mediante un closure:

```python
def _subagent_factory(
    agent: str = "build",
    max_steps: int = 15,
    allowed_tools: list[str] | None = None,
    **kw,
) -> AgentLoop:
    """Crea un AgentLoop fresco para sub-agentes."""
    sub_agent_config = get_agent(agent, config.agents, {"max_steps": max_steps})
    if allowed_tools:
        sub_agent_config.allowed_tools = list(allowed_tools)
    sub_engine = ExecutionEngine(
        registry, config, confirm_mode="yolo", guardrails=guardrails_engine,
    )
    sub_ctx = ContextBuilder(repo_index=repo_index, context_manager=ContextManager(config.context))
    return AgentLoop(llm, sub_engine, sub_agent_config, sub_ctx, ...)

register_dispatch_tool(registry, config.workspace, _subagent_factory)
```

---

## Seguridad

- Los sub-agentes de tipo `explore` y `review` son **solo lectura** — no tienen acceso a write/edit/delete/run_command
- El tipo `test` puede ejecutar comandos pero hereda los guardrails del agente principal
- Cada sub-agente opera en modo `yolo` (sin confirmaciones) pero con las mismas restricciones de seguridad (path validation, blocklist de comandos)
- El resumen se trunca a 1000 caracteres — evita que un sub-agente inyecte contenido excesivo

---

## Buenas prácticas

1. **Usar `explore` para investigar** antes de implementar — no contamina el contexto del builder
2. **Usar `test` para verificar** cambios — el sub-agente ejecuta tests y reporta resultados
3. **No abusar**: cada sub-agente consume pasos LLM adicionales — usar solo cuando la tarea principal se beneficia de la delegación
4. **Contexto mínimo**: pasar en `context` solo la información relevante (paths, nombres de funciones)

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `src/architect/tools/dispatch.py` | `DispatchSubagentTool`, `DispatchSubagentArgs`, constantes |
| `src/architect/tools/setup.py` | `register_dispatch_tool()` |
| `src/architect/cli.py` | `_subagent_factory()` closure, wiring |
| `tests/test_dispatch/test_dispatch.py` | 36 tests unitarios |
| `tests/test_bugfixes/test_bugfixes.py` | Tests BUG-4 (wiring) |
