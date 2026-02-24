"""
Checkpoints & Rollback — Puntos de restauración basados en git commits.

v4-C4: Los checkpoints son git commits con prefijo especial que permiten
restaurar el estado del workspace a un punto anterior. Se integran con
el AgentLoop (checkpoint cada N steps) y con pipelines (checkpoint por step).
"""

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()

__all__ = [
    "CHECKPOINT_PREFIX",
    "Checkpoint",
    "CheckpointManager",
]

CHECKPOINT_PREFIX = "architect:checkpoint"


@dataclass(frozen=True)
class Checkpoint:
    """Representa un checkpoint (git commit con prefijo especial)."""

    step: int
    commit_hash: str
    message: str
    timestamp: float
    files_changed: list[str]

    def short_hash(self) -> str:
        """Retorna los primeros 7 caracteres del hash."""
        return self.commit_hash[:7]


class CheckpointManager:
    """Gestiona checkpoints basados en git commits.

    Los checkpoints se crean como git commits con el prefijo
    'architect:checkpoint' en el mensaje. Esto permite listarlos
    y hacer rollback usando git log/reset.
    """

    def __init__(self, workspace_root: str):
        """Inicializa el manager de checkpoints.

        Args:
            workspace_root: Directorio raíz del repositorio git.
        """
        self.root = workspace_root
        self.log = logger.bind(component="checkpoint_manager")

    def create(self, step: int, message: str = "") -> Checkpoint | None:
        """Crea un checkpoint (git commit con tag especial).

        Stage all changes, commit con prefijo, y retorna el Checkpoint.

        Args:
            step: Número de step del agente.
            message: Mensaje descriptivo adicional.

        Returns:
            Checkpoint creado, o None si no hay cambios para commitear.
        """
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            cwd=self.root,
        )

        # Check if there are changes to commit
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        if not status.stdout.strip():
            self.log.debug("checkpoint.nothing_to_commit", step=step)
            return None

        # Crear commit
        commit_msg = f"{CHECKPOINT_PREFIX}:step-{step}"
        if message:
            commit_msg += f" -- {message}"

        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        if result.returncode != 0:
            self.log.warning(
                "checkpoint.commit_failed",
                step=step,
                error=result.stderr[:200],
            )
            return None

        # Obtener hash del commit
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        commit_hash = hash_result.stdout.strip()

        # Obtener archivos cambiados
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        files = [
            f for f in diff_result.stdout.strip().split("\n") if f
        ]

        checkpoint = Checkpoint(
            step=step,
            commit_hash=commit_hash,
            message=message,
            timestamp=time.time(),
            files_changed=files,
        )

        self.log.info(
            "checkpoint.created",
            step=step,
            hash=checkpoint.short_hash(),
            files=len(files),
        )
        return checkpoint

    def list_checkpoints(self) -> list[Checkpoint]:
        """Lista todos los checkpoints de architect.

        Returns:
            Lista de Checkpoints ordenada del más reciente al más antiguo.
        """
        result = subprocess.run(
            [
                "git", "log", "--oneline",
                f"--grep={CHECKPOINT_PREFIX}",
                "--format=%H|%s|%at",
            ],
            capture_output=True,
            text=True,
            cwd=self.root,
        )

        checkpoints: list[Checkpoint] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue

            # Extraer step number del mensaje
            step_match = re.search(r"step-(\d+)", parts[1])
            step = int(step_match.group(1)) if step_match else 0

            # Extraer mensaje descriptivo (después de " -- ")
            msg_parts = parts[1].split(" -- ", 1)
            message = msg_parts[1] if len(msg_parts) > 1 else ""

            try:
                ts = float(parts[2])
            except ValueError:
                ts = 0.0

            checkpoints.append(Checkpoint(
                step=step,
                commit_hash=parts[0],
                message=message,
                timestamp=ts,
                files_changed=[],  # No listamos files en el list
            ))

        return checkpoints

    def rollback(
        self,
        step: int | None = None,
        commit: str | None = None,
    ) -> bool:
        """Rollback a un checkpoint específico.

        Usa git reset --hard para volver al estado del checkpoint.

        Args:
            step: Número de step al que volver. Busca el checkpoint correspondiente.
            commit: Hash del commit al que volver (tiene prioridad sobre step).

        Returns:
            True si el rollback fue exitoso.
        """
        if commit:
            target = commit
        elif step is not None:
            checkpoints = self.list_checkpoints()
            target_cp = next((c for c in checkpoints if c.step == step), None)
            if not target_cp:
                self.log.error("checkpoint.not_found", step=step)
                return False
            target = target_cp.commit_hash
        else:
            self.log.error("checkpoint.no_target_specified")
            return False

        result = subprocess.run(
            ["git", "reset", "--hard", target],
            capture_output=True,
            text=True,
            cwd=self.root,
        )

        if result.returncode == 0:
            self.log.info("checkpoint.rollback_success", target=target[:7])
            return True
        else:
            self.log.error(
                "checkpoint.rollback_failed",
                target=target[:7],
                error=result.stderr[:200],
            )
            return False

    def get_latest(self) -> Checkpoint | None:
        """Obtiene el checkpoint más reciente.

        Returns:
            Último Checkpoint, o None si no hay ninguno.
        """
        checkpoints = self.list_checkpoints()
        return checkpoints[0] if checkpoints else None

    def has_changes_since(self, commit_hash: str) -> bool:
        """Verifica si hay cambios desde un commit.

        Args:
            commit_hash: Hash del commit de referencia.

        Returns:
            True si hay archivos modificados desde ese commit.
        """
        result = subprocess.run(
            ["git", "diff", "--name-only", commit_hash],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        return bool(result.stdout.strip())
