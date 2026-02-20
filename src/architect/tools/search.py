"""
Tools de búsqueda de código.

Proporciona capacidades para encontrar código en el workspace sin
necesidad de leer archivo por archivo. Incluye:

- search_code: búsqueda regex con contexto
- grep: búsqueda de texto literal (usa rg/grep del sistema si está disponible)
- find_files: búsqueda de archivos por patrón glob

Todas respetan los mismos directorios de exclusión que el indexador
(.git, node_modules, __pycache__, etc.).
"""

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

from ..execution.validators import PathTraversalError, validate_path
from .base import BaseTool, ToolResult
from .schemas import FindFilesArgs, GrepArgs, SearchCodeArgs


# Directorios ignorados en búsquedas (mismos que el indexador)
SEARCH_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "dist",
    "build",
})


def _iter_files(search_root: Path, file_pattern: str | None = None) -> Iterator[Path]:
    """Itera sobre archivos del workspace respetando exclusiones.

    Args:
        search_root: Directorio raíz de búsqueda
        file_pattern: Patrón glob opcional para filtrar archivos por nombre

    Yields:
        Path de cada archivo que pasa los filtros
    """
    for dirpath, dirnames, filenames in os.walk(search_root):
        # Excluir directorios ignorados y ocultos (in-place)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SEARCH_IGNORE_DIRS and not d.startswith(".")
        )

        for filename in sorted(filenames):
            if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                continue
            yield Path(dirpath) / filename


class SearchCodeTool(BaseTool):
    """Busca un patrón regex en archivos del workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.name = "search_code"
        self.description = (
            "Busca un patrón regex en archivos del proyecto. "
            "Retorna coincidencias con contexto (líneas vecinas). "
            "Útil para encontrar definiciones, usos, imports, etc. "
            "Ejemplo: search_code(pattern='def process_', file_pattern='*.py'). "
            "Para texto literal simple, usa grep (más rápido). "
            "Para localizar archivos por nombre, usa find_files."
        )
        self.sensitive = False
        self.args_model = SearchCodeArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Ejecuta búsqueda regex en el workspace.

        Args:
            pattern: Regex a buscar
            path: Directorio o archivo donde buscar
            file_pattern: Filtro de nombres de archivo (glob)
            max_results: Límite de resultados
            context_lines: Líneas de contexto
            case_sensitive: Sensibilidad a mayúsculas

        Returns:
            ToolResult con coincidencias y contexto, o error
        """
        try:
            args = self.validate_args(kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            search_root = validate_path(args.path, self.workspace_root)
        except (PathTraversalError, Exception) as e:
            return ToolResult(success=False, output="", error=str(e))

        # Compilar regex
        try:
            flags = 0 if args.case_sensitive else re.IGNORECASE
            regex = re.compile(args.pattern, flags)
        except re.error as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Patrón regex inválido: {e}",
            )

        matches: list[dict] = []

        for file_path in _iter_files(search_root, args.file_pattern):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()

                for i, line in enumerate(lines):
                    if regex.search(line):
                        ctx_start = max(0, i - args.context_lines)
                        ctx_end = min(len(lines), i + args.context_lines + 1)

                        context_text = "\n".join(
                            f"{'>' if j == i else ' '} {j + 1:4d}: {lines[j]}"
                            for j in range(ctx_start, ctx_end)
                        )

                        rel_path = str(file_path.relative_to(self.workspace_root))
                        rel_path = rel_path.replace("\\", "/")
                        matches.append({
                            "file": rel_path,
                            "line": i + 1,
                            "context": context_text,
                        })

                        if len(matches) >= args.max_results:
                            break

            except (OSError, PermissionError):
                continue

            if len(matches) >= args.max_results:
                break

        if not matches:
            suffix = f" en {args.file_pattern}" if args.file_pattern else ""
            return ToolResult(
                success=True,
                output=f"Sin resultados para '{args.pattern}'{suffix}",
            )

        parts = [f"Encontrados {len(matches)} resultado(s) para '{args.pattern}':\n"]
        for m in matches:
            parts.append(f"📄 {m['file']}:{m['line']}")
            parts.append(m["context"])
            parts.append("")

        result = "\n".join(parts)
        if len(matches) >= args.max_results:
            result += (
                f"\n[Máximo de {args.max_results} resultados alcanzado. "
                "Refina el patrón o añade file_pattern para reducir resultados.]"
            )

        return ToolResult(success=True, output=result)


