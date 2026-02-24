"""
Tests para Pipeline Mode v4-C3.

Cubre:
- PipelineStep (dataclass, defaults y custom values)
- PipelineConfig (dataclass, variables)
- PipelineStepResult (dataclass, defaults)
- PipelineRunner._resolve_vars (sustitución de variables {{name}})
- PipelineRunner._eval_condition (truthy/falsy)
- PipelineRunner.run (ejecución completa, from_step, dry_run, condiciones, output_var)
- PipelineRunner._run_checks (checks pasando y fallando)
- PipelineRunner._create_checkpoint (git commands)
- PipelineRunner.get_plan_summary (formato de salida)
- PipelineRunner.from_yaml (carga YAML, variables, errores)
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from architect.features.pipelines import (
    PipelineConfig,
    PipelineRunner,
    PipelineStep,
    PipelineStepResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_agent_result(
    status: str = "success",
    final_output: str = "done",
    cost: float = 0.01,
) -> SimpleNamespace:
    """Crea un resultado de agente simulado."""
    cost_tracker = SimpleNamespace(total_cost_usd=cost)
    return SimpleNamespace(
        status=status,
        final_output=final_output,
        cost_tracker=cost_tracker,
    )


def _make_factory(
    result: Any | None = None,
    side_effect: list[Any] | Exception | None = None,
) -> MagicMock:
    """Crea un agent_factory mock.

    El factory devuelve un agente cuyo .run() retorna result.
    """
    factory = MagicMock()
    agent = MagicMock()
    if side_effect is not None:
        if isinstance(side_effect, Exception):
            agent.run.side_effect = side_effect
        else:
            agent.run.side_effect = side_effect
    else:
        agent.run.return_value = result or _make_agent_result()
    factory.return_value = agent
    return factory


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal."""
    return tmp_path


@pytest.fixture
def simple_config() -> PipelineConfig:
    """Config con dos pasos simples."""
    return PipelineConfig(
        name="test-pipeline",
        steps=[
            PipelineStep(name="step-1", agent="build", prompt="Do step 1"),
            PipelineStep(name="step-2", agent="review", prompt="Do step 2"),
        ],
    )


@pytest.fixture
def config_with_vars() -> PipelineConfig:
    """Config con variables y output_var."""
    return PipelineConfig(
        name="var-pipeline",
        steps=[
            PipelineStep(
                name="analyze",
                agent="plan",
                prompt="Analyze {{target}}",
                output_var="analysis",
            ),
            PipelineStep(
                name="implement",
                agent="build",
                prompt="Implement based on: {{analysis}}",
            ),
        ],
        variables={"target": "src/main.py"},
    )


@pytest.fixture
def config_with_conditions() -> PipelineConfig:
    """Config con condiciones en pasos."""
    return PipelineConfig(
        name="cond-pipeline",
        steps=[
            PipelineStep(name="always", agent="build", prompt="Always runs"),
            PipelineStep(
                name="skip-me",
                agent="build",
                prompt="Should be skipped",
                condition="false",
            ),
            PipelineStep(
                name="run-me",
                agent="build",
                prompt="Should run",
                condition="true",
            ),
        ],
    )


@pytest.fixture
def config_with_checks() -> PipelineConfig:
    """Config con checks en un paso."""
    return PipelineConfig(
        name="check-pipeline",
        steps=[
            PipelineStep(
                name="build-and-test",
                agent="build",
                prompt="Build the project",
                checks=["echo ok", "exit 0"],
            ),
        ],
    )


@pytest.fixture
def config_with_checkpoint() -> PipelineConfig:
    """Config con checkpoint habilitado."""
    return PipelineConfig(
        name="checkpoint-pipeline",
        steps=[
            PipelineStep(
                name="critical-step",
                agent="build",
                prompt="Do something critical",
                checkpoint=True,
            ),
        ],
    )


# ── Tests: PipelineStep ─────────────────────────────────────────────────


