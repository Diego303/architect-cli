# Plan de Implementación v2 — Addendum de Mejoras

Este documento extiende el plan original con 6 nuevas fases (F9–F14) que añaden capacidades competitivas críticas. Cada mejora incluye análisis de valor, diseño técnico detallado e integración con la arquitectura existente.

---

## Resumen de Mejoras

| # | Mejora | Decisión | Fase | Impacto |
|---|--------|----------|------|---------|
| 1 | Diff inteligente (`apply_patch`) | **Añadir — crítico** | F9 | Reduce tokens 60-80%, seguridad, revisión humana |
| 2 | Contexto incremental (indexador + search + grep) | **Añadir — crítico** | F10 | Escala a repos reales |
| 3 | Optimización de tokens (context pruning) | **Añadir — importante** | F11 | Evita crashes por context window |
| 4 | Self-evaluation (critic agent) | **Añadir — opcional con flag** | F12 | Calidad de output, retry inteligente |
| 5 | Ejecución de código (`run_command`) | **Añadir — crítico** | F13 | Poder agentic real |
| 6 | Parallel tool calls | **Añadir — vale la pena** | F11 | Speedup en tareas con múltiples reads |
| 7 | Cost tracking | **Añadir — importante** | F14 | Visibilidad de costes, control de gasto |
| 8 | Prompt caching | **Añadir — vale la pena** | F14 | Ahorro 50-90% en tokens repetidos |

---

## Cambios a la Estructura del Proyecto

Archivos nuevos respecto al plan original (marcados con `+`):

```
src/architect/
├── tools/
│   ├── filesystem.py          # (existente) + edit_file mejorado
│   ├── patch.py               # + apply_patch, diff engine
│   ├── search.py              # + search_code, grep, find_files
│   └── command.py             # + run_command
├── core/
│   ├── loop.py                # (existente) + parallel tool calls
│   ├── context.py             # (existente) + context pruning
│   └── evaluator.py           # + self-evaluation / critic
├── indexer/
│   ├── __init__.py            # +
│   ├── tree.py                # + repo tree indexer
│   ├── symbols.py             # + extracción de símbolos (AST)
│   └── cache.py               # + cache del índice
├── costs/
│   ├── __init__.py            # +
│   ├── tracker.py             # + tracking por step/total
│   ├── prices.py              # + loader de precios
│   └── default_prices.json    # + precios por defecto
└── llm/
    ├── adapter.py             # (existente) + prompt caching headers
    └── cache.py               # + cache local de respuestas
```

---

## FASE 9 — Diff Inteligente y `apply_patch` (Día 13-15)

### Por Qué Es Crítico

El `write_file` actual reemplaza archivos completos. Esto tiene problemas graves:

1. **Tokens desperdiciados**: Un archivo de 500 líneas donde cambias 3 requiere que el LLM genere las 500 líneas. Con diff, genera ~15 líneas.
2. **Errores de regeneración**: El LLM frecuentemente introduce bugs sutiles al regenerar código que no tenía que tocar.
3. **Sin revisión humana posible**: Un `write_file` completo no te dice qué cambió.
4. **Conflictos silenciosos**: Si el archivo cambió entre el `read_file` y el `write_file`, se pierden cambios.

### Diseño: Tres Niveles de Edición

En vez de solo `apply_patch`, el sistema tiene **tres tools de edición** ordenadas por granularidad:

```
┌─────────────────────────────────────────────────┐
│  Nivel 1: edit_file (str_replace)               │
│  → Reemplaza un bloque exacto por otro          │
│  → El más fiable para LLMs                      │
│  → Similar a lo que usa Claude Code internamente │
├─────────────────────────────────────────────────┤
│  Nivel 2: apply_patch (unified diff)            │
│  → Para cambios multi-hunk                      │
│  → Más eficiente en tokens                      │
│  → Requiere formato correcto del LLM            │
├─────────────────────────────────────────────────┤
│  Nivel 3: write_file (reemplazo completo)       │
│  → Solo para archivos nuevos o reescrituras     │
│  → Fallback cuando diff no aplica               │
└─────────────────────────────────────────────────┘
```

### 9.1 — Tool `edit_file` (str_replace — prioridad alta)

Esta es la tool más importante. Es la que mejor entienden los LLMs actuales porque es conceptualmente simple: "busca este texto exacto, reemplázalo por este otro".

```python
# src/architect/tools/filesystem.py

class EditFileArgs(BaseModel):
    path: str
    old_content: str = Field(description="Bloque exacto de texto a reemplazar (debe existir tal cual en el archivo)")
    new_content: str = Field(description="Texto de reemplazo")

class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Reemplaza un bloque de texto exacto en un archivo por texto nuevo. "
        "old_content debe coincidir exactamente con el texto existente incluyendo "
        "espacios e indentación. Para cambios pequeños, esta tool es preferible a write_file."
    )
    sensitive = True
    args_model = EditFileArgs

    def execute(self, path: str, old_content: str, new_content: str) -> ToolResult:
        content = file_path.read_text(encoding="utf-8")

        # Validación: old_content debe existir exactamente una vez
        count = content.count(old_content)
        if count == 0:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"old_content no encontrado en {path}. "
                    f"Verifica espacios, indentación y que el texto sea exacto. "
                    f"Usa read_file para ver el contenido actual."
                )
            )
        if count > 1:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"old_content aparece {count} veces en {path}. "
                    f"Incluye más contexto (líneas antes/después) para que sea único."
                )
            )

        # Aplicar reemplazo
        new_file_content = content.replace(old_content, new_content, 1)

        # Generar diff para log/confirmación
        diff = self._generate_diff(content, new_file_content, path)

        file_path.write_text(new_file_content, encoding="utf-8")

        return ToolResult(
            success=True,
            output=f"Editado {path}.\nDiff:\n{diff}",
        )

    def _generate_diff(self, old: str, new: str, path: str) -> str:
        """Genera unified diff para logging y revisión."""
        import difflib
        return "\n".join(difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        ))
```

**Por qué str_replace es mejor que unified diff para LLMs**: Los LLMs cometen errores frecuentes con el formato de unified diff (números de línea incorrectos, líneas de contexto que no coinciden). Con str_replace, solo necesitan copiar el texto exacto que quieren cambiar, lo cual es mucho más fiable.

### 9.2 — Tool `apply_patch` (unified diff)

Para cambios multi-hunk donde str_replace sería muy verboso:

