# Testing — Resumen completo de cobertura

Documento actualizado el 2026-02-28. Refleja el estado actual de todos los tests. Versión: v1.1.0.

> **Requisito**: Para ejecutar los tests y herramientas de calidad, instalar el extra `dev`:
> ```bash
> pip install architect-ai-cli[dev]
> ```
> Incluye: `pytest`, `pytest-cov`, `pytest-asyncio`, `black`, `ruff`, `mypy`.

## Resultado global

### Scripts de integración (`scripts/`)

| Archivo | Tests | Estado | Requiere API key |
|---|:---:|:---:|:---:|
| `test_phase1.py` | 6 | Passed | No |
| `test_phase2.py` | 7 | Passed | No |
| `test_phase3.py` | 5 | Passed | No |
| `test_phase4.py` | 3 | Passed | No |
| `test_phase5.py` | 5 | Passed | No |
| `test_phase6.py` | 4+1 skip | Passed | No (1 skip) |
| `test_phase7.py` | 11 | Passed | No |
| `test_phase8.py` | 7 | Passed | No |
| `test_phase9.py` | 24 | Passed | No |
| `test_phase10.py` | 35 | Passed | No |
| `test_phase11.py` | 9 | Passed | No |
| `test_phase12.py` | 39 | Passed | No |
| `test_phase13.py` | 54 | Passed | No |
| `test_phase14.py` | 6 | Passed | No |
| `test_v3_m1.py` | 38 | Passed | No |
| `test_v3_m2.py` | 22 | Passed | No |
| `test_v3_m3.py` | 34 | Passed | No |
| `test_v3_m4.py` | 44 | Passed | No |
| `test_v3_m5.py` | 41 | Passed | No |
| `test_v3_m6.py` | 23 | Passed | No |
| `test_phase15.py` | 29 | Passed | No |
| `test_phase16.py` | 24 | Passed | No |
| `test_phase17.py` | 31 | Passed | No |
| `test_phase18.py` | 32 | Passed | No |
| `test_phase_b.py` | ~104 checks | Passed | No |
| `test_phase_c_e2e.py` | 31 | Passed | No |
| `test_integration.py` | 54 (47+7) | 47 passed, 7 esperados | 7 requieren key |
| `test_config_loader.py` | 37 | Passed | No |
| `test_mcp_internals.py` | 47 | Passed | No |
| `test_streaming.py` | 33 | Passed | No |
| `test_parallel_execution.py` | 29 | Passed | No |
| **TOTAL scripts** | **~848** | **Passed** | **7 esperados con key** |

### Tests unitarios pytest (`tests/`)

| Directorio | Tests | Qué cubre |
|---|:---:|---|
| `tests/test_hooks/` | 29 | HookExecutor, HooksRegistry, HookEvent |
| `tests/test_guardrails/` | 71 | GuardrailsEngine, sensitive_files, protected_files, quality gates, code rules, shell read detection |
| `tests/test_skills/` | 31 | SkillsLoader, SkillInstaller |
| `tests/test_memory/` | 32 | ProceduralMemory, correction patterns |
| `tests/test_sessions/` | 22 | SessionManager, SessionState, generate_session_id |
| `tests/test_reports/` | 29 | ExecutionReport, ReportGenerator, collect_git_diff, _infer_report_format |
| `tests/test_dryrun/` | 23 | DryRunTracker, PlannedAction, WRITE_TOOLS/READ_TOOLS |
| `tests/test_ralph/` | 90 | RalphLoop, RalphConfig, LoopIteration, RalphLoopResult |
| `tests/test_pipelines/` | 83 | PipelineRunner, PipelineConfig, PipelineStep, variables, conditions |
| `tests/test_checkpoints/` | 48 | CheckpointManager, Checkpoint, create/list/rollback |
| `tests/test_reviewer/` | 47 | AutoReviewer, ReviewResult, build_fix_prompt, get_recent_diff |
| `tests/test_parallel/` | 43 | ParallelRunner, ParallelConfig, WorkerResult, worktrees |
| `tests/test_dispatch/` | 36 | DispatchSubagentTool, DispatchSubagentArgs, tipos, tools |
| `tests/test_health/` | 28 | CodeHealthAnalyzer, HealthSnapshot, HealthDelta, FunctionMetric |
| `tests/test_competitive/` | 19 | CompetitiveEval, CompetitiveConfig, CompetitiveResult, ranking |
| `tests/test_telemetry/` | 20 (9 skip) | ArchitectTracer, NoopTracer, NoopSpan, create_tracer, SERVICE_VERSION |
| `tests/test_presets/` | 37 | PresetManager, AVAILABLE_PRESETS, apply, list_presets |
| `tests/test_bugfixes/` | 41 | Validación BUG-3 a BUG-7 (code_rules, dispatch, telemetry, health, parallel) |
| **TOTAL pytest** | **717** | **Phases A + B + C + D + Bugfixes + v1.1.0** |

