# El loop de agente (core/loop.py)

El `AgentLoop` es el corazón del sistema. Ver también [`logging.md`](logging.md) para detalles del sistema de logging.

Usa un bucle `while True` — el LLM decide cuándo terminar (deja de pedir tools). Los safety nets (max_steps, budget, timeout, context) son watchdogs que piden un cierre limpio al LLM en lugar de cortar abruptamente.

---

## Pseudocódigo completo (v3)

```python
def run(prompt, stream=False, on_stream_chunk=None):
    # Inicialización
    messages = ctx.build_initial(agent_config, prompt)
    tools_schema = registry.get_schemas(agent_config.allowed_tools or None)
    state = AgentState(messages=messages, model=llm.config.model, ...)
    step = 0

    while True:

        # ── SAFETY NETS (antes de cada llamada al LLM) ──────────
        stop_reason = _check_safety_nets(state, step)
        if stop_reason is not None:
            return _graceful_close(state, stop_reason, tools_schema)

        # ── CONTEXT MANAGEMENT ──────────────────────────────────
        if context_manager:
            messages = context_manager.manage(messages, llm)
            # manage() aplica:
            #   1. Compresión con LLM (si contexto > 75% del máximo)
            #   2. Ventana deslizante hard limit

        # ── LLAMADA AL LLM ──────────────────────────────────────
        hlog.llm_call(step, messages_count=len(messages))

        try:
            with StepTimeout(step_timeout):
                if stream:
                    response = None
                    for chunk_or_response in llm.completion_stream(messages, tools_schema):
                        if isinstance(chunk_or_response, StreamChunk):
                            if on_stream_chunk:
                                on_stream_chunk(chunk_or_response.data)  # → stderr
                        else:
                            response = chunk_or_response  # LLMResponse final

                else:
                    response = llm.completion(messages, tools_schema)

        except StepTimeoutError:
            hlog.step_timeout(step_timeout)
            return _graceful_close(state, StopReason.TIMEOUT, tools_schema)

        except Exception as e:
            hlog.llm_error(str(e))
            state.status = "failed"
            state.stop_reason = StopReason.LLM_ERROR
            state.final_output = f"Error irrecuperable del LLM: {e}"
            return state

        # ── REGISTRAR COSTE ─────────────────────────────────────
        if cost_tracker and response.usage:
            try:
                cost_tracker.record(step=step, model=..., usage=response.usage)
            except BudgetExceededError:
                return _graceful_close(state, StopReason.BUDGET_EXCEEDED, tools_schema)

        step += 1

        # ── EL LLM DECIDIÓ TERMINAR (no pidió tools) ───────────
        if not response.tool_calls:
            hlog.agent_done(step)
            state.final_output = response.content
            state.status = "success"
            state.stop_reason = StopReason.LLM_DONE
            break

        # ── EL LLM PIDIÓ TOOLS → EJECUTAR ──────────────────────
        tool_results = _execute_tool_calls_batch(response.tool_calls, step)
        messages = ctx.append_tool_results(messages, response.tool_calls, tool_results)
        state.steps.append(StepResult(step, response, tool_results))

    # ── Log final ───────────────────────────────────────────────
    hlog.loop_complete(status=state.status, stop_reason=...,
                       total_steps=state.current_step,
                       total_tool_calls=state.total_tool_calls)
    return state
```

### Diferencia clave con v1

```
ANTES (v1):                         AHORA (v3):

for i in range(max_steps):          while True:
    response = llm(...)                 if watchdog_triggered:
    if done: break                          graceful_close()  ← LLM resume
    execute_tools()                         break
else:                                   response = llm(...)
    status = "partial"  ← frío          if no tool_calls:
                                            done!  ← LLM decidió
                                            break
                                        execute_tools()
```

El `for-range` hace que `max_steps` sea la estructura. El `while True` hace que **la decisión del LLM** sea la estructura y `max_steps` sea un guardia.

---

## StopReason — por qué se detuvo el agente

```python
class StopReason(Enum):
    LLM_DONE = "llm_done"              # El LLM decidió que terminó (natural)
    MAX_STEPS = "max_steps"            # Watchdog: límite de pasos
    BUDGET_EXCEEDED = "budget_exceeded" # Watchdog: límite de coste
    CONTEXT_FULL = "context_full"      # Watchdog: context window lleno
    TIMEOUT = "timeout"                # Watchdog: tiempo total excedido
    USER_INTERRUPT = "user_interrupt"   # El usuario hizo Ctrl+C
    LLM_ERROR = "llm_error"           # Error irrecuperable del LLM
```

