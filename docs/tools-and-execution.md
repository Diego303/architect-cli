# Sistema de tools y ejecución

Describe cómo se definen, registran y ejecutan las herramientas que el agente puede usar.

---

## BaseTool — la interfaz de toda tool

Toda tool (local o MCP) implementa esta clase abstracta:

```python
class BaseTool(ABC):
    name:        str            # identificador único (ej: "write_file", "mcp_github_create_pr")
    description: str            # descripción para el LLM (debe ser precisa y concisa)
    args_model:  type[BaseModel]  # Pydantic model con los argumentos
    sensitive:   bool = False   # True → requiere confirmación en "confirm-sensitive"

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        # NUNCA lanza excepciones. Siempre retorna ToolResult.
        ...

    def get_schema(self) -> dict:
        # Genera el JSON Schema en formato OpenAI function-calling
        # {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    def validate_args(self, args: dict) -> BaseModel:
        # Valida args contra args_model; lanza ValidationError de Pydantic si falla
```

El `get_schema()` produce el formato que LiteLLM/OpenAI espera para tool calling. El `args_model` de Pydantic se convierte automáticamente a JSON Schema.

---

## Resumen de todas las tools disponibles

| Tool | Clase | `sensitive` | Módulo | Propósito |
|------|-------|-------------|--------|-----------|
| `read_file` | `ReadFileTool` | No | `filesystem.py` | Lee un archivo como texto UTF-8 |
| `write_file` | `WriteFileTool` | **Sí** | `filesystem.py` | Escribe o añade contenido a un archivo |
| `delete_file` | `DeleteFileTool` | **Sí** | `filesystem.py` | Elimina un archivo (requiere `allow_delete=true`) |
| `list_files` | `ListFilesTool` | No | `filesystem.py` | Lista archivos con glob y recursión opcionales |
| `edit_file` | `EditFileTool` | **Sí** | `filesystem.py` | Sustituye un bloque exacto de texto en un archivo |
| `apply_patch` | `ApplyPatchTool` | **Sí** | `patch.py` | Aplica un unified diff a un archivo |
| `search_code` | `SearchCodeTool` | No | `search.py` | Busca patrones con regex en el código fuente |
| `grep` | `GrepTool` | No | `search.py` | Busca texto literal (usa rg/grep del sistema si está disponible) |
| `find_files` | `FindFilesTool` | No | `search.py` | Encuentra archivos por nombre o patrón glob |
| `run_command` | `RunCommandTool` | **Dinámico** | `commands.py` | Ejecuta comandos del sistema con 4 capas de seguridad (F13) |

---

## Tools del filesystem

Todas viven en `tools/filesystem.py`. Reciben `workspace_root: Path` en `__init__` y lo pasan a `validate_path()` en cada operación.

### `read_file`

```
ReadFileArgs:
  path: str    # relativo al workspace root
```

Lee el archivo como texto UTF-8. Si el archivo no existe o es un directorio, devuelve `ToolResult(success=False)`.

### `write_file`

```
WriteFileArgs:
  path:    str
  content: str
  mode:    str = "overwrite"   # "overwrite" | "append"
```

Crea directorios padres automáticamente si no existen. `sensitive=True`.

**Cuándo usar**: archivos nuevos o reescrituras completas. Para cambios parciales, usar `edit_file` o `apply_patch`.

### `delete_file`

```
DeleteFileArgs:
  path: str
```

Tiene una doble verificación:
1. `allow_delete` en `WorkspaceConfig` (apagado por defecto).
2. `validate_path()` para prevenir traversal.

```python
if not self.allow_delete:
    return ToolResult(success=False, output="Error: eliminación deshabilitada.",
                      error="allow_delete=False en WorkspaceConfig")
```

### `list_files`

```
ListFilesArgs:
  path:      str       = "."
  pattern:   str|None  = None   # glob (ej: "*.py", "**/*.md", "src/**/*.ts")
  recursive: bool      = False
```

Retorna una lista de paths relativos al workspace root.

---

## Tools de edición incremental (F9)

Preferir estas tools sobre `write_file` para modificar archivos existentes. Consumen menos tokens y tienen menos riesgo de introducir errores.

### `edit_file` — sustitución exacta de texto

```
EditFileArgs:
  path:    str   # archivo a modificar
  old_str: str   # texto exacto a reemplazar (debe ser único en el archivo)
  new_str: str   # texto de reemplazo
```

