"""
Repository indexer -- file tree construction.

Builds a lightweight index of the workspace so the agent can
know the project structure without having to read each file.

The index includes:
- Formatted directory tree
- File and line count per directory
- Language detected by extension
- Global statistics (total files, lines, languages)

Designed to be fast (~100ms on medium repos) and respect
typical exclusion patterns (.git, node_modules, __pycache__, etc.).
"""

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# --- Extension to language mapping ---

EXT_MAP: dict[str, str] = {
    # Python
    ".py": "python", ".pyw": "python", ".pyi": "python",
    # JavaScript / TypeScript
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    # Rust
    ".rs": "rust",
    # Go
    ".go": "go",
    # JVM
    ".java": "java", ".kt": "kotlin", ".scala": "scala",
    # Ruby
    ".rb": "ruby",
    # C / C++
    ".c": "c", ".h": "c-header",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp-header",
    # C#
    ".cs": "csharp",
    # PHP / Swift
    ".php": "php", ".swift": "swift",
    # Web
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
    # Config / Data
    ".yaml": "yaml", ".yml": "yaml",
    ".json": "json", ".jsonc": "json",
    ".toml": "toml",
    ".ini": "ini", ".cfg": "ini",
    ".env": "env",
    ".xml": "xml",
    # Docs / Text
    ".md": "markdown", ".mdx": "markdown",
    ".txt": "text", ".rst": "text",
    # Shell
    ".sh": "bash", ".bash": "bash", ".zsh": "zsh", ".fish": "fish",
    # DB
    ".sql": "sql",
    # Infra
    ".tf": "terraform", ".tfvars": "terraform",
    ".dockerfile": "dockerfile",
}

# Special names (no extension)
SPECIAL_NAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "procfile": "config",
    ".gitignore": "config",
    ".gitattributes": "config",
    ".editorconfig": "config",
    ".prettierrc": "config",
    ".eslintrc": "config",
}

# Default ignored directories
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset({
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
    ".eggs",
    "*.egg-info",
    ".idea",
    ".vscode",
    ".DS_Store",
})

# Default ignored file patterns
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "*.lock",          # package-lock.json, yarn.lock (very verbose)
    "*.log",
)

# Default maximum file size (1 MB)
MAX_FILE_SIZE_DEFAULT = 1_000_000

# File limit for detailed vs compact tree
MAX_TREE_FILES_DETAILED = 300


# --- Data structures ---

@dataclass
class FileInfo:
    """Basic information about a workspace file."""

    path: str           # Relative to workspace
    size_bytes: int
    lines: int
    language: str       # Detected by extension
    last_modified: float


@dataclass
class RepoIndex:
    """Complete workspace index."""

    files: dict[str, FileInfo]   # relative path -> FileInfo
    tree_summary: str            # Formatted tree (ready to insert in prompt)
    total_files: int
    total_lines: int
    languages: dict[str, int]    # language -> number of files, ordered by frequency
    build_time_ms: float         # Build time in ms


# --- Indexer ---

