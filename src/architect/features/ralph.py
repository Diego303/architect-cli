"""
Native Ralph Loop — Automatic iteration until all checks pass.

v4-C1: Killer feature. Each iteration runs an agent with CLEAN context.
Only the following is passed to the agent: original spec, accumulated diff,
errors from the last iteration, and an auto-generated progress.md.

Fundamental principle: the agent does NOT receive the conversation history
from previous iterations. This prevents context contamination and allows
each iteration to approach the problem with a fresh perspective.
"""

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import structlog

from architect.logging.levels import HUMAN

logger = structlog.get_logger()
_hlog = logging.getLogger("architect.ralph")

__all__ = [
    "LoopIteration",
    "RalphConfig",
    "RalphLoop",
    "RalphLoopResult",
]

WORKTREE_DIR = ".architect-ralph-worktree"
WORKTREE_BRANCH = "architect/ralph-loop"


@dataclass
class RalphConfig:
    """Configuration for a Ralph Loop execution."""

    task: str
    checks: list[str]
    spec_file: str | None = None
    completion_tag: str = "COMPLETE"
    max_iterations: int = 25
    max_cost: float | None = None
    max_time: int | None = None
    agent: str = "build"
    model: str | None = None
    use_worktree: bool = False


@dataclass
class LoopIteration:
    """Result of a single Ralph Loop iteration."""

    iteration: int
    steps_taken: int
    cost: float
    duration: float
    check_results: list[dict[str, Any]]
    all_checks_passed: bool
    completion_tag_found: bool
    error: str | None = None


@dataclass
class RalphLoopResult:
    """Complete result of the Ralph Loop."""

    iterations: list[LoopIteration] = field(default_factory=list)
    total_cost: float = 0.0
    total_duration: float = 0.0
    success: bool = False
    stop_reason: str = ""
    worktree_path: str = ""

    @property
    def total_iterations(self) -> int:
        """Total number of completed iterations."""
        return len(self.iterations)


# Type alias for the agent factory callable.
# The factory receives keyword arguments and returns an object with a .run(prompt) method
# that returns an AgentState-like object.
AgentFactory = Callable[..., Any]