**Comportamiento**:
- Valida que `old_str` aparezca **exactamente una vez** en el archivo.
- Si aparece 0 veces → `ToolResult(success=False, "old_str no encontrado")`.
- Si aparece más de una vez → `ToolResult(success=False, "old_str no es único")`.
- Si tiene éxito → devuelve el unified diff del cambio.
- `sensitive=True`.

**Cuándo usar**: cambiar una función, una clase, un bloque de código. El `old_str` debe ser suficientemente largo para ser único (incluir contexto si es necesario).

```python
# Ejemplo de uso del agente
edit_file(
    path="src/utils.py",
    old_str="def calculate(a, b):\n    return a + b",
    new_str="def calculate(a: int, b: int) -> int:\n    \"\"\"Suma dos enteros.\"\"\"\n    return a + b",
)
```

### `apply_patch` — unified diff completo

```
ApplyPatchArgs:
  path:  str   # archivo a modificar
  patch: str   # unified diff con uno o más hunks
```

**Formato del patch**:
```
--- a/src/utils.py
+++ b/src/utils.py
@@ -10,7 +10,10 @@
 def foo():
-    return 1
+    return 2
+
+def bar():
+    return 3
```

**Comportamiento**:
1. Intenta parsear y aplicar el diff con el parser puro-Python interno.
2. Si falla (contexto no coincide, numeración incorrecta), intenta con el comando `patch` del sistema.
3. Si ambos fallan → `ToolResult(success=False)` con descripción del error.
- `sensitive=True`.

**Cuándo usar**: múltiples cambios en un archivo (varios hunks), o cuando el LLM tiene el diff completo listo.

### Jerarquía de edición (BUILD_PROMPT)

El system prompt del agente `build` incluye esta guía explícita:

```
1. edit_file   — cambio de un único bloque contiguo (preferido)
2. apply_patch — múltiples cambios en un archivo o diff preexistente
3. write_file  — archivos nuevos o reorganizaciones completas del archivo
```

---

## Tools de búsqueda (F10)

Viven en `tools/search.py`. Reciben `workspace_root: Path`. Todas son `sensitive=False` (solo lectura).

### `search_code` — regex con contexto

```
SearchCodeArgs:
  pattern:        str            # expresión regular
  path:           str = "."      # directorio donde buscar (relativo al workspace)
  file_pattern:   str = "*.py"   # glob para filtrar archivos
  context_lines:  int = 2        # líneas antes y después de cada match
  max_results:    int = 50       # límite de resultados
```

Usa el módulo `re` de Python. Devuelve matches con número de línea y contexto.

```bash
# Agente buscando todos los uses de validate_path
search_code(pattern="validate_path", file_pattern="*.py", context_lines=3)
```

### `grep` — búsqueda de texto literal

```
GrepArgs:
  pattern:       str            # texto literal (no regex)
  path:          str = "."
  file_pattern:  str = "*"
  recursive:     bool = True
  case_sensitive: bool = True
  max_results:   int = 100
```

**Implementación**: usa `rg` (ripgrep) si está instalado, luego `grep`, luego Python puro como fallback. El agente siempre recibe resultados independientemente del sistema.

```bash
# Agente buscando imports de un módulo específico
grep(pattern="from architect.core import", file_pattern="*.py")
```

### `find_files` — buscar archivos por nombre

```
FindFilesArgs:
  pattern:   str         # glob de nombre de archivo (ej: "*.yaml", "test_*.py", "README*")
  path:      str = "."   # directorio raíz de búsqueda
  recursive: bool = True
```

```bash
# Agente buscando todos los archivos de configuración
find_files(pattern="*.yaml")
find_files(pattern="*.env*")
find_files(pattern="conftest.py")
```

---

## Tool `run_command` — ejecución de código (F13)

Vive en `tools/commands.py`. Disponible solo para el agente `build` por defecto. Se habilita/deshabilita con `commands.enabled` en config o los flags `--allow-commands`/`--no-commands`.

```
RunCommandArgs:
  command: str          # comando a ejecutar (shell string)
  cwd:     str | None   # directorio de trabajo relativo al workspace (default: workspace root)
  timeout: int = 30     # segundos (1-600; override del default_timeout de config)
  env:     dict | None  # variables de entorno adicionales (se suman a las del proceso)
```

### 4 capas de seguridad

