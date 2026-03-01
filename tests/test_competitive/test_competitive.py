"""
Tests para Competitive Eval (v4-D3).

Cubre:
- CompetitiveConfig (campos, defaults)
- CompetitiveResult (campos, defaults)
- CompetitiveEval (init, run con mock ParallelRunner, checks, report, ranking)
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from architect.features.competitive import (
    CompetitiveConfig,
    CompetitiveEval,
    CompetitiveResult,
)
from architect.features.parallel import ParallelConfig, WorkerResult


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Workspace temporal."""
    return tmp_path


@pytest.fixture
def basic_config() -> CompetitiveConfig:
    """Configuración básica de eval competitiva."""
    return CompetitiveConfig(
        task="Implementa la función add(a, b)",
        models=["gpt-4o", "claude-sonnet-4-20250514"],
    )


@pytest.fixture
def config_with_checks() -> CompetitiveConfig:
    """Configuración con checks."""
    return CompetitiveConfig(
        task="Implementa auth JWT",
        models=["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.0-flash"],
        checks=["pytest tests/ -q", "ruff check src/"],
        agent="build",
        max_steps=30,
        budget_per_model=0.50,
        timeout_per_model=300,
    )


@pytest.fixture
def mock_worker_results() -> list[WorkerResult]:
    """Resultados mock de ParallelRunner."""
    return [
        WorkerResult(
            worker_id=1, branch="architect/parallel-1",
            model="gpt-4o", status="success",
            steps=12, cost=0.15, duration=45.2,
            files_modified=["src/auth.py", "tests/test_auth.py"],
            worktree_path="/tmp/wt-1",
        ),
        WorkerResult(
            worker_id=2, branch="architect/parallel-2",
            model="claude-sonnet-4-20250514", status="success",
            steps=8, cost=0.22, duration=38.5,
            files_modified=["src/auth.py"],
            worktree_path="/tmp/wt-2",
        ),
        WorkerResult(
            worker_id=3, branch="architect/parallel-3",
            model="gemini-2.0-flash", status="partial",
            steps=20, cost=0.08, duration=60.1,
            files_modified=["src/auth.py", "src/utils.py"],
            worktree_path="/tmp/wt-3",
        ),
    ]


# -- Tests: CompetitiveConfig ------------------------------------------------


class TestCompetitiveConfig:
    """Tests para CompetitiveConfig."""

    def test_required_fields(self):
        config = CompetitiveConfig(
            task="Test task",
            models=["gpt-4o"],
        )
        assert config.task == "Test task"
        assert config.models == ["gpt-4o"]

    def test_defaults(self):
        config = CompetitiveConfig(task="test", models=["m1"])
        assert config.checks == []
        assert config.agent == "build"
        assert config.max_steps == 50
        assert config.budget_per_model is None
        assert config.timeout_per_model is None

    def test_all_fields(self, config_with_checks):
        assert len(config_with_checks.models) == 3
        assert len(config_with_checks.checks) == 2
        assert config_with_checks.budget_per_model == 0.50
        assert config_with_checks.timeout_per_model == 300


# -- Tests: CompetitiveResult ------------------------------------------------


class TestCompetitiveResult:
    """Tests para CompetitiveResult."""

    def test_fields(self):
        result = CompetitiveResult(
            model="gpt-4o",
            status="success",
            steps=10,
            cost=0.15,
            duration=30.0,
            files_modified=["main.py"],
            checks_passed=2,
            checks_total=3,
        )
        assert result.model == "gpt-4o"
        assert result.checks_passed == 2
        assert result.checks_total == 3

    def test_defaults(self):
        result = CompetitiveResult(
            model="test",
            status="success",
            steps=1,
            cost=0.0,
            duration=1.0,
            files_modified=[],
        )
        assert result.checks_passed == 0
        assert result.checks_total == 0
        assert result.check_details == []
        assert result.worktree_path == ""
        assert result.branch == ""


# -- Tests: CompetitiveEval --------------------------------------------------