> Los 7 tests que fallan en `test_integration.py` son llamadas reales a la API de OpenAI (secciones 1 y 2). Fallan con `AuthenticationError` porque no hay `OPENAI_API_KEY` configurada. Es el comportamiento esperado en CI sin credenciales.

---

## Cobertura por módulo

### `src/architect/tools/` — Herramientas locales

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `filesystem.py` | `test_phase1`, `test_phase9`, `test_v3_m6`, `test_integration` | read_file, write_file, edit_file, delete_file, list_files — operaciones reales, path traversal, dry-run, modos de escritura |
| `patch.py` | `test_phase9`, `test_v3_m6` | apply_patch — single-hunk, multi-hunk, inserción pura, errores de formato, diff output |
| `search.py` | `test_phase10`, `test_v3_m6` | search_code (regex), grep (literal), find_files (glob) — case insensitive, patrones, contexto |
| `commands.py` | `test_phase13` | run_command — blocklist (capa 1), allowed_only (capa 2), timeout+truncado (capa 3), directory sandboxing (capa 4), patrones extra, comandos safe extra, clasificación de sensibilidad |

### `src/architect/core/` — Loop del agente

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `loop.py` | `test_v3_m1`, `test_parallel_execution` | AgentLoop.run(), _check_safety_nets (5 condiciones), _graceful_close (4 StopReasons), _should_parallelize, _execute_tool_calls_batch (secuencial vs paralelo, orden preservado) |
| `state.py` | `test_v3_m1`, `test_parallel_execution` | StopReason (7 miembros), AgentState, StepResult, _CLOSE_INSTRUCTIONS (4 keys), ToolCallResult |
| `context.py` | `test_v3_m2`, `test_phase11` | ContextManager — _estimate_tokens, _is_above_threshold, is_critically_full, manage(), _summarize_steps, _format_steps_for_summary, _count_tool_exchanges, truncate_tool_result, enforce_window, maybe_compress |
| `hooks.py` | `test_v3_m4`, `test_phase15`, `test_parallel_execution` | HookExecutor — 10 lifecycle events (HookEvent enum), HookDecision (ALLOW/BLOCK/MODIFY), exit code protocol, env vars, async hooks, matcher/file_patterns filtering, HooksRegistry, backward-compat run_post_edit; PostEditHooks legacy |
| `evaluator.py` | `test_phase12` | SelfEvaluator — basic mode, full mode, evaluación de resultados |
| `mixed_mode.py` | `test_phase3`, `test_v3_m3` | MixedModeRunner — ya no es default, backward compat |
| `shutdown.py` | `test_phase7` | GracefulShutdown — estado inicial, reset, should_stop, integración con AgentLoop |
| `timeout.py` | `test_phase7` | StepTimeout — sin timeout, salida limpia, restauración de handler, raises |

