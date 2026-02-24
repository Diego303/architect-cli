# Documentación técnica — architect CLI

Índice de la documentación interna del proyecto. Orientada a desarrolladores e IAs que necesitan entender, modificar o extender el sistema.

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| [`usage.md`](usage.md) | **Formas de uso**: flags, logging, configs, CI/CD, scripts, agentes custom, multi-proyecto |
| [`architecture.md`](architecture.md) | Visión general, diagrama de componentes y flujo completo de ejecución |
| [`core-loop.md`](core-loop.md) | El loop while True, safety nets, StopReason, graceful close, hooks lifecycle, human logging, ContextManager, parallel tools, SelfEvaluator |
| [`data-models.md`](data-models.md) | Todos los modelos de datos: Pydantic, dataclasses, jerarquía de errores |
| [`tools-and-execution.md`](tools-and-execution.md) | Sistema de tools: filesystem, edición, búsqueda, MCP, ExecutionEngine |
| [`agents-and-modes.md`](agents-and-modes.md) | Agentes por defecto, registry, prompts del sistema |
| [`config-reference.md`](config-reference.md) | Schema completo de configuración, precedencia, variables de entorno |
| [`logging.md`](logging.md) | **Sistema de logging**: 3 pipelines, nivel HUMAN, iconos, HumanFormatter, structlog |
| [`ai-guide.md`](ai-guide.md) | Guía para IA: invariantes críticos, patrones, dónde añadir cosas, trampas |
| [`testing.md`](testing.md) | Mapa de tests: ~817+ tests en 30+ archivos, cobertura por módulo |
| [`containers.md`](containers.md) | **Contenedores**: Containerfiles (root, non-root, OpenShift), Kubernetes Deployments, Docker, configuración para CI/CD |
| [`casos-de-uso.md`](casos-de-uso.md) | **Casos de uso**: integración en desarrollo diario, CI/CD, QA, DevOps, AIOps, MLOps, arquitecturas MCP, pipelines multi-agente |
| [`fast-usage.md`](fast-usage.md) | **Guía rápida**: instalación, configuración mínima, comandos más útiles y referencia de flags |
| [`mcp-server.md`](mcp-server.md) | **MCP Server**: cómo crear un servidor MCP que exponga architect como herramienta remota (server.py + tools.py completos) |
| [`good-practices.md`](good-practices.md) | **Buenas prácticas**: prompts, agentes, edición, costes, hooks lifecycle, guardrails, skills, memoria, auto-evaluación, CI/CD, errores comunes |
| [`security.md`](security.md) | **Modelo de seguridad**: 19 capas defensivas, modelo de amenazas, path traversal, command security, prompt injection, hardening |
| [`sessions.md`](sessions.md) | **Sessions**: persistencia y resume — guardar, listar, reanudar y limpiar sesiones entre ejecuciones |
| [`reports.md`](reports.md) | **Reports**: reportes de ejecución en JSON, Markdown y GitHub PR comment para CI/CD |
| [`dryrun.md`](dryrun.md) | **Dry Run**: simulación de ejecución — DryRunTracker, WRITE_TOOLS/READ_TOOLS, plan de acciones |
| [`ralph-loop.md`](ralph-loop.md) | **Ralph Loop**: iteración automática con checks — RalphConfig, RalphLoop, contexto limpio, worktrees, safety nets |
| [`pipelines.md`](pipelines.md) | **Pipelines**: workflows YAML multi-step — variables {{nombre}}, condiciones, output_var, checkpoints, dry-run, from-step |
| [`parallel.md`](parallel.md) | **Parallel**: ejecución paralela en git worktrees — ParallelRunner, workers, round-robin de modelos |
| [`checkpoints.md`](checkpoints.md) | **Checkpoints**: puntos de restauración git — CheckpointManager, rollback, integración con pipelines |
| [`auto-review.md`](auto-review.md) | **Auto-Review**: revisión post-build con contexto limpio — AutoReviewer, ReviewResult, fix-pass |

---

## Resumen rápido

**architect** es una CLI headless que conecta un LLM a herramientas de sistema de archivos (y opcionalmente a servidores MCP remotos). El usuario describe una tarea en lenguaje natural; el sistema itera: llama al LLM → el LLM decide qué herramientas usar → las herramientas se ejecutan → los resultados vuelven al LLM → siguiente iteración.

