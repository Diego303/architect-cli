"""
Competitive Eval — Runs the same task with multiple models and generates a comparative report.

v4-D3: Wrapper over ParallelRunner that configures one worker per model,
runs the same task on all of them, and collects comparative metrics:
tests passed, lint errors, steps, cost, time.

Requires: ParallelRunner (v4-C2).
"""

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from architect.logging.levels import HUMAN

from .parallel import ParallelConfig, ParallelRunner, WorkerResult

logger = structlog.get_logger()
_hlog = logging.getLogger("architect.competitive")

__all__ = [
    "CompetitiveConfig",
    "CompetitiveResult",
    "CompetitiveEval",
]


@dataclass
class CompetitiveResult:
    """Result of a competitive evaluation for a model.

    Attributes:
        model: Name of the evaluated model.
        status: Final status (success, partial, failed, timeout).
        steps: Steps executed by the agent.
        cost: Cost in USD.
        duration: Duration in seconds.
        files_modified: Files modified by the agent.
        checks_passed: Number of checks that passed.
        checks_total: Total number of checks.
        check_details: Detail of each check {name, passed, output}.
        worktree_path: Path to the worktree with the changes.
        branch: Git branch where the changes are.
    """

    model: str
    status: str
    steps: int
    cost: float
    duration: float
    files_modified: list[str]
    checks_passed: int = 0
    checks_total: int = 0
    check_details: list[dict[str, str | bool]] = field(default_factory=list)
    worktree_path: str = ""
    branch: str = ""


@dataclass
class CompetitiveConfig:
    """Configuration for competitive evaluation.

    Attributes:
        task: Task to execute with all models.
        models: List of models to compare.
        checks: Verification commands to run afterwards.
        agent: Agent to use (default: build).
        max_steps: Maximum steps per model.
        budget_per_model: USD budget per model.
        timeout_per_model: Timeout in seconds per model.
    """

    task: str
    models: list[str]
    checks: list[str] = field(default_factory=list)
    agent: str = "build"
    max_steps: int = 50
    budget_per_model: float | None = None
    timeout_per_model: int | None = None


