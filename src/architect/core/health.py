"""
Code Health Delta — Measures code health metrics before and after the session.

v4-D2: Runs metric analysis at the start (snapshot before) and end
(snapshot after) of the session, generating a delta report showing what
improved and what degraded.

Metrics:
- Cyclomatic complexity (via radon, if available)
- Lines per function (native AST analysis)
- Basic duplication detection (block hashing)

Optional dependency: radon (for cyclomatic complexity).
Without radon, only AST-based metrics are computed.
"""

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

__all__ = [
    "CodeHealthAnalyzer",
    "HealthSnapshot",
    "HealthDelta",
    "FunctionMetric",
]

# Try to import radon (optional dependency)
try:
    from radon.complexity import cc_visit  # type: ignore[import-untyped]

    RADON_AVAILABLE = True
except ImportError:
    RADON_AVAILABLE = False


@dataclass(frozen=True)
class FunctionMetric:
    """Metrics for an individual function."""

    file: str
    name: str
    lines: int
    complexity: int  # 0 if radon is not available


@dataclass
class HealthSnapshot:
    """Snapshot of code health metrics at a given point in time.

    Attributes:
        files_analyzed: Number of Python files analyzed.
        total_functions: Total number of functions found.
        avg_complexity: Average cyclomatic complexity.
        max_complexity: Maximum cyclomatic complexity.
        avg_function_lines: Average lines per function.
        max_function_lines: Maximum lines per function.
        long_functions: Functions with more than 50 lines.
        complex_functions: Functions with complexity > 10.
        duplicate_blocks: Number of duplicate blocks detected.
        functions: List of per-function metrics.
        radon_available: Whether radon was available for the analysis.
    """

    files_analyzed: int = 0
    total_functions: int = 0
    avg_complexity: float = 0.0
    max_complexity: int = 0
    avg_function_lines: float = 0.0
    max_function_lines: int = 0
    long_functions: int = 0
    complex_functions: int = 0
    duplicate_blocks: int = 0
    functions: list[FunctionMetric] = field(default_factory=list)
    radon_available: bool = False


@dataclass
class HealthDelta:
    """Delta between two health snapshots.

    Negative values = improvement (less complexity, less duplication).
    Positive values = degradation.

    Attributes:
        before: Snapshot before the session.
        after: Snapshot after the session.
        complexity_delta: Change in average complexity.
        max_complexity_delta: Change in maximum complexity.
        avg_lines_delta: Change in average lines per function.
        long_functions_delta: Change in long functions.
        complex_functions_delta: Change in complex functions.
        duplicate_blocks_delta: Change in duplicate blocks.
        new_functions: New functions added.
        removed_functions: Functions removed.
    """

    before: HealthSnapshot
    after: HealthSnapshot
    complexity_delta: float = 0.0
    max_complexity_delta: int = 0
    avg_lines_delta: float = 0.0
    long_functions_delta: int = 0
    complex_functions_delta: int = 0
    duplicate_blocks_delta: int = 0
    new_functions: int = 0
    removed_functions: int = 0

    def to_report(self) -> str:
        """Generate a human-readable health delta report.

        Returns:
            String with the report in markdown format.
        """
        from ..i18n import t

        lines = [t("health.title")]

        if not self.before.radon_available:
            lines.append(t("health.radon_notice"))

        col_m = t("health.col_metric")
        col_b = t("health.col_before")
        col_a = t("health.col_after")
        col_d = t("health.col_delta")
        lines.append(f"| {col_m} | {col_b} | {col_a} | {col_d} |")
        lines.append("|---------|-------|---------|-------|")

        def _row(label: str, before: str, after: str, delta_str: str) -> str:
            return f"| {label} | {before} | {after} | {delta_str} |"

        # Avg complexity
        delta_str = self._format_delta(self.complexity_delta, invert=True)
        lines.append(_row(
            t("health.avg_complexity"),
            f"{self.before.avg_complexity:.1f}",
            f"{self.after.avg_complexity:.1f}",
            delta_str,
        ))

        # Max complexity
        delta_str = self._format_delta(self.max_complexity_delta, invert=True)
        lines.append(_row(
            t("health.max_complexity"),
            str(self.before.max_complexity),
            str(self.after.max_complexity),
            delta_str,
        ))

        # Lines per function
        delta_str = self._format_delta(self.avg_lines_delta, invert=True)
        lines.append(_row(
            t("health.avg_lines"),
            f"{self.before.avg_function_lines:.1f}",
            f"{self.after.avg_function_lines:.1f}",
            delta_str,
        ))

        # Long functions
        delta_str = self._format_delta(self.long_functions_delta, invert=True)
        lines.append(_row(
            t("health.long_functions"),
            str(self.before.long_functions),
            str(self.after.long_functions),
            delta_str,
        ))

        # Complex functions
        delta_str = self._format_delta(self.complex_functions_delta, invert=True)
        lines.append(_row(
            t("health.complex_functions"),
            str(self.before.complex_functions),
            str(self.after.complex_functions),
            delta_str,
        ))

        # Duplicate blocks
        delta_str = self._format_delta(self.duplicate_blocks_delta, invert=True)
        lines.append(_row(
            t("health.duplicate_blocks"),
            str(self.before.duplicate_blocks),
            str(self.after.duplicate_blocks),
            delta_str,
        ))

        lines.append("")

        # Summary
        lines.append(
            t("health.files_analyzed", count=self.after.files_analyzed)
            + " | "
            + t(
                "health.functions_summary",
                total=self.after.total_functions,
                new=self.new_functions,
                removed=self.removed_functions,
            )
        )

        return "\n".join(lines)

    @staticmethod
    def _format_delta(value: float | int, invert: bool = False) -> str:
        """Format a delta value with improvement/degradation indicator.

        Args:
            value: Delta value.
            invert: If True, negative values indicate improvement.
        """
        if isinstance(value, float):
            formatted = f"{value:+.1f}"
        else:
            formatted = f"{value:+d}"

        if value == 0:
            return "="
        if invert:
            return formatted if value > 0 else formatted
        return formatted