class TestCompetitiveEval:
    """Tests para CompetitiveEval."""

    def test_init(self, config_with_checks, workspace):
        ev = CompetitiveEval(config_with_checks, str(workspace))
        assert ev.config is config_with_checks
        assert ev.workspace_root == str(workspace)

    @patch("architect.features.competitive.ParallelRunner")
    def test_run_creates_parallel_config(
        self, MockRunner, basic_config, workspace
    ):
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = [
            WorkerResult(
                worker_id=1, branch="b1", model="gpt-4o",
                status="success", steps=5, cost=0.10,
                duration=20, files_modified=[], worktree_path="",
            ),
            WorkerResult(
                worker_id=2, branch="b2", model="claude-sonnet-4-20250514",
                status="success", steps=8, cost=0.15,
                duration=30, files_modified=[], worktree_path="",
            ),
        ]

        ev = CompetitiveEval(basic_config, str(workspace))
        results = ev.run()

        # Verificar que ParallelRunner fue llamado correctamente
        MockRunner.assert_called_once()
        call_args = MockRunner.call_args
        parallel_config = call_args[0][0]
        assert parallel_config.tasks == [basic_config.task]
        assert parallel_config.workers == 2
        assert parallel_config.models == basic_config.models

        assert len(results) == 2

    @patch("architect.features.competitive.ParallelRunner")
    def test_run_with_checks(
        self, MockRunner, config_with_checks, workspace, mock_worker_results
    ):
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = mock_worker_results

        ev = CompetitiveEval(config_with_checks, str(workspace))

        # Mock subprocess for checks
        with patch("architect.features.competitive.subprocess.run") as mock_sub:
            mock_sub.return_value = Mock(
                returncode=0, stdout="All tests passed", stderr=""
            )
            results = ev.run()

        assert len(results) == 3
        # Checks should have been run for each worker
        for r in results:
            if r.worktree_path:
                assert r.checks_total == 2

    @patch("architect.features.competitive.ParallelRunner")
    def test_run_check_failure(
        self, MockRunner, workspace
    ):
        config = CompetitiveConfig(
            task="Test",
            models=["m1"],
            checks=["pytest tests/"],
        )
        MockRunner.return_value.run.return_value = [
            WorkerResult(
                worker_id=1, branch="b1", model="m1",
                status="success", steps=5, cost=0.1,
                duration=20, files_modified=[], worktree_path="/tmp/wt",
            ),
        ]

        ev = CompetitiveEval(config, str(workspace))
        with patch("architect.features.competitive.subprocess.run") as mock_sub:
            mock_sub.return_value = Mock(
                returncode=1, stdout="FAILED tests", stderr="Error in test"
            )
            results = ev.run()

        assert results[0].checks_passed == 0
        assert results[0].checks_total == 1

    @patch("architect.features.competitive.ParallelRunner")
    def test_run_check_timeout(self, MockRunner, workspace):
        config = CompetitiveConfig(
            task="Test",
            models=["m1"],
            checks=["slow_test"],
        )
        MockRunner.return_value.run.return_value = [
            WorkerResult(
                worker_id=1, branch="b1", model="m1",
                status="success", steps=5, cost=0.1,
                duration=20, files_modified=[], worktree_path="/tmp/wt",
            ),
        ]

        ev = CompetitiveEval(config, str(workspace))
        with patch("architect.features.competitive.subprocess.run") as mock_sub:
            mock_sub.side_effect = subprocess.TimeoutExpired(cmd="slow", timeout=120)
            results = ev.run()

        assert results[0].checks_passed == 0
        assert "Timeout" in str(results[0].check_details[0]["output"])

    def test_run_no_checks_empty_worktree(self, basic_config, workspace):
        with patch("architect.features.competitive.ParallelRunner") as MockRunner:
            MockRunner.return_value.run.return_value = [
                WorkerResult(
                    worker_id=1, branch="b1", model="gpt-4o",
                    status="success", steps=5, cost=0.1,
                    duration=20, files_modified=[], worktree_path="",
                ),
                WorkerResult(
                    worker_id=2, branch="b2", model="claude-sonnet-4-20250514",
                    status="success", steps=3, cost=0.2,
                    duration=15, files_modified=[], worktree_path="",
                ),
            ]

            ev = CompetitiveEval(basic_config, str(workspace))
            results = ev.run()

            for r in results:
                assert r.checks_total == 0
                assert r.check_details == []


# -- Tests: Report Generation ------------------------------------------------


