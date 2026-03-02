"""
Agent State - Immutable data structures for tracking.

Defines the data structures representing the agent's execution state
throughout its lifecycle.

v3: Added StopReason enum and stop_reason field in AgentState.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from ..llm.adapter import LLMResponse
from ..tools.base import ToolResult

if TYPE_CHECKING:
    from ..costs.tracker import CostTracker


class StopReason(Enum):
    """Reason why the agent stopped.

    Distinguishes between natural termination (the LLM decided to finish)
    and forced termination by safety nets (watchdogs).
    """

    LLM_DONE = "llm_done"              # Natural: the LLM requested no more tools
    MAX_STEPS = "max_steps"            # Watchdog: step limit reached
    BUDGET_EXCEEDED = "budget_exceeded"  # Watchdog: cost limit exceeded
    CONTEXT_FULL = "context_full"      # Watchdog: context window full
    TIMEOUT = "timeout"                # Watchdog: total time exceeded
    USER_INTERRUPT = "user_interrupt"  # User pressed Ctrl+C / SIGTERM
    LLM_ERROR = "llm_error"           # Unrecoverable LLM error


@dataclass(frozen=True)
class ToolCallResult:
    """Result of a tool call execution.

    Immutable to facilitate debugging and logging.
    """

    tool_name: str
    args: dict[str, Any]
    result: ToolResult
    was_confirmed: bool = True
    was_dry_run: bool = False
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return (
            f"<ToolCallResult("
            f"tool='{self.tool_name}', "
            f"success={self.result.success}, "
            f"dry_run={self.was_dry_run})>"
        )


@dataclass(frozen=True)
class StepResult:
    """Result of a complete agent step.

    A step includes:
    - LLM call
    - Executed tool calls (if any)
    - Step timestamp

    Immutable to facilitate debugging and eventual persistence.
    """

    step_number: int
    llm_response: LLMResponse
    tool_calls_made: list[ToolCallResult]
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return (
            f"<StepResult("
            f"step={self.step_number}, "
            f"tool_calls={len(self.tool_calls_made)}, "
            f"finish_reason='{self.llm_response.finish_reason}')>"
        )


@dataclass
class AgentState:
    """Mutable agent state during execution.

    Maintains the complete agent state:
    - Messages exchanged with the LLM
    - Executed steps
    - Current status
    - Final output

    Note:
        Although AgentState is mutable, StepResults are immutable.
        This facilitates tracking without losing the flexibility of
        building the state step by step.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    status: Literal["running", "success", "partial", "failed"] = "running"
    stop_reason: StopReason | None = None
    final_output: str | None = None
    start_time: float = field(default_factory=time.time)
    model: str | None = None
    cost_tracker: "CostTracker | None" = field(default=None)

    @property
    def current_step(self) -> int:
        """Return the current step number (0-indexed)."""
        return len(self.steps)

    @property
    def total_tool_calls(self) -> int:
        """Return the total number of executed tool calls."""
        return sum(len(step.tool_calls_made) for step in self.steps)

    @property
    def is_finished(self) -> bool:
        """Return True if the agent has finished."""
        return self.status != "running"

    def to_output_dict(self) -> dict[str, Any]:
        """Convert the state to a dict for JSON output.

        Returns:
            Dict with complete state information for --json output
        """
        # Calculate duration
        duration_seconds = round(time.time() - self.start_time, 2)

        # Collect summary of tools used
        tools_used: list[dict[str, Any]] = []
        for step in self.steps:
            for tc in step.tool_calls_made:
                tool_info = {
                    "name": tc.tool_name,
                    "success": tc.result.success,
                }
                # Add relevant args info (without long content)
                if "path" in tc.args:
                    tool_info["path"] = tc.args["path"]
                if tc.result.error:
                    tool_info["error"] = tc.result.error
                tools_used.append(tool_info)

        # Build output dict
        output_dict: dict[str, Any] = {
            "status": self.status,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "output": self.final_output,
            "steps": self.current_step,
            "tools_used": tools_used,
            "duration_seconds": duration_seconds,
        }

        # Add model if available
        if self.model:
            output_dict["model"] = self.model

        # Add cost summary if available
        if self.cost_tracker is not None and self.cost_tracker.has_data():
            output_dict["costs"] = self.cost_tracker.summary()
            # Top-level convenience key for parallel workers and scripts
            output_dict["cost"] = self.cost_tracker.total_cost_usd

        return output_dict

    def __repr__(self) -> str:
        return (
            f"<AgentState("
            f"status='{self.status}', "
            f"steps={self.current_step}, "
            f"tool_calls={self.total_tool_calls})>"
        )
