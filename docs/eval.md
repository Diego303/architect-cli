# Evaluación Competitiva (Competitive Eval)

Comparación automatizada de múltiples modelos LLM ejecutando la misma tarea, con ranking basado en calidad, eficiencia y coste.

Implementado en `src/architect/features/competitive.py`. Disponible desde v1.0.0 (Plan base v4 Phase D — D3).

---

## Concepto

`architect eval` ejecuta la misma tarea con múltiples modelos en paralelo (cada uno en un git worktree aislado) y después corre los mismos checks de validación en cada worktree. Genera un ranking comparativo basado en un score compuesto.

```bash
architect eval "implementa autenticación JWT" \
  --models gpt-4o,claude-sonnet-4-6,gemini-2.0-flash \
  --check "pytest tests/test_auth.py -q" \
  --check "ruff check src/" \
  --budget-per-model 1.0
```

---

## Cómo funciona

```
architect eval TASK --models m1,m2,m3 --check "cmd1" --check "cmd2"
  │
  ├── Crear CompetitiveConfig
  │     └── task, models, checks, agent, max_steps, budget, timeout
  │
  ├── CompetitiveEval.run()
  │     ├── ParallelRunner (reutiliza infraestructura de parallel)
  │     │     └── Cada modelo → git worktree → `architect run` como subprocess
  │     │
  │     ├── Para cada worktree resultante:
  │     │     └── _run_checks_in_worktree(checks) → (passed, total)
  │     │
  │     └── _rank_results() → calcular score compuesto
  │
  ├── CompetitiveEval.generate_report()
  │     └── Tabla markdown con ranking
  │
  └── Mostrar reporte (stdout o --report-file)
```

---

## Sistema de puntuación

El score compuesto es sobre **100 puntos**:

| Componente | Peso | Cálculo |
|------------|------|---------|
| Checks pasados | 40 pts | `(checks_passed / checks_total) * 40` |
| Status | 30 pts | success=30, partial=15, timeout=5, failed=0 |
| Eficiencia | 20 pts | Menos pasos = mayor puntuación (normalizado) |
| Coste | 10 pts | Menor coste = mayor puntuación (normalizado) |

---

## CLI

```
architect eval PROMPT [opciones]
```

### Opciones

| Opción | Descripción |
|--------|-------------|
| `--models LIST` | Modelos separados por coma (requerido) |
| `--check CMD` | Comando de verificación (repetible, requerido) |
| `--agent NAME` | Agente a usar (default: `build`) |
| `--max-steps N` | Máximo de pasos por modelo (default: 50) |
| `--budget-per-model N` | Límite de coste por modelo en USD |
| `--timeout-per-model N` | Límite de tiempo por modelo en segundos |
| `--report-file PATH` | Guardar reporte en archivo |
| `--config PATH` | Archivo de configuración YAML |
| `--api-base URL` | URL base de la API LLM |

### Ejemplos

```bash
# Comparar 3 modelos con checks
architect eval "refactoriza utils.py" \
  --models gpt-4o,claude-sonnet-4-6,deepseek-chat \
  --check "pytest tests/ -q" \
  --check "ruff check src/" \
  --budget-per-model 0.50

# Guardar reporte
architect eval "optimiza queries SQL" \
  --models gpt-4o,claude-sonnet-4-6 \
  --check "pytest" \
  --report-file eval_report.md

# Con timeout estricto
architect eval "implementa feature" \
  --models gpt-4o-mini,claude-sonnet-4-6 \
  --check "pytest tests/" \
  --timeout-per-model 300 \
  --max-steps 30
```

---

## API

### `CompetitiveConfig`

```python
@dataclass
class CompetitiveConfig:
    task: str
    models: list[str]
    checks: list[str]
    agent: str = "build"
    max_steps: int = 50
    budget_per_model: float | None = None
    timeout_per_model: int | None = None
    config_path: str | None = None
    api_base: str | None = None
```

### `CompetitiveResult`

```python
@dataclass
class CompetitiveResult:
    model: str
    status: str               # success | partial | failed | timeout
    steps: int
    cost: float
    duration: float
    files_modified: list[str]
    checks_passed: int
    checks_total: int
    worktree_path: str
    score: float              # score compuesto (0-100)
```

### `CompetitiveEval`

```python
class CompetitiveEval:
    def __init__(self, config: CompetitiveConfig, workspace_root: str): ...
    def run(self) -> list[CompetitiveResult]: ...
    def generate_report(self, results: list[CompetitiveResult]) -> str: ...
```

---

## Reporte generado

El reporte incluye:

1. **Tabla comparativa**: modelo, status, pasos, coste, tiempo, checks pasados, archivos modificados
2. **Ranking**: ordenado por score compuesto (1er, 2do, 3er lugar)
3. **Resultados de checks**: detalle por modelo
4. **Worktree paths**: para inspección manual de cada resultado

```markdown
## Ranking

| # | Modelo | Score | Status | Steps | Cost | Checks |
|---|--------|-------|--------|-------|------|--------|
| 1 | gpt-4o | 85.0 | success | 12 | $0.42 | 3/3 |
| 2 | claude-sonnet-4-6 | 78.5 | success | 15 | $0.38 | 2/3 |
| 3 | deepseek-chat | 45.0 | partial | 30 | $0.12 | 1/3 |
```

---

## Salida visual (HUMAN logging)

A partir de v1.1.0, la evaluación competitiva emite eventos de nivel HUMAN que producen una salida visual clara en stderr. El usuario puede ver el ranking en tiempo real sin necesidad de flags `-v`.

```
   🏆 gpt-4.1: #1 (score: 85, 5/5 checks, $0.0456)
   🥈 claude-sonnet: #2 (score: 72, 4/5 checks, $0.0312)
   🥉 gpt-4.1-mini: #3 (score: 41, 2/5 checks, $0.0089)

🏁 Ranking final: gpt-4.1 > claude-sonnet > gpt-4.1-mini
```

Los modelos en posiciones 1, 2 y 3 muestran medallas (🏆, 🥈, 🥉). A partir de la 4ª posición se muestra `#N`.

### Eventos emitidos

| Evento | Cuándo | Datos |
|--------|--------|-------|
| `competitive.model_done` | Al completar cada modelo | model, rank, score, cost, checks_passed, checks_total |
| `competitive.ranking` | Al finalizar la evaluación | ranking (lista de {model, score, rank}) |

Se desactiva con `--quiet` o `--json`. Ver [`logging.md`](logging.md) para detalles del sistema HUMAN.

---

## Relación con Parallel

`CompetitiveEval` reutiliza la infraestructura de `ParallelRunner` (git worktrees + ProcessPoolExecutor). La diferencia es que:

- `parallel` ejecuta **tareas diferentes** (o la misma tarea) con posiblemente diferentes modelos
- `eval` ejecuta la **misma tarea** con **diferentes modelos** y añade validación con checks + ranking

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `src/architect/features/competitive.py` | `CompetitiveEval`, `CompetitiveConfig`, `CompetitiveResult` |
| `src/architect/cli.py` | Comando `architect eval` |
| `tests/test_competitive/` | Tests unitarios |
