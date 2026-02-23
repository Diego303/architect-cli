"""
Tests para el sistema de sesiones v4-B1.

Cubre:
- SessionState (dataclass, serialización/deserialización)
- SessionManager (save, load, list, cleanup, delete)
- generate_session_id (formato y unicidad)
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from architect.features.sessions import (
    SessionManager,
    SessionState,
    generate_session_id,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal."""
    return tmp_path


@pytest.fixture
def session_manager(workspace: Path) -> SessionManager:
    """Crea un SessionManager con workspace temporal."""
    return SessionManager(str(workspace))


@pytest.fixture
def sample_state() -> SessionState:
    """Crea un SessionState de ejemplo."""
    return SessionState(
        session_id="20260223-120000-abc123",
        task="Refactorizar main.py",
        agent="build",
        model="gpt-4o",
        status="running",
        steps_completed=5,
        messages=[
            {"role": "system", "content": "Eres un agente..."},
            {"role": "user", "content": "Refactorizar main.py"},
            {"role": "assistant", "content": "Voy a leer el archivo..."},
        ],
        files_modified=["src/main.py", "tests/test_main.py"],
        total_cost=0.0123,
        started_at=time.time() - 60,
        updated_at=time.time(),
    )


# ── Tests: generate_session_id ───────────────────────────────────────────


class TestGenerateSessionId:
    """Tests para la generación de IDs de sesión."""

    def test_format(self) -> None:
        """El ID tiene formato YYYYMMDD-HHMMSS-hexchars."""
        sid = generate_session_id()
        parts = sid.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 8  # YYYYMMDD
        assert len(parts[1]) == 6  # HHMMSS
        assert len(parts[2]) == 6  # hex chars

    def test_uniqueness(self) -> None:
        """Dos IDs generados son diferentes."""
        id1 = generate_session_id()
        id2 = generate_session_id()
        assert id1 != id2


# ── Tests: SessionState ──────────────────────────────────────────────────


class TestSessionState:
    """Tests para SessionState dataclass."""

    def test_to_dict(self, sample_state: SessionState) -> None:
        """to_dict retorna dict serializable con todos los campos."""
        d = sample_state.to_dict()
        assert d["session_id"] == "20260223-120000-abc123"
        assert d["task"] == "Refactorizar main.py"
        assert d["agent"] == "build"
        assert d["model"] == "gpt-4o"
        assert d["status"] == "running"
        assert d["steps_completed"] == 5
        assert len(d["messages"]) == 3
        assert len(d["files_modified"]) == 2
        assert d["total_cost"] == 0.0123
        assert d["stop_reason"] is None
        assert d["metadata"] == {}

    def test_to_dict_json_serializable(self, sample_state: SessionState) -> None:
        """to_dict produce un dict que se puede serializar a JSON."""
        d = sample_state.to_dict()
        json_str = json.dumps(d, default=str)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["session_id"] == sample_state.session_id

    def test_from_dict_roundtrip(self, sample_state: SessionState) -> None:
        """from_dict(to_dict(state)) produce un estado equivalente."""
        d = sample_state.to_dict()
        restored = SessionState.from_dict(d)
        assert restored.session_id == sample_state.session_id
        assert restored.task == sample_state.task
        assert restored.status == sample_state.status
        assert restored.steps_completed == sample_state.steps_completed
        assert restored.files_modified == sample_state.files_modified

    def test_from_dict_ignores_extra_fields(self) -> None:
        """from_dict ignora campos extra que no existen en el dataclass."""
        data = {
            "session_id": "test-id",
            "task": "test",
            "agent": "build",
            "model": "gpt-4o",
            "status": "running",
            "steps_completed": 0,
            "messages": [],
            "files_modified": [],
            "total_cost": 0,
            "started_at": time.time(),
            "updated_at": time.time(),
            "unknown_field": "should be ignored",
            "messages_truncated": True,
        }
        state = SessionState.from_dict(data)
        assert state.session_id == "test-id"

    def test_from_dict_with_stop_reason(self) -> None:
        """from_dict maneja stop_reason correctamente."""
        data = {
            "session_id": "test-id",
            "task": "test",
            "agent": "build",
            "model": "gpt-4o",
            "status": "partial",
            "steps_completed": 3,
            "messages": [],
            "files_modified": [],
            "total_cost": 0.05,
            "started_at": time.time(),
            "updated_at": time.time(),
            "stop_reason": "timeout",
        }
        state = SessionState.from_dict(data)
        assert state.stop_reason == "timeout"


# ── Tests: SessionManager ────────────────────────────────────────────────


