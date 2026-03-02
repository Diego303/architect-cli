# Extendiendo Architect CLI

Guia completa para extender architect-cli v1.0.0 con tools custom, agentes, hooks, skills y guardrails.

Architect es un agente de IA headless para CLI, escrito en Python 3.12+, que usa Pydantic v2 para validacion, structlog para logging y LiteLLM como abstraccion de modelos. Su arquitectura esta disenada para ser extensible en cinco superficies:

| Superficie | Que extiende | Donde vive |
|---|---|---|
| **Tools** | Capacidades del agente (leer, escribir, buscar...) | `src/architect/tools/` |
| **Agentes** | Roles con prompts y tools distintas | `architect.yaml` o `agents/registry.py` |
| **Hooks** | Acciones automaticas en el lifecycle | `architect.yaml` seccion `hooks:` |
| **Skills** | Instrucciones contextuales por proyecto/archivo | `.architect/skills/`, `.architect.md` |
| **Guardrails** | Restricciones de seguridad deterministas | `architect.yaml` seccion `guardrails:` |

---

## 1. Crear una Tool Custom

Las tools son la interfaz entre el agente y el mundo exterior. Cada tool hereda de `BaseTool`, define un schema de argumentos con Pydantic y expone un metodo `execute()` que siempre retorna un `ToolResult`.

### 1.1. Anatomia de una Tool

```
BaseTool (abstracta)
  ├── name: str              # Nombre unico de la tool (ej: "count_lines")
  ├── description: str       # Descripcion para el LLM
  ├── args_model: type[BaseModel]  # Schema Pydantic de argumentos
  ├── sensitive: bool        # Si True, requiere confirmacion en modo confirm-sensitive
  ├── execute(**kwargs) -> ToolResult   # Logica de la tool
  ├── get_schema() -> dict   # Genera JSON Schema OpenAI-compatible (automatico)
  └── validate_args(args) -> BaseModel  # Valida args contra args_model (automatico)
```

El contrato principal:

- `execute()` **NUNCA** debe lanzar excepciones al caller. Todos los errores se capturan y se retornan como `ToolResult(success=False, output="", error="mensaje")`.
- El retorno siempre es `ToolResult(success=bool, output=str, error=str|None)`.
- Si la tool opera sobre archivos, **debe** usar `validate_path()` para prevenir path traversal.

### 1.2. Paso 1 — Definir el modelo de argumentos

Crear el schema Pydantic en `src/architect/tools/schemas.py` (o en un archivo propio):

```python
# src/architect/tools/schemas.py (anadir al final)

class CountLinesArgs(BaseModel):
    """Argumentos para count_lines tool."""

    path: str = Field(
        default=".",
        description="Directorio relativo al workspace donde contar lineas",
        examples=[".", "src", "lib"],
    )
    extensions: list[str] = Field(
        default_factory=lambda: [".py", ".js", ".ts", ".go", ".rs"],
        description="Extensiones de archivo a incluir (con punto)",
        examples=[[".py", ".js"], [".ts", ".tsx"]],
    )
    exclude_dirs: list[str] = Field(
        default_factory=lambda: ["node_modules", "__pycache__", ".git", ".venv"],
        description="Directorios a excluir del conteo",
    )

    model_config = {"extra": "forbid"}
```

Puntos clave:
- Siempre usar `model_config = {"extra": "forbid"}` para que Pydantic rechace campos desconocidos.
- Usar `Field(description=...)` en cada campo: el LLM lee estas descripciones para entender como llamar la tool.
- Los defaults deben ser sensatos para el caso comun.

### 1.3. Paso 2 — Implementar la Tool

Crear la clase que hereda de `BaseTool`:

```python
# src/architect/tools/count_lines.py

from collections import Counter
from pathlib import Path
from typing import Any

from ..execution.validators import PathTraversalError, ValidationError, validate_path
from .base import BaseTool, ToolResult
from .schemas import CountLinesArgs


class CountLinesTool(BaseTool):
    """Cuenta lineas de codigo por lenguaje en un directorio."""

    def __init__(self, workspace_root: Path):
        self.name = "count_lines"
        self.description = (
            "Cuenta lineas de codigo agrupadas por extension/lenguaje. "
            "Util para obtener una vision general del tamano del proyecto. "
            "Excluye lineas vacias y directorios como node_modules."
        )
        self.sensitive = False  # Solo lectura, no requiere confirmacion
        self.args_model = CountLinesArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Cuenta lineas de codigo en el directorio especificado."""
        try:
            # 1. Validar argumentos con Pydantic
            args = self.validate_args(kwargs)

            # 2. Validar path (CRITICO para seguridad)
            target_dir = validate_path(args.path, self.workspace_root)

            if not target_dir.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"'{args.path}' no es un directorio",
                )

            # 3. Logica de la tool
            counts: Counter[str] = Counter()
            file_counts: Counter[str] = Counter()
            exclude = set(args.exclude_dirs)

            for file_path in target_dir.rglob("*"):
                # Saltar directorios excluidos
                if any(part in exclude for part in file_path.parts):
                    continue

                if file_path.is_file() and file_path.suffix in args.extensions:
                    try:
                        lines = file_path.read_text(encoding="utf-8").splitlines()
                        non_empty = sum(1 for line in lines if line.strip())
                        counts[file_path.suffix] += non_empty
                        file_counts[file_path.suffix] += 1
                    except (UnicodeDecodeError, OSError):
                        continue  # Saltar archivos binarios o inaccesibles

            # 4. Formatear resultado
            if not counts:
                return ToolResult(
                    success=True,
                    output=f"No se encontraron archivos con extensiones {args.extensions} en '{args.path}'",
                )

            lines_output = []
            total = 0
            for ext, count in counts.most_common():
                files = file_counts[ext]
                lines_output.append(f"  {ext:8s}  {count:>8,} lineas  ({files} archivos)")
                total += count

            result = (
                f"Conteo de lineas en '{args.path}':\n\n"
                + "\n".join(lines_output)
                + f"\n\n  {'Total':8s}  {total:>8,} lineas"
            )

            return ToolResult(success=True, output=result)

        # 5. NUNCA lanzar excepciones — siempre retornar ToolResult
        except PathTraversalError as e:
            return ToolResult(success=False, output="", error=f"Error de seguridad: {e}")
        except ValidationError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error inesperado: {e}")
```

