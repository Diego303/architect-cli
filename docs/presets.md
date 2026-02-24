# Presets de Configuración (Init)

Sistema de inicialización de proyectos con configuraciones predefinidas.

Implementado en `src/architect/config/presets.py`. Disponible desde v1.0.0 (Plan base v4 Phase D — D5).

---

## Concepto

`architect init` genera archivos de configuración (`.architect.md` + `config.yaml`) a partir de presets predefinidos. Cada preset incluye convenciones del proyecto, hooks de calidad, guardrails y configuración del agente optimizada para un caso de uso específico.

```bash
# Ver presets disponibles
architect init --list-presets

# Inicializar proyecto Python
architect init --preset python
# → Crea .architect.md (convenciones) + config.yaml (hooks: ruff, mypy, pytest)
```

---

## Presets disponibles

### `python` — Proyecto Python estándar

Convenciones y herramientas para proyectos Python modernos.

**`.architect.md`**: PEP 8, type hints, Google-style docstrings, pytest, structlog, black (100 chars)

**`config.yaml`**:
- Hooks: `ruff check {file} --fix`, `mypy {file}`
- Quality gates: `pytest tests/ -x` (required)
- Guardrails: proteger `.env`, `*.pem`

### `node-react` — Proyecto Node.js/React

Convenciones para proyectos TypeScript/React.

**`.architect.md`**: TypeScript strict, ESLint, Prettier, componentes funcionales, Jest/Vitest

**`config.yaml`**:
- Hooks: `eslint --fix {file}`, `prettier --write {file}`
- Quality gates: `npm test` (required)
- Guardrails: proteger `.env*`, `*.pem`

### `ci` — Modo headless CI/CD

Configuración mínima y autónoma para pipelines de CI.

**`.architect.md`**: instrucciones de modo autónomo, sin preguntas, salida parseble

**`config.yaml`**:
- Confirm mode: `yolo`
- Stream: desactivado
- Sessions/memory: desactivados
- Logging: warn level

### `paranoid` — Máxima seguridad

Para entornos donde la seguridad es prioritaria.

**`.architect.md`**: instrucciones de mínimo impacto, no eliminar archivos, pedir verificación

**`config.yaml`**:
- Confirm mode: `confirm-all`
- Max steps: 20
- Guardrails estrictos: `eval()`, `pickle`, `os.system` bloqueados
- Quality gates: pytest + ruff (required)
- Auto-review activado
- Code rules: severity block para patrones peligrosos

### `yolo` — Sin restricciones

Para desarrollo rápido sin barreras.

**`config.yaml`**:
- Confirm mode: `yolo`
- Max steps: 100
- Sin guardrails
- Overhead mínimo

---

## CLI

```
architect init [opciones]
```

### Opciones

| Opción | Descripción |
|--------|-------------|
| `--preset NAME` | Preset a aplicar (requerido si no se usa `--list-presets`) |
| `--list-presets` | Mostrar presets disponibles con descripción |
| `--overwrite` | Sobreescribir archivos existentes (por defecto no sobreescribe) |

### Ejemplos

```bash
# Listar presets
architect init --list-presets
# → python: Proyecto Python estándar (pytest, ruff, mypy)
# → node-react: Proyecto Node.js/React (ESLint, Prettier, Jest)
# → ci: Modo headless CI/CD
# → paranoid: Máxima seguridad
# → yolo: Sin restricciones

# Inicializar proyecto
architect init --preset python
# → Creado .architect.md
# → Creado config.yaml
# → Creado .architect/

# Reinicializar con overwrite
architect init --preset paranoid --overwrite
```

---

## API

### `PresetManager`

```python
class PresetManager:
    AVAILABLE_PRESETS: frozenset = {"python", "node-react", "ci", "paranoid", "yolo"}

    def __init__(self, workspace_root: str): ...

    def apply(self, preset_name: str, overwrite: bool = False) -> list[str]:
        """Aplica un preset. Retorna lista de archivos creados."""

    @staticmethod
    def list_presets() -> dict[str, str]:
        """Retorna {nombre: descripción} de todos los presets."""
```

### `PRESET_TEMPLATES`

Diccionario interno con el contenido de cada preset:

```python
PRESET_TEMPLATES = {
    "python": {
        ".architect.md": "...",      # convenciones Python
        "config.yaml": "...",         # hooks ruff/mypy, guardrails
    },
    "node-react": { ... },
    "ci": { ... },
    "paranoid": { ... },
    "yolo": { ... },
}
```

---

## Archivos generados

Cada preset genera hasta 3 elementos:

| Elemento | Descripción |
|----------|-------------|
| `.architect.md` | Convenciones del proyecto inyectadas en el system prompt del agente |
| `config.yaml` | Configuración YAML completa de architect |
| `.architect/` | Directorio creado automáticamente (para skills, memory, sessions) |

Los archivos son editables — sirven como punto de partida que el usuario puede personalizar.

---

## Flujo de ejecución

```
architect init --preset python
  │
  ├── PresetManager(workspace_root)
  │
  ├── Verificar que el preset existe
  │
  ├── Para cada archivo del preset:
  │     ├── ¿Existe el archivo y no hay --overwrite?
  │     │     └── Sí: skip con warning
  │     └── No: escribir contenido del template
  │
  ├── Crear directorio .architect/ si no existe
  │
  └── Retornar lista de archivos creados
```

---

## Personalización post-init

Después de `architect init`, se recomienda:

1. **Editar `.architect.md`**: añadir convenciones específicas del proyecto
2. **Ajustar `config.yaml`**: cambiar modelo, API base, hooks específicos
3. **Crear skills**: `architect skill create mi-patron` para patrones recurrentes
4. **Activar memoria**: si se quiere que el agente aprenda de correcciones

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `src/architect/config/presets.py` | `PresetManager`, `AVAILABLE_PRESETS`, `PRESET_TEMPLATES` |
| `src/architect/cli.py` | Comando `architect init` |
| `tests/test_presets/` | Tests unitarios |