class TestSessionManager:
    """Tests para SessionManager (save/load/list/cleanup/delete)."""

    def test_save_creates_file(
        self, session_manager: SessionManager, sample_state: SessionState, workspace: Path
    ) -> None:
        """save crea un archivo JSON en el directorio de sesiones."""
        session_manager.save(sample_state)
        path = workspace / ".architect" / "sessions" / f"{sample_state.session_id}.json"
        assert path.exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["session_id"] == sample_state.session_id
        assert data["task"] == sample_state.task

    def test_save_updates_updated_at(
        self, session_manager: SessionManager, sample_state: SessionState
    ) -> None:
        """save actualiza updated_at."""
        old_time = sample_state.updated_at
        time.sleep(0.01)
        session_manager.save(sample_state)
        assert sample_state.updated_at > old_time

    def test_save_truncates_long_messages(
        self, session_manager: SessionManager, workspace: Path
    ) -> None:
        """save trunca mensajes si hay más de 50."""
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(80)]
        state = SessionState(
            session_id="truncation-test",
            task="test",
            agent="build",
            model="gpt-4o",
            status="running",
            steps_completed=40,
            messages=messages,
            files_modified=[],
            total_cost=0,
            started_at=time.time(),
            updated_at=time.time(),
        )
        session_manager.save(state)

        path = workspace / ".architect" / "sessions" / "truncation-test.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["messages"]) == 30  # Últimos 30
        assert data["messages_truncated"] is True

    def test_load_existing(
        self, session_manager: SessionManager, sample_state: SessionState
    ) -> None:
        """load restaura una sesión guardada."""
        session_manager.save(sample_state)
        loaded = session_manager.load(sample_state.session_id)
        assert loaded is not None
        assert loaded.session_id == sample_state.session_id
        assert loaded.task == sample_state.task
        assert loaded.steps_completed == sample_state.steps_completed

    def test_load_nonexistent(self, session_manager: SessionManager) -> None:
        """load retorna None si la sesión no existe."""
        result = session_manager.load("nonexistent-id")
        assert result is None

    def test_load_corrupted_json(
        self, session_manager: SessionManager, workspace: Path
    ) -> None:
        """load retorna None si el JSON está corrupto."""
        sessions_dir = workspace / ".architect" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "bad.json").write_text("{corrupted json", encoding="utf-8")
        result = session_manager.load("bad")
        assert result is None

    def test_list_sessions_empty(self, session_manager: SessionManager) -> None:
        """list_sessions retorna lista vacía si no hay sesiones."""
        result = session_manager.list_sessions()
        assert result == []

    def test_list_sessions_multiple(
        self, session_manager: SessionManager
    ) -> None:
        """list_sessions retorna todas las sesiones ordenadas por fecha."""
        for i in range(3):
            state = SessionState(
                session_id=f"session-{i}",
                task=f"Task {i}",
                agent="build",
                model="gpt-4o",
                status="success" if i == 2 else "partial",
                steps_completed=i + 1,
                messages=[],
                files_modified=[],
                total_cost=0.01 * (i + 1),
                started_at=time.time(),
                updated_at=time.time(),
            )
            session_manager.save(state)
            time.sleep(0.01)

        sessions = session_manager.list_sessions()
        assert len(sessions) == 3
        # Más reciente primero
        assert sessions[0]["id"] == "session-2"
        assert sessions[0]["status"] == "success"
        assert sessions[1]["id"] == "session-1"

    def test_list_sessions_has_required_fields(
        self, session_manager: SessionManager, sample_state: SessionState
    ) -> None:
        """list_sessions incluye todos los campos necesarios."""
        session_manager.save(sample_state)
        sessions = session_manager.list_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert "id" in s
        assert "task" in s
        assert "status" in s
        assert "steps" in s
        assert "cost" in s
        assert "agent" in s
        assert "model" in s
        assert "updated" in s

    def test_cleanup_removes_old(
        self, session_manager: SessionManager, workspace: Path
    ) -> None:
        """cleanup elimina sesiones más antiguas que N días."""
        sessions_dir = workspace / ".architect" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Crear sesión "vieja" (simulamos con mtime)
        old_path = sessions_dir / "old-session.json"
        old_data = {
            "session_id": "old-session",
            "task": "old task",
            "agent": "build",
            "model": "gpt-4o",
            "status": "partial",
            "steps_completed": 1,
            "messages": [],
            "files_modified": [],
            "total_cost": 0,
            "started_at": time.time() - 86400 * 10,
            "updated_at": time.time() - 86400 * 10,
        }
        old_path.write_text(json.dumps(old_data))
        # Establecer mtime a 10 días atrás
        import os
        old_time = time.time() - 86400 * 10
        os.utime(old_path, (old_time, old_time))

        # Crear sesión reciente
        new_state = SessionState(
            session_id="new-session",
            task="new task",
            agent="build",
            model="gpt-4o",
            status="running",
            steps_completed=1,
            messages=[],
            files_modified=[],
            total_cost=0,
            started_at=time.time(),
            updated_at=time.time(),
        )
        session_manager.save(new_state)

        removed = session_manager.cleanup(older_than_days=7)
        assert removed == 1

        remaining = session_manager.list_sessions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "new-session"

    def test_cleanup_no_sessions(self, session_manager: SessionManager) -> None:
        """cleanup retorna 0 si no hay sesiones."""
        removed = session_manager.cleanup()
        assert removed == 0

    def test_delete_existing(
        self, session_manager: SessionManager, sample_state: SessionState
    ) -> None:
        """delete elimina una sesión específica."""
        session_manager.save(sample_state)
        assert session_manager.delete(sample_state.session_id) is True
        assert session_manager.load(sample_state.session_id) is None

    def test_delete_nonexistent(self, session_manager: SessionManager) -> None:
        """delete retorna False si la sesión no existe."""
        assert session_manager.delete("nonexistent") is False

    def test_save_overwrite(
        self, session_manager: SessionManager, sample_state: SessionState
    ) -> None:
        """save sobreescribe una sesión existente con el mismo ID."""
        session_manager.save(sample_state)
        sample_state.status = "success"
        sample_state.steps_completed = 10
        session_manager.save(sample_state)

        loaded = session_manager.load(sample_state.session_id)
        assert loaded is not None
        assert loaded.status == "success"
        assert loaded.steps_completed == 10