### 1.4. Paso 3 — Registrar la Tool

Anadir la tool al registry en `src/architect/tools/setup.py`:

```python
# En register_all_tools(), anadir:
from .count_lines import CountLinesTool

def register_all_tools(registry, workspace_config, commands_config=None):
    register_filesystem_tools(registry, workspace_config)
    register_search_tools(registry, workspace_config)
    # ... tools existentes ...

    # Tool custom
    workspace_root = Path(workspace_config.root).resolve()
    registry.register(CountLinesTool(workspace_root))
```

### 1.5. Paso 4 — Autorizar la Tool en los Agentes

Las tools solo estan disponibles para agentes que las listan en `allowed_tools`. Para que `build` pueda usar `count_lines`, anadir al YAML:

```yaml
# architect.yaml
agents:
  build:
    allowed_tools:
      - read_file
      - write_file
      - edit_file
      - apply_patch
      - delete_file
      - list_files
      - search_code
      - grep
      - find_files
      - run_command
      - count_lines    # <-- nueva tool
```

O alternativamente, editar `DEFAULT_AGENTS` en `src/architect/agents/registry.py` para incluirla en la lista de `allowed_tools` del agente `build`.

### 1.6. Checklist de una Tool Correcta

- [ ] `args_model` con `model_config = {"extra": "forbid"}`
- [ ] `execute()` captura TODAS las excepciones y retorna `ToolResult`
- [ ] Usa `validate_path()` si opera sobre archivos
- [ ] `sensitive = True` si modifica estado (archivos, red, etc.)
- [ ] Registrada en `setup.py`
- [ ] Anadida a `allowed_tools` de los agentes relevantes
- [ ] Tiene tests unitarios

---

## 2. Crear un Agente Custom

Un agente es una configuracion que combina un system prompt, un subconjunto de tools y politicas de confirmacion. Hay dos formas de crear agentes custom: via YAML (sin tocar codigo) o via codigo.

### 2.1. Via YAML (recomendado)

La forma mas sencilla. En `architect.yaml`:

```yaml
agents:
  security-audit:
    system_prompt: |
      Eres un agente de auditoría de seguridad. Tu trabajo es analizar
      el codigo fuente buscando vulnerabilidades de seguridad.

      ## Que buscar (por prioridad)

      1. **Critico**: Inyeccion SQL, XSS, path traversal, secrets hardcodeados
      2. **Alto**: Autenticacion debil, falta de validacion de input, CSRF
      3. **Medio**: Dependencias con CVEs, permisos excesivos, logging de datos sensibles
      4. **Bajo**: Headers de seguridad faltantes, configuraciones suboptimas

      ## Formato de salida

      Para cada hallazgo, reportar:
      - Severidad: CRITICO | ALTO | MEDIO | BAJO
      - Archivo y linea
      - Descripcion del problema
      - Remediacion recomendada
      - CWE reference si aplica

      ## Reglas

      - NO modifiques ningun archivo
      - Usa search_code para buscar patrones peligrosos
      - Revisa TODOS los archivos relevantes, no solo los obvios
      - Si no encuentras vulnerabilidades, indicalo explicitamente
    allowed_tools:
      - read_file
      - list_files
      - search_code
      - grep
      - find_files
    confirm_mode: yolo     # Solo lectura, no necesita confirmacion
    max_steps: 30          # Suficiente para un audit completo
```

Ejecutar:

```bash
architect run "Audita la seguridad del modulo de autenticacion" --agent security-audit
```

Campos disponibles en `AgentConfig`:

| Campo | Tipo | Default | Descripcion |
|---|---|---|---|
| `system_prompt` | `str` | (requerido) | Prompt de sistema que define el rol |
| `allowed_tools` | `list[str]` | `[]` | Tools que el agente puede usar |
| `confirm_mode` | `str` | `"confirm-sensitive"` | `"yolo"`, `"confirm-sensitive"`, `"confirm-all"` |
| `max_steps` | `int` | `20` | Maximo de iteraciones del loop |

