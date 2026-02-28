# Changelog

Todos los cambios notables en el proyecto architect serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y este proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

---

## [1.1.0] - 2026-02-28

### Guardrails: `sensitive_files` — Protección de lectura y escritura

#### Añadido

- **`sensitive_files` en GuardrailsConfig** — Nuevo campo que bloquea LECTURA y ESCRITURA de archivos sensibles. A diferencia de `protected_files` (que solo bloquea escritura), `sensitive_files` impide que el agente lea el contenido de archivos como `.env`, `*.pem`, `*.key`, evitando que secrets se envíen al proveedor de LLM. (`src/architect/config/schema.py`)
- **Detección de lecturas shell** — Nuevo regex `_READ_CMD_RE` y helper `_extract_read_targets()` que detectan comandos `cat`, `head`, `tail`, `less`, `more` intentando leer archivos sensibles. (`src/architect/core/guardrails.py`)
- **`read_file` en guardrails check** — El tool `read_file` ahora pasa por `check_file_access()` en el ExecutionEngine, bloqueándose si el archivo está en `sensitive_files`. (`src/architect/execution/engine.py`)
- **Auto-enable** — `sensitive_files` activa automáticamente el sistema de guardrails si tiene patrones configurados, igual que `protected_files` y otros campos. (`src/architect/config/schema.py`)
- **30 tests nuevos** — `TestSensitiveFiles` (22 tests: lectura bloqueada, escritura bloqueada, protected vs sensitive, shell reads, shell redirects, basename matching), `TestExtractReadTargets` (6 tests), `TestGuardrailsConfigSchema` ampliado (3 tests). (`tests/test_guardrails/test_guardrails.py`)

### Reports: Inferencia de formato por extensión de archivo

#### Añadido

- **`_infer_report_format()`** — Cuando se usa `--report-file` sin `--report`, el formato se infiere automáticamente de la extensión: `.json` → json, `.md`/`.markdown` → markdown, `.html` → github, otro → markdown. (`src/architect/cli.py`)
- **`_write_report_file()`** — Escritura robusta de reportes: crea directorios padres automáticamente, con fallback al directorio actual si falla, y notificación al usuario si no se puede escribir. Reemplaza los 4 `Path.write_text()` directos en `run`, `loop`, `pipeline` y `eval`. (`src/architect/cli.py`)
- **13 tests nuevos** — `TestInferReportFormat` (8 tests: extensiones, case-insensitive, paths con directorios) + `TestWriteReportFile` (5 tests: creación de directorios, fallback, fallo total, sobreescritura). (`tests/test_reports/test_reports.py`)

#### Corregido

- **`--report-file` sin `--report` no generaba reporte** — La lógica de generación estaba condicionada a `if report_format:`, que era `None` cuando no se pasaba `--report`. Ahora se infiere el formato de la extensión del archivo en los 3 puntos de generación: `run`, `loop` y `pipeline`. (`src/architect/cli.py`)
- **`--report-file` con directorio inexistente crasheaba** — `Path.write_text()` no crea directorios padres, causando `FileNotFoundError` con rutas como `reports/ralph-run.json`. Ahora `_write_report_file()` crea los directorios automáticamente. (`src/architect/cli.py`)

### Pipelines: Validación de YAML antes de ejecutar

#### Añadido

- **`PipelineValidationError`** — Excepción dedicada para errores de validación de pipeline YAML. Hereda de `ValueError` para backward compatibility. (`src/architect/features/pipelines.py`)
- **`_validate_steps()`** — Validación completa del YAML antes de ejecutar: `prompt` requerido y no vacío, campos desconocidos rechazados (con hint `task` → "¿quisiste decir `prompt`?"), al menos 1 step, entradas non-dict rechazadas. Recopila todos los errores en un solo mensaje. (`src/architect/features/pipelines.py`)
- **CLI captura `PipelineValidationError`** — Muestra error limpio sin traceback y sale con `EXIT_CONFIG_ERROR` (3). (`src/architect/cli.py`)
- **9 tests nuevos** — `TestPipelineYamlValidation`: `task` rechazado con hint, prompt vacío, prompt missing, no steps, campos desconocidos, errores coleccionados, YAML válido pasa, whitespace-only rechazado, `steps` key missing. (`tests/test_pipelines/test_pipelines.py`)

#### Cambiado

- **`check_file_access()` ahora usa el parámetro `action`** — El método ya recibía `action` pero lo ignoraba. Ahora diferencia entre acciones de lectura (solo `sensitive_files`) y escritura (`protected_files` + `sensitive_files`). Backward compatible: todos los callers existentes pasan acciones de escritura. (`src/architect/core/guardrails.py`)
- **`check_command()` ampliado** — Las redirecciones shell (`>`, `>>`, `| tee`) ahora se verifican contra `protected_files` + `sensitive_files` combinados. (`src/architect/core/guardrails.py`)

#### Tests

- **739 passed**, 9 skipped, 0 failures (687 pre-existentes + 30 guardrails + 13 reports + 9 pipeline validation)
- 31 E2E checks pasando sin cambios

---

## [1.0.1] - 2026-02-26

### Correcciones post-release

#### Corregido

- Correcciones de errores encontrados en tests tras la release v1.0.0
- Correcciones generales de estabilidad
- Traducciones y documentos de LICENCIA y SEGURIDAD

---

## [1.0.0] - 2026-02-24

### Release 1.0.0 — Primera versión estable

Primera release pública de architect CLI. Culminación de 4 fases de desarrollo (Plan V4: A, B, C, D) sobre la base del core v3, resultando en una herramienta CLI completa, robusta y extensible para orquestar agentes de IA sobre código local.

#### Resumen de capacidades

**Core del agente**:
- Loop determinista `while True` con el LLM decidiendo cuándo parar
- 4 agentes por defecto: `build`, `plan`, `resume`, `review` + agentes custom en YAML
- 8 tools locales: `read_file`, `write_file`, `edit_file`, `delete_file`, `list_files`, `search_code`, `grep`, `find_files`, `apply_patch`, `run_command`, `dispatch_subagent`
- Gestión de contexto inteligente: compresión, pruning, enforce_window
- Auto-evaluación (`--self-eval basic|full`) con reintentos automáticos
- Safety nets: max_steps, budget, timeout, context_full — todos con cierre limpio (graceful close)

**Seguridad (Phase A)**:
- Hooks del lifecycle (10 eventos: pre/post tool, pre/post LLM, session, agent, error, budget, context)
- Guardrails deterministas: archivos protegidos, comandos bloqueados, límites de edición, code_rules (warn/block)
- Quality gates post-build con re-ejecución automática si fallan
- Skills ecosystem: `.architect.md`, `.architect/skills/`, instalación desde GitHub
- Memoria procedural: correcciones del usuario persistidas entre sesiones

**Operaciones (Phase B)**:
- Sesiones persistentes con resume (`architect sessions`, `architect resume`)
- Reportes multi-formato: JSON, Markdown, GitHub PR comment
- 10+ flags CI/CD nativos: `--dry-run`, `--report`, `--session`, `--context-git-diff`, `--confirm-mode`, `--exit-code-on-partial`
- Dry-run/preview mode con registro de acciones simuladas

**Orquestación (Phase C)**:
- Ralph Loop: iteración automática hasta que checks pasen (`architect loop`)
- Pipeline Mode: workflows YAML multi-step con variables, condiciones, checkpoints (`architect pipeline`)
- Ejecución paralela en git worktrees aislados (`architect parallel`)
- Checkpoints git con rollback (`architect rollback`, `architect history`)
- Auto-review post-build con contexto limpio

**Extensiones (Phase D)**:
- Sub-agentes delegados: explore, test, review (`dispatch_subagent`)
- Análisis de salud del código: complejidad, duplicados, funciones largas (`--health`)
- Evaluación competitiva multi-modelo con ranking (`architect eval`)
- Trazabilidad OpenTelemetry: session/llm/tool spans (otlp, console, json-file)
- Presets de configuración: python, node-react, ci, paranoid, yolo (`architect init`)

**Infraestructura**:
- 15 comandos CLI: `run`, `loop`, `pipeline`, `parallel`, `parallel-cleanup`, `eval`, `init`, `sessions`, `resume`, `cleanup`, `agents`, `validate-config`, `skill`, `rollback`, `history`
- Control de costes: `CostTracker`, `--budget`, prompt caching, `--show-costs`
- Logging triple pipeline: HUMAN (stderr), técnico (stderr con -v), JSON file (--log-file)
- Proveedores LLM vía LiteLLM: OpenAI, Anthropic, Google, Ollama, proxies
- MCP (Model Context Protocol): tools remotas vía HTTP, auto-discovery

**Calidad**:
- 687 tests unitarios (pytest), 9 skipped, 0 failures
- 31 E2E script checks
- 7 bugs de QA corregidos (BUG-1 a BUG-7)
- Tipado estricto con mypy, formato con black (100 chars), linting con ruff

---

## [0.19.0] - 2026-02-24

### v4 Phase D — Extensiones Avanzadas y QA

Extensiones avanzadas del agente: sub-agentes despachables, análisis de salud del código, evaluación competitiva multi-modelo, trazas OpenTelemetry, presets de configuración, y 7 bugs corregidos del QA exhaustivo.

#### Añadido

**D1 — Sub-Agents / Dispatch**:
- `DispatchSubagentTool` — tool `dispatch_subagent` que delega sub-tareas a agentes con contexto independiente
- Tres tipos de sub-agente: `explore` (solo lectura/búsqueda), `test` (lectura + ejecución de tests), `review` (lectura + análisis)
- `SUBAGENT_MAX_STEPS=15`, `SUBAGENT_SUMMARY_MAX_CHARS=1000` — límites para no consumir contexto/coste
- `register_dispatch_tool()` en `tools/setup.py` — registro con agent_factory callable
- Wiring completo en `cli.py`: `_subagent_factory()` closure que crea AgentLoops frescos para sub-agentes

**D2 — Code Health Delta**:
- `CodeHealthAnalyzer` — analiza métricas de salud del código Python (AST nativo + radon opcional)
- `HealthSnapshot` — files_analyzed, total_functions, avg_complexity, max_complexity, long_functions, duplicate_blocks
- `HealthDelta` — delta entre snapshots con `to_report()` en formato markdown
- `FunctionMetric` — métricas por función (file, name, lines, complexity)
- Detección de duplicación por hashing de bloques (ventana deslizante MD5)
- Flag `--health` en `architect run` — toma snapshot antes/después y muestra delta report
- `HealthConfig` en `AppConfig` — `enabled`, `include_patterns`, `exclude_dirs`

**D3 — Competitive Eval**:
- `CompetitiveEval` — ejecuta misma tarea con múltiples modelos en worktrees aislados
- `CompetitiveConfig` — task, models, checks, agent, max_steps, budget_per_model, timeout_per_model
- `CompetitiveResult` — model, status, steps, cost, duration, checks_passed/total, worktree_path
- `generate_report()` — reporte markdown con tabla comparativa, ranking por score compuesto (checks 40% + status 30% + efficiency 20% + cost 10%)
- Comando `architect eval` — `--models` (requerido), `--check` (repetible), `--report-file`

**D4 — OpenTelemetry Traces**:
- `ArchitectTracer` — emite spans para sesiones, llamadas LLM y tools (GenAI Semantic Conventions)
- `NoopTracer` / `NoopSpan` — pattern para cuando OTel no está instalado
- `create_tracer()` factory — retorna ArchitectTracer o NoopTracer según configuración
- Exporters: `otlp` (gRPC), `console` (stderr), `json-file` (archivo JSON)
- `TelemetryConfig` en `AppConfig` — `enabled`, `exporter`, `endpoint`, `trace_file`
- Wiring completo en `cli.py`: `create_tracer()` + `tracer.start_session()` envuelve ejecución + `tracer.shutdown()`

**D5 — Preset Configs**:
- `PresetManager` — genera `.architect.md` y `config.yaml` desde presets predefinidos
- 5 presets: `python` (ruff/mypy/pytest), `node-react` (eslint/jest), `ci` (yolo headless), `paranoid` (máxima seguridad), `yolo` (sin restricciones)
- `AVAILABLE_PRESETS` dict con metadata (description, tags, files)
- Comando `architect init --preset <name>` con `--overwrite` y `--list-presets`

**Nuevos módulos**:
- `src/architect/tools/dispatch.py` — DispatchSubagentTool
- `src/architect/core/health.py` — CodeHealthAnalyzer
- `src/architect/features/competitive.py` — CompetitiveEval
- `src/architect/telemetry/otel.py` — ArchitectTracer
- `src/architect/config/presets.py` — PresetManager

**Dependencias opcionales** (pyproject.toml):
- `telemetry` — opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp (>=1.20)
- `health` — radon (>=6.0)

**Tests**: 687 pytest (646 pre-existentes + 41 nuevos bugfix tests), 9 skipped, 0 failures. Tests nuevos en:
- `tests/test_dispatch/` (36 tests) — DispatchSubagentTool unit tests
- `tests/test_health/` (28 tests) — CodeHealthAnalyzer unit tests
- `tests/test_competitive/` — CompetitiveEval unit tests
- `tests/test_telemetry/` (16 tests) — ArchitectTracer y NoopTracer unit tests
- `tests/test_presets/` — PresetManager unit tests
- `tests/test_bugfixes/` (41 tests) — validación específica de los 7 bugs corregidos

#### Corregido

- **[CRITICAL] BUG-1: CLI commands `eval` e `init` usaban `@cli.command` en vez de `@main.command`** — Rompía toda la importación del módulo CLI. Fix: cambiado a `@main.command("eval")` y `@main.command("init")`. (`src/architect/cli.py`)
- **[MEDIUM] BUG-2: Versión inconsistente** — `pyproject.toml` en 0.19.0 pero `__init__.py` y `cli.py` en 0.18.0. Fix: actualizado ambos a 0.19.0. (`src/architect/__init__.py`, `src/architect/cli.py`)
- **[HIGH] BUG-3: `code_rules` severity:block no prevenía escrituras** — `check_code_rules` se ejecutaba DESPUÉS de `execute_tool_call`, el archivo ya estaba escrito en disco. Fix: movido el check a ANTES de la ejecución en `_execute_single_tool`; si hay violación block, retorna ToolResult failure sin ejecutar. `record_edit()` movido a `execute_tool_call` solo tras éxito. (`src/architect/core/loop.py`, `src/architect/execution/engine.py`)
- **[MEDIUM] BUG-4: `dispatch_subagent` tool no registrada en CLI run** — `register_dispatch_tool()` existía pero no se llamaba. Fix: añadido wiring en `cli.py` con closure `_subagent_factory()` que crea AgentLoops frescos. (`src/architect/cli.py`)
- **[MEDIUM] BUG-5: `TelemetryConfig` parseada pero `create_tracer()` nunca llamado** — La config existía en schema pero no se conectaba. Fix: añadido `create_tracer()` desde config, `tracer.start_session()` envolviendo ejecución, y `tracer.shutdown()` al finalizar. (`src/architect/cli.py`)
- **[MEDIUM] BUG-6: `HealthConfig` parseada pero `CodeHealthAnalyzer` nunca invocado** — Config en schema sin wiring. Fix: añadido flag `--health` en run command, `CodeHealthAnalyzer` con snapshots before/after y delta report. (`src/architect/cli.py`)
- **[MEDIUM] BUG-7: Parallel workers no propagaban `--config` ni `--api-base`** — `_run_worker_process` no incluía estos flags en el subprocess. Fix: añadidos `config_path` y `api_base` a `ParallelConfig` y `_run_worker_process`, y `--config`/`--api-base` en CLI parallel. (`src/architect/features/parallel.py`, `src/architect/cli.py`)

---

## [0.18.0] - 2026-02-24

### v4 Phase C — Iteración, Pipelines y Revisión

Orquestación avanzada de agentes: loops iterativos con checks automáticos, pipelines YAML multi-step, ejecución paralela en worktrees git, checkpoints con rollback, y auto-review post-build con contexto limpio.

#### Añadido

**C1 — Ralph Loop (Iteración Automática)**:
- `RalphConfig` dataclass — configuración completa: task, checks, spec_file, max_iterations (25), max_cost, max_time, agent, model, use_worktree, completion_tag
- `RalphLoop.run()` — loop iterativo que ejecuta un agente hasta que todos los checks shell pasen o se agoten límites (iteraciones, coste, tiempo)
- Contexto limpio por iteración — cada iteración recibe solo: spec original, diff acumulado, errores de la anterior, y progress.md auto-generado
- `_run_checks()` — ejecuta checks como subprocesos shell (timeout 30s, output truncado 2000 chars)
- `_update_progress()` — genera `.architect/progress.md` con historial de iteraciones
- Worktree support — `_create_worktree()` / `_cleanup_worktree()` para aislamiento git
- `RalphLoopResult` con success flag, iterations list, total_cost, worktree_path

