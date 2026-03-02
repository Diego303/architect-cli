# Ralph Loop — Iteración Automática con Checks

El Ralph Loop ejecuta un agente de forma iterativa hasta que un conjunto de verificaciones (checks) pasen. Cada iteración recibe un **contexto completamente limpio** — no arrastra historial de iteraciones anteriores.

---

## Concepto

El patrón Ralph Loop resuelve un problema común: ejecutar un agente que modifica código y luego verificar que las modificaciones son correctas (tests, lint, type check). Si los checks fallan, el agente debe intentar de nuevo con información sobre los errores.

```
Iteración 1:  Agent → modifica código → checks fallan (test error en line 42)
Iteración 2:  Agent → recibe error + diff → corrige → checks fallan (lint warning)
Iteración 3:  Agent → recibe error + diff → corrige → checks pasan ✓
```

La clave es el **contexto limpio**: cada iteración crea un `AgentLoop` completamente nuevo. El agente solo recibe:

1. La spec original (archivo o prompt)
2. El diff acumulado de todas las iteraciones anteriores
3. Los errores de los checks de la iteración anterior
4. Un `progress.md` auto-generado con el historial

Esto evita la contaminación del contexto y permite iteraciones largas sin degradación.

---

## Uso básico

```bash
# Iterar hasta que tests pasen
architect loop "implementa autenticación JWT" \
  --check "pytest tests/test_auth.py"

# Múltiples checks — TODOS deben pasar
architect loop "refactoriza el módulo de pagos" \
  --check "pytest tests/" \
  --check "ruff check src/" \
  --check "mypy src/"
```

### Con spec file

Para tareas complejas, puedes definir la especificación en un archivo Markdown:

```bash
architect loop "implementar según spec" \
  --spec requirements/auth-spec.md \
  --check "pytest tests/test_auth.py" \
  --check "ruff check src/auth/"
```

El contenido del spec file se inyecta en el prompt de cada iteración en lugar del texto del argumento `TASK`.

### Con worktree aislado

```bash
architect loop "migrar de SQLAlchemy a Tortoise ORM" \
  --check "pytest tests/" \
  --worktree \
  --max-iterations 10
```

Con `--worktree`, el loop crea un git worktree aislado (`.architect-ralph-worktree`). Si todos los checks pasan, el resultado incluye la ruta al worktree para inspección o merge manual.

---

## Opciones

| Opción | Default | Descripción |
|--------|---------|-------------|
| `--check CMD` | (requerido) | Comando de verificación shell. Repetible. Todos deben pasar (exit 0) |
| `--spec PATH` | — | Archivo de especificación. Se usa en vez del argumento TASK |
| `--max-iterations N` | 25 | Máximo de iteraciones antes de parar |
| `--max-cost FLOAT` | — | Límite de coste en USD. Se detiene si se supera |
| `--max-time INT` | — | Límite de tiempo total en segundos |
| `--completion-tag TAG` | `COMPLETE` | Tag que el agente debe emitir cuando considere que terminó |
| `--agent NAME` | `build` | Agente a usar en cada iteración |
| `--model MODEL` | — | Modelo LLM (override del config) |
| `-c, --config PATH` | — | Archivo de configuración YAML |
| `--worktree` | `false` | Ejecutar en un git worktree aislado |
| `--quiet` | `false` | Solo resultado final, sin logs de iteraciones |

---

## Cómo funciona internamente

### Flujo de una ejecución

```
architect loop "task" --check "pytest" --check "ruff check src/"
  │
  ├── 1. Capturar ref inicial: git rev-parse HEAD → initial_ref
  ├── 2. (Opcional) Crear worktree: .architect-ralph-worktree
  │
  ├── LOOP:
  │   ├── 3. Construir prompt limpio (_build_iteration_prompt)
  │   │       ├── Spec/task original
  │   │       ├── Instrucciones de iteración (nº, checks, completion_tag)
  │   │       ├── Diff acumulado: git diff <initial_ref> (truncado 5000 chars)
  │   │       ├── Errores de checks previos (truncado 2000 chars/check)
  │   │       └── Contenido de .architect/ralph-progress.md
  │   │
  │   ├── 4. agent_factory() → AgentLoop fresco
  │   ├── 5. agent.run(prompt) → AgentState
  │   │
  │   ├── 6. _run_checks() → ejecutar cada check como subprocess
  │   │       └── subprocess.run(cmd, shell=True, timeout=120, cwd=workspace)
  │   │
  │   ├── 7. _update_progress() → escribir iteración a .architect/ralph-progress.md
  │   │
  │   ├── 8. ¿Todos los checks pasaron Y completion_tag encontrado?
  │   │       ├── SÍ → success, salir del loop
  │   │       └── NO → ¿Safety nets?
  │   │               ├── max_iterations alcanzado → stop
  │   │               ├── max_cost superado → stop
  │   │               ├── max_time excedido → stop
  │   │               └── Continuar al siguiente iteration
  │   └── (vuelve a 3)
  │
  ├── 9. (Opcional) Resultado incluye worktree_path
  └── 10. Retornar RalphLoopResult
```