### `src/architect/llm/` — Adaptador LLM

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `adapter.py` | `test_streaming`, `test_phase2`, `test_phase7`, `test_integration` | completion_stream (mock completo), _parse_arguments, _try_parse_text_tool_calls, _prepare_messages_with_caching, _normalize_response, StreamChunk/LLMResponse/ToolCall modelos, retry logic |
| `cache.py` | `test_phase14` | LocalLLMCache — SHA-256 determinista, TTL, hit/miss |

### `src/architect/mcp/` — MCP (Model Context Protocol)

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `client.py` | `test_mcp_internals`, `test_phase4` | MCPClient init (headers, token, URL), _parse_sse (8 escenarios), _parse_response (JSON/SSE/fallback), _resolve_token (4 fuentes), _next_id (secuencia), _ensure_initialized (handshake mock) |
| `adapter.py` | `test_mcp_internals`, `test_phase4` | MCPToolAdapter — name prefixing, schema generation, args_model dinámico, required/optional fields, type mapping, _extract_content (4 formatos), execute (success/errors) |
| `discovery.py` | `test_phase4` | MCPDiscovery — descubrimiento de servidores |

### `src/architect/config/` — Configuración

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `schema.py` | `test_config_loader`, `test_v3_m4`, `test_phase13`, `test_phase14` | AppConfig, AgentConfig, ContextConfig, MCPServerConfig, HookConfig, HooksConfig, LoggingConfig, CommandsConfig — validación Pydantic, extra='forbid', defaults |
| `loader.py` | `test_config_loader` | deep_merge (8 tests), load_yaml_config (5), load_env_overrides (6), apply_cli_overrides (10), load_config pipeline (5), validación Pydantic en pipeline (3) |

### `src/architect/execution/` — Motor de ejecución

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `engine.py` | `test_phase1`, `test_v3_m4`, `test_parallel_execution` | ExecutionEngine — execute, dry-run, run_post_edit_hooks, integración con hooks |
| `policies.py` | `test_phase1`, `test_parallel_execution` | ConfirmationPolicy — yolo, confirm-all, confirm-sensitive |
| `validators.py` | `test_phase1`, `test_v3_m6` | validate_path — path traversal prevention |

### `src/architect/costs/` — Tracking de costes

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `tracker.py` | `test_phase14`, `test_phase11` | CostTracker — record, summary, format_summary_line |
| `prices.py` | `test_phase14` | PriceLoader — precios por modelo, default_prices.json |
| `__init__.py` | `test_phase14` | BudgetExceededError — presupuesto excedido |

### `src/architect/agents/` — Agentes y prompts

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `prompts.py` | `test_v3_m3` | BUILD_PROMPT (5 fases: ANALIZAR→PLANIFICAR→EJECUTAR→VERIFICAR→CORREGIR), PLAN_PROMPT, REVIEW_PROMPT, DEFAULT_PROMPTS |
| `registry.py` | `test_v3_m3`, `test_phase3` | DEFAULT_AGENTS (4 agentes), get_agent (merge YAML+defaults), list_available_agents, resolve_agents_from_yaml, AgentNotFoundError, CLI overrides |

### `src/architect/indexer/` — Indexador de repositorio

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `tree.py` | `test_phase10` | RepoIndexer — basic, excludes, file_info, languages |
| `cache.py` | `test_phase10` | IndexCache — set/get, TTL expiración |

### `src/architect/logging/` — Sistema de logging

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `levels.py` | `test_v3_m5` | HUMAN level (25, entre INFO y WARNING) |
| `human.py` | `test_v3_m5` | HumanFormatter.format_event, HumanLog métodos, HumanLogHandler filtrado |
| `setup.py` | `test_v3_m5`, `test_phase5` | configure_logging, dual pipeline (JSON file + stderr humano), quiet mode, verbose levels |

### `src/architect/cli.py` — CLI (Click)

