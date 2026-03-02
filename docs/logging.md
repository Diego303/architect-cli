# Sistema de logging

Describe la arquitectura completa de logging del proyecto: tres pipelines independientes, el nivel HUMAN personalizado, el formato visual con iconos y la integración con el loop del agente.

> **v1.1.0**: Los mensajes del pipeline HUMAN ahora soportan i18n (inglés por defecto, español configurable). Los ejemplos en esta página muestran el formato inglés (default). Ver [`i18n.md`](i18n.md).

---

## Arquitectura: tres pipelines

El sistema usa **structlog** sobre la stdlib de Python con tres pipelines independientes. Cada uno tiene su propio handler, nivel y formato.

```
structlog.configure(
    processors=[..., wrap_for_formatter],  ← siempre wrap_for_formatter
    logger_factory=LoggerFactory(),        ← stdlib loggers
)
    │
    ▼
logging.root
    ├── [1] FileHandler        (JSON Lines, DEBUG+)       ← solo si --log-file
    ├── [2] HumanLogHandler    (stderr, solo HUMAN=25)    ← siempre activo (excepto --quiet/--json)
    └── [3] StreamHandler      (stderr, WARNING+ / -v)    ← consola técnico, excluye HUMAN
```

### Pipeline 1 — Archivo JSON (opcional)

Se activa con `--log-file PATH`. Captura **todos** los eventos (DEBUG+) en formato JSON Lines.

```bash
architect run "..." --log-file logs/session.jsonl
cat logs/session.jsonl | jq 'select(.event == "agent.tool_call.execute")'
```

### Pipeline 2 — Human handler (trazabilidad del agente)

Activo por defecto. Solo procesa eventos de nivel `HUMAN` (25). Produce output legible con iconos en stderr.

> **v1.1.0**: El idioma del output HUMAN depende de la configuración `language` (default: `en`). Ver [`i18n.md`](i18n.md).

```
🔄 Step 1 → LLM call (5 messages)
   ✓ LLM responded with 2 tool calls

   🔧 read_file → src/main.py
      ✓ OK

   🔧 edit_file → src/main.py (3→5 lines)
      ✓ OK
      🔍 Hook python-lint: ✓

🔄 Step 2 → LLM call (9 messages)
   ✓ LLM responded with final text

✅ Agent complete (2 steps)
   Reason: LLM decided it was done
   Cost: $0.0042
```

Con `language: es` en la configuración:

```
🔄 Paso 1 → Llamada al LLM (5 mensajes)
   ✓ LLM respondió con 2 tool calls
   ...
✅ Agente completado (2 pasos)
   Razón: LLM decidió que terminó
   Coste: $0.0042
```

Se desactiva con `--quiet` o `--json`.

### Pipeline 3 — Console técnico

Controlado por `-v` / `-vv` / `-vvv`. Muestra logs técnicos (INFO/DEBUG) en stderr. **Excluye** eventos HUMAN para evitar duplicados.

| Flag | Nivel | Qué muestra |
|------|-------|------------|
| (sin -v) | WARNING | Solo problemas |
| `-v` | INFO | Operaciones del sistema, config, registrations |
| `-vv` | DEBUG | Args completos, respuestas LLM, timing |
| `-vvv` | DEBUG | Todo, incluyendo HTTP |

---

## Nivel HUMAN (25)

Nivel personalizado entre INFO (20) y WARNING (30):

```python
# logging/levels.py
HUMAN = 25
logging.addLevelName(HUMAN, "HUMAN")
```

Los eventos HUMAN representan la **trazabilidad del agente** — qué está haciendo paso a paso. No son logs técnicos sino información para el usuario final.

---

## HumanFormatter — formato visual de eventos

Cada tipo de evento tiene su formato con iconos:

### Eventos del loop

> Los ejemplos muestran el formato en inglés (default). Con `language: es`, los mensajes se muestran en español.

| Evento | Formato (EN) | Icono |
|--------|---------|-------|
| `agent.llm.call` | `🔄 Step N → LLM call (M messages)` | 🔄 |
| `agent.llm.response` (tools) | `✓ LLM responded with N tool calls` | ✓ |
| `agent.llm.response` (texto) | `✓ LLM responded with final text` | ✓ |
| `agent.complete` | `✅ Agent complete (N steps)` + reason + cost | ✅ |

### Eventos de tools

