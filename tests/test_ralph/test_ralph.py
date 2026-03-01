"""
Tests para el Ralph Loop Nativo v4-C1.

Cubre:
- RalphConfig (dataclass, campos y defaults)
- LoopIteration (dataclass, campos)
- RalphLoopResult (dataclass, properties)
- RalphLoop (run, _build_iteration_prompt, _run_checks, _update_progress,
  cleanup_progress, contexto limpio por iteracion)
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from architect.features.ralph import (
    LoopIteration,
    RalphConfig,
    RalphLoop,
    RalphLoopResult,
    WORKTREE_BRANCH,
    WORKTREE_DIR,
)


# ── Mock helpers ─────────────────────────────────────────────────────────


class MockCostTracker:
    """Mock de CostTracker con total_cost_usd."""

    def __init__(self, cost: float = 0.01):
        self.total_cost_usd = cost


class MockAgentState:
    """Mock del estado retornado por un agente."""

    def __init__(
        self,
        final_output: str = "",
        status: str = "success",
        steps: int = 3,
        cost: float = 0.01,
    ):
        self.final_output = final_output
        self.status = status
        self.current_step = steps
        self.cost_tracker = MockCostTracker(cost) if cost > 0 else None


class MockAgent:
    """Mock de un AgentLoop con metodo .run()."""

    def __init__(self, state: MockAgentState | None = None):
        self.state = state or MockAgentState()
        self.run_calls: list[str] = []

    def run(self, prompt: str) -> MockAgentState:
        self.run_calls.append(prompt)
        return self.state


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal."""
    return tmp_path


@pytest.fixture
def default_config() -> RalphConfig:
    """Configuracion Ralph con defaults."""
    return RalphConfig(
        task="Fix the login bug",
        checks=["pytest tests/", "ruff check ."],
    )


@pytest.fixture
def mock_agent_factory():
    """Factory que retorna un mock agent configurable."""
    state = MockAgentState(final_output="Done. COMPLETE", steps=3, cost=0.01)
    agent = MockAgent(state)

    def factory(**kwargs):
        return agent

    factory._agent = agent
    factory._state = state
    return factory


@pytest.fixture
def ralph_loop(
    default_config: RalphConfig,
    mock_agent_factory,
    workspace: Path,
) -> RalphLoop:
    """RalphLoop con config por defecto y mocks."""
    return RalphLoop(
        config=default_config,
        agent_factory=mock_agent_factory,
        workspace_root=str(workspace),
    )


# ── Tests: RalphConfig ──────────────────────────────────────────────────


class TestRalphConfig:
    """Tests para RalphConfig dataclass."""

    def test_required_fields(self) -> None:
        """RalphConfig requiere task y checks."""
        config = RalphConfig(task="Do something", checks=["pytest"])
        assert config.task == "Do something"
        assert config.checks == ["pytest"]

    def test_defaults(self) -> None:
        """RalphConfig tiene defaults razonables."""
        config = RalphConfig(task="test", checks=["make test"])
        assert config.spec_file is None
        assert config.completion_tag == "COMPLETE"
        assert config.max_iterations == 25
        assert config.max_cost is None
        assert config.max_time is None
        assert config.agent == "build"
        assert config.model is None
        assert config.use_worktree is False

    def test_custom_values(self) -> None:
        """RalphConfig acepta valores personalizados."""
        config = RalphConfig(
            task="build feature",
            checks=["pytest", "mypy src/"],
            spec_file="spec.md",
            completion_tag="DONE",
            max_iterations=10,
            max_cost=5.0,
            max_time=600,
            agent="plan",
            model="claude-sonnet-4-6",
            use_worktree=True,
        )
        assert config.spec_file == "spec.md"
        assert config.completion_tag == "DONE"
        assert config.max_iterations == 10
        assert config.max_cost == 5.0
        assert config.max_time == 600
        assert config.agent == "plan"
        assert config.model == "claude-sonnet-4-6"
        assert config.use_worktree is True

    def test_checks_is_list(self) -> None:
        """checks es una lista de strings."""
        config = RalphConfig(task="t", checks=["a", "b", "c"])
        assert len(config.checks) == 3
        assert all(isinstance(c, str) for c in config.checks)

    def test_empty_checks(self) -> None:
        """checks puede ser lista vacia."""
        config = RalphConfig(task="t", checks=[])
        assert config.checks == []


# ── Tests: LoopIteration ────────────────────────────────────────────────


class TestLoopIteration:
    """Tests para LoopIteration dataclass."""

    def test_all_fields(self) -> None:
        """LoopIteration tiene todos los campos esperados."""
        iteration = LoopIteration(
            iteration=1,
            steps_taken=5,
            cost=0.023,
            duration=12.5,
            check_results=[{"name": "pytest", "passed": True, "output": ""}],
            all_checks_passed=True,
            completion_tag_found=True,
        )
        assert iteration.iteration == 1
        assert iteration.steps_taken == 5
        assert iteration.cost == 0.023
        assert iteration.duration == 12.5
        assert len(iteration.check_results) == 1
        assert iteration.all_checks_passed is True
        assert iteration.completion_tag_found is True
        assert iteration.error is None

    def test_error_default_none(self) -> None:
        """error es None por defecto."""
        iteration = LoopIteration(
            iteration=1,
            steps_taken=0,
            cost=0.0,
            duration=0.0,
            check_results=[],
            all_checks_passed=False,
            completion_tag_found=False,
        )
        assert iteration.error is None

    def test_error_with_value(self) -> None:
        """error puede tener un valor."""
        iteration = LoopIteration(
            iteration=2,
            steps_taken=0,
            cost=0.0,
            duration=0.0,
            check_results=[],
            all_checks_passed=False,
            completion_tag_found=False,
            error="Agent crashed",
        )
        assert iteration.error == "Agent crashed"

    def test_check_results_multiple(self) -> None:
        """check_results puede tener multiples resultados."""
        checks = [
            {"name": "pytest", "passed": True, "output": ""},
            {"name": "ruff", "passed": False, "output": "E501 line too long"},
        ]
        iteration = LoopIteration(
            iteration=1,
            steps_taken=3,
            cost=0.01,
            duration=5.0,
            check_results=checks,
            all_checks_passed=False,
            completion_tag_found=False,
        )
        assert len(iteration.check_results) == 2
        assert iteration.check_results[0]["passed"] is True
        assert iteration.check_results[1]["passed"] is False


# ── Tests: RalphLoopResult ──────────────────────────────────────────────


class TestRalphLoopResult:
    """Tests para RalphLoopResult dataclass y properties."""

    def test_defaults(self) -> None:
        """RalphLoopResult tiene defaults razonables."""
        result = RalphLoopResult()
        assert result.iterations == []
        assert result.total_cost == 0.0
        assert result.total_duration == 0.0
        assert result.success is False
        assert result.stop_reason == ""

    def test_total_iterations_empty(self) -> None:
        """total_iterations es 0 sin iteraciones."""
        result = RalphLoopResult()
        assert result.total_iterations == 0

    def test_total_iterations_with_data(self) -> None:
        """total_iterations cuenta las iteraciones."""
        result = RalphLoopResult()
        for i in range(3):
            result.iterations.append(
                LoopIteration(
                    iteration=i + 1,
                    steps_taken=2,
                    cost=0.01,
                    duration=5.0,
                    check_results=[],
                    all_checks_passed=False,
                    completion_tag_found=False,
                )
            )
        assert result.total_iterations == 3

    def test_success_flag(self) -> None:
        """success se puede establecer."""
        result = RalphLoopResult(success=True, stop_reason="all_checks_passed")
        assert result.success is True
        assert result.stop_reason == "all_checks_passed"

    def test_total_cost_accumulates(self) -> None:
        """total_cost refleja el coste total."""
        result = RalphLoopResult(total_cost=0.15)
        assert result.total_cost == 0.15

    def test_iterations_list_is_independent(self) -> None:
        """Cada RalphLoopResult tiene su propia lista de iteraciones."""
        r1 = RalphLoopResult()
        r2 = RalphLoopResult()
        r1.iterations.append(
            LoopIteration(
                iteration=1, steps_taken=1, cost=0.0, duration=0.0,
                check_results=[], all_checks_passed=False,
                completion_tag_found=False,
            )
        )
        assert len(r2.iterations) == 0


