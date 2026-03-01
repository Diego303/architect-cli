"""
Core Module - Agent loop and state management.

Exports AgentLoop, ContextBuilder, ContextManager, and state structures,
as well as robustness utilities (GracefulShutdown, StepTimeout).

v3: Added StopReason.
v4-A1: Added complete hook system (HookEvent, HookExecutor, HooksRegistry).
"""

from .context import ContextBuilder, ContextManager
from .evaluator import EvalResult, SelfEvaluator
from .hooks import HookConfig, HookDecision, HookEvent, HookExecutor, HookResult, HooksRegistry
from .loop import AgentLoop
from .mixed_mode import MixedModeRunner
from .shutdown import GracefulShutdown
from .state import AgentState, StepResult, StopReason, ToolCallResult
from .timeout import StepTimeout, StepTimeoutError

__all__ = [
    "AgentLoop",
    "ContextBuilder",
    "ContextManager",
    "EvalResult",
    "GracefulShutdown",
    "HookConfig",
    "HookDecision",
    "HookEvent",
    "HookExecutor",
    "HookResult",
    "HooksRegistry",
    "MixedModeRunner",
    "SelfEvaluator",
    "AgentState",
    "StepResult",
    "StopReason",
    "StepTimeout",
    "StepTimeoutError",
    "ToolCallResult",
]
