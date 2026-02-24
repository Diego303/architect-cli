"""
Auto-Review Writer/Reviewer — Agente reviewer que inspecciona cambios post-build.

v4-C5: Después de que el builder completa, el reviewer recibe SOLO el diff
y la tarea original (contexto LIMPIO, sin historial del builder).
Solo tiene acceso a tools de lectura. Si encuentra problemas, el builder
realiza un fix-pass.
"""

import subprocess
from typing import Any, Callable

import structlog

logger = structlog.get_logger()

__all__ = [
    "REVIEW_SYSTEM_PROMPT",
    "AutoReviewer",
    "ReviewResult",
]

REVIEW_SYSTEM_PROMPT = """Eres un reviewer senior de código. Tu trabajo es revisar \
cambios de código hechos por otro agente y encontrar problemas.

Busca específicamente:
1. Bugs lógicos y edge cases no cubiertos
2. Problemas de seguridad (SQL injection, XSS, secrets hardcoded, etc.)
3. Violaciones de las convenciones del proyecto (si hay .architect.md, síguelo)
4. Oportunidades de simplificación o mejora
5. Tests faltantes o insuficientes

Sé específico: indica archivo, línea, y qué cambio exacto harías.
Si no encuentras problemas significativos, di "Sin issues encontrados."
"""

# Type alias for the agent factory callable.
AgentFactory = Callable[..., Any]


class ReviewResult:
    """Resultado de un auto-review."""

    def __init__(
        self,
        has_issues: bool,
        review_text: str,
        cost: float = 0.0,
    ):
        """Inicializa el resultado del review.

        Args:
            has_issues: True si se encontraron issues.
            review_text: Texto completo del review.
            cost: Coste en USD del review.
        """
        self.has_issues = has_issues
        self.review_text = review_text
        self.cost = cost


class AutoReviewer:
    """Ejecuta un agente reviewer sobre los cambios del builder.

    El reviewer recibe SOLO el diff y la tarea original — contexto LIMPIO.
    Solo tiene tools de lectura (read_file, search_code, grep, list_directory).
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        review_model: str | None = None,
    ):
        """Inicializa el auto-reviewer.

        Args:
            agent_factory: Callable que crea AgentLoops.
                Recibe kwargs: agent, model, system_prompt, allowed_tools.
            review_model: Modelo LLM para el reviewer. None = default.
        """
        self.agent_factory = agent_factory
        self.review_model = review_model
        self.log = logger.bind(component="auto_reviewer")

    def review_changes(self, task: str, git_diff: str) -> ReviewResult:
        """Ejecuta review en contexto limpio.

        Args:
            task: Tarea original que ejecutó el builder.
            git_diff: Diff de los cambios a revisar.

        Returns:
            ReviewResult con issues encontrados.
        """
        if not git_diff.strip():
            self.log.info("auto_review.no_diff")
            return ReviewResult(
                has_issues=False,
                review_text="Sin cambios para revisar.",
            )

        # Truncar diff si es muy largo
        truncated_diff = git_diff[:8000]
        if len(git_diff) > 8000:
            truncated_diff += "\n... (diff truncado)"

        prompt = (
            f"## Tarea Original\n{task}\n\n"
            f"## Cambios a Revisar\n```diff\n{truncated_diff}\n```\n\n"
            f"Revisa estos cambios. Lista cada issue encontrado con formato:\n"
            f"- **[archivo:linea]** Descripción del problema. Sugerencia de fix.\n\n"
            f"Si no hay issues, responde exactamente: 'Sin issues encontrados.'"
        )

        self.log.info(
            "auto_review.start",
            task_preview=task[:60],
            diff_chars=len(git_diff),
        )

        try:
            agent = self.agent_factory(
                agent="review",
                model=self.review_model,
            )
            result = agent.run(prompt)

            response = getattr(result, "final_output", "") or ""
            cost = 0.0
            if hasattr(result, "cost_tracker") and result.cost_tracker:
                cost = result.cost_tracker.total_cost_usd

            has_issues = "sin issues" not in response.lower()

            self.log.info(
                "auto_review.complete",
                has_issues=has_issues,
                cost=cost,
            )

            return ReviewResult(
                has_issues=has_issues,
                review_text=response,
                cost=cost,
            )

        except Exception as e:
            self.log.error("auto_review.error", error=str(e))
            return ReviewResult(
                has_issues=False,
                review_text=f"Error en auto-review: {e}",
                cost=0.0,
            )

    @staticmethod
    def get_recent_diff(workspace_root: str, commits_back: int = 1) -> str:
        """Obtiene el diff de los últimos N commits.

        Args:
            workspace_root: Directorio raíz del repositorio.
            commits_back: Número de commits hacia atrás.

        Returns:
            Diff como string.
        """
        try:
            result = subprocess.run(
                ["git", "diff", f"HEAD~{commits_back}", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=workspace_root,
            )
            return result.stdout
        except Exception:
            return ""

    @staticmethod
    def build_fix_prompt(review_text: str) -> str:
        """Construye un prompt de corrección basado en el review.

        Args:
            review_text: Texto del review con los issues encontrados.

        Returns:
            Prompt para el builder con instrucciones de fix.
        """
        return (
            f"Un reviewer encontró estos problemas en tu código:\n\n"
            f"{review_text}\n\n"
            f"Corrige estos problemas. Asegúrate de que cada issue "
            f"mencionado sea resuelto."
        )