```python
# src/architect/tools/patch.py
import subprocess
import tempfile

class ApplyPatchArgs(BaseModel):
    path: str
    patch: str = Field(description="Diff en formato unified (como output de `diff -u`)")

class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = (
        "Aplica un patch en formato unified diff a un archivo. "
        "Útil para múltiples cambios en distintas partes del archivo. "
        "El patch debe incluir líneas de contexto correctas. "
        "Para cambios simples, prefiere edit_file."
    )
    sensitive = True
    args_model = ApplyPatchArgs

    def execute(self, path: str, patch: str) -> ToolResult:
        file_path = self._resolve_path(path)

        # 1. Validar que el archivo existe
        if not file_path.exists():
            return ToolResult(success=False, output="", error=f"Archivo no encontrado: {path}")

        # 2. Guardar backup en memoria
        original = file_path.read_text(encoding="utf-8")

        # 3. Intentar aplicar con Python puro (sin dependencia de `patch`)
        try:
            result = self._apply_unified_diff(original, patch)
        except PatchError as e:
            # 4. Si falla el aplicado Python, intentar con `patch` del sistema
            result = self._try_system_patch(file_path, patch)
            if result is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"El patch no aplica limpiamente: {e}. Verifica que las líneas de contexto coincidan con el archivo actual."
                )

        # 5. Validar que el resultado es razonable
        if not result.strip():
            return ToolResult(
                success=False,
                output="",
                error="El patch produjo un archivo vacío. Abortando."
            )

        file_path.write_text(result, encoding="utf-8")

        # 6. Generar resumen
        added = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))

        return ToolResult(
            success=True,
            output=f"Patch aplicado a {path}: +{added} -{removed} líneas.",
        )

    def _apply_unified_diff(self, original: str, patch_text: str) -> str:
        """
        Aplicador de unified diff en Python puro.
        Parsea hunks, valida contexto, aplica cambios.
        """
        lines = original.splitlines(keepends=True)
        hunks = self._parse_hunks(patch_text)

        # Aplicar hunks de atrás hacia adelante (para no desplazar offsets)
        for hunk in reversed(hunks):
            lines = self._apply_hunk(lines, hunk)

        return "".join(lines)

    def _try_system_patch(self, file_path: Path, patch_text: str) -> str | None:
        """Fallback: usa el comando `patch` del sistema."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
            f.write(patch_text)
            patch_file = f.name
        try:
            result = subprocess.run(
                ["patch", "--dry-run", "-p0", str(file_path)],
                input=patch_text, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                # Dry-run exitoso, aplicar de verdad
                subprocess.run(
                    ["patch", "-p0", str(file_path)],
                    input=patch_text, capture_output=True, text=True, timeout=10,
                )
                return file_path.read_text()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
```

### 9.3 — Modificación de `write_file`

`write_file` sigue existiendo pero con advertencias al LLM:

```python
class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Crea un archivo nuevo o reemplaza TODO el contenido de uno existente. "
        "IMPORTANTE: Para editar archivos existentes, prefiere edit_file (cambios pequeños) "
        "o apply_patch (cambios múltiples). Usa write_file solo para archivos nuevos "
        "o cuando necesites reescribir completamente un archivo."
    )
```

### 9.4 — Integración con Confirmación y Dry-Run

El diff generado se muestra en la confirmación:

```python
# En execution/engine.py, al confirmar:
def _format_confirmation(self, tool_name: str, args: dict) -> str:
    if tool_name == "edit_file":
        return (
            f"📝 edit_file: {args['path']}\n"
            f"  Reemplazar:\n"
            f"    {self._indent(args['old_content'])}\n"
            f"  Con:\n"
            f"    {self._indent(args['new_content'])}\n"
        )
    elif tool_name == "apply_patch":
        return f"📝 apply_patch: {args['path']}\n{args['patch']}"
    # ...
```

En dry-run, se muestra el diff sin aplicar — esto es especialmente útil para revisión.

### 9.5 — Guía en el System Prompt

Los prompts de agentes que escriben archivos incluyen guía explícita:

```python
EDIT_GUIDANCE = """
Cuando necesites modificar archivos:
1. SIEMPRE lee el archivo primero con read_file
2. Para cambios pequeños (1-20 líneas): usa edit_file con el texto exacto a reemplazar
3. Para cambios múltiples dispersos: usa apply_patch con formato unified diff
4. Para archivos nuevos o reescrituras completas: usa write_file
5. NUNCA uses write_file para cambiar unas pocas líneas de un archivo grande
"""
```

**Entregable F9**: `edit_file` funciona con str_replace, `apply_patch` aplica diffs, ambas generan diff legible para logs/confirmación. Los prompts guían al LLM a usarlas correctamente.

---

## FASE 10 — Contexto Incremental Inteligente (Día 15-18)

### Por Qué Es Crítico

Sin esto, en un repo de 500 archivos el agente está ciego. Depende de que el humano le diga qué archivos mirar, o de hacer `list_files` → `read_file` uno por uno, quemando contexto.

### 10.1 — Indexador de Repositorio

Un índice ligero que se construye al inicio y se cachea:

```python
# src/architect/indexer/tree.py
from pathlib import Path
from dataclasses import dataclass

@dataclass
class FileInfo:
    path: str              # Relativo al workspace
    size_bytes: int
    lines: int
    language: str          # Detectado por extensión
    last_modified: float

@dataclass
class RepoIndex:
    files: dict[str, FileInfo]  # path → FileInfo
    tree_summary: str           # Árbol formateado (como `tree`)
    total_files: int
    total_lines: int
    languages: dict[str, int]   # language → count

class RepoIndexer:
    IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".eggs", "*.egg-info",
    }
    IGNORE_FILES = {".DS_Store", "Thumbs.db", "*.pyc", "*.pyo"}

    MAX_FILE_SIZE = 1_000_000  # 1MB — archivos mayores se indexan pero no se leen

    def __init__(self, workspace_root: Path):
        self.root = workspace_root

    def build_index(self) -> RepoIndex:
        """Construye índice completo del workspace. ~100ms para repos medianos."""
        files = {}
        for path in self._walk():
            info = self._analyze_file(path)
            files[str(path.relative_to(self.root))] = info

        return RepoIndex(
            files=files,
            tree_summary=self._format_tree(files),
            total_files=len(files),
            total_lines=sum(f.lines for f in files.values()),
            languages=self._count_languages(files),
        )

    def _walk(self) -> Iterator[Path]:
        """Walk respetando .gitignore patterns y IGNORE_DIRS."""
        for item in self.root.rglob("*"):
            if any(ignored in item.parts for ignored in self.IGNORE_DIRS):
                continue
            if item.is_file() and item.stat().st_size <= self.MAX_FILE_SIZE:
                yield item

    def _format_tree(self, files: dict) -> str:
        """
        Genera árbol tipo `tree` pero compacto.
        Para repos >200 archivos, agrupa por directorio.
        """
        # Ejemplo output:
        # src/ (45 files, 3200 lines)
        #   ├── main.py (120 lines)
        #   ├── config/ (8 files)
        #   │   ├── schema.py (85 lines)
        #   │   └── loader.py (60 lines)
        #   └── tools/ (12 files)
        ...

    def _detect_language(self, path: Path) -> str:
        EXT_MAP = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
            ".cpp": "cpp", ".c": "c", ".h": "c-header",
            ".yaml": "yaml", ".yml": "yaml", ".json": "json",
            ".md": "markdown", ".txt": "text", ".sh": "bash",
            ".html": "html", ".css": "css", ".sql": "sql",
        }
        return EXT_MAP.get(path.suffix.lower(), "unknown")
```

