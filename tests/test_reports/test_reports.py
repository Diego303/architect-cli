"""
Tests para el sistema de reportes v4-B2.

Cubre:
- ExecutionReport (dataclass)
- ReportGenerator (to_json, to_markdown, to_github_pr_comment)
"""

import json

import pytest

from architect.features.report import ExecutionReport, ReportGenerator


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def minimal_report() -> ExecutionReport:
    """Reporte mínimo sin datos opcionales."""
    return ExecutionReport(
        task="Añadir validación",
        agent="build",
        model="gpt-4o",
        status="success",
        duration_seconds=45.5,
        steps=8,
        total_cost=0.0234,
    )


@pytest.fixture
def full_report() -> ExecutionReport:
    """Reporte completo con todos los campos opcionales."""
    return ExecutionReport(
        task="Refactorizar auth module",
        agent="build",
        model="claude-sonnet-4-6",
        status="partial",
        duration_seconds=120.7,
        steps=15,
        total_cost=0.1500,
        files_modified=[
            {"path": "src/auth.py", "action": "modified", "lines_added": 50, "lines_removed": 20},
            {"path": "tests/test_auth.py", "action": "created", "lines_added": 80, "lines_removed": 0},
        ],
        quality_gates=[
            {"name": "lint", "passed": True, "output": ""},
            {"name": "tests", "passed": False, "output": "2 tests failed: test_login, test_logout"},
        ],
        errors=["Timeout en step 12", "Error de conexión LLM en step 14"],
        git_diff="diff --git a/src/auth.py b/src/auth.py\n...",
        timeline=[
            {"step": 1, "tool": "read_file", "duration": 0.5, "cost": 0.001},
            {"step": 2, "tool": "write_file", "duration": 1.2, "cost": 0.003},
            {"step": 3, "tool": "run_command", "duration": 5.0, "cost": 0.005},
        ],
        stop_reason="timeout",
    )


# ── Tests: ExecutionReport ───────────────────────────────────────────────


class TestExecutionReport:
    """Tests para ExecutionReport dataclass."""

    def test_minimal_creation(self, minimal_report: ExecutionReport) -> None:
        """Crear reporte con solo campos requeridos."""
        assert minimal_report.task == "Añadir validación"
        assert minimal_report.status == "success"
        assert minimal_report.files_modified == []
        assert minimal_report.quality_gates == []
        assert minimal_report.errors == []
        assert minimal_report.git_diff is None
        assert minimal_report.timeline == []
        assert minimal_report.stop_reason is None

    def test_full_creation(self, full_report: ExecutionReport) -> None:
        """Crear reporte con todos los campos."""
        assert full_report.status == "partial"
        assert len(full_report.files_modified) == 2
        assert len(full_report.quality_gates) == 2
        assert len(full_report.errors) == 2
        assert len(full_report.timeline) == 3
        assert full_report.stop_reason == "timeout"


# ── Tests: ReportGenerator.to_json ───────────────────────────────────────


class TestReportToJson:
    """Tests para generación de reportes JSON."""

    def test_valid_json(self, minimal_report: ExecutionReport) -> None:
        """to_json produce JSON válido."""
        gen = ReportGenerator(minimal_report)
        result = gen.to_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_contains_all_fields(self, full_report: ExecutionReport) -> None:
        """to_json incluye todos los campos del reporte."""
        gen = ReportGenerator(full_report)
        parsed = json.loads(gen.to_json())

        assert parsed["task"] == "Refactorizar auth module"
        assert parsed["agent"] == "build"
        assert parsed["model"] == "claude-sonnet-4-6"
        assert parsed["status"] == "partial"
        assert parsed["duration_seconds"] == 120.7
        assert parsed["steps"] == 15
        assert parsed["total_cost"] == 0.15
        assert len(parsed["files_modified"]) == 2
        assert len(parsed["quality_gates"]) == 2
        assert len(parsed["errors"]) == 2
        assert len(parsed["timeline"]) == 3
        assert parsed["stop_reason"] == "timeout"

    def test_parseable_by_ci(self, minimal_report: ExecutionReport) -> None:
        """El JSON es parseable y tiene los campos que CI/CD necesita."""
        gen = ReportGenerator(minimal_report)
        parsed = json.loads(gen.to_json())

        # CI/CD típicamente necesita: status, steps, cost, duration
        assert "status" in parsed
        assert "steps" in parsed
        assert "total_cost" in parsed
        assert "duration_seconds" in parsed


# ── Tests: ReportGenerator.to_markdown ───────────────────────────────────


