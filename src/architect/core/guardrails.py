"""
Guardrails Engine — Deterministic security layer for the agent.

v4-A2: Guardrails are evaluated BEFORE user hooks and are
DETERMINISTIC rules that do not depend on the LLM and cannot be disabled.

Functions:
- check_file_access: Protect files (protected_files: write only,
  sensitive_files: read and write)
- check_command: Block dangerous commands (rm -rf /, git push --force, etc.)
  and detect shell reads (cat, head, tail) to sensitive files
- check_edit_limits: Limit modified files/lines
- check_code_rules: Scan written content against regex patterns
- run_quality_gates: Run checks on completion (lint, tests, typecheck)

Invariants:
- Guardrails NEVER break the loop (return allowed/reason tuples)
- Quality gates run as subprocesses with timeout
- Everything is logged with structlog
"""

import fnmatch
import os
import re
import subprocess
from pathlib import Path

import structlog

from ..config.schema import GuardrailsConfig

logger = structlog.get_logger()

__all__ = [
    "GuardrailsEngine",
]

# Regex to detect target files of shell redirections
# Captures: > file, >> file, >file, | tee file, | tee -a file
_REDIRECT_RE = re.compile(
    r">{1,2}\s*([^\s;|&]+)"        # > file or >> file
    r"|"
    r"\|\s*tee\s+(?:-a\s+)?([^\s;|&]+)"  # | tee file or | tee -a file
)

# Regex to detect commands that read files
# Captures: cat file, head file, head -n 10 file, tail -5 file, less file, more file
_READ_CMD_RE = re.compile(
    r"\b(?:cat|head|tail|less|more)\s+"
    r"(?:-[^\s]+(?:\s+\d+)?\s+)*"  # Optional flags with numeric args (-n 10, -5)
    r"([^\s;|&>]+)"                # Target file
)


def _extract_redirect_targets(command: str) -> list[str]:
    """Extract target files from shell redirections.

    Args:
        command: Full shell command.

    Returns:
        List of file paths that output is redirected to.
    """
    targets: list[str] = []
    for match in _REDIRECT_RE.finditer(command):
        target = match.group(1) or match.group(2)
        if target:
            # Strip quotes
            target = target.strip("'\"")
            targets.append(target)
    return targets


def _extract_read_targets(command: str) -> list[str]:
    """Extract files that a shell command attempts to read.

    Detects: cat file, head file, tail file, less file, more file.

    Args:
        command: Full shell command.

    Returns:
        List of file paths that the command reads.
    """
    targets: list[str] = []
    for match in _READ_CMD_RE.finditer(command):
        target = match.group(1)
        if target:
            target = target.strip("'\"")
            targets.append(target)
    return targets


