# Arquitectura del sistema

## Mapa de componentes

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CLI (cli.py)                                                           │
│                                                                         │
│  architect run PROMPT                                                   │
│     │                                                                   │
│     ├─ 1. GracefulShutdown()          instala SIGINT + SIGTERM          │
│     ├─ 2. load_config()               YAML → env → CLI flags            │
│     ├─ 3. configure_logging()         stderr + opcional JSON file       │
│     ├─ 4. ToolRegistry                                                  │
│     │       └─ register_all_tools()   filesystem + edición + búsqueda  │
│     │       └─ MCPDiscovery()         (opcional, --disable-mcp)        │
│     ├─ 5. RepoIndexer                 árbol del workspace (F10)         │
│     │       └─ IndexCache             caché en disco (TTL 5 min)        │
│     ├─ 6. LLMAdapter(config.llm)      LiteLLM + retries selectivos      │
│     ├─ 7. ContextManager(config.ctx)  pruning 3 niveles (F11)           │
│     ├─ 8. ContextBuilder(repo_index, context_manager)                  │
│     │                                                                   │
│     ├─ 9a. AgentLoop (modo single-agent, -a flag)                      │
│     │       └─ ExecutionEngine(registry, config, confirm_mode)         │
│     └─ 9b. MixedModeRunner (modo mixto, sin -a)                        │
│             ├─ plan_engine + plan_loop                                  │
│             └─ build_engine + build_loop                                │
│                                                                         │
│    10. SelfEvaluator (opcional, --self-eval basic|full, F12)           │
│         └─ evaluate_basic() | evaluate_full(run_fn)                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Diagrama de módulos y dependencias

```
cli.py
 ├── config/loader.py ──── config/schema.py
 ├── logging/setup.py
 ├── tools/setup.py ────── tools/registry.py
 │                          tools/filesystem.py ── tools/base.py
 │                          tools/patch.py         tools/schemas.py
 │                          tools/search.py
 │                          execution/validators.py
 ├── mcp/discovery.py ──── mcp/client.py
 │                          mcp/adapter.py ──────── tools/base.py
 ├── indexer/tree.py
 ├── indexer/cache.py
 ├── llm/adapter.py
 ├── core/context.py ───── indexer/tree.py (RepoIndex)
 │                          llm/adapter.py (LLMAdapter — para maybe_compress)
 ├── core/loop.py ──────── core/state.py
 │                          core/shutdown.py
 │                          core/timeout.py
 │                          core/context.py (ContextManager)
 ├── core/mixed_mode.py ── core/loop.py
 │                          core/context.py (ContextManager)
 ├── core/evaluator.py ─── llm/adapter.py (LLMAdapter)
 │                          core/state.py (AgentState) — TYPE_CHECKING only
 └── agents/registry.py ── agents/prompts.py
                            config/schema.py (AgentConfig)
```

---

## Flujo de ejecución completo

### Modo single-agent (`architect run PROMPT -a build`)

```
GracefulShutdown()
     │
load_config(yaml, env, cli_flags)
     │
configure_logging()
     │
ToolRegistry
  ├─ register_all_tools()    read_file, write_file, delete_file, list_files,
  │                          edit_file, apply_patch, search_code, grep, find_files
  └─ MCPDiscovery()          mcp_{server}_{tool} (si hay servidores MCP)
     │
RepoIndexer.build_index()    recorre workspace → RepoIndex
  (o IndexCache.get())       usa caché si < 5 min
     │
LLMAdapter(config.llm)
     │
ContextManager(config.context)
     │
ContextBuilder(repo_index=index, context_manager=ctx_mgr)
     │
get_agent("build", yaml_agents, cli_overrides)
  → AgentConfig{system_prompt, allowed_tools, confirm_mode, max_steps}
     │
ExecutionEngine(registry, config, confirm_mode)
     │
AgentLoop.run(prompt, stream=True, on_stream_chunk=stderr_write)
     │
     ├── [iter 1]
     │     shutdown.should_stop?  →  si True: status="partial", break
     │     │
     │     with StepTimeout(seconds):
     │       llm.completion_stream(messages, tools_schema)
     │         → StreamChunk("def foo...") ──→ stderr via callback
     │         → LLMResponse(tool_calls=[ToolCall("edit_file", {...})])
     │     │
     │     _execute_tool_calls_batch([tc1, tc2, ...])
     │       si paralelo → ThreadPoolExecutor(max_workers=4)
     │         → engine.execute_tool_call("edit_file", {path:..., old_str:..., new_str:...})
     │             1. registry.get("edit_file")
     │             2. tool.validate_args(args)         → EditFileArgs
     │             3. policy.should_confirm()           → True: prompt y/n/a
     │             4. si dry_run: return [DRY-RUN]
     │             5. EditFileTool.execute()
     │                  └─ validate_path() ─ confinamiento workspace
     │                  └─ assert old_str único
     │                  └─ file.write_text(new_content)
     │                  └─ return ToolResult(success=True, output="[diff...]")
     │     │
     │     ctx.append_tool_results(messages, tool_calls, results)
     │       └─ ContextManager.truncate_tool_result(content)  ← Nivel 1
     │     state.steps.append(StepResult(...))
     │     ContextManager.maybe_compress(messages, llm)       ← Nivel 2 (si >8 steps)
     │     ContextManager.enforce_window(messages)             ← Nivel 3 (si >80k tokens)
     │
     ├── [iter 2]
     │     llm.completion(...)
     │       → LLMResponse(finish_reason="stop", content="He refactorizado main.py...")
     │     status="success", final_output="He refactorizado main.py..."
     │     break
     │
state.status = "success"

[Opcional] SelfEvaluator (si --self-eval != "off")
     │
     ├── basic: evaluate_basic(prompt, state) → EvalResult
     │     → si no pasa: state.status = "partial"
     │
     └── full: evaluate_full(prompt, state, run_fn)
           → loop hasta max_retries: evaluate_basic() + run_fn(correction_prompt)
           → retorna el mejor AgentState

si --json: stdout ← json.dumps(state.to_output_dict())
si normal: stdout ← state.final_output

sys.exit(0)
```