**C2 — Parallel Runs (Ejecución Paralela en Worktrees)**:
- `ParallelConfig` dataclass — tasks, workers (3), models, agent, budget_per_worker, timeout_per_worker
- `ParallelRunner.run()` → list[WorkerResult] — fan-out con ProcessPoolExecutor en git worktrees aislados
- `WorkerResult` dataclass — worker_id, branch, model, status, steps, cost, duration, files_modified
- Round-robin de modelos cuando hay menos models que workers
- Cleanup automático de worktrees (`WORKTREE_PREFIX = ".architect-parallel"`)

**C3 — Pipeline Mode (Workflows YAML Multi-Step)**:
- `PipelineConfig` con steps secuenciales, cada uno con agente/prompt/modelo independiente
- Variable substitution con `{{variable_name}}` en prompts de steps
- `condition` — expresión evaluada; step skipped si False
- `output_var` — captura output del agente como variable para steps siguientes
- `checks` — comandos shell post-step con resultado en `checks_passed`
- `checkpoint: true` — crea git checkpoint automático al completar el step
- `from_step` — resume pipeline desde un step específico
- `dry_run` — muestra plan sin ejecutar agentes

**C4 — Checkpoints & Rollback**:
- `CheckpointManager` — gestiona git commits con prefijo `architect:checkpoint`
- `create(step, message)` — stage all + commit con prefijo
- `list_checkpoints()` — parsea `git log --grep` para listar checkpoints
- `rollback(step=, commit=)` — `git reset --hard` al checkpoint especificado
- `get_latest()`, `has_changes_since(commit_hash)`
- Integrado con Pipeline (checkpoint per step) y Ralph Loop

**C5 — Auto-Review (Revisión Post-Build)**:
- `AutoReviewer` — agente reviewer con contexto LIMPIO (solo diff + tarea, sin historial del builder)
- `review_changes(task, git_diff)` → `ReviewResult` (has_issues, review_text, cost)
- `build_fix_prompt(review_result)` — genera prompt para que el builder corrija issues
- `REVIEW_SYSTEM_PROMPT` — busca bugs, problemas de seguridad, violaciones de convenciones, mejoras, tests faltantes
- Graceful error handling — excepciones de LLM retornan error controlado

**Nuevos comandos CLI**:
- `architect loop` — Ralph Loop con `--check` (múltiple), `--spec`, `--max-iterations`, `--max-cost`, `--max-time`, `--worktree`, `--agent`, `--model`
- `architect parallel` — ejecución paralela con `--task` (múltiple), `--workers`, `--models`, `--agent`, `--budget-per-worker`
- `architect parallel-cleanup` — limpieza de worktrees de ejecución paralela
- `architect pipeline` — workflow YAML con `--var` (múltiple), `--from-step`, `--dry-run`, `--config`

**Nuevo módulo**: `src/architect/features/` ampliado con ralph.py, pipelines.py, parallel.py, checkpoints.py. `src/architect/agents/reviewer.py` nuevo.

**Tests**: 311 pytest tests (test_ralph: 90, test_pipelines: 83, test_checkpoints: 48, test_reviewer: 47, test_parallel: 43) + `scripts/test_phase_c_e2e.py` con 31 tests E2E cubriendo C1-C5 + Guardrails. Total proyecto: 504 pytest + 31 E2E.

#### Corregido

- **[MEDIUM] Ralph Loop worktree agent isolation broken** — Agent factory creaba agentes con workspace original en vez del worktree. Fix: `workspace_root` pasado desde `_run_single_iteration` al factory; cli.py factory acepta y usa `workspace_root` kwarg. (`src/architect/features/ralph.py`, `src/architect/cli.py`)
- **[MEDIUM] Guardrails no bloqueaban `apply_patch` + factories sin guardrails** — `apply_patch` no estaba en la tupla de check de file access en ExecutionEngine. Las factories de `loop_cmd` y `pipeline_cmd` no creaban GuardrailsEngine. Fix: añadido `apply_patch` a la tupla + GuardrailsEngine en ambos factories. (`src/architect/execution/engine.py`, `src/architect/cli.py`)
- **[LOW] `test_integration.py` stale `PostEditHooks` import** — Sección 8 reescrita con `HookExecutor` API (v4-A1). Sección 9 con paths dinámicos via `tempfile.mkdtemp()`. (`scripts/test_integration.py`)

---

## [0.17.0] - 2026-02-23

### v4 Phase B — Persistencia y Reporting

Implementación completa de los 4 componentes de Phase B: sesiones persistentes con resume, reportes multi-formato para CI/CD, flags nativos de línea de comandos y modo dry-run/preview.

#### Añadido

**B1 — Session Resume y Persistencia**:
- `SessionState` dataclass (13 campos) con serialización JSON completa (`to_dict()` / `from_dict()`)
- `SessionManager` — save, load, list_sessions, cleanup, delete. Persistencia en `.architect/sessions/`
- Truncación automática de mensajes (>50 → últimos 30, marca `truncated=True`)
- `generate_session_id()` — formato `YYYYMMDD-HHMMSS-hexhex` con unicidad garantizada
- Graceful handling de JSON corrupto, soporte UTF-8 completo

**B2 — Reportes de Ejecución**:
- `ExecutionReport` dataclass (13 campos) — datos completos de ejecución
- `ReportGenerator` — tres formatos de salida:
  - `to_json()` — JSON parseable por CI/CD
  - `to_markdown()` — tablas, secciones de archivos, quality gates, errores, timeline
  - `to_github_pr_comment()` — optimizado con `<details>` collapsible
- `collect_git_diff(workspace_root)` — ejecuta `git diff HEAD`, trunca a 50KB
- Status icons: success→"OK", partial→"WARN", failed→"FAIL"

**B3 — CI/CD Native Flags**:
- Flags de `architect run`: `--json`, `--dry-run`, `--report [json|markdown|github]`, `--report-file PATH`, `--session SESSION_ID`, `--confirm-mode [yolo|confirm-sensitive|confirm-all]`, `--context-git-diff REF`, `--exit-code-on-partial INT`, `--budget FLOAT`, `--timeout INT`
- Nuevos comandos CLI: `architect sessions` (lista), `architect cleanup [--older-than N]` (limpieza), `architect resume SESSION_ID` (reanudación)
- Exit codes estandarizados: SUCCESS(0), FAILED(1), PARTIAL(2), CONFIG_ERROR(3), AUTH_ERROR(4), TIMEOUT(5), INTERRUPTED(130)

**B4 — Dry Run / Preview Mode**:
- `DryRunTracker` — registra acciones de herramientas de escritura sin ejecutarlas
- `PlannedAction` dataclass (step, tool, summary)
- `WRITE_TOOLS` / `READ_TOOLS` frozensets (sin intersección)
- `_summarize_action()` — resúmenes inteligentes por tipo de tool (path, command con truncación, fallback)
- `get_plan_summary()` — plan formateado en Markdown

**Nuevo módulo**: `src/architect/features/` (sessions.py, report.py, dryrun.py, __init__.py)

**Tests**: 65 pytest tests (test_sessions: 22, test_reports: 20, test_dryrun: 23) + `scripts/test_phase_b.py` con 35 tests y 104 checks de integración cubriendo B1-B4 y tests combinados

#### Corregido

- **[MEDIUM] Guardrails bypass via shell redirection** — Comandos con `>`, `>>`, `| tee` podían escribir en archivos protegidos. Añadido `_extract_redirect_targets()` con detección de 5 patrones de redirección + 13 tests nuevos. (`src/architect/core/guardrails.py`)
- **[LOW] Timeline duration -0.0** — Duración de steps con valor negativo por imprecisión float. Corregido con `max(0, duration)`.
- **[LOW] Versión hardcoded en test scripts** — `test_phase12.py` y `test_phase11.py` usaban "0.16.1" literal. Cambiado a versión dinámica desde `architect.__version__`. (`scripts/test_phase12.py`, `scripts/test_phase11.py`)

---

## [0.16.2] - 2026-02-23

### QA Round 2 — Testing Real End-to-End y Bugfixes Críticos

QA exhaustivo con ejecuciones reales contra LiteLLM proxy y servidores MCP. 5 bugs encontrados y corregidos. 12 tests de integración ejecutados.

#### Corregido

- **[CRITICAL] `--show-costs` no mostraba costes en modo streaming** — `completion_stream()` no pasaba `stream_options={"include_usage": True}` a LiteLLM. Sin esto, las APIs OpenAI-compatible no devuelven datos de uso de tokens en streaming, por lo que `response.usage=None` y el cost tracker nunca registraba datos. Añadido `stream_options` + fallback `_estimate_streaming_usage()` que usa `litellm.token_counter()` cuando el provider no devuelve usage. (`src/architect/llm/adapter.py`)

- **[CRITICAL] `--mode yolo` seguía pidiendo confirmación para comandos** — `_should_confirm_command()` devolvía `True` para comandos "dangerous" incluso en yolo. "Dangerous" solo significa "no reconocido en listas safe/dev", no realmente peligroso (la blocklist ya bloquea los peligrosos). Ahora yolo nunca pide confirmación, alineado con la documentación. (`src/architect/execution/engine.py`)

- **[CRITICAL] MCP tools descubiertas pero no expuestas al LLM** — Los agentes con `allowed_tools` explícito (como build) filtraban las MCP tools al construir los schemas para el LLM. Las tools se registraban en el ToolRegistry pero nunca se enviaban al modelo. Ahora se inyectan los nombres de MCP tools en `allowed_tools` tras la resolución del agente. (`src/architect/cli.py`)

- **[MEDIUM] `--timeout` CLI sobreescribía `llm.timeout` per-request** — `apply_cli_overrides()` mapeaba el flag `--timeout` (timeout total de sesión) también a `llm.timeout` (timeout per-request). Si pasabas `--timeout 10` para limitar la sesión, también limitabas cada llamada individual al LLM a 10s. Separados los dos conceptos. (`src/architect/config/loader.py`)

- **[MEDIUM] `get_schemas()` crasheaba si una tool de `allowed_tools` no estaba registrada** — `filter_by_names()` lanzaba `ToolNotFoundError` si un nombre no existía en el registry. Esto crasheaba con `--no-commands` (run_command no registrada pero en `allowed_tools` del build agent) o si un servidor MCP caía. Ahora hace skip defensivo. (`src/architect/tools/registry.py`)

#### Modificado

- `scripts/test_config_loader.py` — test de timeout actualizado para reflejar la separación de `--timeout` CLI vs `llm.timeout`
- Documentación actualizada en `docs/` para reflejar el comportamiento real post-fixes

---

## [0.16.1] - 2026-02-22

### QA Phase A — Corrección de Bugs y Alineación de Tests

QA exhaustivo de 228 verificaciones sobre toda la base de código. 5 bugs encontrados y corregidos. 24 scripts legacy actualizados.

#### Corregido

- **[CRITICAL] `NameError: ToolResult`** en `core/loop.py:596` — `isinstance(pre_result, ToolResult)` sin import. Añadido import local de `ToolResult` desde `tools.base`.
- **[MEDIUM] `CostTracker.total` inexistente** en `core/loop.py:317,359` — el atributo correcto es `total_cost_usd`. Renombrado.
- **[MINOR] YAML `off` → `False`** en `EvaluationConfig.mode` — YAML 1.1 parsea `off` sin comillas como bool `False`. Añadido `@field_validator("mode", mode="before")` que convierte `False → "off"`.
- **[MINOR] Pydantic `schema` field shadowing** en `mcp/adapter.py` — tools MCP con campo "schema" causan `UserWarning` por shadowing de `BaseModel.schema`. Añadida detección de nombres reservados + alias (`schema_ = Field(..., alias="schema")`) con `populate_by_name=True`.

#### Modificado

- `scripts/test_phase{8-12}.py` — versión actualizada a `0.16.0`
- `scripts/test_phase11.py` — añadidos mocks para v4-A1/A2 (`check_guardrails`, `run_pre_tool_hooks`, `check_code_rules`, `run_post_tool_hooks`, `dry_run`)
- `scripts/test_v3_m1.py` — añadidos mocks de guardrails/hooks para test de tool_calls
- `scripts/test_v3_m4.py` — reescritura completa para API v4-A1 (HookExecutor, HookEvent, HooksRegistry, HookDecision, HookResult); 31 tests
- `scripts/test_parallel_execution.py` — añadidos mocks v4 a `_make_loop()` + renombrado `run_post_edit_hooks` → `run_post_tool_hooks`

---

## [0.16.0] - 2026-02-22

### v4 Phase A — Fundamentos de Extensibilidad

Implementación completa de los 4 pilares de extensibilidad del Plan V4: hooks completos, guardrails, skills y memoria procedural.

#### Añadido

**A1 — Sistema de Hooks Completo**:
- `HookExecutor` con 10 eventos del lifecycle (pre/post_tool_use, pre/post_llm_call, session_start/end, on_error, budget_warning, context_compress, agent_complete)
- Protocolo de exit codes: 0=ALLOW, 2=BLOCK, otro=error(warn)
- Soporte para modificación de input (MODIFY) y contexto adicional via JSON stdout
- Env vars injection (ARCHITECT_*) y stdin JSON para hooks
- Hooks async (daemon threads) para tareas de background
- Matcher regex y file_patterns para filtrado granular
- Backward compat con PostEditHooks de v3-M4

**A2 — Guardrails de Primera Clase**:
- `GuardrailsEngine` — capa de seguridad determinista evaluada ANTES que hooks
- Protected files (fnmatch), blocked commands (regex), edit limits (files/lines)
- Code rules: regex scan de contenido escrito (severity: warn/block)
- Quality gates: comandos que se ejecutan cuando el agente declara completado
- Quality gates required: si fallan, el agente recibe feedback y sigue trabajando

**A3 — Skills Ecosystem (.architect.md)**:
- `SkillsLoader`: carga .architect.md / AGENTS.md / CLAUDE.md como contexto de proyecto
- Descubrimiento de skills en .architect/skills/ y .architect/installed-skills/
- SKILL.md con frontmatter YAML (name, description, globs)
- Filtrado por glob: skills se activan segun archivos en juego
- `SkillInstaller`: install desde GitHub (sparse checkout), create, list, uninstall
- CLI: `architect skill install|create|list|remove`
- Inyeccion automatica en system prompt del agente

**A4 — Memoria Procedural**:
- `ProceduralMemory`: deteccion de correcciones del usuario (6 patrones en español)
- Persistencia en .architect/memory.md con formato `- [YYYY-MM-DD] Tipo: contenido`
- Deduplicacion de entradas
- Inyeccion automatica en system prompt
- `analyze_session_learnings()`: extraccion post-sesion de correcciones

#### Archivos nuevos
- `src/architect/core/guardrails.py`
- `src/architect/skills/__init__.py`
- `src/architect/skills/loader.py`
- `src/architect/skills/installer.py`
- `src/architect/skills/memory.py`
- `tests/test_hooks/` (29 tests)
- `tests/test_guardrails/` (29 tests)
- `tests/test_skills/` (29 tests)
- `tests/test_memory/` (29 tests)

#### Modificados
- `src/architect/core/hooks.py` — reescritura completa (HookExecutor, HooksRegistry, HookEvent)
- `src/architect/config/schema.py` — HookItemConfig, HooksConfig, GuardrailsConfig, QualityGateConfig, CodeRuleConfig, SkillsConfig, MemoryConfig
- `src/architect/execution/engine.py` — hook_executor, guardrails, check_guardrails(), check_code_rules()
- `src/architect/core/loop.py` — hooks lifecycle, guardrails, skills_loader, memory
- `src/architect/cli.py` — HookExecutor, GuardrailsEngine, SkillsLoader, ProceduralMemory, `architect skill` commands
- `src/architect/core/__init__.py` — exports actualizados

---

## [0.15.3] - 2026-02-21

### Fix — Pipeline structlog sin `--log-file` no mostraba logs HUMAN

El logging HUMAN (trazabilidad del agente con iconos) no aparecía al ejecutar `architect run`
sin la opción `--log-file`. La causa raíz era que la configuración de structlog tenía dos caminos:
- **Con `--log-file`**: usaba `wrap_for_formatter` → eventos fluían por stdlib handlers → HumanLogHandler funcionaba.
- **Sin `--log-file`**: usaba `ConsoleRenderer` directamente → eventos se renderizaban a texto plano
  antes de llegar a los handlers stdlib → HumanLogHandler recibía strings pre-renderizados y no podía
  extraer el nombre del evento para formatearlo.

#### Modificado

**`src/architect/logging/setup.py`**:
- Siempre usa `ProcessorFormatter.wrap_for_formatter` como procesador final de structlog,
  independientemente de si hay `--log-file` o no.