class GuardrailsEngine:
    """Evaluates guardrails before allowing agent actions.

    Guardrails are the first line of defense: evaluated BEFORE
    user hooks in the ExecutionEngine.

    State tracking:
    - _files_modified: set of files modified during the session
    - _lines_changed: accumulated total of changed lines
    - _commands_executed: total commands executed
    - _edits_since_last_test: counter for require_test_after_edit
    """

    def __init__(self, config: GuardrailsConfig, workspace_root: str) -> None:
        """Initialize the guardrails engine.

        Args:
            config: Guardrails configuration from YAML.
            workspace_root: Workspace root directory.
        """
        self.config = config
        self.workspace_root = workspace_root
        self._files_modified: set[str] = set()
        self._lines_changed: int = 0
        self._commands_executed: int = 0
        self._edits_since_last_test: int = 0
        self.log = logger.bind(component="guardrails")

    def check_file_access(self, file_path: str, action: str) -> tuple[bool, str]:
        """Check if a file is protected or sensitive.

        - sensitive_files: blocks ALL actions (read and write).
        - protected_files: blocks only write actions.

        Args:
            file_path: Path of the file to access.
            action: Action type ('read_file', 'write_file', 'edit_file',
                    'delete_file', 'apply_patch').

        Returns:
            Tuple (allowed, reason). If allowed=False, reason explains why.
        """
        path_name = Path(file_path).name

        from ..i18n import t

        # 1. Sensitive files: block ALL actions (read + write)
        for pattern in self.config.sensitive_files:
            if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(
                path_name, pattern
            ):
                reason = t("guardrail.sensitive_blocked", file=file_path, pattern=pattern)
                self.log.warning(
                    "guardrail.sensitive_file_blocked",
                    file=file_path,
                    pattern=pattern,
                    action=action,
                )
                return False, reason

        # 2. Protected files: block write/edit/delete only
        _write_actions = ("write_file", "edit_file", "delete_file", "apply_patch")
        if action in _write_actions:
            for pattern in self.config.protected_files:
                if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(
                    path_name, pattern
                ):
                    reason = t("guardrail.protected_blocked", file=file_path, pattern=pattern)
                    self.log.warning("guardrail.file_blocked", file=file_path, pattern=pattern)
                    return False, reason

        return True, ""

    def check_command(self, command: str) -> tuple[bool, str]:
        """Check if a command is blocked.

        Checks three things:
        1. The command against the blocked_commands list (regex).
        2. Whether the command redirects output to a protected or sensitive file
           (shell redirection: >, >>, tee -> protected_files + sensitive_files).
        3. Whether the command reads a sensitive file
           (cat, head, tail, less, more -> sensitive_files).

        Args:
            command: Shell command to verify.

        Returns:
            Tuple (allowed, reason).
        """
        from ..i18n import t

        for pattern in self.config.blocked_commands:
            try:
                if re.search(pattern, command, re.IGNORECASE):
                    reason = t("guardrail.command_blocked", pattern=pattern)
                    self.log.warning("guardrail.command_blocked", command=command[:60], pattern=pattern)
                    return False, reason
            except re.error:
                self.log.warning("guardrail.invalid_regex", pattern=pattern)
                continue

        # Check that the command doesn't redirect output to protected/sensitive files
        write_patterns = list(self.config.protected_files) + list(self.config.sensitive_files)
        if write_patterns:
            redirect_targets = _extract_redirect_targets(command)
            for target in redirect_targets:
                for pattern in write_patterns:
                    if fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(
                        Path(target).name, pattern
                    ):
                        reason = t("guardrail.command_write_blocked", target=target, pattern=pattern)
                        self.log.warning(
                            "guardrail.command_redirect_blocked",
                            command=command[:60],
                            target=target,
                            pattern=pattern,
                        )
                        return False, reason

        # Check that the command doesn't read sensitive files (cat, head, tail, etc.)
        if self.config.sensitive_files:
            read_targets = _extract_read_targets(command)
            for target in read_targets:
                for pattern in self.config.sensitive_files:
                    if fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(
                        Path(target).name, pattern
                    ):
                        reason = t("guardrail.command_read_blocked", target=target, pattern=pattern)
                        self.log.warning(
                            "guardrail.command_read_blocked",
                            command=command[:60],
                            target=target,
                            pattern=pattern,
                        )
                        return False, reason

        if (
            self.config.max_commands_executed is not None
            and self._commands_executed >= self.config.max_commands_executed
        ):
            reason = t("guardrail.commands_limit", limit=self.config.max_commands_executed)
            self.log.warning("guardrail.commands_limit", count=self._commands_executed)
            return False, reason

        return True, ""

    def check_edit_limits(
        self, file_path: str, lines_added: int = 0, lines_removed: int = 0
    ) -> tuple[bool, str]:
        """Check modified files/lines limits.

        Args:
            file_path: Modified file.
            lines_added: Lines added in this edit.
            lines_removed: Lines removed in this edit.

        Returns:
            Tuple (allowed, reason).
        """
        from ..i18n import t

        self._files_modified.add(file_path)
        self._lines_changed += lines_added + lines_removed

        if (
            self.config.max_files_modified is not None
            and len(self._files_modified) > self.config.max_files_modified
        ):
            reason = t("guardrail.files_limit", limit=self.config.max_files_modified)
            self.log.warning(
                "guardrail.files_limit",
                count=len(self._files_modified),
                limit=self.config.max_files_modified,
            )
            return False, reason

        if (
            self.config.max_lines_changed is not None
            and self._lines_changed > self.config.max_lines_changed
        ):
            reason = t("guardrail.lines_limit", limit=self.config.max_lines_changed)
            self.log.warning(
                "guardrail.lines_limit",
                count=self._lines_changed,
                limit=self.config.max_lines_changed,
            )
            return False, reason

        return True, ""

    def check_code_rules(self, content: str, file_path: str) -> list[tuple[str, str]]:
        """Scan written content against code_rules.

        Args:
            content: Written file content.
            file_path: File path (for logging).

        Returns:
            List of (severity, message) for each violation found.
        """
        violations: list[tuple[str, str]] = []
        for rule in self.config.code_rules:
            try:
                if re.search(rule.pattern, content):
                    violations.append((rule.severity, rule.message))
                    self.log.info(
                        "guardrail.code_rule_violation",
                        file=file_path,
                        severity=rule.severity,
                        pattern=rule.pattern,
                    )
            except re.error:
                self.log.warning("guardrail.invalid_rule_regex", pattern=rule.pattern)
                continue
        return violations

    def record_command(self) -> None:
        """Record that a command was executed."""
        self._commands_executed += 1

    def record_edit(self) -> None:
        """Record an edit for require_test tracking."""
        self._edits_since_last_test += 1

    def should_force_test(self) -> bool:
        """True if require_test_after_edit and there are pending edits."""
        return self.config.require_test_after_edit and self._edits_since_last_test > 0

    def reset_test_counter(self) -> None:
        """Reset the edit counter since last test."""
        self._edits_since_last_test = 0

    def run_quality_gates(self) -> list[dict]:
        """Execute quality gates. Called when the agent declares completion.

        Returns:
            List of dicts with keys: name, passed, required, output, error.
        """
        results: list[dict] = []
        for gate in self.config.quality_gates:
            try:
                proc = subprocess.run(
                    gate.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=gate.timeout,
                    cwd=self.workspace_root,
                )
                passed = proc.returncode == 0
                results.append({
                    "name": gate.name,
                    "passed": passed,
                    "required": gate.required,
                    "output": proc.stdout[-500:] if not passed else "",
                    "error": proc.stderr[-300:] if not passed else "",
                })
                self.log.info(
                    "guardrail.quality_gate",
                    name=gate.name,
                    passed=passed,
                    required=gate.required,
                )
            except subprocess.TimeoutExpired:
                results.append({
                    "name": gate.name,
                    "passed": False,
                    "required": gate.required,
                    "output": f"Timeout after {gate.timeout}s",
                    "error": "",
                })
                self.log.warning("guardrail.quality_gate_timeout", name=gate.name)
        return results
