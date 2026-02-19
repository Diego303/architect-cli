# El loop de agente (core/loop.py)

El `AgentLoop` es el corazón del sistema. Itera entre llamadas al LLM y ejecuciones de herramientas hasta que el agente termina, alcanza el límite de pasos, es interrumpido o expira el timeout.

---

## Pseudocódigo completo

```python
def run(prompt, stream=False, on_stream_chunk=None):
    # Inicialización
    messages = ctx.build_initial(agent_config, prompt)
    # messages = [
    #   {"role": "system", "content": agent_config.system_prompt},
    #   {"role": "user",   "content": prompt}
    # ]

    tools_schema = registry.get_schemas(agent_config.allowed_tools or None)
    # Lista de dicts JSON Schema en formato OpenAI function-calling

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
            tool_results = []
            for tc in response.tool_calls:
                result = engine.execute_tool_call(tc.name, tc.arguments)
                tool_results.append(ToolCallResult(
                    tool_name=tc.name,
                    args=tc.arguments,
                    result=result,
                ))

            messages = ctx.append_tool_results(messages, response.tool_calls, tool_results)
            state.steps.append(StepResult(step_num + 1, response, tool_results))
            # → continúa al siguiente step

        # ── 4. SIN TOOL CALLS Y SIN STOP ─────────────────────────────
        elif response.finish_reason == "length":
            # El modelo alcanzó el límite de tokens; intentar continuar
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

## Estado del loop (AgentState)

```
AgentState
├── messages: list[dict]      ← historial OpenAI, crece cada step
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

Cada step añade mensajes a la lista. El historial completo se envía al LLM en cada llamada.

```
Paso 0 (inicial):
messages = [
  {"role": "system",    "content": "Eres un agente de build..."},
  {"role": "user",      "content": "refactoriza main.py"}
]

Después de tool calls en step 1:
messages = [
  {"role": "system",    "content": "..."},
  {"role": "user",      "content": "refactoriza main.py"},
  {"role": "assistant", "content": null,
   "tool_calls": [
     {"id": "call_abc", "type": "function",
      "function": {"name": "read_file", "arguments": "{\"path\":\"main.py\"}"}}
   ]
  },
  {"role": "tool",      "tool_call_id": "call_abc",
   "content": "def foo():\n    pass\n..."}
]

Después del step 2 final (sin tool calls):
messages = [
  ... los anteriores ...
  {"role": "assistant", "content": "He refactorizado main.py. Los cambios son..."}
]
```

El formato `assistant` + `tool` (uno por cada tool call) es el que OpenAI/Anthropic/LiteLLM esperan para tool calling. **El orden y los IDs son críticos** — si no coinciden, el LLM puede rechazar la conversación.

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
    llm:          LLMAdapter,
    engine:       ExecutionEngine,
    agent_config: AgentConfig,
    ctx:          ContextBuilder,
    shutdown:     GracefulShutdown | None = None,
    step_timeout: int = 0,               # 0 = sin timeout
)
```

El loop no crea sus dependencias — las recibe como parámetros (inyección de dependencias). Esto facilita testing y composición (MixedModeRunner reutiliza el mismo `llm` y `engine` en ambas fases).
