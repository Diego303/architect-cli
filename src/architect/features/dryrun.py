"""
Dry Run / Preview Mode — Registra acciones sin ejecutarlas.

DryRunTracker se usa junto con el ExecutionEngine.dry_run existente
para recopilar las acciones que el agente habría ejecutado y generar
un resumen al final de la ejecución.

El ExecutionEngine ya maneja el dry-run a nivel de ejecución (retorna
"[DRY-RUN] Se ejecutaría..." en lugar de ejecutar). DryRunTracker
complementa esto registrando las acciones para el resumen final.
"""

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# Tools que modifican estado (escritura)
WRITE_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "delete_file",
    "apply_patch",
    "run_command",
})

# Tools que solo leen (permitidas en dry-run)
READ_TOOLS = frozenset({
    "read_file",
    "search_code",
    "grep",
    "find_files",
    "list_directory",
})


@dataclass
class PlannedAction:
    """Una acción que se habría ejecutado en modo real."""

    step: int
    tool: str
    summary: str


@dataclass
class DryRunTracker:
    """Registra acciones planificadas durante dry-run para generar resumen.

    Se instancia cuando --dry-run está activo y se consulta al final
    de la ejecución para mostrar el plan de acciones.
    """

    actions: list[PlannedAction] = field(default_factory=list)

    def record(self, step: int, tool_name: str, tool_input: dict) -> None:
        """Registra una acción de escritura planificada.

        Args:
            step: Número de step actual.
            tool_name: Nombre del tool.
            tool_input: Argumentos del tool.
        """
        if tool_name not in WRITE_TOOLS:
            return

        summary = _summarize_action(tool_name, tool_input)
        self.actions.append(PlannedAction(step=step, tool=tool_name, summary=summary))
        logger.debug("dryrun.recorded", step=step, tool=tool_name, summary=summary)

    def get_plan_summary(self) -> str:
        """Genera resumen legible del plan de acciones.

        Returns:
            String con el plan formateado. Vacío si no hay acciones.
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
        """Número de acciones de escritura registradas."""
        return len(self.actions)


def _summarize_action(tool_name: str, tool_input: dict) -> str:
    """Genera un resumen corto de una acción para el plan.

    Args:
        tool_name: Nombre del tool.
        tool_input: Argumentos del tool.

    Returns:
        String de resumen.
    """
    if "path" in tool_input:
        return f"path={tool_input['path']}"
    if "command" in tool_input:
        cmd = tool_input["command"]
        if len(cmd) > 60:
            cmd = cmd[:60] + "..."
        return f"command={cmd}"
    # Fallback: mostrar keys
    keys = ", ".join(tool_input.keys())
    return f"args=[{keys}]"
