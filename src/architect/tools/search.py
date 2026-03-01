"""
Code search tools.

Provides capabilities for finding code in the workspace without
needing to read file by file. Includes:

- search_code: regex search with context
- grep: literal text search (uses system rg/grep if available)
- find_files: file search by glob pattern

All respect the same exclusion directories as the indexer
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


# Directories ignored in searches (same as the indexer)
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
    """Iterate over workspace files respecting exclusions.

    Args:
        search_root: Root directory for search
        file_pattern: Optional glob pattern to filter files by name

    Yields:
        Path of each file that passes the filters
    """
    for dirpath, dirnames, filenames in os.walk(search_root):
        # Exclude ignored and hidden directories (in-place)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SEARCH_IGNORE_DIRS and not d.startswith(".")
        )

        for filename in sorted(filenames):
            if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                continue
            yield Path(dirpath) / filename


class SearchCodeTool(BaseTool):
    """Searches for a regex pattern in workspace files."""

    def __init__(self, workspace_root: Path) -> None:
        self.name = "search_code"
        self.description = (
            "Search for a regex pattern in project files. "
            "Returns matches with context (neighboring lines). "
            "Useful for finding definitions, usages, imports, etc. "
            "Example: search_code(pattern='def process_', file_pattern='*.py'). "
            "For simple literal text, use grep (faster). "
            "To locate files by name, use find_files."
        )
        self.sensitive = False
        self.args_model = SearchCodeArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute regex search in the workspace.

        Args:
            pattern: Regex to search for
            path: Directory or file to search in
            file_pattern: File name filter (glob)
            max_results: Result limit
            context_lines: Context lines
            case_sensitive: Case sensitivity

        Returns:
            ToolResult with matches and context, or error
        """
        try:
            args = self.validate_args(kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            search_root = validate_path(args.path, self.workspace_root)
        except (PathTraversalError, Exception) as e:
            return ToolResult(success=False, output="", error=str(e))

        # Compile regex
        try:
            flags = 0 if args.case_sensitive else re.IGNORECASE
            regex = re.compile(args.pattern, flags)
        except re.error as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid regex pattern: {e}",
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
            suffix = f" in {args.file_pattern}" if args.file_pattern else ""
            return ToolResult(
                success=True,
                output=f"No results for '{args.pattern}'{suffix}",
            )

        parts = [f"Found {len(matches)} result(s) for '{args.pattern}':\n"]
        for m in matches:
            parts.append(f"📄 {m['file']}:{m['line']}")
            parts.append(m["context"])
            parts.append("")

        result = "\n".join(parts)
        if len(matches) >= args.max_results:
            result += (
                f"\n[Maximum of {args.max_results} results reached. "
                "Refine the pattern or add file_pattern to narrow results.]"
            )

        return ToolResult(success=True, output=result)


class GrepTool(BaseTool):
    """Searches for literal text in workspace files."""

    def __init__(self, workspace_root: Path) -> None:
        self.name = "grep"
        self.description = (
            "Search for literal text in files. Faster than search_code for "
            "simple exact string searches. "
            "Useful for finding variable names, specific imports, strings, etc. "
            "Example: grep(text='from architect import', file_pattern='*.py'). "
            "For complex patterns use search_code. "
            "To locate files by name use find_files."
        )
        self.sensitive = False
        self.args_model = GrepArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Search for literal text in the workspace.

        Tries to use system rg (ripgrep) or grep first for performance.
        Falls back to Python implementation.

        Args:
            text: Literal text to search for
            path: Directory or file to search in
            file_pattern: File name filter (glob)
            max_results: Result limit
            case_sensitive: Case sensitivity

        Returns:
            ToolResult with matches or error
        """
        try:
            args = self.validate_args(kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            search_root = validate_path(args.path, self.workspace_root)
        except (PathTraversalError, Exception) as e:
            return ToolResult(success=False, output="", error=str(e))

        # Try system first (faster)
        system_result = self._system_grep(args, search_root)
        if system_result is not None:
            return system_result

        # Fallback to Python
        return self._python_grep(args, search_root)

    def _system_grep(self, args: GrepArgs, search_root: Path) -> ToolResult | None:
        """Use system rg or grep if available.

        Returns:
            ToolResult if system has grep/rg, None to use Python fallback
        """
        # Prefer ripgrep (much faster)
        grep_cmd = shutil.which("rg") or shutil.which("grep")
        if not grep_cmd:
            return None

        is_rg = os.path.basename(grep_cmd) == "rg"

        try:
            if is_rg:
                cmd = [
                    grep_cmd,
                    "--fixed-strings",   # Literal text (not regex)
                    "-n",                # Line numbers
                    "--max-count", "1",  # Max matches per file
                    "-m", str(args.max_results),
                ]
                if not args.case_sensitive:
                    cmd.append("--ignore-case")
                if args.file_pattern:
                    cmd += ["--glob", args.file_pattern]
                # Exclude standard dirs
                for d in sorted(SEARCH_IGNORE_DIRS):
                    cmd += ["--glob", f"!{d}"]
                cmd += [args.text, str(search_root)]
            else:
                # GNU grep / BSD grep
                cmd = [
                    grep_cmd,
                    "-r",               # Recursive
                    "-F",               # Fixed strings (not regex)
                    "-n",               # Line numbers
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

            # grep returns 1 when there are no matches (not an error)
            output = proc.stdout.strip()
            if not output:
                suffix = f" in {args.file_pattern}" if args.file_pattern else ""
                return ToolResult(
                    success=True,
                    output=f"No results for '{args.text}'{suffix}",
                )

            # Reformat output with paths relative to workspace
            result_lines: list[str] = []
            for line in output.splitlines()[:args.max_results]:
                # Replace absolute path with relative
                search_root_str = str(search_root)
                if line.startswith(search_root_str):
                    rel = line[len(search_root_str):].lstrip("/\\")
                    result_lines.append(f"📄 {rel}")
                else:
                    result_lines.append(line)

            result = "\n".join(result_lines)
            if len(result_lines) >= args.max_results:
                result += f"\n\n[Maximum of {args.max_results} results reached.]"

            return ToolResult(success=True, output=result)

        except subprocess.TimeoutExpired:
            return None  # Timeout -> fallback to Python
        except (OSError, FileNotFoundError):
            return None  # grep not available -> fallback to Python
        except Exception:
            return None  # Any other error -> fallback to Python

    def _python_grep(self, args: GrepArgs, search_root: Path) -> ToolResult:
        """Pure Python implementation of literal text search."""
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
            suffix = f" in {args.file_pattern}" if args.file_pattern else ""
            return ToolResult(
                success=True,
                output=f"No results for '{args.text}'{suffix}",
            )

        result = "\n".join(matches)
        if len(matches) >= args.max_results:
            result += f"\n\n[Maximum of {args.max_results} results reached.]"

        return ToolResult(success=True, output=result)


class FindFilesTool(BaseTool):
    """Finds files by glob name pattern."""

    def __init__(self, workspace_root: Path) -> None:
        self.name = "find_files"
        self.description = (
            "Find files by name using glob patterns. "
            "Useful for locating config files, tests, modules, etc. "
            "Example: find_files(pattern='*.test.py'), find_files(pattern='Dockerfile*'), "
            "find_files(pattern='config.yaml'). "
            "To search for content inside files use grep or search_code."
        )
        self.sensitive = False
        self.args_model = FindFilesArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Search for files by name in the workspace.

        Args:
            pattern: Glob pattern for file names
            path: Directory to search in

        Returns:
            ToolResult with the list of found files
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
                output=f"No files found matching '{args.pattern}'",
            )

        found.sort()
        output = (
            f"Files matching '{args.pattern}' "
            f"({len(found)} found):\n\n"
            + "\n".join(f"  {f}" for f in found)
        )

        return ToolResult(success=True, output=output)