**Capa 1 — Blocklist** (`BLOCKED_PATTERNS`): regexes que bloquean comandos destructivos **siempre**, independientemente del modo de confirmación. Incluye: `rm -rf /`, `rm -rf ~`, `sudo`, `su`, `chmod 777`, `curl|bash`, `wget|bash`, `dd of=/dev/`, `> /dev/sd*`, `mkfs`, fork bomb, `pkill -9 -f`, `killall -9`.

**Capa 2 — Clasificación dinámica** (`classify_sensitivity()`): cada comando se clasifica en:
- `'safe'` — comandos de solo lectura/consulta: `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, `tree`, `file`, `which`, `echo`, `pwd`, `env`, `date`, `python --version`, `git status`, `git log`, `git diff`, `git show`, `git branch` (vista), `npm list`, `cargo check`, etc.
- `'dev'` — herramientas de desarrollo: `pytest`, `python -m pytest`, `mypy`, `ruff`, `black`, `eslint`, `make`, `cargo build`, `go build`, `mvn`, `gradle`, `tsc`, `npm run`, `pnpm run`, `yarn run`, `docker ps`, `kubectl get`, etc.
- `'dangerous'` — cualquier comando no reconocido explícitamente como safe o dev.

**Capa 3 — Timeouts + output limit**: `subprocess.run(..., timeout=N, stdin=subprocess.DEVNULL)`. El proceso es headless (sin stdin). La salida se trunca a `max_output_lines` preservando inicio y final.

**Capa 4 — Directory sandboxing**: el `cwd` del subproceso se valida con `validate_path()` — siempre dentro del workspace.

### Tabla de confirmación dinámica

La sensibilidad de `run_command` no es estática (`tool.sensitive`). `ExecutionEngine._should_confirm_command()` consulta `classify_sensitivity()` en tiempo real:

| Clasificación | `yolo` | `confirm-sensitive` | `confirm-all` |
|---------------|--------|---------------------|---------------|
| `safe` | No | No | Sí |
| `dev` | No | **Sí** | Sí |
| `dangerous` | No | **Sí** | Sí |

El modo `yolo` **nunca** confirma ningún comando (ni `safe`, ni `dev`, ni `dangerous`). La seguridad contra comandos destructivos se garantiza exclusivamente mediante la Capa 1 (blocklist), que bloquea siempre independientemente del modo de confirmación.

### `allowed_only`

Si `commands.allowed_only: true`, los comandos clasificados como `dangerous` se rechazan en `execute()` sin llegar a la confirmación. Útil en CI donde solo se quiere permitir un whitelist estricto.

```python
# Ejemplo con allowed_only=True:
run_command(command="npm install --global malicious-pkg")
# → ToolResult(success=False, "Comando clasificado como 'dangerous' y allowed_only=True")
```

---

## Validación de paths — seguridad

`execution/validators.py` es la única puerta de seguridad para todas las operaciones de archivos.

```python
def validate_path(path: str, workspace_root: Path) -> Path:
    resolved = (workspace_root / path).resolve()
    if not resolved.is_relative_to(workspace_root.resolve()):
        raise PathTraversalError(f"Path '{path}' escapa del workspace")
    return resolved
```

El truco es `Path.resolve()`:
- Colapsa `../..` → ruta absoluta real.
- Resuelve symlinks → previene escapes vía symlinks.
- Hace que `../../etc/passwd` → `/etc/passwd`, que claramente no es `is_relative_to(workspace)`.
- Paths absolutos como `/etc/passwd` también fallan (Python ignora workspace_root con paths absolutos, y luego `is_relative_to` falla).

**Todos los paths del usuario pasan por `validate_path()` antes de cualquier operación de I/O.**

---

## ToolRegistry

Almacén central en memoria.

```python
class ToolRegistry:
    _tools: dict[str, BaseTool]

    register(tool, allow_override=False)
    # Lanza DuplicateToolError si ya existe y allow_override=False

    get(name) -> BaseTool
    # Lanza ToolNotFoundError si no existe

    list_all() -> list[BaseTool]     # ordenado por nombre
    get_schemas(allowed=None) -> list[dict]
    # allowed=None → schemas de todas las tools
    # allowed=["read_file","list_files"] → solo esas dos
    # Nombres no encontrados se ignoran silenciosamente (no lanza error)

    filter_by_names(names) -> list[BaseTool]
    has_tool(name) -> bool
    count() -> int
    clear()  # para testing