`StopReason` se guarda en `AgentState.stop_reason` y se incluye en el JSON output.

---

## Safety nets (`_check_safety_nets`)

Comprueban condiciones antes de cada iteración. Si alguna salta, devuelven un `StopReason` y el loop hace `_graceful_close()`.

```python
def _check_safety_nets(state, step) -> StopReason | None:
    # 1. User interrupt (Ctrl+C / SIGTERM) — más urgente
    if shutdown and shutdown.should_stop:
        return StopReason.USER_INTERRUPT

    # 2. Max steps — watchdog de pasos
    if step >= agent_config.max_steps:
        return StopReason.MAX_STEPS

    # 3. Timeout total — watchdog de tiempo
    if timeout and (time.time() - start_time) > timeout:
        return StopReason.TIMEOUT

    # 4. Context window críticamente lleno (>95%)
    if context_manager and context_manager.is_critically_full(messages):
        return StopReason.CONTEXT_FULL

    return None  # Todo bien, continuar
```

Cada safety net emite un log HUMAN via `hlog.safety_net()`.

---

## Cierre limpio (`_graceful_close`)

Cuando un safety net salta, no corta abruptamente. Le da al LLM una última oportunidad de resumir qué hizo y qué queda pendiente.

```python
def _graceful_close(state, reason, tools_schema) -> AgentState:
    hlog.closing(reason.value, len(state.steps))

    # USER_INTERRUPT: corte inmediato, sin llamar al LLM
    if reason == StopReason.USER_INTERRUPT:
        state.status = "partial"
        state.final_output = "Interrumpido por el usuario."
        return state

    # Para todos los demás: pedir resumen al LLM
    instruction = _CLOSE_INSTRUCTIONS[reason]
    state.messages.append({"role": "user", "content": f"[SISTEMA] {instruction}"})

    try:
        # Última llamada SIN tools — solo texto de cierre
        response = llm.completion(messages=state.messages, tools=None)
        state.final_output = response.content
    except Exception:
        state.final_output = f"El agente se detuvo ({reason.value})."

    state.status = "partial"
    state.stop_reason = reason
    hlog.loop_complete(status="partial", ...)
    return state
```

---

## Post-edit hooks (v3-M4)

Después de que el agente edita un archivo (`edit_file`, `write_file`, `apply_patch`), se ejecutan automáticamente hooks configurados (lint, typecheck, tests). El resultado vuelve al LLM como parte del tool result.

```python
def _execute_single_tool(tc, step) -> ToolCallResult:
    hlog.tool_call(tc.name, tc.arguments)

    result = engine.execute_tool_call(tc.name, tc.arguments)

    # v3-M4: Ejecutar hooks post-edit si aplican
    hook_output = engine.run_post_edit_hooks(tc.name, tc.arguments)

    if hook_output and result.success:
        # Añadir output de hooks al resultado del tool
        combined_output = result.output + "\n\n" + hook_output
        result = ToolResult(success=result.success, output=combined_output)
        hlog.hook_complete(tc.name)

    hlog.tool_result(tc.name, result.success, result.error)
    return ToolCallResult(tool_name=tc.name, args=tc.arguments, result=result)
```

Ejemplo de output con hooks:
```
   🔧 edit_file → src/main.py (3→5 líneas)
      ✓ OK
      🔍 Hook python-lint: ✓
```

Si un hook falla, el LLM ve el error y puede auto-corregir:
```
      🔍 Hook python-lint: ⚠️
         src/main.py:45: E302 expected 2 blank lines, found 1
```

### Configuración de hooks

```yaml
hooks:
  post_edit:
    - name: python-lint
      command: "ruff check {file} --no-fix"
      file_patterns: ["*.py"]
      timeout: 10

    - name: python-typecheck
      command: "mypy {file}"
      file_patterns: ["*.py"]
      timeout: 15
      enabled: false
```

El placeholder `{file}` se sustituye por el path del archivo editado. La variable de entorno `ARCHITECT_EDITED_FILE` también está disponible.

---

## Parallel tool calls

