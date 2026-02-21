"""
Módulo Core - Agent loop y gestión de estado.

Exporta el AgentLoop, ContextBuilder, ContextManager y estructuras de estado,
además de las utilidades de robustez (GracefulShutdown, StepTimeout).

v3: Añadido StopReason.
"""

from .context import ContextBuilder, ContextManager
from .evaluator import EvalResult, SelfEvaluator
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
    "MixedModeRunner",
    "SelfEvaluator",
    "AgentState",
    "StepResult",
    "StopReason",
    "StepTimeout",
    "StepTimeoutError",
    "ToolCallResult",
]
