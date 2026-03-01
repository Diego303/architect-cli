"""
Parallel Runs + Worktrees — Ejecución paralela de agentes en worktrees git aislados.

v4-C2: Cada worker se ejecuta en un git worktree separado con aislamiento total.
Los workers se lanzan con ProcessPoolExecutor y cada uno invoca `architect run`
como subprocess en su propio worktree.
"""

import json
import logging
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from architect.logging.levels import HUMAN

logger = structlog.get_logger()
_hlog = logging.getLogger("architect.parallel")

__all__ = [
    "ParallelConfig",
    "ParallelRunner",
    "WorkerResult",
]

WORKTREE_PREFIX = ".architect-parallel"


@dataclass
class WorkerResult:
    """Resultado de un worker paralelo."""

    worker_id: int
    branch: str
    model: str
    status: str  # "success" | "partial" | "failed" | "timeout"
    steps: int
    cost: float
    duration: float
    files_modified: list[str]
    worktree_path: str


@dataclass
class ParallelConfig:
    """Configuración de ejecución paralela."""

    tasks: list[str]
    workers: int = 3
    models: list[str] | None = None
    agent: str = "build"
    max_steps: int = 50
    budget_per_worker: float | None = None
    timeout_per_worker: int | None = None
    base_branch: str | None = None
    config_path: str | None = None
    api_base: str | None = None


