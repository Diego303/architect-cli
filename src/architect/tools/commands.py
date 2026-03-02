"""
Tool run_command — System command execution (F13).

Implements four security layers:
  1. Blocklist: regex patterns that are never executed
  2. Dynamic classification: safe / dev / dangerous -> confirmation policy
  3. Timeouts and output limit: prevents hung processes or saturated contexts
  4. Directory sandboxing: cwd always within the workspace
"""

import os
import re
import subprocess
from pathlib import Path

import structlog

from ..config.schema import CommandsConfig
from ..execution.validators import PathTraversalError, validate_path
from .base import BaseTool, ToolResult
from .schemas import RunCommandArgs

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Built-in security constants
# ---------------------------------------------------------------------------

# Regex patterns that are NEVER executed (Layer 1 — hard blocklist)
BLOCKED_PATTERNS: list[str] = [
    r"\brm\s+-rf\s+/",          # rm -rf / (system wipe)
    r"\brm\s+-rf\s+~",          # rm -rf ~ (user home wipe)
    r"\bsudo\b",                 # privilege escalation
    r"\bsu\b",                   # user switch
    r"\bchmod\s+777\b",          # insecure universal permissions
    r"\bcurl\b.*\|\s*(ba)?sh",   # curl | bash / curl | sh
    r"\bwget\b.*\|\s*(ba)?sh",   # wget | bash / wget | sh
    r"\bdd\b.*\bof=/dev/",       # direct write to devices
    r">\s*/dev/sd",              # redirect to disks
    r"\bmkfs\b",                 # format disks
    r"\b:()\s*\{\s*:\|:&\s*\};?:", # fork bomb
    r"\bpkill\s+-9\s+-f\b",     # kill all processes by name
    r"\bkillall\s+-9\b",        # kill all processes
]

# Base commands considered safe (read-only, no side effects)
SAFE_COMMANDS: set[str] = {
    "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
    "tree", "file", "which", "echo", "pwd", "env", "date",
    "python --version", "python3 --version",
    "node --version", "npm --version",
    "pip list", "pip show", "pip freeze",
    "git status", "git log", "git diff", "git show", "git branch",
    "git remote", "git fetch",
    "go version", "cargo --version", "rustc --version",
    "java -version", "mvn --version",
    "docker --version", "docker ps",
    "kubectl version", "kubectl get",
}

# Development command prefixes (semi-safe — dev tools)
DEV_PREFIXES: set[str] = {
    "pytest", "python -m pytest",
    "python -m mypy", "mypy",
    "python -m ruff", "ruff",
    "python -m black", "black --check",
    "python -m coverage", "coverage",
    "python -m unittest",
    "npm test", "npm run", "npm ci", "npm audit",
    "yarn test", "yarn run",
    "cargo test", "cargo build", "cargo check", "cargo clippy", "cargo fmt",
    "go test", "go build", "go vet", "go fmt", "golangci-lint",
    "make", "tsc", "eslint", "prettier --check",
    "pip install", "pip install -r",
    "npm install", "yarn install",
    "mvn test", "mvn compile", "mvn package",
    "gradle test", "gradle build",
}