| Test file(s) | Qué se prueba |
|---|---|
| `test_phase6`, `test_phase8`, `test_v3_m3` | JSON output format, exit codes, stdout/stderr separation, CLI help, agents command, validate-config, full init without LLM, dry-run sin API key, build como default |

### v4 Phase A — Hooks, Guardrails, Skills, Memory

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `core/hooks.py` | `test_phase15` (29 tests) | HookEvent (10 valores), HookDecision (3 valores), HookResult, HookConfig, HooksRegistry (registro, get_hooks, has_hooks), HookExecutor (_build_env, execute_hook, run_event con matcher/file_patterns, run_post_edit backward-compat), exit code protocol (0=ALLOW, 2=BLOCK, otro=Error), async hooks, timeout |
| `core/guardrails.py` | `test_phase16` (24 tests), `tests/test_guardrails/` (71 tests) | GuardrailsEngine — sensitive_files (bloquea lectura+escritura), protected_files (bloquea solo escritura), shell read detection (`cat/head/tail` a sensibles), check_command (blocked_commands regex + redirect/read checks), check_edit_limits (max_files/lines), check_code_rules (severity warn/block), record_command/record_edit, should_force_test, run_quality_gates (subprocess, timeout, required vs optional), state tracking |
| `skills/loader.py` | `test_phase17` (31 tests) | SkillsLoader — load_project_context (.architect.md, AGENTS.md, CLAUDE.md), discover_skills (local + installed), _parse_skill (YAML frontmatter), get_relevant_skills (glob matching), build_system_context; SkillInfo dataclass |
| `skills/installer.py` | `test_phase17` | SkillInstaller — install_from_github (sparse checkout), create_local (plantilla SKILL.md), list_installed, uninstall |
| `skills/memory.py` | `test_phase18` (32 tests) | ProceduralMemory — 6 CORRECTION_PATTERNS (direct, negation, clarification, should_be, wrong_approach, absolute_rule), detect_correction, add_correction (dedup), add_pattern, _load/_append_to_file, get_context, analyze_session_learnings |
| `config/schema.py` | `test_phase15-18`, `test_config_loader` | HookItemConfig, HooksConfig (10 eventos + post_edit compat), GuardrailsConfig, QualityGateConfig, CodeRuleConfig, SkillsConfig, MemoryConfig — validación Pydantic, defaults, extra='forbid' |

### v4 Phase B — Sessions, Reports, Dry Run, CI/CD Flags

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `features/sessions.py` | `test_phase_b` (B1, 8 tests), `tests/test_sessions/` (22 tests) | SessionManager — save/load/list/cleanup/delete, SessionState round-trip, generate_session_id (formato + unicidad), message truncation (>50 → últimos 30), JSON corrupto → None, ordenación newest-first, caracteres especiales, StopReason round-trip |
| `features/report.py` | `test_phase_b` (B2, 8 tests), `tests/test_reports/` (20 tests) | ExecutionReport, ReportGenerator — to_json (parseable + todas las keys), to_markdown (tablas + secciones), to_github_pr_comment (`<details>` collapsible), status icons (OK/WARN/FAIL), valores zero, colecciones vacías, paths largos, collect_git_diff |
| `features/dryrun.py` | `test_phase_b` (B4, 6 tests), `tests/test_dryrun/` (23 tests) | DryRunTracker — record_action, get_plan_summary, action_count, WRITE_TOOLS/READ_TOOLS disjuntos, _summarize_action (5 code paths), interleave read+write, tool_input complejo/truncación |
| `cli.py` (B3 flags) | `test_phase_b` (B3, 5 tests) | CLI flags: --json, --dry-run, --report, --report-file, --session, --confirm-mode, --context-git-diff, --exit-code-on-partial; comandos: `architect sessions`, `architect cleanup`, `architect resume NONEXISTENT` → exit 3; exit code constants (0,1,2,3,4,5,130) |

