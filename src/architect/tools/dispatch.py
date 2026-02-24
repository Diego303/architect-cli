"""
Tool dispatch_subagent — Despacha sub-agentes con contexto independiente.

v4-D1: Permite al agente principal delegar sub-tareas a un agente especializado
con su propio contexto aislado. El sub-agente ejecuta con un límite bajo de pasos
y retorna un resumen truncado al agente padre.

Tipos de sub-agente:
- explore: Solo herramientas de lectura/búsqueda (read_file, search_code, grep, etc.)
- test: Lectura + ejecución de tests (run_command limitado a tests)
- review: Lectura + análisis (sin escritura ni ejecución)
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

# Herramientas permitidas por tipo de sub-agente
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

# Máximo de pasos para sub-agentes (límite bajo para no consumir demasiado contexto/coste)
SUBAGENT_MAX_STEPS = 15

# Máximo de caracteres en el resumen retornado al agente padre
SUBAGENT_SUMMARY_MAX_CHARS = 1000


class DispatchSubagentArgs(BaseModel):
    """Argumentos para dispatch_subagent tool."""

    task: str = Field(
        description=(
            "Descripción de la sub-tarea a ejecutar. Sé específico sobre qué "
            "quieres que el sub-agente investigue, pruebe o revise."
        ),
    )
    agent_type: str = Field(
        default="explore",
        description=(
            "Tipo de sub-agente: "
            "'explore' (solo lectura/búsqueda, para investigar), "
            "'test' (lectura + ejecución de tests), "
            "'review' (lectura + análisis de código)"
        ),
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description=(
            "Archivos que el sub-agente debería leer para contexto. "
            "Ejemplo: ['src/main.py', 'tests/test_main.py']"
        ),
    )

    model_config = {"extra": "forbid"}


class DispatchSubagentTool(BaseTool):
    """Despacha una sub-tarea a un agente especializado con contexto independiente.

    El sub-agente tiene su propio contexto limpio y un límite bajo de pasos.
    Retorna un resumen truncado de su trabajo al agente padre, evitando
    contaminar el contexto principal con detalles de la investigación.

    Attributes:
        name: Nombre de la tool ("dispatch_subagent").
        description: Descripción visible por el LLM.
        sensitive: False — el sub-agente tiene restricciones propias.
        args_model: DispatchSubagentArgs.
    """

    name = "dispatch_subagent"
    description = (
        "Delega una sub-tarea a un agente especializado con su propio contexto "
        "independiente. Útil para investigar, explorar código o ejecutar tests "
        "sin contaminar tu contexto principal. El sub-agente retornará un "
        "resumen de su trabajo.\n\n"
        "Tipos disponibles:\n"
        "- explore: Solo lectura/búsqueda (leer archivos, buscar código)\n"
        "- test: Lectura + ejecución de tests (pytest, etc.)\n"
        "- review: Lectura + análisis de código\n\n"
        "El sub-agente tiene un máximo de 15 pasos y retorna un resumen "
        "de máximo 1000 caracteres."
    )
    sensitive = False
    args_model = DispatchSubagentArgs

    def __init__(self, agent_factory: Callable[..., Any], workspace_root: str) -> None:
        """Inicializa el tool de dispatch.

        Args:
            agent_factory: Callable que crea un AgentLoop configurado.
                Debe aceptar keyword args: agent, max_steps, allowed_tools.
            workspace_root: Directorio raíz del workspace.
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
        """Ejecuta un sub-agente con contexto aislado.

        Args:
            task: Descripción de la sub-tarea.
            agent_type: Tipo de sub-agente (explore, test, review).
            relevant_files: Archivos relevantes para dar contexto.

        Returns:
            ToolResult con el resumen del sub-agente.
        """
        if relevant_files is None:
            relevant_files = []

        try:
            # Validar tipo de sub-agente
            if agent_type not in VALID_SUBAGENT_TYPES:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Tipo de sub-agente inválido: '{agent_type}'. "
                        f"Tipos válidos: {', '.join(sorted(VALID_SUBAGENT_TYPES))}"
                    ),
                )

            allowed_tools = SUBAGENT_ALLOWED_TOOLS[agent_type]

            # Construir prompt enriquecido con archivos relevantes
            prompt = self._build_subagent_prompt(task, agent_type, relevant_files)

            self.log.info(
                "dispatch.start",
                agent_type=agent_type,
                task=task[:100],
                relevant_files=relevant_files[:5],
            )

            # Crear y ejecutar sub-agente con contexto limpio
            subagent = self.agent_factory(
                agent=agent_type,
                max_steps=SUBAGENT_MAX_STEPS,
                allowed_tools=allowed_tools,
            )
            result = subagent.run(prompt)

            # Extraer respuesta final
            summary = getattr(result, "final_response", None) or "Sin resultado del sub-agente."

            # Truncar para no llenar el contexto del padre
            if len(summary) > SUBAGENT_SUMMARY_MAX_CHARS:
                summary = summary[:SUBAGENT_SUMMARY_MAX_CHARS] + "\n... (resumen truncado)"

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
                error=f"Error ejecutando sub-agente: {e}",
            )

    def _build_subagent_prompt(
        self, task: str, agent_type: str, relevant_files: list[str]
    ) -> str:
        """Construye el prompt para el sub-agente.

        Args:
            task: Tarea original.
            agent_type: Tipo de sub-agente.
            relevant_files: Archivos relevantes.

        Returns:
            Prompt enriquecido con instrucciones y contexto.
        """
        parts = [f"## Sub-tarea ({agent_type})\n\n{task}"]

        if relevant_files:
            file_list = "\n".join(f"- `{f}`" for f in relevant_files[:10])
            parts.append(
                f"\n## Archivos Relevantes\n\n"
                f"Lee estos archivos para contexto:\n{file_list}"
            )

        # Instrucciones según tipo
        match agent_type:
            case "explore":
                parts.append(
                    "\n## Instrucciones\n\n"
                    "Investiga y responde la pregunta usando las herramientas de "
                    "lectura y búsqueda disponibles. NO modifiques ningún archivo. "
                    "Responde con un resumen conciso y útil."
                )
            case "test":
                parts.append(
                    "\n## Instrucciones\n\n"
                    "Ejecuta los tests relevantes y reporta los resultados. "
                    "NO modifiques código. Solo lee archivos y ejecuta tests. "
                    "Responde con un resumen de qué tests pasaron/fallaron."
                )
            case "review":
                parts.append(
                    "\n## Instrucciones\n\n"
                    "Revisa el código de los archivos relevantes. Busca bugs, "
                    "problemas de diseño y oportunidades de mejora. "
                    "NO modifiques ningún archivo. Responde con un resumen "
                    "de tus hallazgos."
                )

        return "\n".join(parts)