class RalphLoop:
    """Native implementation of the Ralph Wiggum Loop.

    Each iteration runs the agent with CLEAN context.
    Only the following is passed to the agent:
    - The original spec/task
    - The accumulated diff from previous iterations
    - The errors from the last iteration
    - An auto-generated progress.md
    """

    def __init__(
        self,
        config: RalphConfig,
        agent_factory: AgentFactory,
        workspace_root: str | None = None,
    ):
        """Initialize the Ralph Loop.

        Args:
            config: Loop configuration.
            agent_factory: Callable that creates a fresh AgentLoop.
                Receives kwargs: agent, model. Returns an object with .run(prompt) -> AgentState.
            workspace_root: Root directory of the workspace. None = cwd.
        """
        self.config = config
        self.agent_factory = agent_factory
        self.workspace_root = workspace_root or str(Path.cwd())
        self.iterations: list[LoopIteration] = []
        self.progress_file = Path(self.workspace_root) / ".architect" / "ralph-progress.md"
        self.log = logger.bind(component="ralph_loop")

    def run(self) -> RalphLoopResult:
        """Run the complete loop.

        If use_worktree is enabled, creates an isolated git worktree
        and runs all iterations there. The worktree is NOT cleaned up
        automatically — the user must inspect it and merge.

        Returns:
            RalphLoopResult with all iterations and metrics.
        """
        start_time = time.time()
        total_cost = 0.0
        result = RalphLoopResult()

        # Worktree: create isolated environment if requested
        original_workspace = self.workspace_root
        if self.config.use_worktree:
            worktree_path = self._create_worktree()
            if worktree_path:
                self.workspace_root = worktree_path
                self.progress_file = Path(worktree_path) / ".architect" / "ralph-progress.md"
                result.worktree_path = worktree_path
                self.log.info("ralph.worktree_active", path=worktree_path)
            else:
                self.log.warning("ralph.worktree_failed_fallback")

        # Capture initial git state
        initial_ref = self._get_current_ref()

        for i in range(1, self.config.max_iterations + 1):
            self.log.info(
                "ralph.iteration_start",
                iteration=i,
                max=self.config.max_iterations,
            )
            _hlog.log(HUMAN, {
                "event": "ralph.iteration_start",
                "iteration": i,
                "max_iterations": self.config.max_iterations,
                "check_cmd": self.config.checks[0] if self.config.checks else "",
            })

            # Check global limits
            if self.config.max_cost and total_cost >= self.config.max_cost:
                self.log.info("ralph.budget_exhausted", cost=total_cost)
                result.stop_reason = "budget_exhausted"
                break

            elapsed = time.time() - start_time
            if self.config.max_time and elapsed >= self.config.max_time:
                self.log.info("ralph.timeout", elapsed=elapsed)
                result.stop_reason = "timeout"
                break

            # Build prompt for this iteration
            prompt = self._build_iteration_prompt(i, initial_ref)

            # Run agent with CLEAN context
            iter_start = time.time()
            iteration = self._run_single_iteration(i, prompt)
            iteration.duration = time.time() - iter_start

            self.iterations.append(iteration)
            result.iterations.append(iteration)
            total_cost += iteration.cost

            # Update progress
            self._update_progress(iteration)

            # Log result
            self._log_iteration_result(iteration)
            passed_count = sum(1 for c in iteration.check_results if c["passed"])
            total_count = len(iteration.check_results)
            _hlog.log(HUMAN, {
                "event": "ralph.checks_result",
                "iteration": i,
                "passed": passed_count,
                "total": total_count,
                "all_passed": iteration.all_checks_passed,
            })
            iter_status = "passed" if iteration.all_checks_passed else "failed"
            _hlog.log(HUMAN, {
                "event": "ralph.iteration_done",
                "iteration": i,
                "status": iter_status,
                "cost": iteration.cost,
                "duration": iteration.duration,
            })

            # Finish if checks pass AND tag found
            if iteration.all_checks_passed and iteration.completion_tag_found:
                self.log.info(
                    "ralph.complete",
                    iterations=i,
                    total_cost=total_cost,
                    total_time=time.time() - start_time,
                )
                result.success = True
                result.stop_reason = "all_checks_passed"
                break
            elif iteration.all_checks_passed:
                self.log.info(
                    "ralph.checks_passed_no_tag",
                    iteration=i,
                )
        else:
            # Iterations exhausted
            result.stop_reason = "max_iterations"

        result.total_cost = total_cost
        result.total_duration = time.time() - start_time
        _hlog.log(HUMAN, {
            "event": "ralph.complete",
            "total_iterations": result.total_iterations,
            "status": "success" if result.success else result.stop_reason,
            "total_cost": total_cost,
        })
        return result

    def _run_single_iteration(self, iteration: int, prompt: str) -> LoopIteration:
        """Run a single iteration of the loop.

        Args:
            iteration: Iteration number (1-based).
            prompt: Prompt built for this iteration.

        Returns:
            LoopIteration with the results.
        """
        try:
            agent = self.agent_factory(
                agent=self.config.agent,
                model=self.config.model,
                workspace_root=self.workspace_root,
            )
            agent_result = agent.run(prompt)

            steps = getattr(agent_result, "current_step", 0)
            cost = 0.0
            if hasattr(agent_result, "cost_tracker") and agent_result.cost_tracker:
                cost = agent_result.cost_tracker.total_cost_usd
            final_response = getattr(agent_result, "final_output", "") or ""

            # Run external checks
            check_results = self._run_checks()
            all_passed = all(c["passed"] for c in check_results) if check_results else False

            # Search for completion tag
            tag_found = self.config.completion_tag in final_response

            return LoopIteration(
                iteration=iteration,
                steps_taken=steps,
                cost=cost,
                duration=0.0,  # Overwritten in run()
                check_results=check_results,
                all_checks_passed=all_passed,
                completion_tag_found=tag_found,
            )

        except Exception as e:
            self.log.error("ralph.iteration_error", iteration=iteration, error=str(e))
            return LoopIteration(
                iteration=iteration,
                steps_taken=0,
                cost=0.0,
                duration=0.0,
                check_results=[],
                all_checks_passed=False,
                completion_tag_found=False,
                error=str(e),
            )

    def _build_iteration_prompt(self, iteration: int, initial_ref: str) -> str:
        """Build the prompt for a specific iteration.

        Args:
            iteration: Iteration number (1-based).
            initial_ref: Git reference of the initial state.

        Returns:
            Complete prompt for the agent.
        """
        from architect.i18n import t

        parts: list[str] = []

        # 1. Original task/spec
        if self.config.spec_file:
            spec_path = Path(self.config.spec_file)
            if spec_path.exists():
                spec = spec_path.read_text(encoding="utf-8")
                parts.append(t("ralph.spec_header", spec=spec))
            else:
                parts.append(t("ralph.task_header", task=self.config.task))
        else:
            parts.append(t("ralph.task_header", task=self.config.task))

        # 2. Ralph Loop instructions
        checks_list = "\n".join(f"- `{check}`" for check in self.config.checks)
        parts.append(t(
            "ralph.iteration_instructions",
            iteration=iteration,
            max_iterations=self.config.max_iterations,
            completion_tag=self.config.completion_tag,
            checks_list=checks_list,
        ))

        # 3. Accumulated diff
        if iteration > 1:
            diff = self._get_accumulated_diff(initial_ref)
            if diff:
                truncated = diff[:5000]
                if len(diff) > 5000:
                    truncated += t("ralph.diff_truncated")
                parts.append(t("ralph.previous_diff", diff=truncated))

        # 4. Errors from the previous iteration
        if self.iterations:
            last = self.iterations[-1]
            failed_checks = [c for c in last.check_results if not c["passed"]]
            if failed_checks:
                parts.append(t("ralph.previous_errors_header"))
                for check in failed_checks:
                    output = check.get("output", "")[:2000]
                    parts.append(
                        f"### {check['name']}\n"
                        f"```\n{output}\n```"
                    )
            if last.error:
                parts.append(t("ralph.execution_error_header", error=last.error[:1000]))

        # 5. Progress file
        if self.progress_file.exists():
            progress_content = self.progress_file.read_text(encoding="utf-8")
            if progress_content.strip():
                parts.append(t("ralph.accumulated_progress", content=progress_content))

        return "\n\n".join(parts)

    def _run_checks(self) -> list[dict[str, Any]]:
        """Run the verification commands.

        Returns:
            List of results: {name, passed, output}.
        """
        results: list[dict[str, Any]] = []
        for check_cmd in self.config.checks:
            try:
                proc = subprocess.run(
                    check_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=self.workspace_root,
                )
                results.append({
                    "name": check_cmd,
                    "passed": proc.returncode == 0,
                    "output": (proc.stdout + proc.stderr)[-1000:],
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

    def _get_accumulated_diff(self, initial_ref: str) -> str:
        """Get the accumulated diff since the initial state.

        Args:
            initial_ref: Git reference of the initial state.

        Returns:
            Diff as a string, or empty string on failure.
        """
        try:
            result = subprocess.run(
                ["git", "diff", initial_ref],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.workspace_root,
            )
            return result.stdout
        except Exception:
            return ""

    def _get_current_ref(self) -> str:
        """Capture the current git ref.

        Returns:
            Hash of the current HEAD commit, or 'HEAD' on failure.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.workspace_root,
            )
            return result.stdout.strip() or "HEAD"
        except Exception:
            return "HEAD"

    def _update_progress(self, iteration: LoopIteration) -> None:
        """Update the progress file.

        Args:
            iteration: Iteration result to record.
        """
        from architect.i18n import t

        try:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.progress_file.exists():
                self.progress_file.write_text(
                    t("ralph.progress_title") + t("ralph.progress_auto"),
                    encoding="utf-8",
                )

            status = "Passed" if iteration.all_checks_passed else "Failed"
            lines = [
                t("ralph.progress_iteration", iteration=iteration.iteration),
                t("ralph.progress_status", status=status),
                t("ralph.progress_steps", steps=iteration.steps_taken),
                t("ralph.progress_cost", cost=iteration.cost),
                t("ralph.progress_duration", duration=iteration.duration),
            ]
            if iteration.error:
                lines.append(t("ralph.progress_error", error=iteration.error[:200]))
            for check in iteration.check_results:
                icon = "PASS" if check["passed"] else "FAIL"
                lines.append(f"- [{icon}] {check['name']}\n")
            lines.append("\n")

            with open(self.progress_file, "a", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            self.log.warning("ralph.progress_write_error", error=str(e))

    def _log_iteration_result(self, iteration: LoopIteration) -> None:
        """Human-readable log of the iteration result.

        Args:
            iteration: Iteration result.
        """
        for check in iteration.check_results:
            self.log.info(
                "ralph.check",
                iteration=iteration.iteration,
                name=check["name"],
                passed=check["passed"],
            )
        if iteration.error:
            self.log.error(
                "ralph.iteration_error",
                iteration=iteration.iteration,
                error=iteration.error[:200],
            )

    def _create_worktree(self) -> str | None:
        """Create an isolated git worktree for the loop.

        Creates a worktree at `<workspace>/../.architect-ralph-worktree`
        based on the current HEAD.

        Returns:
            Absolute path to the worktree, or None on failure.
        """
        root = Path(self.workspace_root)
        worktree_path = root / WORKTREE_DIR

        try:
            # Clean up previous worktree if it exists
            if worktree_path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path), "--force"],
                    capture_output=True,
                    cwd=self.workspace_root,
                )

            # Delete old branch if it exists
            subprocess.run(
                ["git", "branch", "-D", WORKTREE_BRANCH],
                capture_output=True,
                cwd=self.workspace_root,
            )

            # Create worktree with new branch from HEAD
            result = subprocess.run(
                [
                    "git", "worktree", "add",
                    "-b", WORKTREE_BRANCH,
                    str(worktree_path),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                cwd=self.workspace_root,
            )
            if result.returncode != 0:
                self.log.error(
                    "ralph.worktree_create_failed",
                    error=result.stderr[:200],
                )
                return None

            self.log.info(
                "ralph.worktree_created",
                path=str(worktree_path),
                branch=WORKTREE_BRANCH,
            )
            return str(worktree_path)

        except Exception as e:
            self.log.error("ralph.worktree_error", error=str(e))
            return None

    def cleanup_worktree(self) -> bool:
        """Clean up the Ralph Loop worktree and branch.

        Returns:
            True if cleaned up successfully.
        """
        root = Path(self.workspace_root)
        # If we are inside the worktree, go up to the original root
        worktree_path = root / WORKTREE_DIR
        if not worktree_path.exists():
            # Try from the parent (in case workspace_root IS the worktree)
            worktree_path = root.parent / WORKTREE_DIR if WORKTREE_DIR in root.name else root / WORKTREE_DIR

        # Find the real repo root (not the worktree)
        repo_root = self.workspace_root
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                capture_output=True,
                text=True,
                cwd=self.workspace_root,
            )
            if result.returncode == 0:
                git_common = Path(result.stdout.strip())
                if git_common.is_absolute():
                    repo_root = str(git_common.parent)
                else:
                    repo_root = str((Path(self.workspace_root) / git_common).resolve().parent)
        except Exception:
            pass

        removed = False
        wt_path = Path(repo_root) / WORKTREE_DIR
        if wt_path.exists():
            result = subprocess.run(
                ["git", "worktree", "remove", str(wt_path), "--force"],
                capture_output=True,
                cwd=repo_root,
            )
            removed = result.returncode == 0

        # Delete branch
        subprocess.run(
            ["git", "branch", "-D", WORKTREE_BRANCH],
            capture_output=True,
            cwd=repo_root,
        )

        # Prune orphan worktrees
        subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True,
            cwd=repo_root,
        )

        if removed:
            self.log.info("ralph.worktree_cleaned")
        return removed

    def cleanup_progress(self) -> None:
        """Delete the progress file."""
        if self.progress_file.exists():
            self.progress_file.unlink()
