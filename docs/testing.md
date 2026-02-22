# Testing — Resumen completo de cobertura

Documento actualizado el 2026-02-23. Refleja el estado actual de todos los test scripts en `scripts/`. Versión: v0.16.2.

## Resultado global

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
| `test_integration.py` | 54 (47+7) | 47 passed, 7 esperados | 7 requieren key |
| `test_config_loader.py` | 37 | Passed | No |
| `test_mcp_internals.py` | 47 | Passed | No |
| `test_streaming.py` | 33 | Passed | No |
| `test_parallel_execution.py` | 29 | Passed | No |
| **TOTAL** | **~713** | **Passed** | **7 esperados con key** |

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
| `core/guardrails.py` | `test_phase16` (24 tests) | GuardrailsEngine — check_file_access (protected_files globs), check_command (blocked_commands regex), check_edit_limits (max_files/lines), check_code_rules (severity warn/block), record_command/record_edit, should_force_test, run_quality_gates (subprocess, timeout, required vs optional), state tracking |
| `skills/loader.py` | `test_phase17` (31 tests) | SkillsLoader — load_project_context (.architect.md, AGENTS.md, CLAUDE.md), discover_skills (local + installed), _parse_skill (YAML frontmatter), get_relevant_skills (glob matching), build_system_context; SkillInfo dataclass |
| `skills/installer.py` | `test_phase17` | SkillInstaller — install_from_github (sparse checkout), create_local (plantilla SKILL.md), list_installed, uninstall |
| `skills/memory.py` | `test_phase18` (32 tests) | ProceduralMemory — 6 CORRECTION_PATTERNS (direct, negation, clarification, should_be, wrong_approach, absolute_rule), detect_correction, add_correction (dedup), add_pattern, _load/_append_to_file, get_context, analyze_session_learnings |
| `config/schema.py` | `test_phase15-18`, `test_config_loader` | HookItemConfig, HooksConfig (10 eventos + post_edit compat), GuardrailsConfig, QualityGateConfig, CodeRuleConfig, SkillsConfig, MemoryConfig — validación Pydantic, defaults, extra='forbid' |

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
