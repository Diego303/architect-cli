# Seguimiento de Implementación - architect CLI

Este documento resume todo lo implementado en el proyecto architect CLI.

Para el historial detallado de cada fase y tarea individual, consultar `SEGUIMIENTO.md` (archivo histórico).

---

## Release v1.1.0 — 2026-02-28

### Guardrails: `sensitive_files` — Protección de lectura y escritura

Se detectó un gap de seguridad: `protected_files` bloqueaba escritura/edición/borrado pero permitía al agente **leer** archivos sensibles como `.env`, `*.pem`, `*.key`. Esto exponía secrets al proveedor de LLM.

**Solución**: Nuevo campo `sensitive_files` que bloquea **toda** acción (lectura + escritura), manteniendo `protected_files` solo para escritura (backward compatible).

| Cambio | Archivo |
|--------|---------|
| Campo `sensitive_files: list[str]` + auto-enable en `model_post_init` | `src/architect/config/schema.py` |
| `check_file_access()` diferencia read/write via `action`. Nuevo `_extract_read_targets()` para shell reads | `src/architect/core/guardrails.py` |
| `read_file` añadido a guardrails check | `src/architect/execution/engine.py` |
| 30 tests nuevos (TestSensitiveFiles, TestExtractReadTargets, schema) | `tests/test_guardrails/test_guardrails.py` |

### Reports: Inferencia de formato por extensión de archivo

`--report-file report.md` sin `--report` no generaba reporte porque la lógica estaba condicionada a `if report_format:`.

**Solución**: `_infer_report_format()` infiere el formato de la extensión (`.json` → json, `.md` → markdown, `.html` → github, default: markdown). Aplicado en los 3 comandos: `run`, `loop`, `pipeline`.

### Reports: Creación automática de directorios para `--report-file`

`--report-file reports/ralph-run.json` crasheaba con `FileNotFoundError` si el directorio `reports/` no existía.

**Solución**: `_write_report_file()` centraliza la escritura en los 4 puntos (`run`, `loop`, `pipeline`, `eval`) con estrategia de fallback: (1) crear directorios padres y escribir, (2) si falla → escribir en directorio actual, (3) si ambos fallan → notificar al usuario sin crashear.

| Cambio | Archivo |
|--------|---------|
| Helper `_infer_report_format()` + inferencia en 3 puntos de generación | `src/architect/cli.py` |
| Helper `_write_report_file()` + reemplazo de 4 `Path.write_text()` directos | `src/architect/cli.py` |
| 13 tests nuevos (TestInferReportFormat + TestWriteReportFile) | `tests/test_reports/test_reports.py` |

### Pipelines: Validación estricta de YAML antes de ejecutar

Un pipeline YAML con campos incorrectos (ej: `task:` en vez de `prompt:`) se lanzaba sin error, ejecutando steps con prompts vacíos que consumían tokens sin resultado útil.

**Solución**: Validación completa del YAML antes de ejecutar con `_validate_steps()`:
- `prompt` requerido y no vacío en cada step
- Campos desconocidos rechazados (con hint: `task` → "¿quisiste decir `prompt`?")
- Al menos 1 step definido
- Entradas non-dict rechazadas
- Todos los errores recopilados en un solo mensaje

| Cambio | Archivo |
|--------|---------|
| `PipelineValidationError` + `_VALID_STEP_FIELDS` + `_validate_steps()` | `src/architect/features/pipelines.py` |
| CLI captura `PipelineValidationError` → exit code 3 sin traceback | `src/architect/cli.py` |
| 9 tests nuevos (TestPipelineYamlValidation) | `tests/test_pipelines/test_pipelines.py` |

### HUMAN Logging: Trazabilidad visual para features de alto nivel

Las features de ejecución de alto nivel (pipelines, ralph loop, auto-review, parallel, competitive eval) solo emitían logs técnicos de structlog. El usuario no tenía visibilidad clara de qué paso/iteración/worker estaba ejecutándose.

**Solución**: 14 eventos HUMAN-level (nivel 25) emitidos desde cada feature vía stdlib `logging.getLogger()` con dict msgs, formateados por `HumanFormatter` y mostrados en stderr con iconos y barras separadoras.

