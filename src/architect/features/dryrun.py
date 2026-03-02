"""
Dry Run / Preview Mode — Records actions without executing them.

DryRunTracker is used alongside the existing ExecutionEngine.dry_run
to collect the actions the agent would have executed and generate
a summary at the end of the execution.

The ExecutionEngine already handles dry-run at the execution level (returns
"[DRY-RUN] Would execute..." instead of executing). DryRunTracker
complements this by recording the actions for the final summary.
"""

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# Tools that modify state (write operations)
WRITE_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "delete_file",
    "apply_patch",
    "run_command",
})

# Tools that only read (allowed in dry-run)
READ_TOOLS = frozenset({
    "read_file",
    "search_code",
    "grep",
    "find_files",
    "list_directory",
})


@dataclass
class PlannedAction:
    """An action that would have been executed in real mode."""

    step: int
    tool: str
    summary: str


@dataclass
class DryRunTracker:
    """Records planned actions during dry-run to generate a summary.

    Instantiated when --dry-run is active and queried at the end
    of execution to display the action plan.
    """

    actions: list[PlannedAction] = field(default_factory=list)

    def record(self, step: int, tool_name: str, tool_input: dict) -> None:
        """Record a planned write action.

        Args:
            step: Current step number.
            tool_name: Name of the tool.
            tool_input: Tool arguments.
        """
        if tool_name not in WRITE_TOOLS:
            return

        summary = _summarize_action(tool_name, tool_input)
        self.actions.append(PlannedAction(step=step, tool=tool_name, summary=summary))
        logger.debug("dryrun.recorded", step=step, tool=tool_name, summary=summary)

    def get_plan_summary(self) -> str:
        """Generate a human-readable summary of the action plan.

        Returns:
            String with the formatted plan. Empty if no actions.
        """
        if not self.actions:
            return "No write actions were planned."

        lines = ["## Dry Run Plan", ""]
        lines.append(f"**{len(self.actions)} write action(s) would be executed:**")
        lines.append("")

        for i, action in enumerate(self.actions, 1):
            lines.append(f"{i}. **{action.tool}** (step {action.step}) -> {action.summary}")

        return "\n".join(lines)

    @property
    def action_count(self) -> int:
        """Number of recorded write actions."""
        return len(self.actions)


def _summarize_action(tool_name: str, tool_input: dict) -> str:
    """Generate a short summary of an action for the plan.

    Args:
        tool_name: Name of the tool.
        tool_input: Tool arguments.

    Returns:
        Summary string.
    """
    if "path" in tool_input:
        return f"path={tool_input['path']}"
    if "command" in tool_input:
        cmd = tool_input["command"]
        if len(cmd) > 60:
            cmd = cmd[:60] + "..."
        return f"command={cmd}"
    # Fallback: show keys
    keys = ", ".join(tool_input.keys())
    return f"args=[{keys}]"