### 10.2 — Inyección Automática en el Contexto

El índice se añade al system prompt automáticamente:

```python
# src/architect/core/context.py
class ContextBuilder:
    def build_initial(self, agent_config, prompt, repo_index=None):
        system_parts = [agent_config.system_prompt]

        if repo_index:
            system_parts.append(
                f"\n## Estructura del proyecto\n"
                f"Total: {repo_index.total_files} archivos, "
                f"{repo_index.total_lines} líneas\n"
                f"Lenguajes: {repo_index.languages}\n\n"
                f"```\n{repo_index.tree_summary}\n```\n"
                f"\nUsa search_code o grep para encontrar código relevante "
                f"antes de hacer cambios."
            )

        return [
            {"role": "system", "content": "\n".join(system_parts)},
            {"role": "user", "content": prompt},
        ]
```

### 10.3 — Tool `search_code` (búsqueda semántica por regex)

```python
# src/architect/tools/search.py

class SearchCodeArgs(BaseModel):
    pattern: str = Field(description="Patrón regex a buscar")
    path: str = Field(default=".", description="Directorio o archivo donde buscar")
    file_pattern: str | None = Field(default=None, description="Filtro de archivos, e.g. '*.py'")
    max_results: int = Field(default=20, description="Máximo de resultados")
    context_lines: int = Field(default=2, description="Líneas de contexto antes/después")

class SearchCodeTool(BaseTool):
    name = "search_code"
    description = (
        "Busca un patrón regex en archivos del proyecto. Retorna coincidencias "
        "con contexto. Útil para encontrar definiciones, usos, imports, etc. "
        "Ejemplo: search_code(pattern='def process_', file_pattern='*.py')"
    )
    sensitive = False
    args_model = SearchCodeArgs

    def execute(self, pattern: str, path: str = ".", **kwargs) -> ToolResult:
        import re
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(success=False, output="", error=f"Regex inválido: {e}")

        matches = []
        search_path = self._resolve_path(path)

        for file_path in self._iter_files(search_path, kwargs.get("file_pattern")):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if regex.search(line):
                        ctx_start = max(0, i - kwargs.get("context_lines", 2))
                        ctx_end = min(len(lines), i + kwargs.get("context_lines", 2) + 1)
                        matches.append({
                            "file": str(file_path.relative_to(self.workspace_root)),
                            "line": i + 1,
                            "match": line.strip(),
                            "context": "\n".join(
                                f"{'>' if j == i else ' '} {j+1}: {lines[j]}"
                                for j in range(ctx_start, ctx_end)
                            ),
                        })
                        if len(matches) >= kwargs.get("max_results", 20):
                            break
            except (UnicodeDecodeError, PermissionError):
                continue

        if not matches:
            return ToolResult(success=True, output=f"Sin resultados para '{pattern}'")

        output = f"Encontrados {len(matches)} resultados para '{pattern}':\n\n"
        for m in matches:
            output += f"📄 {m['file']}:{m['line']}\n{m['context']}\n\n"

        return ToolResult(success=True, output=output)
```

### 10.4 — Tool `grep` (búsqueda rápida de texto literal)

```python
class GrepArgs(BaseModel):
    text: str = Field(description="Texto literal a buscar (no regex)")
    path: str = Field(default=".", description="Directorio o archivo")
    file_pattern: str | None = Field(default=None, description="Filtro, e.g. '*.py'")
    max_results: int = Field(default=30)
    case_sensitive: bool = Field(default=True)

class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Busca texto literal en archivos. Más rápido que search_code para "
        "búsquedas simples. Útil para encontrar strings, nombres de variables, "
        "imports específicos, etc."
    )
    sensitive = False
    args_model = GrepArgs

    def execute(self, text: str, **kwargs) -> ToolResult:
        """Implementación con subprocess + grep del sistema cuando disponible."""
        # Intenta usar grep del sistema (10-100x más rápido)
        try:
            result = self._system_grep(text, **kwargs)
            if result is not None:
                return result
        except FileNotFoundError:
            pass
        # Fallback a implementación Python
        return self._python_grep(text, **kwargs)

    def _system_grep(self, text, path=".", **kwargs) -> ToolResult | None:
        """Usa grep/ripgrep del sistema si está disponible."""
        import shutil
        # Preferir ripgrep si existe (mucho más rápido)
        grep_cmd = shutil.which("rg") or shutil.which("grep")
        if not grep_cmd:
            return None

        cmd = [grep_cmd, "-rn", "--max-count", str(kwargs.get("max_results", 30))]
        if not kwargs.get("case_sensitive", True):
            cmd.append("-i")
        if kwargs.get("file_pattern"):
            cmd.extend(["--include", kwargs["file_pattern"]])
        cmd.extend([text, str(self._resolve_path(path))])

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        # Parsear output...
```

### 10.5 — Tool `find_files`

```python
class FindFilesArgs(BaseModel):
    pattern: str = Field(description="Patrón glob para nombres de archivo, e.g. '*.test.py', 'Dockerfile*'")
    path: str = Field(default=".", description="Directorio donde buscar")

class FindFilesTool(BaseTool):
    name = "find_files"
    description = (
        "Encuentra archivos por nombre usando patrones glob. "
        "Útil para localizar archivos de configuración, tests, etc."
    )
    sensitive = False
    args_model = FindFilesArgs
```

### 10.6 — Extracto de Símbolos (opcional, post-MVP)

Un extractor ligero de definiciones usando AST de Python (extensible a otros lenguajes con tree-sitter):

```python
# src/architect/indexer/symbols.py
import ast

@dataclass
class Symbol:
    name: str
    kind: str          # function | class | method | variable
    file: str
    line: int
    signature: str     # e.g. "def process(data: list[dict]) -> bool"

class PythonSymbolExtractor:
    """Extrae definiciones de nivel superior de archivos Python."""

    def extract(self, file_path: Path) -> list[Symbol]:
        try:
            tree = ast.parse(file_path.read_text())
        except SyntaxError:
            return []

        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                symbols.append(Symbol(
                    name=node.name,
                    kind="function",
                    file=str(file_path),
                    line=node.lineno,
                    signature=self._func_signature(node),
                ))
            elif isinstance(node, ast.ClassDef):
                symbols.append(Symbol(
                    name=node.name,
                    kind="class",
                    file=str(file_path),
                    line=node.lineno,
                    signature=f"class {node.name}",
                ))
        return symbols
```