### 2.2. Via Codigo

Para agentes que forman parte del core, anadir a `src/architect/agents/registry.py`:

```python
# En agents/prompts.py, anadir el prompt:
SECURITY_AUDIT_PROMPT = """..."""

DEFAULT_PROMPTS["security-audit"] = SECURITY_AUDIT_PROMPT

# En agents/registry.py, anadir al dict:
DEFAULT_AGENTS["security-audit"] = AgentConfig(
    system_prompt=DEFAULT_PROMPTS["security-audit"],
    allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
    confirm_mode="yolo",
    max_steps=30,
)
```

### 2.3. Nota sobre i18n (v1.1.0)

Los system prompts de los agentes default (`build`, `plan`, `resume`, `review`) ahora se resuelven via el sistema i18n. Esto significa que cambian de idioma según la configuración `language`. Los agentes custom definidos via YAML mantienen sus prompts tal cual los escribes — no se traducen.

Si quieres que un agente custom soporte múltiples idiomas, puedes usar la API de i18n directamente en código:

```python
from architect.i18n import t

CUSTOM_PROMPT = t("mi_agente.system_prompt")
```

Ver [`i18n.md`](i18n.md) para detalles sobre el sistema de internacionalización.

### 2.4. Escribir System Prompts Efectivos

Un buen system prompt para architect sigue esta estructura:

```
1. ROL: Una frase que define quien es el agente
2. PROCESO: Pasos numerados del workflow
3. HERRAMIENTAS: Tabla de cuando usar cada tool
4. FORMATO: Como estructurar la salida
5. REGLAS: Restricciones explicitas (DO NOT / ALWAYS)
```

Consejos:

- **Ser explicito sobre lo que NO debe hacer**: si el agente es de solo lectura, decirlo claramente.
- **Dar ejemplos de output**: el LLM replica el formato que le muestras.
- **Limitar el scope**: un agente con un rol claro rinde mejor que uno generico.
- **Usar tablas**: el LLM las parsea mejor que listas largas de prosa.

### 2.5. Precedencia de Configuracion

Los agentes siguen este orden de merge (de menor a mayor prioridad):

1. `DEFAULT_AGENTS` en codigo
2. `agents:` en `architect.yaml`
3. Flags de CLI (`--mode`, `--max-steps`)

Un agente YAML puede override parcialmente uno default: si defines solo `max_steps` en YAML para el agente `build`, hereda el `system_prompt` y `allowed_tools` del default.

---

## 3. Hooks del Lifecycle — Guia Practica

Los hooks son comandos shell que se ejecutan automaticamente en puntos clave del lifecycle del agente. Permiten integrar architect con herramientas externas sin modificar codigo.

### 3.1. Los 10 Eventos

| Evento | Cuando se dispara | Puede bloquear? |
|---|---|---|
| `pre_tool_use` | Antes de ejecutar cualquier tool | Si (exit 2) |
| `post_tool_use` | Despues de ejecutar cualquier tool | No |
| `pre_llm_call` | Antes de cada llamada al LLM | Si (exit 2) |
| `post_llm_call` | Despues de cada respuesta del LLM | No |
| `session_start` | Al iniciar una sesion del agente | No |
| `session_end` | Al terminar una sesion | No |
| `on_error` | Cuando un tool falla (success=False) | No |
| `budget_warning` | Cuando el gasto supera warn_at_usd | No |
| `context_compress` | Antes de comprimir el contexto del LLM | No |
| `agent_complete` | Cuando el agente declara tarea completada | No |

Los eventos `pre_*` pueden bloquear la accion (exit code 2). Los eventos `post_*` y los demas son informativos.

### 3.2. Protocolo de Exit Codes

```
Exit 0  →  ALLOW   — La accion se permite.
                      stdout JSON opcional:
                        {"additionalContext": "info extra para el LLM"}
                        {"updatedInput": {"path": "otro.py"}} → MODIFY
Exit 2  →  BLOCK   — La accion se bloquea (solo pre-hooks).
                      stderr = razon del bloqueo (se pasa al LLM).
Otro    →  WARNING — Error del hook. Se logea, pero NO bloquea.
```

### 3.3. Variables de Entorno

Cada hook recibe automaticamente estas variables:

| Variable | Siempre presente | Descripcion |
|---|---|---|
| `ARCHITECT_EVENT` | Si | Nombre del evento (ej: `pre_tool_use`) |
| `ARCHITECT_WORKSPACE` | Si | Path absoluto del workspace |
| `ARCHITECT_TOOL_NAME` | En tool events | Nombre del tool (ej: `write_file`) |
| `ARCHITECT_FILE_PATH` | Si hay archivo involucrado | Path del archivo |

Ademas, cada clave del contexto del evento se inyecta como `ARCHITECT_{KEY}` en mayusculas.

### 3.4. Configuracion en YAML

