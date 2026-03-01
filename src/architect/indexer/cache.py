"""
On-disk cache for the repository index.

Saves the index to disk to avoid rebuilding it on each call
when the workspace has not changed. The cache is automatically
invalidated after TTL_SECONDS seconds since construction.

Typical usage:
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


# Cache time to live: 5 minutes
# Short by default to detect changes in active repos
TTL_SECONDS = 300

# Default cache directory
DEFAULT_CACHE_DIR = Path.home() / ".architect" / "index_cache"


class IndexCache:
    """On-disk cache for the repository index.

    Persists the index in a JSON file in the cache directory.
    Each workspace has its own file identified by a hash of its path.
    """

    def __init__(self, cache_dir: Path | None = None, ttl_seconds: int = TTL_SECONDS) -> None:
        """Initialize the cache.

        Args:
            cache_dir: Directory to store the cache. Defaults to ~/.architect/index_cache
            ttl_seconds: Cache validity in seconds. Defaults to 300 (5 min).
        """
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.ttl_seconds = ttl_seconds

        # Create directory if it doesn't exist (silent failure if no permissions)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def get(self, workspace_root: Path) -> RepoIndex | None:
        """Get the index from cache if it exists and is still valid.

        Args:
            workspace_root: Root directory of the workspace

        Returns:
            RepoIndex if the cache is valid, None if it doesn't exist or expired
        """
        cache_file = self._cache_path(workspace_root)
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))

            # Check that the cache has not expired
            cached_at = data.get("cached_at", 0)
            if time.time() - cached_at > self.ttl_seconds:
                return None

            return self._deserialize(data["index"])

        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            # Corrupt cache or incorrect format -> ignore
            return None

    def set(self, workspace_root: Path, index: RepoIndex) -> None:
        """Save the index to cache.

        Silent failure: if the cache cannot be written, the system
        continues working (cache is not critical).

        Args:
            workspace_root: Root directory of the workspace
            index: Index to save
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
            pass  # Cache is not critical

    def clear(self, workspace_root: Path | None = None) -> int:
        """Clear the cache.

        Args:
            workspace_root: If specified, clears only that workspace.
                            If None, clears all caches.

        Returns:
            Number of cache files deleted.
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
        """Calculate the cache file path for a workspace."""
        key = hashlib.sha256(
            str(workspace_root.resolve()).encode()
        ).hexdigest()[:16]
        return self.cache_dir / f"index_{key}.json"

    def _serialize(self, index: RepoIndex) -> dict:
        """Serialize a RepoIndex to a JSON-serializable dict."""
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
        """Deserialize a dict to RepoIndex."""
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
