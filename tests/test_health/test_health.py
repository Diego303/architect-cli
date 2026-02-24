"""
Tests para Code Health Delta (v4-D2).

Cubre:
- FunctionMetric (frozen dataclass)
- HealthSnapshot (campos, defaults)
- HealthDelta (cálculo, reporte)
- CodeHealthAnalyzer (snapshot, delta, AST analysis, duplicación)
- Casos sin radon
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from architect.core.health import (
    COMPLEX_FUNCTION_THRESHOLD,
    DUPLICATE_BLOCK_SIZE,
    LONG_FUNCTION_THRESHOLD,
    CodeHealthAnalyzer,
    FunctionMetric,
    HealthDelta,
    HealthSnapshot,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal con archivos Python."""
    src = tmp_path / "src"
    src.mkdir()

    # Archivo con funciones simples
    (src / "simple.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
    )

    # Archivo con función larga
    long_body = "\n".join(f"    x = {i}" for i in range(60))
    (src / "long_func.py").write_text(
        f"def very_long_function():\n{long_body}\n    return x\n"
    )

    # Archivo con función compleja (muchos if/elif)
    complex_body = "\n".join(
        f"    if x == {i}:\n        return {i}" for i in range(15)
    )
    (src / "complex_func.py").write_text(
        f"def complex_function(x):\n{complex_body}\n    return -1\n"
    )

    return tmp_path


@pytest.fixture
def analyzer(workspace: Path) -> CodeHealthAnalyzer:
    """Analizador configurado para el workspace temporal."""
    return CodeHealthAnalyzer(
        workspace_root=str(workspace),
        include_patterns=["**/*.py"],
    )


# -- Tests: FunctionMetric ---------------------------------------------------


class TestFunctionMetric:
    """Tests para FunctionMetric dataclass."""

    def test_frozen(self):
        m = FunctionMetric(file="test.py", name="foo", lines=10, complexity=3)
        with pytest.raises(AttributeError):
            m.lines = 20  # type: ignore[misc]

    def test_fields(self):
        m = FunctionMetric(file="src/main.py", name="main", lines=25, complexity=5)
        assert m.file == "src/main.py"
        assert m.name == "main"
        assert m.lines == 25
        assert m.complexity == 5


# -- Tests: HealthSnapshot ---------------------------------------------------


class TestHealthSnapshot:
    """Tests para HealthSnapshot dataclass."""

    def test_default_values(self):
        s = HealthSnapshot()
        assert s.files_analyzed == 0
        assert s.total_functions == 0
        assert s.avg_complexity == 0.0
        assert s.max_complexity == 0
        assert s.avg_function_lines == 0.0
        assert s.max_function_lines == 0
        assert s.long_functions == 0
        assert s.complex_functions == 0
        assert s.duplicate_blocks == 0
        assert s.functions == []
        assert s.radon_available is False

    def test_custom_values(self):
        s = HealthSnapshot(
            files_analyzed=10,
            total_functions=50,
            avg_complexity=3.5,
            max_complexity=15,
        )
        assert s.files_analyzed == 10
        assert s.total_functions == 50
        assert s.avg_complexity == 3.5
        assert s.max_complexity == 15


# -- Tests: HealthDelta ------------------------------------------------------


