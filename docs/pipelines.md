# Pipeline Mode — Workflows YAML Multi-Step

El Pipeline Mode ejecuta workflows definidos en YAML con pasos secuenciales. Cada paso puede tener su propio agente, modelo, prompt, checks, condiciones y variables.

---

## Concepto

Un pipeline define una secuencia de tareas donde cada paso puede depender de los anteriores. Los pasos se comunican entre sí mediante **variables** (`{{nombre}}`) y se pueden condicionar, verificar con checks, y proteger con checkpoints git.

```yaml
name: feature-pipeline
steps:
  - name: analyze
    agent: plan
    prompt: "Analiza los requisitos de {{feature}}"
    output_var: analysis

  - name: implement
    agent: build
    prompt: "Implementa según este análisis: {{analysis}}"
    checks:
      - "pytest tests/ -q"
    checkpoint: true

  - name: review
    agent: review
    prompt: "Revisa la implementación de {{feature}}"
    condition: "run_review == 'true'"
```

---

## Uso básico

```bash
# Ejecutar un pipeline
architect pipeline workflow.yaml --var feature="user auth"

# Ver qué haría sin ejecutar (dry-run)
architect pipeline workflow.yaml --var feature="user auth" --dry-run

# Reanudar desde un paso específico
architect pipeline workflow.yaml --var feature="user auth" --from-step implement

# Con variables múltiples
architect pipeline workflow.yaml \
  --var feature="payment gateway" \
  --var env=staging \
  --var run_review=true
```

---

## Opciones del comando

| Opción | Default | Descripción |
|--------|---------|-------------|
| `PIPELINE_FILE` | (requerido) | Archivo YAML con la definición del pipeline |
| `--var KEY=VALUE` | — | Variable para el pipeline (repetible) |
| `--from-step NAME` | — | Reanudar desde un step específico (salta anteriores) |
| `--dry-run` | `false` | Mostrar plan sin ejecutar agentes |
| `-c, --config PATH` | — | Archivo de configuración YAML de architect |
| `--quiet` | `false` | Solo resultado final |

---

## Formato YAML del pipeline

### Estructura completa

```yaml
name: mi-pipeline                    # Nombre identificativo
variables:                           # Variables iniciales (opcional)
  key: value
steps:
  - name: step-id                    # Identificador único del paso
    agent: build                     # Agente: build, plan, review, resume, o custom
    prompt: "Prompt con {{var}}"     # Prompt con sustitución de variables
    model: gpt-4o                    # Modelo LLM (opcional, override)
    condition: "var == 'true'"       # Condición para ejecutar (opcional)
    output_var: result               # Guardar output como variable (opcional)
    checks:                          # Comandos de verificación post-step (opcional)
      - "pytest tests/"
      - "ruff check src/"
    checkpoint: true                 # Crear git checkpoint (opcional)
    timeout: 300                     # Timeout en segundos (opcional)
```

### Campos de cada step

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `name` | `str` | (requerido) | Identificador del paso |
| `agent` | `str` | `"build"` | Agente a usar |
| `prompt` | `str` | `""` | Prompt con soporte para `{{variables}}` |
| `model` | `str\|null` | `null` | Modelo LLM (null = usar default del config) |
| `condition` | `str\|null` | `null` | Expresión condicional. Si evalúa a falsy, el step se salta |
| `output_var` | `str\|null` | `null` | Nombre de variable donde guardar el output del agente |
| `checks` | `list[str]` | `[]` | Comandos shell post-step (exit 0 = pass) |
| `checkpoint` | `bool` | `false` | Crear git checkpoint al completar el step |
| `timeout` | `int\|null` | `null` | Timeout en segundos |

---

## Características

### Variables (`{{nombre}}`)

Las variables se sustituyen en los prompts antes de la ejecución. Se definen en tres fuentes (menor a mayor prioridad):

1. Sección `variables` del YAML
2. Flag `--var KEY=VALUE` del CLI (sobreescribe YAML)
3. `output_var` de steps anteriores (se añaden dinámicamente)

