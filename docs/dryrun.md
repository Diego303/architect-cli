# Dry Run — Simulación de Ejecución

El modo `--dry-run` permite previsualizar qué haría el agente sin ejecutar cambios reales. Las tools de lectura funcionan normalmente, pero las de escritura se simulan y se registran en un plan de acciones.

---

## Uso

```bash
# Previsualizar qué haría el agente
architect run "refactoriza auth.py" --dry-run

# Combinar con otros flags
architect run "migra tests a pytest" --dry-run --mode yolo --show-costs
```

El agente interactúa normalmente con el LLM, lee archivos, busca código. Pero cuando intenta escribir, editar o ejecutar comandos, recibe `[DRY-RUN] Se ejecutaría: tool_name(args)`.

---

## Cómo funciona

### Tools de escritura (simuladas)

`WRITE_TOOLS` (frozenset): `write_file`, `edit_file`, `apply_patch`, `delete_file`, `run_command`

Estas tools **no se ejecutan** en dry-run. En su lugar:
1. El `DryRunTracker` registra la acción (`PlannedAction`)
2. Se retorna `ToolResult(success=True, "[DRY-RUN] ...")`
3. El LLM continúa planificando con la información que tiene

### Tools de lectura (ejecutadas normalmente)

`READ_TOOLS` (frozenset): `read_file`, `list_files`, `search_code`, `grep`, `find_files`

Se ejecutan normalmente para que el agente pueda analizar código y planificar.

Los conjuntos `WRITE_TOOLS` y `READ_TOOLS` son disjuntos por diseño.

---

## DryRunTracker — modelo de datos

```python
@dataclass
class PlannedAction:
    tool_name:   str      # nombre de la tool
    description: str      # descripción legible de la acción
    tool_input:  dict     # argumentos originales de la tool

class DryRunTracker:
    actions: list[PlannedAction]

    def record_action(self, tool_name: str, tool_input: dict) -> None: ...
    def get_plan_summary(self) -> str: ...    # resumen formateado
    @property
    def action_count(self) -> int: ...
```

### `_summarize_action(tool_name, tool_input)`

Genera descripciones legibles con 5 code paths:

| Caso | Ejemplo de descripción |
|------|----------------------|
| Tool con `path` | `write_file → src/main.py` |
| Tool con `command` corto | `run_command → pytest tests/` |
| Tool con `command` largo | `run_command → pytest tests/test_a... (truncado)` |
| Tool con otras keys | `edit_file → old_str, new_str, path` |
| Tool sin argumentos | `delete_file → (sin argumentos)` |

---

## Plan summary

`get_plan_summary()` genera un resumen legible:

```
Plan de acciones (dry-run): 3 acciones planificadas

1. write_file → tests/test_auth.py
2. edit_file → src/auth.py
3. run_command → pytest tests/ -x
```

Si no hay acciones: `"Dry-run completado: no se planificaron acciones de escritura."`

---

## Integración con reports

Si `--report` y `--dry-run` se usan juntos, el reporte incluye las acciones planificadas en lugar de archivos realmente modificados. El campo `files_modified` del reporte se llena a partir de las acciones registradas por el `DryRunTracker`.

---

## Archivos

- **Módulo**: `src/architect/features/dryrun.py`
- **Tests**: `tests/test_dryrun/` (23 tests) + `scripts/test_phase_b.py` sección B4 (6 tests, 18 checks)
