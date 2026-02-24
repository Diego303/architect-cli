"""
Competitive Eval — Ejecuta la misma tarea con múltiples modelos y genera un report comparativo.

v4-D3: Wrapper sobre ParallelRunner que configura un worker por modelo,
ejecuta la misma tarea en todos, y recolecta métricas comparativas:
tests pasados, errores lint, pasos, coste, tiempo.

Requiere: ParallelRunner (v4-C2).
"""

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from .parallel import ParallelConfig, ParallelRunner, WorkerResult

logger = structlog.get_logger()

__all__ = [
    "CompetitiveConfig",
    "CompetitiveResult",
    "CompetitiveEval",
]


@dataclass
class CompetitiveResult:
    """Resultado de una evaluación competitiva de un modelo.

    Attributes:
        model: Nombre del modelo evaluado.
        status: Estado final (success, partial, failed, timeout).
        steps: Pasos ejecutados por el agente.
        cost: Coste en USD.
        duration: Duración en segundos.
        files_modified: Archivos modificados por el agente.
        checks_passed: Número de checks que pasaron.
        checks_total: Número total de checks.
        check_details: Detalle de cada check {name, passed, output}.
        worktree_path: Path al worktree con los cambios.
        branch: Branch de git donde están los cambios.
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
    """Configuración para evaluación competitiva.

    Attributes:
        task: Tarea a ejecutar con todos los modelos.
        models: Lista de modelos a comparar.
        checks: Comandos de verificación a ejecutar después.
        agent: Agente a usar (default: build).
        max_steps: Máximo de pasos por modelo.
        budget_per_model: Presupuesto USD por modelo.
        timeout_per_model: Timeout en segundos por modelo.
    """

    task: str
    models: list[str]
    checks: list[str] = field(default_factory=list)
    agent: str = "build"
    max_steps: int = 50
    budget_per_model: float | None = None
    timeout_per_model: int | None = None


class CompetitiveEval:
    """Ejecuta evaluación competitiva de múltiples modelos.

    Usa ParallelRunner para ejecutar la misma tarea con diferentes modelos
    en worktrees aislados, luego ejecuta los checks en cada worktree
    y genera un report comparativo.
    """

    def __init__(self, config: CompetitiveConfig, workspace_root: str) -> None:
        """Inicializa la evaluación competitiva.

        Args:
            config: Configuración de la evaluación.
            workspace_root: Directorio raíz del repositorio.
        """
        self.config = config
        self.workspace_root = workspace_root
        self.log = logger.bind(component="competitive_eval")

    def run(self) -> list[CompetitiveResult]:
        """Ejecuta la evaluación competitiva.

        Returns:
            Lista de CompetitiveResult, uno por modelo, ordenada por modelo.
        """
        self.log.info(
            "competitive.start",
            models=self.config.models,
            task=self.config.task[:100],
            checks=self.config.checks,
        )

        # Configurar ParallelRunner: misma tarea, un worker por modelo
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

        # Ejecutar checks en cada worktree
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

        return sorted(results, key=lambda r: r.model)

    def _run_checks_in_worktree(
        self, worktree_path: str
    ) -> list[dict[str, str | bool]]:
        """Ejecuta los checks configurados en un worktree.

        Args:
            worktree_path: Path al worktree donde ejecutar.

        Returns:
            Lista de {name, passed, output} por check.
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
        """Genera un reporte comparativo en formato markdown.

        Args:
            results: Lista de resultados de la evaluación.

        Returns:
            String con el reporte en formato markdown.
        """
        lines = [
            "# Competitive Eval Report\n",
            f"**Tarea**: {self.config.task}\n",
            f"**Modelos**: {len(results)}\n",
        ]

        if self.config.checks:
            lines.append(f"**Checks**: {', '.join(self.config.checks)}\n")

        # Tabla comparativa
        lines.append("\n## Resultados\n")
        lines.append(
            "| Modelo | Estado | Pasos | Coste | Tiempo | "
            "Checks | Archivos |"
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
        lines.append("\n## Ranking\n")
        ranked = self._rank_results(results)
        for i, (r, score) in enumerate(ranked, 1):
            medal = ["1st", "2nd", "3rd"][i - 1] if i <= 3 else f"{i}th"
            lines.append(
                f"{i}. **{medal}** — {r.model} (score: {score:.1f})"
            )

        # Detalle de checks por modelo
        if self.config.checks:
            lines.append("\n## Detalle de Checks\n")
            for r in results:
                lines.append(f"\n### {r.model}\n")
                if not r.check_details:
                    lines.append("No se ejecutaron checks.\n")
                    continue
                for check in r.check_details:
                    icon = "pass" if check["passed"] else "FAIL"
                    lines.append(f"- [{icon}] `{check['name']}`")
                    if not check["passed"] and check.get("output"):
                        output = str(check["output"])[:200]
                        lines.append(f"  ```\n  {output}\n  ```")

        # Worktrees para inspección
        lines.append("\n## Worktrees\n")
        lines.append("Para inspeccionar los resultados de cada modelo:\n")
        for r in results:
            if r.worktree_path:
                lines.append(f"- **{r.model}**: `{r.worktree_path}` (branch: `{r.branch}`)")

        return "\n".join(lines)

    def _rank_results(
        self, results: list[CompetitiveResult]
    ) -> list[tuple[CompetitiveResult, float]]:
        """Rankea resultados usando un score compuesto.

        Score = (checks_passed/total * 40) + (status_score * 30) +
                (efficiency_score * 20) + (cost_score * 10)

        Args:
            results: Lista de resultados.

        Returns:
            Lista de (resultado, score) ordenada por score descendente.
        """
        scored: list[tuple[CompetitiveResult, float]] = []

        max_cost = max((r.cost for r in results if r.cost > 0), default=1.0)
        max_steps = max((r.steps for r in results if r.steps > 0), default=1)

        for r in results:
            # Checks score (0-40)
            if r.checks_total > 0:
                checks_score = (r.checks_passed / r.checks_total) * 40
            else:
                checks_score = 20.0  # Neutral si no hay checks

            # Status score (0-30)
            status_scores = {
                "success": 30.0,
                "partial": 15.0,
                "failed": 0.0,
                "timeout": 5.0,
            }
            status_score = status_scores.get(r.status, 0.0)

            # Efficiency score (0-20): menos pasos es mejor
            if r.steps > 0 and max_steps > 0:
                efficiency_score = (1 - r.steps / max_steps) * 20
            else:
                efficiency_score = 0.0

            # Cost score (0-10): menos coste es mejor
            if r.cost > 0 and max_cost > 0:
                cost_score = (1 - r.cost / max_cost) * 10
            else:
                cost_score = 10.0  # Sin coste = máximo score

            total = checks_score + status_score + efficiency_score + cost_score
            scored.append((r, round(total, 1)))

        return sorted(scored, key=lambda x: x[1], reverse=True)

    @staticmethod
    def _status_icon(status: str) -> str:
        """Retorna icono según estado."""
        icons = {
            "success": "OK",
            "partial": "WARN",
            "failed": "FAIL",
            "timeout": "TIME",
        }
        return icons.get(status, "?")