### Contexto limpio por iteración

Cada iteración invoca `agent_factory()` que crea un `AgentLoop` completamente nuevo. No se comparte ningún estado entre iteraciones:

- Nuevo `ContextBuilder` (sin mensajes previos)
- Nuevo `CostTracker` (el coste se acumula externamente)
- Nuevo `ExecutionEngine` con guardrails frescos

Lo único que conecta iteraciones es el **filesystem** (los archivos modificados persisten) y el **prompt** (que incluye el diff acumulado y los errores).

### Checks

Los checks son comandos shell ejecutados como subprocesos:

```python
subprocess.run(cmd, shell=True, capture_output=True, timeout=120, cwd=workspace_root)
```

- **Exit code 0** = check pasó
- **Cualquier otro exit code** = check falló
- **Timeout** (120s por defecto) = check falló con mensaje "Timeout"
- El output (stdout + stderr) se trunca a los últimos 2000 caracteres
- Los checks se ejecutan en el directorio del workspace (o worktree)

### Progress file

Después de cada iteración, se escribe `.architect/ralph-progress.md`:

```markdown
## Iteración 1 — FAIL
- Steps: 8
- Coste: $0.0234
- Duración: 15.2s
- Checks:
  - pytest tests/: PASS
  - ruff check src/: FAIL — src/auth.py:42:1: F841 local variable 'x' is assigned to but never used

## Iteración 2 — PASS
- Steps: 3
- Coste: $0.0089
- Duración: 5.1s
- Checks:
  - pytest tests/: PASS
  - ruff check src/: PASS
```

Este archivo se incluye en el prompt de iteraciones posteriores para que el agente tenga visibilidad del progreso.

---

## Safety nets

El loop se detiene automáticamente si se cumple alguna de estas condiciones:

| Condición | Configuración | Comportamiento |
|-----------|---------------|----------------|
| Iteraciones | `--max-iterations 25` | Para después de N iteraciones sin éxito |
| Coste | `--max-cost 5.0` | Para si el coste acumulado supera el límite |
| Tiempo | `--max-time 600` | Para si la duración total supera N segundos |

El resultado (`RalphLoopResult`) indica la razón de parada en `stop_reason`:
- `"all_checks_passed"` — todos los checks pasaron (éxito)
- `"max_iterations"` — se agotaron las iteraciones
- `"budget_exhausted"` — se superó el presupuesto
- `"timeout"` — se superó el tiempo máximo

---

## Worktrees

Con `--worktree`, el loop crea un git worktree aislado:

1. **Creación**: `git worktree add -b architect/ralph-loop .architect-ralph-worktree HEAD`
2. **Ejecución**: Todas las iteraciones trabajan en el worktree
3. **Resultado**: Si los checks pasan, `result.worktree_path` contiene la ruta

El worktree no se elimina automáticamente — puedes inspeccionarlo, hacer cherry-pick, o merge manual:

```bash
# Ver qué cambió
cd .architect-ralph-worktree
git diff HEAD~1

# Merge al branch principal
git checkout main
git merge architect/ralph-loop

# Limpiar manualmente
git worktree remove .architect-ralph-worktree
git branch -D architect/ralph-loop
```

---

## Configuración YAML

```yaml
ralph_loop:
  max_iterations: 25        # 1-100
  max_cost: null             # USD, null = sin límite
  max_time: null             # segundos, null = sin límite
  completion_tag: "COMPLETE" # tag que el agente emite
  agent: build               # agente por defecto
```

---

## API Python

### RalphConfig

