"""
Ralph Loop Nativo — Iteración automática hasta que todos los checks pasen.

v4-C1: Killer feature. Cada iteración ejecuta un agente con contexto LIMPIO.
Solo se pasa al agente: spec original, diff acumulado, errores de la última
iteración, y un progress.md auto-generado.

Principio fundamental: el agente NO recibe el historial de conversación de
iteraciones anteriores. Esto evita contaminación de contexto y permite que
cada iteración aborde el problema con perspectiva fresca.
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
    """Configuración de una ejecución del Ralph Loop."""

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
    """Resultado de una iteración del Ralph Loop."""

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
    """Resultado completo del Ralph Loop."""

    iterations: list[LoopIteration] = field(default_factory=list)
    total_cost: float = 0.0
    total_duration: float = 0.0
    success: bool = False
    stop_reason: str = ""
    worktree_path: str = ""

    @property
    def total_iterations(self) -> int:
        """Número total de iteraciones completadas."""
        return len(self.iterations)


# Type alias for the agent factory callable.
# The factory receives keyword arguments and returns an object with a .run(prompt) method
# that returns an AgentState-like object.
AgentFactory = Callable[..., Any]


class RalphLoop:
    """Implementación nativa del Ralph Wiggum Loop.

    Cada iteración ejecuta el agente con contexto LIMPIO.
    Solo se pasa al agente:
    - La spec/task original
    - El diff acumulado de iteraciones anteriores
    - Los errores de la última iteración
    - Un progress.md auto-generado
    """

    def __init__(
        self,
        config: RalphConfig,
        agent_factory: AgentFactory,
        workspace_root: str | None = None,
    ):
        """Inicializa el Ralph Loop.

        Args:
            config: Configuración del loop.
            agent_factory: Callable que crea un AgentLoop fresco.
                Recibe kwargs: agent, model. Retorna objeto con .run(prompt) -> AgentState.
            workspace_root: Directorio raíz del workspace. None = cwd.
        """
        self.config = config
        self.agent_factory = agent_factory
        self.workspace_root = workspace_root or str(Path.cwd())
        self.iterations: list[LoopIteration] = []
        self.progress_file = Path(self.workspace_root) / ".architect" / "ralph-progress.md"
        self.log = logger.bind(component="ralph_loop")

    def run(self) -> RalphLoopResult:
        """Ejecuta el loop completo.

        Si use_worktree está habilitado, crea un git worktree aislado
        y ejecuta todas las iteraciones ahí. El worktree NO se limpia
        automáticamente — el usuario debe inspeccionarlo y mergear.

        Returns:
            RalphLoopResult con todas las iteraciones y métricas.
        """
        start_time = time.time()
        total_cost = 0.0
        result = RalphLoopResult()

        # Worktree: crear entorno aislado si se solicita
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

        # Capturar git state inicial
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

            # Verificar límites globales
            if self.config.max_cost and total_cost >= self.config.max_cost:
                self.log.info("ralph.budget_exhausted", cost=total_cost)
                result.stop_reason = "budget_exhausted"
                break

            elapsed = time.time() - start_time
            if self.config.max_time and elapsed >= self.config.max_time:
                self.log.info("ralph.timeout", elapsed=elapsed)
                result.stop_reason = "timeout"
                break

            # Construir prompt para esta iteración
            prompt = self._build_iteration_prompt(i, initial_ref)

            # Ejecutar agente con contexto LIMPIO
            iter_start = time.time()
            iteration = self._run_single_iteration(i, prompt)
            iteration.duration = time.time() - iter_start

            self.iterations.append(iteration)
            result.iterations.append(iteration)
            total_cost += iteration.cost

            # Actualizar progress
            self._update_progress(iteration)

            # Log resultado
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

            # Terminamos si checks pasan Y tag encontrado
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
            # Se agotaron las iteraciones
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
        """Ejecuta una sola iteración del loop.

        Args:
            iteration: Número de iteración (1-based).
            prompt: Prompt construido para esta iteración.

        Returns:
            LoopIteration con los resultados.
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

            # Ejecutar checks externos
            check_results = self._run_checks()
            all_passed = all(c["passed"] for c in check_results) if check_results else False

            # Buscar completion tag
            tag_found = self.config.completion_tag in final_response

            return LoopIteration(
                iteration=iteration,
                steps_taken=steps,
                cost=cost,
                duration=0.0,  # Se sobreescribe en run()
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
        """Construye el prompt para una iteración específica.

        Args:
            iteration: Número de iteración (1-based).
            initial_ref: Referencia git del estado inicial.

        Returns:
            Prompt completo para el agente.
        """
        parts: list[str] = []

        # 1. Task/spec original
        if self.config.spec_file:
            spec_path = Path(self.config.spec_file)
            if spec_path.exists():
                spec = spec_path.read_text(encoding="utf-8")
                parts.append(f"## Especificación de la Tarea\n\n{spec}")
            else:
                parts.append(f"## Tarea\n\n{self.config.task}")
        else:
            parts.append(f"## Tarea\n\n{self.config.task}")

        # 2. Instrucciones del Ralph Loop
        checks_list = "\n".join(f"- `{check}`" for check in self.config.checks)
        parts.append(
            f"## Instrucciones de Iteración\n\n"
            f"Esta es la **iteración {iteration}/{self.config.max_iterations}** "
            f"de un loop de corrección automática.\n\n"
            f"Cuando hayas completado TODA la tarea y estés seguro de que "
            f"todo funciona correctamente, incluye la palabra "
            f"`{self.config.completion_tag}` en tu respuesta final.\n\n"
            f"**Verificaciones que debe pasar tu código:**\n{checks_list}"
        )

        # 3. Diff acumulado (qué cambió en iteraciones anteriores)
        if iteration > 1:
            diff = self._get_accumulated_diff(initial_ref)
            if diff:
                truncated = diff[:5000]
                if len(diff) > 5000:
                    truncated += "\n... (diff truncado)"
                parts.append(
                    f"\n## Cambios de Iteraciones Anteriores\n\n"
                    f"```diff\n{truncated}\n```"
                )

        # 4. Errores de la última iteración
        if self.iterations:
            last = self.iterations[-1]
            failed_checks = [c for c in last.check_results if not c["passed"]]
            if failed_checks:
                parts.append("\n## Errores de la Iteración Anterior\n")
                for check in failed_checks:
                    output = check.get("output", "")[:2000]
                    parts.append(
                        f"### {check['name']}\n"
                        f"```\n{output}\n```"
                    )
            if last.error:
                parts.append(
                    f"\n## Error de Ejecución\n\n```\n{last.error[:1000]}\n```"
                )

        # 5. Progress file
        if self.progress_file.exists():
            progress_content = self.progress_file.read_text(encoding="utf-8")
            if progress_content.strip():
                parts.append(
                    f"\n## Progreso Acumulado\n\n{progress_content}"
                )

        return "\n\n".join(parts)

    def _run_checks(self) -> list[dict[str, Any]]:
        """Ejecuta los comandos de verificación.

        Returns:
            Lista de resultados: {name, passed, output}.
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
        """Obtiene el diff acumulado desde el estado inicial.

        Args:
            initial_ref: Referencia git del estado inicial.

        Returns:
            Diff como string, o cadena vacía si falla.
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
        """Captura el ref de git actual.

        Returns:
            Hash del commit HEAD actual, o 'HEAD' si falla.
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
        """Actualiza el archivo de progreso.

        Args:
            iteration: Resultado de la iteración a registrar.
        """
        try:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.progress_file.exists():
                self.progress_file.write_text(
                    "# Ralph Loop — Progreso\n\n"
                    "> Auto-generado. No editar manualmente.\n\n",
                    encoding="utf-8",
                )

            status = "Passed" if iteration.all_checks_passed else "Failed"
            lines = [
                f"### Iteración {iteration.iteration}\n",
                f"- Estado: {status}\n",
                f"- Pasos: {iteration.steps_taken}\n",
                f"- Coste: ${iteration.cost:.4f}\n",
                f"- Duración: {iteration.duration:.1f}s\n",
            ]
            if iteration.error:
                lines.append(f"- Error: {iteration.error[:200]}\n")
            for check in iteration.check_results:
                icon = "PASS" if check["passed"] else "FAIL"
                lines.append(f"- [{icon}] {check['name']}\n")
            lines.append("\n")

            with open(self.progress_file, "a", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            self.log.warning("ralph.progress_write_error", error=str(e))

    def _log_iteration_result(self, iteration: LoopIteration) -> None:
        """Log legible del resultado de la iteración.

        Args:
            iteration: Resultado de la iteración.
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
        """Crea un git worktree aislado para el loop.

        Crea un worktree en `<workspace>/../.architect-ralph-worktree`
        basado en HEAD actual.

        Returns:
            Path absoluto al worktree, o None si falla.
        """
        root = Path(self.workspace_root)
        worktree_path = root / WORKTREE_DIR

        try:
            # Limpiar worktree previo si existe
            if worktree_path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path), "--force"],
                    capture_output=True,
                    cwd=self.workspace_root,
                )

            # Eliminar branch vieja si existe
            subprocess.run(
                ["git", "branch", "-D", WORKTREE_BRANCH],
                capture_output=True,
                cwd=self.workspace_root,
            )

            # Crear worktree con nueva branch desde HEAD
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
        """Limpia el worktree y branch del Ralph Loop.

        Returns:
            True si se limpió correctamente.
        """
        root = Path(self.workspace_root)
        # Si estamos dentro del worktree, subir al root original
        worktree_path = root / WORKTREE_DIR
        if not worktree_path.exists():
            # Intentar desde el padre (por si workspace_root ES el worktree)
            worktree_path = root.parent / WORKTREE_DIR if WORKTREE_DIR in root.name else root / WORKTREE_DIR

        # Buscar el root real del repo (no el worktree)
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

        # Eliminar branch
        subprocess.run(
            ["git", "branch", "-D", WORKTREE_BRANCH],
            capture_output=True,
            cwd=repo_root,
        )

        # Prune worktrees huérfanos
        subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True,
            cwd=repo_root,
        )

        if removed:
            self.log.info("ralph.worktree_cleaned")
        return removed

    def cleanup_progress(self) -> None:
        """Elimina el archivo de progreso."""
        if self.progress_file.exists():
            self.progress_file.unlink()