class TestReportGeneration:
    """Tests para generación de reportes."""

    def test_generate_report_basic(self, basic_config, workspace):
        ev = CompetitiveEval(basic_config, str(workspace))
        results = [
            CompetitiveResult(
                model="gpt-4o", status="success",
                steps=10, cost=0.15, duration=30.0,
                files_modified=["main.py"],
            ),
            CompetitiveResult(
                model="claude-sonnet-4-20250514", status="success",
                steps=8, cost=0.22, duration=25.0,
                files_modified=["main.py", "test.py"],
            ),
        ]
        report = ev.generate_report(results)

        assert "Competitive Eval Report" in report
        assert "gpt-4o" in report
        assert "claude-sonnet-4-20250514" in report
        assert "Ranking" in report

    def test_generate_report_with_checks(self, workspace):
        config = CompetitiveConfig(
            task="Test",
            models=["m1", "m2"],
            checks=["pytest", "ruff"],
        )
        ev = CompetitiveEval(config, str(workspace))
        results = [
            CompetitiveResult(
                model="m1", status="success",
                steps=5, cost=0.1, duration=20.0,
                files_modified=["a.py"],
                checks_passed=2, checks_total=2,
                check_details=[
                    {"name": "pytest", "passed": True, "output": ""},
                    {"name": "ruff", "passed": True, "output": ""},
                ],
            ),
            CompetitiveResult(
                model="m2", status="partial",
                steps=15, cost=0.3, duration=45.0,
                files_modified=["a.py"],
                checks_passed=1, checks_total=2,
                check_details=[
                    {"name": "pytest", "passed": True, "output": ""},
                    {"name": "ruff", "passed": False, "output": "3 errors found"},
                ],
            ),
        ]
        report = ev.generate_report(results)

        assert "Detalle de Checks" in report
        assert "FAIL" in report
        assert "3 errors found" in report

    def test_report_with_worktrees(self, basic_config, workspace):
        ev = CompetitiveEval(basic_config, str(workspace))
        results = [
            CompetitiveResult(
                model="gpt-4o", status="success",
                steps=5, cost=0.1, duration=20.0,
                files_modified=[],
                worktree_path="/tmp/wt-1",
                branch="architect/parallel-1",
            ),
        ]
        report = ev.generate_report(results)
        assert "Worktrees" in report
        assert "/tmp/wt-1" in report


# -- Tests: Ranking -----------------------------------------------------------


class TestRanking:
    """Tests para el sistema de ranking."""

    def test_ranking_success_over_failure(self, basic_config, workspace):
        ev = CompetitiveEval(basic_config, str(workspace))
        results = [
            CompetitiveResult(
                model="fail", status="failed",
                steps=5, cost=0.1, duration=20.0,
                files_modified=[],
            ),
            CompetitiveResult(
                model="success", status="success",
                steps=5, cost=0.1, duration=20.0,
                files_modified=[],
            ),
        ]
        ranked = ev._rank_results(results)
        assert ranked[0][0].model == "success"

    def test_ranking_more_checks_better(self, workspace):
        config = CompetitiveConfig(task="t", models=["a", "b"], checks=["c1"])
        ev = CompetitiveEval(config, str(workspace))
        results = [
            CompetitiveResult(
                model="a", status="success",
                steps=10, cost=0.1, duration=20.0,
                files_modified=[],
                checks_passed=1, checks_total=2,
            ),
            CompetitiveResult(
                model="b", status="success",
                steps=10, cost=0.1, duration=20.0,
                files_modified=[],
                checks_passed=2, checks_total=2,
            ),
        ]
        ranked = ev._rank_results(results)
        assert ranked[0][0].model == "b"

    def test_ranking_fewer_steps_better(self, basic_config, workspace):
        ev = CompetitiveEval(basic_config, str(workspace))
        results = [
            CompetitiveResult(
                model="slow", status="success",
                steps=50, cost=0.5, duration=100,
                files_modified=[],
            ),
            CompetitiveResult(
                model="fast", status="success",
                steps=5, cost=0.5, duration=100,
                files_modified=[],
            ),
        ]
        ranked = ev._rank_results(results)
        assert ranked[0][0].model == "fast"

    def test_ranking_lower_cost_better(self, basic_config, workspace):
        ev = CompetitiveEval(basic_config, str(workspace))
        results = [
            CompetitiveResult(
                model="expensive", status="success",
                steps=10, cost=1.0, duration=30,
                files_modified=[],
            ),
            CompetitiveResult(
                model="cheap", status="success",
                steps=10, cost=0.01, duration=30,
                files_modified=[],
            ),
        ]
        ranked = ev._rank_results(results)
        assert ranked[0][0].model == "cheap"

    def test_status_icon(self):
        assert CompetitiveEval._status_icon("success") == "OK"
        assert CompetitiveEval._status_icon("failed") == "FAIL"
        assert CompetitiveEval._status_icon("timeout") == "TIME"
        assert CompetitiveEval._status_icon("unknown") == "?"