```
architect run "refactoriza main.py" -a build --mode yolo
         │
         ├─ load_config()         YAML + env + CLI flags
         ├─ configure_logging()   3 pipelines: HUMAN + técnico + JSON file
         ├─ ToolRegistry          local tools + MCP remotas
         ├─ RepoIndexer           árbol del workspace → system prompt
         ├─ LLMAdapter            LiteLLM + retries selectivos + prompt caching + local cache
         ├─ ContextManager        pruning de contexto (3 niveles)
         ├─ CostTracker           seguimiento de costes + budget enforcement
         ├─ SkillsLoader          .architect.md + skills → system prompt context
         ├─ ProceduralMemory      correcciones del usuario → .architect/memory.md
         ├─ SessionManager        persistencia de sesiones en .architect/sessions/
         ├─ DryRunTracker         registro de acciones en modo --dry-run
         ├─ CheckpointManager     git commits con rollback (architect:checkpoint)
         │
         ├─ RalphLoop             iteración automática hasta que checks pasen (v4-C1)
         ├─ PipelineRunner        workflows YAML multi-step con variables (v4-C3)
         ├─ ParallelRunner        ejecución paralela en git worktrees (v4-C2)
         ├─ AutoReviewer          review post-build con contexto limpio (v4-C5)
         │
         ├─ AgentLoop (build por defecto)        while True + safety nets
         │       │
         │       ├─ [check safety nets]   max_steps / budget / timeout / context_full → StopReason
         │       ├─ [check shutdown]      SIGINT/SIGTERM → graceful close
         │       ├─ [StepTimeout]         SIGALRM por step
         │       ├─ llm.completion()      → streaming chunks a stderr
         │       ├─ cost_tracker.record() → coste del step; BudgetExceededError si excede
         │       ├─ engine.execute()      → guardrails → pre-hooks → validar → confirmar → tool → post-hooks
         │       │       ├─ GuardrailsEngine   → check_file_access / check_command / check_edit_limits
         │       │       ├─ HookExecutor       → pre_tool_use (BLOCK/ALLOW) + post_tool_use (lint/etc)
         │       │       └─ PostEditHooks      → backward-compat v3-M4
         │       ├─ HumanLog              → eventos HUMAN (25) a stderr (pipeline separado)
         │       ├─ ctx.append_results()  → siguiente iteración
         │       ├─ context_mgr.prune()   → truncar/resumir/ventana
         │       ├─ session_mgr.save()    → guardar estado después de cada paso (B1)
         │       └─ _graceful_close()     → ultima llamada al LLM sin tools (resumen)
         │
         └─ SelfEvaluator (opcional, --self-eval)
                 └─ evaluate_basic() / evaluate_full()

         └─ ReportGenerator (opcional, --report json|markdown|github)
                 └─ to_json() / to_markdown() / to_github_pr_comment()
```

**Stack**: Python 3.12+, Click, Pydantic v2, LiteLLM, httpx, structlog, tenacity.

**Versión actual**: 0.18.0

---

## Novedades recientes (v0.9–v0.18)

| Versión | Funcionalidad |
|---------|---------------|
| v0.9.0 | `edit_file` (str-replace incremental) + `apply_patch` (unified diff) |
| v0.10.0 | `RepoIndexer` (árbol del proyecto en system prompt) + `search_code`, `grep`, `find_files` |
| v0.11.0 | `ContextManager` (pruning 3 niveles) + parallel tool calls (ThreadPoolExecutor) |
| v0.12.0 | `SelfEvaluator` (auto-evaluación) + `--self-eval basic/full` |
| v0.13.0 | `RunCommandTool` (ejecución de código) + 4 capas de seguridad + `--allow-commands/--no-commands` |
| v0.14.0 | `CostTracker` + `PriceLoader` + `LocalLLMCache` + prompt caching + `--budget/--show-costs/--cache` |
| v0.15.0 | `while True` loop (v3) + `StopReason` enum + `PostEditHooks` + `HUMAN` log level + `HumanLog` + graceful close + `build` como agente default |
| v0.15.2 | `HumanFormatter` con iconos (🔄🔧🌐✅⚡❌📦🔍) + distinción MCP + evento `llm_response` + coste en completado |
| v0.15.3 | Fix pipeline structlog: `wrap_for_formatter` siempre activo, human logging funciona sin `--log-file` |
| v0.16.0 | **v4 Phase A**: `HookExecutor` (10 lifecycle events, exit code protocol), `GuardrailsEngine` (protected files, blocked commands, edit limits, quality gates), `SkillsLoader` + `SkillInstaller` (.architect.md, SKILL.md, glob activation), `ProceduralMemory` (correction detection, persistence) |
| v0.16.1 | QA Phase A: 5 bug fixes, 116 nuevos tests (713 total), scripts actualizados |
| v0.16.2 | QA2: streaming costs fix, yolo mode fix, timeout separation, MCP tools auto-injection, defensive get_schemas |
| v0.17.0 | **v4 Phase B**: `SessionManager` (save/load/resume/cleanup), `ReportGenerator` (JSON/Markdown/GitHub PR), `DryRunTracker` (plan de acciones), CI/CD flags (`--report`, `--session`, `--context-git-diff`, `--exit-code-on-partial`), exit codes (0-5, 130), nuevos comandos (`sessions`, `resume`, `cleanup`) |
| v0.18.0 | **v4 Phase C**: `RalphLoop` (iteración automática con checks, contexto limpio, worktrees), `PipelineRunner` (workflows YAML multi-step con variables, condiciones, checkpoints), `ParallelRunner` (ejecución paralela en git worktrees), `CheckpointManager` (git commits con rollback), `AutoReviewer` (review post-build con contexto limpio), 4 nuevos comandos (`loop`, `pipeline`, `parallel`, `parallel-cleanup`) |