```yaml
hooks:
  pre_tool_use:
    - name: "secret-scanner"
      command: "python scripts/scan_secrets.py"
      matcher: "write_file|edit_file|apply_patch"  # Solo tools de escritura
      file_patterns: ["*.py", "*.yaml", "*.env"]   # Solo estos archivos
      timeout: 5
      enabled: true

  post_tool_use:
    - name: "auto-formatter"
      command: "black {file} --quiet 2>/dev/null; exit 0"
      matcher: "write_file|edit_file|apply_patch"
      file_patterns: ["*.py"]
      timeout: 10

  on_error:
    - name: "slack-notification"
      command: >
        curl -s -X POST "$SLACK_WEBHOOK_URL"
        -H 'Content-Type: application/json'
        -d "{\"text\": \"Architect error en tool $ARCHITECT_TOOL_NAME\"}"
      async: true   # No bloquear esperando respuesta
      timeout: 15

  budget_warning:
    - name: "budget-alert"
      command: >
        curl -s -X POST "$ALERT_WEBHOOK"
        -d "{\"alert\": \"Architect gasto superado\", \"event\": \"$ARCHITECT_EVENT\"}"
      async: true
      timeout: 10

  session_start:
    - name: "log-session"
      command: "echo \"Session started at $(date)\" >> .architect/sessions.log"

  agent_complete:
    - name: "notify-complete"
      command: "echo 'Tarea completada' | notify-send -t 5000 'Architect'"
      async: true
```

### 3.5. Filtrado con matcher y file_patterns

- **`matcher`**: Regex que se compara contra el nombre del tool. `"*"` (default) matchea todos. Para filtrar por tool especifico: `"write_file"`, o multiples: `"write_file|edit_file|apply_patch"`.
- **`file_patterns`**: Lista de globs que se comparan contra el path del archivo involucrado. Si esta vacio (default), el hook aplica a cualquier archivo. Ejemplo: `["*.py", "*.ts"]`.

Ambos filtros se combinan con AND: el hook solo se ejecuta si AMBOS matchean.

### 3.6. Placeholder `{file}`

En el campo `command`, el placeholder `{file}` se reemplaza por el path del archivo involucrado en la accion. Util para post-hooks de formateo:

```yaml
post_tool_use:
  - name: "format-python"
    command: "black {file} --quiet"
    matcher: "write_file|edit_file"
    file_patterns: ["*.py"]
```

### 3.7. Hooks Async

Los hooks con `async: true` se ejecutan en un thread de background y no bloquean la ejecucion del agente. Utiles para notificaciones, logging externo y webhooks. No tienen efecto en el resultado (no pueden bloquear ni modificar).

### 3.8. Timeout

Cada hook tiene un timeout (default 10 segundos, configurable de 1 a 300). Si el hook excede el timeout:
- Se termina el proceso.
- Se logea un WARNING.
- Se retorna ALLOW (no bloquea).

Para hooks lentos (ej: analisis de seguridad), subir el timeout:

```yaml
pre_tool_use:
  - name: "deep-scan"
    command: "python scripts/deep_security_scan.py"
    timeout: 60
```

### 3.9. Retrocompatibilidad: post_edit

El campo `post_edit` existe para compatibilidad con versiones anteriores. Los hooks definidos ahi se anadon internamente a `post_tool_use` con el matcher `write_file|edit_file|apply_patch`. Usar `post_tool_use` directamente con el matcher apropiado es preferible.

### 3.10. Ejemplo Completo: Secret Scanner Pre-Hook

```python
#!/usr/bin/env python3
"""scripts/scan_secrets.py — Hook que bloquea escrituras con secrets."""

import os
import re
import sys
import json

# Patrones de secrets comunes
SECRET_PATTERNS = [
    (r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9]{20,}", "API key detectada"),
    (r"(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]+['\"]", "Password hardcodeada"),
    (r"(?:secret|token)\s*[:=]\s*['\"][A-Za-z0-9+/]{20,}", "Secret/token detectado"),
    (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Clave privada detectada"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal token detectado"),
    (r"sk-[A-Za-z0-9]{48}", "OpenAI API key detectada"),
]

def main():
    # Leer contexto del stdin (JSON con los args del tool)
    stdin_data = sys.stdin.read()
    if not stdin_data:
        sys.exit(0)  # Sin datos, permitir

    try:
        data = json.loads(stdin_data)
    except json.JSONDecodeError:
        sys.exit(0)

    # Obtener el contenido que se va a escribir
    content = data.get("content", "") or data.get("new_str", "")
    if not content:
        sys.exit(0)  # No hay contenido que escanear

    # Escanear patrones
    for pattern, message in SECRET_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            # Exit 2 = BLOCK. El mensaje va a stderr.
            print(f"BLOQUEADO: {message}. No se permite escribir secrets en el codigo.", file=sys.stderr)
            sys.exit(2)

    # Todo limpio, permitir
    sys.exit(0)

if __name__ == "__main__":
    main()
```

Configuracion:

```yaml
hooks:
  pre_tool_use:
    - name: "secret-scanner"
      command: "python scripts/scan_secrets.py"
      matcher: "write_file|edit_file|apply_patch"
      timeout: 5
```