class TestHealthDelta:
    """Tests para HealthDelta y su reporte."""

    def test_zero_delta(self):
        snapshot = HealthSnapshot(
            files_analyzed=5,
            total_functions=10,
            avg_complexity=3.0,
        )
        delta = HealthDelta(before=snapshot, after=snapshot)
        assert delta.complexity_delta == 0.0
        assert delta.long_functions_delta == 0
        assert delta.new_functions == 0

    def test_positive_delta_degradation(self):
        before = HealthSnapshot(avg_complexity=3.0, max_complexity=8)
        after = HealthSnapshot(avg_complexity=5.0, max_complexity=12)
        delta = HealthDelta(
            before=before,
            after=after,
            complexity_delta=2.0,
            max_complexity_delta=4,
        )
        assert delta.complexity_delta == 2.0
        assert delta.max_complexity_delta == 4

    def test_negative_delta_improvement(self):
        before = HealthSnapshot(avg_complexity=5.0, long_functions=3)
        after = HealthSnapshot(avg_complexity=3.0, long_functions=1)
        delta = HealthDelta(
            before=before,
            after=after,
            complexity_delta=-2.0,
            long_functions_delta=-2,
        )
        assert delta.complexity_delta == -2.0
        assert delta.long_functions_delta == -2

    def test_to_report_contains_table(self):
        before = HealthSnapshot(
            files_analyzed=5,
            total_functions=10,
            avg_complexity=3.0,
            max_complexity=8,
            avg_function_lines=15.0,
            long_functions=1,
            complex_functions=0,
            duplicate_blocks=2,
        )
        after = HealthSnapshot(
            files_analyzed=6,
            total_functions=12,
            avg_complexity=3.5,
            max_complexity=10,
            avg_function_lines=18.0,
            long_functions=2,
            complex_functions=1,
            duplicate_blocks=1,
        )
        delta = HealthDelta(
            before=before,
            after=after,
            complexity_delta=0.5,
            max_complexity_delta=2,
            avg_lines_delta=3.0,
            long_functions_delta=1,
            complex_functions_delta=1,
            duplicate_blocks_delta=-1,
            new_functions=3,
            removed_functions=1,
        )
        report = delta.to_report()
        assert "Code Health Delta" in report
        assert "Complejidad promedio" in report
        assert "Antes" in report
        assert "Después" in report
        assert "Delta" in report

    def test_to_report_radon_not_available(self):
        before = HealthSnapshot(radon_available=False)
        after = HealthSnapshot(radon_available=False)
        delta = HealthDelta(before=before, after=after)
        report = delta.to_report()
        assert "radon no disponible" in report

    def test_format_delta_zero(self):
        assert HealthDelta._format_delta(0) == "="
        assert HealthDelta._format_delta(0.0) == "="

    def test_format_delta_positive(self):
        result = HealthDelta._format_delta(3)
        assert "+" in result

    def test_format_delta_negative(self):
        result = HealthDelta._format_delta(-2)
        assert "-" in result


# -- Tests: CodeHealthAnalyzer ------------------------------------------------


class TestCodeHealthAnalyzer:
    """Tests para el analizador de salud."""

    def test_init(self, analyzer, workspace):
        assert analyzer.root == workspace
        assert "**/*.py" in analyzer.include_patterns

    def test_snapshot_counts_files(self, analyzer):
        snapshot = analyzer.snapshot()
        assert snapshot.files_analyzed >= 3  # simple, long_func, complex_func

    def test_snapshot_counts_functions(self, analyzer):
        snapshot = analyzer.snapshot()
        # simple.py: add, subtract; long_func.py: very_long_function; complex_func.py: complex_function
        assert snapshot.total_functions >= 4

    def test_snapshot_detects_long_functions(self, analyzer):
        snapshot = analyzer.snapshot()
        assert snapshot.long_functions >= 1  # very_long_function tiene 60+ líneas

    def test_snapshot_max_function_lines(self, analyzer):
        snapshot = analyzer.snapshot()
        assert snapshot.max_function_lines >= 50

    def test_snapshot_avg_function_lines(self, analyzer):
        snapshot = analyzer.snapshot()
        assert snapshot.avg_function_lines > 0

    def test_before_after_delta(self, analyzer, workspace):
        # Before snapshot
        analyzer.take_before_snapshot()

        # Modificar el workspace (agregar más funciones)
        new_file = workspace / "src" / "new_module.py"
        new_file.write_text(
            "def new_function():\n"
            "    return 42\n"
            "\n"
            "def another_function():\n"
            "    return 84\n"
        )

        # After snapshot
        analyzer.take_after_snapshot()

        delta = analyzer.compute_delta()
        assert delta is not None
        assert delta.new_functions >= 2
        assert delta.after.total_functions > delta.before.total_functions

    def test_delta_without_before(self, analyzer):
        analyzer.take_after_snapshot()
        delta = analyzer.compute_delta()
        assert delta is None

    def test_delta_without_after(self, analyzer):
        analyzer.take_before_snapshot()
        delta = analyzer.compute_delta()
        assert delta is None

    def test_excludes_pycache(self, workspace):
        # Crear archivo en __pycache__
        pycache = workspace / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("x = 1\n")

        analyzer = CodeHealthAnalyzer(str(workspace))
        snapshot = analyzer.snapshot()
        # No debe incluir el archivo de __pycache__
        assert all("__pycache__" not in f.file for f in snapshot.functions)

    def test_handles_syntax_error(self, workspace):
        bad_file = workspace / "src" / "bad.py"
        bad_file.write_text("def foo(:\n  pass\n")

        analyzer = CodeHealthAnalyzer(str(workspace))
        # No debe crashear
        snapshot = analyzer.snapshot()
        assert snapshot.files_analyzed >= 3

    def test_handles_encoding_error(self, workspace):
        bad_file = workspace / "src" / "binary.py"
        bad_file.write_bytes(b"\xff\xfe\x00\x00invalid")

        analyzer = CodeHealthAnalyzer(str(workspace))
        # No debe crashear
        snapshot = analyzer.snapshot()
        assert snapshot.files_analyzed >= 3

    def test_empty_workspace(self, tmp_path):
        analyzer = CodeHealthAnalyzer(str(tmp_path))
        snapshot = analyzer.snapshot()
        assert snapshot.files_analyzed == 0
        assert snapshot.total_functions == 0


