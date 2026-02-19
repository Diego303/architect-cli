# Arquitectura del sistema

## Mapa de componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLI (cli.py)                                                       │
│                                                                     │
│  architect run PROMPT                                               │
│     │                                                               │
│     ├─ 1. GracefulShutdown()          instala SIGINT + SIGTERM      │
│     ├─ 2. load_config()               YAML → env → CLI flags        │
│     ├─ 3. configure_logging()         stderr + opcional JSON file   │
│     ├─ 4. ToolRegistry                                              │
│     │       └─ register_filesystem_tools()                          │
│     │       └─ MCPDiscovery.discover_and_register()  (opcional)     │
│     ├─ 5. LLMAdapter(config.llm)                                    │
│     ├─ 6. ContextBuilder()                                          │
│     ├─ 7a. AgentLoop (modo single-agent, -a flag)                   │
│     │       └─ ExecutionEngine(registry, config, confirm_mode)      │
│     └─ 7b. MixedModeRunner (modo mixto, sin -a)                     │
│             ├─ plan_engine + plan_loop                              │
│             └─ build_engine + build_loop                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Diagrama de módulos y dependencias

```
cli.py
 ├── config/loader.py ──── config/schema.py
 ├── logging/setup.py
 ├── tools/setup.py ────── tools/registry.py
 │                          tools/filesystem.py ── tools/base.py
 │                                                  tools/schemas.py
 │                          execution/validators.py
 ├── mcp/discovery.py ──── mcp/client.py
 │                          mcp/adapter.py ──────── tools/base.py
 ├── llm/adapter.py
 ├── core/context.py
 ├── core/loop.py ──────── core/state.py
 │                          core/shutdown.py
 │                          core/timeout.py
 ├── core/mixed_mode.py ── core/loop.py
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
ToolRegistry.register(read_file, write_file, delete_file, list_files)
     │
MCPDiscovery.discover_and_register()  ─── si hay servidores MCP config
     │
get_agent("build", yaml_agents, cli_overrides)
     │  → AgentConfig{system_prompt, allowed_tools, confirm_mode, max_steps}
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
     │         → LLMResponse(tool_calls=[ToolCall("write_file", {...})])
     │     │
     │     for tc in tool_calls:
     │       engine.execute_tool_call("write_file", {path:..., content:...})
     │         1. registry.get("write_file")
     │         2. tool.validate_args(args)    → WriteFileArgs
     │         3. policy.should_confirm()     → si True: prompt usuario y/n/a
     │         4. si dry_run: return [DRY-RUN]
     │         5. WriteFileTool.execute()
     │              └─ validate_path() ─ confinamiento workspace
     │              └─ file.write_text()
     │              └─ return ToolResult(success=True)
     │         6. log result
     │     │
     │     ctx.append_tool_results(messages, tool_calls, results)
     │     state.steps.append(StepResult(...))
     │
     ├── [iter 2]
     │     llm.completion(...)
     │       → LLMResponse(finish_reason="stop", content="He reescrito...")
     │     status="success", final_output="He reescrito..."
     │     break
     │
state.status = "success"

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
     │     plan_loop = AgentLoop(llm, plan_engine, plan_config, ...)
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
     │     build_loop = AgentLoop(llm, build_engine, build_config, ...)
     │     build_state = build_loop.run(enriched_prompt, stream=True, ...)
     │
     └── return build_state
```

---

## Separación stdout / stderr

Esta separación es crítica para compatibilidad con pipes Unix.

```
┌─────────────────────────┬──────────────────────────────────────────┐
│ Destino                 │ Contenido                                │
├─────────────────────────┼──────────────────────────────────────────┤
│ stderr                  │ Streaming chunks del LLM en tiempo real  │
│ stderr                  │ Logs estructurados (structlog)           │
│ stderr                  │ Header de ejecución (modelo, workspace)  │
│ stderr                  │ Estadísticas de MCP                      │
│ stderr                  │ Avisos de confirmación                   │
│ stderr                  │ Avisos de shutdown (Ctrl+C)              │
├─────────────────────────┼──────────────────────────────────────────┤
│ stdout                  │ Respuesta final del agente               │
│ stdout                  │ Output JSON (--json)                     │
└─────────────────────────┴──────────────────────────────────────────┘

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
| 2 | `EXIT_PARTIAL` | Parcial — hizo parte del trabajo, no completó |
| 3 | `EXIT_CONFIG_ERROR` | Error de configuración o archivo YAML no encontrado |
| 4 | `EXIT_AUTH_ERROR` | Error de autenticación LLM (API key inválida) |
| 5 | `EXIT_TIMEOUT` | Timeout en llamada LLM |
| 130 | `EXIT_INTERRUPTED` | Interrumpido por Ctrl+C (POSIX: 128 + SIGINT=2) |

Los errores de autenticación (exit 4) y timeout (exit 5) se detectan por keywords en el mensaje de error de LiteLLM, ya que LiteLLM puede lanzar varios tipos de excepción para el mismo error conceptual.

---

## Decisiones de diseño

| Decisión | Justificación |
|----------|---------------|
| Sync-first (no asyncio) | Predecible, debuggable; las llamadas al LLM son la única latencia |
| Sin LangChain/LangGraph | El loop es simple (~150 líneas); añadir abstracción oscurecería el flujo |
| Pydantic v2 como fuente de verdad | Validación, serialización y documentación en un solo sitio |
| Tools nunca lanzan excepciones | El loop de agente permanece estable ante cualquier fallo de tool |
| stdout limpio | Pipes Unix: `architect run ... | jq .` funciona sin filtrar |
| MCP tools = BaseTool | Registro unificado; el agente no distingue entre local y remoto |
| Retries selectivos | Solo errores transitorios (rate limit, conexión); auth errors fallan rápido |
| SIGALRM para timeouts | Por-step, no global; permite reanudar en el siguiente step si hay timeout |