---

## 4. Skills y .architect.md

Las skills son el mecanismo para inyectar instrucciones contextuales en el system prompt del agente. Hay dos niveles:

### 4.1. Instrucciones de Proyecto

Archivos de instrucciones globales que siempre se inyectan en el system prompt. Architect busca (en orden de prioridad, usa el primero que encuentra):

1. `.architect.md`
2. `AGENTS.md`
3. `CLAUDE.md`

Estos archivos se colocan en la raiz del proyecto y contienen instrucciones generales. Ejemplo:

```markdown
<!-- .architect.md -->
# Instrucciones del Proyecto

## Stack
- Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- Frontend: React 18, TypeScript, TailwindCSS
- Base de datos: PostgreSQL 16

## Convenciones de codigo
- Usar type hints en todas las funciones publicas
- Docstrings en formato Google
- Tests con pytest, minimo 80% cobertura
- Nombres de variables en snake_case, clases en PascalCase

## Estructura
- `src/api/` — endpoints FastAPI
- `src/models/` — modelos SQLAlchemy
- `src/services/` — logica de negocio
- `tests/` — tests unitarios e integracion

## Reglas
- NUNCA modificar las migraciones de Alembic existentes
- SIEMPRE crear una nueva migracion para cambios de schema
- Los endpoints DEBEN tener validacion Pydantic en input y output
```

### 4.2. Skills Contextuales

Las skills son instrucciones que se activan solo cuando el agente trabaja con archivos que matchean ciertos patrones glob. Viven en `.architect/skills/<nombre>/SKILL.md`.

Estructura:

```
.architect/
  skills/
    django/
      SKILL.md
    react/
      SKILL.md
    database/
      SKILL.md
  installed-skills/   # Skills instaladas via `architect install-skill`
    ...
```

Cada `SKILL.md` tiene un frontmatter YAML opcional seguido del contenido markdown:

```markdown
---
name: django
description: Convenciones para desarrollo Django
globs:
  - "*.py"
  - "*/views.py"
  - "*/models.py"
  - "*/serializers.py"
  - "*/urls.py"
---

# Django Conventions

## Modelos
- Usar `models.TextChoices` para campos con opciones fijas
- Cada modelo debe tener `__str__` y `class Meta` con ordering
- Usar `related_name` explicito en ForeignKey y M2M
- NUNCA usar `on_delete=CASCADE` sin pensar en las consecuencias

## Views
- Preferir class-based views (APIView, ViewSet)
- Usar `get_object_or_404` en lugar de try/except
- Serializer validation en el serializer, NO en la view

## URLs
- Usar `path()` con nombres descriptivos
- Namespace por app: `app_name = "users"`

## Tests
- Cada view necesita test de:
  1. Happy path (200/201)
  2. Validacion (400)
  3. Auth (401/403)
  4. Not found (404)
```

### 4.3. Cuando se Activa una Skill

El `SkillsLoader` busca skills cuyo patron `globs` matchea algun archivo activo en la sesion. Por ejemplo, si el agente esta editando `src/users/views.py`, la skill `django` se activaria porque matchea `*/views.py`.

La jerarquia:

1. **Instrucciones de proyecto** (`.architect.md`) se inyectan SIEMPRE.
2. **Skills** se inyectan solo si hay archivos activos que matchean sus globs.

### 4.4. Cuando Usar Cada Uno

| Caso | Mecanismo |
|---|---|
| Reglas que aplican a TODO el proyecto | `.architect.md` |
| Convenciones de un framework/lenguaje especifico | Skill con globs apropiados |
| Instrucciones para un tipo de archivo | Skill con glob de extension (`*.py`) |
| Workflow complejo paso a paso | Skill con descripcion detallada |

### 4.5. Ejemplo Completo: Skill para Desarrollo Django

Crear el directorio y archivo:

```bash
mkdir -p .architect/skills/django
```

Archivo `.architect/skills/django/SKILL.md`:

```markdown
---
name: django
description: Convenciones y mejores practicas para desarrollo Django en este proyecto
globs:
  - "**/*.py"
  - "**/models.py"
  - "**/views.py"
  - "**/serializers.py"
  - "**/admin.py"
  - "**/urls.py"
  - "**/tests/*.py"
  - "**/tests.py"
---

# Convenciones Django del Proyecto

## Estructura de Apps
Cada app Django sigue esta estructura:
```
apps/<nombre>/
  ├── models.py        # Modelos de la app
  ├── views.py         # ViewSets y APIViews
  ├── serializers.py   # Serializers DRF
  ├── urls.py          # URL patterns
  ├── admin.py         # Admin site config
  ├── signals.py       # Signal handlers
  ├── tasks.py         # Celery tasks
  ├── services.py      # Logica de negocio
  └── tests/
      ├── test_models.py
      ├── test_views.py
      └── test_services.py
