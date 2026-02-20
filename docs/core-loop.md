# El loop de agente (core/loop.py)

El `AgentLoop` es el corazón del sistema. Itera entre llamadas al LLM y ejecuciones de herramientas hasta que el agente termina, alcanza el límite de pasos, es interrumpido o expira el timeout. El `ContextManager` controla el tamaño del contexto en cada iteración.

---

## Pseudocódigo completo

```python
def run(prompt, stream=False, on_stream_chunk=None):
    # Inicialización
    messages = ctx.build_initial(agent_config, prompt)
    # messages = [
    #   {"role": "system", "content": agent_config.system_prompt + árbol_del_repo},
    #   {"role": "user",   "content": prompt}
    # ]

    tools_schema = registry.get_schemas(agent_config.allowed_tools or None)
    state = AgentState(messages=messages, model=llm.config.model, ...)

    for step_num in range(agent_config.max_steps):

        # ── 0. SHUTDOWN CHECK ────────────────────────────────────────
        if shutdown and shutdown.should_stop:
            state.status = "partial"
            state.final_output = "Ejecución interrumpida por señal de shutdown."
            break

        # ── 1. LLAMADA AL LLM ────────────────────────────────────────
        try:
            with StepTimeout(step_timeout):
                if stream:
                    response = None
                    for item in llm.completion_stream(messages, tools_schema):
                        if isinstance(item, StreamChunk):
                            if on_stream_chunk:
                                on_stream_chunk(item.data)  # → stderr
                        else:
                            response = item  # LLMResponse final
                else:
                    response = llm.completion(messages, tools_schema)

        except StepTimeoutError as e:
            state.status = "partial"
            state.final_output = f"Step {step_num+1} excedió timeout de {e.seconds}s"
            break

        except Exception as e:
            state.status = "failed"
            state.final_output = f"Error del LLM: {e}"
            break

        # ── 2. ¿TERMINÓ EL AGENTE? ───────────────────────────────────
        if response.finish_reason == "stop" and not response.tool_calls:
            state.final_output = response.content or ""
            state.status = "success"
            break

        # ── 3. EJECUTAR TOOL CALLS ───────────────────────────────────
        if response.tool_calls:
            # Paralelo o secuencial según _should_parallelize()
            tool_results = _execute_tool_calls_batch(response.tool_calls, step_num)

            messages = ctx.append_tool_results(messages, response.tool_calls, tool_results)
            state.steps.append(StepResult(step_num + 1, response, tool_results))

            # ── 3b. CONTEXT PRUNING (F11) ─────────────────────────────
            if context_manager:
                messages = context_manager.maybe_compress(messages, llm)   # Nivel 2
                messages = context_manager.enforce_window(messages)          # Nivel 3

            # → continúa al siguiente step

        # ── 4. SIN TOOL CALLS Y SIN STOP ─────────────────────────────
        elif response.finish_reason == "length":
            messages = ctx.append_assistant_message(messages, response.content or "")
            messages = ctx.append_user_message(messages, "Continúa desde donde te quedaste.")
        else:
            state.status = "partial"
            state.final_output = response.content or ""
            break

    else:
        # El for llegó a max_steps sin break
        state.status = "partial"
        state.final_output = f"Se alcanzó el límite de {agent_config.max_steps} pasos..."

    return state
```

---

## Parallel tool calls (F11)

Cuando el LLM solicita varias tool calls en un mismo step, el loop puede ejecutarlas en paralelo.

### Lógica de decisión (`_should_parallelize`)

```python
def _should_parallelize(self, tool_calls: list[ToolCall]) -> bool:
    # Desactivado si el config lo dice
    if self.context_manager and not self.context_manager.config.parallel_tools:
        return False

    # confirm-all: siempre secuencial (interacción con el usuario)
    if self.agent_config.confirm_mode == "confirm-all":
        return False

    # confirm-sensitive: secuencial si alguna tool es sensible
    if self.agent_config.confirm_mode == "confirm-sensitive":
        for tc in tool_calls:
            if self.engine.registry.has_tool(tc.name):
                tool = self.engine.registry.get(tc.name)
                if tool.sensitive:
                    return False

    # yolo o confirm-sensitive sin tools sensibles → paralelo
    return True
```