**Esto permite hacer**: `search_code(pattern="class.*Tool")` o que el agente entienda la estructura del código sin leer cada archivo.

### Configuración YAML (adiciones)

```yaml
indexer:
  enabled: true
  max_file_size: 1000000      # 1MB
  exclude_dirs:
    - node_modules
    - .git
    - __pycache__
  exclude_patterns:
    - "*.min.js"
    - "*.map"
  symbols: false              # Extracción AST (post-MVP)
```

**Entregable F10**: Al iniciar, el agente conoce la estructura del repo. `search_code`, `grep` y `find_files` funcionan. En repos de 500+ archivos el agente encuentra lo que necesita sin leer todo.

---

## FASE 11 — Optimización de Tokens y Parallel Tool Calls (Día 18-20)

### 11.1 — Context Pruning (gestión del context window)

El problema es real: en tareas de 15+ pasos, `AgentState.messages` crece hasta explotar el context window. La solución tiene tres niveles:

```
┌──────────────────────────────────────────────┐
│  Nivel 1: Truncado de tool results           │
│  → Cortar outputs >N tokens                  │
│  → Siempre activo                            │
├──────────────────────────────────────────────┤
│  Nivel 2: Resumen de pasos antiguos          │
│  → Resumir steps >K pasos atrás              │
│  → Se activa cuando mensajes > threshold     │
├──────────────────────────────────────────────┤
│  Nivel 3: Sliding window con sumario         │
│  → Mantener solo últimos N pasos completos   │
│  → Pasos antiguos → resumen comprimido       │
│  → Para tareas muy largas                    │
└──────────────────────────────────────────────┘
```

#### Nivel 1: Truncado de Tool Results

```python
# src/architect/core/context.py

class ContextManager:
    MAX_TOOL_RESULT_TOKENS = 2000  # ~8000 chars

    def truncate_tool_result(self, result: str) -> str:
        """Trunca resultados largos preservando inicio y final."""
        if self._estimate_tokens(result) <= self.MAX_TOOL_RESULT_TOKENS:
            return result

        lines = result.splitlines()
        # Mantener primeras 40 y últimas 20 líneas
        head = "\n".join(lines[:40])
        tail = "\n".join(lines[-20:])
        omitted = len(lines) - 60
        return f"{head}\n\n[... {omitted} líneas omitidas ...]\n\n{tail}"

    def _estimate_tokens(self, text: str) -> int:
        """Estimación rápida: ~4 chars por token para inglés/código."""
        return len(text) // 4
```

#### Nivel 2: Resumen de Pasos Antiguos

```python
class ContextManager:
    SUMMARIZE_AFTER_STEPS = 8     # Resumir cuando hay >8 pasos
    KEEP_RECENT_STEPS = 4         # Mantener los últimos 4 completos

    def maybe_compress(self, messages: list[dict], llm: LLMAdapter) -> list[dict]:
        """
        Si hay demasiados mensajes, comprime los antiguos en un resumen.
        """
        tool_exchanges = self._count_tool_exchanges(messages)
        if tool_exchanges <= self.SUMMARIZE_AFTER_STEPS:
            return messages  # No comprimir

        # Separar: system + user original | pasos antiguos | pasos recientes
        system_msg = messages[0]
        user_msg = messages[1]
        old_messages = messages[2:-self.KEEP_RECENT_STEPS * 3]  # ~3 msgs por step
        recent_messages = messages[-self.KEEP_RECENT_STEPS * 3:]

        # Generar resumen de los pasos antiguos
        summary = self._summarize_steps(old_messages, llm)

        return [
            system_msg,
            user_msg,
            {"role": "assistant", "content": f"[Resumen de pasos anteriores]\n{summary}"},
            *recent_messages,
        ]

    def _summarize_steps(self, messages: list[dict], llm: LLMAdapter) -> str:
        """Usa el LLM para resumir pasos anteriores en ~200 tokens."""
        summary_prompt = [
            {"role": "system", "content": (
                "Resume las siguientes acciones del agente en un párrafo conciso. "
                "Incluye: qué archivos se leyeron/modificaron, qué se intentó, "
                "qué funcionó y qué falló. Máximo 200 palabras."
            )},
            {"role": "user", "content": self._format_steps_for_summary(messages)},
        ]
        response = llm.completion(summary_prompt, tools=None)
        return response.content
```

#### Nivel 3: Sliding Window (para tareas >20 pasos)

```python
class ContextManager:
    MAX_CONTEXT_TOKENS = 80000  # Dejar margen para el modelo

    def enforce_window(self, messages: list[dict]) -> list[dict]:
        """Hard limit: si excede MAX_CONTEXT_TOKENS, cortar."""
        total = sum(self._estimate_tokens(str(m)) for m in messages)
        if total <= self.MAX_CONTEXT_TOKENS:
            return messages

        # Mantener system + user + resumen + últimos N steps
        # Ir reduciendo N hasta que quepa
        ...
```

### Configuración

```yaml
context:
  max_tool_result_tokens: 2000
  summarize_after_steps: 8
  keep_recent_steps: 4
  max_context_tokens: 80000     # Ajustar según modelo
```

### 11.2 — Parallel Tool Calls

LiteLLM (y la API de OpenAI) pueden devolver **múltiples tool calls en una sola respuesta**. Hoy el loop las ejecuta secuencialmente. Si son independientes (e.g., leer 5 archivos), se pueden paralelizar.

#### Análisis de Valor

| Escenario | Ganancia |
|-----------|----------|
| Leer 5 archivos (local) | Mínima (~ms cada uno) |
| 3 llamadas MCP remotas | **Significativa** (~3x speedup) |
| 2 búsquedas + 1 read | Moderada |

**Conclusión**: Vale la pena, especialmente para MCP. La implementación es sencilla porque cada tool call es independiente.

#### Implementación

```python
# src/architect/core/loop.py
from concurrent.futures import ThreadPoolExecutor, as_completed

class AgentLoop:
    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolCallResult]:
        """
        Ejecuta tool calls. Paraleliza si son >1 y ninguna es sensible
        que requiera confirmación secuencial.
        """
        # Si alguna requiere confirmación, ejecutar secuencialmente
        if any(self._needs_confirmation(tc) for tc in tool_calls):
            return [self._execute_single(tc) for tc in tool_calls]

        # Si son pocas o locales, secuencial (overhead de threads no vale)
        if len(tool_calls) <= 1:
            return [self._execute_single(tc) for tc in tool_calls]

        # Paralelo para >1 calls independientes
        results = [None] * len(tool_calls)
        with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
            futures = {
                pool.submit(self._execute_single, tc): i
                for i, tc in enumerate(tool_calls)
            }
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()

        return results
```