class CompetitiveEval:
    """Runs competitive evaluation of multiple models.

    Uses ParallelRunner to execute the same task with different models
    in isolated worktrees, then runs checks in each worktree
    and generates a comparative report.
    """

    def __init__(self, config: CompetitiveConfig, workspace_root: str) -> None:
        """Initialize the competitive evaluation.

        Args:
            config: Evaluation configuration.
            workspace_root: Root directory of the repository.
        """
        self.config = config
        self.workspace_root = workspace_root
        self.log = logger.bind(component="competitive_eval")

    def run(self) -> list[CompetitiveResult]:
        """Run the competitive evaluation.

        Returns:
            List of CompetitiveResult, one per model, sorted by model.
        """
        self.log.info(
            "competitive.start",
            models=self.config.models,
            task=self.config.task[:100],
            checks=self.config.checks,
        )

        # Configure ParallelRunner: same task, one worker per model
        parallel_config = ParallelConfig(
            tasks=[self.config.task],
            workers=len(self.config.models),
            models=self.config.models,
            agent=self.config.agent,
            max_steps=self.config.max_steps,
            budget_per_worker=self.config.budget_per_model,
            timeout_per_worker=self.config.timeout_per_model,
        )

        runner = ParallelRunner(parallel_config, self.workspace_root)
        worker_results = runner.run()

        # Run checks in each worktree
        results: list[CompetitiveResult] = []
        for wr in worker_results:
            check_details = self._run_checks_in_worktree(wr.worktree_path)
            passed = sum(1 for c in check_details if c["passed"])

            results.append(CompetitiveResult(
                model=wr.model,
                status=wr.status,
                steps=wr.steps,
                cost=wr.cost,
                duration=wr.duration,
                files_modified=wr.files_modified,
                checks_passed=passed,
                checks_total=len(check_details),
                check_details=check_details,
                worktree_path=wr.worktree_path,
                branch=wr.branch,
            ))

        self.log.info(
            "competitive.complete",
            models=len(results),
            results=[
                {"model": r.model, "status": r.status, "checks": f"{r.checks_passed}/{r.checks_total}"}
                for r in results
            ],
        )

        # Emit HUMAN events with ranking info
        ranked = self._rank_results(results)
        for rank_pos, (r, score) in enumerate(ranked, 1):
            _hlog.log(HUMAN, {
                "event": "competitive.model_done",
                "model": r.model,
                "rank": rank_pos,
                "score": score,
                "cost": r.cost,
                "checks_passed": r.checks_passed,
                "checks_total": r.checks_total,
            })
        _hlog.log(HUMAN, {
            "event": "competitive.ranking",
            "ranking": [
                {"model": r.model, "score": score, "rank": i}
                for i, (r, score) in enumerate(ranked, 1)
            ],
        })

        return sorted(results, key=lambda r: r.model)

    def _run_checks_in_worktree(
        self, worktree_path: str
    ) -> list[dict[str, str | bool]]:
        """Run the configured checks in a worktree.

        Args:
            worktree_path: Path to the worktree where checks are executed.

        Returns:
            List of {name, passed, output} per check.
        """
        if not self.config.checks or not worktree_path:
            return []

        results: list[dict[str, str | bool]] = []
        for check_cmd in self.config.checks:
            try:
                proc = subprocess.run(
                    check_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=worktree_path,
                )
                results.append({
                    "name": check_cmd,
                    "passed": proc.returncode == 0,
                    "output": (proc.stdout + proc.stderr)[-500:],
                })
            except subprocess.TimeoutExpired:
                results.append({
                    "name": check_cmd,
                    "passed": False,
                    "output": "Timeout (120s)",
                })
            except Exception as e:
                results.append({
                    "name": check_cmd,
                    "passed": False,
                    "output": f"Error: {e}",
                })

        return results

    def generate_report(self, results: list[CompetitiveResult]) -> str:
        """Generate a comparative markdown report.

        Args:
            results: List of evaluation results.

        Returns:
            String with the report in markdown format.
        """
        from architect.i18n import t

        lines = [
            t("competitive.report_title"),
            t("competitive.task_label", task=self.config.task),
            t("competitive.models_label", count=len(results)),
        ]

        if self.config.checks:
            lines.append(t("competitive.checks_label", checks=", ".join(self.config.checks)))

        # Results table
        lines.append(t("competitive.results_header"))
        lines.append(
            f"| {t('competitive.col_model')} | {t('competitive.col_status')} "
            f"| {t('competitive.col_steps')} | {t('competitive.col_cost')} "
            f"| {t('competitive.col_time')} | {t('competitive.col_checks')} "
            f"| {t('competitive.col_files')} |"
        )
        lines.append(
            "|--------|--------|-------|-------|--------|"
            "--------|----------|"
        )

        for r in results:
            status_icon = self._status_icon(r.status)
            checks_str = f"{r.checks_passed}/{r.checks_total}" if r.checks_total else "N/A"
            lines.append(
                f"| {r.model} | {status_icon} {r.status} | {r.steps} "
                f"| ${r.cost:.4f} | {r.duration:.1f}s "
                f"| {checks_str} | {len(r.files_modified)} |"
            )

        # Ranking
        lines.append(t("competitive.ranking_header"))
        ranked = self._rank_results(results)
        for i, (r, score) in enumerate(ranked, 1):
            medal = ["1st", "2nd", "3rd"][i - 1] if i <= 3 else f"{i}th"
            lines.append(
                f"{i}. **{medal}** — {r.model} (score: {score:.1f})"
            )

        # Check details per model
        if self.config.checks:
            lines.append(t("competitive.check_details_header"))
            for r in results:
                lines.append(f"\n### {r.model}\n")
                if not r.check_details:
                    lines.append(t("competitive.no_checks_run"))
                    continue
                for check in r.check_details:
                    icon = "pass" if check["passed"] else "FAIL"
                    lines.append(f"- [{icon}] `{check['name']}`")
                    if not check["passed"] and check.get("output"):
                        output = str(check["output"])[:200]
                        lines.append(f"  ```\n  {output}\n  ```")

        # Worktrees for inspection
        lines.append(t("competitive.worktrees_header"))
        lines.append(t("competitive.worktrees_desc"))
        for r in results:
            if r.worktree_path:
                lines.append(f"- **{r.model}**: `{r.worktree_path}` (branch: `{r.branch}`)")

        return "\n".join(lines)

    def _rank_results(
        self, results: list[CompetitiveResult]
    ) -> list[tuple[CompetitiveResult, float]]:
        """Rank results using a composite score.

        Score = (checks_passed/total * 40) + (status_score * 30) +
                (efficiency_score * 20) + (cost_score * 10)

        Args:
            results: List of results.

        Returns:
            List of (result, score) sorted by score descending.
        """
        scored: list[tuple[CompetitiveResult, float]] = []

        max_cost = max((r.cost for r in results if r.cost > 0), default=1.0)
        max_steps = max((r.steps for r in results if r.steps > 0), default=1)

        for r in results:
            # Checks score (0-40)
            if r.checks_total > 0:
                checks_score = (r.checks_passed / r.checks_total) * 40
            else:
                checks_score = 20.0  # Neutral if no checks

            # Status score (0-30)
            status_scores = {
                "success": 30.0,
                "partial": 15.0,
                "failed": 0.0,
                "timeout": 5.0,
            }
            status_score = status_scores.get(r.status, 0.0)

            # Efficiency score (0-20): fewer steps is better
            if r.steps > 0 and max_steps > 0:
                efficiency_score = (1 - r.steps / max_steps) * 20
            else:
                efficiency_score = 0.0

            # Cost score (0-10): lower cost is better
            if r.cost > 0 and max_cost > 0:
                cost_score = (1 - r.cost / max_cost) * 10
            else:
                cost_score = 10.0  # No cost = maximum score

            total = checks_score + status_score + efficiency_score + cost_score
            scored.append((r, round(total, 1)))

        return sorted(scored, key=lambda x: x[1], reverse=True)

    @staticmethod
    def _status_icon(status: str) -> str:
        """Return icon based on status."""
        icons = {
            "success": "OK",
            "partial": "WARN",
            "failed": "FAIL",
            "timeout": "TIME",
        }
        return icons.get(status, "?")