- El `console_handler` siempre tiene un `ProcessorFormatter` con `ConsoleRenderer`.
- Eliminado el camino condicional que ponía `ConsoleRenderer` directamente en la cadena de procesadores.

**`src/architect/logging/human.py`** — `HumanLogHandler.emit()`:
- Extrae el event dict de `record.msg` (dict puesto por `wrap_for_formatter`) en lugar de
  buscar atributos sueltos en el record.
- Separados los conjuntos de campos a filtrar: `_STRUCTLOG_META` (para event dict de structlog)
  vs `_RECORD_FIELDS` (para fallback con atributos de LogRecord).
- Corregido bug donde `"args"` (atributo estándar de LogRecord) se filtraba del event dict,
  impidiendo que `_summarize_args()` recibiera los argumentos de las tools.

---

## [0.15.2] - 2026-02-21

### Mejora — HumanFormatter con iconos según plan v3-M5

Alineación completa del formato de logs HUMAN con la especificación visual del `plan-v3-core.md`.

#### Modificado

**`src/architect/logging/human.py`** — HumanFormatter con iconos y eventos nuevos:

- `agent.llm.call` → `🔄 Paso N → Llamada al LLM (M mensajes)` (antes: sin emoji)
- `agent.llm.response` → **Nuevo evento**: `✓ LLM respondió con N tool calls` / `✓ LLM respondió con texto final`
- `agent.complete` → `✅ Agente completado (N pasos)` con razón y coste opcional (antes: `✓ Completado`)
- `agent.tool_call.execute` → `🔧 tool → summary` para local, `🌐 tool → summary (MCP: server)` para MCP (antes: sin iconos ni distinción MCP)
- `agent.tool_call.complete` → `✓ OK` / `✗ ERROR: ...` (antes: sin iconos ✓/✗)
- `agent.hook.complete` → `🔍 Hook nombre: ✓/⚠️ detalle` individual por hook (antes: `[hooks ejecutados]` genérico)
- `safety.*` → `⚠️` (emoji completo, antes: `⚠` sin variation selector)
- `agent.llm_error` → `❌ Error del LLM: ...` (antes: `✗`)
- `agent.closing` → `🔄 Cerrando (...)` (antes: `→`)
- `context.*` → `📦` para compresión y ventana (antes: texto plano entre corchetes)

**`src/architect/logging/human.py`** — HumanLog ampliado:

- Nuevo método `llm_response(tool_calls)` — emite `agent.llm.response`
- `tool_call()` acepta `is_mcp` y `mcp_server` para distinción visual MCP
- `hook_complete()` acepta `hook`, `success`, `detail` para hooks individuales
- `agent_done()` acepta `cost` opcional para mostrar coste en completado

**`src/architect/core/loop.py`** — Emisión de nuevos eventos:

- Emite `hlog.llm_response()` tras cada respuesta del LLM (con y sin tool calls)
- Detecta tools MCP (`startswith("mcp_")`) y pasa `is_mcp`/`mcp_server` a `hlog.tool_call()`
- Pasa `hook="post-edit"` y `success=True` a `hlog.hook_complete()`
- Incluye `cost_str` de `CostTracker.format_summary_line()` en `hlog.agent_done()`

**`scripts/test_v3_m5.py`** — Tests actualizados (41 → 49 tests):

- Tests de iconos: 🔄, 🔧, 🌐, ✅, ⚠️, ❌, 📦, ⚡, 🔍, ✓, ✗
- Tests de `agent.llm.response` (texto final y tool calls)
- Tests de `agent.complete` con coste
- Tests de MCP tool distinction (`is_mcp=True, mcp_server="docs"`)
- Tests de hooks individuales (`hook="python-lint"`)
- Tests de `agent_done(cost=...)` en HumanLog

---

## [0.15.1] - 2026-02-21

### Correcciones — Alineación del Test Suite con v3-core

#### Modificado

**`scripts/test_phase3.py`**:
- Añadida nota de deprecación en `test_mixed_mode()`: `MixedModeRunner` es legacy a partir de v3-M3. El agente `build` planifica internamente; la CLI ya no usa `MixedModeRunner` como modo por defecto.

**`scripts/test_phase5.py`**:
- Añadida nota en docstring indicando que las pruebas de los componentes v3-M5 (nivel `HUMAN`, `HumanFormatter`, `HumanLogHandler`, 3 pipelines) están en `scripts/test_v3_m5.py`.

**`scripts/test_phase6.py`**:
- Añadido `stop_reason` a `required_fields` en `test_json_output_format()`: en v3, `AgentState.to_output_dict()` siempre incluye `stop_reason` (valor `None` si terminó limpiamente).
- Separada la verificación de `model` (campo condicional, solo presente si `state.model` está seteado).

**`scripts/test_phase8.py`**:
- Actualizado `EXPECTED_VERSION = "0.8.0"` → `"0.15.0"`.
- Añadidos 7 módulos v3 al `test_imports()`: `architect.core.hooks`, `architect.core.evaluator`, `architect.logging.levels`, `architect.logging.human`, `architect.indexer.tree`, `architect.costs`, `architect.llm.cache`.

**`scripts/test_phase9.py`**:
- Actualizado `EXPECTED_VERSION = "0.9.0"` → `"0.15.0"`.

**`scripts/test_phase10.py`**:
- Actualizada versión `"0.10.0"` → `"0.15.0"` (2 ocurrencias).

**`scripts/test_phase11.py`**:
- Actualizada versión `"0.11.0"` → `"0.15.0"` (2 ocurrencias).
- Los métodos de la API original (`truncate_tool_result`, `enforce_window`, `maybe_compress`) siguen presentes en `ContextManager` junto con el nuevo `manage()` unificado de v3-M2.

**`scripts/test_phase12.py`**:
- Actualizada versión `"0.12.0"` → `"0.15.0"` (2 ocurrencias).

---

## [0.15.0] - 2026-02-21

### v3-core — Rediseño del Núcleo del Agente ✅

#### Agregado

**`StopReason`** (`src/architect/core/state.py`) — enum de 7 razones de parada:

- `LLM_DONE`, `MAX_STEPS`, `BUDGET_EXCEEDED`, `CONTEXT_FULL`, `TIMEOUT`, `USER_INTERRUPT`, `LLM_ERROR`
- Campo `stop_reason: StopReason | None` en `AgentState`
- Incluido en `to_output_dict()` → disponible en output JSON

**AgentLoop rediseñado** (`src/architect/core/loop.py`) — `while True` con safety nets y graceful close:

- `_check_safety_nets(state, step)` → `StopReason | None`: comprueba señales antes de cada LLM call
- `_graceful_close(state, reason, tools_schema)`: última LLM call sin tools → el agente resume su trabajo
- `_CLOSE_INSTRUCTIONS`: mensajes de cierre específicos por motivo de parada
- `timeout: int | None`: watchdog de tiempo total transcurrido (antes era SIGALRM por step)
- Hooks integrados: llama `engine.run_post_edit_hooks()` tras tools de edición

**`ContextManager.manage()` + `is_critically_full()`** (`src/architect/core/context.py`):

- `manage(messages, llm=None)` → `list[dict]`: pipeline unificado compress + enforce_window
- `is_critically_full(messages)` → `bool`: True si >95% del límite máximo

**`PostEditHooks`** (`src/architect/core/hooks.py`) — verificación automática tras editar:

- `HookRunResult` dataclass: `hook_name`, `file_path`, `success`, `output`, `exit_code`
- `PostEditHooks`: `run_for_tool(tool_name, args)`, `run_for_file(file_path)`, `_matches()`, `_run_hook()`
- Placeholder `{file}` en comandos de hook sustituido por el path del archivo editado
- Output del hook añadido al resultado de la tool para retroalimentación al LLM

**`HookConfig` + `HooksConfig`** (`src/architect/config/schema.py`):

- `HookConfig`: `name`, `command`, `file_patterns: list[str]`, `timeout: int = 15`, `enabled: bool = True`
- `HooksConfig`: `post_edit: list[HookConfig] = []`
- Campo `hooks: HooksConfig` añadido a `AppConfig`

**Nivel de logging HUMAN (25)** (`src/architect/logging/`):

- `HUMAN = 25` en `logging/levels.py` — entre INFO (20) y WARNING (30)
- `HumanFormatter.format_event(event, **kw)`: match/case para ~12 eventos del agente con iconos y formato
- `HumanLogHandler(logging.Handler)`: filtra `record.levelno == HUMAN`, escribe a stderr
- `HumanLog`: helper tipado con `llm_call()`, `tool_call()`, `tool_result()`, `hook_complete()`, `agent_done()`, `safety_net()`, `closing()`, `loop_complete()`

**`_summarize_args(tool_name, args)`** (`src/architect/logging/human.py`) — M6:

- Resumen human-readable específico para cada tool: `read_file` → path, `write_file` → path + líneas, `edit_file` → path + (old→new líneas), `apply_patch` → path + (+X -Y), `run_command` → comando truncado, etc.

**Tres pipelines de logging independientes** (`src/architect/logging/setup.py`):

- Pipeline 1: Archivo JSON (DEBUG+, si `logging.file` configurado)
- Pipeline 2: `HumanLogHandler` (stderr, solo nivel HUMAN, excluido en --quiet/--json)
- Pipeline 3: Console técnico (stderr, excluye HUMAN, controlado por -v)
- Sin `-v`: el usuario ve solo logs HUMAN — trazabilidad limpia sin ruido técnico

#### Modificado

**`BUILD_PROMPT`** (`src/architect/agents/prompts.py`):

- Workflow integrado de planificación: ANALIZAR → PLANIFICAR → EJECUTAR → VERIFICAR → CORREGIR
- El agente `build` planifica internamente sin necesitar un agente `plan` previo

**`DEFAULT_AGENTS`** (`src/architect/agents/registry.py`):

- `plan`: `confirm_mode` "confirm-all" → "yolo" (solo lectura), `max_steps` 10 → 20
- `build`: `max_steps` 25 → 50 (ahora es watchdog, no driver del loop)
- `resume`: `max_steps` 10 → 15
- `review`: `max_steps` 15 → 20

**`ExecutionEngine`** (`src/architect/execution/engine.py`):

- Nuevo parámetro `hooks: PostEditHooks | None = None`
- Nuevo método `run_post_edit_hooks(tool_name, args) -> str | None`

**`LoggingConfig`** (`src/architect/config/schema.py`):

- `level`: añadido "human" como valor válido, default cambiado a "human"

**`cli.py`** — reescritura completa:

- `agent_name = kwargs.get("agent") or "build"` — build es el agente por defecto
- Single code path — eliminado el branching `use_mixed_mode`
- `_print_banner(agent_name, model, quiet)` y `_print_result_separator(quiet)` como funciones
- `--timeout` es ahora watchdog de tiempo total, no SIGALRM por step
- `--log-level` acepta "human" como opción

**`logging/__init__.py`**:

- Exports: `HUMAN`, `HumanLog`, `HumanLogHandler`, `_summarize_args`

**`config.example.yaml`** — corregido y actualizado:

- `agents: {}` — corregido YAML null que causaba error de validación
- `evaluation.mode: "off"` — corregido YAML boolean (off → False en YAML 1.1)
- Sección `logging` actualizada con nivel "human" y descripción de los tres pipelines
- Sección `hooks:` añadida con documentación y ejemplos (ruff, mypy, eslint)
- Versión actualizada a 0.15.0

#### Versión

- `src/architect/__init__.py`: `__version__ = "0.15.0"`
- `pyproject.toml`: `version = "0.15.0"`
- `src/architect/cli.py`: `_VERSION = "0.15.0"`

---

## [0.14.0] - 2026-02-21

### Fase 14 - Cost Tracking + Prompt Caching ✅

#### Agregado

**`CostTracker`** (`src/architect/costs/tracker.py`) — seguimiento de costes de llamadas LLM:

- `record(step, model, usage, source)` — registra coste con desglose por tokens cacheados vs. normales
- `BudgetExceededError` — detiene el agente si se supera el límite configurado
- Warn threshold — log warning cuando se alcanza `warn_at_usd` (sin detener)
- `summary()` → dict con totales y desglose `by_source` (agent/eval/summary)
- `format_summary_line()` → `"$0.0042 (12,450 in / 3,200 out / 500 cached)"`

**`PriceLoader`** (`src/architect/costs/prices.py`) — resolución de precios por modelo:

- Match exacto → match por prefijo → fallback genérico (3.0/15.0 por millón)
- Precios embebidos en `costs/default_prices.json`: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini`, `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5`, `gemini-2.0-flash`, `deepseek-chat`, `ollama` (coste 0)
- `cached_input_per_million` para todos los modelos que soportan prompt caching

**`LocalLLMCache`** (`src/architect/llm/cache.py`) — cache determinista de respuestas LLM:

- Clave: SHA-256[:24] de JSON canónico `(messages, tools)` — determinista independientemente del orden de claves
- Almacenamiento: un archivo `.json` por entrada en directorio configurable (`~/.architect/cache/`)
- TTL simple basado en `mtime` del archivo
- Fallos silenciosos: nunca rompe el flujo del adapter
- `clear()` retorna número de entradas eliminadas, `stats()` para debugging

**Prompt caching** (`LLMAdapter._prepare_messages_with_caching()`):

- Convierte `system.content: str` → lista de bloques con `cache_control: {"type":"ephemeral"}`
- Soporte para Anthropic prompt caching (ahorro 50-90% en tokens repetidos)
- Completamente transparente en proveedores sin soporte (campo ignorado)
- Aplica tanto en `completion()` como en `completion_stream()`
- Controlado por `LLMConfig.prompt_caching: bool = False`

**Extracción de `cache_read_input_tokens`** en `LLMAdapter._normalize_response()`:

- Captura `cache_read_input_tokens` de `response.usage` (Anthropic)
- Disponible en `LLMResponse.usage` y propagado al `CostTracker`

**`CostsConfig`** y **`LLMCacheConfig`** (`src/architect/config/schema.py`):

- `CostsConfig`: `enabled`, `prices_file`, `budget_usd`, `warn_at_usd`
- `LLMCacheConfig`: `enabled`, `dir`, `ttl_hours` (ge=1, le=8760)
- `LLMConfig.prompt_caching: bool = False`

**5 nuevos flags CLI** (`src/architect/cli.py`):

- `--budget FLOAT` — límite de gasto en USD (override de `costs.budget_usd`)
- `--show-costs` — mostrar resumen de costes al terminar
- `--cache` — activar cache local de LLM (override de `llm_cache.enabled`)
- `--no-cache` — desactivar cache aunque esté en config
- `--cache-clear` — limpiar cache antes de ejecutar

**Output JSON** incluye `costs` automáticamente cuando hay datos.

#### Modificado

- **`llm/adapter.py`**: `__init__` acepta `local_cache: LocalLLMCache | None`; `completion()` consulta y guarda en cache; `_normalize_response()` captura `cache_read_input_tokens`; `completion_stream()` aplica prompt caching y captura `cache_read_input_tokens`
- **`llm/__init__.py`**: exportar `LocalLLMCache`
- **`core/state.py`**: campo `cost_tracker: CostTracker | None`; `to_output_dict()` incluye `"costs"` cuando hay datos
- **`core/loop.py`**: parámetro `cost_tracker`; `record()` tras cada llamada LLM; manejo de `BudgetExceededError`
- **`core/mixed_mode.py`**: parámetro `cost_tracker` propagado a ambos `AgentLoop`
- **`config.example.yaml`**: secciones `costs:`, `llm_cache:`, `llm.prompt_caching`
- **Versión**: bump a `0.14.0` en `__init__.py`, `pyproject.toml`, `cli.py` (2 sitios)

---

## [0.13.0] - 2026-02-21

### Fase 13 - run_command — Ejecución de Código ✅

#### Agregado

**`RunCommandTool`** (`src/architect/tools/commands.py`) — nueva tool para ejecutar comandos del sistema:

- **Cuatro capas de seguridad**:
  1. **Blocklist** (`BLOCKED_PATTERNS`): 9+ regexes que bloquean comandos destructivos siempre (`rm -rf /`, `sudo`, `curl|bash`, `dd of=/dev/`, `mkfs`, fork bomb, etc.)
  2. **Clasificación dinámica** (`classify_sensitivity()`): retorna `'safe' | 'dev' | 'dangerous'` basado en `SAFE_COMMANDS` (ls, cat, git status, grep, etc.) y `DEV_PREFIXES` (pytest, mypy, ruff, make, cargo, etc.)
  3. **Timeouts + output limit**: `subprocess.run(..., timeout=N, stdin=subprocess.DEVNULL)` — headless; output truncado a `max_output_lines` preservando inicio y final
  4. **Directory sandboxing**: `cwd` validado con `validate_path()` — siempre dentro del workspace

- **`allowed_only` mode**: si `True`, comandos `dangerous` rechazados en `execute()` sin confirmación

- **Tabla de sensibilidad dinámica** implementada en `ExecutionEngine._should_confirm_command()`:
  - `safe` + yolo/confirm-sensitive → sin confirmación
  - `dev` + confirm-sensitive → confirmación
  - `dangerous` + yolo → confirmación (único caso en yolo que confirma)
  - Todas + confirm-all → confirmación

**`CommandsConfig`** (`src/architect/config/schema.py`) — nueva sección de configuración:
- `enabled: bool = True` — registrar o no la tool (desactivar con `--no-commands`)
- `default_timeout: int = 30` — timeout por defecto (1-600s)
- `max_output_lines: int = 200` — límite de líneas de output (10-5000)
- `blocked_patterns: list[str] = []` — regexes extra a bloquear
- `safe_commands: list[str] = []` — comandos extra considerados seguros
- `allowed_only: bool = False` — modo whitelist estricto

**Opciones `--allow-commands` / `--no-commands`** en CLI (`src/architect/cli.py`):
- `--allow-commands` — habilitar `run_command` (override de `commands.enabled`)
- `--no-commands` — deshabilitar `run_command` completamente (override de `commands.enabled`)

**Sección `commands:` en `config.example.yaml`** con documentación completa de todas las opciones.

#### Modificado

- **`tools/setup.py`**: nueva función `register_command_tools(registry, workspace_config, commands_config)`, `register_all_tools()` acepta ahora `commands_config` opcional
- **`tools/__init__.py`**: exports de `RunCommandTool`, `RunCommandArgs`, `register_command_tools`
- **`execution/engine.py`**: nuevo método `_should_confirm_command(command, tool)` + override de confirmación para `run_command` en `execute_tool_call()`
- **`agents/registry.py`**: `run_command` añadido a `allowed_tools` del agente `build`
- **`agents/prompts.py`**: sección `run_command` en `BUILD_PROMPT` con tabla de uso y flujo editar→verificar→corregir
- **Versión**: bump a `0.13.0` en `__init__.py`, `pyproject.toml`, `cli.py` (2 sitios)

#### Scripts de Test

- `scripts/test_phase13.py` — test manual sin LLM: clasificación, blocklist, ejecución real, timeout, truncado, allowed_only, patrones custom, sandboxing de cwd, validación de `CommandsConfig`

---

## [0.12.0] - 2026-02-20

### Fase 12 - Self-Evaluation (Critic Agent) ✅

#### Agregado

**`SelfEvaluator`** (`src/architect/core/evaluator.py`) — evaluador automático del resultado del agente:

- **`evaluate_basic(original_prompt, state)`** → `EvalResult`:
  - Construye contexto: prompt original + `state.final_output[:500]` + resumen de steps
  - Llama `llm.completion(messages, tools=None)` — sin tools, solo evaluación de texto
  - Parsea la respuesta JSON con 3 estrategias en orden:
    1. JSON directo (`json.loads`)
    2. Extracción de bloque de código `` ```json ... ``` ``
    3. Extracción del primer `{...}` válido con regex
  - Fallback conservador si ninguna estrategia funciona: `EvalResult(completed=False, confidence=0.0)`
  - Coste: ~500 tokens extra por evaluación

- **`evaluate_full(original_prompt, state, run_fn)`** → `AgentState`:
  - Loop de hasta `max_retries` ciclos de evaluación + corrección
  - Si `completed=True` y `confidence >= confidence_threshold` → retorna estado (éxito temprano)
  - Si no → construye prompt de corrección con issues y sugerencia, llama `run_fn(correction_prompt)`
  - Error en `run_fn` → detiene el loop silenciosamente (retorna último estado disponible)
  - `run_fn: Callable[[str], AgentState]` — evita acoplamiento circular con `AgentLoop`

- **`_EVAL_SYSTEM_PROMPT`** — prompt estricto que pide respuesta exclusivamente en JSON:
  `{"completed": bool, "confidence": float, "issues": [str, ...], "suggestion": str}`

**`EvalResult`** (dataclass):
- `completed: bool` — ¿se completó la tarea?
- `confidence: float` — nivel de confianza del LLM evaluador [0.0, 1.0] (clampeado)
- `issues: list[str]` — lista de problemas detectados (vacía si todo OK)
- `suggestion: str` — sugerencia para mejorar el resultado
- `raw_response: str` — respuesta cruda del LLM (para debugging)

**`EvaluationConfig`** (`src/architect/config/schema.py`) — nueva sección de configuración:
- `mode: Literal["off", "basic", "full"] = "off"` — modo de evaluación
- `max_retries: int = 2` — reintentos en modo `full` (rango: 1-5)
- `confidence_threshold: float = 0.8` — umbral para aceptar resultado en modo `full`
- `extra="forbid"` — validación estricta

**Opción `--self-eval` en CLI** (`src/architect/cli.py`):
- `--self-eval off|basic|full` — override del modo configurado en YAML
- Precedencia: CLI flag > `config.evaluation.mode`
- Solo se activa si `state.status == "success"` (evita evaluar fallos obvios)
- Modo `basic`: si no pasa → `state.status = "partial"`, muestra issues en stderr
- Modo `full`: `run_fn` capturado en closure sin streaming para los reintentos
- Output siempre a stderr (compatible con `--json` y pipes)

**Sección `evaluation:` en `config.example.yaml`**:
- Documentación completa de los 3 modos con ejemplos de uso
- Descripción de `max_retries` y `confidence_threshold`
- Override desde CLI documentado

#### Modificado

- **`src/architect/core/__init__.py`**: exporta `SelfEvaluator` y `EvalResult`
- **`src/architect/__init__.py`**: versión `0.12.0`
- **`pyproject.toml`**: versión `0.12.0`
- **`src/architect/cli.py`**: versión `0.12.0` en 3 sitios (version_option + 2 headers)

---

## [0.11.0] - 2026-02-20

### Fase 11 - Optimización de Tokens y Parallel Tool Calls ✅

#### Agregado

**`ContextManager`** (`src/architect/core/context.py`) — gestor del context window en 3 niveles:

- **Nivel 1 — `truncate_tool_result(content)`** (siempre activo):
  - Trunca tool results que superen `max_tool_result_tokens * 4` caracteres
  - Preserva las primeras 40 líneas y las últimas 20 (inicio + final, lo más valioso)
  - Inserta marcador `"[... N líneas omitidas ...]"` o `"[... N caracteres omitidos ...]"`
  - `max_tool_result_tokens=0` desactiva el truncado completamente
  - Integrado en `ContextBuilder._format_tool_result()` — transparente para el loop

- **Nivel 2 — `maybe_compress(messages, llm)`** (cuando hay demasiados pasos):
  - Se activa cuando el número de tool-exchanges supera `summarize_after_steps` (default: 8)
  - Separa los mensajes en "antiguos" y "recientes" (los últimos `keep_recent_steps*3`)
  - Llama al LLM para resumir los pasos antiguos en ~200 palabras
  - Produce: `[system, user, summary_assistant, *recent_steps]`
  - Falla silenciosamente si el LLM falla — retorna mensajes originales sin cambios
  - `summarize_after_steps=0` desactiva la compresión

- **Nivel 3 — `enforce_window(messages)`** (hard limit):
  - Si `_estimate_tokens(messages) > max_context_tokens`, elimina pares de mensajes (de 2 en 2) desde el más antiguo
  - Siempre conserva `messages[0]` (system) y `messages[1]` (user)
  - `max_context_tokens=0` desactiva el límite hard
  - Log warning cuando se eliminan mensajes

- Método auxiliar `_estimate_tokens(messages)` — estimación por `len(str) // 4` (≈4 chars/token)
- Método `_count_tool_exchanges(messages)` — cuenta assistant messages con tool_calls

**`ContextConfig`** (`src/architect/config/schema.py`) — nueva sección de configuración:
- `max_tool_result_tokens: int = 2000` — límite por tool result (Nivel 1)
- `summarize_after_steps: int = 8` — threshold para compresión (Nivel 2)
- `keep_recent_steps: int = 4` — pasos recientes conservados en compresión (Nivel 2)
- `max_context_tokens: int = 80000` — límite hard total (Nivel 3)
- `parallel_tools: bool = True` — habilitar parallel tool calls
- `extra="forbid"` — validación estricta

**Parallel Tool Calls** (`src/architect/core/loop.py`):
- `AgentLoop._execute_tool_calls_batch(tool_calls, step)` — ejecución del lote
- `AgentLoop._execute_single_tool(tc, step)` — ejecución de una sola tool call
- `AgentLoop._should_parallelize(tool_calls)` — lógica de decisión:
  - `parallel_tools=False` → siempre secuencial
  - `confirm-all` → siempre secuencial (requiere confirmación interactiva)
  - `confirm-sensitive` + alguna tool `sensitive=True` → secuencial
  - `yolo` o `confirm-sensitive` sin tools sensibles → `ThreadPoolExecutor(max_workers=4)`
  - Una sola tool call → secuencial (sin overhead de threads)
- `ThreadPoolExecutor` con `futures = {future: idx}` + `as_completed()` → **orden preservado**

**Testing** (`scripts/test_phase11.py`) — 22 tests:
1. Importaciones y versión 0.11.0
2. `ContextConfig` defaults y validación estricta
3. `ContextConfig` en `AppConfig`
4. `truncate_tool_result` — contenido corto (sin truncar)
5. `truncate_tool_result` — contenido largo (truncar)
6. `truncate_tool_result` — preserva inicio y fin
7. `truncate_tool_result` — `max_tool_result_tokens=0` (desactivado)
8. `enforce_window` — dentro del límite (sin cambios)
9. `enforce_window` — fuera del límite (recortar)
10. `enforce_window` — `max_context_tokens=0` (desactivado)
11. `maybe_compress` — pocos pasos (sin compresión, LLM no llamado)
12. `maybe_compress` — `summarize_after_steps=0` (desactivado)
13. `maybe_compress` — 9 pasos (compresión con LLM mock)
14. `ContextBuilder` con `context_manager` — trunca tool results
15. `ContextBuilder` sin `context_manager` — no trunca
16. `_should_parallelize` — modo yolo → paralelo
17. `_should_parallelize` — `confirm-all` → secuencial
18. `_should_parallelize` — `confirm-sensitive` + tool sensible → secuencial
19. `_should_parallelize` — `parallel_tools=False` → secuencial
20. Parallel tool calls — orden de resultados preservado
21. Integración `ContextManager` en `ContextBuilder`
22. Versión 0.11.0 consistente en 4 sitios

#### Modificado

**`src/architect/core/context.py`**:
- `ContextBuilder.__init__(context_manager: ContextManager | None = None)` — acepta manager
- `ContextBuilder._format_tool_result()` — aplica `truncate_tool_result()` si hay manager
- Importados: `structlog`, `ContextConfig`, `LLMAdapter` (runtime para `maybe_compress`)

**`src/architect/core/loop.py`**:
- `AgentLoop.__init__` añade parámetro `context_manager: ContextManager | None = None`
- Bloque de tool calls refactorizado: `_execute_tool_calls_batch()` reemplaza el bucle inline
- Tras `append_tool_results()`, se aplican niveles 2 y 3 del `ContextManager`
- Import añadido: `from concurrent.futures import ThreadPoolExecutor, as_completed`
- Import añadido: `ContextManager` desde `context`

**`src/architect/core/mixed_mode.py`**:
- `MixedModeRunner.__init__` añade `context_manager: ContextManager | None = None`
- Propaga `context_manager` a `plan_loop` y `build_loop` al crearlos

**`src/architect/core/__init__.py`**:
- Exporta `ContextManager`

**`src/architect/config/schema.py`**:
- Añadido `ContextConfig` (antes de `AppConfig`)
- `AppConfig` añade campo `context: ContextConfig = Field(default_factory=ContextConfig)`

**`src/architect/cli.py`**:
- Crea `context_mgr = ContextManager(config.context)` entre el indexador y el LLM
- `ContextBuilder(repo_index=repo_index, context_manager=context_mgr)`
- Pasa `context_manager=context_mgr` a `MixedModeRunner` y `AgentLoop`
- Import añadido: `ContextManager` desde `.core`

**`config.example.yaml`**:
- Nueva sección `context:` con los 5 campos documentados y ejemplos de modelos con sus límites

#### Versión
- `src/architect/__init__.py`: `0.10.0` → `0.11.0`
- `pyproject.toml`: `0.10.0` → `0.11.0`
- `src/architect/cli.py`: `0.10.0` → `0.11.0` (3 sitios: `version_option` + 2 headers)

#### Características Implementadas

- ✅ Tool results largos truncados automáticamente (preservando inicio+fin)
- ✅ Pasos antiguos resumidos con el propio LLM cuando el contexto crece
- ✅ Hard limit de tokens con ventana deslizante
- ✅ Parallel tool calls con `ThreadPoolExecutor` y orden preservado
- ✅ Decisión de paralelismo basada en `confirm_mode` y sensibilidad de tools
- ✅ `ContextConfig` integrado en `AppConfig` con validación estricta
- ✅ Sección `context:` en `config.example.yaml` completamente documentada
- ✅ 22 tests sin API key

#### Notas Técnicas

- `_estimate_tokens()` usa `len(str(messages)) // 4` — estimación suficientemente precisa para decisiones de compresión
- `ThreadPoolExecutor(max_workers=min(N, 4))` — cap de 4 workers para evitar saturar la red en MCP calls
- `as_completed(futures)` + `futures = {future: idx}` — patrón estándar para preservar orden con concurrencia
- `maybe_compress` falla silenciosamente — si el LLM no está disponible (offline, error de red), el loop continúa con los mensajes originales
- Nivel 2 (resumen) reduce `tool_exchanges` de `>summarize_after_steps` a `keep_recent_steps`, por lo que comprime cada `summarize_after_steps - keep_recent_steps` pasos adicionales

---

## [0.10.0] - 2026-02-20

### Fase 10 - Contexto Incremental Inteligente ✅

#### Agregado

**Módulo `src/architect/indexer/`** — nuevo módulo de indexación:

- **`src/architect/indexer/tree.py`** — indexador de repositorio:
  - `FileInfo` (dataclass) — metadatos de un archivo: `path`, `relative_path`, `size`, `language`, `lines`
  - `RepoIndex` (dataclass) — índice completo del repo: `files`, `tree_summary`, `total_files`, `total_lines`, `languages`, `build_time_ms`, `workspace_root`
  - `RepoIndexer` — clase principal de indexación:
    - Constructor: `workspace_root`, `max_file_size`, `exclude_dirs`, `exclude_patterns`
    - `build_index()` — construye y retorna un `RepoIndex`; usa `os.walk()` con modificación in-place de `dirnames` para pruning eficiente
    - `_format_tree_detailed()` — árbol Unicode (├──, └──, │) para repos ≤300 archivos
    - `_format_tree_compact()` — árbol agrupado por directorio raíz para repos >300 archivos
    - `_count_languages()` — dict de lenguajes ordenado por frecuencia
  - `EXT_MAP` — mapeo de 40+ extensiones a nombres de lenguaje
  - `DEFAULT_IGNORE_DIRS` — frozenset: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.hypothesis`, `dist`, `build`, `.eggs`
  - `DEFAULT_IGNORE_PATTERNS` — tuple: `*.min.js`, `*.min.css`, `*.map`, `*.pyc`, `*.pyo`, `*.pyd`, `.DS_Store`, `Thumbs.db`, `*.lock`, `*.log`
  - `MAX_TREE_FILES_DETAILED = 300` — umbral entre árbol detallado y compacto

- **`src/architect/indexer/cache.py`** — caché en disco del índice:
  - `IndexCache` — caché JSON por workspace con TTL configurable:
    - Clave de caché: SHA-256 (16 chars) del path absoluto del workspace
    - Directorio por defecto: `~/.architect/index_cache/`
    - TTL por defecto: 300 segundos (5 minutos)
    - `get(workspace_root)` — retorna `RepoIndex` si existe y no expiró, o `None`
    - `set(workspace_root, index)` — persiste índice como JSON, falla silenciosamente
    - `clear(workspace_root=None)` — limpia caché de un workspace o de todos
    - Serialización/deserialización completa de `RepoIndex` a/desde JSON

- **`src/architect/indexer/__init__.py`** — exports: `FileInfo`, `RepoIndex`, `RepoIndexer`, `IndexCache`

**`src/architect/tools/search.py`** — tres nuevas tools de búsqueda:

- `SearchCodeTool` (`search_code`, `sensitive=False`) — búsqueda por regex:
  - Args: `pattern`, `path="."`, `file_pattern=None`, `max_results=20`, `context_lines=2`, `case_sensitive=True`
  - Output con marcador `>` en líneas que coinciden, contexto arriba/abajo configurable
  - Formato: `📄 file.py:lineno` + bloque de código con contexto

- `GrepTool` (`grep`, `sensitive=False`) — búsqueda literal de texto:
  - Args: `text`, `path="."`, `file_pattern=None`, `max_results=30`, `case_sensitive=True`
  - Usa `rg` (ripgrep) o `grep` del sistema si están disponibles (`shutil.which`)
  - Fallback puro-Python cuando el comando no está disponible o hace timeout
  - `rg` con `--fixed-strings`, `--glob`; `grep` con `-F`, `--include`, `--exclude-dir`

- `FindFilesTool` (`find_files`, `sensitive=False`) — búsqueda de archivos por nombre glob:
  - Args: `pattern`, `path="."`
  - Usa `fnmatch.fnmatch(filename, pattern)` para matching
  - Omite los mismos `DEFAULT_IGNORE_DIRS` del indexador

**Schemas nuevos** (`src/architect/tools/schemas.py`):
- `SearchCodeArgs` — `pattern`, `path`, `file_pattern`, `max_results` (1–200), `context_lines` (0–10), `case_sensitive`
- `GrepArgs` — `text`, `path`, `file_pattern`, `max_results` (1–500), `case_sensitive`
- `FindFilesArgs` — `pattern`, `path`; todos con `extra="forbid"`

**`IndexerConfig`** (`src/architect/config/schema.py`):
- Nuevo modelo Pydantic con `extra="forbid"`:
  - `enabled: bool = True`
  - `max_file_size: int = 1_000_000` (1 MB)
  - `exclude_dirs: list[str] = []`
  - `exclude_patterns: list[str] = []`
  - `use_cache: bool = True`
- Añadido a `AppConfig`: `indexer: IndexerConfig = Field(default_factory=IndexerConfig)`

**Testing** (`scripts/test_phase10.py`) — 12 grupos de pruebas:
1. Importaciones del módulo indexer y tools de búsqueda
2. `RepoIndexer` básico — indexa el workspace actual, cuenta archivos y lenguajes
3. Exclusión de directorios (`node_modules`, `__pycache__`, `.git`)
4. `FileInfo` — campos path, size, language, lines correctamente poblados
5. Detección de lenguajes — Python, YAML, Markdown detectados
6. `IndexCache` set/get — persistencia y recuperación del índice
7. `IndexCache` TTL — retorna `None` si el TTL expiró
8. `SearchCodeTool` — búsqueda básica, file_pattern, context_lines, sin resultados, regex inválido, case insensitive
9. `GrepTool` — búsqueda literal básica, file_pattern, sin resultados, case insensitive
10. `FindFilesTool` — glob básico, patrón `test_*`, sin resultados, extensiones yaml
11. `ContextBuilder` — sin índice (prompt sin sección), con índice (inyecta "Estructura del Proyecto"), prompt base preservado
12. Consistencia de versión, `IndexerConfig` en `AppConfig`, search tools en registry, agentes con search tools, build con edit tools, CLI `--version`

#### Modificado

**`src/architect/tools/setup.py`**:
- Nueva función `register_search_tools(registry, workspace_config)` — registra `search_code`, `grep`, `find_files`
- Nueva función `register_all_tools(registry, workspace_config)` — combina filesystem + search tools
- `register_filesystem_tools()` sin cambios

**`src/architect/tools/__init__.py`**:
- Nuevos exports: `SearchCodeTool`, `GrepTool`, `FindFilesTool`, `SearchCodeArgs`, `GrepArgs`, `FindFilesArgs`, `register_search_tools`, `register_all_tools`

**`src/architect/core/context.py`** — inyección de índice en system prompt:
- `ContextBuilder.__init__(self, repo_index: RepoIndex | None = None)` — acepta índice opcional
- `build_initial()` llama `_inject_repo_index()` si hay índice disponible
- `_inject_repo_index()` añade sección "## Estructura del Proyecto" al system prompt:
  - Totales: archivos, líneas, lenguajes top-5
  - `tree_summary` completo del repositorio
  - Guía de uso de `search_code`, `grep`, `find_files`
- Import de `RepoIndex` bajo `TYPE_CHECKING` para evitar importaciones circulares

**`src/architect/agents/registry.py`** — search tools en todos los agentes:
- Agentes `plan`, `build`, `resume`, `review` añaden: `search_code`, `grep`, `find_files` a `allowed_tools`
- Agente `build` añade también `edit_file`, `apply_patch` (faltaban)
- Agente `build` aumenta `max_steps` de 20 a 25

**`src/architect/agents/prompts.py`** — guía de herramientas de búsqueda:
- `PLAN_PROMPT`: nueva tabla "Herramientas de Exploración" con cuándo usar cada tool
- `BUILD_PROMPT`: nueva tabla "Herramientas de Búsqueda (F10)" + "Flujo de Trabajo Típico" actualizado para referenciar search tools primero

**`src/architect/cli.py`** — integración del indexador:
- Import cambiado: `register_filesystem_tools` → `register_all_tools`
- Imports añadidos: `IndexCache`, `RepoIndex`, `RepoIndexer`
- Bloque de indexación al inicio de `run()`:
  - Respeta `config.indexer.enabled`
  - Lee de caché si `config.indexer.use_cache=True` y la caché es fresca
  - Construye índice si no hay caché o está obsoleta
  - Actualiza caché tras construir
  - Log de estado si `verbose >= 1`
- `ContextBuilder(repo_index=repo_index)` recibe el índice

**`config.example.yaml`**:
- Nueva sección `indexer:` documentando todos los campos de `IndexerConfig` con comentarios explicativos, ejemplos de `exclude_dirs` y `exclude_patterns`

#### Versión
- `src/architect/__init__.py`: `0.9.0` → `0.10.0`
- `pyproject.toml`: `0.9.0` → `0.10.0`
- `src/architect/cli.py`: `0.9.0` → `0.10.0` (3 sitios: `version_option` + 2 headers)

#### Características Implementadas

- ✅ Indexador de repositorio con árbol Unicode (detallado ≤300 archivos, compacto >300)
- ✅ Caché en disco con SHA-256 por workspace y TTL de 5 minutos
- ✅ `SearchCodeTool` — búsqueda regex con contexto configurable
- ✅ `GrepTool` — búsqueda literal con rg/grep del sistema + fallback Python
- ✅ `FindFilesTool` — búsqueda de archivos por patrón glob
- ✅ `IndexerConfig` — sección `indexer:` en YAML con validación estricta
- ✅ System prompt enriquecido con árbol del proyecto + guía de search tools
- ✅ Todos los agentes (plan/build/resume/review) con acceso a search tools
- ✅ CLI con indexación automática al inicio, respetando config y caché
- ✅ 12 grupos de tests sin API key

#### Uso

```bash
# El indexador actúa automáticamente al iniciar (con verbose=1 muestra stats)
architect run "analiza la arquitectura del proyecto" -a resume -v

# Deshabilitar indexador en repos muy grandes
architect run "tarea puntual" --no-stream  # el indexador sigue activo
```

```yaml
# config.yaml — deshabilitar caché o excluir directorios extra
indexer:
  enabled: true
  use_cache: true
  exclude_dirs:
    - vendor
    - .terraform
  exclude_patterns:
    - "*.generated.py"
```

```bash
# El agente ahora puede usar search_code/grep/find_files directamente
# Inyectado automáticamente en el system prompt:
# "Usa search_code para buscar patrones regex,
#  grep para texto literal, find_files para nombres de archivo"
```

#### Notas Técnicas

- `os.walk()` modifica `dirnames` in-place → poda eficiente sin descender a dirs excluidos
- Árbol detallado usa conectores Unicode: `├──`, `└──`, `│` (compatible con terminales UTF-8)
- `GrepTool` detecta rg vs grep por `os.path.basename(cmd)` para construir flags correctos
- `IndexCache` falla silenciosamente en escritura — nunca rompe la ejecución si `~/.architect/` no es accesible
- `ContextBuilder` usa `TYPE_CHECKING` guard para el import de `RepoIndex` (evita importaciones circulares)
- Paths en resultados de search usan `.replace("\\", "/")` para compatibilidad Windows/WSL

---

## [0.9.0] - 2026-02-19

### Fase 9 - Diff Inteligente y apply_patch ✅

#### Agregado

**`EditFileTool`** (`src/architect/tools/filesystem.py`):
- Tool `edit_file` para modificaciones parciales via str_replace exacto
- Valida que `old_str` aparezca exactamente una vez en el archivo
- Si `old_str` no existe → error `"no encontrado"` con sugerencia
- Si `old_str` aparece >1 veces → error con el conteo y sugerencia de añadir contexto
- Si `old_str` está vacío → error descriptivo con alternativas
- Genera diff en el output (vía `difflib.unified_diff`) para confirmación visual
- `sensitive = True`; requiere confirmación en modo `confirm-sensitive` o superior

**`ApplyPatchTool`** (`src/architect/tools/patch.py`):
- Tool `apply_patch` para parches unified diff con uno o más hunks
- **Parser puro-Python** (sin dependencias externas):
  - Regex `^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@` para cabeceras
  - Soporte de hunks de inserción pura (`orig_count=0`)
  - Offset acumulado entre hunks para ajustar posiciones
  - Validación de contexto con normalización de line endings (`rstrip("\n\r")`)
- **Fallback al comando `patch` del sistema** si el parser puro falla:
  - `patch --dry-run -f -i patch_file file_path` → validación sin modificar
  - `patch -f -i patch_file file_path` → aplicación real
- Las cabeceras `--- / +++` en el parche son opcionales
- `sensitive = True`

**`PatchError`** (`src/architect/tools/patch.py`):
- Excepción interna para errores de parseo/aplicación de parches

**Schemas nuevos** (`src/architect/tools/schemas.py`):
- `EditFileArgs` — `path`, `old_str`, `new_str` (todos requeridos excepto `new_str` que puede ser `""`)
- `ApplyPatchArgs` — `path`, `patch`

**Testing** (`scripts/test_phase9.py`) — 12 pruebas:
1. Importaciones de nuevas tools y `PatchError`
2. Versión 0.9.0 consistente en `__init__.py` y `pyproject.toml`
3. `EditFileTool` caso feliz — reemplazo y diff en output
4. `EditFileTool` old_str no encontrado — error descriptivo
5. `EditFileTool` old_str ambiguo — error con conteo
6. `EditFileTool` old_str vacío — error con alternativas
7. `ApplyPatchTool` single-hunk
8. `ApplyPatchTool` multi-hunk (2 hunks, posiciones no contiguas)
9. `ApplyPatchTool` inserción pura (`orig_count=0`)
10. `ApplyPatchTool` contexto incorrecto — falla con error claro
11. Jerarquía en descriptions de tools (`PREFERIR`, menciones cruzadas)
12. `EditFileTool` y `ApplyPatchTool` presentes en el registry

#### Modificado

**`WriteFileTool.description`** (`src/architect/tools/filesystem.py`):
- Ahora incluye orientación explícita: úsalo solo para archivos nuevos o reescritura total
- Referencia a `edit_file` y `apply_patch` como alternativas

**`BUILD_PROMPT`** (`src/architect/agents/prompts.py`):
- Nueva sección "Herramientas de Edición — Jerarquía de Uso" con tabla comparativa
- Guía detallada para `edit_file`, `apply_patch` y `write_file`
- El agente `build` ahora sabe cuándo preferir cada herramienta

**`src/architect/tools/setup.py`**:
- Registra `EditFileTool` y `ApplyPatchTool` en el registry por defecto

**`src/architect/tools/__init__.py`**:
- Exporta `EditFileTool`, `ApplyPatchTool`, `PatchError`, `EditFileArgs`, `ApplyPatchArgs`

#### Versión
- `src/architect/__init__.py`: `0.8.0` → `0.9.0`
- `pyproject.toml`: `0.8.0` → `0.9.0`
- `src/architect/cli.py`: `0.8.0` → `0.9.0` (3 sitios: `version_option` + 2 headers)

---

## [0.8.0] - 2026-02-19

### Fase 8 - Integración Final y Pulido ✅

#### Agregado

**Subcomando `architect agents`** (`src/architect/cli.py`):
- Lista los 4 agentes por defecto: `plan`, `build`, `resume`, `review`
- Muestra nombre, descripción y confirm_mode de cada agente
- Con `-c config.yaml`: incluye también los agentes custom del YAML
- Los defaults sobreescritos por el YAML se marcan con `*`
- Comando: `architect agents` / `architect agents -c config.yaml`

**Testing de integración (`scripts/test_phase8.py`)** — 7 pruebas:
1. **Importaciones**: verifica que los 23 módulos del proyecto importan sin errores
2. **Versión consistente**: comprueba que `__init__.py`, `pyproject.toml`, `--version` y `cli.py` headers muestran "0.8.0"
3. **CLI --help**: `architect --help`, `architect run --help` (con PROMPT/--dry-run/--mode/--json), `architect agents --help`, `architect validate-config --help`
4. **Subcomando agents**: verifica que los 4 agentes por defecto aparecen en la salida
5. **validate-config con example**: valida `config.example.yaml` y parsea correctamente (model, retries, stream, allow_delete)
6. **Inicialización completa sin LLM**: AppConfig, configure_logging, ToolRegistry, DEFAULT_AGENTS, GracefulShutdown, StepTimeout, ExecutionEngine, ContextBuilder
7. **dry-run sin API key**: verifica que falla con error de LLM (exit 1/4), no de config (exit 3)

#### Modificado

**Versión 0.8.0** — actualizada en todos los puntos:
- `src/architect/__init__.py` → `__version__ = "0.8.0"` (era "0.6.0")
- `pyproject.toml` → `version = "0.8.0"` (era "0.6.0")
- `src/architect/cli.py` → `@click.version_option(version="0.8.0")` (era "0.6.0")
- `src/architect/cli.py` → headers de ejecución muestran `architect v0.8.0`

**`config.example.yaml`** — reescrito completamente:
- Sección `llm`: explicación de provider/mode, todos los campos con comentarios, ejemplos de modelos (OpenAI, Anthropic, Gemini, Ollama, Together), `api_base` comentado, explicación detallada de `retries` (qué errores se reintentan y cuáles no), `stream` con notas sobre auto-desactivación
- Sección `agents`: explicación del sistema de merge, 3 agentes custom de ejemplo comentados (deploy, documenter, security) con system_prompt, allowed_tools, confirm_mode, max_steps
- Sección `logging`: tabla de niveles verbose (0-3), campo `file` comentado con ejemplo
- Sección `workspace`: explicación de confinamiento y path traversal, `allow_delete` con nota de seguridad
- Sección `mcp`: 4 ejemplos de servidores comentados (git, database, github+jira, internal), nota sobre `token` vs `token_env`
- Cabecera con versión 0.8.0 y explicación del orden de precedencia

**`README.md`** — reescrito completamente como documentación de usuario final:
- Instalación: requisitos Python 3.12+, `pip install -e .`, verificación, dependencias principales
- Quickstart: 7 ejemplos de uso reales (resume, review, plan, build, mixed, yolo, dry-run)
- Referencia `architect run`: tabla completa de opciones (principales, LLM, output, MCP)
- Referencia `architect agents` y `architect validate-config`
- Tabla de agentes: nombre, descripción, tools disponibles, confirm_mode
- Modo mixto: explicación del flujo plan→build
- Agentes custom: ejemplo YAML completo
- Modos de confirmación: tabla con comportamiento de cada modo
- Configuración: estructura YAML mínima, tabla de variables de entorno
- Salida y códigos de salida: separación stdout/stderr, tabla de 7 códigos, ejemplos bash
- Formato JSON (`--json`): ejemplo real con todos los campos
- Logging: ejemplos de todos los niveles (-v, -vv, -vvv, --quiet, --log-file, jq)
- MCP: YAML de configuración, ejemplo con/sin MCP
- CI/CD: GitHub Actions completo con verificación de resultado
- Arquitectura: diagrama ASCII del flujo interno, decisiones de diseño
- Seguridad: path traversal, allow_delete, MCP sensitive, API keys
- Proveedores LLM: ejemplos con OpenAI, Anthropic, Gemini, Ollama, LiteLLM Proxy
- Extensiones futuras

#### Características Implementadas

- ✅ Subcomando `architect agents` funcional (defaults + custom YAML)
- ✅ Versión 0.8.0 consistente en los 4 puntos del sistema
- ✅ `config.example.yaml` completamente documentado con todos los casos de uso
- ✅ README.md como documentación completa de usuario final
- ✅ Suite de integración: 7 pruebas que verifican el sistema completo sin API key

#### Uso

```bash
# Listar agentes disponibles
architect agents

# Listar agentes incluyendo custom del YAML
architect agents -c config.yaml

# Verificar la versión
architect --version