### Plan base v4 Phase C — Ralph Loop, Parallel, Pipelines, Checkpoints, Auto-Review

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `features/ralph.py` | `tests/test_ralph/` (90 tests) | RalphLoop — iteración completa, contexto limpio por iteración, safety nets (max_iterations, max_cost, max_time), _run_checks (subprocess, exit codes), _build_iteration_prompt (con checks fallidos y outputs), RalphConfig dataclass, LoopIteration, RalphLoopResult, stop_reason (5 valores), worktree isolation, agent_factory pattern |
| `features/pipelines.py` | `tests/test_pipelines/` (83 tests) | PipelineRunner — ejecución secuencial, _substitute_variables ({{name}}), _check_condition (shell exit code), _run_checks, _create_checkpoint, from_step resume, dry_run mode, PipelineConfig/PipelineStep dataclasses, PipelineStepResult, output_var captura, pasos condicionados, YAML parsing |
| `features/parallel.py` | `tests/test_parallel/` (43 tests) | ParallelRunner — _create_worktrees, _run_worker (subprocess), cleanup_worktrees, round-robin de tareas y modelos, WorkerResult dataclass, ParallelConfig, WORKTREE_PREFIX, ProcessPoolExecutor, error handling por worker |
| `features/checkpoints.py` | `tests/test_checkpoints/` (48 tests) | CheckpointManager — create (git add + commit), list_checkpoints (git log --grep, format %H\|%s\|%at), rollback (git reset --hard), get_latest, has_changes_since, Checkpoint dataclass (frozen), short_hash, CHECKPOINT_PREFIX, no-changes → None |
| `agents/reviewer.py` | `tests/test_reviewer/` (47 tests) | AutoReviewer — review_changes (contexto limpio, agent_factory), build_fix_prompt, get_recent_diff (subprocess git diff), ReviewResult dataclass, REVIEW_SYSTEM_PROMPT, detección "sin issues" (case-insensitive), error handling (LLM failure → ReviewResult con error), AutoReviewConfig |
| `cli.py` (C commands) | `test_phase_c_e2e.py` (31 tests) | CLI: `architect loop`, `architect pipeline`, `architect parallel`, `architect parallel-cleanup`; integración ralph+checks, pipeline+variables+conditions, parallel+worktrees, checkpoints+list+rollback, auto-review flow |

### Plan base v4 Phase D — Dispatch, Health, Eval, Telemetry, Presets

| Archivo fuente | Test file(s) | Qué se prueba |
|---|---|---|
| `tools/dispatch.py` | `tests/test_dispatch/` (36 tests) | DispatchSubagentTool — DispatchSubagentArgs validación, VALID_SUBAGENT_TYPES (explore/test/review), SUBAGENT_ALLOWED_TOOLS per tipo, SUBAGENT_MAX_STEPS=15, SUBAGENT_SUMMARY_MAX_CHARS=1000, execute con agent_factory mock, error handling |
| `core/health.py` | `tests/test_health/` (28 tests) | CodeHealthAnalyzer — take_before/after_snapshot, compute_delta, FunctionMetric (frozen dataclass), HealthSnapshot campos, HealthDelta.to_report() markdown, LONG_FUNCTION_THRESHOLD (50), DUPLICATE_BLOCK_SIZE (6), análisis AST sin radon |
| `features/competitive.py` | `tests/test_competitive/` (19 tests) | CompetitiveEval — CompetitiveConfig, CompetitiveResult, run() con ParallelRunner mock, _run_checks_in_worktree, _rank_results (score compuesto), generate_report markdown |
| `telemetry/otel.py` | `tests/test_telemetry/` (20 tests, 9 skip) | ArchitectTracer — start_session context manager, trace_llm_call, trace_tool, NoopTracer/NoopSpan, create_tracer factory (enabled/disabled), SERVICE_NAME/SERVICE_VERSION constants. 9 tests skip si OpenTelemetry no está instalado |
| `config/presets.py` | `tests/test_presets/` (37 tests) | PresetManager — AVAILABLE_PRESETS (5), apply() genera .architect.md + config.yaml, list_presets(), overwrite behavior, preset content validation |
| (bugfixes) | `tests/test_bugfixes/` (41 tests) | BUG-3: code_rules pre-execution (11), BUG-4: dispatch wiring (5), BUG-5: telemetry wiring (8), BUG-6: health wiring (6), BUG-7: parallel config propagation (11) |

