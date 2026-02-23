# Sessions — Persistencia y Resume

El sistema de sesiones permite guardar, listar, reanudar y limpiar el estado del agente entre ejecuciones.

---

## Cómo funciona

El agente guarda su estado automáticamente después de cada paso en `.architect/sessions/<session_id>.json`. Si una ejecución se interrumpe (Ctrl+C, timeout, budget exceeded, error), puedes reanudarla donde se quedó.

```
.architect/
└── sessions/
    ├── 20260223-143022-a1b2c3.json
    ├── 20260223-151045-d4e5f6.json
    └── ...
```

Cada archivo contiene: ID de sesión, tarea original, agente, modelo, status, pasos completados, mensajes (historial LLM), archivos modificados, coste acumulado, timestamps y razón de parada.

---

## Comandos

### `architect sessions` — listar sesiones

```bash
architect sessions
```

Muestra una tabla con todas las sesiones guardadas:

```
ID                     Status       Steps  Cost    Task
20260223-143022-a1b2   interrupted  12     $1.23   refactoriza todo el módulo de auth
20260223-151045-d4e5   success      8      $0.45   añade tests a user.py
20260223-160000-f7g8   partial      25     $2.00   migra la base de datos
```

### `architect resume` — reanudar sesión

```bash
architect resume 20260223-143022-a1b2
```

Carga el estado completo de la sesión (mensajes, archivos modificados, coste acumulado) y continúa donde se dejó. Si el ID no existe, termina con exit code 3 (`EXIT_CONFIG_ERROR`).

### `architect cleanup` — limpiar sesiones antiguas

```bash
architect cleanup                  # elimina sesiones > 7 días (default)
architect cleanup --older-than 30  # elimina sesiones > 30 días
```

### `--session` flag en `architect run`

```bash
architect run "continúa la tarea" --session 20260223-143022-a1b2
```

Equivalente a `architect resume`, pero permite combinar con otros flags de `architect run`.

---

## Truncación de mensajes

Las sesiones con más de 50 mensajes se truncan automáticamente al guardar: se conservan los últimos 30 mensajes y se marca `truncated: true` en los metadatos. Esto evita que las sesiones crezcan indefinidamente en disco.

---

## Configuración

```yaml
sessions:
  auto_save: true           # guardar estado después de cada paso (default: true)
  cleanup_after_days: 7     # días después de los cuales `cleanup` elimina (default: 7)
```

---

## SessionState — modelo de datos

```python
@dataclass
class SessionState:
    session_id:     str              # formato: YYYYMMDD-HHMMSS-hexhex
    task:           str              # prompt original del usuario
    agent:          str              # nombre del agente (build, plan, etc.)
    model:          str              # modelo LLM usado
    status:         str              # running, success, partial, failed
    steps_completed: int             # pasos ejecutados
    messages:       list[dict]       # historial de mensajes LLM
    files_modified: list[str]        # archivos tocados durante la sesión
    total_cost:     float            # coste acumulado en USD
    started_at:     str              # ISO 8601 timestamp
    updated_at:     str              # ISO 8601 timestamp (se actualiza en cada save)
    stop_reason:    str | None       # razón de parada (llm_done, timeout, etc.)
    metadata:       dict             # datos adicionales arbitrarios
```

Métodos: `to_dict()` / `from_dict()` para serialización JSON.

### SessionManager

```python
class SessionManager:
    def __init__(self, workspace_root: str): ...
    def save(self, state: SessionState) -> None: ...        # guarda en .architect/sessions/
    def load(self, session_id: str) -> SessionState | None: ...  # None si no existe o JSON corrupto
    def list_sessions(self) -> list[dict]: ...               # metadata resumida, newest first
    def cleanup(self, older_than_days: int = 7) -> int: ...  # retorna count eliminados
    def delete(self, session_id: str) -> bool: ...
```

### generate_session_id

```python
def generate_session_id() -> str:
    # Formato: YYYYMMDD-HHMMSS-hexhex
    # Ejemplo: 20260223-143022-a1b2c3
    # Unicidad garantizada por timestamp + random hex
```

---

## Flujo de resume

```
1. architect resume SESSION_ID
2. SessionManager.load(SESSION_ID)
3. Reconstruir AgentState desde SessionState
4. Inyectar mensajes, coste acumulado, archivos modificados
5. AgentLoop.run() continúa desde el último paso
6. Session se re-guarda con cada paso adicional
```

---

## Patrones de uso

### Tareas largas con budget limitado

```bash
# Primera ejecución — se detiene por budget
architect run "refactoriza todo el módulo auth" --budget 1.00

# Ver sesiones
architect sessions

# Continuar con más budget
architect resume 20260223-143022-a1b2 --budget 2.00
```

### CI con persistencia entre runs

```bash
# Run 1: implementar
architect run "implementa feature X" --mode yolo --json > result.json
SESSION=$(jq -r '.session_id // empty' result.json)

# Run 2: verificar y continuar si quedó parcial
if [ "$(jq -r '.status' result.json)" = "partial" ]; then
  architect resume "$SESSION" --mode yolo --budget 1.00
fi
```

### Limpieza periódica

```bash
# Cron job semanal
architect cleanup --older-than 7
```

---

## Archivos

- **Módulo**: `src/architect/features/sessions.py`
- **Config**: `SessionsConfig` en `src/architect/config/schema.py`
- **CLI**: `architect sessions`, `architect resume`, `architect cleanup` en `src/architect/cli.py`
- **Tests**: `tests/test_sessions/` (22 tests) + `scripts/test_phase_b.py` sección B1 (8 tests, 24 checks)