**Seguridad**: Las tool calls con confirmación siempre se ejecutan secuencialmente. El paralelismo solo aplica en modo `yolo` o para tools no sensibles.

**Entregable F11**: El contexto no explota en tareas largas. Las tool calls paralelas funcionan automáticamente.

---

## FASE 12 — Self-Evaluation (Opcional con Flag) (Día 20-22)

### Diseño: Dos Modos de Evaluación

```
--self-eval off      → Sin evaluación (default)
--self-eval basic    → Validación del resultado final
--self-eval full     → Critic agent + retry inteligente
```

### 12.1 — Modo `basic`: Validación del Resultado

Después de que el agente termina, un paso adicional verifica si la tarea se completó:

```python
# src/architect/core/evaluator.py

class SelfEvaluator:
    def __init__(self, llm: LLMAdapter, log: BoundLogger):
        self.llm = llm
        self.log = log

    def evaluate_basic(self, original_prompt: str, state: AgentState) -> EvalResult:
        """
        Evaluación básica: pregunta al LLM si la tarea se completó.
        Cuesta ~500 tokens extra.
        """
        eval_messages = [
            {"role": "system", "content": (
                "Eres un evaluador. Tu trabajo es verificar si una tarea "
                "se completó correctamente. Responde SOLO con un JSON:\n"
                '{"completed": true/false, "confidence": 0.0-1.0, '
                '"issues": ["...", "..."], "suggestion": "..."}'
            )},
            {"role": "user", "content": (
                f"Tarea original: {original_prompt}\n\n"
                f"Resultado del agente: {state.final_output}\n\n"
                f"Pasos ejecutados:\n{self._summarize_steps(state)}\n\n"
                f"¿Se completó correctamente la tarea?"
            )},
        ]

        response = self.llm.completion(eval_messages)
        return self._parse_eval(response.content)
```

### 12.2 — Modo `full`: Critic + Retry

```python
class SelfEvaluator:
    MAX_RETRIES = 2

    def evaluate_full(
        self, original_prompt: str, state: AgentState, agent_loop: AgentLoop
    ) -> AgentState:
        """
        Evaluación completa con posibilidad de retry.
        1. Evalúa resultado
        2. Si hay problemas, genera prompt de corrección
        3. Re-ejecuta el agente con contexto de lo que falló
        """
        for attempt in range(self.MAX_RETRIES):
            eval_result = self.evaluate_basic(original_prompt, state)

            if eval_result.completed and eval_result.confidence > 0.8:
                self.log.info("eval.passed", attempt=attempt, confidence=eval_result.confidence)
                return state

            self.log.warn("eval.failed", attempt=attempt, issues=eval_result.issues)

            # Generar prompt de corrección
            correction_prompt = (
                f"Tu tarea anterior no se completó correctamente.\n"
                f"Tarea original: {original_prompt}\n"
                f"Problemas detectados: {eval_result.issues}\n"
                f"Sugerencia: {eval_result.suggestion}\n\n"
                f"Por favor, corrige estos problemas."
            )

            # Re-ejecutar con contexto de corrección
            state = agent_loop.run(correction_prompt)

        self.log.warn("eval.max_retries", attempts=self.MAX_RETRIES)
        return state
```

### 12.3 — Integración en el Flujo Principal

```python
# En cli.py
@main.command()
@click.option("--self-eval", type=click.Choice(["off", "basic", "full"]), default="off")
def run(prompt, self_eval, **kwargs):
    # ... setup normal ...

    state = loop.run(prompt)

    # Self-evaluation si está habilitada
    if self_eval != "off" and state.status == "success":
        evaluator = SelfEvaluator(llm, log)
        if self_eval == "basic":
            eval_result = evaluator.evaluate_basic(prompt, state)
            if not eval_result.completed:
                log.warn("eval.incomplete", issues=eval_result.issues)
                state.status = "partial"
        elif self_eval == "full":
            state = evaluator.evaluate_full(prompt, state, loop)
```

### Configuración YAML

```yaml
evaluation:
  mode: "off"           # off | basic | full
  max_retries: 2        # Solo para modo full
  confidence_threshold: 0.8
```

**Entregable F12**: `architect run "..." --self-eval basic` evalúa el resultado. `--self-eval full` reintenta automáticamente si la evaluación falla. Por defecto está desactivado para no gastar tokens extra.

---

## FASE 13 — Ejecución de Código (`run_command`) (Día 22-24)

### Por Qué Es Crítico

Sin `run_command`, el agente no puede:
- Ejecutar tests para verificar que los cambios funcionan
- Compilar código
- Ejecutar linters
- Correr scripts de build
- Verificar que un servicio arranca

Esto limita severamente el "agentic power" — es como tener un desarrollador que solo puede editar archivos pero nunca ejecutar nada.

### Diseño: Seguridad por Capas

`run_command` es la tool más peligrosa del sistema. El diseño aplica múltiples capas de protección:

```
┌─────────────────────────────────────────────────┐
│  Capa 1: Whitelist / Blocklist de comandos      │
│  → Solo permite comandos explícitamente seguros  │
│  → Bloquea patrones peligrosos                   │
├─────────────────────────────────────────────────┤
│  Capa 2: Sensibilidad dinámica                  │
│  → Comandos read-only → no sensible              │
│  → Comandos que escriben → sensible              │
│  → Comandos desconocidos → siempre confirmar     │
├─────────────────────────────────────────────────┤
│  Capa 3: Timeouts y resource limits             │
│  → Timeout por comando                           │
│  → Límite de output                              │
│  → No heredar stdin (headless)                   │
├─────────────────────────────────────────────────┤
│  Capa 4: Sandboxing por directorio              │
│  → cwd siempre es el workspace                   │
│  → No se puede escapar del workspace             │
└─────────────────────────────────────────────────┘
```

### 13.1 — Implementación