```

## Reglas de Modelos
- Heredar de `BaseModel` (tiene `created_at`, `updated_at`, `id` UUID)
- Usar `class Meta: ordering = ["-created_at"]` siempre
- Los querysets custom van en un `Manager` separado

## Reglas de Views (DRF)
- Usar `ModelViewSet` para CRUDs completos
- `permission_classes` explicitos en cada viewset
- Paginacion: `PageNumberPagination` con `page_size = 20`

## Reglas de Tests
- Usar `APITestCase` de DRF
- Factory Boy para generar datos: `apps/<nombre>/tests/factories.py`
- `setUp` para autenticacion, `setUpTestData` para datos compartidos
```

### 4.6. Memoria Procedural

Ademas de skills, architect mantiene una **memoria procedural** en `.architect/memory.md`. Este archivo se genera automaticamente cuando el sistema detecta correcciones del usuario (frases como "no, usa X", "eso esta mal", "siempre haz Y"). Las correcciones se persisten y se inyectan en futuras sesiones.

Se puede editar manualmente para anadir reglas permanentes:

```markdown
# Memoria del Proyecto

> Auto-generado por architect. Editable manualmente.

- [2026-01-15] Correccion: Siempre usar python3.12 en lugar de python
- [2026-01-16] Patron: Los imports deben seguir el orden: stdlib, third-party, local
- [2026-02-01] Correccion: No usar print(), usar structlog para todo el logging
```

---

## 5. Guardrails Custom

Los guardrails son la capa de seguridad determinista de architect. Se evaluan **ANTES** que los hooks y no pueden ser desactivados por el LLM. Son reglas rigidas, no heuristicas.

### 5.1. Archivos Sensibles (v1.1.0) — Lectura + Escritura

Patrones glob de archivos que el agente NO puede leer ni modificar. Usa esto para secrets que no deben llegar al LLM:

```yaml
guardrails:
  enabled: true
  sensitive_files:
    - ".env"
    - ".env.*"
    - "*.pem"
    - "*.key"
    - "*.p12"
    - "credentials.json"
    - "*.secret"
```

Cuando el agente intenta leer o escribir un archivo sensible, recibe un error claro: `"Archivo sensible bloqueado por guardrail: .env (patron: .env)"`. Tambien se detectan lecturas shell (`cat .env`, `head *.pem`, `tail .env`) y redirecciones (`echo "data" > .env`).

### 5.2. Archivos Protegidos — Solo Escritura

Patrones glob de archivos que el agente NO puede modificar ni eliminar, pero SI puede leer:

```yaml
guardrails:
  enabled: true
  protected_files:
    - "docker-compose.prod.yaml"
    - "Makefile"
    - "*.lock"           # No tocar lockfiles
    - "deploy/**"
```

Cuando el agente intenta escribir/editar/eliminar un archivo protegido, recibe un error: `"Archivo protegido por guardrail: Makefile (patron: Makefile)"`. El agente puede leer archivos protegidos; solo la escritura esta bloqueada. Tambien se detectan redirecciones shell.

### 5.3. Comandos Bloqueados

Patrones regex de comandos que el agente NO puede ejecutar:

```yaml
guardrails:
  enabled: true
  blocked_commands:
    - 'rm\s+-[rf]+\s+/'            # rm -rf /
    - 'sudo\s+'                     # Cualquier sudo
    - 'chmod\s+777'                 # Permisos inseguros
    - 'git\s+push\s+.*--force'      # Force push
    - 'curl.*\|\s*bash'             # Pipe to bash
    - 'wget.*\|\s*sh'              # Pipe to shell
    - 'DROP\s+TABLE'                # SQL destructivo
    - 'TRUNCATE\s+TABLE'            # SQL destructivo
    - 'npm\s+publish'               # No publicar
    - 'pip\s+install\s+(?!-e)'      # Solo pip install -e permitido
```

Los patrones se evaluan con `re.search()` case-insensitive.

### 5.4. Limites de Edicion

```yaml
guardrails:
  enabled: true
  max_files_modified: 15       # Maximo de archivos distintos modificados
  max_lines_changed: 2000      # Maximo total de lineas cambiadas
  max_commands_executed: 50     # Maximo de comandos shell ejecutados
```

Estos limites se acumulan durante toda la sesion. Cuando se alcanza un limite, el agente recibe un error y no puede hacer mas cambios de ese tipo. Esto previene que el agente "se desboque" modificando archivos indiscriminadamente.

### 5.5. Code Rules

Patrones regex que se escanean en todo contenido que el agente escribe. Utiles para forzar convenciones o prevenir patrones peligrosos:

```yaml
guardrails:
  enabled: true
  code_rules:
    - pattern: 'eval\s*\('
      message: "No usar eval(). Es un riesgo de seguridad. Usa ast.literal_eval() si necesitas parsear."
      severity: block         # block = impide el write

    - pattern: 'import\s+pickle'
      message: "pickle es inseguro para datos no confiables. Usar json o msgpack."
      severity: warn          # warn = permite pero avisa al LLM

    - pattern: 'TODO|FIXME|HACK|XXX'
      message: "No dejar TODO/FIXME en codigo nuevo. Implementa la funcionalidad completa."
      severity: warn

    - pattern: 'print\s*\('
      message: "Usar structlog para logging, no print(). Ejemplo: logger.info('msg', key=value)"
      severity: warn

    - pattern: 'from\s+\.\s+import\s+\*'
      message: "No usar wildcard imports. Importar nombres explicitamente."
      severity: block

    - pattern: 'password\s*=\s*["\'][^"\']+["\']'
      message: "Password hardcodeada detectada. Usar variables de entorno."
      severity: block
```

