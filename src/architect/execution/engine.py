"""
Execution Engine - Central orchestrator for tool execution.

The ExecutionEngine is the mandatory pass-through point for all tool
execution. Applies validation, confirmation policies, dry-run and logging.

v3-M4: Added support for PostEditHooks (post-edit auto-verification).
v4-A1: Integration with the complete hook system (pre/post tool hooks).
"""

from typing import TYPE_CHECKING, Any

import structlog

from ..config.schema import AppConfig
from ..tools.base import BaseTool, ToolResult
from ..tools.registry import ToolNotFoundError, ToolRegistry
from .policies import ConfirmationPolicy, NoTTYError

if TYPE_CHECKING:
    from ..core.guardrails import GuardrailsEngine
    from ..core.hooks import HookExecutor

logger = structlog.get_logger()


class ExecutionEngine:
    """Tool execution engine with validation and policies.

    The ExecutionEngine applies a complete pipeline to each tool call:
    1. Find tool in registry
    2. Validate arguments (Pydantic)
    3. Validate paths if applicable (already within each tool)
    4. Apply confirmation policy
    5. Execute (or simulate in dry-run)
    6. Log result
    7. Return result (never exception)

    Key features:
    - NEVER raises exceptions to the caller (always returns ToolResult)
    - Supports dry-run (simulation without side effects)
    - Applies configurable confirmation policies
    - Structured logging of all operations
    - Integrated pre/post tool hooks (v4-A1)
    """

    def __init__(
        self,
        registry: ToolRegistry,
        config: AppConfig,
        confirm_mode: str | None = None,
        hook_executor: "HookExecutor | None" = None,
        guardrails: "GuardrailsEngine | None" = None,
    ):
        """Initialize the execution engine.

        Args:
            registry: ToolRegistry with available tools
            config: Complete application configuration
            confirm_mode: Confirmation mode override (optional)
            hook_executor: HookExecutor for pre/post hooks (v4-A1)
            guardrails: GuardrailsEngine for deterministic security (v4-A2)
        """
        self.registry = registry
        self.config = config
        self.dry_run = False
        self.hook_executor = hook_executor
        self.guardrails = guardrails

        # Determine confirmation mode
        # Priority: confirm_mode argument > agent config > default
        mode = confirm_mode or "confirm-sensitive"
        self.policy = ConfirmationPolicy(mode)

        self.log = logger.bind(component="execution_engine")

    def execute_tool_call(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool call with the complete pipeline.

        This is the main method of the ExecutionEngine. It applies all
        validations and policies before executing the tool.

        Args:
            tool_name: Name of the tool to execute
            args: Dictionary with unvalidated arguments

        Returns:
            ToolResult with the execution result or error

        Note:
            This method NEVER raises exceptions. All errors are
            caught and returned as ToolResult with success=False.
        """
        self.log.info(
            "tool.call.start",
            tool=tool_name,
            args=self._sanitize_args_for_log(args),
            dry_run=self.dry_run,
        )

        try:
            # 1. Find tool in registry
            try:
                tool = self.registry.get(tool_name)
            except ToolNotFoundError as e:
                self.log.error("tool.not_found", tool=tool_name)
                return ToolResult(
                    success=False,
                    output="",
                    error=str(e),
                )

            # 2. Validate arguments with Pydantic
            try:
                validated_args = tool.validate_args(args)
            except Exception as e:
                self.log.error("tool.validation_error", tool=tool_name, error=str(e))
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Invalid arguments: {e}",
                )

            # 3. Apply confirmation policy
            # run_command uses dynamic classification by command (not just tool.sensitive)
            if tool.name == "run_command":
                command_str = validated_args.model_dump().get("command", "")
                needs_confirm = self._should_confirm_command(command_str, tool)
            else:
                needs_confirm = self.policy.should_confirm(tool)

            if needs_confirm:
                try:
                    confirmed = self.policy.request_confirmation(
                        tool_name,
                        args,
                        dry_run=self.dry_run,
                    )

                    if not confirmed:
                        self.log.info("tool.cancelled", tool=tool_name)
                        return ToolResult(
                            success=False,
                            output="",
                            error="Operation cancelled by the user",
                        )

                except NoTTYError as e:
                    self.log.error("tool.no_tty", tool=tool_name)
                    return ToolResult(
                        success=False,
                        output="",
                        error=str(e),
                    )

            # 4. Execute (or simulate in dry-run)
            if self.dry_run:
                self.log.info(
                    "tool.dry_run",
                    tool=tool_name,
                    args=validated_args.model_dump(),
                )
                return ToolResult(
                    success=True,
                    output=f"[DRY-RUN] Would execute {tool_name} with args: {validated_args.model_dump()}",
                )

            # 5. Actual execution
            try:
                result = tool.execute(**validated_args.model_dump())
            except Exception as e:
                # Tools should NOT raise exceptions, but
                # we catch just in case (defensive programming)
                self.log.error(
                    "tool.execution_error",
                    tool=tool_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                result = ToolResult(
                    success=False,
                    output="",
                    error=f"Internal tool error: {e}",
                )

            # 6. Record edit for guardrails tracking
            if result.success and self.guardrails and tool_name in ("write_file", "edit_file"):
                self.guardrails.record_edit()

            # 7. Log result
            self.log.info(
                "tool.call.complete",
                tool=tool_name,
                success=result.success,
                output_length=len(result.output) if result.output else 0,
                has_error=result.error is not None,
            )

            return result

        except Exception as e:
            # Last resort catch for unexpected errors
            # in the ExecutionEngine itself
            self.log.error(
                "engine.unexpected_error",
                tool=tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error in the execution engine: {e}",
            )

    def check_guardrails(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> ToolResult | None:
        """Check guardrails BEFORE executing a tool (v4-A2).

        Guardrails are evaluated before user hooks.
        They are the deterministic security layer that the LLM cannot bypass.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Tool arguments.

        Returns:
            ToolResult with error if a guardrail blocked, None if all OK.
        """
        if not self.guardrails:
            return None

        # Check protected/sensitive files
        if tool_name in ("read_file", "write_file", "edit_file", "delete_file", "apply_patch"):
            file_path = tool_input.get("path", "")
            allowed, reason = self.guardrails.check_file_access(file_path, tool_name)
            if not allowed:
                return ToolResult(success=False, output=f"Guardrail: {reason}")

        # Check blocked commands
        if tool_name == "run_command":
            command = tool_input.get("command", "")
            allowed, reason = self.guardrails.check_command(command)
            if not allowed:
                return ToolResult(success=False, output=f"Guardrail: {reason}")
            self.guardrails.record_command()

        # Check edit limits
        if tool_name in ("write_file", "edit_file", "apply_patch"):
            file_path = tool_input.get("path", "")
            content = tool_input.get("content", "")
            lines = content.count("\n") + 1 if content else 0
            allowed, reason = self.guardrails.check_edit_limits(file_path, lines_added=lines)
            if not allowed:
                return ToolResult(success=False, output=f"Guardrail: {reason}")

        return None

    def check_code_rules(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> list[str]:
        """Scan content against code_rules BEFORE executing (v4-A2).

        Args:
            tool_name: Name of the tool executed.
            tool_input: Tool arguments.

        Returns:
            List of warning/block messages.
        """
        if not self.guardrails:
            return []

        if tool_name not in ("write_file", "edit_file"):
            return []

        content = tool_input.get("content", "") or tool_input.get("new_str", "")
        if not content:
            return []

        file_path = tool_input.get("path", "")
        violations = self.guardrails.check_code_rules(content, file_path)

        messages: list[str] = []
        for severity, msg in violations:
            if severity == "block":
                messages.append(f"BLOCKED by code rule: {msg}")
            else:
                messages.append(f"Code rule warning: {msg}")

        return messages

    def run_pre_tool_hooks(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> ToolResult | dict[str, Any] | None:
        """Execute pre-tool hooks (v4-A1).

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Original tool arguments.

        Returns:
            - ToolResult if a hook blocked the action (with blocked_by_hook info)
            - dict with updated input if a hook modified it
            - None if all hooks allow the action without modification
        """
        if not self.hook_executor or self.dry_run:
            return None

        from ..core.hooks import HookDecision, HookEvent

        context: dict[str, Any] = {"tool_name": tool_name}
        file_path = tool_input.get("path") or tool_input.get("file_path")
        if file_path:
            context["file_path"] = str(file_path)
        if "command" in tool_input:
            context["command"] = tool_input["command"]

        results = self.hook_executor.run_event(
            HookEvent.PRE_TOOL_USE,
            context,
            stdin_data={"tool_name": tool_name, "tool_input": tool_input},
        )

        updated_input: dict[str, Any] | None = None
        additional_contexts: list[str] = []

        for result in results:
            if result.decision == HookDecision.BLOCK:
                return ToolResult(
                    success=False,
                    output=f"Blocked by hook: {result.reason}",
                    error=f"Hook blocked the action: {result.reason}",
                )
            if result.decision == HookDecision.MODIFY and result.updated_input:
                updated_input = result.updated_input
            if result.additional_context:
                additional_contexts.append(result.additional_context)

        if updated_input:
            return updated_input

        return None

    def run_post_tool_hooks(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str, success: bool
    ) -> str | None:
        """Execute post-tool hooks (v4-A1).

        Args:
            tool_name: Name of the tool executed.
            tool_input: Tool arguments.
            tool_output: Tool output (truncated).
            success: Whether the tool executed successfully.

        Returns:
            Text with additional context from the hooks, or None.
        """
        if not self.hook_executor or self.dry_run:
            return None

        from ..core.hooks import HookEvent

        context: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_result_success": str(success),
        }
        file_path = tool_input.get("path") or tool_input.get("file_path")
        if file_path:
            context["file_path"] = str(file_path)

        results = self.hook_executor.run_event(
            HookEvent.POST_TOOL_USE,
            context,
            stdin_data={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output[:2000],
            },
        )

        outputs: list[str] = []
        for result in results:
            if result.additional_context:
                outputs.append(result.additional_context)

        return "\n".join(outputs) if outputs else None

    def _sanitize_args_for_log(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitize arguments for safe logging.

        Truncates very long values (like content) to avoid
        massive logs.

        Args:
            args: Original arguments

        Returns:
            Sanitized dictionary for logging
        """
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 200:
                sanitized[key] = value[:200] + f"... ({len(value)} chars total)"
            else:
                sanitized[key] = value

        return sanitized

    def _should_confirm_command(self, command: str, tool: Any) -> bool:
        """Determine whether a run_command requires confirmation.

        Implements a dynamic sensitivity table for run_command (F13),
        overriding the static policy based on tool.sensitive:

        | Classification | yolo | confirm-sensitive | confirm-all |
        |----------------|------|-------------------|-------------|
        | safe           | No   | No                | Yes         |
        | dev            | No   | Yes               | Yes         |
        | dangerous      | No   | Yes               | Yes         |

        In yolo mode confirmation is NEVER requested. Security is guaranteed
        by the blocklist (Layer 1) that prevents truly dangerous commands.
        "dangerous" commands are simply unrecognized commands not found in
        the safe/dev lists, not necessarily dangerous.

        Args:
            command: The command to be executed
            tool: The RunCommandTool instance (with classify_sensitivity())

        Returns:
            True if user confirmation should be requested
        """
        classification = tool.classify_sensitivity(command)
        match self.policy.mode:
            case "yolo":
                return False
            case "confirm-sensitive":
                return classification in ("dev", "dangerous")
            case "confirm-all":
                return True
            case _:
                return True

    def set_dry_run(self, enabled: bool) -> None:
        """Enable or disable dry-run mode.

        Args:
            enabled: True to enable dry-run, False to disable
        """
        self.dry_run = enabled
        self.log.info("engine.dry_run_mode", enabled=enabled)

    def __repr__(self) -> str:
        return (
            f"<ExecutionEngine("
            f"tools={self.registry.count()}, "
            f"mode={self.policy.mode}, "
            f"dry_run={self.dry_run})>"
        )
