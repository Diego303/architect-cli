# Documentación técnica — architect CLI

Índice de la documentación interna del proyecto. Orientada a desarrolladores e IAs que necesitan entender, modificar o extender el sistema.

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| [`usage.md`](usage.md) | **Formas de uso**: flags, logging, configs, CI/CD, scripts, agentes custom, multi-proyecto |
| [`architecture.md`](architecture.md) | Visión general, diagrama de componentes y flujo completo de ejecución |
| [`core-loop.md`](core-loop.md) | El loop while True, safety nets, StopReason, graceful close, hooks post-edit, human logging, ContextManager, parallel tools, SelfEvaluator |
| [`data-models.md`](data-models.md) | Todos los modelos de datos: Pydantic, dataclasses, jerarquía de errores |
| [`tools-and-execution.md`](tools-and-execution.md) | Sistema de tools: filesystem, edición, búsqueda, MCP, ExecutionEngine |
| [`agents-and-modes.md`](agents-and-modes.md) | Agentes por defecto, registry, mixed mode, prompts del sistema |
| [`config-reference.md`](config-reference.md) | Schema completo de configuración, precedencia, variables de entorno |
| [`ai-guide.md`](ai-guide.md) | Guía para IA: invariantes críticos, patrones, dónde añadir cosas, trampas |

---

## Resumen rápido

**architect** es una CLI headless que conecta un LLM a herramientas de sistema de archivos (y opcionalmente a servidores MCP remotos). El usuario describe una tarea en lenguaje natural; el sistema itera: llama al LLM → el LLM decide qué herramientas usar → las herramientas se ejecutan → los resultados vuelven al LLM → siguiente iteración.

```
architect run "refactoriza main.py" -a build --mode yolo
         │
         ├─ load_config()         YAML + env + CLI flags
         ├─ configure_logging()   stderr dual-pipeline
         ├─ ToolRegistry          local tools + MCP remotas
         ├─ RepoIndexer           árbol del workspace → system prompt
         ├─ LLMAdapter            LiteLLM + retries selectivos + prompt caching + local cache
         ├─ ContextManager        pruning de contexto (3 niveles)
         ├─ CostTracker           seguimiento de costes + budget enforcement
         │
         ├─ AgentLoop (o MixedModeRunner)      while True + safety nets
         │       │
         │       ├─ [check safety nets]   max_steps / budget / timeout / context_full → StopReason
         │       ├─ [check shutdown]      SIGINT/SIGTERM → graceful close
         │       ├─ [StepTimeout]         SIGALRM por step
         │       ├─ llm.completion()      → streaming chunks a stderr
         │       ├─ cost_tracker.record() → coste del step; BudgetExceededError si excede
         │       ├─ engine.execute()      → paralelo si posible → validar → confirmar
         │       ├─ PostEditHooks         → auto-lint/test tras edit_file/write_file/apply_patch
         │       ├─ HumanLog              → eventos HUMAN (25) a stderr (pipeline separado)
         │       ├─ ctx.append_results()  → siguiente iteración
         │       ├─ context_mgr.prune()   → truncar/resumir/ventana
         │       └─ _graceful_close()     → ultima llamada al LLM sin tools (resumen)
         │
         └─ SelfEvaluator (opcional, --self-eval)
                 └─ evaluate_basic() / evaluate_full()
```

**Stack**: Python 3.12+, Click, Pydantic v2, LiteLLM, httpx, structlog, tenacity.

**Versión actual**: 0.15.0

---

## Novedades recientes (v0.9–v0.15)

| Versión | Funcionalidad |
|---------|---------------|
| v0.9.0 | `edit_file` (str-replace incremental) + `apply_patch` (unified diff) |
| v0.10.0 | `RepoIndexer` (árbol del proyecto en system prompt) + `search_code`, `grep`, `find_files` |
| v0.11.0 | `ContextManager` (pruning 3 niveles) + parallel tool calls (ThreadPoolExecutor) |
| v0.12.0 | `SelfEvaluator` (auto-evaluación) + `--self-eval basic/full` |
| v0.13.0 | `RunCommandTool` (ejecución de código) + 4 capas de seguridad + `--allow-commands/--no-commands` |
| v0.14.0 | `CostTracker` + `PriceLoader` + `LocalLLMCache` + prompt caching + `--budget/--show-costs/--cache` |
| v0.15.0 | `while True` loop (v3) + `StopReason` enum + `PostEditHooks` (auto-lint/test) + `HUMAN` log level + `HumanLog` + graceful close |