class ParallelRunner:
    """Ejecuta múltiples agentes en paralelo usando git worktrees.

    Cada worker:
    1. Tiene su propio git worktree (branch separada)
    2. Ejecuta `architect run` como subprocess
    3. Retorna WorkerResult con métricas

    Los worktrees NO se limpian automáticamente — el usuario los inspecciona
    y decide cuál mergear.
    """

    def __init__(self, config: ParallelConfig, workspace_root: str):
        """Inicializa el runner paralelo.

        Args:
            config: Configuración de la ejecución paralela.
            workspace_root: Directorio raíz del repositorio git.
        """
        self.config = config
        self.root = Path(workspace_root)
        self.worktrees: list[Path] = []
        self.log = logger.bind(component="parallel_runner")

    def run(self) -> list[WorkerResult]:
        """Ejecuta todos los workers en paralelo.

        Returns:
            Lista de WorkerResult ordenada por worker_id.
        """
        results: list[WorkerResult] = []

        try:
            # Crear worktrees
            self._create_worktrees()

            # Lanzar workers en paralelo
            with ProcessPoolExecutor(max_workers=self.config.workers) as executor:
                futures = {}
                for i in range(self.config.workers):
                    task = self._get_task_for_worker(i)
                    model = self._get_model_for_worker(i)
                    worktree = self.worktrees[i]
                    branch = f"architect/parallel-{i + 1}"

                    future = executor.submit(
                        _run_worker_process,
                        worker_id=i + 1,
                        task=task,
                        model=model,
                        worktree_path=str(worktree),
                        branch=branch,
                        agent=self.config.agent,
                        max_steps=self.config.max_steps,
                        budget=self.config.budget_per_worker,
                        timeout=self.config.timeout_per_worker,
                        config_path=self.config.config_path,
                        api_base=self.config.api_base,
                    )
                    futures[future] = i + 1

                for future in as_completed(futures):
                    worker_id = futures[future]
                    try:
                        result = future.result()
                        results.append(result)
                        self.log.info(
                            "parallel.worker_done",
                            worker=worker_id,
                            status=result.status,
                            cost=result.cost,
                            steps=result.steps,
                        )
                        _hlog.log(HUMAN, {
                            "event": "parallel.worker_done",
                            "worker": worker_id,
                            "model": result.model,
                            "status": result.status,
                            "cost": result.cost,
                            "duration": result.duration,
                        })
                    except Exception as e:
                        self.log.error(
                            "parallel.worker_error",
                            worker=worker_id,
                            error=str(e),
                        )
                        _hlog.log(HUMAN, {
                            "event": "parallel.worker_error",
                            "worker": worker_id,
                            "error": str(e),
                        })
                        results.append(WorkerResult(
                            worker_id=worker_id,
                            branch=f"architect/parallel-{worker_id}",
                            model="",
                            status="failed",
                            steps=0,
                            cost=0,
                            duration=0,
                            files_modified=[],
                            worktree_path="",
                        ))

        except Exception as e:
            self.log.error("parallel.run_error", error=str(e))

        succeeded = sum(1 for r in results if r.status == "success")
        failed_count = sum(1 for r in results if r.status in ("failed", "timeout"))
        total_cost = sum(r.cost for r in results)
        _hlog.log(HUMAN, {
            "event": "parallel.complete",
            "total_workers": len(results),
            "succeeded": succeeded,
            "failed": failed_count,
            "total_cost": total_cost,
        })

        return sorted(results, key=lambda r: r.worker_id)

    def _create_worktrees(self) -> None:
        """Crea git worktrees para cada worker."""
        base_branch = self.config.base_branch or self._get_current_branch()

        for i in range(self.config.workers):
            branch_name = f"architect/parallel-{i + 1}"
            worktree_path = self.root / f"{WORKTREE_PREFIX}-{i + 1}"

            # Limpiar si existe
            if worktree_path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path), "--force"],
                    capture_output=True,
                    cwd=str(self.root),
                )

            # Eliminar branch vieja si existe
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True,
                cwd=str(self.root),
            )

            # Crear branch y worktree
            result = subprocess.run(
                [
                    "git", "worktree", "add",
                    "-b", branch_name,
                    str(worktree_path),
                    base_branch,
                ],
                capture_output=True,
                text=True,
                cwd=str(self.root),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Error creando worktree {worktree_path}: {result.stderr}"
                )

            self.worktrees.append(worktree_path)
            self.log.info(
                "parallel.worktree_created",
                worker=i + 1,
                path=str(worktree_path),
                branch=branch_name,
            )

    def cleanup(self) -> int:
        """Limpia worktrees y branches de ejecuciones paralelas.

        Returns:
            Número de worktrees eliminados.
        """
        removed = 0

        # Buscar worktrees con nuestro prefijo
        for path in self.root.parent.glob(f"{self.root.name}/{WORKTREE_PREFIX}-*"):
            if path.is_dir():
                subprocess.run(
                    ["git", "worktree", "remove", str(path), "--force"],
                    capture_output=True,
                    cwd=str(self.root),
                )
                removed += 1

        # También buscar directamente en el root
        for path in self.root.glob(f"{WORKTREE_PREFIX}-*"):
            if path.is_dir():
                subprocess.run(
                    ["git", "worktree", "remove", str(path), "--force"],
                    capture_output=True,
                    cwd=str(self.root),
                )
                removed += 1

        # Limpiar branches
        result = subprocess.run(
            ["git", "branch", "--list", "architect/parallel-*"],
            capture_output=True,
            text=True,
            cwd=str(self.root),
        )
        for line in result.stdout.strip().split("\n"):
            branch = line.strip()
            if branch:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True,
                    cwd=str(self.root),
                )

        # Prune worktrees huérfanos
        subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True,
            cwd=str(self.root),
        )

        return removed

    def _get_task_for_worker(self, index: int) -> str:
        """Obtiene la tarea para un worker por su índice."""
        if index < len(self.config.tasks):
            return self.config.tasks[index]
        return self.config.tasks[0]  # Misma tarea para todos

    def _get_model_for_worker(self, index: int) -> str | None:
        """Obtiene el modelo para un worker por su índice."""
        if self.config.models and index < len(self.config.models):
            return self.config.models[index]
        return None

    def _get_current_branch(self) -> str:
        """Obtiene la branch actual del repositorio."""
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(self.root),
        )
        return result.stdout.strip() or "HEAD"

    @staticmethod
    def list_worktrees(workspace_root: str) -> list[dict[str, str]]:
        """Lista worktrees de ejecuciones paralelas.

        Args:
            workspace_root: Directorio raíz del repositorio.

        Returns:
            Lista de {path, branch} para cada worktree.
        """
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=workspace_root,
        )
        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                if current and WORKTREE_PREFIX in current.get("path", ""):
                    worktrees.append(current)
                current = {"path": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
        if current and WORKTREE_PREFIX in current.get("path", ""):
            worktrees.append(current)
        return worktrees


def _run_worker_process(
    worker_id: int,
    task: str,
    model: str | None,
    worktree_path: str,
    branch: str,
    agent: str,
    max_steps: int,
    budget: float | None,
    timeout: int | None,
    config_path: str | None = None,
    api_base: str | None = None,
) -> WorkerResult:
    """Ejecuta un worker en un worktree. Función top-level para ProcessPoolExecutor.

    Invoca `architect run` como subprocess en el worktree para aislamiento total.

    Args:
        worker_id: ID del worker (1-based).
        task: Tarea a ejecutar.
        model: Modelo LLM. None = default.
        worktree_path: Path al git worktree.
        branch: Nombre de la branch.
        agent: Agente a usar.
        max_steps: Máximo de pasos.
        budget: Presupuesto USD. None = sin límite.
        timeout: Timeout en segundos. None = 600.
        config_path: Path al archivo de configuración. None = default.
        api_base: URL base de la API del LLM. None = default.

    Returns:
        WorkerResult con métricas de la ejecución.
    """
    start = time.time()

    cmd = [
        "architect", "run", task,
        "--agent", agent,
        "--confirm-mode", "yolo",
        "--json",
        "--max-steps", str(max_steps),
    ]
    if model:
        cmd.extend(["--model", model])
    if budget:
        cmd.extend(["--budget", str(budget)])
    if timeout:
        cmd.extend(["--timeout", str(timeout)])
    if config_path:
        cmd.extend(["--config", config_path])
    if api_base:
        cmd.extend(["--api-base", api_base])

    effective_timeout = timeout or 600

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            cwd=worktree_path,
        )
        duration = time.time() - start

        # Parsear output JSON
        try:
            data = json.loads(proc.stdout)
            # Cost can be at top-level "cost" or nested in "costs.total_cost_usd"
            cost = data.get("cost", 0) or data.get("costs", {}).get("total_cost_usd", 0)
            return WorkerResult(
                worker_id=worker_id,
                branch=branch,
                model=model or "default",
                status=data.get("status", "unknown"),
                steps=data.get("steps", 0),
                cost=cost,
                duration=duration,
                files_modified=data.get("files_modified", []),
                worktree_path=worktree_path,
            )
        except (json.JSONDecodeError, KeyError):
            return WorkerResult(
                worker_id=worker_id,
                branch=branch,
                model=model or "default",
                status="partial" if proc.returncode == 0 else "failed",
                steps=0,
                cost=0,
                duration=duration,
                files_modified=[],
                worktree_path=worktree_path,
            )
    except subprocess.TimeoutExpired:
        return WorkerResult(
            worker_id=worker_id,
            branch=branch,
            model=model or "default",
            status="timeout",
            steps=0,
            cost=0,
            duration=time.time() - start,
            files_modified=[],
            worktree_path=worktree_path,
        )