| Feature | Eventos | Ejemplo visual |
|---------|---------|---------------|
| Pipelines | `step_start`, `step_skipped`, `step_done` | `━ Pipeline step 1/3: build (agent: build) ━━━` |
| Ralph Loop | `iteration_start`, `checks_result`, `iteration_done`, `complete` | `━ Ralph iteration 1/5 (check: pytest) ━━━` / `🧪 Checks: 3/5 passed` |
| Auto-Reviewer | `start`, `complete` | `━ Auto-Review (142 líneas de diff) ━━━` / `✓ Review completo: aprobado` |
| Parallel Runs | `worker_done`, `worker_error`, `complete` | `✓ Worker 1 (gpt-4.1) → success ($0.04, 120s)` |
| Competitive Eval | `model_done`, `ranking` | `🏆 gpt-4.1: #1 (score: 85, 5/5 checks)` / `🏁 Ranking final: A > B > C` |

| Cambio | Archivo |
|--------|---------|
| 3 eventos HUMAN + `_hlog` stdlib logger | `src/architect/features/pipelines.py` |
| 4 eventos HUMAN + `_hlog` stdlib logger | `src/architect/features/ralph.py` |
| 2 eventos HUMAN + `_hlog` stdlib logger | `src/architect/agents/reviewer.py` |
| 3 eventos HUMAN + `_hlog` stdlib logger | `src/architect/features/parallel.py` |
| 2 eventos HUMAN + `_hlog` stdlib logger | `src/architect/features/competitive.py` |
| 14 case handlers en `HumanFormatter` + 11 métodos en `HumanLog` | `src/architect/logging/human.py` |
| 56 tests nuevos (integration + formatter + HumanLog por feature) | `tests/test_pipelines/`, `test_ralph/`, `test_reviewer/`, `test_parallel/`, `test_competitive/` |

**Tests**: 795 passed, 9 skipped, 0 failures. 31 E2E checks pasando.

---

## Release v1.0.1 — 2026-02-26

Correcciones de errores encontrados en tests y errores generales post-release v1.0.0. Traducciones y documentos de LICENCIA y SEGURIDAD.

---

## Release v1.0.0 — 2026-02-24

**Primera versión estable** de architect CLI. Culminación de 4 fases de desarrollo (Plan V4: A, B, C, D) sobre la base del core v3, resultando en una herramienta CLI completa para orquestar agentes de IA sobre código local.

---

## Resumen de fases implementadas

### Core (F0-F14 + v3 M1-M6) — v0.9.0 a v0.15.3

Fundación completa del agente: scaffolding, tools del filesystem, execution engine, agentes y prompts, adaptador LLM con LiteLLM, indexer del repositorio, context management, auto-evaluación, `run_command` con 4 capas de seguridad, cost tracking con prompt caching, loop `while True` con safety nets y cierre limpio, human logging con iconos.

| Fase | Descripción | Versión |
|------|-------------|---------|
| F0 | Scaffolding, config Pydantic, CLI Click | v0.9.0 |
| F1 | Tools filesystem, ToolRegistry, ExecutionEngine, path validation | v0.9.0 |
| F2 | `edit_file` (str-replace), `apply_patch` (unified diff) | v0.9.0 |
| F3 | Agentes (plan/build/resume/review), system prompts, registry | v0.9.0 |
| F4 | LLMAdapter con LiteLLM, retries selectivos | v0.9.0 |
| F5 | AgentLoop básico, function calling | v0.9.0 |
| F6 | CLI completa con Click | v0.9.0 |
| F7 | RepoIndexer, árbol en system prompt | v0.10.0 |
| F8 | `search_code`, `grep`, `find_files` | v0.10.0 |
| F9 | Context management: truncado, compresión LLM, hard limit | v0.11.0 |
| F10 | Parallel tool calls | v0.11.0 |
| F11 | Self-evaluation: `--self-eval basic/full` | v0.12.0 |
| F12 | `run_command`: blocklist + clasificación dinámica + confinamiento | v0.13.0 |
| F13 | Clasificación safe/dev/dangerous para confirmaciones | v0.13.0 |
| F14 | CostTracker, `--budget`, prompt caching, LocalLLMCache | v0.14.0 |
| v3-M1 | `while True` loop, LLM decide parada | v0.15.0 |
| v3-M2 | Safety nets: max_steps, budget, timeout, context_full | v0.15.0 |
| v3-M3 | Graceful close: última LLM call sin tools | v0.15.0 |
| v3-M4 | PostEditHooks (post-edición auto-verificación) | v0.15.0 |
| v3-M5 | Human logging: HUMAN level, iconos, MCP distinción | v0.15.2 |
| v3-M6 | StopReason, ContextManager.manage(), pipeline structlog fix | v0.15.3 |

### Phase A — Seguridad y Extensibilidad (v0.16.x)