```python
# src/architect/tools/command.py
import subprocess
import shlex

class RunCommandArgs(BaseModel):
    command: str = Field(description="Comando a ejecutar en shell")
    cwd: str | None = Field(default=None, description="Directorio de trabajo (relativo al workspace)")
    timeout: int = Field(default=30, description="Timeout en segundos")
    env: dict[str, str] | None = Field(default=None, description="Variables de entorno adicionales")

class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "Ejecuta un comando en el shell del sistema. Útil para:\n"
        "- Ejecutar tests (pytest, npm test, go test)\n"
        "- Compilar código (make, cargo build, tsc)\n"
        "- Ejecutar linters (ruff, eslint, mypy)\n"
        "- Correr scripts (python script.py, bash script.sh)\n"
        "- Verificar estado (git status, ls, cat)\n"
        "El comando se ejecuta en el directorio del workspace."
    )
    sensitive = True  # Base: sensible, pero se ajusta dinámicamente
    args_model = RunCommandArgs

    # Comandos que solo leen — se pueden ejecutar sin confirmación
    SAFE_COMMANDS = {
        "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
        "tree", "file", "which", "echo", "pwd", "env", "date",
        "python --version", "node --version", "pip list",
        "git status", "git log", "git diff", "git show",
    }

    # Prefijos de comandos de desarrollo comunes (semi-seguros)
    DEV_PREFIXES = {
        "pytest", "python -m pytest", "npm test", "npm run",
        "cargo test", "cargo build", "cargo check",
        "go test", "go build", "go vet",
        "make", "tsc", "ruff", "mypy", "eslint", "black --check",
        "pip install", "npm install",
    }

    # Patrones BLOQUEADOS — nunca se ejecutan
    BLOCKED_PATTERNS = [
        r"\brm\s+-rf\s+/",         # rm -rf /
        r"\bsudo\b",                # sudo
        r"\bchmod\s+777\b",        # chmod 777
        r"\bcurl\b.*\|\s*bash",    # curl | bash
        r"\bwget\b.*\|\s*sh",     # wget | sh
        r"\bdd\b.*of=/dev/",      # dd a dispositivos
        r">\s*/dev/sd",            # Escribir a discos
        r"\bmkfs\b",              # Formatear discos
        r"\b:(){ :|:& };:\b",    # Fork bomb
    ]

    def execute(self, command: str, cwd: str | None = None,
                timeout: int = 30, env: dict | None = None) -> ToolResult:
        # 1. Validar contra blocklist
        if self._is_blocked(command):
            return ToolResult(
                success=False, output="",
                error=f"Comando bloqueado por política de seguridad: {command}"
            )

        # 2. Resolver directorio de trabajo
        work_dir = self._resolve_cwd(cwd)

        # 3. Preparar entorno
        proc_env = {**os.environ, **(env or {})}

        # 4. Ejecutar
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                env=proc_env,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,  # Headless: nunca leer stdin
            )

            # 5. Truncar output si es muy largo
            stdout = self._truncate(result.stdout, max_lines=200)
            stderr = self._truncate(result.stderr, max_lines=50)

            output_parts = []
            if stdout:
                output_parts.append(f"stdout:\n{stdout}")
            if stderr:
                output_parts.append(f"stderr:\n{stderr}")
            output_parts.append(f"exit_code: {result.returncode}")

            return ToolResult(
                success=result.returncode == 0,
                output="\n\n".join(output_parts),
                error=stderr if result.returncode != 0 else None,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, output="",
                error=f"Comando excedió timeout de {timeout}s: {command}"
            )

    @property
    def sensitive(self) -> bool:
        """Sensibilidad dinámica basada en el comando."""
        return True  # Base, se override en el engine

    def classify_sensitivity(self, command: str) -> str:
        """
        Clasifica el comando para políticas de confirmación:
        - 'safe': no necesita confirmación
        - 'dev': semi-seguro, depende del modo
        - 'dangerous': siempre confirmar
        """
        cmd_base = command.strip().split()[0] if command.strip() else ""

        if any(command.startswith(safe) for safe in self.SAFE_COMMANDS):
            return "safe"
        if any(command.startswith(prefix) for prefix in self.DEV_PREFIXES):
            return "dev"
        return "dangerous"

    def _is_blocked(self, command: str) -> bool:
        import re
        return any(re.search(pattern, command) for pattern in self.BLOCKED_PATTERNS)

    def _truncate(self, text: str, max_lines: int) -> str:
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text
        head = "\n".join(lines[:max_lines // 2])
        tail = "\n".join(lines[-max_lines // 4:])
        omitted = len(lines) - (max_lines // 2 + max_lines // 4)
        return f"{head}\n\n[... {omitted} líneas omitidas ...]\n\n{tail}"
```

### 13.2 — Integración con Políticas de Confirmación

El Execution Engine trata `run_command` de forma especial:

```python
# src/architect/execution/engine.py
class ExecutionEngine:
    def _should_confirm_command(self, command: str) -> bool:
        classification = RunCommandTool.classify_sensitivity(command)
        match self.confirm_mode:
            case "yolo":
                return classification == "dangerous"  # Incluso en yolo, lo peligroso confirma
            case "confirm-sensitive":
                return classification in ("dev", "dangerous")
            case "confirm-all":
                return True
```

### 13.3 — Configuración

```yaml
commands:
  enabled: true
  default_timeout: 30
  max_output_lines: 200
  blocked_patterns:            # Adicionales a los built-in
    - "docker rm"
  safe_commands:               # Adicionales a los built-in
    - "my-custom-lint"
  allowed_only: false          # Si true, SOLO ejecuta safe + dev commands
```

**Flag CLI**:

```
--allow-commands              Habilita run_command (default: según config)
--no-commands                 Deshabilita run_command completamente
```

**Entregable F13**: `architect run "ejecuta los tests y arregla los que fallen" -a build --mode confirm-sensitive` ejecuta `pytest`, interpreta resultados, edita código, re-ejecuta. Comandos peligrosos se bloquean.

---

## FASE 14 — Cost Tracking y Prompt Caching (Día 24-26)

### 14.1 — Cost Tracking

#### Por Qué Es Importante

En tareas agenticas con 10-20 steps, el coste puede dispararse. Sin tracking, el usuario no tiene visibilidad ni control.

#### Implementación: Precio por Token

```python
# src/architect/costs/tracker.py
from dataclasses import dataclass, field

@dataclass
class StepCost:
    step: int
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    source: str          # "agent" | "eval" | "summary"

@dataclass
class CostTracker:
    steps: list[StepCost] = field(default_factory=list)
    budget_usd: float | None = None

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.steps)

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.steps)

    def record(self, step: int, model: str, usage: dict, source: str = "agent"):
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = self._calculate_cost(model, input_tokens, output_tokens)

        self.steps.append(StepCost(
            step=step,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            source=source,
        ))

        # Check budget
        if self.budget_usd and self.total_cost_usd > self.budget_usd:
            raise BudgetExceededError(
                f"Presupuesto excedido: ${self.total_cost_usd:.4f} > ${self.budget_usd:.4f}"
            )

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = self.price_loader.get_prices(model)
        return (
            (input_tokens / 1_000_000) * prices.input_per_million +
            (output_tokens / 1_000_000) * prices.output_per_million
        )

    def summary(self) -> dict:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "steps": len(self.steps),
            "by_source": self._group_by_source(),
        }
```

#### Loader de Precios