```

`get_schemas(allowed_tools)` es el método crítico que se llama en cada iteración del loop para obtener los schemas que se envían al LLM.

### Función `register_all_tools()`

`tools/setup.py` define cómo se registran todas las tools:

```python
def register_filesystem_tools(registry, workspace_config):
    root = workspace_config.root.resolve()
    registry.register(ReadFileTool(root))
    registry.register(WriteFileTool(root))
    registry.register(DeleteFileTool(root, workspace_config.allow_delete))
    registry.register(ListFilesTool(root))
    registry.register(EditFileTool(root))
    registry.register(ApplyPatchTool(root))

def register_search_tools(registry, workspace_config):
    root = workspace_config.root.resolve()
    registry.register(SearchCodeTool(root))
    registry.register(GrepTool(root))
    registry.register(FindFilesTool(root))

def register_command_tools(registry, workspace_config, commands_config):
    if not commands_config.enabled:
        return
    root = workspace_config.root.resolve()
    registry.register(RunCommandTool(root, commands_config))

def register_all_tools(registry, workspace_config, commands_config=None):
    register_filesystem_tools(registry, workspace_config)
    register_search_tools(registry, workspace_config)
    if commands_config is None:
        commands_config = CommandsConfig()
    register_command_tools(registry, workspace_config, commands_config)
```

La CLI usa `register_all_tools()` — todas las tools siempre están disponibles en el registry. El filtrado por agente se hace a través de `allowed_tools` en `AgentConfig`. La tool `run_command` se registra solo si `commands_config.enabled=True`.

---

## ExecutionEngine — el pipeline de ejecución

Punto de entrada obligatorio para TODA ejecución de tool. **Nunca lanza excepciones.**

```python
class ExecutionEngine:
    registry:      ToolRegistry
    config:        AppConfig
    dry_run:       bool = False
    policy:        ConfirmationPolicy
    hook_executor: HookExecutor | None = None       # v4-A1: lifecycle hooks
    guardrails:    GuardrailsEngine | None = None    # v4-A2: deterministic rules
    hooks:         PostEditHooks | None = None       # v3-M4: legacy (backward-compat)

    def execute_tool_call(self, tool_name: str, args: dict) -> ToolResult:
```

### Los 10 pasos del pipeline (v4)

```
1.  registry.get(tool_name)
    ✗ ToolNotFoundError → return ToolResult(success=False, "Tool no encontrada")

2.  tool.validate_args(args)
    ✗ ValidationError → return ToolResult(success=False, "Argumentos inválidos: ...")

3.  guardrails.check_*()  [v4-A2: si guardrails configurado]
    → check_file_access() para tools de filesystem
    → check_command() para run_command
    → check_edit_limits() para edit/write/patch
    → check_code_rules() para contenido escrito
    ✗ Bloqueado → return ToolResult(success=False, "Guardrail: {razón}")

4.  hook_executor.run_event(PRE_TOOL_USE)  [v4-A1: pre-hooks]
    → HookDecision.BLOCK → return ToolResult(success=False, "Bloqueado por hook: {razón}")
    → HookDecision.MODIFY → actualizar args con updated_input

5.  policy.should_confirm(tool)
    → True: policy.request_confirmation(tool_name, args, dry_run)
        ✗ NoTTYError → return ToolResult(success=False, "No hay TTY para confirmar")
        ✗ user cancela → return ToolResult(success=False, "Acción cancelada por usuario")

6.  if dry_run:
    → return ToolResult(success=True, "[DRY-RUN] Se ejecutaría: tool_name(args)")

7.  tool.execute(**validated_args.model_dump())
    (tool.execute() no lanza — si hay excepción interna, la tool la captura)

8.  hook_executor.run_event(POST_TOOL_USE)  [v4-A1: post-hooks]
    → adicional_context se añade al ToolResult
    (también: run_post_edit_hooks legacy para backward-compat v3-M4)

9.  log resultado (structlog)

10. return ToolResult
```

Hay un `try/except Exception` exterior que captura cualquier error inesperado del paso 5 y lo convierte en `ToolResult(success=False)`.

El resultado de error se devuelve al agente como mensaje de tool, y el LLM puede decidir intentar otra cosa. **Los errores de tools no rompen el loop.**

---

## ConfirmationPolicy

Implementa la lógica de confirmación interactiva.

```python
class ConfirmationPolicy:
    mode: str   # "yolo" | "confirm-all" | "confirm-sensitive"

    def should_confirm(self, tool: BaseTool) -> bool:
        if mode == "yolo":             return False   # nunca confirma
        if mode == "confirm-all":      return True    # siempre confirma
        if mode == "confirm-sensitive": return tool.sensitive  # solo si sensitive=True