class RunCommandTool(BaseTool):
    """Executes system commands with four security layers.

    Layer 1 — Blocklist: permanently blocked regex patterns (rm -rf /, sudo, etc.).
    Layer 2 — Classification: safe/dev/dangerous determines the confirmation policy.
    Layer 3 — Timeouts + output limit: prevents hung processes and saturated contexts.
    Layer 4 — Directory sandboxing: cwd always within workspace_root.
    """

    name = "run_command"
    description = (
        "Execute a command in the system shell. Useful for:\n"
        "- Running tests: pytest tests/, npm test, go test ./...\n"
        "- Type checking: mypy src/, tsc --noEmit\n"
        "- Linting: ruff check ., eslint src/\n"
        "- Building: make build, cargo build, tsc\n"
        "- Checking status: git status, git log --oneline -5\n"
        "- Running scripts: python script.py, bash setup.sh\n"
        "The command runs in the workspace directory (or in cwd if specified)."
    )
    sensitive = True  # Base: sensitive. The engine applies dynamic classification.
    args_model = RunCommandArgs

    def __init__(self, workspace_root: Path, commands_config: CommandsConfig) -> None:
        self.workspace_root = workspace_root
        self.commands_config = commands_config

        # Combine built-in patterns and commands with config extras
        self._blocked_patterns: list[str] = BLOCKED_PATTERNS + list(commands_config.blocked_patterns)
        self._safe_commands: set[str] = SAFE_COMMANDS | set(commands_config.safe_commands)
        self._max_lines: int = commands_config.max_output_lines
        self._default_timeout: int = commands_config.default_timeout

        self.log = logger.bind(component="run_command_tool")

    # ------------------------------------------------------------------
    # Sensitivity classification (also used by the engine)
    # ------------------------------------------------------------------

    def classify_sensitivity(self, command: str) -> str:
        """Classify the command for the confirmation policy.

        Returns:
            'safe'      — No confirmation required (read-only, info-gathering)
            'dev'       — Development tools (tests, linters, build)
            'dangerous' — Unknown; always confirm in interactive mode
        """
        cmd_stripped = command.strip()

        # Check safe commands (exact prefix match)
        if any(cmd_stripped.startswith(safe) for safe in self._safe_commands):
            return "safe"

        # Check dev prefixes
        if any(cmd_stripped.startswith(prefix) for prefix in DEV_PREFIXES):
            return "dev"

        return "dangerous"

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> ToolResult:
        """Execute the command with four security layers.

        Args:
            command: Command to execute (may include pipes and redirections)
            cwd: Working directory relative to workspace (optional)
            timeout: Timeout in seconds (uses config default_timeout if 30 and config differs)
            env: Additional environment variables

        Returns:
            ToolResult with stdout, stderr and exit_code. Never raises exceptions.
        """
        try:
            # Layer 1: Hard blocklist
            if self._is_blocked(command):
                self.log.warning("run_command.blocked", command=command[:100])
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Command blocked by security policy: '{command}'",
                )

            # Layer 2: allowed_only mode — rejects 'dangerous' in execute
            sensitivity = self.classify_sensitivity(command)
            if self.commands_config.allowed_only and sensitivity == "dangerous":
                self.log.warning("run_command.allowed_only_rejected", command=command[:100])
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"allowed_only mode active: only safe/dev commands are allowed. "
                        f"Command classified as 'dangerous': '{command}'"
                    ),
                )

            # Layer 3: Resolve working directory (within the workspace)
            work_dir = self._resolve_cwd(cwd)

            # Prepare environment (merge with current environ)
            proc_env = {**os.environ, **(env or {})}

            # Use config timeout if the caller uses the schema default (30s)
            # and the config has a different value
            effective_timeout = timeout if timeout != 30 else self._default_timeout

            self.log.info(
                "run_command.execute",
                command=command[:100],
                cwd=str(work_dir),
                timeout=effective_timeout,
            )

            # Execute the process (Layer 3 — timeout, Layer 4 — cwd sandboxing)
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                env=proc_env,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                stdin=subprocess.DEVNULL,  # Headless: never waits for input
            )

            # Truncate long outputs to avoid saturating the context
            stdout = self._truncate(result.stdout, self._max_lines)
            stderr = self._truncate(result.stderr, max(self._max_lines // 4, 10))

            # Compose structured output
            parts: list[str] = []
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            parts.append(f"exit_code: {result.returncode}")

            output = "\n\n".join(parts)
            success = result.returncode == 0

            self.log.info(
                "run_command.complete",
                command=command[:100],
                exit_code=result.returncode,
                success=success,
            )

            error_msg = None
            if not success:
                error_msg = stderr if stderr else f"Command failed with exit code {result.returncode}"

            return ToolResult(
                success=success,
                output=output,
                error=error_msg,
            )

        except subprocess.TimeoutExpired:
            self.log.warning("run_command.timeout", command=command[:100], timeout=effective_timeout)
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Command exceeded the {effective_timeout}s timeout: '{command}'. "
                    "Consider increasing the timeout or splitting the command into smaller parts."
                ),
            )
        except PathTraversalError as e:
            self.log.error("run_command.path_traversal", error=str(e))
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            self.log.error("run_command.unexpected_error", error=str(e), error_type=type(e).__name__)
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error executing command: {e}",
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_blocked(self, command: str) -> bool:
        """Check if the command matches any blocked pattern."""
        return any(re.search(pattern, command, re.IGNORECASE) for pattern in self._blocked_patterns)

    def _resolve_cwd(self, cwd: str | None) -> Path:
        """Resolve the working directory, ensuring it is within the workspace.

        If cwd is None, returns workspace_root.
        If cwd is a relative path, validates it against workspace_root.
        """
        if cwd is None:
            return self.workspace_root
        return validate_path(cwd, self.workspace_root)

    def _truncate(self, text: str, max_lines: int) -> str:
        """Truncate long text preserving the beginning and end.

        Keeps the first half and the last quarter of the output
        to preserve the most relevant context.
        """
        if not text:
            return text
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text

        head_count = max_lines // 2
        tail_count = max_lines // 4
        omitted = len(lines) - head_count - tail_count

        head = "\n".join(lines[:head_count])
        tail = "\n".join(lines[-tail_count:])
        return f"{head}\n\n[... {omitted} lines omitted ...]\n\n{tail}"
