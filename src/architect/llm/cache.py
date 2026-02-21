"""
Cache local de respuestas LLM (F14).

Caché determinista en disco para desarrollo — evita llamadas repetidas al LLM
cuando los mensajes son idénticos. NO para uso en producción.

La clave de caché es un hash SHA-256 del contenido JSON canónico de
(messages, tools). Las entradas expiran después de ttl_hours.
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
    """Cache local de respuestas LLM en disco.

    Características:
    - Clave determinista: SHA-256 de (messages, tools) en JSON canónico
    - Almacenamiento en JSON Lines por archivo
    - TTL simple basado en mtime del archivo
    - Fallos silenciosos: nunca rompe el flujo del adapter

    Uso:
        cache = LocalLLMCache(dir=Path("~/.architect/cache"), ttl_hours=24)
        response = cache.get(messages, tools)
        if response is None:
            response = llm.call(messages, tools)
            cache.set(messages, tools, response)
    """

    def __init__(self, cache_dir: Path, ttl_hours: int = 24) -> None:
        """Inicializa el cache.

        Args:
            cache_dir: Directorio donde guardar las entradas de cache
            ttl_hours: Horas de validez de cada entrada (1-8760)
        """
        self._dir = Path(cache_dir).expanduser().resolve()
        self._ttl_seconds = ttl_hours * 3600
        self._log = logger.bind(component="llm_cache")

        # Crear directorio si no existe
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._log.warning("llm_cache.dir_create_failed", path=str(self._dir), error=str(e))

    def get(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> "LLMResponse | None":
        """Busca una respuesta cacheada.

        Args:
            messages: Lista de mensajes del contexto
            tools: Lista de tool schemas (puede ser None)

        Returns:
            LLMResponse si hay cache hit, None si no existe o expiró
        """
        try:
            cache_file = self._cache_path(messages, tools)
            if not cache_file.exists():
                return None

            # Verificar TTL
            age = time.time() - cache_file.stat().st_mtime
            if age > self._ttl_seconds:
                self._log.debug("llm_cache.expired", file=cache_file.name, age_hours=age / 3600)
                return None

            # Deserializar respuesta
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
        """Guarda una respuesta en el cache.

        Args:
            messages: Lista de mensajes del contexto
            tools: Lista de tool schemas (puede ser None)
            response: LLMResponse a cachear
        """
        try:
            cache_file = self._cache_path(messages, tools)
            cache_file.write_text(response.model_dump_json(), encoding="utf-8")
            self._log.debug("llm_cache.set", file=cache_file.name)
        except Exception as e:
            self._log.warning("llm_cache.set_failed", error=str(e))

    def clear(self) -> int:
        """Elimina todas las entradas del cache.

        Returns:
            Número de archivos eliminados
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
        """Retorna estadísticas del cache.

        Returns:
            Dict con número de entradas, tamaño total, y entradas expiradas
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
        """Genera el path del archivo de cache para una petición dada."""
        key = self._make_key(messages, tools)
        return self._dir / f"{key}.json"

    def _make_key(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> str:
        """Genera una clave SHA-256 determinista para (messages, tools).

        Usa JSON canónico (sort_keys=True) para garantizar determinismo
        independientemente del orden de las claves.
        """
        payload = {"messages": messages, "tools": tools}
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
