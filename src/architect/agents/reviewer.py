"""
Auto-Review Writer/Reviewer — Reviewer agent that inspects post-build changes.

v4-C5: After the builder completes, the reviewer receives ONLY the diff
and the original task (CLEAN context, no builder history).
Only has access to read-only tools. If it finds problems, the builder
performs a fix-pass.
"""

import logging
import subprocess
from typing import Any, Callable

import structlog

from architect.i18n import get_prompt, t
from architect.logging.levels import HUMAN

logger = structlog.get_logger()
_hlog = logging.getLogger("architect.reviewer")

__all__ = [
    "REVIEW_SYSTEM_PROMPT",
    "AutoReviewer",
    "ReviewResult",
]


def _get_review_system_prompt() -> str:
    """Get the review system prompt in the current language."""
    return get_prompt("prompt.review_system")


class _LazyPrompt:
    """Descriptor that resolves the review system prompt lazily.

    Maintains backward compat: code that does
    ``from architect.agents.reviewer import REVIEW_SYSTEM_PROMPT``
    and then uses it as a string will get the current-language version.
    """

    def __str__(self) -> str:
        return _get_review_system_prompt()

    def __repr__(self) -> str:
        return f"<LazyPrompt: {_get_review_system_prompt()[:60]}...>"

    def __contains__(self, item: str) -> bool:
        return item in _get_review_system_prompt()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return _get_review_system_prompt() == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(_get_review_system_prompt())

    def lower(self) -> str:
        return _get_review_system_prompt().lower()

    def strip(self) -> str:
        return _get_review_system_prompt().strip()

    def __len__(self) -> int:
        return len(_get_review_system_prompt())


# Module-level constant that resolves lazily
REVIEW_SYSTEM_PROMPT: Any = _LazyPrompt()

# Type alias for the agent factory callable.
AgentFactory = Callable[..., Any]


class ReviewResult:
    """Result of an auto-review."""

    def __init__(
        self,
        has_issues: bool,
        review_text: str,
        cost: float = 0.0,
    ):
        self.has_issues = has_issues
        self.review_text = review_text
        self.cost = cost


class AutoReviewer:
    """Runs a reviewer agent on the builder's changes.

    The reviewer receives ONLY the diff and the original task — CLEAN context.
    Only has read-only tools (read_file, search_code, grep, list_directory).
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        review_model: str | None = None,
    ):
        self.agent_factory = agent_factory
        self.review_model = review_model
        self.log = logger.bind(component="auto_reviewer")

    def review_changes(self, task: str, git_diff: str) -> ReviewResult:
        """Run review in a clean context.

        Args:
            task: Original task the builder executed.
            git_diff: Diff of changes to review.

        Returns:
            ReviewResult with found issues.
        """
        if not git_diff.strip():
            self.log.info("auto_review.no_diff")
            return ReviewResult(
                has_issues=False,
                review_text=t("reviewer.no_changes"),
            )

        truncated_diff = git_diff[:8000]
        if len(git_diff) > 8000:
            truncated_diff += t("reviewer.diff_truncated")

        prompt = t("reviewer.prompt", task=task, diff=truncated_diff)

        self.log.info(
            "auto_review.start",
            task_preview=task[:60],
            diff_chars=len(git_diff),
        )
        _hlog.log(HUMAN, {
            "event": "reviewer.start",
            "diff_lines": git_diff.count("\n"),
        })

        try:
            agent = self.agent_factory(
                agent="review",
                model=self.review_model,
            )
            result = agent.run(prompt)

            response = getattr(result, "final_output", "") or ""
            cost = 0.0
            if hasattr(result, "cost_tracker") and result.cost_tracker:
                cost = result.cost_tracker.total_cost_usd

            # Detect "no issues" in both languages
            has_issues = (
                "sin issues" not in response.lower()
                and "no issues found" not in response.lower()
            )

            self.log.info(
                "auto_review.complete",
                has_issues=has_issues,
                cost=cost,
            )
            issue_count = response.count("- **") if has_issues else 0
            _hlog.log(HUMAN, {
                "event": "reviewer.complete",
                "approved": not has_issues,
                "issues": issue_count,
                "score": "N/A",
            })

            return ReviewResult(
                has_issues=has_issues,
                review_text=response,
                cost=cost,
            )

        except Exception as e:
            self.log.error("auto_review.error", error=str(e))
            return ReviewResult(
                has_issues=False,
                review_text=t("reviewer.error", error=str(e)),
                cost=0.0,
            )

    @staticmethod
    def get_recent_diff(workspace_root: str, commits_back: int = 1) -> str:
        """Get the diff of the last N commits."""
        try:
            result = subprocess.run(
                ["git", "diff", f"HEAD~{commits_back}", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=workspace_root,
            )
            return result.stdout
        except Exception:
            return ""

    @staticmethod
    def build_fix_prompt(review_text: str) -> str:
        """Build a correction prompt based on the review."""
        return t("reviewer.fix_prompt", review_text=review_text)
