# Sistema de agentes y modos de ejecución

---

## Agentes por defecto

Definidos en `agents/registry.py` como `DEFAULT_AGENTS: dict[str, AgentConfig]`.

| Agente | Tools disponibles | confirm_mode | max_steps | Propósito |
|--------|-------------------|--------------|-----------|-----------|
| `plan` | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 20 | Analiza la tarea y genera un plan estructurado. Solo lectura. (v3: yolo porque plan no modifica archivos) |
| `build` | todas las tools (filesystem + edición + búsqueda + `run_command`) | `confirm-sensitive` | 50 | Ejecuta tareas: crea y modifica archivos con herramientas completas. (v3: safety net, no driver del loop) |
| `resume` | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 15 | Lee y resume información. Solo lectura, sin confirmaciones. |
| `review` | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 20 | Revisa código y da feedback. Solo lectura, sin confirmaciones. |

Las tools de búsqueda (`search_code`, `grep`, `find_files`) están disponibles para todos los agentes desde F10. El agente `build` tiene acceso adicional a `edit_file` y `apply_patch` para edición incremental.

---

## System prompts (`agents/prompts.py`)

### `PLAN_PROMPT`
- Rol: analista y planificador.
- **Nunca ejecuta acciones** — su output es el plan, no los cambios.
- Formato de output esperado: `## Resumen / ## Pasos / ## Archivos afectados / ## Consideraciones`.
- Incluye guía de herramientas de búsqueda (cuándo usar `search_code` vs `grep` vs `find_files`).
- Ideal para: entender el alcance de una tarea antes de ejecutarla.

### `BUILD_PROMPT`
- Rol: ejecutor cuidadoso.
- Flujo: lee el código primero, luego modifica, luego verifica.
- **Jerarquía de edición explícita**:
  1. `edit_file` — cambio de un único bloque contiguo (preferido).
  2. `apply_patch` — múltiples cambios o diff preexistente.
  3. `write_file` — archivos nuevos o reorganizaciones completas.
- Cambios incrementales y conservadores.
- Al terminar: resume los cambios realizados.
- Ideal para: crear, modificar o refactorizar código.

### `RESUME_PROMPT`
- Rol: analista de sólo-lectura.
- Nunca modifica archivos.
- Output estructurado con bullets.
- Puede usar `search_code` para encontrar implementaciones específicas.
- Ideal para: entender un proyecto rápidamente.

### `REVIEW_PROMPT`
- Rol: revisor de código constructivo.
- Prioriza issues: crítico / importante / menor.
- Categorías: bugs, seguridad, performance, código limpio.
- Nunca modifica archivos.
- Puede usar `grep` para buscar patrones problemáticos a lo largo del proyecto.
- Ideal para: auditar calidad de código.

---

## Agent registry — resolución de agentes

`agents/registry.py` define cómo se resuelve un agente dado su nombre.

### Precedencia de merge (menor a mayor):

```
1. DEFAULT_AGENTS[name]          (si existe el nombre en defaults)
2. YAML override (config.agents) (solo campos especificados)
3. CLI overrides (--mode, --max-steps)
```

El merge es selectivo: `model_copy(update=yaml.model_dump(exclude_unset=True))`. Solo se sobreescriben los campos que el YAML define explícitamente; los demás se mantienen del default.

### `get_agent(name, yaml_agents, cli_overrides)` → `AgentConfig | None`

```python
# Retorna None si name es None → modo mixto
# Lanza AgentNotFoundError si name no existe en defaults ni en YAML

config = DEFAULT_AGENTS.get(name) or _build_from_yaml(name, yaml_agents)
config = _merge_agent_config(config, yaml_agents.get(name))
config = _apply_cli_overrides(config, cli_overrides)
return config
```

### Agente custom completo (solo en YAML)