```python
# src/architect/costs/prices.py
import json
from pathlib import Path

@dataclass
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None

class PriceLoader:
    def __init__(self, custom_path: Path | None = None):
        self.prices = self._load_defaults()
        if custom_path:
            self.prices.update(self._load_custom(custom_path))

    def _load_defaults(self) -> dict[str, ModelPricing]:
        """Carga precios por defecto embebidos."""
        default_path = Path(__file__).parent / "default_prices.json"
        return self._parse(json.loads(default_path.read_text()))

    def _load_custom(self, path: Path) -> dict[str, ModelPricing]:
        """Carga precios custom que sobreescriben los defaults."""
        return self._parse(json.loads(path.read_text()))

    def get_prices(self, model: str) -> ModelPricing:
        """Busca precio exacto, luego por prefijo, luego default."""
        if model in self.prices:
            return self.prices[model]
        # Buscar por prefijo (e.g., "gpt-4" matchea "gpt-4-turbo")
        for key, pricing in self.prices.items():
            if model.startswith(key):
                return pricing
        # Default genérico
        return ModelPricing(input_per_million=3.0, output_per_million=15.0)
```

#### default_prices.json

```json
{
  "gpt-4.1": {
    "input_per_million": 2.0,
    "output_per_million": 8.0,
    "cached_input_per_million": 0.5
  },
  "gpt-4.1-mini": {
    "input_per_million": 0.4,
    "output_per_million": 1.6,
    "cached_input_per_million": 0.1
  },
  "gpt-4.1-nano": {
    "input_per_million": 0.1,
    "output_per_million": 0.4,
    "cached_input_per_million": 0.025
  },
  "claude-sonnet-4-20250514": {
    "input_per_million": 3.0,
    "output_per_million": 15.0,
    "cached_input_per_million": 0.3
  },
  "claude-opus-4-20250514": {
    "input_per_million": 15.0,
    "output_per_million": 75.0,
    "cached_input_per_million": 1.5
  },
  "claude-haiku-4-20250514": {
    "input_per_million": 0.80,
    "output_per_million": 4.0,
    "cached_input_per_million": 0.08
  },
  "deepseek/deepseek-chat": {
    "input_per_million": 0.27,
    "output_per_million": 1.10,
    "cached_input_per_million": 0.07
  },
  "gemini/gemini-2.5-pro": {
    "input_per_million": 1.25,
    "output_per_million": 10.0,
    "cached_input_per_million": 0.315
  }
}
```

#### Integración en el Output

```python
# En la salida por terminal (con -v o superior):
# ─── Cost Summary ───
# Steps: 8 | Tokens: 12,450 in / 3,200 out
# Cost: $0.0412 (agent: $0.0380, eval: $0.0032)
# Model: gpt-4.1

# En --json:
{
    "status": "success",
    "output": "...",
    "costs": {
        "total_input_tokens": 12450,
        "total_output_tokens": 3200,
        "total_cost_usd": 0.0412,
        "by_source": {"agent": 0.0380, "eval": 0.0032}
    }
}
```

#### Budget Limit

```yaml
costs:
  enabled: true
  prices_file: ./custom-prices.json   # Override precios
  budget_usd: 1.00                     # Límite por ejecución
  warn_at_usd: 0.50                    # Warning al 50%
```

```
--budget 0.50                          # Override por CLI
```

Cuando se excede el budget, el agente se detiene con status `PARTIAL` y un mensaje claro de por qué.

### 14.2 — Prompt Caching

#### Análisis: ¿Vale la Pena?

Hay dos tipos de "prompt caching" relevantes:

| Tipo | Dónde se cachea | Ahorro | Complejidad |
|------|-----------------|--------|-------------|
| **Provider-side** (Anthropic, OpenAI) | En el proveedor | 50-90% en input tokens | Baja — solo headers |
| **Local cache** | En disco local | 100% (no llama al LLM) | Media — gestión de cache |

**Recomendación**: Implementar ambos, pero priorizar provider-side porque es casi gratis y tiene más impacto en el uso real.

#### Provider-Side Prompt Caching

Anthropic y OpenAI cachean automáticamente el system prompt si se usan los headers correctos. LiteLLM lo soporta:

```python
# src/architect/llm/adapter.py
class LLMAdapter:
    def _prepare_messages_with_caching(self, messages: list[dict]) -> list[dict]:
        """
        Marca el system prompt y mensajes estáticos para caching.
        Funciona con Anthropic (cache_control) y OpenAI (automatic).
        """
        if not self.config.prompt_caching:
            return messages

        enhanced = []
        for msg in messages:
            if msg["role"] == "system":
                # Anthropic: marcar con cache_control
                enhanced.append({
                    **msg,
                    "cache_control": {"type": "ephemeral"},
                })
            else:
                enhanced.append(msg)
        return enhanced

    def completion(self, messages, tools=None, stream=False):
        messages = self._prepare_messages_with_caching(messages)

        response = litellm.completion(
            model=self.config.model,
            messages=messages,
            tools=tools,
            stream=stream,
            timeout=self.config.timeout,
            # LiteLLM pasa cache_control al proveedor automáticamente
        )

        # Registrar si hubo cache hit
        usage = response.usage
        if hasattr(usage, "cache_read_input_tokens"):
            self.log.debug("llm.cache_hit",
                cached_tokens=usage.cache_read_input_tokens)

        return self._normalize_response(response)
```

**Impacto**: En un agent loop de 15 steps, el system prompt (~500-2000 tokens) se envía en cada llamada. Con caching, a partir del step 2 esos tokens cuestan 10% del precio normal. En una tarea con $0.50 de coste, esto ahorra ~$0.10-0.20.

#### Local Cache (para desarrollo)

Cache local de respuestas exactas — útil durante desarrollo para no gastar tokens repitiendo la misma tarea:

```python
# src/architect/llm/cache.py
import hashlib
import json
from pathlib import Path

class LocalLLMCache:
    """
    Cache determinista de respuestas LLM.
    Solo para desarrollo — no usar en producción.
    """
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, messages: list[dict], tools: list[dict] | None) -> LLMResponse | None:
        key = self._make_key(messages, tools)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            return LLMResponse(**data)
        return None

    def set(self, messages: list[dict], tools: list[dict] | None, response: LLMResponse):
        key = self._make_key(messages, tools)
        cache_file = self.cache_dir / f"{key}.json"
        cache_file.write_text(response.model_dump_json())

    def _make_key(self, messages, tools) -> str:
        content = json.dumps({"messages": messages, "tools": tools}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
```

#### Configuración

```yaml
llm:
  prompt_caching: true          # Provider-side caching (recomendado)

cache:
  enabled: false                # Local cache (solo desarrollo)
  dir: ~/.architect/cache
  ttl_hours: 24
```

```
--cache                        # Activa local cache
--no-cache                     # Desactiva
--cache-clear                  # Limpia cache
```

**Entregable F14**: `architect run "..." -v` muestra coste total al final. `--budget 0.50` limita el gasto. Provider-side caching activo por defecto. `--cache` para desarrollo.