class GrepTool(BaseTool):
    """Busca texto literal en archivos del workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.name = "grep"
        self.description = (
            "Busca texto literal en archivos. Más rápido que search_code para "
            "búsquedas simples de strings exactos. "
            "Útil para encontrar nombres de variables, imports específicos, strings, etc. "
            "Ejemplo: grep(text='from architect import', file_pattern='*.py'). "
            "Para patrones complejos usa search_code. "
            "Para localizar archivos por nombre usa find_files."
        )
        self.sensitive = False
        self.args_model = GrepArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Busca texto literal en el workspace.

        Intenta usar rg (ripgrep) o grep del sistema primero por rendimiento.
        Usa implementación Python como fallback.

        Args:
            text: Texto literal a buscar
            path: Directorio o archivo donde buscar
            file_pattern: Filtro de nombres de archivo (glob)
            max_results: Límite de resultados
            case_sensitive: Sensibilidad a mayúsculas

        Returns:
            ToolResult con coincidencias o error
        """
        try:
            args = self.validate_args(kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            search_root = validate_path(args.path, self.workspace_root)
        except (PathTraversalError, Exception) as e:
            return ToolResult(success=False, output="", error=str(e))

        # Intentar con sistema primero (más rápido)
        system_result = self._system_grep(args, search_root)
        if system_result is not None:
            return system_result

        # Fallback a Python
        return self._python_grep(args, search_root)

    def _system_grep(self, args: GrepArgs, search_root: Path) -> ToolResult | None:
        """Usa rg o grep del sistema si está disponible.

        Returns:
            ToolResult si el sistema tiene grep/rg, None para usar fallback Python
        """
        # Preferir ripgrep (mucho más rápido)
        grep_cmd = shutil.which("rg") or shutil.which("grep")
        if not grep_cmd:
            return None

        is_rg = os.path.basename(grep_cmd) == "rg"

        try:
            if is_rg:
                cmd = [
                    grep_cmd,
                    "--fixed-strings",   # Texto literal (no regex)
                    "-n",                # Números de línea
                    "--max-count", "1",  # Max matches por archivo
                    "-m", str(args.max_results),
                ]
                if not args.case_sensitive:
                    cmd.append("--ignore-case")
                if args.file_pattern:
                    cmd += ["--glob", args.file_pattern]
                # Excluir dirs estándar
                for d in sorted(SEARCH_IGNORE_DIRS):
                    cmd += ["--glob", f"!{d}"]
                cmd += [args.text, str(search_root)]
            else:
                # GNU grep / BSD grep
                cmd = [
                    grep_cmd,
                    "-r",               # Recursivo
                    "-F",               # Fixed strings (no regex)
                    "-n",               # Números de línea
                    "--max-count", str(args.max_results),
                ]
                if not args.case_sensitive:
                    cmd.append("-i")
                if args.file_pattern:
                    cmd += ["--include", args.file_pattern]
                for d in sorted(SEARCH_IGNORE_DIRS):
                    cmd += ["--exclude-dir", d]
                cmd += [args.text, str(search_root)]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )

            # grep retorna 1 cuando no hay coincidencias (no es un error)
            output = proc.stdout.strip()
            if not output:
                suffix = f" en {args.file_pattern}" if args.file_pattern else ""
                return ToolResult(
                    success=True,
                    output=f"Sin resultados para '{args.text}'{suffix}",
                )

            # Reformatear output con paths relativos al workspace
            result_lines: list[str] = []
            for line in output.splitlines()[:args.max_results]:
                # Reemplazar path absoluto por relativo
                search_root_str = str(search_root)
                if line.startswith(search_root_str):
                    rel = line[len(search_root_str):].lstrip("/\\")
                    result_lines.append(f"📄 {rel}")
                else:
                    result_lines.append(line)

            result = "\n".join(result_lines)
            if len(result_lines) >= args.max_results:
                result += f"\n\n[Máximo de {args.max_results} resultados alcanzado.]"

            return ToolResult(success=True, output=result)

        except subprocess.TimeoutExpired:
            return None  # Timeout → fallback a Python
        except (OSError, FileNotFoundError):
            return None  # grep no disponible → fallback a Python
        except Exception:
            return None  # Cualquier otro error → fallback a Python

    def _python_grep(self, args: GrepArgs, search_root: Path) -> ToolResult:
        """Implementación Python pura de búsqueda de texto literal."""
        search_text = args.text if args.case_sensitive else args.text.lower()
        matches: list[str] = []

        for file_path in _iter_files(search_root, args.file_pattern):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines()):
                    compare_line = line if args.case_sensitive else line.lower()
                    if search_text in compare_line:
                        rel_path = str(file_path.relative_to(self.workspace_root))
                        rel_path = rel_path.replace("\\", "/")
                        matches.append(f"📄 {rel_path}:{i + 1}: {line.rstrip()}")
                        if len(matches) >= args.max_results:
                            break

            except (OSError, PermissionError):
                continue

            if len(matches) >= args.max_results:
                break

        if not matches:
            suffix = f" en {args.file_pattern}" if args.file_pattern else ""
            return ToolResult(
                success=True,
                output=f"Sin resultados para '{args.text}'{suffix}",
            )

        result = "\n".join(matches)
        if len(matches) >= args.max_results:
            result += f"\n\n[Máximo de {args.max_results} resultados alcanzado.]"

        return ToolResult(success=True, output=result)


class FindFilesTool(BaseTool):
    """Encuentra archivos por patrón glob de nombre."""

    def __init__(self, workspace_root: Path) -> None:
        self.name = "find_files"
        self.description = (
            "Encuentra archivos por nombre usando patrones glob. "
            "Útil para localizar archivos de configuración, tests, módulos, etc. "
            "Ejemplo: find_files(pattern='*.test.py'), find_files(pattern='Dockerfile*'), "
            "find_files(pattern='config.yaml'). "
            "Para buscar contenido dentro de archivos usa grep o search_code."
        )
        self.sensitive = False
        self.args_model = FindFilesArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Busca archivos por nombre en el workspace.

        Args:
            pattern: Patrón glob para nombres de archivo
            path: Directorio donde buscar

        Returns:
            ToolResult con la lista de archivos encontrados
        """
        try:
            args = self.validate_args(kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            search_root = validate_path(args.path, self.workspace_root)
        except (PathTraversalError, Exception) as e:
            return ToolResult(success=False, output="", error=str(e))

        found: list[str] = []

        for file_path in _iter_files(search_root, file_pattern=args.pattern):
            rel_path = str(file_path.relative_to(self.workspace_root))
            rel_path = rel_path.replace("\\", "/")
            found.append(rel_path)

        if not found:
            return ToolResult(
                success=True,
                output=f"No se encontraron archivos que coincidan con '{args.pattern}'",
            )

        found.sort()
        output = (
            f"Archivos que coinciden con '{args.pattern}' "
            f"({len(found)} encontrado(s)):\n\n"
            + "\n".join(f"  {f}" for f in found)
        )

        return ToolResult(success=True, output=output)