```yaml
agents:
  deploy:
    system_prompt: |
      Eres un agente de deployment especializado.
      Verifica tests, revisa CI/CD, genera reporte antes de actuar.
    allowed_tools:
      - read_file
      - list_files
      - search_code
      - write_file
    confirm_mode: confirm-all
    max_steps: 15
```

### Override parcial de un default

```yaml
agents:
  build:
    confirm_mode: confirm-all   # solo cambia esto; max_steps, tools, prompt = defaults
```

---

## Modos de ejecución

### Single-agent — modo por defecto

El agente `build` se usa por defecto si no se especifica `-a`. Con `-a nombre` se puede seleccionar cualquier otro agente.

```
AgentLoop(llm, engine, agent_config, ctx, shutdown, step_timeout, context_manager, cost_tracker, timeout)
  └─ run(prompt, stream, on_stream_chunk)
```

El agente especificado ejecuta el prompt directamente. El `engine` usa el `confirm_mode` del agente (a menos que `--mode` lo sobreescriba).

### Modo mixto (sin `-a`) — legacy

Ya no es el modo por defecto desde v0.15.0 (v3-M3). El agente `build` se usa directamente como default.

Si se necesita el modo mixto plan→build, se puede invocar `MixedModeRunner` programáticamente, pero la CLI ya no lo usa como default. Para un flujo plan→build desde CLI, ejecutar primero `-a plan` y luego `-a build`.

```
MixedModeRunner(llm, engine, plan_config, build_config, context_builder,
                shutdown, step_timeout, context_manager, cost_tracker)
  └─ run(prompt, stream, on_stream_chunk)
       │
       ├─ FASE 1: plan (sin streaming, yolo)
       │     plan_loop.run(prompt, stream=False)
       │     → plan_state.final_output = "## Pasos\n1. Leer main.py\n2. ..."
       │
       ├─ si plan falla → return plan_state
       ├─ si shutdown → return plan_state
       │
       └─ FASE 2: build (con streaming, confirm-sensitive)
             enriched_prompt = f"""
             El usuario pidió: {prompt}

             Plan generado:
             ---
             {plan_state.final_output}
             ---
             Tu trabajo es ejecutar este plan paso a paso.
             Usa las tools disponibles para completar cada paso.
             """
             build_loop.run(enriched_prompt, stream=True, ...)
```

El plan enriquece el contexto del build agent. El build agent no parte de cero — ya sabe qué hacer y en qué orden.

**Nota importante**: En modo mixto se crean **dos `AgentLoop` distintos** pero comparten el mismo `ExecutionEngine`. Cada loop usa su propia `AgentConfig` (plan o build), lo que determina las tools disponibles y el confirm_mode.

El `ContextManager` se **comparte** entre ambas fases para mantener una contabilidad coherente del contexto. El `CostTracker` se comparte entre ambas fases para que el presupuesto sea global. El `SelfEvaluator` se aplica sobre el resultado final del `build_loop`.

---

## Selección de tools por agente

`AgentConfig.allowed_tools` filtra qué tools del registry están disponibles:

```python
tools_schema = registry.get_schemas(agent_config.allowed_tools or None)
# [] o None → todas las tools registradas
# ["read_file", "list_files", "search_code"] → solo esas tres
```

Si el LLM intenta llamar a una tool no permitida (ej: `edit_file` cuando solo tiene `read_file`), el `ExecutionEngine` la rechaza con `ToolNotFoundError` convertido en `ToolResult(success=False)`. El error vuelve al LLM como mensaje de tool, y el LLM puede adaptar su estrategia.

### Tools disponibles por agente (con alias)

```
Agente plan / resume / review:
  ✓ read_file       — leer cualquier archivo
  ✓ list_files      — listar directorio
  ✓ search_code     — buscar con regex en código
  ✓ grep            — buscar texto literal
  ✓ find_files      — buscar archivos por nombre

Agente build (+ todo lo anterior):
  ✓ write_file      — crear o sobrescribir archivos
  ✓ edit_file       — edición incremental (str-replace)
  ✓ apply_patch     — aplicar unified diff
  ✓ delete_file     — eliminar (requiere allow_delete=true)
  ✓ run_command     — ejecutar comandos del sistema (F13)

Agentes custom: definidos explícitamente en allowed_tools

MCP tools (auto-inyectadas a partir de v0.16.2):
  ✓ mcp_{servidor}_{tool}  — descubiertas automáticamente de los servidores MCP
```