Cuando el LLM solicita varias tool calls en un mismo step, el loop puede ejecutarlas en paralelo.

### Lógica de decisión (`_should_parallelize`)

```python
def _should_parallelize(tool_calls) -> bool:
    # Desactivado si el config lo dice
    if context_manager and not context_manager.config.parallel_tools:
        return False

    # confirm-all: siempre secuencial (interacción con el usuario)
    if agent_config.confirm_mode == "confirm-all":
        return False

    # confirm-sensitive: secuencial si alguna tool es sensible
    if agent_config.confirm_mode == "confirm-sensitive":
        for tc in tool_calls:
            if registry.get(tc.name).sensitive:
                return False

    # yolo o confirm-sensitive sin tools sensibles → paralelo
    return True
```

### Implementación paralela

```python
def _execute_tool_calls_batch(tool_calls, step):
    if len(tool_calls) <= 1 or not _should_parallelize(tool_calls):
        return [_execute_single_tool(tc, step) for tc in tool_calls]

    # Ejecución paralela con ThreadPoolExecutor
    results = [None] * len(tool_calls)
    with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
        futures = {
            pool.submit(_execute_single_tool, tc, step): i
            for i, tc in enumerate(tool_calls)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
```

El patrón `{future: idx}` garantiza orden correcto independientemente del orden de completación.

---

## ContextManager — gestión del context window

El `ContextManager` actúa en tres niveles progresivos para evitar que el contexto se llene en tareas largas.

### Pipeline unificado (`manage`)

```python
def manage(messages, llm=None) -> list[dict]:
    # Solo comprimir si el contexto supera el 75% del máximo
    if llm and _is_above_threshold(messages, 0.75):
        messages = maybe_compress(messages, llm)
    messages = enforce_window(messages)
    return messages
```

El threshold del 75% evita compresiones innecesarias en tareas cortas. Si `max_context_tokens=0` (sin límite), se confía en `summarize_after_steps`.

### Nivel 1 — Truncado de tool results (`truncate_tool_result`)

Se aplica en `ContextBuilder._format_tool_result()` antes de añadir cada tool result al historial.

- `max_tool_result_tokens=0` desactiva el truncado.
- Preserva primeras 40 líneas + últimas 20 líneas + marcador de omisión.

### Nivel 2 — Compresión con LLM (`maybe_compress`)

Se activa cuando el número de intercambios supera `summarize_after_steps` Y el contexto está >75% lleno.

```python
def maybe_compress(messages, llm) -> list[dict]:
    tool_exchanges = _count_tool_exchanges(messages)
    if tool_exchanges <= config.summarize_after_steps:
        return messages  # sin cambios

    old_msgs = dialog[:-keep_count]
    recent_msgs = dialog[-keep_count:]

    # Resumir con el LLM; fallback mecánico si falla
    summary = _summarize_steps(old_msgs, llm)

    return [system_msg, user_msg, summary_msg, *recent_msgs]
```

Si el LLM falla al resumir (red, auth, etc.), se genera un resumen mecánico (lista de tools y archivos) como fallback.

### Nivel 3 — Ventana deslizante (`enforce_window`)

Hard limit que elimina pares de mensajes antiguos hasta que el total estimado cabe.

- `max_context_tokens=0` desactiva el límite.
- Siempre preserva `messages[0]` (system) y `messages[1]` (user original).

### `is_critically_full` — safety net del contexto

```python
def is_critically_full(messages) -> bool:
    # True si el contexto está al 95%+ del máximo
    return _estimate_tokens(messages) > int(max_context_tokens * 0.95)
```

Usado como safety net en el loop: si retorna True después de comprimir, el agente debe cerrar.

### Estimación de tokens (`_estimate_tokens`)

```python
def _estimate_tokens(messages) -> int:
    total_chars = 0
    for m in messages:
        if m.get("content"):
            total_chars += len(str(m["content"]))
        for tc in m.get("tool_calls", []):
            total_chars += len(str(tc["function"]["name"]))
            total_chars += len(str(tc["function"]["arguments"]))
        total_chars += 16  # overhead por mensaje
    return total_chars // 4
```

Extrae solo los campos de contenido relevantes (no serializa el dict completo) para evitar sobreestimaciones.

---

## Human logging (v3-M5+M6)

El sistema de logging tiene 3 pipelines:

1. **JSON file** (si configurado) — Todo, estructurado
2. **HumanLogHandler** (stderr) — Solo eventos de trazabilidad del agente (nivel HUMAN=25)
3. **Console técnico** (stderr) — Debug/info controlado por `-v`, excluyendo HUMAN

### Nivel HUMAN

```python
# logging/levels.py
HUMAN = 25  # entre INFO (20) y WARNING (30)
```

### HumanLog — helper tipado

El `AgentLoop` usa `self.hlog = HumanLog(logger)` para emitir eventos HUMAN:

```python
hlog.llm_call(step, messages_count)                    # "🔄 Paso N → Llamada al LLM (M mensajes)"
hlog.llm_response(tool_calls)                          # "   ✓ LLM respondió con N tool calls"
hlog.tool_call(name, args, is_mcp, mcp_server)        # "   🔧 tool → summary" or "   🌐 tool → summary (MCP: server)"
hlog.tool_result(name, success, error)                 # "      ✓ OK" or "      ✗ ERROR: ..."
hlog.hook_complete(name, hook, success, detail)        # "      🔍 Hook name: ✓/⚠️ detail"
hlog.agent_done(step, cost)                            # "✅ Agente completado (N pasos)" + cost
hlog.safety_net(reason, **kw)                          # "⚠️ Límite de pasos alcanzado..."
hlog.closing(reason, steps)                            # "🔄 Cerrando (reason, N pasos)"
hlog.loop_complete(status, stop_reason, total_steps, total_tool_calls)
hlog.llm_error(error)                                  # "❌ Error del LLM: ..."
hlog.step_timeout(seconds)                             # "⚠️ Step timeout (Ns)..."
```

### Formato visual de ejemplo

```
🔄 Paso 1 → Llamada al LLM (3 mensajes)
   ✓ LLM respondió con 2 tool calls

   🔧 read_file → src/main.py
      ✓ OK
   🔧 read_file → src/config.py
      ✓ OK

🔄 Paso 2 → Llamada al LLM (7 mensajes)
   ✓ LLM respondió con 1 tool call

   🔧 edit_file → src/main.py (3→5 líneas)
      ✓ OK
      🔍 Hook ruff: ✓

🔄 Paso 3 → Llamada al LLM (10 mensajes)
   ✓ LLM respondió con texto final

✅ Agente completado (3 pasos)
   Razón: LLM decidió que terminó
  (3 pasos, 3 tool calls)
```

### Args summarizer (M6)

`_summarize_args(tool_name, args)` produce resúmenes legibles por tool:

| Tool | Ejemplo de resumen |
|------|-------------------|
| `read_file` | `src/main.py` |
| `write_file` | `src/main.py (42 líneas)` |
| `edit_file` | `src/main.py (3→5 líneas)` |
| `apply_patch` | `src/main.py (+5 -3)` |
| `search_code` | `"validate_path" en src/` |
| `grep` | `"import jwt" en src/` |
| `run_command` | `pytest tests/ -x` |
| MCP tools | primer argumento truncado a 60 chars |

---

## SelfEvaluator — auto-evaluación del resultado (F12)

Se invoca desde la CLI **después** de que el agente completa su ejecución. Solo evalúa estados `"success"`.

### `evaluate_basic` — una evaluación

El LLM evalúa el resultado y responde en JSON: `{"completed": true, "confidence": 0.92, "issues": [], "suggestion": ""}`. Si no pasa, `state.status = "partial"`.

### `evaluate_full` — evaluación + reintentos

Hasta `max_retries` ciclos de `evaluate_basic()` + `run_fn(correction_prompt)`. Retorna el mejor estado.

### Parseo de respuesta JSON

Tres estrategias en orden:
1. `json.loads(content)` directo.
2. Regex para bloque de código JSON.
3. Regex para primer `{...}`.

---

## Estado del loop (AgentState)

```
AgentState
├── messages: list[dict]           ← historial OpenAI (gestionado por ContextManager)
├── steps: list[StepResult]        ← resultados inmutables de cada step
├── status: str                    ← "running" | "success" | "partial" | "failed"
├── stop_reason: StopReason | None ← por qué se detuvo
├── final_output: str | None       ← respuesta final del agente
├── start_time: float              ← para calcular duration_seconds
├── model: str | None              ← modelo usado
└── cost_tracker: CostTracker | None ← F14: tracker de costes
```