```python
@dataclass
class RalphConfig:
    task: str                           # Descripción de la tarea
    checks: list[str]                   # Comandos de verificación (deben retornar exit 0)
    spec_file: str | None = None        # Archivo de especificación (sustituye task en prompt)
    completion_tag: str = "COMPLETE"     # Tag de completación
    max_iterations: int = 25            # Máximo de iteraciones
    max_cost: float | None = None       # Límite USD
    max_time: int | None = None         # Límite en segundos
    agent: str = "build"                # Agente a usar
    model: str | None = None            # Modelo LLM
    use_worktree: bool = False          # Usar git worktree
```

### RalphLoop

```python
class RalphLoop:
    def __init__(
        self,
        config: RalphConfig,
        agent_factory: Callable[..., Any],  # (**kwargs) → AgentLoop
        workspace_root: str | None = None,
    ) -> None: ...

    def run(self) -> RalphLoopResult: ...
    def cleanup_worktree(self) -> bool: ...
    def cleanup_progress(self) -> None: ...
```

### RalphLoopResult

```python
@dataclass
class RalphLoopResult:
    iterations: list[LoopIteration]     # Todas las iteraciones
    total_cost: float = 0.0             # Coste acumulado USD
    total_duration: float = 0.0         # Duración total en segundos
    success: bool = False               # True si checks pasaron
    stop_reason: str = ""               # "all_checks_passed", "max_iterations", etc.
    worktree_path: str = ""             # Ruta al worktree (si se usó)

    @property
    def total_iterations(self) -> int: ...
```

### LoopIteration

```python
@dataclass
class LoopIteration:
    iteration: int                      # Número (1-based)
    steps_taken: int                    # Pasos del agente
    cost: float                         # Coste USD de esta iteración
    duration: float                     # Duración en segundos
    check_results: list[dict]           # [{name, passed, output}]
    all_checks_passed: bool             # True si todos pasaron
    completion_tag_found: bool          # True si el agente emitió el tag
    error: str | None = None            # Error de ejecución (si hubo)
```

---

## Salida visual (HUMAN logging)

A partir de v1.1.0, el Ralph Loop emite eventos de nivel HUMAN que producen una salida visual clara en stderr. El usuario puede ver en tiempo real el progreso de cada iteración sin necesidad de flags `-v`.

```
━ Ralph iteration 1/5 (check: pytest tests/) ━━━━━━━━━━━━━━━━
   🧪 Checks: 3/5 passed
   ✗ Iteration 1 → partial ($0.0234, 45.2s)

━ Ralph iteration 2/5 (check: pytest tests/) ━━━━━━━━━━━━━━━━
   🧪 Checks: 5/5 passed ✓
   ✓ Iteration 2 → success ($0.0189, 32.1s)

✅ Ralph complete — 2 iterations, success ($0.0423)
```

### Eventos emitidos

| Evento | Cuándo | Datos |
|--------|--------|-------|
| `ralph.iteration_start` | Al inicio de cada iteración | iteration, max_iterations, check_cmd |
| `ralph.checks_result` | Después de ejecutar los checks | iteration, passed, total, all_passed |
| `ralph.iteration_done` | Al completar cada iteración | iteration, status, cost, duration |
| `ralph.complete` | Al finalizar el loop (cualquier razón) | total_iterations, status, total_cost |

Se desactiva con `--quiet` o `--json`. Ver [`logging.md`](logging.md) para detalles del sistema HUMAN.

---

## Ejemplos avanzados

### Loop con budget y timeout

```bash
architect loop "implementa feature X según la spec" \
  --spec spec.md \
  --check "pytest tests/ -x" \
  --check "ruff check src/" \
  --max-iterations 10 \
  --max-cost 3.0 \
  --max-time 600 \
  --model gpt-4o
```

### Loop en CI/CD

```yaml
# GitHub Actions
- name: Implementar y verificar
  run: |
    architect loop "${{ github.event.issue.body }}" \
      --spec spec.md \
      --check "pytest tests/ -q" \
      --check "ruff check src/" \
      --max-iterations 5 \
      --max-cost 2.0 \
      --quiet
```

### Loop con worktree para experimentar

```bash
# Ejecutar en worktree aislado
architect loop "migra a async/await" \
  --check "pytest tests/" \
  --worktree \
  --max-iterations 15

# Si tuvo éxito, inspeccionar y merge
git diff main...architect/ralph-loop
git merge architect/ralph-loop
```