# Validar configuración
architect validate-config -c config.example.yaml

# Flujo completo (requiere API key)
LITELLM_API_KEY=sk-... architect run "analiza el proyecto" -a resume --quiet
```

#### Notas Técnicas

- `architect agents` muestra defaults aunque no haya config — no requiere API key ni YAML
- El subcomando re-usa `load_config()` con `config_path=None` cuando no se pasa `-c`
- Versión bump de 0.6.0 a 0.8.0 (salto intencional: F7 fue versión interna, F8 es el MVP)
- `test_phase8.py` verifica imports, CLI, y lógica de inicialización — no requiere LLM activo

#### MVP Completado

v0.8.0 es el MVP completo y funcional. Todas las fases del plan implementadas:
- F0: Scaffolding + config
- F1: Tools + execution engine
- F2: LLM adapter + agent loop
- F3: Sistema de agentes + mixed mode
- F4: MCP connector
- F5: Logging dual pipeline
- F6: Streaming + output final
- F7: Robustez y tolerancia a fallos
- F8: Integración final y pulido ✅

---

## [0.7.0] - 2026-02-19

### Fase 7 - Robustez y Tolerancia a Fallos ✅

#### Agregado

**StepTimeout (`src/architect/core/timeout.py`)** — nuevo archivo:
- Clase `StepTimeout` - Context manager de timeout por step
  - Usa `signal.SIGALRM` en sistemas POSIX (Linux/macOS)
  - No-op gracioso en Windows (sin SIGALRM), sin romper la ejecución
  - Parámetro `seconds=0` deshabilita el timeout completamente
  - Guarda y restaura el handler previo al salir (compatible con handlers anidados)
  - Cancela la alarma pendiente con `signal.alarm(0)` al salir limpiamente
- `StepTimeoutError(TimeoutError)` — excepción lanzada al expirar
  - Incluye el número de segundos en el mensaje
  - Subclase de `TimeoutError` (fácil de capturar específicamente)
- `_SIGALRM_SUPPORTED` — constante calculada al importar para detección de plataforma

**GracefulShutdown (`src/architect/core/shutdown.py`)** — nuevo archivo:
- Clase `GracefulShutdown` — gestión de señales de interrupción
  - Instala handlers para `SIGINT` y `SIGTERM` al instanciar
  - Primer disparo: muestra aviso en stderr, marca `_interrupted = True`
  - Segundo disparo `SIGINT`: `sys.exit(130)` inmediato (estándar POSIX)
  - `SIGTERM` siempre comportamiento graceful (para Docker/Kubernetes)
  - Propiedad `should_stop` — True si se recibió señal de interrupción
  - Método `reset()` — resetea el flag (útil para testing)
  - Método `restore_defaults()` — restaura `SIG_DFL` para cleanup

**Testing (`scripts/test_phase7.py`)** — 11 pruebas:
- StepTimeout sin timeout (seconds=0)
- StepTimeout dentro del límite
- StepTimeout expiración → StepTimeoutError
- StepTimeout restaura handler anterior
- GracefulShutdown estado inicial (should_stop=False)
- GracefulShutdown reset del flag
- AgentLoop acepta parámetros shutdown y step_timeout
- Retries LLM — _RETRYABLE_ERRORS contiene los tipos correctos
- Retries LLM — _call_with_retry ejecuta sin errores
- Tool errors como feedback (ExecutionEngine nunca lanza excepción)
- Integración estructural completa de F7

#### Modificado

**LLMAdapter (`src/architect/llm/adapter.py`)** — retries mejorados:
- Eliminado decorator `@retry(Exception)` (demasiado amplio, no configurable)
- `_RETRYABLE_ERRORS` — tupla con solo errores transitorios:
  - `litellm.RateLimitError` — límite de rate del proveedor
  - `litellm.ServiceUnavailableError` — servicio no disponible (503)
  - `litellm.APIConnectionError` — error de conexión de red
  - `litellm.Timeout` — timeout en la llamada HTTP
  - **NO incluye**: `AuthenticationError`, errores de configuración, etc.
- `_call_with_retry(fn, *args, **kwargs)` — método de instancia con Retrying:
  - `stop_after_attempt(config.retries + 1)` — usa `config.retries` real
  - `wait_exponential(multiplier=1, min=2, max=60)` — backoff progresivo
  - `before_sleep=self._on_retry_sleep` — callback de logging
  - `reraise=True` — propaga el último error
- `_on_retry_sleep(retry_state)` — logging estructurado antes de cada reintento:
  - Logea: `llm.retry`, attempt, wait_seconds, error, error_type
  - Usa `retry_state.next_action.sleep` para el tiempo de espera
- `completion()` refactorizado — usa `_call_with_retry` internamente

**AgentLoop (`src/architect/core/loop.py`)** — shutdown y timeout:
- Nuevos parámetros en `__init__`:
  - `shutdown: GracefulShutdown | None = None` — señal de interrupción
  - `step_timeout: int = 0` — segundos por step (0=sin límite)
- Comprobación de `shutdown.should_stop` al **inicio de cada iteración**:
  - Si True → `status="partial"`, mensaje descriptivo, `break`
- `StepTimeout(self.step_timeout)` envuelve la llamada al LLM (streaming y no-streaming)
- `StepTimeoutError` capturada específicamente:
  - `status="partial"`, mensaje con step number y segundos configurados
  - No propaga la excepción al llamador

**MixedModeRunner (`src/architect/core/mixed_mode.py`)** — shutdown y timeout:
- Nuevos parámetros: `shutdown` y `step_timeout`
- Los pasa a `plan_loop` y `build_loop` al instanciarlos
- Verificación adicional de `shutdown.should_stop` entre fase plan y build:
  - Si hubo shutdown durante plan → retorna `plan_state` inmediatamente

**CLI (`src/architect/cli.py`)** — GracefulShutdown integrado:
- `shutdown = GracefulShutdown()` — instanciado al inicio de `run()`
- Handler inline de SIGINT de F6 eliminado (reemplazado por la clase)
- `shutdown=shutdown` pasado a `AgentLoop` y `MixedModeRunner`
- `step_timeout=kwargs.get("timeout") or 0` — usa el flag `--timeout` del CLI
- `if shutdown.should_stop: sys.exit(EXIT_INTERRUPTED)` al finalizar
- Import `signal` eliminado (ya no necesario en CLI)

**Exports (`src/architect/core/__init__.py`)**:
- Añadido: `GracefulShutdown`, `StepTimeout`, `StepTimeoutError`

#### Características Implementadas

- ✅ StepTimeout: SIGALRM en POSIX, no-op en Windows, restaura handlers
- ✅ GracefulShutdown: SIGINT graceful + inmediato, SIGTERM graceful
- ✅ Retries selectivos: solo errores transitorios, no errores de auth
- ✅ Logging en cada reintento (intento, espera, tipo de error)
- ✅ config.retries usado realmente para configurar max_attempts
- ✅ AgentLoop comprueba shutdown antes de cada step
- ✅ AgentLoop envuelve LLM en StepTimeout
- ✅ MixedModeRunner propaga shutdown y timeout a ambos loops
- ✅ CLI usa GracefulShutdown class (código más limpio)

#### Notas Técnicas

- `SIGALRM` no disponible en Windows — StepTimeout es no-op, no rompe nada
- `_call_with_retry` es método de instancia (puede acceder a `self.config.retries`)
- El logger en `_on_retry_sleep` usa `self.log` (componente y modelo ya vinculados)
- `GracefulShutdown` instanciado antes de cargar config — captura Ctrl+C desde el inicio
- `step_timeout` usa el flag `--timeout` existente (re-usa config existente)
- Segundo SIGINT: `sys.exit(130)` — sale desde dentro del handler (no loop)

#### Próxima Fase

F8 - Integración Final y Pulido (Día 11-12)

---

## [0.6.0] - 2026-02-19

### Fase 6 - Streaming + Output Final ✅

#### Modificado

**CLI (`src/architect/cli.py`) - Streaming conectado y exit codes completos**:

- **Streaming activado por defecto**:
  - `use_stream` calculado automáticamente al inicio del comando `run`
  - Activo si: `config.llm.stream=True` AND NOT `--no-stream` AND NOT `--json`
  - Callback `on_stream_chunk` definido localmente: escribe a `sys.stderr` en tiempo real
  - Callback se pasa a `loop.run()` y `runner.run()` (ya soportaban el parámetro)
  - Newline final añadido a stderr tras el último chunk de streaming
  - Info del header muestra `📡 Streaming: sí/no` para claridad

- **Separación stdout/stderr completa**:
  - Toda la info de progreso (header, MCP stats, dry-run notice) → `err=True` (stderr)
  - Streaming chunks → `sys.stderr`
  - Separadores y estadísticas finales → `err=True` (stderr)
  - Resultado final del agente → `click.echo(state.final_output)` → **stdout**
  - `--json` output → `click.echo(json.dumps(...))` → **stdout**
  - Compatible con pipes: `architect run "..." --quiet --json | jq .`

- **Códigos de salida completos** (constantes definidas como módulo-level):
  - `EXIT_SUCCESS = 0` - Éxito
  - `EXIT_FAILED = 1` - Fallo del agente
  - `EXIT_PARTIAL = 2` - Parcial
  - `EXIT_CONFIG_ERROR = 3` - Error de configuración (FileNotFoundError)
  - `EXIT_AUTH_ERROR = 4` - Error de autenticación LLM
    - Detección por keywords: authenticationerror, api key, unauthorized, 401
  - `EXIT_TIMEOUT = 5` - Timeout
    - Detección por keywords: timeout, timed out, readtimeout
  - `EXIT_INTERRUPTED = 130` - Interrumpido por señal (estándar POSIX)

- **Manejo de SIGINT (graceful shutdown)**:
  - Handler instalado al inicio de `run()` con `signal.signal(SIGINT, ...)`
  - Primer Ctrl+C: muestra aviso, marca `interrupted=True`, continúa el step actual
  - Segundo Ctrl+C: `sys.exit(EXIT_INTERRUPTED)` inmediato
  - Al terminar: si `interrupted`, sale con código 130
  - `KeyboardInterrupt` como fallback en el bloque `except` principal
  - Estado del agente marcado como `partial` si fue interrumpido antes de terminar

- **Limpieza de imports**:
  - Eliminado `DEFAULT_AGENTS` (importado pero no usado directamente)
  - Añadido `json` y `signal` al top-level
  - Añadido `Callable` desde `typing`

- **Versión actualizada**:
  - `@click.version_option(version="0.6.0")` (era "0.1.0")
  - Headers de ejecución muestran `architect v0.6.0`
  - `validate_config` usa constantes `EXIT_CONFIG_ERROR` y `EXIT_FAILED`

**Testing (`scripts/test_phase6.py`)** - Suite completa nueva:
- Prueba 1: Formato JSON de `to_output_dict()` — verifica campos, tipos y valores
- Prueba 2: Constantes de exit codes — verifica los 7 códigos definidos
- Prueba 3: Streaming callback (mock) — simula chunks y verifica acumulación correcta
- Prueba 4: Separación stdout/stderr — documentación y verificación conceptual
- Prueba 5: Streaming real (opcional, requiere API key) — verifica chunks reales del LLM

#### Características Implementadas

- ✅ Streaming del LLM visible en terminal (stderr en tiempo real)
- ✅ `--no-stream` deshabilita streaming explícitamente
- ✅ Streaming auto-desactivado con `--json` y `--quiet`
- ✅ 7 códigos de salida con detección automática de tipo de error
- ✅ SIGINT: graceful (primer Ctrl+C) e inmediato (segundo Ctrl+C)
- ✅ Todo el output no-resultado va a stderr (stdout limpio para pipes)
- ✅ `--json` produce formato completo parseable por jq
- ✅ Versión actualizada a 0.6.0 en CLI y headers

#### Uso

```bash
# Streaming por defecto (se ve en terminal, no rompe pipes)
architect run "refactoriza main.py" -a build --mode yolo

# Sin streaming (útil para CI o logs más limpios)
architect run "tarea" --no-stream -v

# Salida JSON para pipes (streaming desactivado automáticamente)
architect run "resume el proyecto" --quiet --json | jq .status

# Logging a archivo + streaming visible
architect run "tarea compleja" -vv --log-file logs/run.jsonl

# Verificar exit codes
architect run "tarea" --mode yolo
echo "Exit code: $?"
# 0=success, 1=failed, 2=partial, 3=config error, 4=auth, 5=timeout, 130=Ctrl+C
```

#### Notas Técnicas

- Streaming chunks van a stderr: el stdout queda libre para el resultado/JSON
- El callback `on_stream_chunk` ya estaba soportado en `AgentLoop` y `MixedModeRunner`
- En mixed mode, solo la fase `build` usa streaming (plan es rápido y no necesita)
- Detección de errores de auth/timeout por keywords en el mensaje (compatible con LiteLLM)
- Signal handler es local al comando `run` para no afectar otros contextos
- `EXIT_INTERRUPTED = 130` sigue el estándar POSIX (128 + SIGINT=2)

#### Próxima Fase

F7 - Robustez y Tolerancia a Fallos (Día 10-11)

---

## [0.5.5] - 2026-02-18

### Fase 5 - Logging Completo ✅

#### Agregado

**Sistema de Logging Dual Pipeline**:
- `src/architect/logging/setup.py` - Reescritura completa del sistema de logging
  - Función `configure_logging()` - Configuración completa con dual pipeline
    - Pipeline 1: Archivo → JSON estructurado (JSON Lines)
      - FileHandler con encoding UTF-8
      - JSONRenderer de structlog
      - Nivel: DEBUG (captura todo)
      - Formato: un JSON por línea para parsing fácil
      - Creación automática de directorio padre
    - Pipeline 2: Stderr → Humano legible
      - StreamHandler a sys.stderr
      - ConsoleRenderer con colores automáticos (solo si TTY)
      - Nivel: según verbose/quiet
      - Formato: timestamp, nivel, logger, mensaje, campos extra
    - Procesadores compartidos:
      - merge_contextvars - Contexto global
      - add_log_level - Nivel de logging
      - add_logger_name - Nombre del logger
      - TimeStamper (ISO 8601, UTC)
      - StackInfoRenderer - Stack traces
      - format_exc_info - Formateo de excepciones
    - Configuración independiente:
      - Archivo siempre captura DEBUG completo
      - Stderr filtrado por verbose/quiet
      - Ambos pipelines pueden coexistir
    - ProcessorFormatter para dual rendering:
      - wrap_for_formatter en procesadores
      - formatter diferente por handler
      - JSON para archivo, Console para stderr

  - Función `_verbose_to_level()` - Mapeo de verbose a nivel logging
    - Niveles claros y progresivos:
      - 0 (sin -v) → WARNING (solo problemas)
      - 1 (-v) → INFO (steps del agente, tool calls principales)
      - 2 (-vv) → DEBUG (argumentos, respuestas LLM detalladas)
      - 3+ (-vvv) → DEBUG completo (incluyendo HTTP, internals)
    - Diseñado para debugging incremental

  - Función `configure_logging_basic()` - Backward compatibility
    - Para código de fases anteriores
    - Llama a configure_logging() con defaults razonables
    - level="info", verbose=1, file=None

  - Función `get_logger()` - Obtención de logger estructurado
    - Retorna structlog.BoundLogger
    - Logger estructurado con typing completo
    - Soporte para contexto y campos extra

  - Características del sistema:
    - Logs a stderr (stdout libre para output final)
    - JSON Lines en archivo (un JSON por línea)
    - Colores automáticos solo en TTY
    - Quiet mode: solo ERROR level
    - JSON output mode compatible (reduce logging)
    - Configuración vía LoggingConfig Pydantic
    - Sin handlers duplicados (clear antes de configurar)
    - Reset de structlog defaults cada vez

**Testing**:
- `scripts/test_phase5.py` - Suite completa de pruebas de logging
  - Prueba 1: Niveles de logging (verbose 0-3)
    - Genera logs en los 4 niveles (debug, info, warning, error)
    - Muestra comportamiento de cada verbose level
    - Verifica filtrado correcto por nivel

  - Prueba 2: Logging a archivo JSON
    - Crea archivo temporal .jsonl
    - Genera logs con contexto estructurado:
      - agent.step.start/complete
      - tool.call con argumentos
      - tool.result con success
    - Lee y muestra JSON generado
    - Verifica formato JSON Lines
    - Limpieza automática de archivos temporales

  - Prueba 3: Modo quiet
    - Configura con quiet=True
    - Genera debug, info, warning (no deberían verse)
    - Genera error (sí debería verse)
    - Verifica que solo ERROR se muestra

  - Prueba 4: Logging estructurado con contexto
    - Simula ejecución real de agent loop
    - Eventos: agent.loop.start, agent.step.start, llm.completion.start
    - Tool calls con múltiples steps
    - Contexto coherente (step, agent, prompt)
    - Muestra uso realista del sistema

  - Prueba 5: Dual pipeline simultáneo
    - Archivo JSON + stderr humano al mismo tiempo
    - Genera logs que van a ambos destinos
    - Compara output en stderr vs archivo JSON
    - Verifica que formatos son diferentes pero contenido igual
    - Demuestra independencia de los pipelines

  - Output formateado con:
    - Headers con caracteres box drawing
    - Separadores visuales
    - Notas técnicas al final
    - Explicación de cada test

**Integración CLI**:
- `src/architect/cli.py` - CLI actualizado para usar logging completo
  - Import actualizado: `from .logging import configure_logging`
  - Configuración temprana de logging (después de load_config)
  - Llamada a `configure_logging()` con:
    - config.logging (LoggingConfig completo)
    - json_output desde CLI args
    - quiet desde CLI args
  - Logging configurado ANTES de crear componentes
  - Todos los componentes pueden usar get_logger() desde el inicio
  - Flags CLI pasados correctamente:
    - --verbose (count) → config.logging.verbose
    - --log-file → config.logging.file
    - --log-level → config.logging.level
    - --json → json_output parameter
    - --quiet → quiet parameter

- `src/architect/logging/__init__.py` - Exports actualizados
  - Mantiene exports anteriores para compatibilidad
  - configure_logging_basic() disponible
  - get_logger() como interfaz principal

#### Características Implementadas

- ✅ Dual pipeline completo (archivo JSON + stderr humano)
- ✅ Verbose levels progresivos (0-3+)
- ✅ Quiet mode funcional (solo errores)
- ✅ JSON Lines format para archivos
- ✅ Console renderer con colores automáticos
- ✅ Logs a stderr (stdout libre para pipes)
- ✅ Configuración vía Pydantic (type-safe)
- ✅ Procesadores compartidos entre pipelines
- ✅ Backward compatibility con configure_logging_basic()
- ✅ Suite de pruebas completa (5 tests)
- ✅ Integración completa con CLI

#### Mejoras

- 🔄 Sistema de logging profesional y robusto
- 🔄 Debugging incremental con -v, -vv, -vvv
- 🔄 Logs estructurados para análisis automatizado
- 🔄 Output humano para desarrollo y debugging
- 🔄 Compatible con pipes y redirecciones
- 🔄 Colores solo cuando tiene sentido (TTY detection)

#### Uso

```bash
# Logging normal (INFO level, -v)
architect run "analiza proyecto" -v

