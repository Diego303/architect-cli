"""
Code Health Delta — Mide métricas de salud del código antes y después de la sesión.

v4-D2: Ejecuta análisis de métricas al inicio (snapshot before) y al final
(snapshot after) de la sesión, generando un delta report que muestra qué
mejoró y qué empeoró.

Métricas:
- Complejidad ciclomática (via radon, si está disponible)
- Líneas por función (análisis AST nativo)
- Detección básica de duplicación (hashing de bloques)

Dependencia opcional: radon (para complejidad ciclomática).
Sin radon, solo se calculan métricas basadas en AST.
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

# Intentar importar radon (dependencia opcional)
try:
    from radon.complexity import cc_visit  # type: ignore[import-untyped]

    RADON_AVAILABLE = True
except ImportError:
    RADON_AVAILABLE = False


@dataclass(frozen=True)
class FunctionMetric:
    """Métricas de una función individual."""

    file: str
    name: str
    lines: int
    complexity: int  # 0 si radon no está disponible


@dataclass
class HealthSnapshot:
    """Snapshot de métricas de salud del código en un momento dado.

    Attributes:
        files_analyzed: Número de archivos Python analizados.
        total_functions: Número total de funciones encontradas.
        avg_complexity: Complejidad ciclomática promedio.
        max_complexity: Complejidad ciclomática máxima.
        avg_function_lines: Promedio de líneas por función.
        max_function_lines: Máximo de líneas por función.
        long_functions: Funciones con más de 50 líneas.
        complex_functions: Funciones con complejidad > 10.
        duplicate_blocks: Número de bloques duplicados detectados.
        functions: Lista de métricas por función.
        radon_available: Si radon estaba disponible para el análisis.
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
    """Delta entre dos snapshots de salud.

    Valores negativos = mejora (menos complejidad, menos duplicación).
    Valores positivos = degradación.

    Attributes:
        before: Snapshot antes de la sesión.
        after: Snapshot después de la sesión.
        complexity_delta: Cambio en complejidad promedio.
        max_complexity_delta: Cambio en complejidad máxima.
        avg_lines_delta: Cambio en promedio de líneas por función.
        long_functions_delta: Cambio en funciones largas.
        complex_functions_delta: Cambio en funciones complejas.
        duplicate_blocks_delta: Cambio en bloques duplicados.
        new_functions: Funciones nuevas añadidas.
        removed_functions: Funciones eliminadas.
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
        """Genera un reporte legible del delta de salud.

        Returns:
            String con el reporte en formato markdown.
        """
        lines = ["## Code Health Delta\n"]

        if not self.before.radon_available:
            lines.append(
                "> *radon no disponible — complejidad ciclomática no medida. "
                "Instala con `pip install radon`.*\n"
            )

        lines.append("| Métrica | Antes | Después | Delta |")
        lines.append("|---------|-------|---------|-------|")

        # Complejidad promedio
        delta_str = self._format_delta(self.complexity_delta, invert=True)
        lines.append(
            f"| Complejidad promedio | {self.before.avg_complexity:.1f} "
            f"| {self.after.avg_complexity:.1f} | {delta_str} |"
        )

        # Complejidad máxima
        delta_str = self._format_delta(self.max_complexity_delta, invert=True)
        lines.append(
            f"| Complejidad máxima | {self.before.max_complexity} "
            f"| {self.after.max_complexity} | {delta_str} |"
        )

        # Líneas por función
        delta_str = self._format_delta(self.avg_lines_delta, invert=True)
        lines.append(
            f"| Líneas/función (promedio) | {self.before.avg_function_lines:.1f} "
            f"| {self.after.avg_function_lines:.1f} | {delta_str} |"
        )

        # Funciones largas
        delta_str = self._format_delta(self.long_functions_delta, invert=True)
        lines.append(
            f"| Funciones largas (>50 líneas) | {self.before.long_functions} "
            f"| {self.after.long_functions} | {delta_str} |"
        )

        # Funciones complejas
        delta_str = self._format_delta(self.complex_functions_delta, invert=True)
        lines.append(
            f"| Funciones complejas (>10) | {self.before.complex_functions} "
            f"| {self.after.complex_functions} | {delta_str} |"
        )

        # Duplicación
        delta_str = self._format_delta(self.duplicate_blocks_delta, invert=True)
        lines.append(
            f"| Bloques duplicados | {self.before.duplicate_blocks} "
            f"| {self.after.duplicate_blocks} | {delta_str} |"
        )

        lines.append("")

        # Totales
        lines.append(
            f"**Archivos analizados**: {self.after.files_analyzed} | "
            f"**Funciones**: {self.after.total_functions} "
            f"(+{self.new_functions} nuevas, -{self.removed_functions} eliminadas)"
        )

        return "\n".join(lines)

    @staticmethod
    def _format_delta(value: float | int, invert: bool = False) -> str:
        """Formatea un valor delta con indicador de mejora/degradación.

        Args:
            value: Valor del delta.
            invert: Si True, valores negativos son mejora.
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