```

```python
    def request_confirmation(self, tool_name, args, dry_run=False) -> bool:
        if not sys.stdin.isatty():
            raise NoTTYError(
                "Modo confirm requiere TTY interactiva. "
                "En CI usa --mode yolo o --dry-run."
            )
        # Muestra: "¿Ejecutar 'write_file' con args=...? [y/n/a]"
        # 'y' → True (ejecutar)
        # 'n' → False (cancelar esta tool, continúa el loop)
        # 'a' → sys.exit(130) (abortar todo)
```

Sensibilidad por defecto de cada tool:

| Tool | `sensitive` | Requiere confirmación en `confirm-sensitive` |
|------|-------------|----------------------------------------------|
| `read_file`, `list_files`, `search_code`, `grep`, `find_files` | No | No |
| `write_file`, `delete_file`, `edit_file`, `apply_patch` | **Sí** | **Sí** |
| Todas las tools MCP | **Sí** | **Sí** |
| `run_command` (safe) | Dinámico | No |
| `run_command` (dev) | Dinámico | **Sí** |
| `run_command` (dangerous) | Dinámico | **Sí** |

Para `run_command`, `ExecutionEngine` llama a `_should_confirm_command()` que consulta `tool.classify_sensitivity(command)` en lugar de usar el atributo estático `tool.sensitive`.

---

## HookExecutor — hooks del lifecycle (v4-A1)

A partir de v0.16.0, el sistema de hooks soporta **10 eventos del lifecycle**. Los hooks se ejecutan como subprocesos shell y reciben contexto via variables de entorno `ARCHITECT_*`.

### Eventos y tipos

| Evento | Tipo | Puede BLOCK |
|--------|------|:-----------:|
| `pre_tool_use` | Pre-hook | Sí |
| `post_tool_use` | Post-hook | No |
| `pre_llm_call` | Pre-hook | Sí |
| `post_llm_call` | Post-hook | No |
| `session_start` | Notificación | No |
| `session_end` | Notificación | No |
| `on_error` | Notificación | No |
| `budget_warning` | Notificación | No |
| `context_compress` | Notificación | No |
| `agent_complete` | Notificación | No |

### Exit code protocol

- **Exit 0** → ALLOW. stdout puede contener JSON con `additionalContext` o `updatedInput`.
- **Exit 2** → BLOCK (solo pre-hooks). stderr contiene la razón.
- **Otro** → Error. Se logea como warning, no rompe el loop. Decisión = ALLOW.

### Configuración

```yaml
hooks:
  pre_tool_use:
    - name: validate-secrets
      command: "bash scripts/check.sh"
      matcher: "write_file|edit_file"
      file_patterns: ["*.py"]
      timeout: 5
  post_tool_use:
    - name: python-lint
      command: "ruff check {file} --no-fix"
      file_patterns: ["*.py"]
      timeout: 15
```

### Retrocompatibilidad v3-M4

`hooks.post_edit` sigue funcionando y se mapea internamente a `post_tool_use` con matcher automático para `edit_file|write_file|apply_patch`. El `PostEditHooks` legacy sigue disponible.

Si un hook falla (exit code != 0), su output se añade al tool result. En el log HUMAN se muestra con iconos:

```
      🔍 Hook python-lint: ⚠️
```

Y en el tool result que recibe el LLM:

```
[Hook python-lint: FALLO (exit 1)]
src/main.py:15:5: F841 local variable 'x' is assigned to but never used
```

---

## GuardrailsEngine — seguridad determinista (v4-A2)

Motor de reglas deterministas evaluado **ANTES** que los hooks en el pipeline de ejecución. No puede ser desactivado por el LLM.

### Checks disponibles

| Check | Método | Cuándo |
|-------|--------|--------|
| Archivos protegidos | `check_file_access()` | En tools de filesystem (write, edit, delete) |
| Comandos bloqueados | `check_command()` | En `run_command` |
| Límites de edición | `check_edit_limits()` | En tools de edición |
| Reglas de código | `check_code_rules()` | En contenido escrito |
| Quality gates | `run_quality_gates()` | Al completar el agente |

Los guardrails se configuran en `guardrails:` del YAML. Si un guardrail bloquea, ni siquiera se ejecutan los hooks pre_tool_use.

---

## MCPToolAdapter — tools remotas como locales

`MCPToolAdapter` hereda de `BaseTool` y hace que una tool de un servidor MCP sea indistinguible de una tool local.

```python
class MCPToolAdapter(BaseTool):
    name = f"mcp_{server_name}_{original_name}"
    # Prefijo evita colisiones cuando dos servidores tienen tools con el mismo nombre

    sensitive = True   # todas las tools MCP son sensibles por defecto

    args_model = _build_args_model(tool_definition["inputSchema"])
    # Genera un Pydantic model dinámicamente desde el JSON Schema del servidor MCP

    def execute(self, **kwargs) -> ToolResult:
        result = client.call_tool(original_name, kwargs)
        return ToolResult(success=True, output=_extract_content(result))
