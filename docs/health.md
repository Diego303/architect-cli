# Code Health Delta

Análisis automático de métricas de calidad del código antes y después de una ejecución.

Implementado en `src/architect/core/health.py`. Disponible desde v1.0.0 (Plan base v4 Phase D — D2).

---

## Concepto

El `CodeHealthAnalyzer` toma una snapshot de métricas del código Python al inicio de la ejecución y otra al final. El delta entre ambas muestra si los cambios del agente mejoraron o degradaron la calidad del código.

```
architect run "refactoriza utils.py" --health
```

Al finalizar la ejecución, se muestra un reporte en stderr:

```
## Code Health Delta

| Métrica              | Antes | Después | Delta |
|----------------------|-------|---------|-------|
| Archivos analizados  | 12    | 12      | =     |
| Total funciones      | 45    | 43      | -2    |
| Complejidad promedio | 4.2   | 3.8     | -0.4  |
| Complejidad máxima   | 12    | 8       | -4    |
| Funciones largas     | 3     | 1       | -2    |
| Bloques duplicados   | 5     | 3       | -2    |
```

---

## Métricas analizadas

### Complejidad ciclomática

Si `radon` está instalado (`pip install radon`), se calcula la complejidad ciclomática real de cada función. Sin radon, se usa un conteo AST simplificado (branches + loops).

### Funciones largas

Funciones con más de **50 líneas** (umbral configurable via `LONG_FUNCTION_THRESHOLD`).

### Funciones complejas

Funciones con complejidad ciclomática mayor a **10** (umbral configurable via `COMPLEX_FUNCTION_THRESHOLD`).

### Duplicación de código

Detección de bloques duplicados usando una ventana deslizante de **6 líneas** (configurable via `DUPLICATE_BLOCK_SIZE`). Cada ventana se hashea con MD5 y se buscan colisiones.

### Conteo de funciones

Funciones totales en el proyecto, incluyendo nuevas y eliminadas.

---

## API

### `CodeHealthAnalyzer`

```python
class CodeHealthAnalyzer:
    def __init__(
        self,
        workspace_root: str,
        include_patterns: list[str] = ["**/*.py"],
        exclude_dirs: list[str] | None = None,
    ): ...

    def take_before_snapshot(self) -> HealthSnapshot: ...
    def take_after_snapshot(self) -> HealthSnapshot: ...
    def compute_delta(self) -> HealthDelta | None: ...
```

### `HealthSnapshot`

```python
@dataclass
class HealthSnapshot:
    files_analyzed: int
    total_functions: int
    avg_complexity: float
    max_complexity: int
    long_functions: int        # > LONG_FUNCTION_THRESHOLD líneas
    duplicate_blocks: int      # bloques de código duplicado
    functions: list[FunctionMetric]
```

### `HealthDelta`

```python
@dataclass
class HealthDelta:
    before: HealthSnapshot
    after: HealthSnapshot

    def to_report(self) -> str:
        """Genera reporte markdown con tabla comparativa."""
```

### `FunctionMetric`

```python
@dataclass(frozen=True)
class FunctionMetric:
    file: str
    name: str
    lines: int
    complexity: int
```

### Constantes

```python
LONG_FUNCTION_THRESHOLD = 50      # líneas
COMPLEX_FUNCTION_THRESHOLD = 10   # complejidad ciclomática
DUPLICATE_BLOCK_SIZE = 6          # líneas por bloque
```

---

## Configuración

### Flag CLI

```bash
architect run "tarea" --health
```

### Config YAML

```yaml
health:
  enabled: true                    # activar automáticamente (sin necesidad de --health)
  include_patterns: ["**/*.py"]    # patrones de archivos a analizar
  exclude_dirs:                    # directorios a excluir
    - .git
    - venv
    - __pycache__
    - node_modules
```

### Dependencia opcional

```bash
# Para complejidad ciclomática precisa
pip install radon

# O instalar con el extra
pip install architect[health]
```

Sin `radon`, el análisis funciona pero usa un conteo AST simplificado para la complejidad.

---

## Flujo de ejecución

```
CLI: architect run "..." --health
  │
  ├── ¿--health flag O config.health.enabled?
  │     └── Sí: crear CodeHealthAnalyzer
  │
  ├── health_analyzer.take_before_snapshot()
  │     └── Escanea todos los .py en workspace
  │
  ├── AgentLoop.run(prompt)
  │     └── ... ejecución normal del agente ...
  │
  ├── health_analyzer.take_after_snapshot()
  │
  ├── delta = health_analyzer.compute_delta()
  │
  └── click.echo(delta.to_report(), err=True)
        └── Reporte markdown a stderr
```

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `src/architect/core/health.py` | `CodeHealthAnalyzer`, `HealthSnapshot`, `HealthDelta`, `FunctionMetric` |
| `src/architect/config/schema.py` | `HealthConfig` (Pydantic model) |
| `src/architect/cli.py` | Flag `--health`, wiring before/after snapshots |
| `tests/test_health/test_health.py` | 28 tests unitarios |
| `tests/test_bugfixes/test_bugfixes.py` | Tests BUG-6 (wiring) |
