# Auto-Review — Revisión Automática Post-Build

Agente reviewer con contexto limpio que inspecciona los cambios realizados por el builder.

---

## Concepto

Después de que un agente builder completa su trabajo, el Auto-Reviewer recibe **solo** el diff de los cambios y la tarea original — sin ningún historial del builder. Este contexto limpio permite una revisión imparcial.

El reviewer tiene acceso exclusivo a tools de lectura (no puede modificar archivos). Busca:

1. Bugs lógicos y edge cases no cubiertos
2. Problemas de seguridad (SQL injection, XSS, secrets, etc.)
3. Violaciones de convenciones del proyecto
4. Oportunidades de simplificación
5. Tests faltantes

Si encuentra issues, puede generar un prompt de corrección para que el builder los resuelva en un segundo pase.

---

## Configuración

```yaml
auto_review:
  enabled: true                    # Activar auto-review post-build
  review_model: claude-sonnet-4-6  # Modelo para el reviewer (null = mismo que builder)
  max_fix_passes: 1                # Pases de corrección (0 = solo reportar, 1-3 = corregir)
```

---

## Flujo

```
Builder completa tarea
  │
  ├── 1. get_recent_diff(workspace) → obtener git diff
  │
  ├── 2. AutoReviewer.review_changes(task, diff)
  │       ├── Crear AgentLoop fresco (contexto limpio)
  │       ├── Prompt: tarea original + diff
  │       ├── Agent "review" con tools de lectura
  │       └── ReviewResult(has_issues, review_text, cost)
  │
  ├── 3. Si has_issues y max_fix_passes > 0:
  │       ├── build_fix_prompt(review_text) → prompt de corrección
  │       └── Builder ejecuta corrección
  │
  └── 4. Resultado final
```

---

## API Python

### AutoReviewer

```python
class AutoReviewer:
    def __init__(
        self,
        agent_factory: Callable[..., Any],   # (**kwargs) → AgentLoop
        review_model: str | None = None,      # Modelo para el reviewer
    ) -> None: ...

    def review_changes(
        self,
        task: str,                            # Tarea original
        git_diff: str,                        # Diff de los cambios
    ) -> ReviewResult: ...

    @staticmethod
    def build_fix_prompt(review_text: str) -> str:
        """Genera prompt de corrección basado en la review."""

    @staticmethod
    def get_recent_diff(
        workspace_root: str,
        commits_back: int = 1,
    ) -> str:
        """Obtiene diff de los últimos N commits."""
```

### ReviewResult

```python
class ReviewResult:
    has_issues: bool       # True si se encontraron problemas
    review_text: str       # Texto completo de la review
    cost: float            # Coste USD de la review
```

### REVIEW_SYSTEM_PROMPT

El system prompt del reviewer:

```
Eres un reviewer senior de código. Tu trabajo es revisar cambios de código
hechos por otro agente y encontrar problemas.

Busca específicamente:
1. Bugs lógicos y edge cases no cubiertos
2. Problemas de seguridad (SQL injection, XSS, secrets, etc.)
3. Violaciones de convenciones del proyecto
4. Oportunidades de simplificación
5. Tests faltantes

Sé específico: archivo, línea, cambio exacto.
Si no hay issues: di "Sin issues encontrados."
```

---

## Manejo de errores

Si la llamada al LLM falla durante la review, el `AutoReviewer` no propaga la excepción. En su lugar, retorna un `ReviewResult` con:
- `has_issues = True`
- `review_text = "Error durante la review: <mensaje>"
- `cost = 0.0`

Esto permite que el flujo principal continúe sin interrupciones.

---

## Detección de "sin issues"

El reviewer responde "Sin issues encontrados" (o variaciones) cuando no hay problemas. La detección es case-insensitive y busca el patrón "sin issues" en la respuesta.

---

## Ejemplo de uso programático

```python
from architect.agents.reviewer import AutoReviewer, ReviewResult

def my_agent_factory(**kwargs):
    # Crear AgentLoop fresco
    ...

reviewer = AutoReviewer(
    agent_factory=my_agent_factory,
    review_model="claude-sonnet-4-6",
)

# Obtener diff reciente
diff = AutoReviewer.get_recent_diff("/path/to/repo")

# Revisar cambios
result = reviewer.review_changes(
    task="Implementar autenticación JWT",
    git_diff=diff,
)

if result.has_issues:
    # Generar prompt de corrección
    fix_prompt = AutoReviewer.build_fix_prompt(result.review_text)
    # Ejecutar corrección con el builder...
```