```

El generador de `args_model` traduce tipos JSON Schema a Python:
```
"string"  → str
"integer" → int
"number"  → float
"boolean" → bool
"array"   → list
"object"  → dict
```

Campos requeridos → `(type, ...)` (Pydantic required).
Campos opcionales → `(type | None, None)` (Pydantic optional con default None).

### Auto-inyección de MCP tools en `allowed_tools`

A partir de v0.16.2, las tools MCP descubiertas se inyectan automáticamente en el `allowed_tools` del agente activo. Esto resuelve el problema de que un agente con `allowed_tools` explícito (como `build`) filtraba las tools MCP porque no estaban en su lista.

```python
# En cli.py, después de resolver el agent_config:
if agent_config.allowed_tools:
    mcp_tool_names = [t.name for t in registry.list_all() if t.name.startswith("mcp_")]
    agent_config.allowed_tools.extend(mcp_tool_names)
```

Esto significa que un agente `build` con `allowed_tools: [read_file, write_file, ...]` automáticamente también tendrá acceso a `mcp_github_create_pr`, `mcp_database_query`, etc. sin necesidad de configurarlos manualmente.

---

## Ciclo de vida de una tool call

```
LLMResponse.tool_calls = [ToolCall(id="call_abc", name="edit_file", arguments={...})]
                              │
                              ▼
ExecutionEngine.execute_tool_call("edit_file", {path:"main.py", old_str:"...", new_str:"..."})
  │
  ├─ registry.get("edit_file")               → EditFileTool
  ├─ validate_args({path:..., old_str:..., new_str:...}) → EditFileArgs(...)
  │
  ├─ [v4-A2] guardrails.check_file_access("main.py", "edit_file") → (True, "")
  ├─ [v4-A2] guardrails.check_edit_limits("main.py", lines_added, lines_removed) → (True, "")
  │
  ├─ [v4-A1] hook_executor.run_event(PRE_TOOL_USE, context) → [HookResult(ALLOW)]
  │
  ├─ policy.should_confirm(edit_file)         → True (sensitive=True, mode=confirm-sensitive)
  ├─ request_confirmation("edit_file", ...)   → user: y
  ├─ edit_file.execute(path="main.py", old_str="...", new_str="...")
  │     └─ validate_path("main.py", workspace) → /workspace/main.py ✓
  │     └─ file.read_text() → content
  │     └─ assert old_str aparece exactamente 1 vez
  │     └─ content.replace(old_str, new_str, 1)
  │     └─ file.write_text(new_content)
  │     └─ ToolResult(success=True, output="[unified diff del cambio]")
  │
  ├─ [v4-A1] hook_executor.run_event(POST_TOOL_USE, context)
  │     └─ hook "python-lint": ruff check /workspace/main.py --no-fix
  │     └─ hook "python-typecheck": mypy /workspace/main.py --no-error-summary
  │     └─ resultado de hooks se añade al ToolResult.output
  └─ return ToolResult

ContextBuilder.append_tool_results(messages, [ToolCall(...)], [ToolResult(...)])
  → messages += [
      {"role":"assistant", "tool_calls":[{"id":"call_abc","function":{...}}]},
      {"role":"tool", "tool_call_id":"call_abc", "content":"[diff + hook results...]"}
    ]
```

El resultado de la tool (éxito o error) siempre vuelve al LLM como mensaje `tool`, incluyendo la salida de los hooks post-edición si aplican. El LLM decide qué hacer a continuación y puede auto-corregir errores detectados por los hooks.

El pipeline completo con v4 Phase A:
```
Guardrails (determinista) → Pre-hooks (shell) → Confirmación → Ejecución → Post-hooks → LLM
```