```yaml
name: var-demo
variables:
  project: myapp
  lang: python
steps:
  - name: analyze
    agent: plan
    prompt: "Analiza el proyecto {{project}} escrito en {{lang}}"
    output_var: analysis

  - name: implement
    agent: build
    prompt: |
      Implementa las mejoras sugeridas:
      {{analysis}}
```

La sustitución usa regex `\{\{(.+?)\}\}`. Variables no definidas se dejan como `{{nombre}}` (no se eliminan).

### Condiciones (`condition`)

Un step con `condition` se evalúa antes de ejecutarse. Si la condición es falsa, el step se salta con status `"skipped"`.

La evaluación es simple:
- `"true"`, `"yes"`, `"1"` → True
- `"false"`, `"no"`, `"0"`, `""` → False
- Cualquier otro string no vacío → True

Las variables se resuelven en la condición antes de evaluar:

```yaml
steps:
  - name: setup
    prompt: "..."

  - name: deploy
    prompt: "Deploy a producción"
    condition: "deploy_enabled == 'true'"
    # Si --var deploy_enabled=true → se ejecuta
    # Si --var deploy_enabled=false → se salta
```

### Output variables (`output_var`)

Captura la salida final del agente y la almacena como variable para steps posteriores:

```yaml
steps:
  - name: analyze
    agent: plan
    prompt: "Analiza el código y lista las 3 mejoras más importantes"
    output_var: improvements

  - name: implement
    agent: build
    prompt: "Implementa estas mejoras: {{improvements}}"
```

El valor capturado es el `final_output` del `AgentState` — el texto que el agente produce como respuesta final.

### Checks

Los checks son comandos shell que se ejecutan después de cada step:

```yaml
steps:
  - name: implement
    prompt: "Implementa la feature"
    checks:
      - "pytest tests/ -q"
      - "ruff check src/"
```

- Cada check se ejecuta como `subprocess.run(cmd, shell=True, timeout=120)`
- **Exit 0** = check pasó
- El resultado se almacena en `PipelineStepResult.checks_passed`
- Los checks no bloquean la ejecución del pipeline — el siguiente step se ejecuta igualmente

### Checkpoints

Con `checkpoint: true`, se crea un git commit automático al completar el step:

```yaml
steps:
  - name: implement
    prompt: "Implementa la feature"
    checkpoint: true
    # → git add -A && git commit -m "architect:checkpoint:implement"
```

El commit usa el prefijo `architect:checkpoint:<step_name>`. Esto permite:
- Ver qué cambió en cada step: `git log --oneline --grep="architect:checkpoint"`
- Rollback a un step específico con `CheckpointManager.rollback()`

### Dry-run

Con `--dry-run`, el pipeline muestra el plan sin ejecutar agentes:

```bash
architect pipeline workflow.yaml --var feature="auth" --dry-run
```

Output:
```
Pipeline: feature-pipeline
  Step 1: analyze (plan) — "Analiza los requisitos de auth"
  Step 2: implement (build) — "Implementa según este análisis: {{analysis}}"
    Checks: pytest tests/ -q, ruff check src/
    Checkpoint: sí
  Step 3: review (review) — "Revisa la implementación de auth"
    Condition: run_review == 'true'
```

### From-step (resume)

Con `--from-step`, el pipeline salta los steps anteriores y empieza desde el indicado:

```bash
# El step "analyze" ya se ejecutó. Reanudar desde "implement"
architect pipeline workflow.yaml --from-step implement
```

---

## Flujo interno

```
architect pipeline workflow.yaml --var feature="auth"
  │
  ├── 1. PipelineRunner.from_yaml(path, variables)
  │       ├── yaml.safe_load(file)
  │       ├── Merge variables YAML + CLI
  │       └── Construir PipelineConfig con steps
  │
  ├── 2. runner.run(from_step=None, dry_run=False)
  │       │
  │       ├── Para cada step:
  │       │   ├── 2a. _eval_condition(condition) → skip si False
  │       │   ├── 2b. _resolve_vars(prompt) → sustituir {{variables}}
  │       │   ├── 2c. agent_factory(agent=step.agent, model=step.model)
  │       │   │       └── AgentLoop fresco con ContextBuilder, CostTracker, etc.
  │       │   ├── 2d. agent.run(resolved_prompt) → AgentState
  │       │   ├── 2e. Si output_var: variables[output_var] = state.final_output
  │       │   ├── 2f. Si checks: _run_checks(checks) → checks_passed
  │       │   ├── 2g. Si checkpoint: _create_checkpoint(step_name)
  │       │   └── 2h. Registrar PipelineStepResult
  │       │
  │       └── Retornar list[PipelineStepResult]
  │
  └── 3. Mostrar resultados
```

