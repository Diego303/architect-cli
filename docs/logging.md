# Sistema de logging

Describe la arquitectura completa de logging del proyecto: tres pipelines independientes, el nivel HUMAN personalizado, el formato visual con iconos y la integración con el loop del agente.

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

```
🔄 Paso 1 → Llamada al LLM (5 mensajes)
   ✓ LLM respondió con 2 tool calls

   🔧 read_file → src/main.py
      ✓ OK

   🔧 edit_file → src/main.py (3→5 líneas)
      ✓ OK
      🔍 Hook python-lint: ✓

🔄 Paso 2 → Llamada al LLM (9 mensajes)
   ✓ LLM respondió con texto final

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

| Evento | Formato | Icono |
|--------|---------|-------|
| `agent.llm.call` | `🔄 Paso N → Llamada al LLM (M mensajes)` | 🔄 |
| `agent.llm.response` (tools) | `✓ LLM respondió con N tool calls` | ✓ |
| `agent.llm.response` (texto) | `✓ LLM respondió con texto final` | ✓ |
| `agent.complete` | `✅ Agente completado (N pasos)` + razón + coste | ✅ |

### Eventos de tools

| Evento | Formato | Icono |
|--------|---------|-------|
| `agent.tool_call.execute` (local) | `🔧 tool → resumen_args` | 🔧 |
| `agent.tool_call.execute` (MCP) | `🌐 tool → resumen (MCP: server)` | 🌐 |
| `agent.tool_call.complete` (ok) | `✓ OK` | ✓ |
| `agent.tool_call.complete` (error) | `✗ ERROR: mensaje` | ✗ |
| `agent.hook.complete` (named) | `🔍 Hook nombre: ✓/⚠️ detalle` | 🔍 |

### Safety nets

| Evento | Formato | Icono |
|--------|---------|-------|
| `safety.user_interrupt` | `⚠️ Interrumpido por el usuario` | ⚠️ |
| `safety.max_steps` | `⚠️ Límite de pasos alcanzado (N/M)` | ⚠️ |
| `safety.budget_exceeded` | `⚠️ Presupuesto excedido ($X/$Y)` | ⚠️ |
| `safety.timeout` | `⚠️ Timeout alcanzado` | ⚠️ |
| `safety.context_full` | `⚠️ Contexto lleno` | ⚠️ |

### Errores y lifecycle

| Evento | Formato | Icono |
|--------|---------|-------|
| `agent.llm_error` | `❌ Error del LLM: mensaje` | ❌ |
| `agent.step_timeout` | `⚠️ Step timeout (Ns)` | ⚠️ |
| `agent.closing` | `🔄 Cerrando (razón, N pasos)` | 🔄 |
| `agent.loop.complete` (success) | `(N pasos, M tool calls)` + coste | — |
| `agent.loop.complete` (partial) | `⚡ Detenido (status — razón, N pasos)` | ⚡ |

### Contexto

| Evento | Formato | Icono |
|--------|---------|-------|
| `context.compressing` | `📦 Comprimiendo contexto — N intercambios` | 📦 |
| `context.window_enforced` | `📦 Ventana de contexto: eliminados N mensajes` | 📦 |

---

## Args summarizer (`_summarize_args`)

Cada tool tiene un resumen optimizado para que el usuario entienda de un vistazo qué hace el agente:

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
| Tool desconocida sin args | `(sin args)` |

---

## HumanLog — helper tipado

El `AgentLoop` emite eventos HUMAN a través de `HumanLog`, que provee métodos tipados:

```python
hlog = HumanLog(structlog.get_logger())

hlog.llm_call(step=0, messages_count=5)          # 🔄 Paso 1 → LLM (5 mensajes)
hlog.llm_response(tool_calls=2)                   # ✓ LLM respondió con 2 tool calls
hlog.tool_call("read_file", {"path": "main.py"})  # 🔧 read_file → main.py
hlog.tool_call("mcp_docs_search", {"q": "..."}, is_mcp=True, mcp_server="docs")
                                                    # 🌐 mcp_docs_search → ... (MCP: docs)
hlog.tool_result("read_file", success=True)        # ✓ OK
hlog.hook_complete("edit_file", hook="ruff", success=True)
                                                    # 🔍 Hook ruff: ✓
hlog.agent_done(step=3, cost="$0.0042")            # ✅ Agente completado (3 pasos)
hlog.safety_net("max_steps", step=50, max_steps=50)
                                                    # ⚠️ Límite de pasos alcanzado
hlog.closing("max_steps", steps=50)                # 🔄 Cerrando (max_steps, 50 pasos)
hlog.llm_error("timeout")                          # ❌ Error del LLM: timeout
hlog.step_timeout(seconds=60)                      # ⚠️ Step timeout (60s)
hlog.loop_complete("success", None, 3, 5)          # (3 pasos, 5 tool calls)
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

## Archivos del módulo

| Archivo | Contenido |
|---------|-----------|
| `logging/levels.py` | Definición de `HUMAN = 25` |
| `logging/human.py` | `HumanFormatter`, `HumanLogHandler`, `HumanLog`, `_summarize_args` |
| `logging/setup.py` | `configure_logging()`, `configure_logging_basic()`, `get_logger()` |