### Implementación paralela

```python
def _execute_tool_calls_batch(self, tool_calls, step_num):
    if len(tool_calls) <= 1 or not self._should_parallelize(tool_calls):
        # Ejecución secuencial
        return [self._execute_single_tool(tc, step_num) for tc in tool_calls]

    # Ejecución paralela con ThreadPoolExecutor
    results = [None] * len(tool_calls)
    with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
        futures = {
            pool.submit(self._execute_single_tool, tc, step_num): i
            for i, tc in enumerate(tool_calls)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
    return results
```

El patrón `futures = {future: idx}` garantiza que los resultados se colocan en la posición correcta aunque los futures completen en diferente orden. El LLM siempre recibe los resultados en el orden en que solicitó las tool calls.

**Thread safety**: structlog es thread-safe. `engine.execute_tool_call()` nunca lanza excepciones. Cada tool call opera sobre un archivo diferente habitualmente, pero incluso si hubiera colisiones, el resultado sería un error controlado devuelto al LLM.

---

## ContextManager — gestión del context window (F11)

El `ContextManager` actúa en tres niveles progresivos para evitar que el contexto del LLM se llene en tareas largas.

### Nivel 1 — Truncado de tool results (`truncate_tool_result`)

Se aplica en `ContextBuilder._format_tool_result()` antes de añadir cada tool result al historial.

```python
def truncate_tool_result(self, content: str) -> str:
    max_chars = self.config.max_tool_result_tokens * 4  # ~4 chars/token
    if len(content) <= max_chars:
        return content

    lines = content.split("\n")
    head = lines[:40]    # primeras 40 líneas (inicio del archivo)
    tail = lines[-20:]   # últimas 20 líneas (final del archivo)
    omitted = len(lines) - 60
    marker = f"\n[... {omitted} líneas omitidas ...]\n"
    return "\n".join(head) + marker + "\n".join(tail)
```

- `max_tool_result_tokens=0` desactiva el truncado.
- Un `read_file` de 500 líneas → el agente recibe las primeras 40 + las últimas 20.
- El marcador indica cuánto se omitió para que el LLM sepa que hay contenido intermedio.

### Nivel 2 — Compresión con LLM (`maybe_compress`)

Se aplica en el loop **después** de cada step con tool calls.

```python
def maybe_compress(self, messages: list[dict], llm: LLMAdapter) -> list[dict]:
    tool_exchanges = self._count_tool_exchanges(messages)
    if tool_exchanges <= self.config.summarize_after_steps:
        return messages  # sin cambios

    # Separar mensajes en "antiguos" y "recientes"
    keep_count = self.config.keep_recent_steps * 3  # ~3 mensajes por step
    dialog = messages[2:]  # excluir system y user iniciales
    old_msgs = dialog[:-keep_count]
    recent_msgs = dialog[-keep_count:]

    # Resumir los pasos antiguos con el LLM (~200 palabras)
    summary = self._summarize_steps(old_msgs, llm)

    # Resultado: [system, user, summary_assistant, *recent_steps]
    return [
        messages[0],   # system
        messages[1],   # user original
        {"role": "assistant", "content": f"[Resumen de pasos anteriores]\n{summary}"},
        *recent_msgs,
    ]
```

- `summarize_after_steps=0` desactiva la compresión.
- Si el LLM falla al resumir, los mensajes originales se retornan sin cambios (fallo silencioso).
- `_count_tool_exchanges()` cuenta mensajes assistant con `tool_calls` no vacíos.

### Nivel 3 — Ventana deslizante (`enforce_window`)

Se aplica en el loop **después** de `maybe_compress`.

```python
def enforce_window(self, messages: list[dict]) -> list[dict]:
    if self.config.max_context_tokens == 0:
        return messages

    while (len(messages) > 4 and
           self._estimate_tokens(messages) > self.config.max_context_tokens):
        # Eliminar el par de mensajes más antiguo (después de system+user)
        messages = [messages[0], messages[1]] + messages[4:]
        # (se eliminan los mensajes [2] y [3]: el assistant+tool más antiguo)

    return messages
```

