"""Tests for architect.agents.reviewer — AutoReviewer, ReviewResult, REVIEW_SYSTEM_PROMPT."""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from architect.agents.reviewer import (
    REVIEW_SYSTEM_PROMPT,
    AutoReviewer,
    ReviewResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_result(final_output: str = "", total_cost: float = 0.0):
    """Build a fake agent result with final_output and cost_tracker."""
    cost_tracker = SimpleNamespace(total_cost_usd=total_cost)
    return SimpleNamespace(final_output=final_output, cost_tracker=cost_tracker)


def _make_factory(agent_result=None, side_effect=None):
    """Return a MagicMock agent_factory whose agent.run() returns *agent_result*."""
    factory = MagicMock()
    agent_mock = MagicMock()
    if side_effect is not None:
        agent_mock.run.side_effect = side_effect
    else:
        agent_mock.run.return_value = agent_result or _make_agent_result()
    factory.return_value = agent_mock
    return factory


# ===================================================================
# 1. REVIEW_SYSTEM_PROMPT
# ===================================================================

class TestReviewSystemPrompt:
    """Tests for the REVIEW_SYSTEM_PROMPT constant."""

    def test_is_non_empty_string(self):
        # REVIEW_SYSTEM_PROMPT is a lazy descriptor; str() resolves it
        assert len(REVIEW_SYSTEM_PROMPT) > 0
        assert isinstance(str(REVIEW_SYSTEM_PROMPT), str)

    def test_contains_bug_criteria(self):
        assert "Bugs" in REVIEW_SYSTEM_PROMPT or "bugs" in REVIEW_SYSTEM_PROMPT.lower()

    def test_contains_security_criteria(self):
        assert "seguridad" in REVIEW_SYSTEM_PROMPT.lower() or "security" in REVIEW_SYSTEM_PROMPT.lower()

    def test_contains_no_issues_instruction(self):
        """The prompt must tell the reviewer what to say when there are no issues."""
        assert "No issues found" in REVIEW_SYSTEM_PROMPT

    def test_contains_tests_criteria(self):
        assert "Tests" in REVIEW_SYSTEM_PROMPT or "tests" in REVIEW_SYSTEM_PROMPT.lower()

    def test_contains_simplification_criteria(self):
        assert "simplificati" in REVIEW_SYSTEM_PROMPT.lower()


# ===================================================================
# 2. ReviewResult
# ===================================================================

class TestReviewResult:
    """Tests for the ReviewResult value class."""

    def test_stores_has_issues(self):
        r = ReviewResult(has_issues=True, review_text="found bug")
        assert r.has_issues is True

    def test_stores_review_text(self):
        r = ReviewResult(has_issues=False, review_text="all good")
        assert r.review_text == "all good"

    def test_stores_cost(self):
        r = ReviewResult(has_issues=False, review_text="ok", cost=1.23)
        assert r.cost == 1.23

    def test_default_cost_is_zero(self):
        r = ReviewResult(has_issues=False, review_text="ok")
        assert r.cost == 0.0

    def test_has_issues_false(self):
        r = ReviewResult(has_issues=False, review_text="nada")
        assert r.has_issues is False

    def test_review_text_can_be_empty(self):
        r = ReviewResult(has_issues=False, review_text="")
        assert r.review_text == ""


# ===================================================================
# 3. AutoReviewer.__init__
# ===================================================================

class TestAutoReviewerInit:
    """Tests for AutoReviewer construction."""

    def test_stores_agent_factory(self):
        factory = MagicMock()
        reviewer = AutoReviewer(agent_factory=factory)
        assert reviewer.agent_factory is factory

    def test_stores_review_model(self):
        reviewer = AutoReviewer(agent_factory=MagicMock(), review_model="gpt-4o")
        assert reviewer.review_model == "gpt-4o"

    def test_review_model_defaults_to_none(self):
        reviewer = AutoReviewer(agent_factory=MagicMock())
        assert reviewer.review_model is None


# ===================================================================
# 4. AutoReviewer.review_changes
# ===================================================================

class TestReviewChanges:
    """Tests for AutoReviewer.review_changes."""

    # -- empty diff ---------------------------------------------------

    def test_empty_diff_returns_no_issues(self):
        factory = _make_factory()
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("tarea", "")
        assert result.has_issues is False
        assert "No changes" in result.review_text

    def test_whitespace_only_diff_returns_no_issues(self):
        factory = _make_factory()
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("tarea", "   \n\t  ")
        assert result.has_issues is False

    def test_empty_diff_does_not_call_agent(self):
        factory = _make_factory()
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("tarea", "")
        factory.assert_not_called()

    # -- valid diff / agent interaction --------------------------------

    def test_valid_diff_calls_agent_factory(self):
        factory = _make_factory(_make_agent_result("Sin issues encontrados."))
        reviewer = AutoReviewer(agent_factory=factory, review_model="gpt-4o")
        reviewer.review_changes("tarea", "diff --git a/foo.py")

        factory.assert_called_once_with(agent="review", model="gpt-4o")

    def test_valid_diff_calls_agent_run(self):
        factory = _make_factory(_make_agent_result("Sin issues encontrados."))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("tarea", "diff --git a/foo.py")

        agent_mock = factory.return_value
        agent_mock.run.assert_called_once()

    def test_review_model_none_passed_to_factory(self):
        factory = _make_factory(_make_agent_result("ok"))
        reviewer = AutoReviewer(agent_factory=factory, review_model=None)
        reviewer.review_changes("task", "some diff")

        factory.assert_called_once_with(agent="review", model=None)

    # -- sin issues detection -----------------------------------------

    def test_sin_issues_detected_as_no_issues(self):
        factory = _make_factory(_make_agent_result("Sin issues encontrados."))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("tarea", "diff content")
        assert result.has_issues is False

    def test_sin_issues_case_insensitive(self):
        factory = _make_factory(_make_agent_result("SIN ISSUES encontrados."))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("tarea", "diff content")
        assert result.has_issues is False

    def test_text_without_sin_issues_detected_as_having_issues(self):
        text = "- **[foo.py:10]** Bug encontrado en loop."
        factory = _make_factory(_make_agent_result(text))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("tarea", "diff content")
        assert result.has_issues is True
        assert result.review_text == text

    # -- diff truncation ----------------------------------------------

    def test_truncates_long_diff_at_8000(self):
        long_diff = "x" * 10000
        factory = _make_factory(_make_agent_result("Sin issues encontrados."))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("tarea", long_diff)

        agent_mock = factory.return_value
        prompt_arg = agent_mock.run.call_args[0][0]
        # The truncated diff should contain the first 8000 chars + truncation notice
        assert "x" * 8000 in prompt_arg
        assert "diff truncated" in prompt_arg

    def test_short_diff_not_truncated(self):
        short_diff = "x" * 100
        factory = _make_factory(_make_agent_result("ok"))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("tarea", short_diff)

        agent_mock = factory.return_value
        prompt_arg = agent_mock.run.call_args[0][0]
        assert "diff truncated" not in prompt_arg

    # -- prompt format ------------------------------------------------

    def test_prompt_contains_task(self):
        factory = _make_factory(_make_agent_result("ok"))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("Fix login bug", "diff --git a/login.py")

        prompt_arg = factory.return_value.run.call_args[0][0]
        assert "Fix login bug" in prompt_arg

    def test_prompt_contains_diff(self):
        factory = _make_factory(_make_agent_result("ok"))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("task", "diff --git a/login.py\n+new line")

        prompt_arg = factory.return_value.run.call_args[0][0]
        assert "diff --git a/login.py" in prompt_arg
        assert "+new line" in prompt_arg

    def test_prompt_has_original_task_section(self):
        factory = _make_factory(_make_agent_result("ok"))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("the task", "some diff")

        prompt_arg = factory.return_value.run.call_args[0][0]
        assert "## Original Task" in prompt_arg

    def test_prompt_has_changes_section(self):
        factory = _make_factory(_make_agent_result("ok"))
        reviewer = AutoReviewer(agent_factory=factory)
        reviewer.review_changes("the task", "some diff")

        prompt_arg = factory.return_value.run.call_args[0][0]
        assert "## Changes to Review" in prompt_arg

    # -- cost extraction -----------------------------------------------

    def test_extracts_cost_from_tracker(self):
        factory = _make_factory(_make_agent_result("ok", total_cost=0.42))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff")
        assert result.cost == pytest.approx(0.42)

    def test_cost_zero_when_no_tracker(self):
        agent_result = SimpleNamespace(final_output="ok", cost_tracker=None)
        factory = _make_factory(agent_result)
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff")
        assert result.cost == 0.0

    def test_cost_zero_when_no_cost_tracker_attr(self):
        agent_result = SimpleNamespace(final_output="ok")
        factory = _make_factory(agent_result)
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff")
        assert result.cost == 0.0

    # -- error handling ------------------------------------------------

    def test_agent_error_returns_no_issues(self):
        factory = _make_factory(side_effect=RuntimeError("LLM down"))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff content")
        assert result.has_issues is False

    def test_agent_error_includes_message_in_text(self):
        factory = _make_factory(side_effect=RuntimeError("LLM down"))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff content")
        assert "LLM down" in result.review_text

    def test_agent_error_cost_is_zero(self):
        factory = _make_factory(side_effect=RuntimeError("boom"))
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff content")
        assert result.cost == 0.0

    # -- edge: final_output is None ------------------------------------

    def test_none_final_output_treated_as_empty(self):
        agent_result = SimpleNamespace(final_output=None, cost_tracker=None)
        factory = _make_factory(agent_result)
        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes("task", "diff")
        # empty string -> "sin issues" NOT in "" -> has_issues = True
        # Actually: "" doesn't contain "sin issues" so has_issues is True
        assert result.review_text == ""


# ===================================================================
# 5. AutoReviewer.get_recent_diff
# ===================================================================

class TestGetRecentDiff:
    """Tests for AutoReviewer.get_recent_diff (static method)."""

    @patch("architect.agents.reviewer.subprocess.run")
    def test_calls_git_diff(self, mock_run):
        mock_run.return_value = SimpleNamespace(stdout="diff output")
        result = AutoReviewer.get_recent_diff("/workspace", commits_back=1)

        mock_run.assert_called_once_with(
            ["git", "diff", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/workspace",
        )
        assert result == "diff output"

    @patch("architect.agents.reviewer.subprocess.run")
    def test_custom_commits_back(self, mock_run):
        mock_run.return_value = SimpleNamespace(stdout="diff")
        AutoReviewer.get_recent_diff("/ws", commits_back=3)

        args = mock_run.call_args[0][0]
        assert "HEAD~3" in args

    @patch("architect.agents.reviewer.subprocess.run")
    def test_returns_empty_on_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10)
        result = AutoReviewer.get_recent_diff("/workspace")
        assert result == ""

    @patch("architect.agents.reviewer.subprocess.run")
    def test_returns_empty_on_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("not a git repo")
        result = AutoReviewer.get_recent_diff("/workspace")
        assert result == ""

    @patch("architect.agents.reviewer.subprocess.run")
    def test_uses_workspace_root_as_cwd(self, mock_run):
        mock_run.return_value = SimpleNamespace(stdout="")
        AutoReviewer.get_recent_diff("/my/project")
        assert mock_run.call_args[1]["cwd"] == "/my/project"


# ===================================================================
# 6. AutoReviewer.build_fix_prompt
# ===================================================================

class TestBuildFixPrompt:
    """Tests for AutoReviewer.build_fix_prompt (static method)."""

    def test_includes_review_text(self):
        review = "- **[foo.py:5]** Off-by-one error."
        prompt = AutoReviewer.build_fix_prompt(review)
        assert review in prompt

    def test_includes_fix_instruction(self):
        prompt = AutoReviewer.build_fix_prompt("some issue")
        assert "Fix" in prompt or "fix" in prompt.lower()

    def test_format_starts_with_reviewer_intro(self):
        prompt = AutoReviewer.build_fix_prompt("issue")
        assert prompt.startswith("A reviewer found")

    def test_mentions_each_issue(self):
        prompt = AutoReviewer.build_fix_prompt("issue X\nissue Y")
        assert "issue X" in prompt
        assert "issue Y" in prompt

    def test_empty_review_text(self):
        prompt = AutoReviewer.build_fix_prompt("")
        # Should still return a valid prompt even with empty review
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ===================================================================
# HUMAN Logging
# ===================================================================


class TestReviewerHumanLogging:
    """Tests para HUMAN-level logging en AutoReviewer."""

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

    def test_reviewer_start_emitted(self) -> None:
        """reviewer.start se emite al iniciar review."""
        factory = _make_factory(_make_agent_result("Sin issues encontrados.", 0.01))
        reviewer = AutoReviewer(factory, review_model="gpt-4o")
        diff = "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@\n+import os\n"

        with patch("architect.agents.reviewer._hlog") as mock_hlog:
            reviewer.review_changes("Fix login", diff)

        starts = self._extract_human_calls(mock_hlog, "reviewer.start")
        assert len(starts) == 1
        assert "diff_lines" in starts[0]

    def test_reviewer_complete_emitted_approved(self) -> None:
        """reviewer.complete se emite cuando se aprueba."""
        factory = _make_factory(_make_agent_result("Sin issues encontrados.", 0.02))
        reviewer = AutoReviewer(factory)
        diff = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n"

        with patch("architect.agents.reviewer._hlog") as mock_hlog:
            reviewer.review_changes("Fix it", diff)

        completes = self._extract_human_calls(mock_hlog, "reviewer.complete")
        assert len(completes) == 1
        assert completes[0]["approved"] is True
        assert completes[0]["issues"] == 0

    def test_reviewer_complete_emitted_with_issues(self) -> None:
        """reviewer.complete se emite cuando hay issues."""
        review_text = "- **[main.py:1]** Bug found\n- **[utils.py:5]** Security issue"
        factory = _make_factory(_make_agent_result(review_text, 0.03))
        reviewer = AutoReviewer(factory)
        diff = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n"

        with patch("architect.agents.reviewer._hlog") as mock_hlog:
            reviewer.review_changes("Fix it", diff)

        completes = self._extract_human_calls(mock_hlog, "reviewer.complete")
        assert len(completes) == 1
        assert completes[0]["approved"] is False
        assert completes[0]["issues"] == 2

    def test_no_human_log_on_empty_diff(self) -> None:
        """No se emiten HUMAN events si el diff esta vacio."""
        factory = _make_factory()
        reviewer = AutoReviewer(factory)

        with patch("architect.agents.reviewer._hlog") as mock_hlog:
            reviewer.review_changes("Fix it", "")

        starts = self._extract_human_calls(mock_hlog, "reviewer.start")
        assert len(starts) == 0


class TestHumanFormatterReviewer:
    """Tests para HumanFormatter con eventos reviewer.*."""

    def test_reviewer_start_banner(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event("reviewer.start", diff_lines=142)
        assert result is not None
        assert "142" in result
        assert "━" in result

    def test_reviewer_complete_approved(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "reviewer.complete", approved=True, issues=0, score="8/10",
        )
        assert result is not None
        assert "✓" in result
        assert "approved" in result
        assert "8/10" in result

    def test_reviewer_complete_not_approved(self) -> None:
        from architect.logging.human import HumanFormatter
        fmt = HumanFormatter()
        result = fmt.format_event(
            "reviewer.complete", approved=False, issues=5, score="4/10",
        )
        assert result is not None
        assert "✗" in result
        assert "not approved" in result
        assert "5 issues" in result


class TestHumanLogReviewer:
    """Tests para HumanLog helpers de Reviewer."""

    def test_reviewer_start(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.reviewer_start(142)
        mock_logger.log.assert_called_once_with(
            LVL, "reviewer.start", diff_lines=142,
        )

    def test_reviewer_complete(self) -> None:
        from architect.logging.human import HumanLog
        from architect.logging.levels import HUMAN as LVL
        mock_logger = MagicMock()
        hlog = HumanLog(mock_logger)
        hlog.reviewer_complete(True, 2, "8/10")
        mock_logger.log.assert_called_once_with(
            LVL, "reviewer.complete",
            approved=True, issues=2, score="8/10",
        )
