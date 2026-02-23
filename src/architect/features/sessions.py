"""
Session Resume — Persistencia y restauración de sesiones.

Permite guardar el estado de una ejecución a disco (JSON) y restaurarlo
para reanudar tareas interrumpidas o parciales.

Cada sesión se guarda en `.architect/sessions/<session_id>.json`.
El AgentLoop guarda estado después de cada step y al terminar.
"""

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

SESSIONS_DIR = ".architect/sessions"


@dataclass
class SessionState:
    """Estado serializable de una sesión del agente.

    Contiene toda la información necesaria para reanudar una ejecución
    interrumpida: mensajes, estado, coste acumulado, archivos tocados, etc.
    """

    session_id: str
    task: str
    agent: str
    model: str
    status: str  # "running" | "partial" | "success" | "failed"
    steps_completed: int
    messages: list[dict[str, Any]]
    files_modified: list[str]
    total_cost: float
    started_at: float
    updated_at: float
    stop_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte a dict serializable a JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        """Crea una instancia desde un dict deserializado."""
        # Filtrar solo campos válidos del dataclass
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def generate_session_id() -> str:
    """Genera un ID de sesión único basado en timestamp + uuid corto."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{ts}-{short_uuid}"


class SessionManager:
    """Persiste y restaura sesiones del agente.

    Guarda el estado en archivos JSON individuales dentro del directorio
    de sesiones del workspace. Soporta guardar, cargar, listar y limpiar.
    """

    def __init__(self, workspace_root: str):
        """Inicializa el session manager.

        Args:
            workspace_root: Directorio raíz del workspace.
        """
        self.root = Path(workspace_root)
        self.sessions_dir = self.root / SESSIONS_DIR

    def save(self, state: SessionState) -> None:
        """Guarda estado de sesión a disco.

        Args:
            state: SessionState con el estado actual.
        """
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{state.session_id}.json"
        state.updated_at = time.time()

        data = state.to_dict()

        # Comprimir mensajes si son demasiados para evitar archivos enormes
        if len(data["messages"]) > 50:
            data["messages_truncated"] = True
            data["messages"] = data["messages"][-30:]

        path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug(
            "session.saved",
            session_id=state.session_id,
            steps=state.steps_completed,
            status=state.status,
        )

    def load(self, session_id: str) -> SessionState | None:
        """Carga una sesión guardada.

        Args:
            session_id: ID de la sesión a cargar.

        Returns:
            SessionState si existe, None si no se encuentra.
        """
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            logger.warning("session.not_found", session_id=session_id)
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = SessionState.from_dict(data)
            logger.info(
                "session.loaded",
                session_id=session_id,
                steps=state.steps_completed,
                status=state.status,
            )
            return state
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("session.load_error", session_id=session_id, error=str(e))
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Lista todas las sesiones guardadas.

        Returns:
            Lista de dicts con metadatos de cada sesión, ordenada por
            fecha de actualización (más reciente primero).
        """
        if not self.sessions_dir.exists():
            return []

        sessions: list[dict[str, Any]] = []
        for path in sorted(
            self.sessions_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "id": data["session_id"],
                    "task": data["task"][:80],
                    "status": data["status"],
                    "steps": data["steps_completed"],
                    "cost": data.get("total_cost", 0),
                    "agent": data.get("agent", "unknown"),
                    "model": data.get("model", "unknown"),
                    "updated": data.get("updated_at", 0),
                    "stop_reason": data.get("stop_reason"),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return sessions

    def cleanup(self, older_than_days: int = 7) -> int:
        """Limpia sesiones antiguas.

        Args:
            older_than_days: Eliminar sesiones más antiguas que estos días.

        Returns:
            Número de sesiones eliminadas.
        """
        if not self.sessions_dir.exists():
            return 0

        cutoff = time.time() - (older_than_days * 86400)
        removed = 0
        for path in self.sessions_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue

        if removed > 0:
            logger.info("session.cleanup", removed=removed, older_than_days=older_than_days)

        return removed

    def delete(self, session_id: str) -> bool:
        """Elimina una sesión específica.

        Args:
            session_id: ID de la sesión a eliminar.

        Returns:
            True si se eliminó, False si no existía.
        """
        path = self.sessions_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            logger.info("session.deleted", session_id=session_id)
            return True
        return False