# Line threshold to consider a function "long"
LONG_FUNCTION_THRESHOLD = 50

# Complexity threshold to consider a function "complex"
COMPLEX_FUNCTION_THRESHOLD = 10

# Minimum block size for duplicate detection (lines)
DUPLICATE_BLOCK_SIZE = 6


class CodeHealthAnalyzer:
    """Analyzes Python code health metrics in a workspace.

    Runs static analysis to generate health snapshots before/after
    the agent's session. The resulting delta indicates whether the changes
    improved or degraded code quality.
    """

    def __init__(
        self,
        workspace_root: str,
        include_patterns: list[str] | None = None,
        exclude_dirs: list[str] | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            workspace_root: Workspace root directory.
            include_patterns: Glob patterns to include (default: ['**/*.py']).
            exclude_dirs: Directories to exclude from analysis.
        """
        self.root = Path(workspace_root)
        self.include_patterns = include_patterns or ["**/*.py"]
        self.exclude_dirs = set(exclude_dirs or [
            ".git", "__pycache__", ".venv", "venv", "node_modules",
            ".architect", ".tox", ".mypy_cache", ".pytest_cache",
            "dist", "build", "*.egg-info",
        ])
        self._before: HealthSnapshot | None = None
        self._after: HealthSnapshot | None = None
        self.log = logger.bind(component="code_health")

    def snapshot(self) -> HealthSnapshot:
        """Take a snapshot of code health metrics.

        Returns:
            HealthSnapshot with all computed metrics.
        """
        files = self._discover_files()
        all_functions: list[FunctionMetric] = []
        all_block_hashes: list[str] = []

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # AST metrics (functions and lines)
            functions = self._analyze_functions_ast(str(file_path), content)
            all_functions.extend(functions)

            # Cyclomatic complexity (radon)
            if RADON_AVAILABLE:
                complexities = self._analyze_complexity_radon(content)
                # Enrich functions with complexity
                all_functions = self._merge_complexity(
                    all_functions, complexities, str(file_path)
                )

            # Duplicate detection
            block_hashes = self._compute_block_hashes(content)
            all_block_hashes.extend(block_hashes)

        # Compute statistics
        snapshot = self._compute_stats(all_functions, all_block_hashes, len(files))

        self.log.info(
            "health.snapshot",
            files=snapshot.files_analyzed,
            functions=snapshot.total_functions,
            avg_complexity=snapshot.avg_complexity,
            radon=RADON_AVAILABLE,
        )

        return snapshot

    def take_before_snapshot(self) -> HealthSnapshot:
        """Take the 'before' snapshot of the session.

        Returns:
            HealthSnapshot of the current state.
        """
        self._before = self.snapshot()
        return self._before

    def take_after_snapshot(self) -> HealthSnapshot:
        """Take the 'after' snapshot of the session.

        Returns:
            HealthSnapshot of the current state.
        """
        self._after = self.snapshot()
        return self._after

    def compute_delta(self) -> HealthDelta | None:
        """Compute the delta between before and after snapshots.

        Returns:
            HealthDelta with the differences, or None if a snapshot is missing.
        """
        if self._before is None or self._after is None:
            self.log.warning("health.delta_missing_snapshot")
            return None

        before_func_names = {
            (f.file, f.name) for f in self._before.functions
        }
        after_func_names = {
            (f.file, f.name) for f in self._after.functions
        }

        delta = HealthDelta(
            before=self._before,
            after=self._after,
            complexity_delta=self._after.avg_complexity - self._before.avg_complexity,
            max_complexity_delta=self._after.max_complexity - self._before.max_complexity,
            avg_lines_delta=self._after.avg_function_lines - self._before.avg_function_lines,
            long_functions_delta=self._after.long_functions - self._before.long_functions,
            complex_functions_delta=self._after.complex_functions - self._before.complex_functions,
            duplicate_blocks_delta=self._after.duplicate_blocks - self._before.duplicate_blocks,
            new_functions=len(after_func_names - before_func_names),
            removed_functions=len(before_func_names - after_func_names),
        )

        self.log.info(
            "health.delta",
            complexity_delta=delta.complexity_delta,
            long_functions_delta=delta.long_functions_delta,
            new_functions=delta.new_functions,
            removed_functions=delta.removed_functions,
        )

        return delta

    # ── Internal methods ────────────────────────────────────────────────

    def _discover_files(self) -> list[Path]:
        """Discover Python files in the workspace."""
        files: list[Path] = []
        for pattern in self.include_patterns:
            for path in self.root.glob(pattern):
                if not path.is_file():
                    continue
                # Exclude forbidden directories
                parts = set(path.relative_to(self.root).parts)
                if parts & self.exclude_dirs:
                    continue
                files.append(path)
        return sorted(files)

    def _analyze_functions_ast(
        self, file_path: str, content: str
    ) -> list[FunctionMetric]:
        """Analyze functions using Python's native AST.

        Args:
            file_path: File path.
            content: File content.

        Returns:
            List of FunctionMetric for each function/method found.
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        functions: list[FunctionMetric] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno)
                lines = end_line - node.lineno + 1
                functions.append(FunctionMetric(
                    file=file_path,
                    name=node.name,
                    lines=lines,
                    complexity=0,  # Enriched later with radon
                ))

        return functions

    def _analyze_complexity_radon(self, content: str) -> list[tuple[str, int]]:
        """Analyze cyclomatic complexity with radon.

        Args:
            content: Python file content.

        Returns:
            List of (function_name, complexity).
        """
        if not RADON_AVAILABLE:
            return []
        try:
            results = cc_visit(content)
            return [(r.name, r.complexity) for r in results]
        except Exception:
            return []

    def _merge_complexity(
        self,
        functions: list[FunctionMetric],
        complexities: list[tuple[str, int]],
        file_path: str,
    ) -> list[FunctionMetric]:
        """Enrich functions with complexity data from radon.

        Args:
            functions: Current list of FunctionMetric.
            complexities: List of (name, complexity) from radon.
            file_path: Path of the analyzed file.

        Returns:
            Updated list of FunctionMetric.
        """
        complexity_map = dict(complexities)
        result: list[FunctionMetric] = []

        for func in functions:
            if func.file == file_path and func.name in complexity_map:
                result.append(FunctionMetric(
                    file=func.file,
                    name=func.name,
                    lines=func.lines,
                    complexity=complexity_map[func.name],
                ))
            else:
                result.append(func)

        return result

    def _compute_block_hashes(self, content: str) -> list[str]:
        """Compute code block hashes to detect duplication.

        Uses a sliding window of DUPLICATE_BLOCK_SIZE lines.

        Args:
            content: File content.

        Returns:
            List of MD5 hashes for each block.
        """
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if len(lines) < DUPLICATE_BLOCK_SIZE:
            return []

        hashes: list[str] = []
        for i in range(len(lines) - DUPLICATE_BLOCK_SIZE + 1):
            block = "\n".join(lines[i:i + DUPLICATE_BLOCK_SIZE])
            block_hash = hashlib.md5(block.encode(), usedforsecurity=False).hexdigest()
            hashes.append(block_hash)

        return hashes

    def _compute_stats(
        self,
        functions: list[FunctionMetric],
        block_hashes: list[str],
        files_count: int,
    ) -> HealthSnapshot:
        """Compute aggregate statistics from individual metrics.

        Args:
            functions: List of per-function metrics.
            block_hashes: List of block hashes.
            files_count: Number of analyzed files.

        Returns:
            HealthSnapshot with all statistics.
        """
        if not functions:
            return HealthSnapshot(
                files_analyzed=files_count,
                radon_available=RADON_AVAILABLE,
            )

        complexities = [f.complexity for f in functions]
        line_counts = [f.lines for f in functions]

        avg_complexity = sum(complexities) / len(complexities) if complexities else 0.0
        max_complexity = max(complexities) if complexities else 0
        avg_lines = sum(line_counts) / len(line_counts) if line_counts else 0.0
        max_lines = max(line_counts) if line_counts else 0
        long_funcs = sum(1 for lc in line_counts if lc > LONG_FUNCTION_THRESHOLD)
        complex_funcs = sum(
            1 for c in complexities if c > COMPLEX_FUNCTION_THRESHOLD
        )

        # Duplicates: count hashes that appear more than once
        seen: set[str] = set()
        duplicates: set[str] = set()
        for h in block_hashes:
            if h in seen:
                duplicates.add(h)
            seen.add(h)

        return HealthSnapshot(
            files_analyzed=files_count,
            total_functions=len(functions),
            avg_complexity=round(avg_complexity, 2),
            max_complexity=max_complexity,
            avg_function_lines=round(avg_lines, 2),
            max_function_lines=max_lines,
            long_functions=long_funcs,
            complex_functions=complex_funcs,
            duplicate_blocks=len(duplicates),
            functions=functions,
            radon_available=RADON_AVAILABLE,
        )
