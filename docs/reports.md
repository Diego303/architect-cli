# Reports — Reportes de Ejecución

Genera reportes detallados de lo que hizo el agente en tres formatos: JSON (para CI/CD), Markdown (para documentación) y GitHub PR comment (con secciones collapsible).

---

## Uso

```bash
# Reporte JSON — ideal para CI/CD pipelines
architect run "añade tests a user.py" --mode yolo --report json

# Reporte Markdown — para documentación o revisión
architect run "refactoriza utils" --mode yolo --report markdown --report-file report.md

# Comentario GitHub PR — con secciones collapsible
architect run "revisa los cambios" --mode yolo --report github --report-file pr-comment.md
```

### Flags

| Flag | Descripción |
|------|-------------|
| `--report FORMAT` | Formato del reporte: `json`, `markdown`, `github` |
| `--report-file PATH` | Guarda el reporte en archivo (si no se especifica, va a stdout) |

---

## Formatos

### JSON (`--report json`)

Parseable por `jq` y herramientas CI. Contiene todos los datos estructurados.

```json
{
  "task": "añade tests a user.py",
  "agent": "build",
  "model": "gpt-4o",
  "status": "success",
  "duration_seconds": 45.2,
  "steps": 8,
  "total_cost": 0.0342,
  "stop_reason": null,
  "files_modified": [
    {"path": "tests/test_user.py", "action": "created", "lines_added": 42, "lines_removed": 0}
  ],
  "quality_gates": [
    {"name": "tests", "passed": true, "output": "8 passed in 1.2s"}
  ],
  "errors": [],
  "git_diff": "diff --git a/tests/test_user.py ...",
  "timeline": [
    {"step": 1, "tool": "read_file", "duration": 0.1, "cost": 0.002},
    {"step": 2, "tool": "write_file", "duration": 0.3, "cost": 0.015}
  ]
}
```

### Markdown (`--report markdown`)

Formato legible con tablas y secciones.

```markdown
# Execution Report

## Summary

| Field | Value |
|-------|-------|
| Task | añade tests a user.py |
| Agent | build |
| Model | gpt-4o |
| Status | OK |
| Duration | 45.2s |
| Steps | 8 |
| Cost | $0.0342 |

## Files Modified

| Path | Action | +Lines | -Lines |
|------|--------|--------|--------|
| tests/test_user.py | created | 42 | 0 |

## Quality Gates

| Gate | Status |
|------|--------|
| tests | PASS |

## Timeline

| Step | Tool | Duration | Cost |
|------|------|----------|------|
| 1 | read_file | 0.1s | $0.002 |
| 2 | write_file | 0.3s | $0.015 |
```

### GitHub PR comment (`--report github`)

Optimizado para GitHub con secciones `<details>` collapsible. Los detalles largos (timeline, diff) se colapsan por defecto.

```markdown
## OK Execution Report

**Task**: añade tests a user.py
**Status**: success | **Steps**: 8 | **Cost**: $0.0342

<details>
<summary>Files Modified (1)</summary>

| Path | Action | +Lines | -Lines |
|------|--------|--------|--------|
| tests/test_user.py | created | 42 | 0 |

</details>

<details>
<summary>Timeline (8 steps)</summary>
...
</details>
```

---

## Status icons

| Status | Markdown | GitHub |
|--------|----------|--------|
| `success` | OK | OK |
| `partial` | WARN | WARN |
| `failed` | FAIL | FAIL |

---

## Git Diff

`collect_git_diff(workspace_root)` ejecuta `git diff HEAD` para capturar los cambios realizados por el agente. El diff se trunca a 50KB para evitar reportes enormes. Si el workspace no es un repositorio git o no hay cambios, retorna `None`.

---

## ExecutionReport — modelo de datos

```python
@dataclass
class ExecutionReport:
    task:             str
    agent:            str
    model:            str
    status:           str                    # success, partial, failed
    duration_seconds: float
    steps:            int
    total_cost:       float
    stop_reason:      str | None = None
    files_modified:   list[dict] = field(default_factory=list)
    quality_gates:    list[dict] = field(default_factory=list)
    errors:           list[str]  = field(default_factory=list)
    git_diff:         str | None = None
    timeline:         list[dict] = field(default_factory=list)
```

### ReportGenerator

```python
class ReportGenerator:
    def __init__(self, report: ExecutionReport): ...
    def to_json(self) -> str: ...                  # JSON completo
    def to_markdown(self) -> str: ...              # Markdown con tablas
    def to_github_pr_comment(self) -> str: ...     # GitHub con <details>
```

---

## Integración con CI/CD

### GitHub Actions — reporte como comentario de PR

```yaml
- name: Run architect with report
  run: |
    architect run "revisa los cambios del PR" \
      --mode yolo \
      --context-git-diff origin/main \
      --report github \
      --report-file pr-report.md \
      --budget 2.00

- name: Comment on PR
  if: always()
  run: gh pr comment ${{ github.event.pull_request.number }} --body-file pr-report.md
```

### GitLab CI — reporte como artefacto

```yaml
architect-report:
  script:
    - architect run "..." --mode yolo --report json --report-file report.json
  artifacts:
    paths: [report.json]
    expire_in: 1 week
```

### Parsear reporte JSON en scripts

```bash
# Verificar status
STATUS=$(jq -r '.status' report.json)

# Contar archivos modificados
FILES=$(jq '.files_modified | length' report.json)

# Verificar quality gates
GATES_PASSED=$(jq '[.quality_gates[] | select(.passed)] | length' report.json)
```

---

## Archivos

- **Módulo**: `src/architect/features/report.py`
- **CLI**: flags `--report` y `--report-file` en `src/architect/cli.py`
- **Tests**: `tests/test_reports/` (20 tests) + `scripts/test_phase_b.py` sección B2 (8 tests, 24 checks)