---

## API Python

### PipelineConfig

```python
@dataclass
class PipelineConfig:
    name: str                          # Nombre del pipeline
    steps: list[PipelineStep]          # Pasos secuenciales
    variables: dict[str, str]          # Variables iniciales
```

### PipelineStep

```python
@dataclass
class PipelineStep:
    name: str                          # Identificador
    agent: str = "build"               # Agente a usar
    prompt: str = ""                   # Prompt (soporta {{variables}})
    model: str | None = None           # Modelo LLM override
    checkpoint: bool = False           # Crear git checkpoint
    condition: str | None = None       # Condición para ejecutar
    output_var: str | None = None      # Variable donde guardar output
    checks: list[str] = []            # Comandos de verificación
    timeout: int | None = None         # Timeout en segundos
```

### PipelineRunner

```python
class PipelineRunner:
    def __init__(
        self,
        config: PipelineConfig,
        agent_factory: Callable[..., Any],
        workspace_root: str | None = None,
    ) -> None: ...

    def run(
        self,
        from_step: str | None = None,
        dry_run: bool = False,
    ) -> list[PipelineStepResult]: ...

    def get_plan_summary(self) -> str: ...

    @classmethod
    def from_yaml(
        cls,
        path: str,
        variables: dict[str, str],
        agent_factory: Callable[..., Any],
        workspace_root: str | None = None,
    ) -> "PipelineRunner": ...
```

### PipelineStepResult

```python
@dataclass
class PipelineStepResult:
    step_name: str                     # Identificador del paso
    status: str                        # "success", "partial", "failed", "skipped", "dry_run"
    cost: float = 0.0                  # Coste USD
    duration: float = 0.0              # Segundos
    checks_passed: bool = True         # True si todos los checks pasaron
    error: str | None = None           # Mensaje de error
```

---

## Ejemplos

### Pipeline de feature completa

```yaml
name: feature-pipeline
variables:
  branch: feature/auth
steps:
  - name: plan
    agent: plan
    prompt: |
      Analiza el proyecto y planifica cómo implementar
      autenticación JWT. Lista los archivos a modificar
      y el orden de los cambios.
    output_var: plan

  - name: implement
    agent: build
    prompt: |
      Ejecuta este plan paso a paso:
      {{plan}}
    model: gpt-4o
    checks:
      - "pytest tests/ -q"
      - "ruff check src/"
    checkpoint: true

  - name: docs
    agent: build
    prompt: "Actualiza la documentación para reflejar los cambios de autenticación"
    checkpoint: true
```

### Pipeline de CI/CD

```yaml
name: ci-review
variables:
  base_branch: origin/main
steps:
  - name: review
    agent: review
    prompt: "Revisa los cambios de este PR respecto a {{base_branch}}"
    output_var: review_result

  - name: fix
    agent: build
    prompt: "Corrige estos problemas encontrados en la review: {{review_result}}"
    condition: "auto_fix == 'true'"
    checks:
      - "pytest tests/ -q"
```

```bash
architect pipeline ci-review.yaml \
  --var base_branch=origin/main \
  --var auto_fix=true
```

### Pipeline con múltiples modelos

```yaml
name: multi-model
steps:
  - name: draft
    agent: build
    model: gpt-4o-mini          # Modelo rápido para el draft
    prompt: "Genera un primer borrador de tests para auth.py"
    output_var: draft

  - name: refine
    agent: build
    model: claude-sonnet-4-6    # Modelo más capaz para refinar
    prompt: "Mejora y completa estos tests: {{draft}}"
    checks:
      - "pytest tests/test_auth.py -v"
```
