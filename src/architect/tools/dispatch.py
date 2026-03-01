"""
Tool dispatch_subagent — Dispatches sub-agents with independent context.

v4-D1: Allows the main agent to delegate sub-tasks to a specialized agent
with its own isolated context. The sub-agent executes with a low step limit
and returns a truncated summary to the parent agent.

Sub-agent types:
- explore: Read/search tools only (read_file, search_code, grep, etc.)
- test: Read + test execution (run_command limited to tests)
- review: Read + analysis (no writing or execution)
"""

from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult

logger = structlog.get_logger()

__all__ = [
    "DispatchSubagentTool",
    "DispatchSubagentArgs",
    "SubagentType",
]

# Allowed tools per sub-agent type
SUBAGENT_ALLOWED_TOOLS: dict[str, list[str]] = {
    "explore": [
        "read_file", "list_files", "search_code", "grep", "find_files",
    ],
    "test": [
        "read_file", "list_files", "search_code", "grep", "find_files",
        "run_command",
    ],
    "review": [
        "read_file", "list_files", "search_code", "grep", "find_files",
    ],
}

VALID_SUBAGENT_TYPES = frozenset(SUBAGENT_ALLOWED_TOOLS.keys())

# Maximum steps for sub-agents (low limit to avoid consuming too much context/cost)
SUBAGENT_MAX_STEPS = 15

# Maximum characters in the summary returned to the parent agent
SUBAGENT_SUMMARY_MAX_CHARS = 1000


class DispatchSubagentArgs(BaseModel):
    """Arguments for dispatch_subagent tool."""

    task: str = Field(
        description=(
            "Description of the sub-task to execute. Be specific about what "
            "you want the sub-agent to investigate, test, or review."
        ),
    )
    agent_type: str = Field(
        default="explore",
        description=(
            "Sub-agent type: "
            "'explore' (read-only/search, for investigation), "
            "'test' (read + test execution), "
            "'review' (read + code analysis)"
        ),
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description=(
            "Files the sub-agent should read for context. "
            "Example: ['src/main.py', 'tests/test_main.py']"
        ),
    )

    model_config = {"extra": "forbid"}


class DispatchSubagentTool(BaseTool):
    """Dispatches a sub-task to a specialized agent with independent context.

    The sub-agent has its own clean context and a low step limit.
    Returns a truncated summary of its work to the parent agent, avoiding
    polluting the main context with investigation details.

    Attributes:
        name: Tool name ("dispatch_subagent").
        description: Description visible to the LLM.
        sensitive: False — the sub-agent has its own restrictions.
        args_model: DispatchSubagentArgs.
    """

    name = "dispatch_subagent"
    description = (
        "Delegates a sub-task to a specialized agent with its own independent "
        "context. Useful for investigating, exploring code or running tests "
        "without polluting your main context. The sub-agent will return a "
        "summary of its work.\n\n"
        "Available types:\n"
        "- explore: Read-only/search (read files, search code)\n"
        "- test: Read + test execution (pytest, etc.)\n"
        "- review: Read + code analysis\n\n"
        "The sub-agent has a maximum of 15 steps and returns a summary "
        "of up to 1000 characters."
    )
    sensitive = False
    args_model = DispatchSubagentArgs

    def __init__(self, agent_factory: Callable[..., Any], workspace_root: str) -> None:
        """Initialize the dispatch tool.

        Args:
            agent_factory: Callable that creates a configured AgentLoop.
                Must accept keyword args: agent, max_steps, allowed_tools.
            workspace_root: Root directory of the workspace.
        """
        self.agent_factory = agent_factory
        self.workspace_root = workspace_root
        self.log = logger.bind(component="dispatch_subagent")

    def execute(
        self,
        task: str,
        agent_type: str = "explore",
        relevant_files: list[str] | None = None,
    ) -> ToolResult:
        """Execute a sub-agent with isolated context.

        Args:
            task: Description of the sub-task.
            agent_type: Type of sub-agent (explore, test, review).
            relevant_files: Relevant files for context.

        Returns:
            ToolResult with the sub-agent's summary.
        """
        if relevant_files is None:
            relevant_files = []

        try:
            # Validate sub-agent type
            if agent_type not in VALID_SUBAGENT_TYPES:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Invalid sub-agent type: '{agent_type}'. "
                        f"Valid types: {', '.join(sorted(VALID_SUBAGENT_TYPES))}"
                    ),
                )

            allowed_tools = SUBAGENT_ALLOWED_TOOLS[agent_type]

            # Build enriched prompt with relevant files
            prompt = self._build_subagent_prompt(task, agent_type, relevant_files)

            self.log.info(
                "dispatch.start",
                agent_type=agent_type,
                task=task[:100],
                relevant_files=relevant_files[:5],
            )

            # Create and execute sub-agent with clean context
            subagent = self.agent_factory(
                agent=agent_type,
                max_steps=SUBAGENT_MAX_STEPS,
                allowed_tools=allowed_tools,
            )
            result = subagent.run(prompt)

            # Extract final response
            summary = getattr(result, "final_response", None) or "No result from sub-agent."

            # Truncate to avoid filling the parent's context
            if len(summary) > SUBAGENT_SUMMARY_MAX_CHARS:
                summary = summary[:SUBAGENT_SUMMARY_MAX_CHARS] + "\n... (summary truncated)"

            cost = getattr(result, "total_cost", 0)
            steps = getattr(result, "steps_completed", 0)

            self.log.info(
                "dispatch.complete",
                agent_type=agent_type,
                steps=steps,
                cost=cost,
                summary_length=len(summary),
            )

            return ToolResult(
                success=True,
                output=summary,
            )

        except Exception as e:
            self.log.error(
                "dispatch.error",
                agent_type=agent_type,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ToolResult(
                success=False,
                output="",
                error=f"Error executing sub-agent: {e}",
            )

    def _build_subagent_prompt(
        self, task: str, agent_type: str, relevant_files: list[str]
    ) -> str:
        """Build the prompt for the sub-agent.

        Args:
            task: Original task.
            agent_type: Type of sub-agent.
            relevant_files: Relevant files.

        Returns:
            Enriched prompt with instructions and context.
        """
        parts = [f"## Sub-task ({agent_type})\n\n{task}"]

        if relevant_files:
            file_list = "\n".join(f"- `{f}`" for f in relevant_files[:10])
            parts.append(
                f"\n## Relevant Files\n\n"
                f"Read these files for context:\n{file_list}"
            )

        # Instructions by type
        match agent_type:
            case "explore":
                parts.append(
                    "\n## Instructions\n\n"
                    "Investigate and answer the question using the available "
                    "read and search tools. Do NOT modify any files. "
                    "Respond with a concise and useful summary."
                )
            case "test":
                parts.append(
                    "\n## Instructions\n\n"
                    "Run the relevant tests and report results. "
                    "Do NOT modify code. Only read files and run tests. "
                    "Respond with a summary of which tests passed/failed."
                )
            case "review":
                parts.append(
                    "\n## Instructions\n\n"
                    "Review the code in the relevant files. Look for bugs, "
                    "design problems and improvement opportunities. "
                    "Do NOT modify any files. Respond with a summary "
                    "of your findings."
                )

        return "\n".join(parts)