# Umbral de líneas para considerar una función "larga"
LONG_FUNCTION_THRESHOLD = 50

# Umbral de complejidad para considerar una función "compleja"
COMPLEX_FUNCTION_THRESHOLD = 10

# Tamaño mínimo de bloque para detección de duplicados (líneas)
DUPLICATE_BLOCK_SIZE = 6


class CodeHealthAnalyzer:
    """Analiza métricas de salud del código Python en un workspace.

    Ejecuta análisis estático para generar snapshots de salud antes/después
    de la sesión del agente. El delta resultante indica si los cambios
    mejoraron o degradaron la calidad del código.
    """

    def __init__(
        self,
        workspace_root: str,
        include_patterns: list[str] | None = None,
        exclude_dirs: list[str] | None = None,
    ) -> None:
        """Inicializa el analizador.

        Args:
            workspace_root: Directorio raíz del workspace.
            include_patterns: Patrones glob para incluir (default: ['**/*.py']).
            exclude_dirs: Directorios a excluir del análisis.
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
        """Toma un snapshot de las métricas de salud del código.

        Returns:
            HealthSnapshot con todas las métricas calculadas.
        """
        files = self._discover_files()
        all_functions: list[FunctionMetric] = []
        all_block_hashes: list[str] = []

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Métricas AST (funciones y líneas)
            functions = self._analyze_functions_ast(str(file_path), content)
            all_functions.extend(functions)

            # Complejidad ciclomática (radon)
            if RADON_AVAILABLE:
                complexities = self._analyze_complexity_radon(content)
                # Enriquecer funciones con complejidad
                all_functions = self._merge_complexity(
                    all_functions, complexities, str(file_path)
                )

            # Detección de duplicados
            block_hashes = self._compute_block_hashes(content)
            all_block_hashes.extend(block_hashes)

        # Calcular estadísticas
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
        """Toma el snapshot 'antes' de la sesión.

        Returns:
            HealthSnapshot del estado actual.
        """
        self._before = self.snapshot()
        return self._before

    def take_after_snapshot(self) -> HealthSnapshot:
        """Toma el snapshot 'después' de la sesión.

        Returns:
            HealthSnapshot del estado actual.
        """
        self._after = self.snapshot()
        return self._after

    def compute_delta(self) -> HealthDelta | None:
        """Calcula el delta entre before y after snapshots.

        Returns:
            HealthDelta con las diferencias, o None si falta algún snapshot.
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
        """Descubre archivos Python en el workspace."""
        files: list[Path] = []
        for pattern in self.include_patterns:
            for path in self.root.glob(pattern):
                if not path.is_file():
                    continue
                # Excluir directorios prohibidos
                parts = set(path.relative_to(self.root).parts)
                if parts & self.exclude_dirs:
                    continue
                files.append(path)
        return sorted(files)

    def _analyze_functions_ast(
        self, file_path: str, content: str
    ) -> list[FunctionMetric]:
        """Analiza funciones usando AST nativo de Python.

        Args:
            file_path: Path del archivo.
            content: Contenido del archivo.

        Returns:
            Lista de FunctionMetric para cada función/método encontrado.
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
                    complexity=0,  # Se enriquece después con radon
                ))

        return functions

    def _analyze_complexity_radon(self, content: str) -> list[tuple[str, int]]:
        """Analiza complejidad ciclomática con radon.

        Args:
            content: Contenido del archivo Python.

        Returns:
            Lista de (nombre_función, complejidad).
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
        """Enriquece funciones con datos de complejidad de radon.

        Args:
            functions: Lista actual de FunctionMetric.
            complexities: Lista de (nombre, complejidad) de radon.
            file_path: Path del archivo analizado.

        Returns:
            Lista actualizada de FunctionMetric.
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
        """Calcula hashes de bloques de código para detectar duplicación.

        Usa una ventana deslizante de DUPLICATE_BLOCK_SIZE líneas.

        Args:
            content: Contenido del archivo.

        Returns:
            Lista de hashes MD5 de cada bloque.
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
        """Calcula estadísticas agregadas a partir de métricas individuales.

        Args:
            functions: Lista de métricas por función.
            block_hashes: Lista de hashes de bloques.
            files_count: Número de archivos analizados.

        Returns:
            HealthSnapshot con todas las estadísticas.
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

        # Duplicados: contar hashes que aparecen más de una vez
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