Severity:
- `"warn"`: El write se permite, pero se adjunta el mensaje al LLM como advertencia.
- `"block"`: El write se bloquea y el LLM recibe el mensaje de error para corregir.

### 5.6. Quality Gates

Comandos que se ejecutan cuando el agente declara que ha terminado. Si un gate requerido falla, el resultado se pasa al agente para que corrija:

```yaml
guardrails:
  enabled: true
  quality_gates:
    - name: "lint"
      command: "ruff check . --select E,W"
      required: true
      timeout: 30

    - name: "type-check"
      command: "mypy src/ --ignore-missing-imports"
      required: true
      timeout: 60

    - name: "tests"
      command: "pytest tests/ -x -q --tb=short"
      required: true
      timeout: 120

    - name: "format-check"
      command: "black . --check --quiet"
      required: false    # Solo informativo, no bloquea
      timeout: 30
```

Cada gate tiene:
- `name`: Nombre descriptivo.
- `command`: Comando shell. Exit 0 = passed, otro = failed.
- `required`: Si `true`, un fallo impide que el agente termine sin corregir.
- `timeout`: Segundos maximos de ejecucion.

### 5.7. require_test_after_edit

```yaml
guardrails:
  enabled: true
  require_test_after_edit: true
```

Cuando esta activo, el agente es forzado a ejecutar tests despues de hacer ediciones. El contador interno se resetea cada vez que el agente ejecuta un comando de test.

### 5.8. Ejemplo Completo: Configuracion Enterprise

```yaml
guardrails:
  enabled: true

  # Archivos intocables
  protected_files:
    - ".env"
    - ".env.*"
    - "*.pem"
    - "*.key"
    - "credentials.json"
    - "*.lock"
    - "docker-compose.prod.yaml"
    - "infrastructure/**"
    - ".github/workflows/**"

  # Comandos peligrosos
  blocked_commands:
    - 'rm\s+-[rf]+\s+/'
    - 'sudo\s+'
    - 'chmod\s+777'
    - 'git\s+push'
    - 'git\s+checkout\s+(main|master|prod)'
    - 'curl.*\|\s*(bash|sh)'
    - 'npm\s+publish'
    - 'docker\s+push'
    - 'kubectl\s+(delete|apply|create)'

  # Limites conservadores
  max_files_modified: 10
  max_lines_changed: 1000
  max_commands_executed: 30
  require_test_after_edit: true

  # Reglas de codigo
  code_rules:
    - pattern: 'eval\s*\('
      message: "eval() prohibido por politica de seguridad"
      severity: block
    - pattern: 'exec\s*\('
      message: "exec() prohibido por politica de seguridad"
      severity: block
    - pattern: 'from\s+\.\s+import\s+\*'
      message: "Wildcard imports prohibidos"
      severity: block
    - pattern: '(password|secret|token|api_key)\s*=\s*["\'][^"\']+["\']'
      message: "Secret hardcodeado detectado. Usar variables de entorno."
      severity: block
    - pattern: 'print\s*\('
      message: "Usar logging en lugar de print()"
      severity: warn

  # Quality gates obligatorios
  quality_gates:
    - name: "ruff"
      command: "ruff check . --select E,W,F"
      required: true
      timeout: 30
    - name: "mypy"
      command: "mypy src/ --strict"
      required: true
      timeout: 120
    - name: "pytest"
      command: "pytest tests/ -x -q --tb=short"
      required: true
      timeout: 180
    - name: "black"
      command: "black . --check"
      required: false
      timeout: 30
```

---

## 6. Tips de Integracion

### 6.1. Orden de Ejecucion (Pipeline Interno)

Cuando el agente ejecuta una tool, el pipeline interno es:

```
1. LLM decide tool call
2. GUARDRAILS: check_file_access / check_command / check_edit_limits
   └── Si BLOCK → error al LLM, no se ejecuta nada
3. PRE-HOOKS: run_event(PRE_TOOL_USE, context)
   └── Si BLOCK → error al LLM, no se ejecuta la tool
   └── Si MODIFY → se usan los args modificados
4. TOOL EXECUTION: tool.execute(**args) → ToolResult
5. CODE RULES: check_code_rules (si la tool escribio contenido)
   └── Si severity=block → el write se deshace
6. POST-HOOKS: run_event(POST_TOOL_USE, context)
   └── Informativo (no bloquea)
7. Resultado se pasa al LLM como tool_result
```

Implicaciones:
- Un guardrail bloquea ANTES que un hook tenga oportunidad de actuar.
- Un pre-hook puede modificar los argumentos de una tool (ej: cambiar el path).
- Las code_rules se evaluan DESPUES de escribir pero ANTES de confirmar al LLM.
- Los post-hooks son ideales para formateo (black, prettier) porque se ejecutan despues del write.