---

## Tests de integración (`test_integration.py`)

60 assertions que prueban flujos end-to-end entre múltiples módulos:

| Sección | Tests | Estado | Nota |
|---|:---:|:---:|---|
| 0. Prerequisitos | 4 | Passed | Imports, versión, tools, config |
| 1. LLM Proxy — Llamadas directas | 4 | **Requiere API key** | Completion básico, con tools, multiple tools, usage |
| 2. Streaming — Respuestas en tiempo real | 3 | **Requiere API key** | Streaming básico, tool calls, usage info |
| 3. MCP — Servidores reales | 3 | Passed | Client init, handshake mock, tool call mock |
| 4. CLI End-to-End | 5 | Passed | Help, version, agents list, validate-config, dry-run |
| 5. Config YAML — Configuraciones complejas | 6 | Passed | YAML completo, merge, env vars, defaults |
| 6. Safety Nets — Watchdogs | 4 | Passed | Timeout, shutdown, max_steps, context full |
| 7. CLI + MCP — Flujo completo | 3 | Passed | Config con MCP, discovery mock, tools adapter |
| 8. Post-Edit Hooks | 5 | Passed | run_for_tool, matching, truncado, disabled |
| 9. Tools Locales | 8 | Passed | read/write/edit/delete/list/search/grep/find |
| 10. Context Manager | 6 | Passed | estimate_tokens, threshold, manage, summarize |
| 11. Cost Tracker | 3 | Passed | Basic tracking, budget exceeded, format line |

---

## Qué NO se prueba (gaps conocidos)

Estas áreas no tienen cobertura automatizada pero son difíciles de testear sin infraestructura real:

| Área | Razón |
|---|---|
| **LLM real** (secciones 1-2 de integration) | Requiere `OPENAI_API_KEY`. Funciona con key, probado manualmente |
| **MCP servidor real** (HTTP live) | Requiere servidor MCP corriendo. `test_phase4` prueba con mocks; `test_mcp_internals` prueba internals exhaustivamente |
| **Agent loop completo** (LLM → Tools → LLM) | Requiere API key para el ciclo completo. Las partes individuales están probadas por separado |
| **Streaming real sobre red** | `test_streaming.py` prueba con mocks completos del generator; streaming real requiere API key |
| **SIGINT/SIGTERM real** | `test_phase7` prueba GracefulShutdown en aislamiento; señales reales en un proceso vivo son frágiles en CI |

> Todas las funciones internas, parsing, validación, seguridad y lógica de decisión están cubiertas sin necesidad de credenciales externas.

---

## QA — v0.16.1

Tras la implementación de v4 Phase A se realizó un proceso de QA completo:

1. Se ejecutaron los 25 scripts de test (597 originales + 116 nuevos)
2. Se detectaron y corrigieron 5 bugs:
   - `CostTracker.format_summary_line()` — AttributeError por campo mal referenciado
   - `PriceLoader._load_prices()` — acceso a dict con `get()` vs `[]` en nested keys
   - `HUMAN` log level — registro doble del nivel en `logging.addLevelName()`
   - `HumanFormatter._summarize_args()` — `ValueError` en `.index()` para strings sin separador
   - `CommandTool` — referencia incorrecta a `args.timeout` vs `args.timeout_seconds`
3. Se actualizaron 5 scripts de test para usar `EXPECTED_VERSION = "0.16.1"`
4. Resultado final: **713 tests passing**, 7 expected failures (requieren API key)

## QA — v0.17.0

Tras la implementación de v4 Phase B:

1. Se creó `scripts/test_phase_b.py` con ~35 tests y ~104 checks
2. Se crearon tests unitarios pytest: `tests/test_sessions/` (22), `tests/test_reports/` (20), `tests/test_dryrun/` (23)
3. Se detectaron y corrigieron 4 bugs (QA3):
   - `GuardrailsEngine.check_command()` — redirect output no debería bloquearse
   - `ReportGenerator.to_markdown()` — duración en timeline no calculada
   - Version hardcoded en tests — ahora se lee dinámicamente desde `__init__.py`
   - `_execute_tool_calls_batch` — parallel execution timeout en CI
4. Resultado final: **~817+ tests passing** (scripts) + **~181 tests pytest** (unitarios)

## QA — v0.18.0 (Plan base v4 Phase C)

Tras la implementación de Phase C:

1. Se crearon tests unitarios pytest: `tests/test_ralph/` (90), `tests/test_pipelines/` (83), `tests/test_checkpoints/` (48), `tests/test_reviewer/` (47), `tests/test_parallel/` (43)
2. Se creó `scripts/test_phase_c_e2e.py` con 31 tests E2E (C1-C5 + combinados)
3. Se detectaron y corrigieron 3 bugs (QA4):
   - **BUG-1**: `RalphLoop` ejecutaba iteraciones compartiendo contexto — corregido para crear agente FRESCO por iteración via `agent_factory`
   - **BUG-2**: `ParallelRunner._create_worktrees()` no aislaba correctamente — corregido para usar git worktree con branches dedicadas
   - **BUG-3**: `CheckpointManager.list_checkpoints()` parseaba incorrecto el formato de `git log` — corregido formato pipe-separated `%H|%s|%at`
4. Resultado final: **~848 tests passing** (scripts) + **504 tests pytest** (unitarios) + **31 E2E** (Phase C)

## QA — v0.19.0 / v1.0.0 (Plan base v4 Phase D)

Tras la implementación de Phase D:

1. Se crearon tests unitarios pytest: `tests/test_dispatch/` (36), `tests/test_health/` (28), `tests/test_competitive/` (19), `tests/test_telemetry/` (20, 9 skip), `tests/test_presets/` (37)
2. Se detectaron y corrigieron 7 bugs (QA-D):
   - **BUG-1 (CRITICAL)**: `@cli.command` → `@main.command` para `eval` e `init` — rompía importación del módulo CLI
   - **BUG-2 (MEDIUM)**: Versión inconsistente entre `pyproject.toml`, `__init__.py` y `cli.py`
   - **BUG-3 (HIGH)**: `code_rules` severity:block no prevenía escrituras — se ejecutaba DESPUÉS de write. Fix: movido a pre-ejecución
   - **BUG-4 (MEDIUM)**: `dispatch_subagent` tool existía pero no se registraba en CLI run
   - **BUG-5 (MEDIUM)**: `TelemetryConfig` parseada pero `create_tracer()` nunca llamado
   - **BUG-6 (MEDIUM)**: `HealthConfig` parseada pero `CodeHealthAnalyzer` nunca invocado
   - **BUG-7 (MEDIUM)**: Workers paralelos no propagaban `--config` ni `--api-base`
3. Se crearon 41 tests específicos de validación de bugs en `tests/test_bugfixes/test_bugfixes.py`
4. Resultado final: **687 pytest passed**, 9 skipped, 0 failures + **31 E2E** + **~848 scripts**

---

## Cómo ejecutar

```bash
# Todos los tests (sin API key)
for f in scripts/test_*.py; do python3.12 "$f"; done

# Un test específico
python3.12 scripts/test_phase13.py

# Con API key (para tests de integración completos)
OPENAI_API_KEY=sk-... python3.12 scripts/test_integration.py
```

Todos los scripts son standalone: no requieren pytest, usan helpers `ok()`/`fail()`/`section()` internos, y retornan exit code 0 (todo OK) o 1 (hay fallos).
