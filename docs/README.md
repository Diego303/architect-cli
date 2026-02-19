# Documentación técnica — architect CLI

Índice de la documentación interna del proyecto. Orientada a desarrolladores e IAs que necesitan entender, modificar o extender el sistema.

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| [`usage.md`](usage.md) | **Formas de uso**: flags, logging, configs, CI/CD, scripts, agentes custom, multi-proyecto |
| [`architecture.md`](architecture.md) | Visión general, diagrama de componentes y flujo completo de ejecución |
| [`core-loop.md`](core-loop.md) | El loop de agente paso a paso, streaming, shutdown y timeout |
| [`data-models.md`](data-models.md) | Todos los modelos de datos: Pydantic, dataclasses, jerarquía de errores |
| [`tools-and-execution.md`](tools-and-execution.md) | Sistema de tools, validación de paths, políticas de confirmación, ExecutionEngine |
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
         ├─ LLMAdapter            LiteLLM + retries selectivos
         │
         └─ AgentLoop (o MixedModeRunner)
                 │
                 ├─ [check shutdown]   SIGINT/SIGTERM graceful
                 ├─ [StepTimeout]      SIGALRM por step
                 ├─ llm.completion()   → streaming chunks a stderr
                 ├─ engine.execute()   → validar → confirmar → ejecutar
                 └─ ctx.append_results() → siguiente iteración
```

**Stack**: Python 3.12+, Click, Pydantic v2, LiteLLM, httpx, structlog, tenacity.

**Versión actual**: 0.8.0