class TestReportToMarkdown:
    """Tests para generación de reportes Markdown."""

    def test_has_header(self, minimal_report: ExecutionReport) -> None:
        """to_markdown incluye header de reporte."""
        gen = ReportGenerator(minimal_report)
        md = gen.to_markdown()
        assert "# Execution Report" in md

    def test_has_summary_table(self, minimal_report: ExecutionReport) -> None:
        """to_markdown incluye tabla de resumen."""
        gen = ReportGenerator(minimal_report)
        md = gen.to_markdown()
        assert "## Summary" in md
        assert "| Task |" in md
        assert "Añadir validación" in md
        assert "gpt-4o" in md
        assert "OK" in md  # status icon for success

    def test_has_files_section(self, full_report: ExecutionReport) -> None:
        """to_markdown incluye sección de archivos modificados."""
        gen = ReportGenerator(full_report)
        md = gen.to_markdown()
        assert "## Files Modified" in md
        assert "src/auth.py" in md
        assert "tests/test_auth.py" in md

    def test_has_quality_gates(self, full_report: ExecutionReport) -> None:
        """to_markdown incluye sección de quality gates."""
        gen = ReportGenerator(full_report)
        md = gen.to_markdown()
        assert "## Quality Gates" in md
        assert "lint" in md
        assert "tests" in md

    def test_has_errors(self, full_report: ExecutionReport) -> None:
        """to_markdown incluye sección de errores."""
        gen = ReportGenerator(full_report)
        md = gen.to_markdown()
        assert "## Errors" in md
        assert "Timeout en step 12" in md

    def test_has_timeline(self, full_report: ExecutionReport) -> None:
        """to_markdown incluye timeline."""
        gen = ReportGenerator(full_report)
        md = gen.to_markdown()
        assert "## Timeline" in md
        assert "read_file" in md
        assert "write_file" in md

    def test_has_stop_reason(self, full_report: ExecutionReport) -> None:
        """to_markdown incluye stop_reason en la tabla."""
        gen = ReportGenerator(full_report)
        md = gen.to_markdown()
        assert "timeout" in md

    def test_no_files_section_when_empty(self, minimal_report: ExecutionReport) -> None:
        """to_markdown no incluye sección de archivos si está vacía."""
        gen = ReportGenerator(minimal_report)
        md = gen.to_markdown()
        assert "## Files Modified" not in md

    def test_no_errors_section_when_empty(self, minimal_report: ExecutionReport) -> None:
        """to_markdown no incluye sección de errores si está vacía."""
        gen = ReportGenerator(minimal_report)
        md = gen.to_markdown()
        assert "## Errors" not in md

    def test_partial_status_shows_warn(self, full_report: ExecutionReport) -> None:
        """to_markdown muestra WARN para status partial."""
        gen = ReportGenerator(full_report)
        md = gen.to_markdown()
        assert "WARN" in md


# ── Tests: ReportGenerator.to_github_pr_comment ─────────────────────────


class TestReportToGithubComment:
    """Tests para generación de comentarios de PR."""

    def test_has_header(self, minimal_report: ExecutionReport) -> None:
        """to_github_pr_comment incluye header con tarea."""
        gen = ReportGenerator(minimal_report)
        comment = gen.to_github_pr_comment()
        assert "architect:" in comment
        assert "Añadir validación" in comment

    def test_has_metrics(self, minimal_report: ExecutionReport) -> None:
        """to_github_pr_comment incluye métricas clave."""
        gen = ReportGenerator(minimal_report)
        comment = gen.to_github_pr_comment()
        assert "8 steps" in comment
        assert "46s" in comment  # 45.5 redondeado
        assert "$0.023" in comment

    def test_has_files_details(self, full_report: ExecutionReport) -> None:
        """to_github_pr_comment incluye archivos en details/summary."""
        gen = ReportGenerator(full_report)
        comment = gen.to_github_pr_comment()
        assert "<details>" in comment
        assert "src/auth.py" in comment

    def test_has_quality_gates(self, full_report: ExecutionReport) -> None:
        """to_github_pr_comment incluye quality gates inline."""
        gen = ReportGenerator(full_report)
        comment = gen.to_github_pr_comment()
        assert "lint" in comment
        assert "tests" in comment

    def test_success_status_icon(self, minimal_report: ExecutionReport) -> None:
        """to_github_pr_comment usa OK para success."""
        gen = ReportGenerator(minimal_report)
        comment = gen.to_github_pr_comment()
        assert "OK" in comment

    def test_partial_status_icon(self, full_report: ExecutionReport) -> None:
        """to_github_pr_comment usa WARN para partial."""
        gen = ReportGenerator(full_report)
        comment = gen.to_github_pr_comment()
        assert "WARN" in comment
