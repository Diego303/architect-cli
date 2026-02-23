"""
Tests para el Dry Run tracker v4-B4.

Cubre:
- DryRunTracker (record, get_plan_summary, action_count)
- PlannedAction dataclass
- _summarize_action helper
"""

import pytest

from architect.features.dryrun import (
    READ_TOOLS,
    WRITE_TOOLS,
    DryRunTracker,
    PlannedAction,
    _summarize_action,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tracker() -> DryRunTracker:
    """Crea un DryRunTracker vacío."""
    return DryRunTracker()


# ── Tests: WRITE_TOOLS / READ_TOOLS constants ───────────────────────────


class TestToolSets:
    """Tests para los conjuntos de tools."""

    def test_write_tools_includes_write_file(self) -> None:
        assert "write_file" in WRITE_TOOLS

    def test_write_tools_includes_edit_file(self) -> None:
        assert "edit_file" in WRITE_TOOLS

    def test_write_tools_includes_run_command(self) -> None:
        assert "run_command" in WRITE_TOOLS

    def test_write_tools_includes_delete_file(self) -> None:
        assert "delete_file" in WRITE_TOOLS

    def test_read_tools_includes_read_file(self) -> None:
        assert "read_file" in READ_TOOLS

    def test_read_tools_includes_search_code(self) -> None:
        assert "search_code" in READ_TOOLS

    def test_no_overlap(self) -> None:
        """READ_TOOLS y WRITE_TOOLS no se solapan."""
        assert WRITE_TOOLS & READ_TOOLS == set()


# ── Tests: DryRunTracker.record ──────────────────────────────────────────


class TestDryRunRecord:
    """Tests para DryRunTracker.record."""

    def test_records_write_tool(self, tracker: DryRunTracker) -> None:
        """record registra tools de escritura."""
        tracker.record(1, "write_file", {"path": "src/main.py", "content": "..."})
        assert tracker.action_count == 1
        assert tracker.actions[0].tool == "write_file"
        assert tracker.actions[0].step == 1

    def test_ignores_read_tool(self, tracker: DryRunTracker) -> None:
        """record ignora tools de lectura."""
        tracker.record(1, "read_file", {"path": "src/main.py"})
        assert tracker.action_count == 0

    def test_records_multiple(self, tracker: DryRunTracker) -> None:
        """record registra múltiples acciones."""
        tracker.record(1, "write_file", {"path": "a.py"})
        tracker.record(2, "edit_file", {"path": "b.py"})
        tracker.record(3, "run_command", {"command": "pytest"})
        assert tracker.action_count == 3

    def test_records_run_command(self, tracker: DryRunTracker) -> None:
        """record registra run_command como acción de escritura."""
        tracker.record(1, "run_command", {"command": "rm -rf node_modules"})
        assert tracker.action_count == 1
        assert "rm -rf node_modules" in tracker.actions[0].summary

    def test_ignores_unknown_tool(self, tracker: DryRunTracker) -> None:
        """record ignora tools desconocidas (ni read ni write)."""
        tracker.record(1, "unknown_tool", {"foo": "bar"})
        assert tracker.action_count == 0

    def test_records_delete_file(self, tracker: DryRunTracker) -> None:
        """record registra delete_file."""
        tracker.record(1, "delete_file", {"path": "old.py"})
        assert tracker.action_count == 1

    def test_records_apply_patch(self, tracker: DryRunTracker) -> None:
        """record registra apply_patch."""
        tracker.record(1, "apply_patch", {"path": "src/main.py", "diff": "..."})
        assert tracker.action_count == 1


# ── Tests: DryRunTracker.get_plan_summary ────────────────────────────────


class TestDryRunPlanSummary:
    """Tests para DryRunTracker.get_plan_summary."""

    def test_empty_plan(self, tracker: DryRunTracker) -> None:
        """Plan vacío produce mensaje indicativo."""
        summary = tracker.get_plan_summary()
        assert "No write actions" in summary

    def test_single_action(self, tracker: DryRunTracker) -> None:
        """Plan con una acción muestra la acción."""
        tracker.record(1, "write_file", {"path": "src/main.py"})
        summary = tracker.get_plan_summary()
        assert "## Dry Run Plan" in summary
        assert "write_file" in summary
        assert "src/main.py" in summary
        assert "1 write action(s)" in summary

    def test_multiple_actions(self, tracker: DryRunTracker) -> None:
        """Plan con múltiples acciones las lista todas numeradas."""
        tracker.record(1, "write_file", {"path": "a.py"})
        tracker.record(2, "edit_file", {"path": "b.py"})
        tracker.record(3, "run_command", {"command": "pytest tests/"})
        summary = tracker.get_plan_summary()
        assert "3 write action(s)" in summary
        assert "1." in summary
        assert "2." in summary
        assert "3." in summary

    def test_includes_step_number(self, tracker: DryRunTracker) -> None:
        """Plan summary incluye el número de step."""
        tracker.record(5, "write_file", {"path": "src/config.py"})
        summary = tracker.get_plan_summary()
        assert "step 5" in summary


# ── Tests: _summarize_action ─────────────────────────────────────────────


class TestSummarizeAction:
    """Tests para _summarize_action helper."""

    def test_summarize_with_path(self) -> None:
        """Resumen incluye path si está disponible."""
        result = _summarize_action("write_file", {"path": "src/main.py", "content": "..."})
        assert result == "path=src/main.py"

    def test_summarize_with_command(self) -> None:
        """Resumen incluye command si está disponible."""
        result = _summarize_action("run_command", {"command": "pytest tests/"})
        assert result == "command=pytest tests/"

    def test_summarize_long_command(self) -> None:
        """Resumen trunca commands largos a 60 chars."""
        long_cmd = "python -m pytest tests/ --cov=src/ --cov-report=html --verbose --tb=long --color=yes"
        result = _summarize_action("run_command", {"command": long_cmd})
        assert len(result) < len(f"command={long_cmd}") + 5
        assert "..." in result

    def test_summarize_fallback(self) -> None:
        """Resumen muestra keys como fallback."""
        result = _summarize_action("unknown_tool", {"foo": "bar", "baz": "qux"})
        assert "args=" in result
        assert "foo" in result
        assert "baz" in result


# ── Tests: PlannedAction ─────────────────────────────────────────────────


class TestPlannedAction:
    """Tests para PlannedAction dataclass."""

    def test_creation(self) -> None:
        """PlannedAction se crea con todos los campos."""
        action = PlannedAction(step=1, tool="write_file", summary="path=main.py")
        assert action.step == 1
        assert action.tool == "write_file"
        assert action.summary == "path=main.py"