# ── Tests: RalphLoop.__init__ ───────────────────────────────────────────


class TestRalphLoopInit:
    """Tests para RalphLoop constructor."""

    def test_stores_config(self, ralph_loop: RalphLoop, default_config: RalphConfig) -> None:
        """__init__ guarda la config."""
        assert ralph_loop.config is default_config

    def test_stores_workspace(self, ralph_loop: RalphLoop, workspace: Path) -> None:
        """__init__ guarda el workspace_root."""
        assert ralph_loop.workspace_root == str(workspace)

    def test_default_workspace_is_cwd(self, default_config: RalphConfig) -> None:
        """workspace_root es cwd si no se pasa."""
        factory = MagicMock()
        loop = RalphLoop(config=default_config, agent_factory=factory)
        assert loop.workspace_root == str(Path.cwd())

    def test_progress_file_path(self, ralph_loop: RalphLoop, workspace: Path) -> None:
        """progress_file apunta a .architect/ralph-progress.md."""
        expected = workspace / ".architect" / "ralph-progress.md"
        assert ralph_loop.progress_file == expected

    def test_iterations_starts_empty(self, ralph_loop: RalphLoop) -> None:
        """iterations empieza vacio."""
        assert ralph_loop.iterations == []


# ── Tests: RalphLoop.run — Exito en primera iteracion ───────────────────


class TestRalphLoopRunSuccess:
    """Tests para RalphLoop.run cuando checks pasan y tag encontrado."""

    @patch("architect.features.ralph.subprocess.run")
    def test_single_iteration_success(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() termina en 1 iteracion si checks pasan y tag encontrado."""
        # Mock git rev-parse HEAD
        mock_subprocess.return_value = MagicMock(
            stdout="abc123\n", stderr="", returncode=0
        )

        state = MockAgentState(final_output="All done. COMPLETE", steps=5, cost=0.02)
        agent = MockAgent(state)
        call_count = 0

        def factory(**kwargs):
            nonlocal call_count
            call_count += 1
            return agent

        config = RalphConfig(
            task="Fix bug",
            checks=["pytest tests/"],
        )
        loop = RalphLoop(config=config, agent_factory=factory, workspace_root=str(workspace))
        result = loop.run()

        assert result.success is True
        assert result.stop_reason == "all_checks_passed"
        assert result.total_iterations == 1
        assert result.total_cost > 0
        assert result.total_duration > 0
        assert call_count == 1

    @patch("architect.features.ralph.subprocess.run")
    def test_result_contains_iteration(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() incluye la iteracion en el resultado."""
        mock_subprocess.return_value = MagicMock(
            stdout="abc123\n", stderr="", returncode=0
        )

        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)
        agent = MockAgent(state)
        config = RalphConfig(task="Test", checks=["echo ok"])
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: agent,
            workspace_root=str(workspace),
        )
        result = loop.run()

        assert len(result.iterations) == 1
        it = result.iterations[0]
        assert it.iteration == 1
        assert it.steps_taken == 3
        assert it.all_checks_passed is True
        assert it.completion_tag_found is True


# ── Tests: RalphLoop.run — Checks fallan, loop continua ────────────────


