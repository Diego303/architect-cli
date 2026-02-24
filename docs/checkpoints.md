# Checkpoints & Rollback

Puntos de restauración basados en git commits que permiten volver a un estado anterior del workspace.

---

## Concepto

Los checkpoints son git commits con el prefijo `architect:checkpoint`. Se crean automáticamente en pipelines (con `checkpoint: true`) y se pueden listar y restaurar mediante `CheckpointManager`.

```
architect:checkpoint:step-1           ← Después del primer step
architect:checkpoint:step-2           ← Después del segundo step
architect:checkpoint:implement        ← Pipeline step "implement"
```

---

## Uso en Pipelines

```yaml
steps:
  - name: implement
    prompt: "Implementa la feature"
    checkpoint: true
    # → git add -A && git commit -m "architect:checkpoint:implement"

  - name: optimize
    prompt: "Optimiza el rendimiento"
    checkpoint: true
```

Cada step con `checkpoint: true` ejecuta:
1. `git add -A` — stage todos los cambios
2. `git commit -m "architect:checkpoint:<step_name>"` — commit con prefijo

---

## Listar checkpoints

```bash
git log --oneline --grep="architect:checkpoint"
```

Output:
```
def5678 architect:checkpoint:optimize
abc1234 architect:checkpoint:implement
```

---

## API Python

### CheckpointManager

```python
class CheckpointManager:
    def __init__(self, workspace_root: str) -> None: ...

    def create(self, step: int, message: str = "") -> Checkpoint | None:
        """Crea un checkpoint. Retorna None si no hay cambios."""

    def list_checkpoints(self) -> list[Checkpoint]:
        """Lista checkpoints (más reciente primero)."""

    def rollback(self, step: int | None = None, commit: str | None = None) -> bool:
        """Rollback a un checkpoint. Usa git reset --hard."""

    def get_latest(self) -> Checkpoint | None:
        """Obtiene el checkpoint más reciente."""

    def has_changes_since(self, commit_hash: str) -> bool:
        """Verifica si hay cambios desde un commit."""
```

### Checkpoint

```python
@dataclass(frozen=True)
class Checkpoint:
    step: int                          # Número de step
    commit_hash: str                   # Hash git completo
    message: str                       # Mensaje descriptivo
    timestamp: float                   # Unix timestamp
    files_changed: list[str]           # Archivos modificados

    def short_hash(self) -> str:       # Primeros 7 caracteres
```

### Constante

```python
CHECKPOINT_PREFIX = "architect:checkpoint"
```

---

## Configuración YAML

```yaml
checkpoints:
  enabled: false              # true = activar checkpoints automáticos en el AgentLoop
  every_n_steps: 5            # Crear checkpoint cada N pasos (1-50)
```

---

## Rollback manual

```bash
# Ver checkpoints
git log --oneline --grep="architect:checkpoint"

# Volver a un checkpoint específico
git reset --hard <commit_hash>
```

**Precaución**: `git reset --hard` descarta todos los cambios no commiteados.