---

## Cronograma Actualizado

| Fase | Días | Entregable |
|------|------|-----------|
| F0 — Scaffolding | 1 | Proyecto instalable, CLI con `--help` |
| F1 — Tools + Engine | 2 | Tools locales + validación + dry-run |
| F2 — LLM + Loop | 2 | Agent loop completo funcional |
| F3 — Agentes | 1 | Agentes configurables, modo mixto |
| F4 — MCP | 2 | Conexión y descubrimiento MCP |
| F5 — Logging | 1 | Logs estructurados + stdout |
| F6 — Streaming + Output | 1 | Streaming + JSON + exit codes |
| F7 — Robustez | 1 | Retries + timeouts + graceful shutdown |
| F8 — Integración | 1 | Todo conectado + docs |
| **F9 — Diff inteligente** | **3** | **edit_file + apply_patch + write_file mejorado** |
| **F10 — Contexto inteligente** | **3** | **Indexador + search_code + grep + find_files** |
| **F11 — Token optimization** | **2** | **Context pruning + parallel tool calls** |
| **F12 — Self-evaluation** | **2** | **Critic agent opcional (--self-eval)** |
| **F13 — run_command** | **3** | **Ejecución de código con seguridad por capas** |
| **F14 — Cost + Cache** | **2** | **Cost tracking + prompt caching** |
| **Total** | **~27 días** | **MVP competitivo completo** |

---

## Dependencias Actualizadas

```
F0 (scaffolding)
 ├── F1 (tools + engine)
 │    ├── F9 (diff inteligente)    ← extiende tools existentes
 │    ├── F10 (contexto)           ← nuevas tools + indexador
 │    ├── F13 (run_command)        ← nueva tool
 │    └── F2 (LLM + loop)
 │         ├── F3 (agentes)
 │         ├── F6 (streaming)
 │         ├── F7 (robustez)
 │         ├── F11 (token opt)     ← requiere loop + context
 │         ├── F12 (self-eval)     ← requiere loop + LLM
 │         └── F14 (cost+cache)    ← requiere LLM adapter
 ├── F4 (MCP)
 └── F5 (logging)

F8 (integración) ← requiere todo
```

**Ruta crítica recomendada**: F0 → F1 → F9 → F2 → F10 → F13 → F11 → F3 → F14 → F12

Justificación: Las tools (F9, F10, F13) se construyen antes del loop para que el loop ya las tenga disponibles. El cost tracking (F14) se añade antes que self-eval (F12) para poder medir el coste de la evaluación.

---

## Riesgos Adicionales

| Riesgo | Impacto | Mitigación |
|--------|---------|-----------|
| LLM genera diffs incorrectos en `apply_patch` | Alto | `edit_file` como alternativa principal, fallback a `write_file` |
| `run_command` ejecuta algo destructivo | Crítico | Blocklist + clasificación + confirmación + nunca yolo para "dangerous" |
| Context pruning pierde información crucial | Alto | Mantener siempre los últimos N pasos completos, resumir con el propio LLM |
| Cost tracking con precios desactualizados | Bajo | custom-prices.json overrideable, warning cuando precio es default |
| Self-eval entra en loop de retries | Medio | Hard limit de MAX_RETRIES=2, budget compartido con agente |
| Indexador lento en monorepos enormes | Medio | Respeto de .gitignore, exclude patterns, timeout de 5s |

---

## Config YAML Completa (v2)

```yaml
llm:
  provider: litellm
  mode: proxy
  model: gpt-4.1
  api_base: http://localhost:8000
  api_key_env: LITELLM_API_KEY
  timeout: 60
  retries: 2
  stream: true
  prompt_caching: true

agents:
  plan:
    system_prompt: "..."
    allowed_tools: [read_file, list_files, search_code, grep, find_files]
    confirm_mode: confirm-all
    max_steps: 5

  build:
    system_prompt: "..."
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
    confirm_mode: confirm-sensitive
    max_steps: 25

logging:
  level: info
  file: ~/.architect/logs.json
  verbose: 1

workspace:
  root: .
  allow_delete: true

mcp:
  servers:
    - name: tools1
      url: https://mcp.example.com
      token_env: MCP_TOKEN

indexer:
  enabled: true
  max_file_size: 1000000
  exclude_dirs: [node_modules, .git, __pycache__]
  symbols: false

context:
  max_tool_result_tokens: 2000
  summarize_after_steps: 8
  keep_recent_steps: 4
  max_context_tokens: 80000

commands:
  enabled: true
  default_timeout: 30
  max_output_lines: 200
  allowed_only: false

evaluation:
  mode: "off"
  max_retries: 2
  confidence_threshold: 0.8

costs:
  enabled: true
  prices_file: null
  budget_usd: null
  warn_at_usd: null

cache:
  enabled: false
  dir: ~/.architect/cache
  ttl_hours: 24
```

---

## CLI Actualizado (`--help`)

Nuevos flags respecto al plan original (marcados con `+`):

```
GENERAL:
  -c, --config PATH
  -a, --agent NAME
  -m, --mode MODE
  -w, --workspace PATH
  --dry-run

LLM:
  --model NAME
  --api-base URL
  --api-key KEY
  --no-stream

MCP:
  --mcp-config JSON
  --disable-mcp

LOGGING:
  -v, --verbose
  --log-level LEVEL
  --log-file PATH

EXECUTION:
  --max-steps N
  --timeout SECONDS
+ --allow-commands               Habilita run_command
+ --no-commands                  Deshabilita run_command

EVALUATION:                      + nueva sección
+ --self-eval MODE               off | basic | full

COST:                            + nueva sección
+ --budget USD                   Límite de gasto por ejecución
+ --show-costs                   Muestra resumen de costes al final

CACHE:                           + nueva sección
+ --cache                        Activa local cache
+ --no-cache                     Desactiva cache
+ --cache-clear                  Limpia cache local

OUTPUT:
  --json
  --quiet
```

---

## Resumen: Qué Cambia en Cada Componente Existente

| Componente Original | Cambios |
|---------------------|---------|
| `tools/filesystem.py` | + `edit_file` con str_replace |
| `tools/registry.py` | + registro de search/grep/find_files/run_command |
| `core/loop.py` | + parallel tool calls, + budget check, + context pruning trigger |
| `core/context.py` | + ContextManager con truncado y resumen |
| `llm/adapter.py` | + prompt caching headers, + usage tracking para costs |
| `execution/engine.py` | + clasificación dinámica de sensibilidad para run_command |
| `config/schema.py` | + nuevos modelos: IndexerConfig, ContextConfig, CommandsConfig, etc. |
| `cli.py` | + nuevos flags |
| `agents/prompts.py` | + EDIT_GUIDANCE en prompts de build |