Transiciones de estado (v3):

```
                  tool_calls
"running" ──────────────────────→ "running" (siguiente step)
    │
    │  no tool_calls (LLM decidió terminar)
    ├──────────────────────────→ "success" (StopReason.LLM_DONE)
    │                               │
    │                               │ SelfEvaluator (básico, falla)
    │                               └──────────→ "partial"
    │
    │  safety net: MAX_STEPS
    ├──────────────────────────→ _graceful_close → "partial"
    │                            (LLM resume qué hizo)
    │
    │  safety net: BUDGET_EXCEEDED
    ├──────────────────────────→ _graceful_close → "partial"
    │
    │  safety net: TIMEOUT / CONTEXT_FULL
    ├──────────────────────────→ _graceful_close → "partial"
    │
    │  safety net: USER_INTERRUPT
    ├──────────────────────────→ "partial" (corte inmediato, sin LLM)
    │
    │  LLM Exception
    └──────────────────────────→ "failed" (StopReason.LLM_ERROR)
```

---

## Acumulación de mensajes (ContextBuilder)

Cada step añade mensajes. El historial (o la versión comprimida) se envía al LLM en cada llamada.

```
Paso 0 (inicial):
messages = [
  {"role": "system",    "content": "Eres un agente de build...\n\n## Estructura del Proyecto\n..."},
  {"role": "user",      "content": "refactoriza main.py"}
]

Después de tool calls en step 1 (con truncado Nivel 1):
messages = [
  {"role": "system",    "content": "..."},
  {"role": "user",      "content": "refactoriza main.py"},
  {"role": "assistant", "tool_calls": [...]},
  {"role": "tool",      "content": "def foo():\n    pass\n...\n[... 120 líneas omitidas ...]\n..."}
]

Después de 9+ steps (con compresión Nivel 2, si contexto > 75%):
messages = [
  {"role": "system",    "content": "..."},
  {"role": "user",      "content": "refactoriza main.py"},
  {"role": "assistant", "content": "[Resumen de pasos anteriores]\nEl agente leyó main.py, ..."},
  ... (últimos 4 steps completos) ...
]
```

---

## Streaming

Cuando `stream=True`:
1. `llm.completion_stream(messages, tools)` devuelve un generator.
2. Cada `StreamChunk` tiene `type="content"` y `data=str`.
3. El loop llama a `on_stream_chunk(chunk.data)` — escribe a `stderr`.
4. El último item es un `LLMResponse` completo (con `tool_calls` si los hay).
5. Los chunks de tool calls **no** se envían al callback.

El streaming se desactiva automáticamente en: fase plan del modo mixto, `--json`, `--quiet`, `--no-stream`, reintentos de `evaluate_full`.

---

## Shutdown graceful (GracefulShutdown)

```
GracefulShutdown
├── __init__: instala handler en SIGINT + SIGTERM
├── _handler(signum):
│     1er disparo → _interrupted=True, avisa en stderr
│     2do disparo SIGINT → sys.exit(130) inmediato
└── should_stop: property → _interrupted
```

El loop comprueba `shutdown.should_stop` en `_check_safety_nets()` al inicio de cada iteración. Si True, `_graceful_close()` corta inmediatamente (USER_INTERRUPT no llama al LLM).

---

## Timeout por step (StepTimeout)

```python
with StepTimeout(60):          # 60 segundos
    response = llm.completion(...)
# Si tarda > 60s: SIGALRM → StepTimeoutError → _graceful_close(TIMEOUT)
```

- Solo activo en Linux/macOS (usa `SIGALRM`). En Windows: no-op.
- `step_timeout` viene del flag `--timeout` de CLI.

---

## Parámetros del constructor

```python
AgentLoop(
    llm:             LLMAdapter,
    engine:          ExecutionEngine,
    agent_config:    AgentConfig,
    ctx:             ContextBuilder,
    shutdown:        GracefulShutdown | None = None,
    step_timeout:    int = 0,                        # 0 = sin timeout
    context_manager: ContextManager | None = None,
    cost_tracker:    CostTracker | None = None,      # F14: tracking de costes
    timeout:         int | None = None,              # timeout total de ejecución
)
```

El loop no crea sus dependencias — las recibe como parámetros (inyección de dependencias). Internamente crea `self.hlog = HumanLog(logger)` para emitir logs de trazabilidad.
