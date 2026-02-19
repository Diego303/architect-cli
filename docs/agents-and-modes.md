# Sistema de agentes y modos de ejecución

---

## Agentes por defecto

Definidos en `agents/registry.py` como `DEFAULT_AGENTS: dict[str, AgentConfig]`.

| Agente | Tools disponibles | confirm_mode | max_steps | Propósito |
|--------|-------------------|--------------|-----------|-----------|
| `plan` | `read_file`, `list_files` | `confirm-all` | 10 | Analiza la tarea y genera un plan estructurado. Solo lectura. |
| `build` | `read_file`, `write_file`, `delete_file`, `list_files` | `confirm-sensitive` | 20 | Ejecuta tareas: crea y modifica archivos. |
| `resume` | `read_file`, `list_files` | `yolo` | 10 | Lee y resume información. Solo lectura, sin confirmaciones. |
| `review` | `read_file`, `list_files` | `yolo` | 15 | Revisa código y da feedback. Solo lectura, sin confirmaciones. |

---

## System prompts (`agents/prompts.py`)

### `PLAN_PROMPT`
- Rol: analista y planificador.
- **Nunca ejecuta acciones** — su output es el plan, no los cambios.
- Formato de output esperado: `## Resumen / ## Pasos / ## Archivos afectados / ## Consideraciones`.
- Ideal para: entender el alcance de una tarea antes de ejecutarla.

### `BUILD_PROMPT`
- Rol: ejecutor cuidadoso.
- Flujo: lee el código primero, luego modifica, luego verifica.
- Cambios incrementales y conservadores.
- Al terminar: resume los cambios realizados.
- Ideal para: crear, modificar o refactorizar código.

### `RESUME_PROMPT`
- Rol: analista de sólo-lectura.
- Nunca modifica archivos.
- Output estructurado con bullets.
- Ideal para: entender un proyecto rápidamente.

### `REVIEW_PROMPT`
- Rol: revisor de código constructivo.
- Prioriza issues: crítico / importante / menor.
- Categorías: bugs, seguridad, performance, código limpio.
- Nunca modifica archivos.
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
      Eres un agente de deployment...
    allowed_tools:
      - read_file
      - list_files
      - write_file
    confirm_mode: confirm-all
    max_steps: 10
```

### Override parcial de un default

```yaml
agents:
  build:
    confirm_mode: confirm-all   # solo cambia esto; max_steps, tools, prompt = defaults
```

---

## Modos de ejecución

### Single-agent (`-a nombre`)

```
AgentLoop(llm, engine, agent_config, ctx, shutdown, step_timeout)
  └─ run(prompt, stream, on_stream_chunk)
```

El agente especificado ejecuta el prompt directamente. El `engine` usa el `confirm_mode` del agente (a menos que `--mode` lo sobreescriba).

### Modo mixto (sin `-a`)

El modo por defecto. Ejecuta dos agentes en secuencia.

```
MixedModeRunner(llm, plan_engine, plan_config, build_engine, build_config, ...)
  └─ run(prompt, stream, on_stream_chunk)
       │
       ├─ FASE 1: plan (sin streaming, confirm-all)
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

**Nota importante**: En modo mixto se crean **dos `ExecutionEngine` distintos**:
- `plan_engine` con `confirm_mode="confirm-all"` y tools `read_file`, `list_files`.
- `build_engine` con `confirm_mode="confirm-sensitive"` y todas las tools.

Esto permite que el usuario configure `--mode yolo` solo para el build sin afectar el plan, que nunca modifica archivos y por tanto puede usar confirm-all sin peligro.

---

## Selección de tools por agente

`AgentConfig.allowed_tools` filtra qué tools del registry están disponibles:

```python
tools_schema = registry.get_schemas(agent_config.allowed_tools or None)
# [] o None → todas las tools registradas
# ["read_file", "list_files"] → solo esas dos
```

Si el LLM intenta llamar a una tool no permitida (ej: `write_file` cuando solo tiene `read_file`), el `ExecutionEngine` la rechaza con `ToolNotFoundError` convertido en `ToolResult(success=False)`. El error vuelve al LLM como mensaje de tool, y el LLM puede adaptar su estrategia.

---

## Listing de agentes (`architect agents`)

El subcomando `architect agents` muestra todos los agentes disponibles:

```bash
$ architect agents
Agentes disponibles:
  plan    [confirm-all]       Analiza y planifica sin ejecutar
  build   [confirm-sensitive] Crea y modifica archivos del workspace
  resume  [yolo]              Lee y resume información del proyecto
  review  [yolo]              Revisa código y genera feedback

$ architect agents -c config.yaml
Agentes disponibles:
  plan    [confirm-all]       Analiza y planifica sin ejecutar
  build * [confirm-all]       Crea y modifica archivos del workspace  ← override
  resume  [yolo]              Lee y resume información del proyecto
  review  [yolo]              Revisa código y genera feedback
  deploy  [confirm-all]       Agente de deployment custom
```

El `*` indica que ese agente tiene un override en el YAML (algún campo del default fue sobreescrito).