### Modo mixto (`architect run PROMPT`, sin -a)

```
[configuración igual que single-agent]

MixedModeRunner.run(prompt, stream=True, on_stream_chunk=...)
     │
     ├── FASE 1: plan (sin streaming)
     │     plan_loop = AgentLoop(llm, plan_engine, plan_config, ctx,
     │                           context_manager=ctx_mgr)
     │     plan_state = plan_loop.run(prompt, stream=False)
     │     si plan_state.status == "failed": return plan_state
     │     si shutdown.should_stop: return plan_state
     │
     ├── FASE 2: build (con streaming)
     │     enriched_prompt = f"""
     │       El usuario pidió: {prompt}
     │       El agente de planificación generó este plan:
     │       ---
     │       {plan_state.final_output}
     │       ---
     │       Tu trabajo es ejecutar este plan paso a paso...
     │     """
     │     build_loop = AgentLoop(llm, build_engine, build_config, ctx,
     │                            context_manager=ctx_mgr)
     │     build_state = build_loop.run(enriched_prompt, stream=True, ...)
     │
     └── return build_state

[SelfEvaluator se aplica sobre build_state si --self-eval != "off"]
```

---

## Separación stdout / stderr

Esta separación es crítica para compatibilidad con pipes Unix.

```
┌─────────────────────────────┬──────────────────────────────────────────┐
│ Destino                     │ Contenido                                │
├─────────────────────────────┼──────────────────────────────────────────┤
│ stderr                      │ Streaming chunks del LLM en tiempo real  │
│ stderr                      │ Logs estructurados (structlog)           │
│ stderr                      │ Header de ejecución (modelo, workspace)  │
│ stderr                      │ Estadísticas de MCP e indexer            │
│ stderr                      │ Avisos de confirmación                   │
│ stderr                      │ Avisos de shutdown (Ctrl+C)              │
│ stderr                      │ Output del SelfEvaluator (✓ / ⚠️)       │
├─────────────────────────────┼──────────────────────────────────────────┤
│ stdout                      │ Respuesta final del agente               │
│ stdout                      │ Output JSON (--json)                     │
└─────────────────────────────┴──────────────────────────────────────────┘

# Ejemplo de uso correcto con pipes:
architect run "analiza el proyecto" -a resume --quiet --json | jq .status
architect run "genera README" --mode yolo > README.md
architect run "..." -v 2>logs.txt    # logs a archivo, resultado a stdout
```

---

## Códigos de salida

| Código | Constante | Significado |
|--------|-----------|-------------|
| 0 | `EXIT_SUCCESS` | Éxito — agente terminó limpiamente |
| 1 | `EXIT_FAILED` | Fallo del agente — LLM o tool error irrecuperable |
| 2 | `EXIT_PARTIAL` | Parcial — hizo parte del trabajo, no completó (incluso si SelfEvaluator falla) |
| 3 | `EXIT_CONFIG_ERROR` | Error de configuración o archivo YAML no encontrado |
| 4 | `EXIT_AUTH_ERROR` | Error de autenticación LLM (API key inválida) |
| 5 | `EXIT_TIMEOUT` | Timeout en llamada LLM |
| 130 | `EXIT_INTERRUPTED` | Interrumpido por Ctrl+C (POSIX: 128 + SIGINT=2) |

Los errores de autenticación (exit 4) y timeout (exit 5) se detectan por keywords en el mensaje de error de LiteLLM, ya que LiteLLM puede lanzar varios tipos de excepción para el mismo error conceptual.

El `SelfEvaluator` puede cambiar un `"success"` a `"partial"` (exit 2) si detecta que la tarea no se completó correctamente.

---

## Decisiones de diseño

| Decisión | Justificación |
|----------|---------------|
| Sync-first (no asyncio) | Predecible, debuggable; las llamadas al LLM son la única latencia |
| Sin LangChain/LangGraph | El loop es simple (~200 líneas); añadir abstracción oscurecería el flujo |
| Pydantic v2 como fuente de verdad | Validación, serialización y documentación en un solo sitio |
| Tools nunca lanzan excepciones | El loop de agente permanece estable ante cualquier fallo de tool |
| stdout limpio | Pipes Unix: `architect run ... | jq .` funciona sin filtrar |
| MCP tools = BaseTool | Registro unificado; el agente no distingue entre local y remoto |
| Retries selectivos | Solo errores transitorios (rate limit, conexión); auth errors fallan rápido |
| SIGALRM para timeouts | Por-step, no global; permite reanudar en el siguiente step si hay timeout |
| `run_fn` en SelfEvaluator | Evita acoplamiento circular con AgentLoop; simplifica el API del evaluador |
| Parallel tools con `{future:idx}` | Garantiza orden correcto de resultados independientemente del orden de completación |
| ContextManager niveles 1→2→3 | Progresivos: el nivel 1 siempre activo; el 2 y 3 son defensas más agresivas |
| `RepoIndexer` con `os.walk()` | Eficiente; poda directorios `in-place` (no los visita) |
