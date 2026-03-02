"""
Local LLM response cache (F14).

Deterministic on-disk cache for development -- avoids repeated LLM calls
when messages are identical. NOT for production use.

The cache key is a SHA-256 hash of the canonical JSON content of
(messages, tools). Entries expire after ttl_hours.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from .adapter import LLMResponse

logger = structlog.get_logger()


class LocalLLMCache:
    """Local on-disk cache for LLM responses.

    Features:
    - Deterministic key: SHA-256 of (messages, tools) in canonical JSON
    - Storage in JSON Lines per file
    - Simple TTL based on file mtime
    - Silent failures: never breaks the adapter flow

    Usage:
        cache = LocalLLMCache(dir=Path("~/.architect/cache"), ttl_hours=24)
        response = cache.get(messages, tools)
        if response is None:
            response = llm.call(messages, tools)
            cache.set(messages, tools, response)
    """

    def __init__(self, cache_dir: Path, ttl_hours: int = 24) -> None:
        """Initialize the cache.

        Args:
            cache_dir: Directory to store cache entries.
            ttl_hours: Validity period for each entry in hours (1-8760).
        """
        self._dir = Path(cache_dir).expanduser().resolve()
        self._ttl_seconds = ttl_hours * 3600
        self._log = logger.bind(component="llm_cache")

        # Create directory if it doesn't exist
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._log.warning("llm_cache.dir_create_failed", path=str(self._dir), error=str(e))

    def get(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> "LLMResponse | None":
        """Look up a cached response.

        Args:
            messages: List of context messages.
            tools: List of tool schemas (can be None).

        Returns:
            LLMResponse if cache hit, None if not found or expired.
        """
        try:
            cache_file = self._cache_path(messages, tools)
            if not cache_file.exists():
                return None

            # Check TTL
            age = time.time() - cache_file.stat().st_mtime
            if age > self._ttl_seconds:
                self._log.debug("llm_cache.expired", file=cache_file.name, age_hours=age / 3600)
                return None

            # Deserialize response
            from .adapter import LLMResponse
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            response = LLMResponse(**data)
            self._log.info("llm_cache.hit", file=cache_file.name)
            return response

        except Exception as e:
            self._log.warning("llm_cache.get_failed", error=str(e))
            return None

    def set(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response: "LLMResponse",
    ) -> None:
        """Save a response to the cache.

        Args:
            messages: List of context messages.
            tools: List of tool schemas (can be None).
            response: LLMResponse to cache.
        """
        try:
            cache_file = self._cache_path(messages, tools)
            cache_file.write_text(response.model_dump_json(), encoding="utf-8")
            self._log.debug("llm_cache.set", file=cache_file.name)
        except Exception as e:
            self._log.warning("llm_cache.set_failed", error=str(e))

    def clear(self) -> int:
        """Delete all cache entries.

        Returns:
            Number of files deleted.
        """
        count = 0
        try:
            for f in self._dir.glob("*.json"):
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
            self._log.info("llm_cache.cleared", count=count)
        except Exception as e:
            self._log.warning("llm_cache.clear_failed", error=str(e))
        return count

    def stats(self) -> dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dict with number of entries, total size, and expired entries.
        """
        try:
            files = list(self._dir.glob("*.json"))
            now = time.time()
            expired = sum(1 for f in files if (now - f.stat().st_mtime) > self._ttl_seconds)
            total_size = sum(f.stat().st_size for f in files)
            return {
                "entries": len(files),
                "expired": expired,
                "total_size_bytes": total_size,
                "dir": str(self._dir),
            }
        except Exception:
            return {"entries": 0, "expired": 0, "total_size_bytes": 0}

    def _cache_path(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Path:
        """Generate the cache file path for a given request."""
        key = self._make_key(messages, tools)
        return self._dir / f"{key}.json"

    def _make_key(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> str:
        """Generate a deterministic SHA-256 key for (messages, tools).

        Uses canonical JSON (sort_keys=True) to guarantee determinism
        regardless of key ordering.
        """
        payload = {"messages": messages, "tools": tools}
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
