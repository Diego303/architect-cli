"""
Cache en disco del índice del repositorio.

Guarda el índice en disco para evitar reconstruirlo en cada llamada
cuando el workspace no ha cambiado. El cache se invalida automáticamente
transcurridos TTL_SECONDS segundos desde la construcción.

Uso típico:
    cache = IndexCache()
    index = cache.get(workspace_root)
    if index is None:
        index = RepoIndexer(workspace_root).build_index()
        cache.set(workspace_root, index)
"""

import hashlib
import json
import time
from pathlib import Path

from .tree import FileInfo, RepoIndex


# Tiempo de vida del cache: 5 minutos
# Corto por defecto para detectar cambios en repos activos
TTL_SECONDS = 300

# Directorio por defecto del cache
DEFAULT_CACHE_DIR = Path.home() / ".architect" / "index_cache"


class IndexCache:
    """Cache en disco del índice del repositorio.

    Persiste el índice en un archivo JSON en el directorio de cache.
    Cada workspace tiene su propio archivo identificado por un hash de su path.
    """

    def __init__(self, cache_dir: Path | None = None, ttl_seconds: int = TTL_SECONDS) -> None:
        """Inicializa el cache.

        Args:
            cache_dir: Directorio donde guardar el cache. Por defecto ~/.architect/index_cache
            ttl_seconds: Segundos de validez del cache. Por defecto 300 (5 min).
        """
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.ttl_seconds = ttl_seconds

        # Crear directorio si no existe (fallo silencioso si no hay permisos)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def get(self, workspace_root: Path) -> RepoIndex | None:
        """Obtiene el índice del cache si existe y está vigente.

        Args:
            workspace_root: Directorio raíz del workspace

        Returns:
            RepoIndex si el cache es válido, None si no existe o expiró
        """
        cache_file = self._cache_path(workspace_root)
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))

            # Verificar que el cache no haya expirado
            cached_at = data.get("cached_at", 0)
            if time.time() - cached_at > self.ttl_seconds:
                return None

            return self._deserialize(data["index"])

        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            # Cache corrupto o formato incorrecto → ignorar
            return None

    def set(self, workspace_root: Path, index: RepoIndex) -> None:
        """Guarda el índice en el cache.

        Fallo silencioso: si no se puede escribir el cache, el sistema
        sigue funcionando (el cache no es crítico).

        Args:
            workspace_root: Directorio raíz del workspace
            index: Índice a guardar
        """
        cache_file = self._cache_path(workspace_root)
        try:
            payload = {
                "cached_at": time.time(),
                "workspace": str(workspace_root.resolve()),
                "index": self._serialize(index),
            }
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass  # Cache no crítico

    def clear(self, workspace_root: Path | None = None) -> int:
        """Limpia el cache.

        Args:
            workspace_root: Si se especifica, limpia solo ese workspace.
                            Si es None, limpia todos los caches.

        Returns:
            Número de archivos de cache eliminados.
        """
        deleted = 0
        if workspace_root is not None:
            cache_file = self._cache_path(workspace_root)
            if cache_file.exists():
                try:
                    cache_file.unlink()
                    deleted += 1
                except OSError:
                    pass
        else:
            for f in self.cache_dir.glob("*.json"):
                try:
                    f.unlink()
                    deleted += 1
                except OSError:
                    pass
        return deleted

    def _cache_path(self, workspace_root: Path) -> Path:
        """Calcula el path del archivo de cache para un workspace."""
        key = hashlib.sha256(
            str(workspace_root.resolve()).encode()
        ).hexdigest()[:16]
        return self.cache_dir / f"index_{key}.json"

    def _serialize(self, index: RepoIndex) -> dict:
        """Serializa un RepoIndex a dict JSON-serializable."""
        return {
            "files": {
                path: {
                    "path": info.path,
                    "size_bytes": info.size_bytes,
                    "lines": info.lines,
                    "language": info.language,
                    "last_modified": info.last_modified,
                }
                for path, info in index.files.items()
            },
            "tree_summary": index.tree_summary,
            "total_files": index.total_files,
            "total_lines": index.total_lines,
            "languages": index.languages,
            "build_time_ms": index.build_time_ms,
        }

    def _deserialize(self, data: dict) -> RepoIndex:
        """Deserializa un dict a RepoIndex."""
        files = {
            path: FileInfo(**info_data)
            for path, info_data in data["files"].items()
        }
        return RepoIndex(
            files=files,
            tree_summary=data["tree_summary"],
            total_files=data["total_files"],
            total_lines=data["total_lines"],
            languages=data["languages"],
            build_time_ms=data.get("build_time_ms", 0.0),
        )