| Evento | Formato | Icono |
|--------|---------|-------|
| `agent.tool_call.execute` (local) | `🔧 tool → resumen_args` | 🔧 |
| `agent.tool_call.execute` (MCP) | `🌐 tool → resumen (MCP: server)` | 🌐 |
| `agent.tool_call.complete` (ok) | `✓ OK` | ✓ |
| `agent.tool_call.complete` (error) | `✗ ERROR: mensaje` | ✗ |
| `agent.hook.complete` (named) | `🔍 Hook nombre: ✓/⚠️ detalle` | 🔍 |

### Safety nets

| Evento | Formato (EN) | Icono |
|--------|---------|-------|
| `safety.user_interrupt` | `⚠️ Interrupted by user` | ⚠️ |
| `safety.max_steps` | `⚠️ Step limit reached (N/M)` | ⚠️ |
| `safety.budget_exceeded` | `⚠️ Budget exceeded ($X/$Y)` | ⚠️ |
| `safety.timeout` | `⚠️ Timeout reached` | ⚠️ |
| `safety.context_full` | `⚠️ Context full` | ⚠️ |

### Errores y lifecycle

| Evento | Formato (EN) | Icono |
|--------|---------|-------|
| `agent.llm_error` | `❌ LLM error: message` | ❌ |
| `agent.step_timeout` | `⚠️ Step timeout (Ns)` | ⚠️ |
| `agent.closing` | `🔄 Closing (reason, N steps)` | 🔄 |
| `agent.loop.complete` (success) | `(N steps, M tool calls)` + cost | — |
| `agent.loop.complete` (partial) | `⚡ Stopped (status — reason, N steps)` | ⚡ |

### Pipeline (v1.1.0)

| Evento | Formato | Icono |
|--------|---------|-------|
| `pipeline.step_start` | `━ Pipeline step 1/3: analyze (agent: plan) ━━━━━` | ━ |
| `pipeline.step_skipped` | `⏭️  Step 'deploy' skipped (condition not met)` | ⏭️ |
| `pipeline.step_done` | `✓ Step 'analyze' → success ($0.0234, 12.5s)` | ✓/✗ |

### Ralph Loop (v1.1.0)

| Evento | Formato | Icono |
|--------|---------|-------|
| `ralph.iteration_start` | `━ Ralph iteration 1/5 (check: pytest tests/) ━━━` | ━ |
| `ralph.checks_result` | `🧪 Checks: 3/5 passed` (o `5/5 passed ✓`) | 🧪 |
| `ralph.iteration_done` | `✓ Iteration 1 → success ($0.0234, 45.2s)` | ✓/✗ |
| `ralph.complete` | `✅ Ralph complete — 2 iterations, success ($0.0423)` | ✅/⚠️ |

### Auto-Reviewer (v1.1.0)

| Evento | Formato | Icono |
|--------|---------|-------|
| `reviewer.start` | `━ Auto-Review (142 diff lines) ━━━━━━━━━━━━━` | ━ |
| `reviewer.complete` | `✓ Review complete: approved, 2 issues, score 8/10` | ✓/✗ |

### Parallel Runs (v1.1.0)

| Evento | Formato | Icono |
|--------|---------|-------|
| `parallel.worker_done` | `✓ Worker 1 (gpt-4.1) → success ($0.0456, 120.3s)` | ✓/✗ |
| `parallel.worker_error` | `✗ Worker 3 → error: timeout` | ✗ |
| `parallel.complete` | `⚡ Parallel complete — 3 workers: 2 success, 1 failed ($0.0857)` | ⚡ |

### Competitive Eval (v1.1.0)

| Evento | Formato | Icono |
|--------|---------|-------|
| `competitive.model_done` | `🏆 gpt-4.1: #1 (score: 85, 5/5 checks, $0.0456)` | 🏆/🥈/🥉 |
| `competitive.ranking` | `🏁 Ranking final: gpt-4.1 > claude-sonnet > gpt-4.1-mini` | 🏁 |

### Contexto

| Evento | Formato | Icono |
|--------|---------|-------|
| `context.compressing` | `📦 Compressing context — N exchanges` | 📦 |
| `context.window_enforced` | `📦 Context window: removed N messages` | 📦 |

---

## Args summarizer (`_summarize_args`)

Cada tool tiene un resumen optimizado para que el usuario entienda de un vistazo qué hace el agente:

| Tool | Ejemplo de resumen |
|------|-------------------|
| `read_file` | `src/main.py` |
| `write_file` | `src/main.py (42 lines)` |
| `edit_file` | `src/main.py (3→5 lines)` |
| `apply_patch` | `src/main.py (+5 -3)` |
| `search_code` | `"validate_path" in src/` |
| `grep` | `"import jwt" in src/` |
| `run_command` | `pytest tests/ -x` |
| MCP tools | primer argumento truncado a 60 chars |
| Unknown tool without args | `(no args)` |

---

## HumanLog — helper tipado

El `AgentLoop` emite eventos HUMAN a través de `HumanLog`, que provee métodos tipados:

```python
hlog = HumanLog(structlog.get_logger())

hlog.llm_call(step=0, messages_count=5)          # 🔄 Step 1 → LLM call (5 messages)
hlog.llm_response(tool_calls=2)                   # ✓ LLM responded with 2 tool calls
hlog.tool_call("read_file", {"path": "main.py"})  # 🔧 read_file → main.py
hlog.tool_call("mcp_docs_search", {"q": "..."}, is_mcp=True, mcp_server="docs")
                                                    # 🌐 mcp_docs_search → ... (MCP: docs)
hlog.tool_result("read_file", success=True)        # ✓ OK
hlog.hook_complete("edit_file", hook="ruff", success=True)
                                                    # 🔍 Hook ruff: ✓
hlog.agent_done(step=3, cost="$0.0042")            # ✅ Agent complete (3 steps)
hlog.safety_net("max_steps", step=50, max_steps=50)
                                                    # ⚠️ Step limit reached
hlog.closing("max_steps", steps=50)                # 🔄 Closing (max_steps, 50 steps)
hlog.llm_error("timeout")                          # ❌ LLM error: timeout
hlog.step_timeout(seconds=60)                      # ⚠️ Step timeout (60s)
hlog.loop_complete("success", None, 3, 5)          # (3 steps, 5 tool calls)

# Pipeline (v1.1.0)
hlog.pipeline_step_start("analyze", "plan", 1, 3)  # ━ Pipeline step 1/3: analyze ━━━
hlog.pipeline_step_skipped("deploy")                # ⏭️ Step 'deploy' skipped
hlog.pipeline_step_done("analyze", "success", 0.02, 12.5)  # ✓ Step 'analyze' → success

# Ralph Loop (v1.1.0)
hlog.ralph_iteration_start(1, 5, "pytest tests/")   # ━ Ralph iteration 1/5 ━━━
hlog.ralph_checks_result(1, 3, 5, False)             # 🧪 Checks: 3/5 passed
hlog.ralph_iteration_done(1, "partial", 0.02, 45.2)  # ✗ Iteration 1 → partial
hlog.ralph_complete(2, "success", 0.04)              # ✅ Ralph complete — 2 iterations

# Auto-Reviewer (v1.1.0)
hlog.reviewer_start(142)                             # ━ Auto-Review (142 diff lines) ━━━
hlog.reviewer_complete(True, 2, "8/10")              # ✓ Review complete: approved

# Parallel Runs (v1.1.0)
hlog.parallel_worker_done(1, "gpt-4.1", "success", 0.04, 120.3)
                                                      # ✓ Worker 1 (gpt-4.1) → success
hlog.parallel_worker_error(3, "timeout")              # ✗ Worker 3 → error: timeout
hlog.parallel_complete(3, 2, 1, 0.08)                 # ⚡ Parallel complete — 3 workers

# Competitive Eval (v1.1.0)
hlog.competitive_model_done("gpt-4.1", 1, 85, 0.04, 5, 5)
                                                      # 🏆 gpt-4.1: #1 (score: 85)
hlog.competitive_ranking([{"model": "gpt-4.1"}, {"model": "claude-sonnet"}])
                                                      # 🏁 Ranking final: gpt-4.1 > claude-sonnet
```

---

## HumanLogHandler — extracción de eventos estructurados

`HumanLogHandler` es un `logging.Handler` stdlib que:

1. Filtra solo eventos de nivel `HUMAN` exacto (25)
2. Extrae el event dict de `record.msg` (puesto por `wrap_for_formatter`)
3. Pasa el evento a `HumanFormatter.format_event()`
4. Escribe el resultado formateado a stderr

### Extracción del event dict

Cuando structlog usa `wrap_for_formatter`, el event dict se almacena como un `dict` en `record.msg`:

```python
def emit(self, record):
    if isinstance(record.msg, dict) and not record.args:
        # Evento de structlog: extraer del dict
        event = record.msg["event"]        # "agent.llm.call"
        kw = {k: v for k, v in record.msg.items() if k not in _STRUCTLOG_META}
    else:
        # Fallback: extraer de atributos del record
        event = getattr(record, "event", None) or record.getMessage()
```

Los campos filtrados de structlog (`_STRUCTLOG_META`) son: `event`, `level`, `log_level`, `logger`, `logger_name`, `timestamp`. Estos son metadatos del procesador, no kwargs del evento.

---

## Configuración (`logging/setup.py`)

### `configure_logging(config, json_output, quiet)`

```python
def configure_logging(config: LoggingConfig, json_output=False, quiet=False):
    # 1. Limpiar configuración anterior
    logging.root.handlers.clear()
    structlog.reset_defaults()

    # 2. Pipeline 1: Archivo JSON (si config.file está configurado)
    if config.file:
        file_handler = FileHandler(config.file)
        file_handler.setFormatter(ProcessorFormatter(processor=JSONRenderer()))
        logging.root.addHandler(file_handler)

    # 3. Pipeline 2: Human handler (si no --quiet ni --json)
    if show_human:
        human_handler = HumanLogHandler(stream=sys.stderr)
        human_handler.setLevel(HUMAN)
        human_handler.addFilter(lambda r: r.levelno == HUMAN)
        logging.root.addHandler(human_handler)

    # 4. Pipeline 3: Console técnico (si no --quiet ni --json)
    if show_console:
        console_handler = StreamHandler(sys.stderr)
        console_handler.setLevel(_verbose_to_level(config.verbose))
        console_handler.addFilter(lambda r: r.levelno != HUMAN)  # excluir HUMAN
        console_handler.setFormatter(ProcessorFormatter(processor=ConsoleRenderer()))
        logging.root.addHandler(console_handler)

    # 5. structlog: SIEMPRE wrap_for_formatter
    structlog.configure(
        processors=[..., wrap_for_formatter],
        logger_factory=LoggerFactory(),
    )
```

### Por qué siempre `wrap_for_formatter`

El procesador final de structlog **siempre** es `ProcessorFormatter.wrap_for_formatter`, independientemente de si hay `--log-file` o no. Esto garantiza que los eventos fluyan como dicts estructurados por el sistema de handlers de stdlib, lo que permite a `HumanLogHandler` extraer el event dict de `record.msg`.

Si se usara `ConsoleRenderer` directamente en la cadena de procesadores (como se hacía antes de v0.15.3), los eventos se renderizarían a texto plano antes de llegar a los handlers, y `HumanLogHandler` no podría extraer los nombres de evento para formatearlos.

---

## Verbose levels

| Verbose | Console level | Qué ve el usuario |
|---------|--------------|-------------------|
| 0 (default) | WARNING | Solo logs HUMAN (pasos del agente) + errores |
| 1 (`-v`) | INFO | HUMAN + operaciones del sistema |
| 2 (`-vv`) | DEBUG | HUMAN + todo el detalle técnico |
| 3+ (`-vvv`) | DEBUG | HUMAN + HTTP + payloads |

Los logs HUMAN se muestran **siempre** (excepto `--quiet` / `--json`), independientemente de `-v`.

---

## Relación con OpenTelemetry (v1.0.0)

A partir de v1.0.0, architect soporta trazas OpenTelemetry como complemento al logging estructurado. Las trazas y los logs son **sistemas independientes**:

| Sistema | Propósito | Configuración |
|---------|-----------|---------------|
| **Logging (structlog)** | Eventos del agente, debugging, human output | `logging:` en config + `-v` flags |
| **Telemetry (OpenTelemetry)** | Spans de sesión/LLM/tool para observabilidad | `telemetry:` en config |

Los logs van a stderr (human/técnico) y archivo JSON. Las trazas van a OTLP, console o archivo JSON separado. No se mezclan.

Ver [`telemetry.md`](telemetry.md) para configuración de OpenTelemetry.

---

## Archivos del módulo

| Archivo | Contenido |
|---------|-----------|
| `logging/levels.py` | Definición de `HUMAN = 25` |
| `logging/human.py` | `HumanFormatter`, `HumanLogHandler`, `HumanLog`, `_summarize_args` |
| `logging/setup.py` | `configure_logging()`, `configure_logging_basic()`, `get_logger()` |
| `telemetry/otel.py` | `ArchitectTracer`, `NoopTracer` (sistema independiente) |
