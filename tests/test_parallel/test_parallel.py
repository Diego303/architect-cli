"""
Tests para el sistema de ejecucion paralela v4-C2.

Cubre:
- WorkerResult (dataclass, campos)
- ParallelConfig (defaults, valores custom)
- ParallelRunner (init, worktrees, task/model assignment, run, cleanup, list)
- _run_worker_process (JSON exitoso, JSON invalido, timeout)
"""

import json
import subprocess
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from architect.features.parallel import (
    WORKTREE_PREFIX,
    ParallelConfig,
    ParallelRunner,
    WorkerResult,
    _run_worker_process,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal."""
    return tmp_path


@pytest.fixture
def basic_config() -> ParallelConfig:
    """Configuracion basica con una tarea y 3 workers."""
    return ParallelConfig(tasks=["Fix the bug in main.py"])


@pytest.fixture
def multi_config() -> ParallelConfig:
    """Configuracion con multiples tareas, modelos y opciones custom."""
    return ParallelConfig(
        tasks=["Task A", "Task B", "Task C"],
        workers=3,
        models=["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.0-flash"],
        agent="plan",
        max_steps=20,
        budget_per_worker=1.50,
        timeout_per_worker=300,
        base_branch="main",
    )


@pytest.fixture
def runner(basic_config: ParallelConfig, workspace: Path) -> ParallelRunner:
    """ParallelRunner con config basica."""
    return ParallelRunner(basic_config, str(workspace))


@pytest.fixture
def multi_runner(multi_config: ParallelConfig, workspace: Path) -> ParallelRunner:
    """ParallelRunner con config completa."""
    return ParallelRunner(multi_config, str(workspace))


# -- Test WorkerResult -------------------------------------------------------


class TestWorkerResult:
    """Tests para el dataclass WorkerResult."""

    def test_fields_basic(self):
        """WorkerResult almacena todos los campos correctamente."""
        result = WorkerResult(
            worker_id=1,
            branch="architect/parallel-1",
            model="gpt-4o",
            status="success",
            steps=10,
            cost=0.05,
            duration=12.3,
            files_modified=["src/main.py", "tests/test_main.py"],
            worktree_path="/tmp/repo/.architect-parallel-1",
        )
        assert result.worker_id == 1
        assert result.branch == "architect/parallel-1"
        assert result.model == "gpt-4o"
        assert result.status == "success"
        assert result.steps == 10
        assert result.cost == 0.05
        assert result.duration == 12.3
        assert result.files_modified == ["src/main.py", "tests/test_main.py"]
        assert result.worktree_path == "/tmp/repo/.architect-parallel-1"

    def test_failed_result(self):
        """WorkerResult puede representar un fallo."""
        result = WorkerResult(
            worker_id=2,
            branch="architect/parallel-2",
            model="default",
            status="failed",
            steps=0,
            cost=0,
            duration=0,
            files_modified=[],
            worktree_path="",
        )
        assert result.status == "failed"
        assert result.steps == 0
        assert result.files_modified == []

    def test_timeout_result(self):
        """WorkerResult puede representar un timeout."""
        result = WorkerResult(
            worker_id=3,
            branch="architect/parallel-3",
            model="default",
            status="timeout",
            steps=0,
            cost=0,
            duration=600.0,
            files_modified=[],
            worktree_path="/tmp/repo/.architect-parallel-3",
        )
        assert result.status == "timeout"
        assert result.duration == 600.0


# -- Test ParallelConfig -----------------------------------------------------


class TestParallelConfig:
    """Tests para el dataclass ParallelConfig."""

    def test_defaults(self):
        """ParallelConfig tiene valores por defecto correctos."""
        config = ParallelConfig(tasks=["Do something"])
        assert config.tasks == ["Do something"]
        assert config.workers == 3
        assert config.models is None
        assert config.agent == "build"
        assert config.max_steps == 50
        assert config.budget_per_worker is None
        assert config.timeout_per_worker is None
        assert config.base_branch is None

    def test_custom_values(self):
        """ParallelConfig acepta valores personalizados."""
        config = ParallelConfig(
            tasks=["A", "B"],
            workers=5,
            models=["gpt-4o", "claude-sonnet-4-20250514"],
            agent="plan",
            max_steps=20,
            budget_per_worker=2.0,
            timeout_per_worker=120,
            base_branch="develop",
        )
        assert config.tasks == ["A", "B"]
        assert config.workers == 5
        assert config.models == ["gpt-4o", "claude-sonnet-4-20250514"]
        assert config.agent == "plan"
        assert config.max_steps == 20
        assert config.budget_per_worker == 2.0
        assert config.timeout_per_worker == 120
        assert config.base_branch == "develop"

    def test_single_task_multiple_workers(self):
        """Config con una tarea y multiples workers es valida."""
        config = ParallelConfig(tasks=["Shared task"], workers=5)
        assert len(config.tasks) == 1
        assert config.workers == 5


# -- Test ParallelRunner init ------------------------------------------------


class TestParallelRunnerInit:
    """Tests para ParallelRunner.__init__."""

    def test_init_stores_config_and_root(self, basic_config, workspace):
        """Runner almacena config y workspace root correctamente."""
        runner = ParallelRunner(basic_config, str(workspace))
        assert runner.config is basic_config
        assert runner.root == workspace
        assert runner.worktrees == []

    def test_init_root_is_path(self, basic_config, workspace):
        """Runner convierte workspace_root a Path."""
        runner = ParallelRunner(basic_config, str(workspace))
        assert isinstance(runner.root, Path)


# -- Test _get_task_for_worker -----------------------------------------------


class TestGetTaskForWorker:
    """Tests para ParallelRunner._get_task_for_worker."""

    def test_single_task_reuses_for_all(self, runner):
        """Con una sola tarea, todos los workers reciben la misma."""
        assert runner._get_task_for_worker(0) == "Fix the bug in main.py"
        assert runner._get_task_for_worker(1) == "Fix the bug in main.py"
        assert runner._get_task_for_worker(2) == "Fix the bug in main.py"
        assert runner._get_task_for_worker(99) == "Fix the bug in main.py"

    def test_multiple_tasks_distributed(self, multi_runner):
        """Con varias tareas, cada worker recibe la suya por indice."""
        assert multi_runner._get_task_for_worker(0) == "Task A"
        assert multi_runner._get_task_for_worker(1) == "Task B"
        assert multi_runner._get_task_for_worker(2) == "Task C"

    def test_more_workers_than_tasks(self, workspace):
        """Si hay mas workers que tareas, los extra reciben la primera tarea."""
        config = ParallelConfig(tasks=["Task A", "Task B"], workers=4)
        runner = ParallelRunner(config, str(workspace))
        assert runner._get_task_for_worker(0) == "Task A"
        assert runner._get_task_for_worker(1) == "Task B"
        assert runner._get_task_for_worker(2) == "Task A"  # Falls back to first
        assert runner._get_task_for_worker(3) == "Task A"  # Falls back to first


# -- Test _get_model_for_worker ----------------------------------------------


class TestGetModelForWorker:
    """Tests para ParallelRunner._get_model_for_worker."""

    def test_with_models(self, multi_runner):
        """Con modelos configurados, cada worker recibe el suyo."""
        assert multi_runner._get_model_for_worker(0) == "gpt-4o"
        assert multi_runner._get_model_for_worker(1) == "claude-sonnet-4-20250514"
        assert multi_runner._get_model_for_worker(2) == "gemini-2.0-flash"

    def test_without_models_returns_none(self, runner):
        """Sin modelos configurados, retorna None."""
        assert runner._get_model_for_worker(0) is None
        assert runner._get_model_for_worker(1) is None
        assert runner._get_model_for_worker(2) is None

    def test_more_workers_than_models(self, workspace):
        """Si hay mas workers que modelos, los extra reciben None."""
        config = ParallelConfig(
            tasks=["task"],
            workers=4,
            models=["gpt-4o", "claude-sonnet-4-20250514"],
        )
        runner = ParallelRunner(config, str(workspace))
        assert runner._get_model_for_worker(0) == "gpt-4o"
        assert runner._get_model_for_worker(1) == "claude-sonnet-4-20250514"
        assert runner._get_model_for_worker(2) is None
        assert runner._get_model_for_worker(3) is None


# -- Test _create_worktrees --------------------------------------------------


class TestCreateWorktrees:
    """Tests para ParallelRunner._create_worktrees."""

    @patch("architect.features.parallel.subprocess.run")
    def test_creates_correct_git_commands(self, mock_run, runner, workspace):
        """_create_worktrees ejecuta los comandos git correctos."""
        # git rev-parse para obtener branch actual
        mock_run.return_value = MagicMock(
            returncode=0, stdout="main\n", stderr=""
        )

        runner._create_worktrees()

        assert len(runner.worktrees) == 3

        # Verificar que se ejecutaron los comandos correctos para cada worker
        calls = mock_run.call_args_list

        # Primer call: git rev-parse para obtener branch actual
        assert calls[0] == call(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )

        # Para cada worker (3 workers): branch -D + worktree add
        for i in range(3):
            branch_name = f"architect/parallel-{i + 1}"
            worktree_path = str(workspace / f"{WORKTREE_PREFIX}-{i + 1}")

            # Buscar el call de branch -D
            branch_delete_calls = [
                c for c in calls
                if c == call(
                    ["git", "branch", "-D", branch_name],
                    capture_output=True,
                    cwd=str(workspace),
                )
            ]
            assert len(branch_delete_calls) == 1, (
                f"Expected branch -D call for {branch_name}"
            )

            # Buscar el call de worktree add
            worktree_add_calls = [
                c for c in calls
                if c == call(
                    [
                        "git", "worktree", "add",
                        "-b", branch_name,
                        worktree_path,
                        "main",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(workspace),
                )
            ]
            assert len(worktree_add_calls) == 1, (
                f"Expected worktree add call for {branch_name}"
            )

    @patch("architect.features.parallel.subprocess.run")
    def test_uses_base_branch_if_set(self, mock_run, multi_runner, workspace):
        """_create_worktrees usa base_branch de config en vez de rev-parse."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        multi_runner._create_worktrees()

        # No debe haber call a git rev-parse
        rev_parse_calls = [
            c for c in mock_run.call_args_list
            if "rev-parse" in str(c)
        ]
        assert len(rev_parse_calls) == 0

        # Los worktree add deben usar "main" (base_branch de multi_config)
        worktree_add_calls = [
            c for c in mock_run.call_args_list
            if "worktree" in str(c) and "add" in str(c)
        ]
        for wt_call in worktree_add_calls:
            args = wt_call[0][0]  # Primer argumento posicional, la lista de cmd
            assert args[-1] == "main"

    @patch("architect.features.parallel.subprocess.run")
    def test_cleans_existing_worktrees(self, mock_run, runner, workspace):
        """Si el directorio de worktree ya existe, lo limpia primero."""
        # Crear el directorio para simular que ya existe
        worktree_dir = workspace / f"{WORKTREE_PREFIX}-1"
        worktree_dir.mkdir()

        mock_run.return_value = MagicMock(
            returncode=0, stdout="main\n", stderr=""
        )

        runner._create_worktrees()

        # Debe haber un call a worktree remove para el que ya existia
        remove_calls = [
            c for c in mock_run.call_args_list
            if "worktree" in str(c) and "remove" in str(c)
        ]
        assert len(remove_calls) >= 1
        # Verificar que el remove es del path correcto
        remove_call = remove_calls[0]
        assert str(worktree_dir) in str(remove_call)

    @patch("architect.features.parallel.subprocess.run")
    def test_raises_on_worktree_creation_failure(self, mock_run, runner, workspace):
        """Lanza RuntimeError si git worktree add falla."""
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if "worktree" in cmd and "add" in cmd:
                return MagicMock(
                    returncode=1,
                    stderr="fatal: could not create worktree",
                )
            return MagicMock(returncode=0, stdout="main\n", stderr="")

        mock_run.side_effect = side_effect

        with pytest.raises(RuntimeError, match="Error creando worktree"):
            runner._create_worktrees()


# -- Test cleanup ------------------------------------------------------------


class TestCleanup:
    """Tests para ParallelRunner.cleanup."""

    @patch("architect.features.parallel.subprocess.run")
    def test_cleanup_removes_worktrees_and_branches(self, mock_run, runner, workspace):
        """cleanup elimina worktrees, branches y hace prune."""
        # Crear directorios simulando worktrees existentes
        wt1 = workspace / f"{WORKTREE_PREFIX}-1"
        wt2 = workspace / f"{WORKTREE_PREFIX}-2"
        wt1.mkdir()
        wt2.mkdir()

        # Mock de git branch --list
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="  architect/parallel-1\n  architect/parallel-2\n",
            stderr="",
        )

        removed = runner.cleanup()

        # Debe haber eliminado al menos 2 worktrees
        assert removed >= 2

        # Verificar que se hizo prune
        prune_calls = [
            c for c in mock_run.call_args_list
            if "prune" in str(c)
        ]
        assert len(prune_calls) == 1

        # Verificar que se eliminaron branches
        branch_delete_calls = [
            c for c in mock_run.call_args_list
            if "branch" in str(c) and "-D" in str(c)
        ]
        assert len(branch_delete_calls) == 2

    @patch("architect.features.parallel.subprocess.run")
    def test_cleanup_returns_zero_when_no_worktrees(self, mock_run, runner):
        """cleanup retorna 0 si no hay worktrees que limpiar."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        removed = runner.cleanup()
        assert removed == 0


# -- Test list_worktrees -----------------------------------------------------


class TestListWorktrees:
    """Tests para ParallelRunner.list_worktrees (static method)."""

    @patch("architect.features.parallel.subprocess.run")
    def test_parses_porcelain_output(self, mock_run, workspace):
        """list_worktrees parsea correctamente el output porcelain de git."""
        porcelain_output = (
            f"worktree /main/repo\n"
            f"HEAD abc123\n"
            f"branch refs/heads/main\n"
            f"\n"
            f"worktree /main/repo/{WORKTREE_PREFIX}-1\n"
            f"HEAD def456\n"
            f"branch refs/heads/architect/parallel-1\n"
            f"\n"
            f"worktree /main/repo/{WORKTREE_PREFIX}-2\n"
            f"HEAD ghi789\n"
            f"branch refs/heads/architect/parallel-2\n"
            f"\n"
        )
        mock_run.return_value = MagicMock(
            returncode=0, stdout=porcelain_output, stderr=""
        )

        result = ParallelRunner.list_worktrees(str(workspace))

        assert len(result) == 2
        assert result[0]["path"] == f"/main/repo/{WORKTREE_PREFIX}-1"
        assert result[0]["branch"] == "architect/parallel-1"
        assert result[1]["path"] == f"/main/repo/{WORKTREE_PREFIX}-2"
        assert result[1]["branch"] == "architect/parallel-2"

    @patch("architect.features.parallel.subprocess.run")
    def test_filters_non_parallel_worktrees(self, mock_run, workspace):
        """list_worktrees solo retorna worktrees con el prefijo correcto."""
        porcelain_output = (
            "worktree /main/repo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /main/repo/.some-other-worktree\n"
            "HEAD def456\n"
            "branch refs/heads/feature/xyz\n"
            "\n"
        )
        mock_run.return_value = MagicMock(
            returncode=0, stdout=porcelain_output, stderr=""
        )

        result = ParallelRunner.list_worktrees(str(workspace))
        assert len(result) == 0

    @patch("architect.features.parallel.subprocess.run")
    def test_empty_output(self, mock_run, workspace):
        """list_worktrees retorna lista vacia si no hay worktrees."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        result = ParallelRunner.list_worktrees(str(workspace))
        assert result == []

    @patch("architect.features.parallel.subprocess.run")
    def test_calls_git_with_correct_args(self, mock_run, workspace):
        """list_worktrees invoca git worktree list --porcelain."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        ParallelRunner.list_worktrees(str(workspace))

        mock_run.assert_called_once_with(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )


# -- Test _run_worker_process ------------------------------------------------


class TestRunWorkerProcess:
    """Tests para la funcion top-level _run_worker_process."""

    @patch("architect.features.parallel.subprocess.run")
    def test_successful_json_output(self, mock_run):
        """Worker con output JSON valido retorna WorkerResult correcto."""
        json_output = json.dumps({
            "status": "success",
            "steps": 15,
            "cost": 0.042,
            "files_modified": ["src/main.py", "tests/test_main.py"],
        })
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json_output,
            stderr="",
        )

        result = _run_worker_process(
            worker_id=1,
            task="Fix the bug",
            model="gpt-4o",
            worktree_path="/tmp/wt-1",
            branch="architect/parallel-1",
            agent="build",
            max_steps=50,
            budget=1.0,
            timeout=300,
        )

        assert result.worker_id == 1
        assert result.branch == "architect/parallel-1"
        assert result.model == "gpt-4o"
        assert result.status == "success"
        assert result.steps == 15
        assert result.cost == 0.042
        assert result.files_modified == ["src/main.py", "tests/test_main.py"]
        assert result.worktree_path == "/tmp/wt-1"
        assert result.duration > 0

    @patch("architect.features.parallel.subprocess.run")
    def test_successful_json_model_none_becomes_default(self, mock_run):
        """Cuando model es None, el resultado usa 'default'."""
        json_output = json.dumps({"status": "success", "steps": 5, "cost": 0.01})
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json_output, stderr=""
        )

        result = _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        assert result.model == "default"

    @patch("architect.features.parallel.subprocess.run")
    def test_builds_correct_command(self, mock_run):
        """_run_worker_process construye el comando architect correctamente."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Fix the bug",
            model="gpt-4o",
            worktree_path="/tmp/wt-1",
            branch="architect/parallel-1",
            agent="build",
            max_steps=50,
            budget=1.5,
            timeout=300,
        )

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "architect"
        assert cmd[1] == "run"
        assert cmd[2] == "Fix the bug"
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "build"
        assert "--confirm-mode" in cmd
        assert cmd[cmd.index("--confirm-mode") + 1] == "yolo"
        assert "--json" in cmd
        assert "--max-steps" in cmd
        assert cmd[cmd.index("--max-steps") + 1] == "50"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-4o"
        assert "--budget" in cmd
        assert cmd[cmd.index("--budget") + 1] == "1.5"
        assert "--timeout" in cmd
        assert cmd[cmd.index("--timeout") + 1] == "300"

    @patch("architect.features.parallel.subprocess.run")
    def test_command_without_optional_params(self, mock_run):
        """Sin model, budget ni timeout, no se incluyen esos flags."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        cmd = mock_run.call_args[0][0]
        assert "--model" not in cmd
        assert "--budget" not in cmd
        assert "--timeout" not in cmd

    @patch("architect.features.parallel.subprocess.run")
    def test_default_timeout_is_600(self, mock_run):
        """Sin timeout configurado, usa 600 como timeout del subprocess."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        # Verificar que subprocess.run fue llamado con timeout=600
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 600

    @patch("architect.features.parallel.subprocess.run")
    def test_custom_timeout_used(self, mock_run):
        """Con timeout configurado, se pasa al subprocess."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=120,
        )

        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 120

    @patch("architect.features.parallel.subprocess.run")
    def test_invalid_json_output_returncode_zero(self, mock_run):
        """Con JSON invalido y returncode 0, el status es 'partial'."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not valid json {{{",
            stderr="",
        )

        result = _run_worker_process(
            worker_id=2,
            task="Task",
            model="gpt-4o",
            worktree_path="/tmp/wt-2",
            branch="architect/parallel-2",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        assert result.worker_id == 2
        assert result.status == "partial"
        assert result.steps == 0
        assert result.cost == 0
        assert result.files_modified == []
        assert result.model == "gpt-4o"
        assert result.duration > 0

    @patch("architect.features.parallel.subprocess.run")
    def test_invalid_json_output_returncode_nonzero(self, mock_run):
        """Con JSON invalido y returncode != 0, el status es 'failed'."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="Error: something went wrong\n",
            stderr="traceback...",
        )

        result = _run_worker_process(
            worker_id=3,
            task="Task",
            model=None,
            worktree_path="/tmp/wt-3",
            branch="architect/parallel-3",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        assert result.status == "failed"
        assert result.model == "default"
        assert result.steps == 0

    @patch("architect.features.parallel.subprocess.run")
    def test_empty_stdout(self, mock_run):
        """Con stdout vacio y returncode 0, status es 'partial'."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        result = _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        assert result.status == "partial"

    @patch("architect.features.parallel.subprocess.run")
    def test_timeout_expired(self, mock_run):
        """TimeoutExpired retorna WorkerResult con status 'timeout'."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["architect", "run"], timeout=300
        )

        result = _run_worker_process(
            worker_id=4,
            task="Long task",
            model="gpt-4o",
            worktree_path="/tmp/wt-4",
            branch="architect/parallel-4",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=300,
        )

        assert result.worker_id == 4
        assert result.status == "timeout"
        assert result.steps == 0
        assert result.cost == 0
        assert result.files_modified == []
        assert result.model == "gpt-4o"
        assert result.duration > 0
        assert result.branch == "architect/parallel-4"
        assert result.worktree_path == "/tmp/wt-4"

    @patch("architect.features.parallel.subprocess.run")
    def test_json_missing_fields_uses_defaults(self, mock_run):
        """JSON valido pero con campos faltantes usa valores por defecto."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        result = _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        assert result.status == "success"
        assert result.steps == 0  # default from .get("steps", 0)
        assert result.cost == 0  # default from .get("cost", 0)
        assert result.files_modified == []  # default

    @patch("architect.features.parallel.subprocess.run")
    def test_cwd_is_worktree_path(self, mock_run):
        """subprocess.run se ejecuta con cwd=worktree_path."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/custom/worktree/path",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
        )

        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == "/custom/worktree/path"


# -- Test run() orchestration ------------------------------------------------


def _make_fake_executor(worker_fn):
    """Creates a fake ProcessPoolExecutor context manager that runs synchronously.

    The worker_fn is called directly (in-process) instead of being sent to a
    subprocess pool. This allows us to intercept the actual arguments that
    run() passes to _run_worker_process.

    Args:
        worker_fn: Callable that will be invoked instead of the real worker.
                   Receives the same (fn, **kwargs) that executor.submit() gets.
    """

    class _FakeFuture:
        def __init__(self, result=None, exception=None):
            self._result = result
            self._exception = exception

        def result(self):
            if self._exception:
                raise self._exception
            return self._result

    class _FakeExecutor:
        def __init__(self, **kwargs):
            self._futures = []

        def submit(self, fn, **kwargs):
            try:
                res = worker_fn(**kwargs)
                fut = _FakeFuture(result=res)
            except Exception as e:
                fut = _FakeFuture(exception=e)
            self._futures.append(fut)
            return fut

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    # Make as_completed return futures in order
    return _FakeExecutor, lambda futs: iter(futs)


class TestParallelRunnerRun:
    """Tests para ParallelRunner.run (orquestacion completa)."""

    @patch("architect.features.parallel.subprocess.run")
    def test_run_orchestrates_workers(self, mock_subprocess, workspace):
        """run() crea worktrees y lanza workers, retornando resultados ordenados."""
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="main\n", stderr=""
        )

        def make_result(**kwargs):
            return WorkerResult(
                worker_id=kwargs["worker_id"],
                branch=kwargs["branch"],
                model=kwargs.get("model") or "default",
                status="success",
                steps=10,
                cost=0.05,
                duration=5.0,
                files_modified=["file.py"],
                worktree_path=kwargs["worktree_path"],
            )

        FakeExecutor, fake_as_completed = _make_fake_executor(make_result)

        with patch("architect.features.parallel.ProcessPoolExecutor", FakeExecutor), \
             patch("architect.features.parallel.as_completed", fake_as_completed):
            config = ParallelConfig(tasks=["Task A"], workers=2)
            runner = ParallelRunner(config, str(workspace))
            results = runner.run()

        assert len(results) == 2
        assert results[0].worker_id == 1
        assert results[1].worker_id == 2
        assert all(r.status == "success" for r in results)

    @patch("architect.features.parallel.subprocess.run")
    def test_run_handles_worker_exception(self, mock_subprocess, workspace):
        """run() captura excepciones de workers y crea resultado 'failed'."""
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="main\n", stderr=""
        )

        def raise_error(**kwargs):
            raise RuntimeError("Worker crashed")

        FakeExecutor, fake_as_completed = _make_fake_executor(raise_error)

        with patch("architect.features.parallel.ProcessPoolExecutor", FakeExecutor), \
             patch("architect.features.parallel.as_completed", fake_as_completed):
            config = ParallelConfig(tasks=["Task"], workers=1)
            runner = ParallelRunner(config, str(workspace))
            results = runner.run()

        assert len(results) == 1
        assert results[0].status == "failed"
        assert results[0].worker_id == 1
        assert results[0].steps == 0
        assert results[0].cost == 0

    @patch("architect.features.parallel.subprocess.run")
    def test_run_with_multiple_models(self, mock_subprocess, workspace):
        """run() pasa el modelo correcto a cada worker."""
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="main\n", stderr=""
        )

        captured_calls = []

        def capture_worker(**kwargs):
            captured_calls.append({
                "worker_id": kwargs["worker_id"],
                "task": kwargs["task"],
                "model": kwargs["model"],
            })
            return WorkerResult(
                worker_id=kwargs["worker_id"],
                branch=kwargs["branch"],
                model=kwargs.get("model") or "default",
                status="success",
                steps=5,
                cost=0.01,
                duration=2.0,
                files_modified=[],
                worktree_path=kwargs["worktree_path"],
            )

        FakeExecutor, fake_as_completed = _make_fake_executor(capture_worker)

        with patch("architect.features.parallel.ProcessPoolExecutor", FakeExecutor), \
             patch("architect.features.parallel.as_completed", fake_as_completed):
            config = ParallelConfig(
                tasks=["Task A", "Task B"],
                workers=2,
                models=["gpt-4o", "claude-sonnet-4-20250514"],
            )
            runner = ParallelRunner(config, str(workspace))
            results = runner.run()

        assert len(results) == 2

        # Verify models were passed correctly
        models_used = {c["model"] for c in captured_calls}
        assert "gpt-4o" in models_used
        assert "claude-sonnet-4-20250514" in models_used

        # Verify tasks were passed correctly
        tasks_used = {c["task"] for c in captured_calls}
        assert "Task A" in tasks_used
        assert "Task B" in tasks_used

    @patch("architect.features.parallel.subprocess.run")
    def test_run_handles_worktree_creation_error(self, mock_subprocess, workspace):
        """run() captura errores de creacion de worktrees sin crash."""
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if "worktree" in cmd and "add" in cmd:
                return MagicMock(
                    returncode=1,
                    stderr="fatal: error",
                )
            return MagicMock(returncode=0, stdout="main\n", stderr="")

        mock_subprocess.side_effect = side_effect

        config = ParallelConfig(tasks=["Task"], workers=1)
        runner = ParallelRunner(config, str(workspace))
        results = runner.run()

        # run() should catch the RuntimeError and return empty results
        assert isinstance(results, list)

    @patch("architect.features.parallel.subprocess.run")
    def test_run_results_sorted_by_worker_id(self, mock_subprocess, workspace):
        """run() retorna resultados ordenados por worker_id."""
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="main\n", stderr=""
        )

        def make_result(**kwargs):
            wid = kwargs["worker_id"]
            return WorkerResult(
                worker_id=wid,
                branch=kwargs["branch"],
                model=kwargs.get("model") or "default",
                status="success",
                steps=wid * 5,
                cost=wid * 0.01,
                duration=wid * 1.0,
                files_modified=[],
                worktree_path=kwargs["worktree_path"],
            )

        FakeExecutor, fake_as_completed = _make_fake_executor(make_result)

        with patch("architect.features.parallel.ProcessPoolExecutor", FakeExecutor), \
             patch("architect.features.parallel.as_completed", fake_as_completed):
            config = ParallelConfig(tasks=["Task"], workers=4)
            runner = ParallelRunner(config, str(workspace))
            results = runner.run()

        assert len(results) == 4
        worker_ids = [r.worker_id for r in results]
        assert worker_ids == [1, 2, 3, 4]

    @patch("architect.features.parallel.subprocess.run")
    def test_run_passes_config_to_workers(self, mock_subprocess, workspace):
        """run() pasa agent, max_steps, budget y timeout de la config."""
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        captured_kwargs = []

        def capture_worker(**kwargs):
            captured_kwargs.append(kwargs)
            return WorkerResult(
                worker_id=kwargs["worker_id"],
                branch=kwargs["branch"],
                model=kwargs.get("model") or "default",
                status="success",
                steps=1,
                cost=0,
                duration=0.1,
                files_modified=[],
                worktree_path=kwargs["worktree_path"],
            )

        FakeExecutor, fake_as_completed = _make_fake_executor(capture_worker)

        with patch("architect.features.parallel.ProcessPoolExecutor", FakeExecutor), \
             patch("architect.features.parallel.as_completed", fake_as_completed):
            config = ParallelConfig(
                tasks=["Task"],
                workers=1,
                agent="plan",
                max_steps=20,
                budget_per_worker=2.5,
                timeout_per_worker=180,
                base_branch="develop",
            )
            runner = ParallelRunner(config, str(workspace))
            runner.run()

        assert len(captured_kwargs) == 1
        kw = captured_kwargs[0]
        assert kw["agent"] == "plan"
        assert kw["max_steps"] == 20
        assert kw["budget"] == 2.5
        assert kw["timeout"] == 180


# -- Test WORKTREE_PREFIX constant -------------------------------------------


class TestConstants:
    """Tests para constantes del modulo."""

    def test_worktree_prefix(self):
        """WORKTREE_PREFIX tiene el valor esperado."""
        assert WORKTREE_PREFIX == ".architect-parallel"