### 6.2. Testear Extensiones Custom

**Tools**: Testear el `execute()` directamente.

```python
import pytest
from pathlib import Path
from architect.tools.count_lines import CountLinesTool

@pytest.fixture
def tool(tmp_path):
    # Crear archivos de prueba
    (tmp_path / "main.py").write_text("line1\nline2\nline3\n")
    (tmp_path / "utils.py").write_text("a\nb\n")
    (tmp_path / "readme.md").write_text("# Readme\n")
    return CountLinesTool(workspace_root=tmp_path)

def test_count_lines_basic(tool):
    result = tool.execute(path=".", extensions=[".py"])
    assert result.success is True
    assert "5 lineas" in result.output or "5" in result.output

def test_count_lines_no_files(tool):
    result = tool.execute(path=".", extensions=[".rs"])
    assert result.success is True
    assert "No se encontraron" in result.output

def test_count_lines_path_traversal(tool):
    result = tool.execute(path="../../etc")
    assert result.success is False
    assert "seguridad" in result.error.lower()
```

**Hooks**: Testear el script como programa independiente.

```bash
# Simular un pre_tool_use con contenido sospechoso
echo '{"content": "api_key = \"sk-12345\""}' | \
  ARCHITECT_EVENT=pre_tool_use \
  ARCHITECT_TOOL_NAME=write_file \
  python scripts/scan_secrets.py
echo "Exit code: $?"   # Debe ser 2 (BLOCK)
```

**Guardrails**: La clase `GuardrailsEngine` es testeable directamente.

```python
from architect.config.schema import GuardrailsConfig
from architect.core.guardrails import GuardrailsEngine

config = GuardrailsConfig(
    enabled=True,
    sensitive_files=[".env", "*.pem"],    # blocks read + write
    protected_files=["*.lock"],           # blocks write only
    blocked_commands=[r"rm\s+-rf"],
)
engine = GuardrailsEngine(config, workspace_root="/tmp/test")

# sensitive_files: blocks both read and write
allowed, reason = engine.check_file_access(".env", "read_file")
assert allowed is False  # cannot read secrets

allowed, reason = engine.check_file_access(".env", "write_file")
assert allowed is False  # cannot write secrets

# protected_files: blocks write only, allows read
allowed, reason = engine.check_file_access("package.lock", "read_file")
assert allowed is True   # can read protected files

allowed, reason = engine.check_file_access("package.lock", "write_file")
assert allowed is False  # cannot write protected files

allowed, reason = engine.check_file_access("src/main.py", "write_file")
assert allowed is True   # normal files: full access
```

### 6.3. Versionado de Configuraciones

Recomendaciones para mantener configuraciones custom en el repositorio:

```
proyecto/
├── architect.yaml          # Config principal (versionada en git)
├── .architect.md           # Instrucciones de proyecto (versionada)
├── .architect/
│   ├── skills/             # Skills del proyecto (versionadas)
│   │   ├── django/SKILL.md
│   │   └── react/SKILL.md
│   ├── memory.md           # Memoria procedural (versionada)
│   └── installed-skills/   # Skills externas (opcionalmente en .gitignore)
├── scripts/
│   ├── scan_secrets.py     # Hooks custom (versionados)
│   └── format_hook.sh
```

- **Versionar** `architect.yaml`, `.architect.md`, skills y scripts de hooks.
- **No versionar** (anadir a `.gitignore`) archivos generados como `.architect/sessions/`, caches, y logs.
- Considerar un `architect.yaml` base compartido y un `architect.local.yaml` (en `.gitignore`) para overrides locales del desarrollador.

### 6.4. Combinando Superficies

Las cinco superficies se complementan:

| Necesidad | Superficie |
|---|---|
| "El agente debe poder ejecutar X" | Tool custom |
| "El agente debe actuar como Y" | Agente custom |
| "Antes/despues de Z, ejecutar W" | Hook |
| "Cuando trabaje con archivos tipo A, seguir estas reglas" | Skill |
| "JAMAS tocar/hacer esto" | Guardrail |

Ejemplo de integracion completa: un equipo que trabaja con Django + React quiere que architect:

1. **Tool custom** `count_lines` para que el agente sepa el tamano del proyecto.
2. **Agente** `security-audit` especializado en buscar vulnerabilidades.
3. **Hook** `pre_tool_use` que escanea secrets antes de cada write.
4. **Hook** `post_tool_use` que ejecuta `black` despues de cada write en `*.py`.
5. **Skill** `django` activada por `*.py` con convenciones del framework.
6. **Skill** `react` activada por `*.tsx` con convenciones de componentes.
7. **Guardrails** que protegen `.env`, `*.pem`, bloquean `rm -rf` y `git push`, limitan a 15 archivos modificados, y fuerzan tests antes de declarar completado.
8. **Quality gates** que ejecutan `ruff`, `mypy` y `pytest` al final.

Todo esto se configura sin tocar el core de architect, usando solo `architect.yaml`, archivos en `.architect/` y scripts en `scripts/`.
