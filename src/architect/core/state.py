"""
Estado del agente - Estructuras de datos inmutables para tracking.

Define las estructuras de datos que representan el estado de ejecución
del agente a lo largo de su ciclo de vida.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from ..llm.adapter import LLMResponse
from ..tools.base import ToolResult


@dataclass(frozen=True)
class ToolCallResult:
    """Resultado de la ejecución de un tool call.

    Inmutable para facilitar debugging y logging.
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
    """Resultado de un step completo del agente.

    Un step incluye:
    - Llamada al LLM
    - Tool calls ejecutadas (si las hay)
    - Timestamp del step

    Inmutable para facilitar debugging y eventual persistencia.
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
    """Estado mutable del agente durante la ejecución.

    Mantiene el estado completo del agente:
    - Mensajes intercambiados con el LLM
    - Steps ejecutados
    - Estado actual
    - Output final

    Note:
        Aunque AgentState es mutable, los StepResult son inmutables.
        Esto facilita el tracking sin perder la flexibilidad de
        ir construyendo el estado paso a paso.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    status: Literal["running", "success", "partial", "failed"] = "running"
    final_output: str | None = None
    start_time: float = field(default_factory=time.time)
    model: str | None = None

    @property
    def current_step(self) -> int:
        """Retorna el número del step actual (0-indexed)."""
        return len(self.steps)

    @property
    def total_tool_calls(self) -> int:
        """Retorna el total de tool calls ejecutadas."""
        return sum(len(step.tool_calls_made) for step in self.steps)

    @property
    def is_finished(self) -> bool:
        """Retorna True si el agente ha terminado."""
        return self.status != "running"

    def to_output_dict(self) -> dict[str, Any]:
        """Convierte el estado a un dict para output JSON.

        Returns:
            Dict con información completa del estado para output --json
        """
        # Calcular duración
        duration_seconds = round(time.time() - self.start_time, 2)

        # Recopilar resumen de tools usadas
        tools_used: list[dict[str, Any]] = []
        for step in self.steps:
            for tc in step.tool_calls_made:
                tool_info = {
                    "name": tc.tool_name,
                    "success": tc.result.success,
                }
                # Añadir información relevante de args (sin contenido largo)
                if "path" in tc.args:
                    tool_info["path"] = tc.args["path"]
                if tc.result.error:
                    tool_info["error"] = tc.result.error
                tools_used.append(tool_info)

        # Construir output dict
        output_dict: dict[str, Any] = {
            "status": self.status,
            "output": self.final_output,
            "steps": self.current_step,
            "tools_used": tools_used,
            "duration_seconds": duration_seconds,
        }

        # Añadir modelo si está disponible
        if self.model:
            output_dict["model"] = self.model

        return output_dict

    def __repr__(self) -> str:
        return (
            f"<AgentState("
            f"status='{self.status}', "
            f"steps={self.current_step}, "
            f"tool_calls={self.total_tool_calls})>"
        )
