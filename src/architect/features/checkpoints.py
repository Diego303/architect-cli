"""
Checkpoints & Rollback — Restore points based on git commits.

v4-C4: Checkpoints are git commits with a special prefix that allow
restoring the workspace state to a previous point. They integrate with
the AgentLoop (checkpoint every N steps) and with pipelines (checkpoint per step).
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
    """Represents a checkpoint (git commit with a special prefix)."""

    step: int
    commit_hash: str
    message: str
    timestamp: float
    files_changed: list[str]

    def short_hash(self) -> str:
        """Return the first 7 characters of the hash."""
        return self.commit_hash[:7]


class CheckpointManager:
    """Manages checkpoints based on git commits.

    Checkpoints are created as git commits with the prefix
    'architect:checkpoint' in the message. This allows listing them
    and performing rollback using git log/reset.
    """

    def __init__(self, workspace_root: str):
        """Initialize the checkpoint manager.

        Args:
            workspace_root: Root directory of the git repository.
        """
        self.root = workspace_root
        self.log = logger.bind(component="checkpoint_manager")

    def create(self, step: int, message: str = "") -> Checkpoint | None:
        """Create a checkpoint (git commit with a special tag).

        Stage all changes, commit with prefix, and return the Checkpoint.

        Args:
            step: Agent step number.
            message: Additional descriptive message.

        Returns:
            Created Checkpoint, or None if there are no changes to commit.
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

        # Create commit
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

        # Get commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        commit_hash = hash_result.stdout.strip()

        # Get changed files
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
        """List all architect checkpoints.

        Returns:
            List of Checkpoints sorted from most recent to oldest.
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

            # Extract step number from the message
            step_match = re.search(r"step-(\d+)", parts[1])
            step = int(step_match.group(1)) if step_match else 0

            # Extract descriptive message (after " -- ")
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
                files_changed=[],  # We don't list files in the list operation
            ))

        return checkpoints

    def rollback(
        self,
        step: int | None = None,
        commit: str | None = None,
    ) -> bool:
        """Rollback to a specific checkpoint.

        Uses git reset --hard to revert to the checkpoint state.

        Args:
            step: Step number to revert to. Searches for the corresponding checkpoint.
            commit: Commit hash to revert to (takes priority over step).

        Returns:
            True if the rollback was successful.
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
        """Get the most recent checkpoint.

        Returns:
            Latest Checkpoint, or None if there are none.
        """
        checkpoints = self.list_checkpoints()
        return checkpoints[0] if checkpoints else None

    def has_changes_since(self, commit_hash: str) -> bool:
        """Check if there are changes since a commit.

        Args:
            commit_hash: Reference commit hash.

        Returns:
            True if there are modified files since that commit.
        """
        result = subprocess.run(
            ["git", "diff", "--name-only", commit_hash],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        return bool(result.stdout.strip())