class RepoIndexer:
    """Builds a lightweight index of the workspace.

    Traverses the workspace ignoring common directories and files
    (node_modules, .git, __pycache__, etc.) and builds an index
    with basic information about each file.

    The index can be used to:
    - Show the project structure in the system prompt
    - Answer questions about which files exist
    - Guide the agent to use search_code / grep instead of
      listing directories one by one
    """

    def __init__(
        self,
        workspace_root: Path,
        max_file_size: int = MAX_FILE_SIZE_DEFAULT,
        exclude_dirs: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        """Initialize the indexer.

        Args:
            workspace_root: Root directory of the workspace
            max_file_size: Maximum file size to index (bytes)
            exclude_dirs: Additional directories to exclude
            exclude_patterns: Additional file patterns to exclude
        """
        self.root = workspace_root.resolve()
        self.max_file_size = max_file_size
        self.ignore_dirs = DEFAULT_IGNORE_DIRS | frozenset(exclude_dirs or [])
        self.ignore_patterns = DEFAULT_IGNORE_PATTERNS + tuple(exclude_patterns or [])

    def build_index(self) -> RepoIndex:
        """Build the complete workspace index.

        Returns:
            RepoIndex with all indexed files and formatted tree.
            Typically takes <200ms on repos with 500 files.
        """
        start_ms = time.monotonic() * 1000

        files: dict[str, FileInfo] = {}
        for file_path in self._walk():
            rel_path = str(file_path.relative_to(self.root))
            # Normalize separators for cross-platform compatibility
            rel_path = rel_path.replace("\\", "/")
            info = self._analyze_file(file_path, rel_path)
            files[rel_path] = info

        languages = self._count_languages(files)
        tree_summary = self._format_tree(files)

        end_ms = time.monotonic() * 1000

        return RepoIndex(
            files=files,
            tree_summary=tree_summary,
            total_files=len(files),
            total_lines=sum(f.lines for f in files.values()),
            languages=languages,
            build_time_ms=round(end_ms - start_ms, 1),
        )

    def _walk(self) -> Iterator[Path]:
        """Traverse the workspace respecting exclusions.

        Modifies dirnames in-place to avoid descending into ignored
        directories (much more efficient than filtering afterwards).
        """
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Exclude ignored directories (in-place to prune the tree)
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in self.ignore_dirs
                and not d.startswith(".")
                and not any(fnmatch.fnmatch(d, p) for p in self.ignore_patterns)
            )

            for filename in filenames:
                # Exclude files by pattern
                if any(fnmatch.fnmatch(filename, p) for p in self.ignore_patterns):
                    continue

                file_path = Path(dirpath) / filename

                # Exclude files that are too large or inaccessible
                try:
                    stat = file_path.stat()
                    if stat.st_size > self.max_file_size:
                        continue
                except OSError:
                    continue

                yield file_path

    def _analyze_file(self, path: Path, rel_path: str) -> FileInfo:
        """Analyze a file and return its FileInfo."""
        try:
            stat = path.stat()
            size = stat.st_size
            last_modified = stat.st_mtime
        except OSError:
            size = 0
            last_modified = 0.0

        lines = self._count_lines(path, size)
        language = self._detect_language(path)

        return FileInfo(
            path=rel_path,
            size_bytes=size,
            lines=lines,
            language=language,
            last_modified=last_modified,
        )

    def _count_lines(self, path: Path, size: int) -> int:
        """Count lines in a text file."""
        if size == 0:
            return 0
        try:
            content = path.read_bytes()
            count = content.count(b"\n")
            # If the file doesn't end with a newline, the last line has no \n
            if content and not content.endswith(b"\n"):
                count += 1
            return count
        except OSError:
            return 0

    def _detect_language(self, path: Path) -> str:
        """Detect the file language by extension or special name."""
        name_lower = path.name.lower()

        # Check special names (no extension) first
        if name_lower in SPECIAL_NAMES:
            return SPECIAL_NAMES[name_lower]

        # Then by extension
        return EXT_MAP.get(path.suffix.lower(), "unknown")

    def _count_languages(self, files: dict[str, FileInfo]) -> dict[str, int]:
        """Group and count files by language, ordered by frequency."""
        counts: dict[str, int] = {}
        for info in files.values():
            if info.language != "unknown":
                counts[info.language] = counts.get(info.language, 0) + 1
        # Sort by descending frequency
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def _format_tree(self, files: dict[str, FileInfo]) -> str:
        """Generate tree representation of the workspace.

        For repos with <= MAX_TREE_FILES_DETAILED files, shows each file.
        For larger repos, uses compact format by directory.
        """
        if not files:
            return "(empty workspace)"

        if len(files) > MAX_TREE_FILES_DETAILED:
            return self._format_tree_compact(files)
        else:
            return self._format_tree_detailed(files)

    def _format_tree_detailed(self, files: dict[str, FileInfo]) -> str:
        """Detailed tree with all files visible."""
        # Build hierarchical structure: nested dict where
        # leaves are FileInfo and internal nodes are dict
        tree: dict = {}
        for rel_path, info in files.items():
            parts = Path(rel_path).parts
            node = tree
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = info

        lines: list[str] = []
        self._render_node(tree, lines, prefix="")
        return "\n".join(lines)

    def _render_node(
        self,
        node: dict,
        lines: list[str],
        prefix: str,
    ) -> None:
        """Render a tree node recursively with Unicode connectors."""
        # Separate into directories (dict) and files (FileInfo)
        dirs = sorted((k, v) for k, v in node.items() if isinstance(v, dict))
        file_items = sorted(
            (k, v) for k, v in node.items() if isinstance(v, FileInfo)
        )
        items = dirs + file_items

        for i, (name, value) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")

            if isinstance(value, dict):
                # Directory: show descendant file count
                n_files = self._count_files_in_node(value)
                lines.append(f"{prefix}{connector}{name}/ ({n_files} files)")
                self._render_node(value, lines, child_prefix)
            else:
                # File: show lines
                info: FileInfo = value
                lang_str = f", {info.language}" if info.language != "unknown" else ""
                lines.append(
                    f"{prefix}{connector}{name} ({info.lines}L{lang_str})"
                )

    def _count_files_in_node(self, node: dict) -> int:
        """Count files in a tree node recursively."""
        count = 0
        for value in node.values():
            if isinstance(value, FileInfo):
                count += 1
            elif isinstance(value, dict):
                count += self._count_files_in_node(value)
        return count

    def _format_tree_compact(self, files: dict[str, FileInfo]) -> str:
        """Compact tree for large repos (groups by first-level directory).

        Shows each first-level directory with statistics of its files.
        Subdirectories are grouped without listing individual files.
        """
        # Separate files at root vs files in subdirectories
        root_files: list[FileInfo] = []
        dirs: dict[str, list[FileInfo]] = {}

        for rel_path, info in sorted(files.items()):
            parts = Path(rel_path).parts
            if len(parts) == 1:
                root_files.append(info)
            else:
                top_dir = parts[0]
                dirs.setdefault(top_dir, []).append(info)

        lines: list[str] = []

        # Files at root (directly)
        for i, info in enumerate(sorted(root_files, key=lambda f: f.path)):
            is_last_root = (i == len(root_files) - 1) and not dirs
            connector = "└── " if is_last_root else "├── "
            name = Path(info.path).name
            lines.append(f"{connector}{name} ({info.lines}L)")

        # Directories
        sorted_dirs = sorted(dirs.items())
        for dir_idx, (dir_name, dir_files) in enumerate(sorted_dirs):
            is_last_dir = dir_idx == len(sorted_dirs) - 1
            connector = "└── " if is_last_dir else "├── "
            child_prefix = "    " if is_last_dir else "│   "

            total_lines = sum(f.lines for f in dir_files)
            langs = sorted({f.language for f in dir_files if f.language != "unknown"})
            lang_str = f", {', '.join(langs[:3])}" if langs else ""
            lines.append(
                f"{connector}{dir_name}/ "
                f"({len(dir_files)} files, {total_lines}L{lang_str})"
            )

            # Group by second-level subdirectories
            subdirs: dict[str, list[FileInfo]] = {}
            subroot: list[FileInfo] = []

            for info in dir_files:
                parts = Path(info.path).parts
                if len(parts) == 2:
                    subroot.append(info)
                else:
                    sub = parts[1]
                    subdirs.setdefault(sub, []).append(info)

            sub_items: list[tuple[str, list[FileInfo]]] = [
                (f, [finfo]) for finfo in sorted(subroot, key=lambda f: f.path)
                for f in [Path(finfo.path).name]
            ]

            # Show subdirectories
            sorted_subdirs = sorted(subdirs.items())
            all_children = sorted_subdirs + [
                (Path(f.path).name, [f]) for f in sorted(subroot, key=lambda x: x.path)
            ]
            all_children.sort(key=lambda x: x[0])

            for child_idx, (child_name, child_files) in enumerate(all_children):
                is_last_child = child_idx == len(all_children) - 1
                child_connector = "└── " if is_last_child else "├── "

                if child_name in dict(sorted_subdirs):
                    # It's a subdirectory
                    n = len(child_files)
                    nl = sum(f.lines for f in child_files)
                    lines.append(f"{child_prefix}{child_connector}{child_name}/ ({n} files, {nl}L)")
                else:
                    # It's a direct file
                    info = child_files[0]
                    lines.append(f"{child_prefix}{child_connector}{child_name} ({info.lines}L)")

        return "\n".join(lines)