- `max_context_tokens=0` desactiva el límite hard.
- Siempre preserva `messages[0]` (system) y `messages[1]` (user original).
- `_estimate_tokens()` = `len(str(messages)) // 4` (aproximación ~4 chars/token).
- Valores recomendados: `gpt-4o` / `gpt-4o-mini` → 80000, `claude-sonnet-4-6` → 150000.

---

## SelfEvaluator — auto-evaluación del resultado (F12)

El `SelfEvaluator` se invoca desde la CLI **después** de que el agente completa su ejecución.

### Integración en el flujo

```python
# En cli.py, después de state = runner.run(prompt, ...) o loop.run(prompt, ...)

self_eval_mode = kwargs.get("self_eval") or config.evaluation.mode

if self_eval_mode != "off" and state.status == "success":
    evaluator = SelfEvaluator(
        llm,
        max_retries=config.evaluation.max_retries,
        confidence_threshold=config.evaluation.confidence_threshold,
    )

    if self_eval_mode == "basic":
        eval_result = evaluator.evaluate_basic(prompt, state)
        passed = (eval_result.completed
                  and eval_result.confidence >= config.evaluation.confidence_threshold)
        if not passed:
            state.status = "partial"  # modifica el estado

    elif self_eval_mode == "full":
        state = evaluator.evaluate_full(prompt, state, run_fn)
        # run_fn = lambda p: runner.run(p, stream=False)  — sin streaming para reintentos
```

### `evaluate_basic` — una evaluación

```python
def evaluate_basic(self, original_prompt: str, state: AgentState) -> EvalResult:
    eval_messages = [
        {"role": "system", "content": self._EVAL_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"**Tarea original:**\n{original_prompt}\n\n"
            f"**Resultado del agente:**\n{state.final_output[:500]}\n\n"
            f"**Acciones ejecutadas:**\n{self._summarize_steps(state)}\n\n"
            f"¿La tarea se completó correctamente?"
        )},
    ]
    response = self.llm.completion(eval_messages, tools=None)  # sin tools, solo texto
    return self._parse_eval(response.content)
```

El system prompt obliga al LLM evaluador a responder **solo en JSON**:
```json
{"completed": true, "confidence": 0.92, "issues": [], "suggestion": ""}
```

### `evaluate_full` — evaluación + reintentos

```python
def evaluate_full(self, original_prompt, state, run_fn) -> AgentState:
    for attempt in range(self.max_retries):
        eval_result = self.evaluate_basic(original_prompt, state)

        if eval_result.completed and eval_result.confidence >= self.confidence_threshold:
            return state  # éxito temprano

        correction_prompt = self._build_correction_prompt(original_prompt, eval_result)
        try:
            state = run_fn(correction_prompt)
        except Exception:
            break  # fallo silencioso — retorna el último estado disponible

    return state  # retorna el último estado aunque no haya pasado
```

### Parseo de respuesta JSON (`_parse_eval`)

Tres estrategias en orden:
1. `json.loads(content)` directo — caso ideal.
2. Regex `r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'` — LLM envolvió en bloque de código.
3. Regex `r'\{[\s\S]*?\}'` — extrae el primer `{...}` del texto.

Si todas fallan → `EvalResult(completed=False, confidence=0.0, issues=["No se pudo parsear..."])`.

La `confidence` siempre se clampea a `[0.0, 1.0]` independientemente de lo que devuelva el LLM.

---

## Estado del loop (AgentState)

```
AgentState
├── messages: list[dict]      ← historial OpenAI, crece cada step
│                                (puede ser podado por ContextManager)
├── steps: list[StepResult]   ← resultados inmutables de cada step
├── status: str               ← "running" | "success" | "partial" | "failed"
├── final_output: str | None  ← respuesta final del agente
├── start_time: float         ← para calcular duration_seconds
└── model: str | None         ← modelo usado (para --json output)
```

Transiciones de estado:

```
              tool_calls
"running" ──────────────────────────→ "running" (siguiente step)
    │
    │  finish_reason="stop" AND no tool_calls
    ├──────────────────────────────→ "success"
    │                                   │
    │                                   │ SelfEvaluator (básico, falla)
    │                                   ├──────────────→ "partial"
    │                                   │
    │                                   │ SelfEvaluator (full, itera)
    │                                   └──────────────→ "success" | "partial" | "failed"
    │
    │  max_steps alcanzado
    ├──────────────────────────────→ "partial"
    │
    │  StepTimeoutError
    ├──────────────────────────────→ "partial"
    │
    │  shutdown.should_stop
    ├──────────────────────────────→ "partial"
    │
    │  finish_reason != "stop" AND no tool_calls AND != "length"
    ├──────────────────────────────→ "partial"
    │
    │  LLM Exception
    └──────────────────────────────→ "failed"
```