# Debugging detallado (DEBUG level, -vv)
architect run "construye módulo" -a build -vv

# Debugging completo (DEBUG+, -vvv)
architect run "tarea compleja" -vvv

# Modo silencioso (solo errores)
architect run "deploy" --quiet

# Con archivo de logs JSON
architect run "refactoriza" -v --log-file logs/session.jsonl

# Analizar logs después
cat logs/session.jsonl | jq -r 'select(.event=="tool.call") | .tool'
```

```yaml
# config.yaml
logging:
  level: info
  verbose: 1
  file: logs/architect.jsonl
```

#### Notas Técnicas

- Logs van a stderr, output final a stdout (compatible con pipes)
- JSON Lines (`.jsonl`): un JSON por línea, fácil de parsear línea a línea
- Dual pipeline usa ProcessorFormatter de structlog
- Procesadores compartidos aseguran consistencia
- Colores automáticos con `sys.stderr.isatty()` detection
- Verbose progresivo: WARNING → INFO → DEBUG → DEBUG completo
- Quiet mode útil para CI/CD (solo errores)
- File logging captura todo (DEBUG), stderr se filtra
- Backward compatible con fases anteriores

#### Próxima Fase

F6 - CLI Streaming (Día 9-10)

---

## [0.5.0] - 2026-02-18

### Fase 4 - MCP Connector ✅

#### Agregado

**Cliente MCP (JSON-RPC 2.0)**:
- `src/architect/mcp/client.py` - Cliente HTTP completo para servidores MCP
  - Clase `MCPClient` - Cliente con protocolo JSON-RPC 2.0
  - Método `list_tools()` - Lista tools vía método 'tools/list'
    - Request JSON-RPC con id=1
    - Parsing de respuesta con manejo de errores
    - Retorna lista de definiciones de tools
  - Método `call_tool()` - Ejecuta tool vía método 'tools/call'
    - Request JSON-RPC con params: {name, arguments}
    - Manejo de errores RPC (error.code, error.message)
    - Retorna resultado de ejecución
  - Autenticación Bearer token:
    - Desde config.token (directo)
    - Desde variable de entorno (config.token_env)
    - Header: Authorization: Bearer {token}
  - Cliente httpx configurado:
    - base_url desde config
    - timeout: 30.0s
    - follow_redirects: true
    - Content-Type: application/json
  - Manejo robusto de errores:
    - `MCPError` - Error base
    - `MCPConnectionError` - Errores de conexión HTTP
    - `MCPToolCallError` - Errores de ejecución
  - Context manager support (__enter__, __exit__)
  - Logging estructurado:
    - mcp.client.initialized
    - mcp.list_tools.start/success
    - mcp.call_tool.start/success
    - mcp.*.connection_error, rpc_error

**MCP Tool Adapter**:
- `src/architect/mcp/adapter.py` - Adapter de tools MCP a BaseTool
  - Clase `MCPToolAdapter` - Hereda de BaseTool
  - Naming con prefijo: `mcp_{server}_{tool}` para evitar colisiones
  - Atributos:
    - name: nombre prefijado
    - description: desde tool_definition
    - sensitive: true (MCP tools son sensibles por defecto)
    - args_model: Pydantic generado dinámicamente
  - Método `_build_args_model()` - Genera Pydantic desde JSON Schema
    - Lee inputSchema.properties
    - Lee inputSchema.required
    - Crea campos con tipos apropiados
    - Usa create_model() de Pydantic
    - Campos opcionales: tipo | None con default None
    - Campos requeridos: tipo con ... (ellipsis)
  - Método `_json_schema_type_to_python()` - Mapeo de tipos:
    - string → str
    - integer → int
    - number → float
    - boolean → bool
    - array → list
    - object → dict
  - Método `execute()` - Ejecuta vía MCPClient
    - Delega a client.call_tool()
    - Extrae contenido con _extract_content()
    - Manejo de errores sin excepciones (ToolResult)
  - Método `_extract_content()` - Extracción robusta de resultados
    - Soporte para content como list (múltiples bloques)
    - Soporte para content como string
    - Soporte para content como dict
    - Fallbacks: output, result, JSON dump completo
    - Concatenación de bloques de texto

**Descubrimiento MCP**:
- `src/architect/mcp/discovery.py` - Sistema de descubrimiento automático
  - Clase `MCPDiscovery` - Descubridor y registrador
  - Método `discover_and_register()` - Proceso completo:
    - Itera sobre lista de MCPServerConfig
    - Para cada servidor:
      1. Crea MCPClient
      2. Lista tools con client.list_tools()
      3. Para cada tool: crea MCPToolAdapter y registra
      4. Si error: log warning y continúa (no rompe)
    - Retorna estadísticas:
      - servers_total, servers_success, servers_failed
      - tools_discovered, tools_registered
      - errors: lista de mensajes de error
  - Método `discover_server_info()` - Info sin registrar (diagnóstico)
    - Conecta y lista tools
    - Retorna dict con info: connected, tools_count, tools, error
    - Útil para testing y troubleshooting
  - Logging estructurado:
    - mcp.discovery.start/complete
    - mcp.discovery.server_start
    - mcp.discovery.tools_found
    - mcp.discovery.tool_registered
    - mcp.discovery.server_failed

**Testing**:
- `scripts/test_phase4.py` - Suite completa de pruebas MCP
  - Prueba 1: MCPClient directo
    - Conecta a servidor (localhost:3000)
    - Lista tools
    - Ejecuta una tool
  - Prueba 2: MCPDiscovery
    - Descubre de múltiples servidores
    - Muestra estadísticas
    - Lista tools en registry
  - Prueba 3: MCPToolAdapter
    - Crea adapter con tool definition mock
    - Verifica modelo de argumentos
    - Verifica schema para LLM
  - Prueba 4: Server info
    - Obtiene info sin registrar
    - Muestra connected, tools, error
  - Notas sobre cómo configurar servidor MCP real

**Integración CLI**:
- `src/architect/cli.py` - CLI actualizado con MCP
  - Import de MCPDiscovery
  - Descubrimiento automático después de filesystem tools:
    - Solo si NOT --disable-mcp
    - Solo si config.mcp.servers no vacío
    - Muestra mensaje: "🔌 Descubriendo tools MCP..."
    - Muestra resultado:
      - "✓ X tools MCP registradas desde Y servidor(es)"
      - "⚠️ Z servidor(es) no disponible(s)" (warning, no error)
  - Sistema gracefully degraded:
    - Si MCP falla, continúa con tools locales
    - No rompe la ejecución
  - Versión actualizada a v0.5.0

- `src/architect/mcp/__init__.py` - Exports completos

#### Características Implementadas

- ✅ Cliente MCP completo con JSON-RPC 2.0
- ✅ Autenticación Bearer token (directo o env var)
- ✅ Adapter que hace tools MCP indistinguibles de locales
- ✅ Generación dinámica de Pydantic desde JSON Schema
- ✅ Descubrimiento automático multi-servidor
- ✅ Estadísticas detalladas de descubrimiento
- ✅ Manejo robusto de errores (nunca rompe)
- ✅ Graceful degradation (funciona sin MCP)
- ✅ Logging estructurado completo
- ✅ Support para --disable-mcp flag

#### Mejoras

- 🔄 Sistema extensible con tools remotas
- 🔄 Tools MCP tratadas idénticamente a locales
- 🔄 Naming prefijado evita colisiones
- 🔄 Continúa funcionando si servidores MCP no disponibles

#### Uso

```yaml
# config.yaml
mcp:
  servers:
    - name: github
      url: http://localhost:3000
      token_env: GITHUB_MCP_TOKEN

    - name: database
      url: https://mcp.example.com/db
      token: hardcoded-token  # No recomendado
```

```bash
# Uso automático (tools MCP disponibles para agentes)
architect run "usa la tool X del servidor github" --mode yolo

# Deshabilitar MCP
architect run "tarea normal" --disable-mcp
```

#### Notas Técnicas

- JSON-RPC 2.0 estricto (jsonrpc: "2.0", id, method, params)
- Tools MCP son sensitive=true por defecto (operaciones remotas)
- Adapter crea Pydantic models dinámicos (validación automática)
- Descubrimiento es fail-safe (logs + continúa)
- Cliente HTTP con httpx (async-ready para futuro)

#### Próxima Fase

F5 - Logging Completo (Día 8-9)

---

## [0.4.0] - 2026-02-18

### Fase 3 - Sistema de Agentes ✅

#### Agregado

**Prompts de Agentes**:
- `src/architect/agents/prompts.py` - System prompts especializados por agente
  - `PLAN_PROMPT` - Agente de planificación y análisis
    - Enfoque en descomposición de tareas
    - Identificación de archivos y pasos
    - Formato estructurado: resumen, pasos, archivos, consideraciones
  - `BUILD_PROMPT` - Agente de construcción y modificación
    - Flujo incremental: leer → modificar → verificar
    - Énfasis en cambios conservadores
    - Verificación post-modificación
  - `RESUME_PROMPT` - Agente de análisis y resumen
    - Solo lectura (no modificación)
    - Análisis estructurado de proyectos
    - Output organizado con bullet points
  - `REVIEW_PROMPT` - Agente de revisión de código
    - Feedback constructivo y accionable
    - Priorización de problemas (crítico/importante/menor)
    - Aspectos: bugs, seguridad, performance, código limpio
  - `DEFAULT_PROMPTS` - Dict mapeando nombres a prompts

**Agent Registry**:
- `src/architect/agents/registry.py` - Sistema de gestión de agentes
  - `DEFAULT_AGENTS` - Dict con 4 agentes pre-configurados:
    - plan: confirm-all, read-only, 10 steps
    - build: confirm-sensitive, full access, 20 steps
    - resume: yolo, read-only, 10 steps
    - review: yolo, read-only, 15 steps
  - Función `get_agent()` - Resolución con merge multi-fuente
    - Precedencia: defaults → YAML → CLI overrides
    - Merge selectivo (solo campos especificados)
    - Validación con AgentNotFoundError descriptivo
  - Función `list_available_agents()` - Lista defaults + YAML
  - Función `resolve_agents_from_yaml()` - Convierte y valida YAML
  - Función `_merge_agent_config()` - Merge inteligente de configs
  - Función `_apply_cli_overrides()` - Aplica --mode y --max-steps
  - Clase `AgentNotFoundError` - Error con agentes disponibles

**Mixed Mode Runner**:
- `src/architect/core/mixed_mode.py` - Modo plan → build automático
  - Clase `MixedModeRunner` - Orquestador de flujo dual
  - Método `run()` - Ejecuta flujo completo:
    1. Fase plan: analiza tarea con agente plan
    2. Si plan falla → retorna estado de plan
    3. Fase build: ejecuta con prompt enriquecido
  - Método `_build_enriched_prompt()` - Construye contexto con plan
  - Prompt enriquecido incluye:
    - Petición original del usuario
    - Plan generado (completo)
    - Instrucciones para seguir el plan
  - Logging estructurado de ambas fases:
    - mixed_mode.start/complete
    - mixed_mode.phase.plan/build
    - mixed_mode.plan_complete
  - Manejo de plan sin output (fallback)

**Testing**:
- `scripts/test_phase3.py` - Suite completa de pruebas
  - Prueba 1: Registry de agentes (sin API key)
    - Lista DEFAULT_AGENTS
    - Prueba list_available_agents()
    - Prueba get_agent()
  - Prueba 2: Single agent mode con 'review'
    - Configuración completa
    - Ejecución con prompt real
    - Requiere API key
  - Prueba 3: Mixed mode plan→build
    - Configuración de ambos agentes
    - Dry-run habilitado
    - Flujo completo
    - Requiere API key

**Integración CLI**:
- `src/architect/cli.py` - CLI actualizado con sistema completo
  - Import de módulo agents (DEFAULT_AGENTS, get_agent, etc.)
  - Detección automática de mixed mode (sin --agent)
  - Flujo diferenciado:
    - Mixed mode: crea plan_engine + build_engine, ejecuta MixedModeRunner
    - Single agent: crea engine + loop, ejecuta AgentLoop
  - Selección de agente con validación:
    - get_agent() con manejo de AgentNotFoundError
    - Mensaje de error con lista de agentes disponibles
  - CLI overrides aplicados a agentes:
    - --mode → confirm_mode
    - --max-steps → max_steps
  - Output diferenciado:
    - Mixed mode: "🔀 Modo: mixto (plan → build)"
    - Single agent: "🎭 Agente: {nombre}"
  - Versión actualizada a v0.4.0

- `src/architect/agents/__init__.py` - Exports completos
- `src/architect/core/__init__.py` - Export de MixedModeRunner

#### Características Implementadas

- ✅ 4 agentes especializados pre-configurados
- ✅ Sistema de prompts especializados por rol
- ✅ Registry con merge multi-fuente (defaults → YAML → CLI)
- ✅ Mixed mode automático plan→build
- ✅ CLI con detección automática de modo
- ✅ Validación de agentes con mensajes útiles
- ✅ Soporte completo para agentes custom en YAML
- ✅ CLI overrides funcionando (--mode, --max-steps)

#### Mejoras

- 🔄 CLI ahora tiene comportamiento inteligente por defecto (mixed mode)
- 🔄 Agentes especializados para diferentes casos de uso
- 🔄 Sistema extensible para agentes custom
- 🔄 Merge selectivo permite sobrescribir solo lo necesario

#### Uso

```bash
# Modo mixto automático (plan → build)
architect run "refactoriza el módulo de config"

# Agente específico
architect run "analiza este proyecto" -a review
architect run "lee y resume main.py" -a resume
architect run "modifica config.yaml" -a build --mode yolo

# Override de configuración
architect run "tarea compleja" -a build --max-steps 30

