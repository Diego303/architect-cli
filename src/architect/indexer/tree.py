"""
Indexador de repositorio — construcción del árbol de archivos.

Construye un índice ligero del workspace para que el agente pueda
conocer la estructura del proyecto sin tener que leer cada archivo.

El índice incluye:
- Árbol de directorios formateado
- Conteo de archivos y líneas por directorio
- Lenguaje detectado por extensión
- Estadísticas globales (total archivos, líneas, lenguajes)

Diseñado para ser rápido (~100ms en repos medianos) y respetar
patrones de exclusión típicos (.git, node_modules, __pycache__, etc.).
"""

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# --- Mapeo de extensiones a lenguajes ---

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

# Nombres especiales (sin extensión)
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

# Directorios ignorados por defecto
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

# Patrones de archivos ignorados por defecto
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "*.lock",          # package-lock.json, yarn.lock (muy verbosos)
    "*.log",
)

# Límite por defecto del tamaño de archivo (1 MB)
MAX_FILE_SIZE_DEFAULT = 1_000_000

# Límite de archivos para árbol detallado vs compacto
MAX_TREE_FILES_DETAILED = 300


# --- Estructuras de datos ---

@dataclass
class FileInfo:
    """Información básica sobre un archivo del workspace."""

    path: str           # Relativo al workspace
    size_bytes: int
    lines: int
    language: str       # Detectado por extensión
    last_modified: float


@dataclass
class RepoIndex:
    """Índice completo del workspace."""

    files: dict[str, FileInfo]   # path relativo → FileInfo
    tree_summary: str            # Árbol formateado (listo para insertar en prompt)
    total_files: int
    total_lines: int
    languages: dict[str, int]    # language → número de archivos, ordenado por frecuencia
    build_time_ms: float         # Tiempo de construcción en ms


# --- Indexador ---