class TestRalphLoopRunChecksFailThenPass:
    """Tests para RalphLoop.run cuando checks fallan primero."""

    @patch("architect.features.ralph.subprocess.run")
    def test_iterates_until_checks_pass(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() itera multiples veces hasta que checks pasan."""
        # Iteracion 1: git rev-parse OK, then check fails, then
        # Iteracion 2: git diff OK, then check passes
        call_sequence = iter([
            # _get_current_ref
            MagicMock(stdout="abc123\n", stderr="", returncode=0),
            # _run_checks iter 1 - check fails
            MagicMock(stdout="FAIL\n", stderr="1 test failed", returncode=1),
            # _run_checks iter 2 - _get_accumulated_diff
            MagicMock(stdout="diff --git a/file.py", stderr="", returncode=0),
            # _run_checks iter 2 - check passes
            MagicMock(stdout="OK\n", stderr="", returncode=0),
        ])

        def subprocess_side_effect(*args, **kwargs):
            return next(call_sequence)

        mock_subprocess.side_effect = subprocess_side_effect

        iteration_count = 0

        def factory(**kwargs):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count == 1:
                return MockAgent(MockAgentState(final_output="trying...", steps=3, cost=0.01))
            else:
                return MockAgent(MockAgentState(final_output="Fixed it. COMPLETE", steps=5, cost=0.02))

        config = RalphConfig(task="Fix tests", checks=["pytest tests/"])
        loop = RalphLoop(config=config, agent_factory=factory, workspace_root=str(workspace))
        result = loop.run()

        assert result.success is True
        assert result.total_iterations == 2
        assert result.stop_reason == "all_checks_passed"

    @patch("architect.features.ralph.subprocess.run")
    def test_checks_pass_but_no_tag_continues(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() continua si checks pasan pero no se encuentra el tag."""
        calls = iter([
            # _get_current_ref
            MagicMock(stdout="abc123\n", returncode=0),
            # iter 1: check passes
            MagicMock(stdout="OK\n", returncode=0),
            # iter 2: _get_accumulated_diff
            MagicMock(stdout="", returncode=0),
            # iter 2: check passes
            MagicMock(stdout="OK\n", returncode=0),
        ])
        mock_subprocess.side_effect = lambda *a, **kw: next(calls)

        iter_num = 0

        def factory(**kwargs):
            nonlocal iter_num
            iter_num += 1
            if iter_num < 2:
                return MockAgent(MockAgentState(final_output="still working", steps=3, cost=0.01))
            else:
                return MockAgent(MockAgentState(final_output="All done COMPLETE", steps=4, cost=0.01))

        config = RalphConfig(task="Work", checks=["true"], max_iterations=5)
        loop = RalphLoop(config=config, agent_factory=factory, workspace_root=str(workspace))
        result = loop.run()

        assert result.success is True
        assert result.total_iterations == 2


# ── Tests: RalphLoop.run — Limites ──────────────────────────────────────


class TestRalphLoopRunLimits:
    """Tests para limites de RalphLoop.run (max_iterations, max_cost, max_time)."""

    @patch("architect.features.ralph.subprocess.run")
    def test_max_iterations_limit(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() se detiene al alcanzar max_iterations."""
        # Siempre falla el check
        mock_subprocess.return_value = MagicMock(
            stdout="FAIL", stderr="error", returncode=1
        )

        config = RalphConfig(task="Fix", checks=["false"], max_iterations=3)
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(
                MockAgentState(final_output="trying", steps=2, cost=0.01)
            ),
            workspace_root=str(workspace),
        )
        result = loop.run()

        assert result.success is False
        assert result.stop_reason == "max_iterations"
        assert result.total_iterations == 3

    @patch("architect.features.ralph.subprocess.run")
    def test_max_cost_limit(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() se detiene al alcanzar max_cost."""
        mock_subprocess.return_value = MagicMock(
            stdout="FAIL", stderr="", returncode=1
        )

        iteration_num = 0

        def factory(**kwargs):
            nonlocal iteration_num
            iteration_num += 1
            # Cada iteracion cuesta 0.05
            return MockAgent(
                MockAgentState(final_output="trying", steps=2, cost=0.05)
            )

        config = RalphConfig(
            task="Fix",
            checks=["false"],
            max_iterations=100,
            max_cost=0.10,  # Budget: 0.10, cada iter cuesta 0.05
        )
        loop = RalphLoop(
            config=config, agent_factory=factory, workspace_root=str(workspace)
        )
        result = loop.run()

        assert result.success is False
        assert result.stop_reason == "budget_exhausted"
        # Deberian ejecutarse 2 iteraciones (0.05 + 0.05 = 0.10), la 3ra se detiene
        assert result.total_iterations == 2

    @patch("architect.features.ralph.subprocess.run")
    @patch("architect.features.ralph.time.time")
    def test_max_time_limit(
        self, mock_time, mock_subprocess, workspace: Path
    ) -> None:
        """run() se detiene al exceder max_time."""
        mock_subprocess.return_value = MagicMock(
            stdout="FAIL", stderr="", returncode=1
        )

        # Use a counter-based mock that increments by 4 seconds per call.
        # This way:
        # - start_time = 100.0
        # - iter 1 elapsed check: 104.0 (elapsed=4 < 10, OK)
        # - iter 1 iter_start: 108.0
        # - iter 1 duration end: 112.0
        # - ... any additional calls keep going up ...
        # - iter 2 elapsed check: elapsed >= 10, STOP
        # - final total_duration call: still works
        call_count = 0

        def time_counter():
            nonlocal call_count
            call_count += 1
            return 100.0 + (call_count - 1) * 4.0

        mock_time.side_effect = time_counter

        config = RalphConfig(
            task="Fix",
            checks=["false"],
            max_iterations=100,
            max_time=10,
        )
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(
                MockAgentState(final_output="trying", steps=1, cost=0.01)
            ),
            workspace_root=str(workspace),
        )
        result = loop.run()

        assert result.success is False
        assert result.stop_reason == "timeout"
        assert result.total_iterations == 1


# ── Tests: RalphLoop._build_iteration_prompt ────────────────────────────


class TestBuildIterationPrompt:
    """Tests para RalphLoop._build_iteration_prompt."""

    def test_first_iteration_includes_task(self, ralph_loop: RalphLoop) -> None:
        """El prompt de la primera iteracion incluye la tarea."""
        prompt = ralph_loop._build_iteration_prompt(1, "abc123")
        assert "Fix the login bug" in prompt

    def test_first_iteration_includes_checks(self, ralph_loop: RalphLoop) -> None:
        """El prompt incluye los comandos de verificacion."""
        prompt = ralph_loop._build_iteration_prompt(1, "abc123")
        assert "pytest tests/" in prompt
        assert "ruff check ." in prompt

    def test_first_iteration_includes_completion_tag(self, ralph_loop: RalphLoop) -> None:
        """El prompt incluye el completion_tag."""
        prompt = ralph_loop._build_iteration_prompt(1, "abc123")
        assert "COMPLETE" in prompt

    def test_first_iteration_includes_iteration_number(self, ralph_loop: RalphLoop) -> None:
        """El prompt incluye el numero de iteracion."""
        prompt = ralph_loop._build_iteration_prompt(1, "abc123")
        assert "iteration" in prompt.lower()
        assert "1/" in prompt

    @patch("architect.features.ralph.subprocess.run")
    def test_subsequent_iteration_includes_diff(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """El prompt para iteracion >1 incluye el diff acumulado."""
        mock_subprocess.return_value = MagicMock(
            stdout="diff --git a/file.py b/file.py\n+new line",
            stderr="",
            returncode=0,
        )

        prompt = ralph_loop._build_iteration_prompt(2, "abc123")
        assert "diff --git" in prompt
        assert "Changes from Previous Iterations" in prompt

    @patch("architect.features.ralph.subprocess.run")
    def test_subsequent_iteration_no_diff_if_empty(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """Si no hay diff, no se incluye la seccion de diff."""
        mock_subprocess.return_value = MagicMock(stdout="", returncode=0)

        prompt = ralph_loop._build_iteration_prompt(2, "abc123")
        assert "Changes from Previous Iterations" not in prompt

    def test_subsequent_iteration_includes_errors(
        self, ralph_loop: RalphLoop
    ) -> None:
        """El prompt para iteracion >1 incluye errores de la anterior."""
        # Simular una iteracion anterior con checks fallidos
        ralph_loop.iterations.append(
            LoopIteration(
                iteration=1,
                steps_taken=3,
                cost=0.01,
                duration=5.0,
                check_results=[
                    {"name": "pytest tests/", "passed": False, "output": "FAILED test_login"},
                    {"name": "ruff check .", "passed": True, "output": ""},
                ],
                all_checks_passed=False,
                completion_tag_found=False,
            )
        )

        with patch("architect.features.ralph.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(stdout="", returncode=0)
            prompt = ralph_loop._build_iteration_prompt(2, "abc123")

        assert "Errors from Previous Iteration" in prompt
        assert "FAILED test_login" in prompt

    def test_subsequent_iteration_includes_execution_error(
        self, ralph_loop: RalphLoop
    ) -> None:
        """El prompt incluye errores de ejecucion de la iteracion anterior."""
        ralph_loop.iterations.append(
            LoopIteration(
                iteration=1,
                steps_taken=0,
                cost=0.0,
                duration=0.0,
                check_results=[],
                all_checks_passed=False,
                completion_tag_found=False,
                error="Agent timeout after 300s",
            )
        )

        with patch("architect.features.ralph.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(stdout="", returncode=0)
            prompt = ralph_loop._build_iteration_prompt(2, "abc123")

        assert "Execution Error" in prompt
        assert "Agent timeout" in prompt

    def test_spec_file_used_when_exists(self, workspace: Path) -> None:
        """Si spec_file existe, se usa su contenido en lugar de task."""
        spec = workspace / "spec.md"
        spec.write_text("# Detailed Specification\nDo X, Y, Z.", encoding="utf-8")

        config = RalphConfig(
            task="Simple task",
            checks=["pytest"],
            spec_file=str(spec),
        )
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )
        prompt = loop._build_iteration_prompt(1, "abc123")

        assert "Detailed Specification" in prompt
        assert "Do X, Y, Z" in prompt

    def test_spec_file_fallback_to_task(self, workspace: Path) -> None:
        """Si spec_file no existe, se usa task como fallback."""
        config = RalphConfig(
            task="Fallback task description",
            checks=["pytest"],
            spec_file="/nonexistent/spec.md",
        )
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )
        prompt = loop._build_iteration_prompt(1, "abc123")

        assert "Fallback task description" in prompt

    @patch("architect.features.ralph.subprocess.run")
    def test_diff_truncated_at_5000_chars(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """Diff se trunca a 5000 caracteres."""
        long_diff = "+" * 8000
        mock_subprocess.return_value = MagicMock(stdout=long_diff, returncode=0)

        prompt = ralph_loop._build_iteration_prompt(2, "abc123")
        assert "diff truncated" in prompt

    def test_progress_file_included_when_exists(
        self, ralph_loop: RalphLoop, workspace: Path
    ) -> None:
        """Si progress file existe, se incluye en el prompt."""
        progress_dir = workspace / ".architect"
        progress_dir.mkdir(parents=True, exist_ok=True)
        progress_file = progress_dir / "ralph-progress.md"
        progress_file.write_text(
            "# Ralph Loop Progress\n### Iteration 1\n- Status: Failed\n",
            encoding="utf-8",
        )

        prompt = ralph_loop._build_iteration_prompt(1, "abc123")
        assert "Accumulated Progress" in prompt
        assert "Iteration 1" in prompt


# ── Tests: RalphLoop._run_checks ────────────────────────────────────────


class TestRunChecks:
    """Tests para RalphLoop._run_checks."""

    @patch("architect.features.ralph.subprocess.run")
    def test_successful_check(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """Check exitoso retorna passed=True."""
        mock_subprocess.return_value = MagicMock(
            stdout="All 10 tests passed\n",
            stderr="",
            returncode=0,
        )

        results = ralph_loop._run_checks()

        assert len(results) == 2  # 2 checks en default_config
        assert results[0]["passed"] is True
        assert results[0]["name"] == "pytest tests/"
        assert "10 tests passed" in results[0]["output"]

    @patch("architect.features.ralph.subprocess.run")
    def test_failing_check(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """Check que falla retorna passed=False."""
        mock_subprocess.return_value = MagicMock(
            stdout="FAILED",
            stderr="2 tests failed",
            returncode=1,
        )

        results = ralph_loop._run_checks()

        assert len(results) == 2
        assert results[0]["passed"] is False
        assert "FAILED" in results[0]["output"] or "failed" in results[0]["output"]

    @patch("architect.features.ralph.subprocess.run")
    def test_check_timeout(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """Check que excede timeout retorna passed=False con mensaje."""
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd="pytest tests/", timeout=120
        )

        results = ralph_loop._run_checks()

        assert len(results) == 2
        assert results[0]["passed"] is False
        assert "Timeout" in results[0]["output"]

    @patch("architect.features.ralph.subprocess.run")
    def test_check_exception(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """Check que lanza excepcion retorna passed=False con error."""
        mock_subprocess.side_effect = OSError("Permission denied")

        results = ralph_loop._run_checks()

        assert len(results) == 2
        assert results[0]["passed"] is False
        assert "Error" in results[0]["output"]

    @patch("architect.features.ralph.subprocess.run")
    def test_multiple_checks_mixed_results(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """Multiples checks con resultados mixtos."""
        results_iter = iter([
            MagicMock(stdout="OK", stderr="", returncode=0),      # pytest pasa
            MagicMock(stdout="E501", stderr="errors", returncode=1),  # ruff falla
        ])
        mock_subprocess.side_effect = lambda *a, **kw: next(results_iter)

        results = ralph_loop._run_checks()

        assert len(results) == 2
        assert results[0]["passed"] is True
        assert results[1]["passed"] is False

    @patch("architect.features.ralph.subprocess.run")
    def test_empty_checks(self, mock_subprocess, workspace: Path) -> None:
        """Sin checks, _run_checks retorna lista vacia."""
        config = RalphConfig(task="Task", checks=[])
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        results = loop._run_checks()

        assert results == []
        mock_subprocess.assert_not_called()

    @patch("architect.features.ralph.subprocess.run")
    def test_check_output_truncated(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """Output del check se trunca a los ultimos 1000 chars."""
        long_output = "x" * 2000
        mock_subprocess.return_value = MagicMock(
            stdout=long_output, stderr="", returncode=0
        )

        results = ralph_loop._run_checks()

        assert len(results[0]["output"]) <= 1000

    @patch("architect.features.ralph.subprocess.run")
    def test_check_runs_in_workspace(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """Checks se ejecutan en el workspace_root."""
        mock_subprocess.return_value = MagicMock(
            stdout="", stderr="", returncode=0
        )

        ralph_loop._run_checks()

        for c in mock_subprocess.call_args_list:
            assert c.kwargs.get("cwd") == ralph_loop.workspace_root


# ── Tests: RalphLoop._update_progress ───────────────────────────────────


class TestUpdateProgress:
    """Tests para RalphLoop._update_progress."""

    def test_creates_progress_file(self, ralph_loop: RalphLoop) -> None:
        """_update_progress crea el archivo de progreso."""
        iteration = LoopIteration(
            iteration=1,
            steps_taken=5,
            cost=0.023,
            duration=12.5,
            check_results=[{"name": "pytest", "passed": True, "output": ""}],
            all_checks_passed=True,
            completion_tag_found=True,
        )

        ralph_loop._update_progress(iteration)

        assert ralph_loop.progress_file.exists()
        content = ralph_loop.progress_file.read_text(encoding="utf-8")
        assert "Ralph Loop" in content
        assert "Iteration" in content

    def test_appends_to_existing(self, ralph_loop: RalphLoop) -> None:
        """_update_progress acumula iteraciones en el archivo."""
        for i in range(1, 4):
            iteration = LoopIteration(
                iteration=i,
                steps_taken=i * 2,
                cost=0.01 * i,
                duration=5.0 * i,
                check_results=[{"name": "pytest", "passed": i == 3, "output": ""}],
                all_checks_passed=i == 3,
                completion_tag_found=False,
            )
            ralph_loop._update_progress(iteration)

        content = ralph_loop.progress_file.read_text(encoding="utf-8")
        assert "Iteration 1" in content
        assert "Iteration 2" in content
        assert "Iteration 3" in content

    def test_includes_check_status(self, ralph_loop: RalphLoop) -> None:
        """Progress incluye estado de cada check."""
        iteration = LoopIteration(
            iteration=1,
            steps_taken=3,
            cost=0.01,
            duration=5.0,
            check_results=[
                {"name": "pytest tests/", "passed": True, "output": ""},
                {"name": "ruff check .", "passed": False, "output": "errors"},
            ],
            all_checks_passed=False,
            completion_tag_found=False,
        )

        ralph_loop._update_progress(iteration)

        content = ralph_loop.progress_file.read_text(encoding="utf-8")
        assert "[PASS]" in content
        assert "[FAIL]" in content
        assert "pytest tests/" in content
        assert "ruff check ." in content

    def test_includes_error(self, ralph_loop: RalphLoop) -> None:
        """Progress incluye error si hay."""
        iteration = LoopIteration(
            iteration=1,
            steps_taken=0,
            cost=0.0,
            duration=0.0,
            check_results=[],
            all_checks_passed=False,
            completion_tag_found=False,
            error="Agent crashed unexpectedly",
        )

        ralph_loop._update_progress(iteration)

        content = ralph_loop.progress_file.read_text(encoding="utf-8")
        assert "Agent crashed" in content

    def test_includes_cost_and_duration(self, ralph_loop: RalphLoop) -> None:
        """Progress incluye coste y duracion."""
        iteration = LoopIteration(
            iteration=1,
            steps_taken=5,
            cost=0.0456,
            duration=23.7,
            check_results=[],
            all_checks_passed=False,
            completion_tag_found=False,
        )

        ralph_loop._update_progress(iteration)

        content = ralph_loop.progress_file.read_text(encoding="utf-8")
        assert "$0.0456" in content
        assert "23.7s" in content

    def test_creates_parent_directories(self, workspace: Path) -> None:
        """_update_progress crea directorios padre si no existen."""
        config = RalphConfig(task="Test", checks=["true"])
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        iteration = LoopIteration(
            iteration=1, steps_taken=1, cost=0.0, duration=0.0,
            check_results=[], all_checks_passed=False,
            completion_tag_found=False,
        )

        # .architect dir does not exist yet
        assert not (workspace / ".architect").exists()

        loop._update_progress(iteration)

        assert loop.progress_file.exists()
        assert (workspace / ".architect").exists()


# ── Tests: RalphLoop.cleanup_progress ───────────────────────────────────


class TestCleanupProgress:
    """Tests para RalphLoop.cleanup_progress."""

    def test_removes_existing_file(self, ralph_loop: RalphLoop) -> None:
        """cleanup_progress elimina el archivo si existe."""
        ralph_loop.progress_file.parent.mkdir(parents=True, exist_ok=True)
        ralph_loop.progress_file.write_text("content", encoding="utf-8")

        assert ralph_loop.progress_file.exists()
        ralph_loop.cleanup_progress()
        assert not ralph_loop.progress_file.exists()

    def test_no_error_if_not_exists(self, ralph_loop: RalphLoop) -> None:
        """cleanup_progress no lanza error si el archivo no existe."""
        assert not ralph_loop.progress_file.exists()
        ralph_loop.cleanup_progress()  # No debe lanzar


# ── Tests: Contexto limpio por iteracion ────────────────────────────────


class TestCleanContext:
    """Tests para verificar que cada iteracion recibe contexto limpio."""

    @patch("architect.features.ralph.subprocess.run")
    def test_agent_factory_called_each_iteration(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """agent_factory se llama de nuevo en cada iteracion (contexto limpio)."""
        # Siempre falla checks
        mock_subprocess.return_value = MagicMock(
            stdout="FAIL", stderr="", returncode=1
        )

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(
                MockAgentState(final_output="trying", steps=2, cost=0.01)
            )

        config = RalphConfig(task="Fix", checks=["false"], max_iterations=3)
        loop = RalphLoop(
            config=config, agent_factory=factory, workspace_root=str(workspace)
        )
        loop.run()

        # Factory debe haberse llamado 3 veces (una por iteracion)
        assert len(factory_calls) == 3

    @patch("architect.features.ralph.subprocess.run")
    def test_factory_receives_agent_and_model(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """agent_factory recibe agent y model de la config."""
        mock_subprocess.return_value = MagicMock(
            stdout="OK", stderr="", returncode=0
        )

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(
                MockAgentState(final_output="COMPLETE", steps=2, cost=0.01)
            )

        config = RalphConfig(
            task="Fix",
            checks=["true"],
            agent="plan",
            model="claude-sonnet-4-6",
        )
        loop = RalphLoop(
            config=config, agent_factory=factory, workspace_root=str(workspace)
        )
        loop.run()

        assert factory_calls[0]["agent"] == "plan"
        assert factory_calls[0]["model"] == "claude-sonnet-4-6"
        assert factory_calls[0]["workspace_root"] == str(workspace)

    @patch("architect.features.ralph.subprocess.run")
    def test_each_iteration_gets_fresh_agent(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """Cada iteracion recibe un agente distinto (fresco)."""
        mock_subprocess.return_value = MagicMock(
            stdout="FAIL", stderr="", returncode=1
        )

        agents_created = []

        def factory(**kwargs):
            agent = MockAgent(
                MockAgentState(final_output="trying", steps=2, cost=0.01)
            )
            agents_created.append(agent)
            return agent

        config = RalphConfig(task="Fix", checks=["false"], max_iterations=3)
        loop = RalphLoop(
            config=config, agent_factory=factory, workspace_root=str(workspace)
        )
        loop.run()

        # 3 agentes distintos creados
        assert len(agents_created) == 3
        assert agents_created[0] is not agents_created[1]
        assert agents_created[1] is not agents_created[2]


# ── Tests: RalphLoop._run_single_iteration ──────────────────────────────


class TestRunSingleIteration:
    """Tests para RalphLoop._run_single_iteration."""

    @patch("architect.features.ralph.subprocess.run")
    def test_successful_iteration(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """Una iteracion exitosa retorna datos correctos."""
        mock_subprocess.return_value = MagicMock(
            stdout="OK", stderr="", returncode=0
        )

        result = ralph_loop._run_single_iteration(1, "Do something")

        assert result.iteration == 1
        assert result.steps_taken == 3  # MockAgentState default
        assert result.all_checks_passed is True
        assert result.completion_tag_found is True  # "Done. COMPLETE" contiene "COMPLETE"
        assert result.error is None

    @patch("architect.features.ralph.subprocess.run")
    def test_iteration_with_agent_error(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """Si el agente lanza excepcion, la iteracion captura el error."""
        def factory(**kwargs):
            agent = MagicMock()
            agent.run.side_effect = RuntimeError("LLM API down")
            return agent

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config, agent_factory=factory, workspace_root=str(workspace)
        )

        result = loop._run_single_iteration(1, "Do something")

        assert result.iteration == 1
        assert result.steps_taken == 0
        assert result.cost == 0.0
        assert result.all_checks_passed is False
        assert result.completion_tag_found is False
        assert result.error == "LLM API down"

    @patch("architect.features.ralph.subprocess.run")
    def test_cost_from_tracker(self, mock_subprocess, workspace: Path) -> None:
        """El coste se extrae del cost_tracker del agente."""
        state = MockAgentState(final_output="COMPLETE", steps=5, cost=0.075)
        agent = MockAgent(state)

        mock_subprocess.return_value = MagicMock(stdout="OK", returncode=0)

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: agent,
            workspace_root=str(workspace),
        )

        result = loop._run_single_iteration(1, "Do something")
        assert result.cost == 0.075

    @patch("architect.features.ralph.subprocess.run")
    def test_cost_zero_without_tracker(self, mock_subprocess, workspace: Path) -> None:
        """Si no hay cost_tracker, el coste es 0."""
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0)
        agent = MockAgent(state)

        mock_subprocess.return_value = MagicMock(stdout="OK", returncode=0)

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: agent,
            workspace_root=str(workspace),
        )

        result = loop._run_single_iteration(1, "Do something")
        assert result.cost == 0.0

    @patch("architect.features.ralph.subprocess.run")
    def test_completion_tag_not_found(self, mock_subprocess, workspace: Path) -> None:
        """Si el output no contiene el tag, completion_tag_found es False."""
        state = MockAgentState(final_output="Still working on it", steps=3, cost=0.01)
        agent = MockAgent(state)

        mock_subprocess.return_value = MagicMock(stdout="OK", returncode=0)

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: agent,
            workspace_root=str(workspace),
        )

        result = loop._run_single_iteration(1, "Do something")
        assert result.completion_tag_found is False

    @patch("architect.features.ralph.subprocess.run")
    def test_custom_completion_tag(self, mock_subprocess, workspace: Path) -> None:
        """Completion tag personalizado se detecta correctamente."""
        state = MockAgentState(final_output="All done. FINISHED", steps=3, cost=0.01)
        agent = MockAgent(state)

        mock_subprocess.return_value = MagicMock(stdout="OK", returncode=0)

        config = RalphConfig(
            task="Fix", checks=["pytest"], completion_tag="FINISHED"
        )
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: agent,
            workspace_root=str(workspace),
        )

        result = loop._run_single_iteration(1, "Do something")
        assert result.completion_tag_found is True

    @patch("architect.features.ralph.subprocess.run")
    def test_empty_checks_means_not_passed(self, mock_subprocess, workspace: Path) -> None:
        """Sin checks, all_checks_passed es False (no hay checks que pasar)."""
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)
        agent = MockAgent(state)

        config = RalphConfig(task="Fix", checks=[])
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: agent,
            workspace_root=str(workspace),
        )

        result = loop._run_single_iteration(1, "Do something")
        # Con checks vacios, all() de lista vacia retorna True en Python,
        # pero el codigo tiene: all(c["passed"] ...) if check_results else False
        assert result.all_checks_passed is False


# ── Tests: RalphLoop._get_current_ref ───────────────────────────────────


class TestGetCurrentRef:
    """Tests para RalphLoop._get_current_ref."""

    @patch("architect.features.ralph.subprocess.run")
    def test_returns_commit_hash(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """_get_current_ref retorna el hash del commit actual."""
        mock_subprocess.return_value = MagicMock(
            stdout="abc123def456\n", returncode=0
        )
        ref = ralph_loop._get_current_ref()
        assert ref == "abc123def456"

    @patch("architect.features.ralph.subprocess.run")
    def test_returns_head_on_error(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """_get_current_ref retorna 'HEAD' si git falla."""
        mock_subprocess.side_effect = OSError("git not found")
        ref = ralph_loop._get_current_ref()
        assert ref == "HEAD"

    @patch("architect.features.ralph.subprocess.run")
    def test_returns_head_on_empty_output(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """_get_current_ref retorna 'HEAD' si output vacio."""
        mock_subprocess.return_value = MagicMock(stdout="", returncode=0)
        ref = ralph_loop._get_current_ref()
        assert ref == "HEAD"


# ── Tests: RalphLoop._get_accumulated_diff ──────────────────────────────


class TestGetAccumulatedDiff:
    """Tests para RalphLoop._get_accumulated_diff."""

    @patch("architect.features.ralph.subprocess.run")
    def test_returns_diff(self, mock_subprocess, ralph_loop: RalphLoop) -> None:
        """_get_accumulated_diff retorna el diff de git."""
        mock_subprocess.return_value = MagicMock(
            stdout="diff --git a/file.py b/file.py\n+new line\n",
            returncode=0,
        )
        diff = ralph_loop._get_accumulated_diff("abc123")
        assert "diff --git" in diff
        assert "+new line" in diff

    @patch("architect.features.ralph.subprocess.run")
    def test_returns_empty_on_error(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """_get_accumulated_diff retorna cadena vacia si git falla."""
        mock_subprocess.side_effect = OSError("git not found")
        diff = ralph_loop._get_accumulated_diff("abc123")
        assert diff == ""

    @patch("architect.features.ralph.subprocess.run")
    def test_calls_git_diff_with_ref(
        self, mock_subprocess, ralph_loop: RalphLoop
    ) -> None:
        """_get_accumulated_diff llama a git diff con la referencia correcta."""
        mock_subprocess.return_value = MagicMock(stdout="", returncode=0)
        ralph_loop._get_accumulated_diff("initial_abc123")

        mock_subprocess.assert_called_once_with(
            ["git", "diff", "initial_abc123"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=ralph_loop.workspace_root,
        )


# ── Tests: Integracion end-to-end ───────────────────────────────────────


class TestRalphLoopIntegration:
    """Tests de integracion para el flujo completo del Ralph Loop."""

    @patch("architect.features.ralph.subprocess.run")
    def test_full_flow_3_iterations(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """Flujo completo: 2 fallos + 1 exito en 3 iteraciones."""
        subprocess_calls = []

        def subprocess_side_effect(*args, **kwargs):
            subprocess_calls.append((args, kwargs))
            cmd = args[0] if args else kwargs.get("args", "")

            # git rev-parse HEAD
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            # git diff
            if isinstance(cmd, list) and "diff" in cmd:
                return MagicMock(stdout="diff --git a/fix.py\n+fixed", returncode=0)
            # shell checks
            if kwargs.get("shell"):
                # Falla en iteraciones 1 y 2, pasa en 3
                check_num = sum(1 for c in subprocess_calls if c[1].get("shell"))
                if check_num <= 2:
                    return MagicMock(stdout="FAIL", stderr="test error", returncode=1)
                return MagicMock(stdout="OK", stderr="", returncode=0)
            return MagicMock(stdout="", returncode=0)

        mock_subprocess.side_effect = subprocess_side_effect

        iter_count = 0

        def factory(**kwargs):
            nonlocal iter_count
            iter_count += 1
            if iter_count < 3:
                return MockAgent(MockAgentState(
                    final_output="Working on it", steps=3, cost=0.02
                ))
            return MockAgent(MockAgentState(
                final_output="All fixed. COMPLETE", steps=5, cost=0.03
            ))

        config = RalphConfig(
            task="Fix the failing tests",
            checks=["pytest tests/"],
            max_iterations=10,
        )
        loop = RalphLoop(
            config=config, agent_factory=factory, workspace_root=str(workspace)
        )
        result = loop.run()

        assert result.success is True
        assert result.total_iterations == 3
        assert result.stop_reason == "all_checks_passed"
        assert result.total_cost > 0
        assert result.total_duration > 0

        # Progress file deberia existir
        progress = workspace / ".architect" / "ralph-progress.md"
        assert progress.exists()
        content = progress.read_text(encoding="utf-8")
        assert "Failed" in content  # Iteraciones 1 y 2
        assert "Passed" in content  # Iteracion 3

    @patch("architect.features.ralph.subprocess.run")
    def test_all_iterations_fail(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """Si todas las iteraciones fallan, stop_reason es max_iterations."""
        mock_subprocess.return_value = MagicMock(
            stdout="FAIL", stderr="error", returncode=1
        )

        config = RalphConfig(task="Fix", checks=["false"], max_iterations=2)
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(
                MockAgentState(final_output="nope", steps=1, cost=0.01)
            ),
            workspace_root=str(workspace),
        )
        result = loop.run()

        assert result.success is False
        assert result.stop_reason == "max_iterations"
        assert result.total_iterations == 2
        assert len(result.iterations) == 2
        assert all(not it.all_checks_passed for it in result.iterations)


# ── Tests: Worktree support ─────────────────────────────────────────────


class TestRalphLoopResultWorktree:
    """Tests para worktree_path en RalphLoopResult."""

    def test_worktree_path_default_empty(self) -> None:
        """worktree_path es cadena vacía por defecto."""
        result = RalphLoopResult()
        assert result.worktree_path == ""

    def test_worktree_path_set(self) -> None:
        """worktree_path se puede establecer."""
        result = RalphLoopResult(worktree_path="/tmp/worktree")
        assert result.worktree_path == "/tmp/worktree"


class TestWorktreeConstants:
    """Tests para las constantes de worktree."""

    def test_worktree_dir(self) -> None:
        """WORKTREE_DIR tiene el valor esperado."""
        assert WORKTREE_DIR == ".architect-ralph-worktree"

    def test_worktree_branch(self) -> None:
        """WORKTREE_BRANCH tiene el valor esperado."""
        assert WORKTREE_BRANCH == "architect/ralph-loop"


class TestCreateWorktree:
    """Tests para RalphLoop._create_worktree."""

    @patch("architect.features.ralph.subprocess.run")
    def test_create_worktree_success(self, mock_subprocess, workspace: Path) -> None:
        """_create_worktree retorna el path del worktree si git tiene éxito."""
        mock_subprocess.return_value = MagicMock(
            stdout="", stderr="", returncode=0
        )

        config = RalphConfig(task="Fix", checks=["pytest"], use_worktree=True)
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        result = loop._create_worktree()

        expected_path = str(workspace / WORKTREE_DIR)
        assert result == expected_path

    @patch("architect.features.ralph.subprocess.run")
    def test_create_worktree_calls_git_commands(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """_create_worktree llama a git worktree add con los argumentos correctos."""
        mock_subprocess.return_value = MagicMock(
            stdout="", stderr="", returncode=0
        )

        config = RalphConfig(task="Fix", checks=["pytest"], use_worktree=True)
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )
        loop._create_worktree()

        # Debe haber llamado: branch -D (cleanup), worktree add
        calls = mock_subprocess.call_args_list
        # Buscar la llamada a worktree add
        worktree_add_call = None
        for c in calls:
            args = c[0][0] if c[0] else c.kwargs.get("args", [])
            if isinstance(args, list) and "worktree" in args and "add" in args:
                worktree_add_call = c
                break

        assert worktree_add_call is not None
        cmd = worktree_add_call[0][0]
        assert "-b" in cmd
        assert WORKTREE_BRANCH in cmd
        assert "HEAD" in cmd

    @patch("architect.features.ralph.subprocess.run")
    def test_create_worktree_failure(self, mock_subprocess, workspace: Path) -> None:
        """_create_worktree retorna None si git worktree add falla."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
                return MagicMock(stdout="", stderr="error: already exists", returncode=128)
            return MagicMock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = side_effect

        config = RalphConfig(task="Fix", checks=["pytest"], use_worktree=True)
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        result = loop._create_worktree()
        assert result is None

    @patch("architect.features.ralph.subprocess.run")
    def test_create_worktree_exception(self, mock_subprocess, workspace: Path) -> None:
        """_create_worktree retorna None si ocurre una excepcion."""
        mock_subprocess.side_effect = OSError("git not found")

        config = RalphConfig(task="Fix", checks=["pytest"], use_worktree=True)
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        result = loop._create_worktree()
        assert result is None

    @patch("architect.features.ralph.subprocess.run")
    def test_create_worktree_cleans_existing(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """_create_worktree limpia worktree existente antes de crear uno nuevo."""
        # Simular que el directorio worktree ya existe
        worktree_dir = workspace / WORKTREE_DIR
        worktree_dir.mkdir()

        mock_subprocess.return_value = MagicMock(
            stdout="", stderr="", returncode=0
        )

        config = RalphConfig(task="Fix", checks=["pytest"], use_worktree=True)
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )
        loop._create_worktree()

        # Debe haber llamado a worktree remove primero
        calls = mock_subprocess.call_args_list
        remove_call = None
        for c in calls:
            cmd = c[0][0] if c[0] else []
            if isinstance(cmd, list) and "worktree" in cmd and "remove" in cmd:
                remove_call = c
                break

        assert remove_call is not None


class TestCleanupWorktree:
    """Tests para RalphLoop.cleanup_worktree."""

    @patch("architect.features.ralph.subprocess.run")
    def test_cleanup_calls_remove_and_branch_delete(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """cleanup_worktree llama a worktree remove y branch -D."""
        # Crear el worktree dir para que exista
        worktree_dir = workspace / WORKTREE_DIR
        worktree_dir.mkdir()

        # Mock: git rev-parse --git-common-dir returns .git
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else []
            if isinstance(cmd, list) and "--git-common-dir" in cmd:
                return MagicMock(stdout=".git", returncode=0)
            if isinstance(cmd, list) and "worktree" in cmd and "remove" in cmd:
                return MagicMock(stdout="", returncode=0)
            return MagicMock(stdout="", returncode=0)

        mock_subprocess.side_effect = side_effect

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        result = loop.cleanup_worktree()
        assert result is True

        # Verificar que se llamaron los comandos correctos
        cmds_called = [
            c[0][0] for c in mock_subprocess.call_args_list
            if c[0] and isinstance(c[0][0], list)
        ]
        assert any("branch" in cmd and "-D" in cmd for cmd in cmds_called)
        assert any("worktree" in cmd and "prune" in cmd for cmd in cmds_called)

    @patch("architect.features.ralph.subprocess.run")
    def test_cleanup_returns_false_if_no_worktree(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """cleanup_worktree retorna False si no hay worktree para limpiar."""
        mock_subprocess.return_value = MagicMock(
            stdout=".git", stderr="", returncode=0
        )

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config,
            agent_factory=MagicMock(),
            workspace_root=str(workspace),
        )

        result = loop.cleanup_worktree()
        assert result is False


class TestRunWithWorktree:
    """Tests para RalphLoop.run con use_worktree=True."""

    @patch("architect.features.ralph.subprocess.run")
    def test_run_with_worktree_sets_workspace(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() con use_worktree cambia workspace_root al worktree."""
        worktree_path = workspace / WORKTREE_DIR

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])

            # git worktree add — simulate success
            if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
                worktree_path.mkdir(exist_ok=True)
                return MagicMock(stdout="", stderr="", returncode=0)
            # git rev-parse HEAD
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            # shell checks (pass)
            if kwargs.get("shell"):
                return MagicMock(stdout="OK", stderr="", returncode=0)
            # Everything else
            return MagicMock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = subprocess_side_effect

        config = RalphConfig(
            task="Fix",
            checks=["pytest"],
            use_worktree=True,
        )

        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(state),
            workspace_root=str(workspace),
        )
        result = loop.run()

        assert result.success is True
        assert result.worktree_path == str(worktree_path)
        # workspace_root debería haberse cambiado al worktree
        assert loop.workspace_root == str(worktree_path)

    @patch("architect.features.ralph.subprocess.run")
    def test_run_with_worktree_passes_workspace_to_factory(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() con use_worktree pasa workspace_root al agent_factory."""
        worktree_path = workspace / WORKTREE_DIR

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
                worktree_path.mkdir(exist_ok=True)
                return MagicMock(stdout="", stderr="", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            if kwargs.get("shell"):
                return MagicMock(stdout="OK", stderr="", returncode=0)
            return MagicMock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = subprocess_side_effect

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(MockAgentState(final_output="COMPLETE", steps=3, cost=0.01))

        config = RalphConfig(
            task="Fix",
            checks=["pytest"],
            use_worktree=True,
        )
        loop = RalphLoop(
            config=config,
            agent_factory=factory,
            workspace_root=str(workspace),
        )
        loop.run()

        # Factory must receive workspace_root pointing to the worktree
        assert len(factory_calls) >= 1
        assert factory_calls[0]["workspace_root"] == str(worktree_path)

    @patch("architect.features.ralph.subprocess.run")
    def test_run_without_worktree_passes_original_workspace_to_factory(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() sin use_worktree pasa workspace_root original al factory."""
        mock_subprocess.return_value = MagicMock(
            stdout="abc123\n", stderr="", returncode=0
        )

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(MockAgentState(final_output="COMPLETE", steps=3, cost=0.01))

        config = RalphConfig(task="Fix", checks=["pytest"])
        loop = RalphLoop(
            config=config,
            agent_factory=factory,
            workspace_root=str(workspace),
        )
        loop.run()

        # Factory must receive the original workspace_root
        assert len(factory_calls) >= 1
        assert factory_calls[0]["workspace_root"] == str(workspace)

    @patch("architect.features.ralph.subprocess.run")
    def test_run_without_worktree_no_worktree_path(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() sin use_worktree deja worktree_path vacío."""
        mock_subprocess.return_value = MagicMock(
            stdout="abc123\n", stderr="", returncode=0
        )

        config = RalphConfig(task="Fix", checks=["pytest"])
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(state),
            workspace_root=str(workspace),
        )
        result = loop.run()

        assert result.worktree_path == ""

    @patch("architect.features.ralph.subprocess.run")
    def test_run_worktree_failure_falls_back(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() con worktree que falla continúa en workspace original."""
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            # git worktree add fails
            if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
                return MagicMock(stdout="", stderr="fatal error", returncode=128)
            # git rev-parse HEAD
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            # shell checks pass
            if kwargs.get("shell"):
                return MagicMock(stdout="OK", stderr="", returncode=0)
            return MagicMock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = subprocess_side_effect

        config = RalphConfig(
            task="Fix",
            checks=["pytest"],
            use_worktree=True,
        )
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(state),
            workspace_root=str(workspace),
        )
        result = loop.run()

        # Debe completarse en el workspace original
        assert result.success is True
        assert result.worktree_path == ""
        assert loop.workspace_root == str(workspace)

    @patch("architect.features.ralph.subprocess.run")
    def test_run_worktree_progress_file_in_worktree(
        self, mock_subprocess, workspace: Path
    ) -> None:
        """run() con worktree pone el progress file dentro del worktree."""
        worktree_path = workspace / WORKTREE_DIR

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
                worktree_path.mkdir(exist_ok=True)
                return MagicMock(stdout="", stderr="", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            if kwargs.get("shell"):
                return MagicMock(stdout="OK", stderr="", returncode=0)
            return MagicMock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = subprocess_side_effect

        config = RalphConfig(task="Fix", checks=["echo ok"], use_worktree=True)
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)
        loop = RalphLoop(
            config=config,
            agent_factory=lambda **kw: MockAgent(state),
            workspace_root=str(workspace),
        )
        loop.run()

        # Progress file debe estar dentro del worktree
        expected = worktree_path / ".architect" / "ralph-progress.md"
        assert loop.progress_file == expected


# ── Tests: HUMAN Logging ──────────────────────────────────────────────────


class TestRalphHumanLogging:
    """Tests para HUMAN-level logging en RalphLoop."""

    @staticmethod
    def _extract_human_calls(mock_hlog: MagicMock, event_name: str) -> list[dict]:
        from architect.logging.levels import HUMAN as LVL
        results = []
        for c in mock_hlog.log.call_args_list:
            args = c[0]
            if len(args) >= 2 and args[0] == LVL and isinstance(args[1], dict):
                if args[1].get("event") == event_name:
                    results.append(args[1])
        return results

    def test_iteration_start_emitted(self, workspace: Path) -> None:
        """ralph.iteration_start se emite al inicio de cada iteracion."""
        config = RalphConfig(task="Fix", checks=["echo ok"], max_iterations=2)
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)

        with patch("subprocess.run") as mock_run, \
             patch("architect.features.ralph._hlog") as mock_hlog:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n", stderr="")
            loop = RalphLoop(config=config, agent_factory=lambda **kw: MockAgent(state), workspace_root=str(workspace))
            loop.run()

        starts = self._extract_human_calls(mock_hlog, "ralph.iteration_start")
        assert len(starts) >= 1
        assert starts[0]["iteration"] == 1
        assert starts[0]["max_iterations"] == 2
        assert starts[0]["check_cmd"] == "echo ok"

    def test_checks_result_emitted(self, workspace: Path) -> None:
        """ralph.checks_result se emite con conteo de checks."""
        config = RalphConfig(task="Fix", checks=["echo ok"], max_iterations=2)
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)

        with patch("subprocess.run") as mock_run, \
             patch("architect.features.ralph._hlog") as mock_hlog:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n", stderr="")
            loop = RalphLoop(config=config, agent_factory=lambda **kw: MockAgent(state), workspace_root=str(workspace))
            loop.run()

        checks = self._extract_human_calls(mock_hlog, "ralph.checks_result")
        assert len(checks) >= 1
        assert "passed" in checks[0]
        assert "total" in checks[0]

    def test_iteration_done_emitted(self, workspace: Path) -> None:
        """ralph.iteration_done se emite despues de cada iteracion."""
        config = RalphConfig(task="Fix", checks=["echo ok"], max_iterations=2)
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)

        with patch("subprocess.run") as mock_run, \
             patch("architect.features.ralph._hlog") as mock_hlog:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n", stderr="")
            loop = RalphLoop(config=config, agent_factory=lambda **kw: MockAgent(state), workspace_root=str(workspace))
            loop.run()

        dones = self._extract_human_calls(mock_hlog, "ralph.iteration_done")
        assert len(dones) >= 1
        assert dones[0]["iteration"] == 1
        assert "status" in dones[0]
        assert "cost" in dones[0]
        assert "duration" in dones[0]

    def test_complete_emitted(self, workspace: Path) -> None:
        """ralph.complete se emite al terminar el loop."""
        config = RalphConfig(task="Fix", checks=["echo ok"], max_iterations=2)
        state = MockAgentState(final_output="COMPLETE", steps=3, cost=0.01)

        with patch("subprocess.run") as mock_run, \
             patch("architect.features.ralph._hlog") as mock_hlog:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n", stderr="")
            loop = RalphLoop(config=config, agent_factory=lambda **kw: MockAgent(state), workspace_root=str(workspace))
            loop.run()

        completes = self._extract_human_calls(mock_hlog, "ralph.complete")
        assert len(completes) == 1
        assert "total_iterations" in completes[0]
        assert "status" in completes[0]
        assert "total_cost" in completes[0]


class TestHumanFormatterRalph:
    """Tests para HumanFormatter con eventos ralph.*."""

    def test_iteration_start_banner(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.iteration_start", iteration=1, max_iterations=5, check_cmd="pytest tests/",
        )
        assert result is not None
        assert "1/5" in result
        assert "pytest tests/" in result
        assert "━" in result

    def test_checks_result_all_passed(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.checks_result", iteration=1, passed=3, total=3, all_passed=True,
        )
        assert result is not None
        assert "3/3" in result
        assert "✓" in result

    def test_checks_result_some_failed(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.checks_result", iteration=1, passed=2, total=5, all_passed=False,
        )
        assert result is not None
        assert "2/5" in result
        assert "✓" not in result

    def test_iteration_done_passed(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.iteration_done", iteration=2, status="passed", cost=0.0234, duration=45.2,
        )
        assert result is not None
        assert "✓" in result
        assert "$0.0234" in result
        assert "45.2s" in result

    def test_iteration_done_failed(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.iteration_done", iteration=1, status="failed", cost=0.01, duration=10.0,
        )
        assert result is not None
        assert "✗" in result
        assert "failed" in result

    def test_complete_success(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.complete", total_iterations=3, status="success", total_cost=0.0423,
        )
        assert result is not None
        assert "3 iterations" in result
        assert "success" in result
        assert "$0.0423" in result

    def test_complete_max_iterations(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "ralph.complete", total_iterations=25, status="max_iterations", total_cost=1.5,
        )
        assert result is not None
        assert "25 iterations" in result
        assert "⚠️" in result


class TestHumanLogRalph:
    """Tests para HumanLog helpers de Ralph."""

    def test_ralph_iteration_start(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.ralph_iteration_start(1, 5, "pytest tests/")
        mock_logger.log.assert_called_once_with(
            LVL, "ralph.iteration_start",
            iteration=1, max_iterations=5, check_cmd="pytest tests/",
        )

    def test_ralph_checks_result(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.ralph_checks_result(1, 3, 5, False)
        mock_logger.log.assert_called_once_with(
            LVL, "ralph.checks_result",
            iteration=1, passed=3, total=5, all_passed=False,
        )

    def test_ralph_iteration_done(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.ralph_iteration_done(2, "passed", 0.05, 30.0)
        mock_logger.log.assert_called_once_with(
            LVL, "ralph.iteration_done",
            iteration=2, status="passed", cost=0.05, duration=30.0,
        )

    def test_ralph_complete(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.ralph_complete(3, "success", 0.15)
        mock_logger.log.assert_called_once_with(
            LVL, "ralph.complete",
            total_iterations=3, status="success", total_cost=0.15,
        )