# -- Test HUMAN Logging ------------------------------------------------------


class TestCompetitiveHumanLogging:
    """Tests para HUMAN-level logging en CompetitiveEval."""

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

    @patch("architect.features.competitive.ParallelRunner")
    def test_model_done_emitted(self, MockRunner, basic_config, workspace) -> None:
        """competitive.model_done se emite para cada modelo."""
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = [
            WorkerResult(
                worker_id=1, branch="b1", model="gpt-4o",
                status="success", steps=5, cost=0.10,
                duration=20, files_modified=[], worktree_path="",
            ),
            WorkerResult(
                worker_id=2, branch="b2", model="claude-sonnet-4-20250514",
                status="success", steps=8, cost=0.15,
                duration=30, files_modified=[], worktree_path="",
            ),
        ]

        ev = CompetitiveEval(basic_config, str(workspace))

        with patch("architect.features.competitive._hlog") as mock_hlog:
            ev.run()

        dones = self._extract_human_calls(mock_hlog, "competitive.model_done")
        assert len(dones) == 2
        models_logged = {d["model"] for d in dones}
        assert "gpt-4o" in models_logged
        assert "claude-sonnet-4-20250514" in models_logged
        for d in dones:
            assert "rank" in d
            assert "score" in d
            assert "cost" in d

    @patch("architect.features.competitive.ParallelRunner")
    def test_ranking_emitted(self, MockRunner, basic_config, workspace) -> None:
        """competitive.ranking se emite con el ranking final."""
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = [
            WorkerResult(
                worker_id=1, branch="b1", model="gpt-4o",
                status="success", steps=5, cost=0.10,
                duration=20, files_modified=[], worktree_path="",
            ),
        ]

        ev = CompetitiveEval(
            CompetitiveConfig(task="test", models=["gpt-4o"]),
            str(workspace),
        )

        with patch("architect.features.competitive._hlog") as mock_hlog:
            ev.run()

        rankings = self._extract_human_calls(mock_hlog, "competitive.ranking")
        assert len(rankings) == 1
        assert "ranking" in rankings[0]
        assert isinstance(rankings[0]["ranking"], list)


class TestHumanFormatterCompetitive:
    """Tests para HumanFormatter con eventos competitive.*."""

    def test_model_done_first_place(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "competitive.model_done", model="gpt-4o", rank=1, score=85.0,
            cost=0.0456, checks_passed=5, checks_total=5,
        )
        assert result is not None
        assert "gpt-4o" in result
        assert "#1" in result
        assert "score: 85" in result

    def test_model_done_second_place(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "competitive.model_done", model="claude", rank=2, score=72.0,
            cost=0.03, checks_passed=4, checks_total=5,
        )
        assert result is not None
        assert "claude" in result
        assert "#2" in result

    def test_model_done_third_place(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "competitive.model_done", model="gemini", rank=3, score=41.0,
            cost=0.01, checks_passed=2, checks_total=5,
        )
        assert result is not None
        assert "gemini" in result
        assert "#3" in result

    def test_ranking_with_models(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "competitive.ranking",
            ranking=[
                {"model": "gpt-4o", "score": 85, "rank": 1},
                {"model": "claude", "score": 72, "rank": 2},
            ],
        )
        assert result is not None
        assert "gpt-4o" in result
        assert "claude" in result
        assert ">" in result

    def test_ranking_empty(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event("competitive.ranking", ranking=[])
        assert result is not None
        assert "sin resultados" in result


class TestHumanLogCompetitive:
    """Tests para HumanLog helpers de Competitive."""

    def test_competitive_model_done(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.competitive_model_done("gpt-4o", 1, 85.0, 0.05, 5, 5)
        mock_logger.log.assert_called_once_with(
            LVL, "competitive.model_done",
            model="gpt-4o", rank=1, score=85.0, cost=0.05,
            checks_passed=5, checks_total=5,
        )

    def test_competitive_ranking(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        ranking = [{"model": "gpt-4o", "score": 85, "rank": 1}]
        hlog.competitive_ranking(ranking)
        mock_logger.log.assert_called_once_with(
            LVL, "competitive.ranking", ranking=ranking,
        )