class RepoIndexer:
    """Construye un índice ligero del workspace.

    Recorre el workspace ignorando directorios y archivos comunes
    (node_modules, .git, __pycache__, etc.) y construye un índice
    con información básica de cada archivo.

    El índice se puede usar para:
    - Mostrar la estructura del proyecto en el system prompt
    - Responder preguntas sobre qué archivos existen
    - Guiar al agente para que use search_code / grep en vez de
      listar directorios uno a uno
    """

    def __init__(
        self,
        workspace_root: Path,
        max_file_size: int = MAX_FILE_SIZE_DEFAULT,
        exclude_dirs: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        """Inicializa el indexador.

        Args:
            workspace_root: Directorio raíz del workspace
            max_file_size: Tamaño máximo de archivo a indexar (bytes)
            exclude_dirs: Directorios adicionales a excluir
            exclude_patterns: Patrones de archivos adicionales a excluir
        """
        self.root = workspace_root.resolve()
        self.max_file_size = max_file_size
        self.ignore_dirs = DEFAULT_IGNORE_DIRS | frozenset(exclude_dirs or [])
        self.ignore_patterns = DEFAULT_IGNORE_PATTERNS + tuple(exclude_patterns or [])

    def build_index(self) -> RepoIndex:
        """Construye el índice completo del workspace.

        Returns:
            RepoIndex con todos los archivos indexados y árbol formateado.
            Típicamente tarda <200ms en repos de 500 archivos.
        """
        start_ms = time.monotonic() * 1000

        files: dict[str, FileInfo] = {}
        for file_path in self._walk():
            rel_path = str(file_path.relative_to(self.root))
            # Normalizar separadores para compatibilidad cross-platform
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
        """Recorre el workspace respetando exclusiones.

        Modifica dirnames in-place para evitar descender en directorios
        ignorados (mucho más eficiente que filtrar después).
        """
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Excluir directorios ignorados (in-place para cortar el árbol)
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in self.ignore_dirs
                and not d.startswith(".")
                and not any(fnmatch.fnmatch(d, p) for p in self.ignore_patterns)
            )

            for filename in filenames:
                # Excluir archivos por patrón
                if any(fnmatch.fnmatch(filename, p) for p in self.ignore_patterns):
                    continue

                file_path = Path(dirpath) / filename

                # Excluir archivos demasiado grandes o inaccesibles
                try:
                    stat = file_path.stat()
                    if stat.st_size > self.max_file_size:
                        continue
                except OSError:
                    continue

                yield file_path

    def _analyze_file(self, path: Path, rel_path: str) -> FileInfo:
        """Analiza un archivo y retorna su FileInfo."""
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
        """Cuenta líneas de un archivo de texto."""
        if size == 0:
            return 0
        try:
            content = path.read_bytes()
            count = content.count(b"\n")
            # Si el archivo no termina en newline, la última línea no tiene \n
            if content and not content.endswith(b"\n"):
                count += 1
            return count
        except OSError:
            return 0

    def _detect_language(self, path: Path) -> str:
        """Detecta el lenguaje del archivo por extensión o nombre especial."""
        name_lower = path.name.lower()

        # Comprobar nombres especiales (sin extensión) primero
        if name_lower in SPECIAL_NAMES:
            return SPECIAL_NAMES[name_lower]

        # Luego por extensión
        return EXT_MAP.get(path.suffix.lower(), "unknown")

    def _count_languages(self, files: dict[str, FileInfo]) -> dict[str, int]:
        """Agrupa y cuenta archivos por lenguaje, ordenado por frecuencia."""
        counts: dict[str, int] = {}
        for info in files.values():
            if info.language != "unknown":
                counts[info.language] = counts.get(info.language, 0) + 1
        # Ordenar por frecuencia descendente
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def _format_tree(self, files: dict[str, FileInfo]) -> str:
        """Genera representación en árbol del workspace.

        Para repos ≤ MAX_TREE_FILES_DETAILED archivos, muestra cada archivo.
        Para repos más grandes, usa formato compacto por directorio.
        """
        if not files:
            return "(workspace vacío)"

        if len(files) > MAX_TREE_FILES_DETAILED:
            return self._format_tree_compact(files)
        else:
            return self._format_tree_detailed(files)

    def _format_tree_detailed(self, files: dict[str, FileInfo]) -> str:
        """Árbol detallado con todos los archivos visibles."""
        # Construir estructura jerárquica: dict anidado donde
        # las hojas son FileInfo y los nodos internos son dict
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
        """Renderiza un nodo del árbol recursivamente con conectores Unicode."""
        # Separar en directorios (dict) y archivos (FileInfo)
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
                # Directorio: mostrar conteo de archivos descendientes
                n_files = self._count_files_in_node(value)
                lines.append(f"{prefix}{connector}{name}/ ({n_files} archivos)")
                self._render_node(value, lines, child_prefix)
            else:
                # Archivo: mostrar líneas
                info: FileInfo = value
                lang_str = f", {info.language}" if info.language != "unknown" else ""
                lines.append(
                    f"{prefix}{connector}{name} ({info.lines}L{lang_str})"
                )

    def _count_files_in_node(self, node: dict) -> int:
        """Cuenta archivos en un nodo del árbol recursivamente."""
        count = 0
        for value in node.values():
            if isinstance(value, FileInfo):
                count += 1
            elif isinstance(value, dict):
                count += self._count_files_in_node(value)
        return count

    def _format_tree_compact(self, files: dict[str, FileInfo]) -> str:
        """Árbol compacto para repos grandes (agrupa por directorio de primer nivel).

        Muestra cada directorio de primer nivel con estadísticas de sus archivos.
        Los subdirectorios se agrupan sin listar archivos individuales.
        """
        # Separar archivos en raíz vs archivos en subdirectorios
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

        # Archivos en la raíz (directamente)
        for i, info in enumerate(sorted(root_files, key=lambda f: f.path)):
            is_last_root = (i == len(root_files) - 1) and not dirs
            connector = "└── " if is_last_root else "├── "
            name = Path(info.path).name
            lines.append(f"{connector}{name} ({info.lines}L)")

        # Directorios
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
                f"({len(dir_files)} archivos, {total_lines}L{lang_str})"
            )

            # Agrupar en subdirectorios de segundo nivel
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

            # Mostrar subdirectorios
            sorted_subdirs = sorted(subdirs.items())
            all_children = sorted_subdirs + [
                (Path(f.path).name, [f]) for f in sorted(subroot, key=lambda x: x.path)
            ]
            all_children.sort(key=lambda x: x[0])

            for child_idx, (child_name, child_files) in enumerate(all_children):
                is_last_child = child_idx == len(all_children) - 1
                child_connector = "└── " if is_last_child else "├── "

                if child_name in dict(sorted_subdirs):
                    # Es un subdirectorio
                    n = len(child_files)
                    nl = sum(f.lines for f in child_files)
                    lines.append(f"{child_prefix}{child_connector}{child_name}/ ({n} archivos, {nl}L)")
                else:
                    # Es un archivo directo
                    info = child_files[0]
                    lines.append(f"{child_prefix}{child_connector}{child_name} ({info.lines}L)")

        return "\n".join(lines)
