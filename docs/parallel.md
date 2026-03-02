# Ejecución Paralela — Múltiples Agentes en Worktrees

Ejecuta múltiples tareas en paralelo, cada una en un git worktree aislado con total independencia.

---

## Concepto

La ejecución paralela permite lanzar varios agentes simultáneamente, cada uno trabajando en una copia aislada del repositorio (git worktree). Esto es útil para:

- Ejecutar la misma tarea con diferentes modelos y comparar resultados
- Dividir trabajo independiente entre workers paralelos
- Experimentar con múltiples enfoques simultáneamente

Cada worker se ejecuta como un subproceso (`architect run --json --confirm-mode yolo`) en su propio worktree, con aislamiento total de archivos.

---

## Uso

```bash
# Misma tarea con 3 modelos diferentes (competición de modelos)
architect parallel "optimiza las queries SQL del proyecto" \
  --models gpt-4o,claude-sonnet-4-6,deepseek-chat

# Tareas diferentes en paralelo
architect parallel \
  --task "añade tests a src/auth.py" \
  --task "añade tests a src/users.py" \
  --task "añade tests a src/billing.py" \
  --workers 3

# Con budget y timeout por worker
architect parallel \
  --task "refactoriza módulo de pagos" \
  --task "refactoriza módulo de usuarios" \
  --budget-per-worker 2.0 \
  --timeout-per-worker 300
```

---

## Opciones

| Opción | Default | Descripción |
|--------|---------|-------------|
| `TASK` | — | Tarea como argumento posicional |
| `--task CMD` | — | Tarea (repetible). Se asignan round-robin a workers |
| `--workers N` | 3 | Número de workers paralelos |
| `--models CSV` | — | Modelos separados por coma (round-robin entre workers) |
| `--agent NAME` | `build` | Agente a usar en todos los workers |
| `--budget-per-worker FLOAT` | — | Límite USD por worker |
| `--timeout-per-worker INT` | — | Timeout en segundos por worker |
| `--quiet` | `false` | Solo resultado final |

---

## Worktrees

Cada worker se ejecuta en un git worktree independiente:

```
.
├── src/                          # Repositorio original (no se toca)
├── .architect-parallel-1/        # Worker 1
├── .architect-parallel-2/        # Worker 2
└── .architect-parallel-3/        # Worker 3
```

Los worktrees se crean automáticamente antes de la ejecución:
1. Branch: `architect/parallel-{N}`
2. Path: `.architect-parallel-{N}`
3. Base: branch actual (HEAD)

### Limpieza

Los worktrees **no se eliminan automáticamente** — puedes inspeccionarlos después:

```bash
# Ver worktrees activos
git worktree list

# Limpiar todos los worktrees de parallel
architect parallel-cleanup

# O manualmente
git worktree remove .architect-parallel-1
git branch -D architect/parallel-1
```

---

## Asignación de tareas y modelos

### Una tarea, múltiples modelos

```bash
architect parallel "optimiza el rendimiento" \
  --models gpt-4o,claude-sonnet-4-6,deepseek-chat
```

| Worker | Tarea | Modelo |
|--------|-------|--------|
| 1 | optimiza el rendimiento | gpt-4o |
| 2 | optimiza el rendimiento | claude-sonnet-4-6 |
| 3 | optimiza el rendimiento | deepseek-chat |

### Múltiples tareas

```bash
architect parallel \
  --task "tests para auth" \
  --task "tests para users" \
  --task "tests para billing" \
  --workers 3
```

| Worker | Tarea | Modelo |
|--------|-------|--------|
| 1 | tests para auth | default |
| 2 | tests para users | default |
| 3 | tests para billing | default |

### Round-robin

Si hay más workers que tareas, se repite la primera tarea. Si hay más workers que modelos, los workers extra usan el modelo por defecto.

---

## Resultado

Cada worker produce un `WorkerResult`:

```python
@dataclass
class WorkerResult:
    worker_id: int              # 1-based
    branch: str                 # "architect/parallel-1"
    model: str                  # Modelo usado
    status: str                 # "success", "partial", "failed", "timeout"
    steps: int                  # Pasos del agente
    cost: float                 # Coste USD
    duration: float             # Segundos
    files_modified: list[str]   # Archivos cambiados
    worktree_path: str          # Ruta al worktree
```

---

## Configuración YAML

```yaml
parallel_runs:
  workers: 3               # 1-10
  agent: build              # Agente por defecto
  max_steps: 50             # Pasos por worker
  budget_per_worker: null    # USD por worker
  timeout_per_worker: null   # Segundos por worker
```

---

## Salida visual (HUMAN logging)

A partir de v1.1.0, la ejecución paralela emite eventos de nivel HUMAN que producen una salida visual clara en stderr. El usuario puede ver el resultado de cada worker sin necesidad de flags `-v`.

```
   ✓ Worker 1 (gpt-4.1) → success ($0.0456, 120.3s)
   ✓ Worker 2 (claude-sonnet) → success ($0.0312, 98.7s)
   ✗ Worker 3 (gpt-4.1-mini) → failed ($0.0089, 45.1s)

⚡ Parallel complete — 3 workers: 2 success, 1 failed ($0.0857)
```

### Eventos emitidos

| Evento | Cuándo | Datos |
|--------|--------|-------|
| `parallel.worker_done` | Al completar cada worker | worker, model, status, cost, duration |
| `parallel.worker_error` | Si un worker falla con excepción | worker, error |
| `parallel.complete` | Al finalizar todos los workers | total_workers, succeeded, failed, total_cost |

Se desactiva con `--quiet` o `--json`. Ver [`logging.md`](logging.md) para detalles del sistema HUMAN.

---

## Ejemplo CI/CD

```yaml
# GitHub Actions — múltiples tareas en paralelo
- name: Generar tests en paralelo
  run: |
    architect parallel \
      --task "genera tests para src/auth.py" \
      --task "genera tests para src/users.py" \
      --task "genera tests para src/api.py" \
      --workers 3 \
      --budget-per-worker 1.0 \
      --timeout-per-worker 300

- name: Limpiar worktrees
  if: always()
  run: architect parallel-cleanup
```