# Con agente custom desde YAML
architect run "deploy a producción" -a deploy
```

#### Notas Técnicas

- Prompts diseñados para ser claros, directivos y especializados
- Mixed mode enriquece el prompt de build con el plan completo
- Registry permite defaults + YAML + CLI sin conflictos
- Agentes custom pueden sobrescribir defaults parcialmente
- Logging diferenciado entre mixed mode y single agent

#### Próxima Fase

F4 - MCP Connector (Día 6-8)

---

## [0.3.0] - 2026-02-18

### Fase 2 - LLM Adapter + Agent Loop ✅

#### Agregado

**LLM Adapter:**
- `src/architect/llm/adapter.py` - Adapter completo para LiteLLM
  - `LLMAdapter` - Clase principal con configuración y retries
  - `LLMResponse` (Pydantic) - Respuesta normalizada del LLM
  - `ToolCall` (Pydantic) - Representación de tool calls
  - Configuración automática de LiteLLM (mode: direct/proxy)
  - Gestión de API keys desde variables de entorno
  - Retries automáticos con tenacity (exponential backoff)
  - 3 intentos máximo (1 original + 2 retries)
  - Wait times: mín 2s, máx 30s, multiplicador 1
  - Normalización de respuestas de cualquier proveedor a formato interno
  - Soporte completo para OpenAI function/tool calling
  - Parsing robusto de argumentos (JSON string o dict)
  - Logging estructurado de todas las operaciones
  - Supresión de debug info de LiteLLM
  - Manejo de timeout configurable

- `src/architect/llm/__init__.py` - Exports del módulo LLM

**Agent State:**
- `src/architect/core/state.py` - Estructuras de datos inmutables
  - `AgentState` (dataclass) - Estado mutable del agente
    - messages: historial completo de mensajes
    - steps: lista de StepResult ejecutados
    - status: running | success | partial | failed
    - final_output: respuesta final del agente
    - Propiedades: current_step, total_tool_calls, is_finished
    - Método to_output_dict() para serialización JSON
  - `StepResult` (dataclass frozen) - Resultado inmutable de un step
    - step_number, llm_response, tool_calls_made, timestamp
  - `ToolCallResult` (dataclass frozen) - Resultado de tool call
    - tool_name, args, result, was_confirmed, was_dry_run, timestamp

**Context Builder:**
- `src/architect/core/context.py` - Constructor de mensajes para LLM
  - `ContextBuilder` - Clase para construir contexto OpenAI
  - Método `build_initial()` - Crea mensajes iniciales (system + user)
  - Método `append_tool_results()` - Añade resultados de tools
    - Formato correcto OpenAI: assistant message con tool_calls
    - Seguido de tool messages con resultados
    - IDs de tool calls correctamente mapeados
  - Método `append_assistant_message()` - Añade respuesta del assistant
  - Método `append_user_message()` - Añade mensaje del usuario
  - Soporte para dry-run en mensajes de tools
  - Serialización correcta de argumentos a JSON

**Agent Loop:**
- `src/architect/core/loop.py` - Ciclo principal del agente
  - `AgentLoop` - Clase principal del loop
  - Método `run()` - Ejecuta el ciclo completo:
    1. Enviar mensajes al LLM con tools disponibles
    2. Recibir respuesta (content o tool_calls)
    3. Si hay tool_calls, ejecutarlas todas
    4. Añadir resultados a mensajes
    5. Repetir hasta terminar o alcanzar max_steps
  - Detección de terminación correcta (finish_reason="stop" sin tool_calls)
  - Ejecución de múltiples tool calls en un solo step
  - Manejo de errores del LLM (status=failed)
  - Manejo de límite de pasos (status=partial)
  - Manejo de finish_reason="length" (continuar)
  - Logging estructurado de cada paso:
    - agent.loop.start/complete
    - agent.step.start
    - agent.tool_calls_received
    - agent.tool_call.execute/complete
    - agent.complete
    - agent.max_steps_reached
  - Sanitización de argumentos largos para logs
  - Integración completa con LLMAdapter y ExecutionEngine

- `src/architect/core/__init__.py` - Exports del módulo core

**Testing:**
- `scripts/test_phase2.py` - Script de prueba del agent loop completo
  - Configura LLMAdapter con modelo económico (gpt-4o-mini)
  - Crea agente simple con read_file y list_files
  - Ejecuta tarea: listar .md y leer README.md
  - Muestra resultados detallados con steps y tool calls
  - Requiere API key configurada (LITELLM_API_KEY)

**Integración CLI:**
- `src/architect/cli.py` - CLI actualizado con agent loop funcional
  - Import de todos los módulos necesarios (core, llm, execution, tools, logging)
  - Configuración de logging en cada ejecución
  - Creación de agente simple por defecto (TODO: fase 3 para agentes configurables)
  - System prompt por defecto razonable
  - allowed_tools: read_file, write_file, list_files, delete_file
  - Inicialización de tool registry con filesystem tools
  - Creación de ExecutionEngine con confirm_mode del CLI
  - Configuración de dry-run si está habilitado
  - Creación de LLMAdapter con configuración cargada
  - Creación de ContextBuilder y AgentLoop
  - Ejecución completa del agent loop con run()
  - Output formateado:
    - Header con info de configuración
    - Resultado final del agente
    - Estadísticas (status, steps, tool_calls)
  - Soporte para --json output
  - Códigos de salida correctos: 0 (success), 1 (failed), 2 (partial)

#### Características Implementadas

- ✅ LLMAdapter completo con LiteLLM y retries
- ✅ Normalización de respuestas multi-provider
- ✅ Agent state inmutable para debugging
- ✅ Context builder con formato OpenAI correcto
- ✅ Agent loop completo y funcional
- ✅ Manejo robusto de errores en todos los niveles
- ✅ Integración completa con ExecutionEngine de Fase 1
- ✅ CLI funcional end-to-end
- ✅ Logging estructurado completo
- ✅ Soporte para dry-run
- ✅ Códigos de salida apropiados

#### Mejoras

- 🔄 CLI ahora ejecuta tareas reales (antes solo mostraba config)
- 🔄 Sistema completamente funcional end-to-end
- 🔄 Manejo de múltiples tool calls por step
- 🔄 Detección inteligente de terminación

#### Notas Técnicas

- Formato OpenAI usado para tool calling (compatible con todos los providers via LiteLLM)
- Agent state es parcialmente inmutable (steps y results son frozen, state es mutable)
- Retries configurables via tenacity con backoff exponencial
- Logging estructurado en todos los componentes
- Streaming se implementará en Fase 6

#### Próxima Fase

F3 - Sistema de Agentes (Día 5-6)

---

## [0.2.0] - 2026-02-18

### Fase 1 - Tools y Execution Engine ✅

#### Agregado

**Sistema de Tools:**
- `src/architect/tools/base.py` - Clase base abstracta para todas las tools
  - `BaseTool` (ABC) con métodos: execute(), get_schema(), validate_args()
  - `ToolResult` (Pydantic) para resultados estructurados (success, output, error)
  - Generación automática de JSON Schema compatible con OpenAI function calling
  - Sistema de marcado de tools sensibles (sensitive=True/False)

- `src/architect/tools/schemas.py` - Modelos Pydantic para argumentos de tools
  - `ReadFileArgs` - Path del archivo a leer
  - `WriteFileArgs` - Path, content, mode (overwrite/append)
  - `DeleteFileArgs` - Path del archivo a eliminar
  - `ListFilesArgs` - Path, pattern (glob), recursive
  - Validación automática y mensajes de error claros

- `src/architect/tools/filesystem.py` - Tools para operaciones del filesystem
  - `ReadFileTool` - Lee archivos UTF-8 con validación de path
  - `WriteFileTool` - Escribe archivos (overwrite/append), crea directorios padres
  - `DeleteFileTool` - Elimina archivos, requiere allow_delete=true
  - `ListFilesTool` - Lista archivos/directorios, soporta glob y recursión
  - Todas las tools con manejo robusto de errores (nunca lanzan excepciones)
  - Mensajes de error descriptivos y accionables

- `src/architect/tools/registry.py` - Registro centralizado de tools
  - `ToolRegistry` - Clase para gestionar todas las tools disponibles
  - Métodos: register(), get(), list_all(), get_schemas(), filter_by_names()
  - Detección de duplicados con DuplicateToolError
  - Mensajes de error con sugerencias de tools disponibles
  - Generación de schemas filtrados por allowed_tools

- `src/architect/tools/setup.py` - Helpers para inicialización
  - `register_filesystem_tools()` - Registra todas las tools del filesystem
  - Configuración automática basada en WorkspaceConfig

**Sistema de Validación y Seguridad:**
- `src/architect/execution/validators.py` - Validadores críticos de seguridad
  - `validate_path()` - Prevención de path traversal (../../etc/passwd)
  - Usa Path.resolve() para resolver symlinks y paths relativos
  - Verifica confinamiento al workspace con is_relative_to()
  - `validate_file_exists()` - Verifica existencia de archivos
  - `validate_directory_exists()` - Verifica existencia de directorios
  - `ensure_parent_directory()` - Crea directorios padres automáticamente
  - Excepciones: PathTraversalError, ValidationError con mensajes claros

**Sistema de Políticas de Confirmación:**
- `src/architect/execution/policies.py` - Políticas de confirmación de acciones
  - `ConfirmationPolicy` - Tres modos: yolo, confirm-all, confirm-sensitive
  - Método `should_confirm()` - Determina si requiere confirmación
  - Método `request_confirmation()` - Prompt interactivo al usuario
  - Detección de TTY para entornos headless (CI, cron, pipelines)
  - `NoTTYError` con mensaje claro y soluciones para CI/CD
  - Prompts con opciones: y (sí), n (no), a (abortar todo)
  - Sanitización de argumentos largos para mostrar al usuario
  - Soporte para dry-run (skip confirmación en simulaciones)

**Execution Engine:**
- `src/architect/execution/engine.py` - Motor central de ejecución de tools
  - `ExecutionEngine` - Orquestador con pipeline completo:
    1. Buscar tool en registry
    2. Validar argumentos con Pydantic
    3. Aplicar política de confirmación
    4. Ejecutar (o simular en dry-run)
    5. Loggear resultado con structlog
    6. Retornar ToolResult (nunca excepciones)
  - Método `execute_tool_call()` - Ejecución con manejo robusto de errores
  - Método `set_dry_run()` - Habilitar/deshabilitar simulación
  - Integración completa con ToolRegistry y ConfirmationPolicy
  - Logging estructurado de todas las operaciones
  - Sanitización de argumentos largos para logs
  - Captura defensiva de excepciones inesperadas

**Sistema de Logging:**
- `src/architect/logging/setup.py` - Configuración básica de structlog
  - `configure_logging_basic()` - Setup mínimo para desarrollo
  - Procesadores: contextvars, log_level, timestamp, console_renderer
  - Output a stderr (no rompe pipes)
  - Base para logging completo de Fase 5

**Testing y Validación:**
- `scripts/test_phase1.py` - Script de prueba completo de Fase 1
  - Prueba de ToolRegistry y registro de tools
  - Prueba de ExecutionEngine con modo yolo
  - Prueba de list_files con patrones glob
  - Prueba de read_file con archivo real
  - Prueba de dry-run mode
  - Prueba de validación de path traversal (seguridad)
  - Prueba de delete sin allow_delete
  - Prueba de generación de schemas para LLM
  - Output formateado y legible

**Exports y Módulos:**
- `src/architect/tools/__init__.py` - Exports completos del módulo tools
- `src/architect/execution/__init__.py` - Exports completos del módulo execution
- `src/architect/logging/__init__.py` - Exports del módulo logging

#### Características Implementadas

- ✅ Sistema completo de tools con 4 tools del filesystem
- ✅ ToolRegistry con gestión, filtrado y generación de schemas
- ✅ Validación robusta de paths con prevención de path traversal
- ✅ Políticas de confirmación configurables (yolo/confirm-all/confirm-sensitive)
- ✅ ExecutionEngine con pipeline completo y manejo de errores
- ✅ Soporte para dry-run (simulación sin efectos secundarios)
- ✅ Detección de entornos headless con mensajes claros
- ✅ Logging estructurado con structlog
- ✅ Integración completa entre todos los componentes
- ✅ Script de prueba funcional

#### Seguridad

- 🔒 Validación estricta de paths con Path.resolve()
- 🔒 Prevención de path traversal attacks
- 🔒 Confinamiento obligatorio al workspace
- 🔒 Tools sensibles requieren confirmación (configurable)
- 🔒 delete_file requiere allow_delete=true explícito
- 🔒 Manejo defensivo de excepciones (nunca crash)

#### Próxima Fase

F2 - LLM Adapter + Agent Loop (Día 3-5)

---

## [0.1.0] - 2026-02-18

### Fase 0 - Scaffolding y Configuración ✅

#### Agregado

**Infraestructura del Proyecto:**
- `pyproject.toml` - Configuración del proyecto usando hatchling como build backend
  - Dependencias: click, pyyaml, pydantic, litellm, httpx, structlog, tenacity
  - Scripts: comando `architect` disponible globalmente
  - Requerimiento: Python >=3.12
  - Dependencias opcionales de desarrollo (pytest, black, ruff, mypy)

**Sistema de Configuración:**
- `src/architect/config/schema.py` - Modelos Pydantic v2 para validación de configuración
  - `LLMConfig` - Configuración del proveedor LLM (modelo, API, timeouts, retries)
  - `AgentConfig` - Configuración de agentes (system prompt, tools, confirm_mode, max_steps)
  - `LoggingConfig` - Configuración de logging (level, file, verbose)
  - `WorkspaceConfig` - Configuración del workspace (root, allow_delete)
  - `MCPConfig` y `MCPServerConfig` - Configuración de servidores MCP
  - `AppConfig` - Configuración raíz que combina todas las secciones

- `src/architect/config/loader.py` - Cargador de configuración con deep merge
  - Función `deep_merge()` para merge recursivo de diccionarios
  - Función `load_yaml_config()` para cargar archivos YAML
  - Función `load_env_overrides()` para variables de entorno (ARCHITECT_*)
  - Función `apply_cli_overrides()` para argumentos CLI
  - Función `load_config()` - Pipeline completo: defaults → YAML → env → CLI → validación
  - Orden de precedencia correctamente implementado

- `src/architect/config/__init__.py` - Exports del módulo de configuración

**CLI (Command Line Interface):**
- `src/architect/cli.py` - CLI principal usando Click
  - Grupo principal `architect` con version option
  - Comando `run` con 20+ opciones configurables:
    - Configuración: `-c/--config`, `-a/--agent`, `-m/--mode`, `-w/--workspace`
    - Ejecución: `--dry-run`
    - LLM: `--model`, `--api-base`, `--api-key`, `--no-stream`, `--timeout`
    - MCP: `--mcp-config`, `--disable-mcp`
    - Logging: `-v/--verbose`, `--log-level`, `--log-file`
    - Output: `--json`, `--quiet`, `--max-steps`
  - Comando `validate-config` para validar archivos de configuración
  - Manejo de errores con códigos de salida apropiados
  - Soporte para salida JSON estructurada
  - Modo verbose para debugging

- `src/architect/__init__.py` - Inicialización del paquete con `__version__`
- `src/architect/__main__.py` - Entry point para `python -m architect`

**Documentación y Ejemplos:**
- `config.example.yaml` - Archivo de ejemplo completo con:
  - Configuración de LLM con múltiples ejemplos de modelos
  - Ejemplos de agentes custom (deploy, documenter)
  - Configuración de logging y workspace
  - Ejemplos de servidores MCP
  - Comentarios extensivos explicando cada sección
  - Notas sobre precedencia de configuración

**Estructura del Proyecto:**
- Estructura completa de directorios creada:
  - `src/architect/` - Código fuente principal
  - `src/architect/config/` - Sistema de configuración
  - `src/architect/agents/` - Sistema de agentes (preparado)
  - `src/architect/core/` - Agent loop y estado (preparado)
  - `src/architect/llm/` - Adapter de LLM (preparado)
  - `src/architect/tools/` - Tools del sistema (preparado)
  - `src/architect/mcp/` - Cliente MCP (preparado)
  - `src/architect/execution/` - Execution engine (preparado)
  - `src/architect/logging/` - Sistema de logging (preparado)
  - `tests/` - Tests (estructura preparada)
  - `scripts/` - Scripts auxiliares

**Control de Versiones:**
- `.gitignore` - Configuración completa para Python, IDEs, logs, config sensibles

**Seguimiento:**
- `SEGUIMIENTO.md` - Documento de seguimiento de implementación por fases
- `CHANGELOG.md` - Este archivo para documentar cambios

#### Características Implementadas

- ✅ Sistema de configuración completo con validación Pydantic
- ✅ Deep merge de configuración (YAML + env + CLI)
- ✅ CLI funcional con Click y 20+ opciones
- ✅ Estructura modular preparada para todas las fases
- ✅ Documentación inline completa
- ✅ Type hints en todo el código
- ✅ Manejo de errores con códigos de salida apropiados

#### Notas Técnicas

- Arquitectura sync-first según plan (async solo donde sea necesario)
- No se usa LangChain/LangGraph (según decisión técnica del plan)
- Pydantic v2 con `extra="forbid"` para validación estricta
- Python 3.12+ requerido (pattern matching, typing moderno, tomllib nativo)

#### Próxima Fase

F1 - Tools y Execution Engine (Día 2-3)
