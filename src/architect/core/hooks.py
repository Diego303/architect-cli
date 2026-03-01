"""
Hook System — Complete hook system for the agent lifecycle.

v4-A1: Replaces the PostEditHooks system from v3-M4 with a general
hook system covering the entire lifecycle: pre/post tool, pre/post LLM, session,
agent_complete, budget_warning, context_compress, on_error.

Hooks are executed as subprocesses (shell=True) and receive context
via env vars (ARCHITECT_EVENT, ARCHITECT_TOOL_NAME, etc.) and stdin JSON.

Exit code protocol:
- Exit 0  = ALLOW  (allow the action, optionally with additional context)
- Exit 2  = BLOCK  (block the action, stderr = reason)
- Other   = Hook error (logged as WARNING, does not block)

Invariants:
- Hooks NEVER break the loop (errors -> log + return ALLOW)
- Each hook's timeout is configurable (default 10s)
- Async hooks run in background without waiting for result
- If a pre-hook blocks, subsequent hooks for the same event are not executed
"""

import fnmatch
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()

__all__ = [
    "HookEvent",
    "HookDecision",
    "HookResult",
    "HookConfig",
    "HooksRegistry",
    "HookExecutor",
]


class HookEvent(Enum):
    """Lifecycle events where hooks can be injected."""

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    ON_ERROR = "on_error"
    BUDGET_WARNING = "budget_warning"
    CONTEXT_COMPRESS = "context_compress"
    AGENT_COMPLETE = "agent_complete"


class HookDecision(Enum):
    """Decision from a pre-hook."""

    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"


@dataclass
class HookResult:
    """Result of executing a hook."""

    decision: HookDecision = HookDecision.ALLOW
    reason: str | None = None
    additional_context: str | None = None
    updated_input: dict[str, Any] | None = None
    duration_ms: float = 0


@dataclass
class HookConfig:
    """Configuration for an individual hook.

    Attributes:
        command: Shell command to execute.
        matcher: Regex/glob of the tool name (for tool hooks). '*' matches all.
        file_patterns: Filter by file extension.
        timeout: Maximum execution seconds.
        is_async: If True, the hook runs in background without blocking.
        enabled: If False, the hook is ignored.
        name: Descriptive hook name.
    """

    command: str
    matcher: str = "*"
    file_patterns: list[str] = field(default_factory=list)
    timeout: int = 10
    is_async: bool = False
    enabled: bool = True
    name: str = ""


@dataclass
class HooksRegistry:
    """Complete registry of hooks by event."""

    hooks: dict[HookEvent, list[HookConfig]] = field(default_factory=dict)

    def get_hooks(self, event: HookEvent) -> list[HookConfig]:
        """Return active hooks for an event.

        Args:
            event: Lifecycle event.

        Returns:
            List of enabled HookConfig for that event.
        """
        return [h for h in self.hooks.get(event, []) if h.enabled]

    def has_hooks(self) -> bool:
        """Return True if at least one hook is registered."""
        return any(hooks for hooks in self.hooks.values())


