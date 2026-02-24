"""
Tests para Checkpoints & Rollback v4-C4.

Cubre:
- CHECKPOINT_PREFIX constant
- Checkpoint (frozen dataclass, short_hash)
- CheckpointManager (create, list_checkpoints, rollback, get_latest, has_changes_since)

Todas las llamadas a subprocess.run son mockeadas.
"""

import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from architect.features.checkpoints import (
    CHECKPOINT_PREFIX,
    Checkpoint,
    CheckpointManager,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal."""
    return tmp_path


@pytest.fixture
def manager(workspace: Path) -> CheckpointManager:
    """Crea un CheckpointManager con workspace temporal."""
    return CheckpointManager(str(workspace))


@pytest.fixture
def sample_checkpoint() -> Checkpoint:
    """Crea un Checkpoint de ejemplo."""
    return Checkpoint(
        step=3,
        commit_hash="abc1234567890def",
        message="edited files",
        timestamp=1708700000.0,
        files_changed=["src/main.py", "tests/test_main.py"],
    )


def _mock_run_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    """Helper para crear un resultado de subprocess.run mockeado."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ── Tests: CHECKPOINT_PREFIX constant ─────────────────────────────────────


class TestCheckpointPrefix:
    """Tests para la constante CHECKPOINT_PREFIX."""

    def test_prefix_value(self) -> None:
        """CHECKPOINT_PREFIX tiene el valor esperado."""
        assert CHECKPOINT_PREFIX == "architect:checkpoint"

    def test_prefix_is_string(self) -> None:
        """CHECKPOINT_PREFIX es un string."""
        assert isinstance(CHECKPOINT_PREFIX, str)


# ── Tests: Checkpoint dataclass ───────────────────────────────────────────


class TestCheckpointDataclass:
    """Tests para la dataclass Checkpoint."""

    def test_frozen_cannot_set_step(self, sample_checkpoint: Checkpoint) -> None:
        """Checkpoint es frozen: no se puede cambiar step."""
        with pytest.raises(FrozenInstanceError):
            sample_checkpoint.step = 99  # type: ignore[misc]

    def test_frozen_cannot_set_commit_hash(
        self, sample_checkpoint: Checkpoint
    ) -> None:
        """Checkpoint es frozen: no se puede cambiar commit_hash."""
        with pytest.raises(FrozenInstanceError):
            sample_checkpoint.commit_hash = "newvalue"  # type: ignore[misc]

    def test_short_hash_returns_first_7(self) -> None:
        """short_hash() retorna los primeros 7 caracteres."""
        cp = Checkpoint(
            step=1,
            commit_hash="abcdef1234567890",
            message="",
            timestamp=0.0,
            files_changed=[],
        )
        assert cp.short_hash() == "abcdef1"

    def test_short_hash_with_exactly_7_chars(self) -> None:
        """short_hash() funciona cuando el hash tiene exactamente 7 caracteres."""
        cp = Checkpoint(
            step=1,
            commit_hash="abcdef1",
            message="",
            timestamp=0.0,
            files_changed=[],
        )
        assert cp.short_hash() == "abcdef1"

    def test_short_hash_with_short_hash(self) -> None:
        """short_hash() retorna lo que hay si el hash tiene menos de 7 caracteres."""
        cp = Checkpoint(
            step=1,
            commit_hash="abc",
            message="",
            timestamp=0.0,
            files_changed=[],
        )
        assert cp.short_hash() == "abc"

    def test_fields_stored_correctly(self) -> None:
        """Todos los campos se almacenan correctamente."""
        ts = time.time()
        cp = Checkpoint(
            step=5,
            commit_hash="deadbeef12345678",
            message="some message",
            timestamp=ts,
            files_changed=["a.py", "b.py"],
        )
        assert cp.step == 5
        assert cp.commit_hash == "deadbeef12345678"
        assert cp.message == "some message"
        assert cp.timestamp == ts
        assert cp.files_changed == ["a.py", "b.py"]

    def test_empty_files_changed(self) -> None:
        """Checkpoint puede tener files_changed vacío."""
        cp = Checkpoint(
            step=0,
            commit_hash="0000000",
            message="",
            timestamp=0.0,
            files_changed=[],
        )
        assert cp.files_changed == []


# ── Tests: CheckpointManager.__init__ ────────────────────────────────────


class TestCheckpointManagerInit:
    """Tests para la inicialización de CheckpointManager."""

    def test_stores_workspace_root(self, workspace: Path) -> None:
        """__init__ almacena workspace_root como self.root."""
        mgr = CheckpointManager(str(workspace))
        assert mgr.root == str(workspace)

    def test_has_logger(self, manager: CheckpointManager) -> None:
        """__init__ crea un logger bound."""
        assert manager.log is not None


# ── Tests: CheckpointManager.create ──────────────────────────────────────


class TestCheckpointManagerCreate:
    """Tests para create() — creación de checkpoints."""

    @patch("architect.features.checkpoints.subprocess.run")
    @patch("architect.features.checkpoints.time.time", return_value=1708700000.0)
    def test_create_stages_and_commits(
        self, mock_time: MagicMock, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() ejecuta git add, git status, git commit, rev-parse, diff."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add -A
            _mock_run_result(stdout="M src/foo.py\n"),  # git status --porcelain
            _mock_run_result(stdout="committed\n"),  # git commit
            _mock_run_result(stdout="abc1234567890\n"),  # git rev-parse HEAD
            _mock_run_result(stdout="src/foo.py\n"),  # git diff --name-only
        ]

        result = manager.create(step=1, message="test")
        assert result is not None
        assert mock_run.call_count == 5

        # Verify git add -A was called first
        first_call_args = mock_run.call_args_list[0]
        assert first_call_args[0][0] == ["git", "add", "-A"]

    @patch("architect.features.checkpoints.subprocess.run")
    def test_create_returns_none_no_changes(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() retorna None cuando git status --porcelain está vacío."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add -A
            _mock_run_result(stdout=""),  # git status --porcelain (empty)
        ]

        result = manager.create(step=1)
        assert result is None

    @patch("architect.features.checkpoints.subprocess.run")
    def test_create_returns_none_whitespace_only_status(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() retorna None cuando status es solo whitespace."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add -A
            _mock_run_result(stdout="   \n  "),  # git status whitespace
        ]

        result = manager.create(step=1)
        assert result is None

    @patch("architect.features.checkpoints.subprocess.run")
    def test_create_returns_none_commit_fails(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() retorna None cuando git commit falla (returncode != 0)."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add -A
            _mock_run_result(stdout="M file.py\n"),  # git status
            _mock_run_result(returncode=1, stderr="commit failed"),  # git commit
        ]

        result = manager.create(step=2)
        assert result is None

    @patch("architect.features.checkpoints.subprocess.run")
    @patch("architect.features.checkpoints.time.time", return_value=1708700000.0)
    def test_create_returns_checkpoint_correct_fields(
        self, mock_time: MagicMock, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() retorna Checkpoint con campos correctos."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add -A
            _mock_run_result(stdout="M src/main.py\n"),  # git status
            _mock_run_result(stdout="ok\n"),  # git commit
            _mock_run_result(stdout="deadbeef1234567890abcdef\n"),  # rev-parse
            _mock_run_result(stdout="src/main.py\nsrc/util.py\n"),  # diff
        ]

        cp = manager.create(step=7, message="refactored utils")
        assert cp is not None
        assert cp.step == 7
        assert cp.commit_hash == "deadbeef1234567890abcdef"
        assert cp.message == "refactored utils"
        assert cp.timestamp == 1708700000.0
        assert cp.files_changed == ["src/main.py", "src/util.py"]

    @patch("architect.features.checkpoints.subprocess.run")
    @patch("architect.features.checkpoints.time.time", return_value=1000.0)
    def test_create_with_message_appends_to_commit(
        self, mock_time: MagicMock, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() con message incluye ' -- message' en el commit msg."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add
            _mock_run_result(stdout="M a.py\n"),  # status
            _mock_run_result(),  # commit
            _mock_run_result(stdout="aaa1111\n"),  # rev-parse
            _mock_run_result(stdout="a.py\n"),  # diff
        ]

        manager.create(step=5, message="my description")

        # Third call is git commit — check the message
        commit_call = mock_run.call_args_list[2]
        commit_args = commit_call[0][0]
        assert commit_args == [
            "git", "commit", "-m",
            "architect:checkpoint:step-5 -- my description",
        ]

    @patch("architect.features.checkpoints.subprocess.run")
    @patch("architect.features.checkpoints.time.time", return_value=1000.0)
    def test_create_without_message(
        self, mock_time: MagicMock, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() sin message no incluye ' -- ' en el commit msg."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add
            _mock_run_result(stdout="M a.py\n"),  # status
            _mock_run_result(),  # commit
            _mock_run_result(stdout="bbb2222\n"),  # rev-parse
            _mock_run_result(stdout="a.py\n"),  # diff
        ]

        manager.create(step=3)

        commit_call = mock_run.call_args_list[2]
        commit_args = commit_call[0][0]
        assert commit_args == [
            "git", "commit", "-m",
            "architect:checkpoint:step-3",
        ]

    @patch("architect.features.checkpoints.subprocess.run")
    @patch("architect.features.checkpoints.time.time", return_value=1000.0)
    def test_create_empty_diff_returns_empty_files(
        self, mock_time: MagicMock, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() con diff vacío retorna files_changed vacío."""
        mock_run.side_effect = [
            _mock_run_result(),  # git add
            _mock_run_result(stdout="M a.py\n"),  # status
            _mock_run_result(),  # commit
            _mock_run_result(stdout="ccc3333\n"),  # rev-parse
            _mock_run_result(stdout=""),  # diff (empty)
        ]

        cp = manager.create(step=1)
        assert cp is not None
        assert cp.files_changed == []

    @patch("architect.features.checkpoints.subprocess.run")
    @patch("architect.features.checkpoints.time.time", return_value=1000.0)
    def test_create_uses_cwd(
        self, mock_time: MagicMock, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """create() pasa cwd=self.root a todas las llamadas subprocess."""
        mock_run.side_effect = [
            _mock_run_result(),
            _mock_run_result(stdout="M a.py\n"),
            _mock_run_result(),
            _mock_run_result(stdout="ddd4444\n"),
            _mock_run_result(stdout="a.py\n"),
        ]

        manager.create(step=1)

        for c in mock_run.call_args_list:
            assert c.kwargs.get("cwd") == manager.root


# ── Tests: CheckpointManager.list_checkpoints ────────────────────────────


class TestCheckpointManagerListCheckpoints:
    """Tests para list_checkpoints() — listar checkpoints."""

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_parses_git_log(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() parsea correctamente la salida de git log."""
        log_output = (
            "abc1234|architect:checkpoint:step-3 -- edited files|1708700000\n"
            "def5678|architect:checkpoint:step-2 -- added tests|1708699000\n"
            "ghi9012|architect:checkpoint:step-1|1708698000\n"
        )
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 3

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_empty_output(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() retorna lista vacía con output vacío."""
        mock_run.return_value = _mock_run_result(stdout="")

        checkpoints = manager.list_checkpoints()
        assert checkpoints == []

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_whitespace_only_output(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() retorna lista vacía con output solo whitespace."""
        mock_run.return_value = _mock_run_result(stdout="  \n  \n")

        checkpoints = manager.list_checkpoints()
        assert checkpoints == []

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_extracts_step(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() extrae step number del mensaje."""
        log_output = "aaa1111|architect:checkpoint:step-42 -- msg|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 1
        assert checkpoints[0].step == 42

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_extracts_message_after_separator(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() extrae el mensaje después de ' -- '."""
        log_output = "bbb2222|architect:checkpoint:step-5 -- my custom msg|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].message == "my custom msg"

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_no_message_part(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() retorna mensaje vacío si no hay ' -- '."""
        log_output = "ccc3333|architect:checkpoint:step-1|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].message == ""

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_extracts_commit_hash(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() extrae el commit hash correctamente."""
        log_output = "deadbeef12345678|architect:checkpoint:step-1|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].commit_hash == "deadbeef12345678"

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_extracts_timestamp(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() extrae el timestamp correctamente."""
        log_output = "eee5555|architect:checkpoint:step-1|1708712345\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].timestamp == 1708712345.0

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_invalid_timestamp_defaults_to_zero(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() usa 0.0 si el timestamp no es parseable."""
        log_output = "fff6666|architect:checkpoint:step-1|not-a-number\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].timestamp == 0.0

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_files_changed_always_empty(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() siempre devuelve files_changed vacío."""
        log_output = "ggg7777|architect:checkpoint:step-1 -- msg|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].files_changed == []

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_skips_malformed_lines(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() ignora líneas con menos de 3 partes."""
        log_output = (
            "abc1234|architect:checkpoint:step-1|1708700000\n"
            "malformed-line\n"
            "also|malformed\n"
            "def5678|architect:checkpoint:step-2|1708701000\n"
        )
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 2

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_no_step_match_defaults_to_zero(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() usa step=0 si no encuentra el pattern step-N."""
        log_output = "hhh8888|architect:checkpoint:unknown|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert checkpoints[0].step == 0

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_uses_grep_filter(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() pasa --grep=CHECKPOINT_PREFIX a git log."""
        mock_run.return_value = _mock_run_result(stdout="")

        manager.list_checkpoints()

        call_args = mock_run.call_args[0][0]
        assert f"--grep={CHECKPOINT_PREFIX}" in call_args

    @patch("architect.features.checkpoints.subprocess.run")
    def test_list_order_preserved(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """list_checkpoints() preserva el orden de git log (más reciente primero)."""
        log_output = (
            "aaa1111|architect:checkpoint:step-10|1708703000\n"
            "bbb2222|architect:checkpoint:step-5|1708702000\n"
            "ccc3333|architect:checkpoint:step-1|1708701000\n"
        )
        mock_run.return_value = _mock_run_result(stdout=log_output)

        checkpoints = manager.list_checkpoints()
        assert [c.step for c in checkpoints] == [10, 5, 1]


# ── Tests: CheckpointManager.rollback ────────────────────────────────────


class TestCheckpointManagerRollback:
    """Tests para rollback() — restaurar a un checkpoint."""

    @patch("architect.features.checkpoints.subprocess.run")
    def test_rollback_by_step(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """rollback(step=N) busca el checkpoint y hace git reset --hard."""
        # list_checkpoints() call
        log_output = (
            "aaa1111|architect:checkpoint:step-3|1708700000\n"
            "bbb2222|architect:checkpoint:step-2|1708699000\n"
        )
        mock_run.side_effect = [
            _mock_run_result(stdout=log_output),  # git log (list_checkpoints)
            _mock_run_result(returncode=0),  # git reset --hard
        ]

        result = manager.rollback(step=2)
        assert result is True

        # Check git reset --hard was called with correct hash
        reset_call = mock_run.call_args_list[1]
        assert reset_call[0][0] == ["git", "reset", "--hard", "bbb2222"]

    @patch("architect.features.checkpoints.subprocess.run")
    def test_rollback_by_commit(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """rollback(commit=hash) usa el hash directamente."""
        mock_run.return_value = _mock_run_result(returncode=0)

        result = manager.rollback(commit="deadbeef1234")
        assert result is True

        reset_call = mock_run.call_args
        assert reset_call[0][0] == ["git", "reset", "--hard", "deadbeef1234"]

    @patch("architect.features.checkpoints.subprocess.run")
    def test_rollback_commit_has_priority_over_step(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """rollback(commit=X, step=Y) usa commit, no step."""
        mock_run.return_value = _mock_run_result(returncode=0)

        result = manager.rollback(step=5, commit="explicit_hash")
        assert result is True

        # Should NOT call list_checkpoints — only 1 subprocess call
        assert mock_run.call_count == 1
        assert mock_run.call_args[0][0] == [
            "git", "reset", "--hard", "explicit_hash",
        ]

    @patch("architect.features.checkpoints.subprocess.run")
    def test_rollback_step_not_found(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """rollback() retorna False si el step no se encuentra."""
        log_output = "aaa1111|architect:checkpoint:step-3|1708700000\n"
        mock_run.return_value = _mock_run_result(stdout=log_output)

        result = manager.rollback(step=99)
        assert result is False

    def test_rollback_no_target_specified(
        self, manager: CheckpointManager
    ) -> None:
        """rollback() retorna False si no se especifica ni step ni commit."""
        result = manager.rollback()
        assert result is False

    @patch("architect.features.checkpoints.subprocess.run")
    def test_rollback_git_error(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """rollback() retorna False cuando git reset falla."""
        mock_run.return_value = _mock_run_result(
            returncode=128, stderr="fatal: bad revision"
        )

        result = manager.rollback(commit="bad_hash")
        assert result is False

    @patch("architect.features.checkpoints.subprocess.run")
    def test_rollback_uses_cwd(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """rollback() pasa cwd=self.root al subprocess."""
        mock_run.return_value = _mock_run_result(returncode=0)

        manager.rollback(commit="abc1234")

        assert mock_run.call_args.kwargs.get("cwd") == manager.root


# ── Tests: CheckpointManager.get_latest ──────────────────────────────────


class TestCheckpointManagerGetLatest:
    """Tests para get_latest() — obtener el checkpoint más reciente."""

    @patch("architect.features.checkpoints.subprocess.run")
    def test_get_latest_returns_first(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """get_latest() retorna el primer checkpoint de la lista."""
        log_output = (
            "newest1|architect:checkpoint:step-5 -- latest|1708703000\n"
            "oldest2|architect:checkpoint:step-1|1708700000\n"
        )
        mock_run.return_value = _mock_run_result(stdout=log_output)

        latest = manager.get_latest()
        assert latest is not None
        assert latest.step == 5
        assert latest.commit_hash == "newest1"
        assert latest.message == "latest"

    @patch("architect.features.checkpoints.subprocess.run")
    def test_get_latest_returns_none_when_empty(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """get_latest() retorna None cuando no hay checkpoints."""
        mock_run.return_value = _mock_run_result(stdout="")

        latest = manager.get_latest()
        assert latest is None


# ── Tests: CheckpointManager.has_changes_since ───────────────────────────


class TestCheckpointManagerHasChangesSince:
    """Tests para has_changes_since() — detectar cambios desde un commit."""

    @patch("architect.features.checkpoints.subprocess.run")
    def test_has_changes_true(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """has_changes_since() retorna True cuando hay diff."""
        mock_run.return_value = _mock_run_result(stdout="src/main.py\ntests/foo.py\n")

        assert manager.has_changes_since("abc1234") is True

    @patch("architect.features.checkpoints.subprocess.run")
    def test_has_changes_false(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """has_changes_since() retorna False cuando no hay diff."""
        mock_run.return_value = _mock_run_result(stdout="")

        assert manager.has_changes_since("abc1234") is False

    @patch("architect.features.checkpoints.subprocess.run")
    def test_has_changes_whitespace_only(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """has_changes_since() retorna False cuando diff es solo whitespace."""
        mock_run.return_value = _mock_run_result(stdout="  \n  ")

        assert manager.has_changes_since("abc1234") is False

    @patch("architect.features.checkpoints.subprocess.run")
    def test_has_changes_passes_commit_hash(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """has_changes_since() pasa el commit hash a git diff."""
        mock_run.return_value = _mock_run_result(stdout="")

        manager.has_changes_since("deadbeef")

        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "diff", "--name-only", "deadbeef"]

    @patch("architect.features.checkpoints.subprocess.run")
    def test_has_changes_uses_cwd(
        self, mock_run: MagicMock, manager: CheckpointManager
    ) -> None:
        """has_changes_since() pasa cwd=self.root al subprocess."""
        mock_run.return_value = _mock_run_result(stdout="")

        manager.has_changes_since("abc1234")

        assert mock_run.call_args.kwargs.get("cwd") == manager.root