class TestPipelineStep:
    """Tests para PipelineStep dataclass."""

    def test_defaults(self) -> None:
        """PipelineStep tiene defaults razonables."""
        step = PipelineStep(name="test")
        assert step.name == "test"
        assert step.agent == "build"
        assert step.prompt == ""
        assert step.model is None
        assert step.checkpoint is False
        assert step.condition is None
        assert step.output_var is None
        assert step.checks == []
        assert step.timeout is None

    def test_custom_values(self) -> None:
        """PipelineStep acepta valores custom."""
        step = PipelineStep(
            name="deploy",
            agent="review",
            prompt="Deploy to production",
            model="gpt-4o",
            checkpoint=True,
            condition="{{deploy_enabled}}",
            output_var="deploy_result",
            checks=["pytest", "mypy src/"],
            timeout=300,
        )
        assert step.name == "deploy"
        assert step.agent == "review"
        assert step.prompt == "Deploy to production"
        assert step.model == "gpt-4o"
        assert step.checkpoint is True
        assert step.condition == "{{deploy_enabled}}"
        assert step.output_var == "deploy_result"
        assert step.checks == ["pytest", "mypy src/"]
        assert step.timeout == 300

    def test_checks_is_independent_list(self) -> None:
        """Cada PipelineStep tiene su propia lista de checks."""
        step1 = PipelineStep(name="a")
        step2 = PipelineStep(name="b")
        step1.checks.append("pytest")
        assert step2.checks == []


# ── Tests: PipelineConfig ────────────────────────────────────────────────


class TestPipelineConfig:
    """Tests para PipelineConfig dataclass."""

    def test_minimal(self) -> None:
        """PipelineConfig con campos mínimos."""
        config = PipelineConfig(name="test", steps=[])
        assert config.name == "test"
        assert config.steps == []
        assert config.variables == {}

    def test_with_variables(self) -> None:
        """PipelineConfig con variables iniciales."""
        config = PipelineConfig(
            name="test",
            steps=[PipelineStep(name="s1")],
            variables={"foo": "bar", "baz": "qux"},
        )
        assert config.variables["foo"] == "bar"
        assert config.variables["baz"] == "qux"
        assert len(config.steps) == 1

    def test_variables_independent(self) -> None:
        """Cada PipelineConfig tiene su propio dict de variables."""
        c1 = PipelineConfig(name="a", steps=[])
        c2 = PipelineConfig(name="b", steps=[])
        c1.variables["key"] = "val"
        assert "key" not in c2.variables


# ── Tests: PipelineStepResult ────────────────────────────────────────────


class TestPipelineStepResult:
    """Tests para PipelineStepResult dataclass."""

    def test_defaults(self) -> None:
        """PipelineStepResult tiene defaults correctos."""
        result = PipelineStepResult(step_name="s1", status="success")
        assert result.step_name == "s1"
        assert result.status == "success"
        assert result.cost == 0.0
        assert result.duration == 0.0
        assert result.checks_passed is True
        assert result.error is None

    def test_custom_values(self) -> None:
        """PipelineStepResult acepta valores custom."""
        result = PipelineStepResult(
            step_name="deploy",
            status="failed",
            cost=0.123,
            duration=45.6,
            checks_passed=False,
            error="Connection timeout",
        )
        assert result.step_name == "deploy"
        assert result.status == "failed"
        assert result.cost == 0.123
        assert result.duration == 45.6
        assert result.checks_passed is False
        assert result.error == "Connection timeout"

    def test_skipped_status(self) -> None:
        """PipelineStepResult puede tener status skipped."""
        result = PipelineStepResult(step_name="opt", status="skipped")
        assert result.status == "skipped"

    def test_dry_run_status(self) -> None:
        """PipelineStepResult puede tener status dry_run."""
        result = PipelineStepResult(step_name="opt", status="dry_run")
        assert result.status == "dry_run"


# ── Tests: PipelineRunner._resolve_vars ──────────────────────────────────