class HookExecutor:
    """Executes hooks injecting context via env vars and stdin.

    The executor is the central point for hook execution. It handles:
    - Building the environment with ARCHITECT_* variables
    - Running the subprocess with timeout
    - Interpreting the exit code and stdout/stderr
    - Filtering hooks by matcher and file_patterns
    - Handling async hooks (background)
    """

    def __init__(self, registry: HooksRegistry, workspace_root: str) -> None:
        """Initialize the executor.

        Args:
            registry: Hook registry by event.
            workspace_root: Workspace root directory for CWD.
        """
        self.registry = registry
        self.workspace_root = workspace_root
        self.log = logger.bind(component="hooks")

    def _build_env(self, event: HookEvent, context: dict[str, Any]) -> dict[str, str]:
        """Build environment variables for the hook.

        Injects ARCHITECT_EVENT, ARCHITECT_WORKSPACE and each context key
        as ARCHITECT_{KEY.upper()}.

        Args:
            event: Event that triggered the hook.
            context: Context dictionary with event data.

        Returns:
            Dict of env vars for subprocess.
        """
        env = os.environ.copy()
        env["ARCHITECT_EVENT"] = event.value
        env["ARCHITECT_WORKSPACE"] = self.workspace_root
        for key, value in context.items():
            env_key = f"ARCHITECT_{key.upper()}"
            env[env_key] = str(value) if value is not None else ""
        return env

    def execute_hook(
        self,
        hook: HookConfig,
        event: HookEvent,
        context: dict[str, Any],
        stdin_data: dict[str, Any] | None = None,
    ) -> HookResult:
        """Execute an individual hook.

        Args:
            hook: Configuration of the hook to execute.
            event: Event that triggered the hook.
            context: Context dictionary for env vars.
            stdin_data: Optional JSON data to pass via stdin.

        Returns:
            HookResult with the decision and associated data.
        """
        start = time.monotonic()
        env = self._build_env(event, context)
        stdin_json = json.dumps(stdin_data) if stdin_data else ""

        try:
            proc = subprocess.run(
                hook.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=hook.timeout,
                cwd=self.workspace_root,
                env=env,
                input=stdin_json,
            )
            duration = (time.monotonic() - start) * 1000

            if proc.returncode == 0:
                result = self._parse_allow_output(proc.stdout)
                result.duration_ms = duration
                return result
            elif proc.returncode == 2:
                reason = proc.stderr.strip() or f"Hook '{hook.name}' blocked the action"
                return HookResult(
                    decision=HookDecision.BLOCK,
                    reason=reason,
                    duration_ms=duration,
                )
            else:
                self.log.warning(
                    "hook.error",
                    hook=hook.name,
                    exit_code=proc.returncode,
                    stderr=proc.stderr[:200],
                )
                return HookResult(duration_ms=duration)

        except subprocess.TimeoutExpired:
            self.log.warning("hook.timeout", hook=hook.name, timeout=hook.timeout)
            return HookResult(duration_ms=hook.timeout * 1000)
        except Exception as e:
            self.log.error("hook.exception", hook=hook.name, error=str(e))
            return HookResult()

    def _parse_allow_output(self, stdout: str) -> HookResult:
        """Parse JSON stdout from a hook that allows the action.

        If stdout is JSON with 'updatedInput', returns MODIFY.
        If it has 'additionalContext', attaches it.
        If not JSON, treats it as additional text context.

        Args:
            stdout: Standard output from the hook.

        Returns:
            HookResult with ALLOW or MODIFY.
        """
        if not stdout.strip():
            return HookResult(decision=HookDecision.ALLOW)
        try:
            data = json.loads(stdout)
            if "updatedInput" in data:
                return HookResult(
                    decision=HookDecision.MODIFY,
                    updated_input=data["updatedInput"],
                    additional_context=data.get("additionalContext"),
                )
            return HookResult(
                decision=HookDecision.ALLOW,
                additional_context=data.get("additionalContext"),
            )
        except json.JSONDecodeError:
            return HookResult(
                decision=HookDecision.ALLOW,
                additional_context=stdout.strip(),
            )

    def run_event(
        self,
        event: HookEvent,
        context: dict[str, Any],
        stdin_data: dict[str, Any] | None = None,
    ) -> list[HookResult]:
        """Execute all hooks for an event.

        Filters hooks by matcher (for tool hooks) and file_patterns.
        If a hook blocks, subsequent hooks are not executed.
        Async hooks run in background.

        Args:
            event: Lifecycle event.
            context: Context dictionary with event data.
            stdin_data: Optional JSON data to pass via stdin.

        Returns:
            List of HookResult (one per executed hook).
        """
        hooks = self.registry.get_hooks(event)
        results: list[HookResult] = []

        for hook in hooks:
            # Filter by matcher (for tool hooks)
            if hook.matcher != "*" and "tool_name" in context:
                if not re.match(hook.matcher, context["tool_name"]):
                    continue

            # Filter by file_patterns
            if hook.file_patterns and "file_path" in context:
                file_path = context["file_path"]
                if not any(fnmatch.fnmatch(file_path, p) for p in hook.file_patterns):
                    continue

            if hook.is_async:
                threading.Thread(
                    target=self.execute_hook,
                    args=(hook, event, context, stdin_data),
                    daemon=True,
                ).start()
                results.append(HookResult())
            else:
                result = self.execute_hook(hook, event, context, stdin_data)
                results.append(result)

                # If a pre-hook blocks, do not execute the following ones
                if result.decision == HookDecision.BLOCK:
                    break

        return results

    # ── Backward compatibility with PostEditHooks (v3-M4) ─────────────

    def run_post_edit(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """Execute post-edit hooks for backward compatibility with v3-M4.

        This allows existing code that called
        PostEditHooks.run_for_tool() to keep working with the new system.

        Args:
            tool_name: Name of the executed tool.
            args: Tool arguments.

        Returns:
            Text with concatenated results, or None if not applicable.
        """
        edit_tools = frozenset({"edit_file", "write_file", "apply_patch"})
        if tool_name not in edit_tools:
            return None

        file_path = args.get("path")
        if not file_path:
            return None

        context: dict[str, Any] = {
            "tool_name": tool_name,
            "file_path": str(file_path),
        }
        results = self.run_event(HookEvent.POST_TOOL_USE, context)

        # Collect additional context from hooks that produced output
        outputs: list[str] = []
        for result in results:
            if result.additional_context:
                outputs.append(result.additional_context)

        return "\n".join(outputs) if outputs else None