# -- Tests: Duplicación -------------------------------------------------------


class TestDuplication:
    """Tests para detección de duplicados."""

    def test_detects_duplicate_blocks(self, tmp_path):
        # Crear dos archivos con bloques idénticos
        block = "\n".join(f"    x = {i}" for i in range(DUPLICATE_BLOCK_SIZE + 2))
        (tmp_path / "file1.py").write_text(f"def a():\n{block}\n")
        (tmp_path / "file2.py").write_text(f"def b():\n{block}\n")

        analyzer = CodeHealthAnalyzer(str(tmp_path))
        snapshot = analyzer.snapshot()
        assert snapshot.duplicate_blocks > 0

    def test_no_duplicates_in_unique_code(self, tmp_path):
        (tmp_path / "unique1.py").write_text("def a():\n    return 1\n")
        (tmp_path / "unique2.py").write_text("def b():\n    return 2\n")

        analyzer = CodeHealthAnalyzer(str(tmp_path))
        snapshot = analyzer.snapshot()
        assert snapshot.duplicate_blocks == 0


# -- Tests: Constantes -------------------------------------------------------


class TestConstants:
    """Tests para constantes del módulo."""

    def test_long_function_threshold(self):
        assert LONG_FUNCTION_THRESHOLD == 50

    def test_complex_function_threshold(self):
        assert COMPLEX_FUNCTION_THRESHOLD == 10

    def test_duplicate_block_size(self):
        assert DUPLICATE_BLOCK_SIZE == 6


# -- Tests: AST Analysis -----------------------------------------------------


class TestASTAnalysis:
    """Tests para análisis AST específico."""

    def test_async_functions_detected(self, tmp_path):
        (tmp_path / "async_mod.py").write_text(
            "async def fetch():\n"
            "    return await something()\n"
        )
        analyzer = CodeHealthAnalyzer(str(tmp_path))
        snapshot = analyzer.snapshot()
        assert snapshot.total_functions >= 1
        assert any(f.name == "fetch" for f in snapshot.functions)

    def test_methods_detected(self, tmp_path):
        (tmp_path / "class_mod.py").write_text(
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "\n"
            "    def baz(self):\n"
            "        pass\n"
        )
        analyzer = CodeHealthAnalyzer(str(tmp_path))
        snapshot = analyzer.snapshot()
        names = [f.name for f in snapshot.functions]
        assert "bar" in names
        assert "baz" in names

    def test_custom_include_patterns(self, tmp_path):
        (tmp_path / "test.py").write_text("def t(): pass\n")
        (tmp_path / "test.txt").write_text("not python\n")

        analyzer = CodeHealthAnalyzer(str(tmp_path), include_patterns=["*.py"])
        snapshot = analyzer.snapshot()
        assert snapshot.total_functions >= 1

    def test_custom_exclude_dirs(self, tmp_path):
        mydir = tmp_path / "exclude_me"
        mydir.mkdir()
        (mydir / "mod.py").write_text("def excluded(): pass\n")
        (tmp_path / "included.py").write_text("def included(): pass\n")

        analyzer = CodeHealthAnalyzer(
            str(tmp_path),
            exclude_dirs=["exclude_me"],
        )
        snapshot = analyzer.snapshot()
        names = [f.name for f in snapshot.functions]
        assert "included" in names
        assert "excluded" not in names