class TestResolveVars:
    """Tests para resolución de variables {{name}}."""

    def test_basic_substitution(self, workspace: Path) -> None:
        """Sustituye una variable simple."""
        config = PipelineConfig(
            name="t",
            steps=[],
            variables={"name": "world"},
        )
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner._resolve_vars("Hello {{name}}!") == "Hello world!"

    def test_missing_variable_unchanged(self, workspace: Path) -> None:
        """Variables no definidas se mantienen sin cambios."""
        config = PipelineConfig(name="t", steps=[], variables={})
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner._resolve_vars("{{missing}}") == "{{missing}}"

    def test_multiple_variables(self, workspace: Path) -> None:
        """Sustituye múltiples variables en el mismo template."""
        config = PipelineConfig(
            name="t",
            steps=[],
            variables={"first": "John", "last": "Doe"},
        )
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        result = runner._resolve_vars("Name: {{first}} {{last}}")
        assert result == "Name: John Doe"

    def test_variable_with_spaces(self, workspace: Path) -> None:
        """Variables con espacios alrededor del nombre se resuelven."""
        config = PipelineConfig(
            name="t",
            steps=[],
            variables={"name": "world"},
        )
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner._resolve_vars("{{ name }}") == "world"

    def test_no_variables_in_template(self, workspace: Path) -> None:
        """Template sin variables se retorna sin cambios."""
        config = PipelineConfig(name="t", steps=[], variables={"x": "y"})
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner._resolve_vars("plain text") == "plain text"

    def test_empty_template(self, workspace: Path) -> None:
        """Template vacío se retorna vacío."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner._resolve_vars("") == ""

    def test_repeated_variable(self, workspace: Path) -> None:
        """La misma variable repetida se sustituye en ambas posiciones."""
        config = PipelineConfig(
            name="t",
            steps=[],
            variables={"x": "A"},
        )
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner._resolve_vars("{{x}} and {{x}}") == "A and A"

    def test_partial_match(self, workspace: Path) -> None:
        """Solo una de dos variables se resuelve si la otra no existe."""
        config = PipelineConfig(
            name="t",
            steps=[],
            variables={"known": "yes"},
        )
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        result = runner._resolve_vars("{{known}} and {{unknown}}")
        assert result == "yes and {{unknown}}"


# ── Tests: PipelineRunner._eval_condition ────────────────────────────────


class TestEvalCondition:
    """Tests para evaluación de condiciones."""

    def _make_runner(
        self, variables: dict[str, str] | None = None, workspace: str = "/tmp"
    ) -> PipelineRunner:
        config = PipelineConfig(
            name="t", steps=[], variables=variables or {}
        )
        return PipelineRunner(config, _make_factory(), workspace)

    def test_true_literal(self) -> None:
        """'true' se evalúa como True."""
        runner = self._make_runner()
        assert runner._eval_condition("true") is True

    def test_yes_literal(self) -> None:
        """'yes' se evalúa como True."""
        runner = self._make_runner()
        assert runner._eval_condition("yes") is True

    def test_one_literal(self) -> None:
        """'1' se evalúa como True."""
        runner = self._make_runner()
        assert runner._eval_condition("1") is True

    def test_false_literal(self) -> None:
        """'false' se evalúa como False."""
        runner = self._make_runner()
        assert runner._eval_condition("false") is False

    def test_no_literal(self) -> None:
        """'no' se evalúa como False."""
        runner = self._make_runner()
        assert runner._eval_condition("no") is False

    def test_zero_literal(self) -> None:
        """'0' se evalúa como False."""
        runner = self._make_runner()
        assert runner._eval_condition("0") is False

    def test_empty_string(self) -> None:
        """String vacío se evalúa como False."""
        runner = self._make_runner()
        assert runner._eval_condition("") is False

    def test_case_insensitive_true(self) -> None:
        """'TRUE' (mayúsculas) se evalúa como True."""
        runner = self._make_runner()
        assert runner._eval_condition("TRUE") is True

    def test_case_insensitive_false(self) -> None:
        """'FALSE' (mayúsculas) se evalúa como False."""
        runner = self._make_runner()
        assert runner._eval_condition("FALSE") is False

    def test_truthy_string(self) -> None:
        """Cualquier string no vacío y no falsy se evalúa como True."""
        runner = self._make_runner()
        assert runner._eval_condition("something") is True

    def test_whitespace_only_is_falsy(self) -> None:
        """String con solo espacios se evalúa como False (strip hace vacío)."""
        runner = self._make_runner()
        assert runner._eval_condition("   ") is False

    def test_variable_resolution_true(self) -> None:
        """Condición con variable que resuelve a 'true'."""
        runner = self._make_runner(variables={"enabled": "true"})
        assert runner._eval_condition("{{enabled}}") is True

    def test_variable_resolution_false(self) -> None:
        """Condición con variable que resuelve a 'false'."""
        runner = self._make_runner(variables={"enabled": "false"})
        assert runner._eval_condition("{{enabled}}") is False

    def test_unresolved_variable_is_truthy(self) -> None:
        """Variable no resuelta queda como '{{var}}' que es truthy."""
        runner = self._make_runner()
        assert runner._eval_condition("{{undefined}}") is True


# ── Tests: PipelineRunner.run ────────────────────────────────────────────


class TestPipelineRun:
    """Tests para ejecución del pipeline."""

    def test_executes_all_steps(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """run() ejecuta todos los pasos del pipeline."""
        factory = _make_factory()
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run()

        assert len(results) == 2
        assert results[0].step_name == "step-1"
        assert results[1].step_name == "step-2"
        assert factory.call_count == 2

    def test_step_status_from_agent(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """run() propaga el status del agente al resultado del paso."""
        factory = _make_factory(result=_make_agent_result(status="success"))
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run()

        assert results[0].status == "success"
        assert results[1].status == "success"

    def test_from_step_skips_earlier(
        self, simple_config: PipelineConfig, workspace: Path
    ) -> None:
        """run(from_step=...) salta pasos anteriores."""
        factory = _make_factory()
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run(from_step="step-2")

        assert len(results) == 1
        assert results[0].step_name == "step-2"
        assert factory.call_count == 1

    def test_from_step_nonexistent_returns_empty(
        self, simple_config: PipelineConfig, workspace: Path
    ) -> None:
        """run(from_step=...) con paso inexistente retorna lista vacía."""
        factory = _make_factory()
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run(from_step="nonexistent")

        assert results == []
        assert factory.call_count == 0

    def test_condition_false_skips_step(
        self, config_with_conditions: PipelineConfig, workspace: Path
    ) -> None:
        """run() salta pasos cuya condición evalúa a false."""
        factory = _make_factory()
        runner = PipelineRunner(config_with_conditions, factory, str(workspace))
        results = runner.run()

        assert len(results) == 3
        assert results[0].step_name == "always"
        assert results[0].status != "skipped"
        assert results[1].step_name == "skip-me"
        assert results[1].status == "skipped"
        assert results[2].step_name == "run-me"
        assert results[2].status != "skipped"
        # Solo 2 ejecuciones reales (always + run-me)
        assert factory.call_count == 2

    def test_output_var_passes_between_steps(
        self, config_with_vars: PipelineConfig, workspace: Path
    ) -> None:
        """run() almacena output_var y lo pasa al siguiente paso."""
        analysis_result = _make_agent_result(final_output="Found 5 issues")
        impl_result = _make_agent_result(final_output="Fixed all issues")

        factory = _make_factory()
        agent = MagicMock()
        agent.run.side_effect = [analysis_result, impl_result]
        factory.return_value = agent

        runner = PipelineRunner(config_with_vars, factory, str(workspace))
        results = runner.run()

        assert len(results) == 2
        # La variable analysis debe haberse guardado
        assert runner.variables["analysis"] == "Found 5 issues"
        # El segundo paso debe haber recibido el prompt con la variable resuelta
        calls = agent.run.call_args_list
        assert "Found 5 issues" in calls[1][0][0]

    def test_dry_run_no_execution(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """run(dry_run=True) no ejecuta agentes, registra dry_run."""
        factory = _make_factory()
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run(dry_run=True)

        assert len(results) == 2
        assert results[0].status == "dry_run"
        assert results[1].status == "dry_run"
        assert factory.call_count == 0

    def test_step_failure_doesnt_crash(self, workspace: Path) -> None:
        """run() continúa tras un fallo de paso (exception en agent.run)."""
        config = PipelineConfig(
            name="fail-pipeline",
            steps=[
                PipelineStep(name="fail-step", prompt="crash"),
                PipelineStep(name="after-fail", prompt="still runs"),
            ],
        )
        factory = MagicMock()
        agent = MagicMock()
        agent.run.side_effect = [
            RuntimeError("boom"),
            _make_agent_result(status="success"),
        ]
        factory.return_value = agent

        runner = PipelineRunner(config, factory, str(workspace))
        results = runner.run()

        assert len(results) == 2
        assert results[0].status == "failed"
        assert results[0].error == "boom"
        assert results[1].status == "success"

    def test_cost_tracked(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """run() registra el coste de cada paso."""
        factory = _make_factory(result=_make_agent_result(cost=0.05))
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run()

        assert results[0].cost == 0.05
        assert results[1].cost == 0.05

    def test_duration_tracked(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """run() registra la duración de cada paso (>= 0)."""
        factory = _make_factory()
        runner = PipelineRunner(simple_config, factory, str(workspace))
        results = runner.run()

        assert results[0].duration >= 0.0
        assert results[1].duration >= 0.0

    def test_run_passes_agent_and_model(self, workspace: Path) -> None:
        """run() pasa agent y model al factory."""
        config = PipelineConfig(
            name="t",
            steps=[
                PipelineStep(name="s1", agent="plan", model="gpt-4o", prompt="plan it"),
            ],
        )
        factory = _make_factory()
        runner = PipelineRunner(config, factory, str(workspace))
        runner.run()

        factory.assert_called_once_with(agent="plan", model="gpt-4o")

    def test_results_stored_on_runner(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """run() almacena resultados en runner.results."""
        factory = _make_factory()
        runner = PipelineRunner(simple_config, factory, str(workspace))
        returned = runner.run()

        assert runner.results is returned
        assert len(runner.results) == 2

    def test_empty_pipeline(self, workspace: Path) -> None:
        """run() con pipeline sin pasos retorna lista vacía."""
        config = PipelineConfig(name="empty", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        results = runner.run()
        assert results == []


# ── Tests: PipelineRunner._run_checks ────────────────────────────────────


class TestRunChecks:
    """Tests para ejecución de checks."""

    def test_passing_checks(self, workspace: Path) -> None:
        """_run_checks con comandos exitosos retorna passed=True."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args="echo ok", returncode=0, stdout="ok\n", stderr=""
            )
            results = runner._run_checks(["echo ok"])

        assert len(results) == 1
        assert results[0]["passed"] is True
        assert results[0]["name"] == "echo ok"

    def test_failing_checks(self, workspace: Path) -> None:
        """_run_checks con comandos fallidos retorna passed=False."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args="exit 1", returncode=1, stdout="", stderr="error\n"
            )
            results = runner._run_checks(["exit 1"])

        assert len(results) == 1
        assert results[0]["passed"] is False

    def test_timeout_check(self, workspace: Path) -> None:
        """_run_checks con timeout retorna passed=False y output='Timeout'."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("sleep 999", 120)
            results = runner._run_checks(["sleep 999"])

        assert len(results) == 1
        assert results[0]["passed"] is False
        assert results[0]["output"] == "Timeout"

    def test_multiple_checks(self, workspace: Path) -> None:
        """_run_checks ejecuta todos los checks de la lista."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess("c1", 0, "ok", ""),
                subprocess.CompletedProcess("c2", 1, "", "fail"),
                subprocess.CompletedProcess("c3", 0, "ok", ""),
            ]
            results = runner._run_checks(["c1", "c2", "c3"])

        assert len(results) == 3
        assert results[0]["passed"] is True
        assert results[1]["passed"] is False
        assert results[2]["passed"] is True

    def test_check_uses_workspace_cwd(self, workspace: Path) -> None:
        """_run_checks ejecuta comandos en el workspace_root."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess("c", 0, "", "")
            runner._run_checks(["echo test"])

        mock_run.assert_called_once_with(
            "echo test",
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(workspace),
        )

    def test_output_truncated_to_500(self, workspace: Path) -> None:
        """_run_checks trunca output a últimos 500 chars."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        long_output = "x" * 1000
        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                "c", 0, long_output, ""
            )
            results = runner._run_checks(["c"])

        assert len(results[0]["output"]) == 500

    def test_run_with_checks_integration(self, workspace: Path) -> None:
        """run() ejecuta checks del paso y marca checks_passed correctamente."""
        config = PipelineConfig(
            name="t",
            steps=[
                PipelineStep(
                    name="with-checks",
                    prompt="do it",
                    checks=["test_cmd"],
                ),
            ],
        )
        factory = _make_factory()
        runner = PipelineRunner(config, factory, str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess("test_cmd", 0, "ok", "")
            results = runner.run()

        assert len(results) == 1
        assert results[0].checks_passed is True

    def test_run_with_failing_checks_integration(self, workspace: Path) -> None:
        """run() marca checks_passed=False cuando checks fallan."""
        config = PipelineConfig(
            name="t",
            steps=[
                PipelineStep(
                    name="with-checks",
                    prompt="do it",
                    checks=["failing_cmd"],
                ),
            ],
        )
        factory = _make_factory()
        runner = PipelineRunner(config, factory, str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess("failing_cmd", 1, "", "error")
            results = runner.run()

        assert len(results) == 1
        assert results[0].checks_passed is False


# ── Tests: PipelineRunner._create_checkpoint ─────────────────────────────


class TestCreateCheckpoint:
    """Tests para creación de checkpoints git."""

    def test_calls_git_commands(self, workspace: Path) -> None:
        """_create_checkpoint ejecuta git add y git commit."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess("git", 0, "", "")
            runner._create_checkpoint("my-step")

        assert mock_run.call_count == 2
        # Primer call: git add -A
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0] == ["git", "add", "-A"]
        assert first_call[1]["cwd"] == str(workspace)
        # Segundo call: git commit
        second_call = mock_run.call_args_list[1]
        assert second_call[0][0][0] == "git"
        assert second_call[0][0][1] == "commit"
        assert "architect:checkpoint:my-step" in second_call[0][0][3]
        assert "--allow-empty" in second_call[0][0]

    def test_checkpoint_error_handled(self, workspace: Path) -> None:
        """_create_checkpoint no crashea si git falla."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("git not found")
            # No debe lanzar excepción
            runner._create_checkpoint("step")

    def test_run_with_checkpoint_integration(
        self, config_with_checkpoint: PipelineConfig, workspace: Path
    ) -> None:
        """run() llama _create_checkpoint cuando checkpoint=True."""
        factory = _make_factory()
        runner = PipelineRunner(config_with_checkpoint, factory, str(workspace))

        with patch("architect.features.pipelines.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess("git", 0, "", "")
            results = runner.run()

        assert len(results) == 1
        # git add + git commit = 2 calls
        assert mock_run.call_count == 2


# ── Tests: PipelineRunner.get_plan_summary ───────────────────────────────


class TestGetPlanSummary:
    """Tests para generación del resumen del plan."""

    def test_includes_pipeline_name(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary incluye el nombre del pipeline."""
        runner = PipelineRunner(simple_config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "test-pipeline" in summary

    def test_includes_step_count(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary incluye el número de pasos."""
        runner = PipelineRunner(simple_config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "Steps: 2" in summary

    def test_includes_step_names(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary incluye los nombres de los pasos."""
        runner = PipelineRunner(simple_config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "step-1" in summary
        assert "step-2" in summary

    def test_includes_agent_names(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary incluye el agente de cada paso."""
        runner = PipelineRunner(simple_config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "build" in summary
        assert "review" in summary

    def test_includes_variables(self, config_with_vars: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary muestra las variables si las hay."""
        runner = PipelineRunner(config_with_vars, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "Variables:" in summary
        assert "target" in summary

    def test_includes_condition(
        self, config_with_conditions: PipelineConfig, workspace: Path
    ) -> None:
        """get_plan_summary muestra condiciones de los pasos."""
        runner = PipelineRunner(config_with_conditions, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "if:" in summary

    def test_includes_checkpoint_marker(
        self, config_with_checkpoint: PipelineConfig, workspace: Path
    ) -> None:
        """get_plan_summary muestra [checkpoint] para pasos con checkpoint."""
        runner = PipelineRunner(config_with_checkpoint, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "[checkpoint]" in summary

    def test_includes_prompt_preview(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary incluye un preview del prompt."""
        runner = PipelineRunner(simple_config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "Do step 1" in summary
        assert "Do step 2" in summary

    def test_resolves_variables_in_preview(
        self, config_with_vars: PipelineConfig, workspace: Path
    ) -> None:
        """get_plan_summary resuelve variables en el preview del prompt."""
        runner = PipelineRunner(config_with_vars, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "src/main.py" in summary

    def test_empty_pipeline(self, workspace: Path) -> None:
        """get_plan_summary con pipeline vacío muestra 0 steps."""
        config = PipelineConfig(name="empty", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "Steps: 0" in summary

    def test_numbered_steps(self, simple_config: PipelineConfig, workspace: Path) -> None:
        """get_plan_summary numera los pasos empezando en 1."""
        runner = PipelineRunner(simple_config, _make_factory(), str(workspace))
        summary = runner.get_plan_summary()
        assert "1." in summary
        assert "2." in summary


# ── Tests: PipelineRunner.from_yaml ──────────────────────────────────────


class TestFromYaml:
    """Tests para carga de pipelines desde YAML."""

    def test_valid_yaml(self, workspace: Path) -> None:
        """from_yaml carga un pipeline válido."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: my-pipeline
steps:
  - name: analyze
    agent: plan
    prompt: "Analyze the codebase"
  - name: implement
    agent: build
    prompt: "Implement changes"
    model: gpt-4o
    checkpoint: true
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert runner.config.name == "my-pipeline"
        assert len(runner.config.steps) == 2
        assert runner.config.steps[0].name == "analyze"
        assert runner.config.steps[0].agent == "plan"
        assert runner.config.steps[1].model == "gpt-4o"
        assert runner.config.steps[1].checkpoint is True

    def test_cli_variables_override_yaml(self, workspace: Path) -> None:
        """from_yaml merges variables, CLI tiene prioridad sobre YAML."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
variables:
  target: default_target
  extra: yaml_value
steps:
  - name: s1
    prompt: "{{target}}"
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(
            str(yaml_file),
            {"target": "cli_override"},
            factory,
            str(workspace),
        )

        assert runner.variables["target"] == "cli_override"
        assert runner.variables["extra"] == "yaml_value"

    def test_missing_file_raises(self, workspace: Path) -> None:
        """from_yaml lanza FileNotFoundError si el archivo no existe."""
        with pytest.raises(FileNotFoundError, match="Pipeline file not found"):
            PipelineRunner.from_yaml(
                str(workspace / "nonexistent.yaml"), {}, _make_factory()
            )

    def test_invalid_yaml_raises(self, workspace: Path) -> None:
        """from_yaml lanza ValueError si el YAML no es un dict válido."""
        yaml_file = workspace / "bad.yaml"
        yaml_file.write_text("not a mapping", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid pipeline YAML"):
            PipelineRunner.from_yaml(str(yaml_file), {}, _make_factory())

    def test_empty_yaml_raises(self, workspace: Path) -> None:
        """from_yaml lanza ValueError si el YAML está vacío."""
        yaml_file = workspace / "empty.yaml"
        yaml_file.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid pipeline YAML"):
            PipelineRunner.from_yaml(str(yaml_file), {}, _make_factory())

    def test_yaml_with_checks(self, workspace: Path) -> None:
        """from_yaml parsea checks correctamente."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - name: build
    prompt: "Build it"
    checks:
      - "pytest tests/"
      - "mypy src/"
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert len(runner.config.steps[0].checks) == 2
        assert runner.config.steps[0].checks[0] == "pytest tests/"
        assert runner.config.steps[0].checks[1] == "mypy src/"

    def test_yaml_checks_string_to_list(self, workspace: Path) -> None:
        """from_yaml convierte un check string a lista."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - name: build
    prompt: "Build it"
    checks: "pytest"
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert runner.config.steps[0].checks == ["pytest"]

    def test_yaml_with_condition_and_output_var(self, workspace: Path) -> None:
        """from_yaml parsea condition y output_var."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - name: optional
    prompt: "Maybe run"
    condition: "{{do_it}}"
    output_var: result
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        step = runner.config.steps[0]
        assert step.condition == "{{do_it}}"
        assert step.output_var == "result"

    def test_yaml_with_timeout(self, workspace: Path) -> None:
        """from_yaml parsea timeout."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - name: slow
    prompt: "Take your time"
    timeout: 600
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert runner.config.steps[0].timeout == 600

    def test_yaml_defaults_name_from_stem(self, workspace: Path) -> None:
        """from_yaml usa el nombre del archivo como nombre si no se especifica."""
        yaml_file = workspace / "my_workflow.yaml"
        yaml_file.write_text(
            """
steps:
  - name: s1
    prompt: "do something"
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert runner.config.name == "my_workflow"

    def test_yaml_auto_names_steps(self, workspace: Path) -> None:
        """from_yaml auto-genera nombres de pasos si no se especifican."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - prompt: "first thing"
  - prompt: "second thing"
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert runner.config.steps[0].name == "step-1"
        assert runner.config.steps[1].name == "step-2"

    def test_yaml_no_variables_key(self, workspace: Path) -> None:
        """from_yaml funciona sin clave variables en YAML."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - name: s1
    prompt: "do it"
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(
            str(yaml_file), {"cli_var": "val"}, factory, str(workspace)
        )

        assert runner.variables["cli_var"] == "val"

    def test_yaml_skips_non_dict_steps(self, workspace: Path) -> None:
        """from_yaml ignora entradas de steps que no son diccionarios."""
        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(
            """
name: test
steps:
  - name: valid
    prompt: "do it"
  - "just a string"
  - 42
""",
            encoding="utf-8",
        )
        factory = _make_factory()
        runner = PipelineRunner.from_yaml(str(yaml_file), {}, factory, str(workspace))

        assert len(runner.config.steps) == 1
        assert runner.config.steps[0].name == "valid"


# ── Tests: PipelineRunner.__init__ ───────────────────────────────────────


class TestPipelineRunnerInit:
    """Tests para inicialización del PipelineRunner."""

    def test_workspace_default_to_cwd(self) -> None:
        """workspace_root usa cwd si no se especifica."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory())
        assert runner.workspace_root == str(Path.cwd())

    def test_variables_copied_from_config(self, workspace: Path) -> None:
        """Variables se copian del config (no es referencia directa)."""
        config = PipelineConfig(name="t", steps=[], variables={"a": "1"})
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        runner.variables["b"] = "2"
        assert "b" not in config.variables

    def test_results_starts_empty(self, workspace: Path) -> None:
        """results empieza como lista vacía."""
        config = PipelineConfig(name="t", steps=[])
        runner = PipelineRunner(config, _make_factory(), str(workspace))
        assert runner.results == []