---

## Acumulación de mensajes (ContextBuilder)

Cada step añade mensajes a la lista. El historial completo (o la versión podada) se envía al LLM en cada llamada.

```
Paso 0 (inicial):
messages = [
  {"role": "system",    "content": "Eres un agente de build...\n\n## Estructura del Proyecto\n..."},
  {"role": "user",      "content": "refactoriza main.py"}
]

Después de tool calls en step 1 (con truncado Nivel 1 en el tool result):
messages = [
  {"role": "system",    "content": "..."},
  {"role": "user",      "content": "refactoriza main.py"},
  {"role": "assistant", "content": null,
   "tool_calls": [
     {"id": "call_abc", "type": "function",
      "function": {"name": "read_file", "arguments": "{\"path\":\"main.py\"}"}}
   ]
  },
  {"role": "tool", "tool_call_id": "call_abc",
   "content": "def foo():\n    pass\n...\n[... 120 líneas omitidas ...]\n...fin del archivo"}
]

Después de 9+ steps (con compresión Nivel 2):
messages = [
  {"role": "system",    "content": "..."},
  {"role": "user",      "content": "refactoriza main.py"},
  {"role": "assistant", "content": "[Resumen de pasos anteriores]\nEl agente leyó main.py, ..."},
  ... (últimos 4 steps completos) ...
]
```

El `ContextBuilder` también inyecta el árbol del repositorio (`RepoIndex.format_tree()`) al final del system prompt cuando hay un `RepoIndex` disponible.

---

## Streaming

Cuando `stream=True`:

1. `llm.completion_stream(messages, tools)` devuelve un generator.
2. Cada `StreamChunk` tiene `type="content"` y `data=str` con el texto parcial.
3. El loop llama a `on_stream_chunk(chunk.data)` — normalmente esto escribe a `stderr`.
4. El último item del generator es un `LLMResponse` completo (con `tool_calls` si los hay).
5. Los chunks de tool calls **no** se envían al callback — se acumulan internamente y se devuelven en el `LLMResponse` final.

```
generator yields:
  StreamChunk("content", "He")
  StreamChunk("content", " analizado")
  StreamChunk("content", " main.py")
  LLMResponse(content="He analizado main.py", tool_calls=[], finish_reason="stop")
```

El streaming se desactiva automáticamente en:
- Fase plan del modo mixto (es rápido, el output importa menos).
- `--json` o `--quiet` (no hay terminal interactiva que se beneficie).
- `--no-stream` explícito.
- Reintentos de `evaluate_full` (el callback ya no tiene sentido en la corrección).

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

El loop comprueba `shutdown.should_stop` **al inicio de cada iteración**, no dentro de la llamada al LLM. Esto significa:
- Si el usuario pulsa Ctrl+C mientras el LLM está respondiendo, el step actual termina.
- En el siguiente step, el loop detecta `should_stop=True` y sale limpiamente.
- El agente retorna `status="partial"` (no "failed").

---

## Timeout por step (StepTimeout)

```python
with StepTimeout(60):          # 60 segundos
    response = llm.completion(...)
# Si tarda > 60s: SIGALRM → StepTimeoutError → status="partial"
# Si termina antes: signal.alarm(0) cancela la alarma
```

- Sólo activo en Linux/macOS (usa `SIGALRM`).
- En Windows: no-op transparente (sin timeout garantizado).
- Restaura el handler anterior al salir — compatible con nesting.
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
    step_timeout:    int = 0,               # 0 = sin timeout
    context_manager: ContextManager | None = None,  # F11: pruning de contexto
)
```

El loop no crea sus dependencias — las recibe como parámetros (inyección de dependencias). Esto facilita testing y composición (MixedModeRunner reutiliza el mismo `llm`, `context_manager` y `shutdown` en ambas fases).