| Tarea | Descripción |
|-------|-------------|
| A1 — Hooks Lifecycle | 10 eventos (pre/post tool, pre/post LLM, session, agent, error, budget, context), exit code protocol (0=allow, 2=block), variables de entorno, backward compatible con `post_edit` |
| A2 — Guardrails | Archivos protegidos (write-only), archivos sensibles (read+write, v1.1.0), comandos bloqueados, límites de edición, code_rules (warn/block), quality gates post-build |
| A3 — Skills Ecosystem | `.architect.md` auto-cargado, skills por glob en `.architect/skills/`, `SKILL.md` con frontmatter, install desde GitHub |
| A4 — Memoria Procedural | Detección de correcciones del usuario, persistencia en `.architect/memory.md`, inyección en system prompt |
| QA1 | 228 verificaciones, 5 bugs corregidos |
| QA2 | `--show-costs` con streaming, `--mode yolo` sin confirmaciones, `--timeout` como watchdog, MCP auto-inject |

**Tests**: 116 tests unitarios en `tests/test_hooks/`, `tests/test_guardrails/`, `tests/test_skills/`, `tests/test_memory/`

### Phase B — Operaciones y CI/CD (v0.17.0)

| Tarea | Descripción |
|-------|-------------|
| B1 — Sessions | `SessionState` + `SessionManager`. Comandos: `architect sessions`, `architect resume`, `architect cleanup` |
| B2 — Reports | `ReportGenerator` multi-formato: JSON, Markdown, GitHub PR. Flags: `--report`, `--report-file` |
| B3 — CI/CD Flags | `--context-git-diff`, `--session`, `--confirm-mode`, `--exit-code-on-partial`, `--dry-run` |
| B4 — Dry Run | `DryRunTracker` integrado en AgentLoop, registro de acciones simuladas |

**Tests**: 65 tests unitarios en `tests/test_sessions/`, `tests/test_reports/`, `tests/test_dryrun/`

### Phase C — Orquestación Avanzada (v0.18.0)

| Tarea | Descripción |
|-------|-------------|
| C1 — Ralph Loop | Iteración automática hasta que checks pasen. Contexto limpio por iteración. `architect loop` |
| C2 — Parallel Runs | Ejecución en git worktrees con ProcessPoolExecutor. `architect parallel` |
| C3 — Pipeline Mode | Workflows YAML multi-step con variables `{{name}}`, condiciones, checkpoints. `architect pipeline` |
| C4 — Checkpoints | Git commits con prefijo `architect:checkpoint`, rollback. `architect rollback`, `architect history` |
| C5 — Auto-Review | Reviewer con contexto limpio (solo diff + tarea), fix-pass prompt |
| QA4 | 3 bugs corregidos (schema, CLI, tests) |

**Tests**: 311 tests unitarios + 31 E2E script checks

### Phase D — Extensiones Avanzadas (v0.19.0)

| Tarea | Descripción |
|-------|-------------|
| D1 — Dispatch Subagent | Tool `dispatch_subagent` con 3 tipos (explore/test/review), AgentLoop fresco por sub-tarea |
| D2 — Code Health Delta | `CodeHealthAnalyzer` con AST + radon, snapshots before/after, delta report. Flag `--health` |
| D3 — Competitive Eval | `CompetitiveEval` multi-modelo con ranking compuesto. `architect eval` |
| D4 — OpenTelemetry Traces | `ArchitectTracer`/`NoopTracer`, 3 exporters (otlp/console/json-file) |
| D5 — Preset Configs | `PresetManager` con 5 presets (python/node-react/ci/paranoid/yolo). `architect init` |
| QA-D | 7 bugs corregidos (BUG-1 a BUG-7), 41 tests de validación |

**Tests**: 145 tests Phase D + 41 bugfix tests

---

## Estadísticas actuales v1.1.0

| Métrica | Valor |
|---------|-------|
| **Versión** | 1.1.0 |
| **Tests unitarios** | 739 passed, 9 skipped, 0 failures |
| **E2E checks** | 31 |
| **Comandos CLI** | 15 |
| **Tools del agente** | 11+ (locales + MCP + dispatch) |
| **Agentes default** | 4 (build, plan, resume, review) |
| **Hooks lifecycle** | 10 eventos |
| **Presets** | 5 (python, node-react, ci, paranoid, yolo) |
| **Exporters telemetría** | 3 (otlp, console, json-file) |
| **Formatos de reporte** | 3 (json, markdown, github) |
| **Bugs QA corregidos** | 12+ (QA1: 5, QA2: fixes, QA4: 3, QA-D: 7) |

### Comandos CLI disponibles