**Nota sobre MCP tools**: Las tools MCP descubiertas se inyectan automáticamente en `allowed_tools` del agente activo. No es necesario listarlas manualmente. Si el agente tiene `allowed_tools` explícito, las tools MCP se añaden al final.

---

## Listing de agentes (`architect agents`)

El subcomando `architect agents` muestra todos los agentes disponibles:

```bash
$ architect agents
Agentes disponibles:
  plan    [yolo]              Analiza y planifica sin ejecutar
  build   [confirm-sensitive] Crea y modifica archivos del workspace
  resume  [yolo]              Lee y resume información del proyecto
  review  [yolo]              Revisa código y genera feedback

$ architect agents -c config.yaml
Agentes disponibles:
  plan    [yolo]              Analiza y planifica sin ejecutar
  build * [confirm-all]       Crea y modifica archivos del workspace  ← override
  resume  [yolo]              Lee y resume información del proyecto
  review  [yolo]              Revisa código y genera feedback
  deploy  [confirm-all]       Agente de deployment custom
```

El `*` indica que ese agente tiene un override en el YAML (algún campo del default fue sobreescrito).

---

## Indexer y system prompt (F10)

Cuando el `RepoIndexer` está habilitado (`indexer.enabled=true`), el `ContextBuilder` inyecta automáticamente el árbol del proyecto en el system prompt de cada agente:

```
Eres un agente de build especializado...

## Estructura del Proyecto

Workspace: /home/user/mi-proyecto
Archivos: 47 archivos | 3,241 líneas

Lenguajes: Python (23), YAML (8), Markdown (6), JSON (4)

src/
├── architect/
│   ├── cli.py              Python    412 líneas
│   ├── config/
│   │   ├── loader.py       Python    156 líneas
│   │   └── schema.py       Python    220 líneas
│   └── core/
│       ├── context.py      Python    287 líneas
│       ├── evaluator.py    Python    387 líneas
│       └── loop.py         Python    201 líneas
└── tests/
    └── test_core.py        Python     89 líneas
```

Esto permite que el agente conozca la estructura del proyecto **antes de leer ningún archivo**, reduciendo el número de llamadas a `list_files` y mejorando la calidad de los planes.

Para repositorios > 300 archivos, se usa una vista compacta agrupada por directorio raíz para no saturar el system prompt.

---

## Contexto inyectado en system prompt (v4 Phase A)

A partir de v0.16.0, el system prompt de cada agente puede recibir contexto adicional de tres fuentes:

### 1. Skills y contexto del proyecto (v4-A3)

El `SkillsLoader` busca `.architect.md`, `AGENTS.md` o `CLAUDE.md` en la raíz del workspace y lo inyecta como `# Instrucciones del Proyecto`. Además, las skills en `.architect/skills/` cuyo `globs` coincida con los archivos activos se inyectan como `# Skill: {name}`.

### 2. Memoria procedural (v4-A4)

Si `memory.enabled: true`, el contenido de `.architect/memory.md` se inyecta en el system prompt. Esto incluye correcciones del usuario detectadas automáticamente en sesiones anteriores.

### 3. Hooks y guardrails en el pipeline

Los hooks del lifecycle (`HookExecutor`) y los guardrails (`GuardrailsEngine`) se integran en el `ExecutionEngine`, no en el system prompt. Los guardrails se evalúan antes de cada tool call, y los hooks pre/post se ejecutan alrededor de cada acción. Ver `tools-and-execution.md` para el pipeline completo de 10 pasos.