```
architect run          Ejecutar tarea con agente
architect loop         Iteración automática con checks (Ralph Loop)
architect pipeline     Ejecutar workflow YAML multi-step
architect parallel     Ejecución paralela en worktrees
architect parallel-cleanup  Limpiar worktrees
architect eval         Evaluación competitiva multi-modelo
architect init         Inicializar proyecto con presets
architect sessions     Listar sesiones guardadas
architect resume       Reanudar sesión
architect cleanup      Limpiar sesiones antiguas
architect agents       Listar agentes disponibles
architect validate-config  Validar configuración
architect skill        Gestión de skills
architect rollback     Rollback a checkpoint
architect history      Listar checkpoints
```

### Estructura del proyecto

```
src/architect/
├── __init__.py            # __version__ = "1.1.0"
├── cli.py                 # Entry point — 15 comandos Click
├── core/
│   ├── loop.py            # AgentLoop — while True con safety nets
│   ├── context.py         # ContextManager — pruning y compresión
│   ├── evaluator.py       # SelfEvaluator — auto-evaluación
│   ├── state.py           # AgentState
│   ├── hooks.py           # HookExecutor — 10 eventos lifecycle
│   ├── guardrails.py      # GuardrailsEngine — seguridad determinista
│   └── health.py          # CodeHealthAnalyzer — métricas de calidad
├── agents/
│   ├── prompts.py         # System prompts por agente
│   ├── registry.py        # AgentRegistry + custom agents
│   └── reviewer.py        # AutoReviewer — review post-build
├── tools/
│   ├── base.py            # BaseTool + ToolResult
│   ├── filesystem.py      # read/write/delete/list
│   ├── editing.py         # edit_file (str-replace)
│   ├── patch.py           # apply_patch (unified diff)
│   ├── search.py          # search_code, grep, find_files
│   ├── commands.py        # run_command (4 capas seguridad)
│   ├── dispatch.py        # dispatch_subagent (explore/test/review)
│   ├── registry.py        # ToolRegistry
│   └── setup.py           # register_all_tools()
├── execution/
│   ├── engine.py          # ExecutionEngine — pipeline completo
│   ├── policies.py        # ConfirmationPolicy
│   └── validators.py      # validate_path()
├── features/
│   ├── sessions.py        # SessionManager
│   ├── report.py          # ReportGenerator (json/md/github)
│   ├── dryrun.py          # DryRunTracker
│   ├── ralph.py           # RalphLoop
│   ├── parallel.py        # ParallelRunner + worktrees
│   ├── pipelines.py       # PipelineRunner + YAML
│   └── checkpoints.py     # CheckpointManager
│   └── competitive.py     # CompetitiveEval
├── skills/
│   ├── loader.py          # SkillsLoader
│   ├── installer.py       # SkillInstaller
│   └── memory.py          # ProceduralMemory
├── config/
│   ├── schema.py          # AppConfig (Pydantic v2)
│   ├── loader.py          # ConfigLoader
│   └── presets.py          # PresetManager
├── telemetry/
│   └── otel.py            # ArchitectTracer / NoopTracer
├── costs/                 # CostTracker + precios
├── llm/                   # LLMAdapter + LocalLLMCache
├── mcp/                   # MCPClient JSON-RPC 2.0
├── indexer/               # RepoIndexer + IndexCache
└── logging/               # structlog triple pipeline
```

---

## Próximos pasos (post v1.0.0)

El Plan V4 está completo. Posibles direcciones futuras:

- **Performance**: async I/O para MCP y LLM calls, streaming optimizado
- **Testing**: tests de integración con LLM real (proxy), aumento de cobertura
- **Packaging**: publicación en PyPI, Docker image, GitHub Actions prebuilt
- **Extensiones**: más presets, marketplace de skills, plugins de terceros
- **Documentación**: sitio web con mkdocs, tutoriales, API reference

---

## Notas y decisiones de diseño

- **Stack**: Python 3.12+, Click, PyYAML, Pydantic v2, LiteLLM, httpx, structlog, tenacity
- **Sync-first**: sin asyncio en el loop principal (predecible, debuggable)
- **Sin LangChain/LangGraph**: loop directo y controlado (~300 líneas)
- **Tools nunca lanzan excepciones**: siempre retornan ToolResult
- **stdout limpio**: solo resultado final y JSON, todo lo demás a stderr
- **Guardrails antes de hooks**: seguridad determinista que el LLM no puede saltarse (`protected_files` write-only, `sensitive_files` read+write)
- **Contexto limpio**: Ralph Loop, Pipeline, Auto-Review y Sub-agentes usan AgentLoop fresco
