"""
Tracker de costes de llamadas al LLM (F14).

Registra el coste de cada step del agente, agrupa por fuente
(agent/eval/summary) y enforza límites de presupuesto.
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

from .prices import PriceLoader

logger = structlog.get_logger()


class BudgetExceededError(Exception):
    """Error lanzado cuando el coste total supera el presupuesto configurado."""
    pass


@dataclass
class StepCost:
    """Coste de una llamada individual al LLM."""

    step: int
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int   # tokens leídos de caché del proveedor (Anthropic/OpenAI)
    cost_usd: float
    source: str          # "agent" | "eval" | "summary"


class CostTracker:
    """Registra y agrega el coste de las llamadas al LLM.

    Características:
    - Registra coste por step con desglose por fuente (agent/eval/summary)
    - Soporte para tokens de prompt caching (coste reducido para cached_tokens)
    - Budget enforcement: lanza BudgetExceededError si se supera el límite
    - Warn threshold: log de aviso cuando se alcanza un umbral configurable

    Invariante: record() nunca lanza excepciones salvo BudgetExceededError.
    """

    def __init__(
        self,
        price_loader: PriceLoader,
        budget_usd: float | None = None,
        warn_at_usd: float | None = None,
    ) -> None:
        """Inicializa el tracker.

        Args:
            price_loader: PriceLoader para resolver precios por modelo
            budget_usd: Límite de gasto en USD. Si se supera, lanza BudgetExceededError.
            warn_at_usd: Umbral de aviso en USD. Log warning al alcanzarlo.
        """
        self._price_loader = price_loader
        self._budget_usd = budget_usd
        self._warn_at_usd = warn_at_usd
        self._steps: list[StepCost] = []
        self._budget_warned = False
        self._log = logger.bind(component="cost_tracker")

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def record(
        self,
        step: int,
        model: str,
        usage: dict[str, Any],
        source: str = "agent",
    ) -> None:
        """Registra el coste de una llamada al LLM.

        Args:
            step: Número de step del agente
            model: Nombre del modelo usado (e.g., "gpt-4o")
            usage: Dict con usage info del LLM (prompt_tokens, completion_tokens, etc.)
            source: Fuente de la llamada: "agent" | "eval" | "summary"

        Raises:
            BudgetExceededError: Si el coste total supera budget_usd
        """
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        # cache_read_input_tokens: tokens que el proveedor sirvió desde caché
        cached_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)

        cost = self._calculate_cost(model, input_tokens, output_tokens, cached_tokens)

        step_cost = StepCost(
            step=step,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost,
            source=source,
        )
        self._steps.append(step_cost)

        self._log.debug(
            "cost_tracker.record",
            step=step,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=round(cost, 6),
            source=source,
            total_cost_usd=round(self.total_cost_usd, 6),
        )

        # Warn threshold (solo una vez por sesión)
        if (
            not self._budget_warned
            and self._warn_at_usd is not None
            and self.total_cost_usd >= self._warn_at_usd
        ):
            self._budget_warned = True
            self._log.warning(
                "cost_tracker.warn_threshold",
                warn_at_usd=self._warn_at_usd,
                total_cost_usd=round(self.total_cost_usd, 6),
            )

        # Budget enforcement
        if self._budget_usd is not None and self.total_cost_usd > self._budget_usd:
            raise BudgetExceededError(
                f"Presupuesto excedido: ${self.total_cost_usd:.4f} > ${self._budget_usd:.4f} USD"
            )

    # ------------------------------------------------------------------
    # Propiedades de agregación
    # ------------------------------------------------------------------

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self._steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self._steps)

    @property
    def total_cached_tokens(self) -> int:
        return sum(s.cached_tokens for s in self._steps)

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self._steps)

    @property
    def step_count(self) -> int:
        return len(self._steps)

    def has_data(self) -> bool:
        """Retorna True si hay al menos un step registrado."""
        return len(self._steps) > 0

    # ------------------------------------------------------------------
    # Resumen
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Retorna un dict con el resumen de costes para output JSON/terminal.

        Returns:
            Dict con totales, desglose por fuente, y metadatos
        """
        by_source: dict[str, float] = {}
        for step in self._steps:
            by_source[step.source] = round(
                by_source.get(step.source, 0.0) + step.cost_usd, 6
            )

        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "by_source": by_source,
        }

    def format_summary_line(self) -> str:
        """Formatea una línea de resumen compacta para mostrar en terminal.

        Returns:
            Cadena como: "$0.0042 (12,450 in / 3,200 out / 500 cached)"
        """
        total = self.total_cost_usd
        parts = [
            f"${total:.4f}",
            f"({self.total_input_tokens:,} in / {self.total_output_tokens:,} out",
        ]
        if self.total_cached_tokens > 0:
            parts.append(f"/ {self.total_cached_tokens:,} cached)")
        else:
            parts[-1] += ")"
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
    ) -> float:
        """Calcula el coste de una llamada con soporte para cached tokens.

        Los cached_tokens se cobran al precio reducido (cached_input_per_million).
        Los tokens no cacheados se cobran al precio normal (input_per_million).

        Args:
            model: Nombre del modelo
            input_tokens: Total de tokens de input (incluye cached)
            output_tokens: Tokens de output
            cached_tokens: Tokens servidos desde caché del proveedor

        Returns:
            Coste en USD
        """
        pricing = self._price_loader.get_prices(model)

        # Tokens no cacheados = input normal - cached
        non_cached = max(0, input_tokens - cached_tokens)

        # Coste de tokens no cacheados
        input_cost = (non_cached / 1_000_000) * pricing.input_per_million

        # Coste de tokens cacheados (precio reducido si está definido)
        if cached_tokens > 0 and pricing.cached_input_per_million is not None:
            cached_cost = (cached_tokens / 1_000_000) * pricing.cached_input_per_million
        elif cached_tokens > 0:
            # Sin precio de cache definido → usar precio normal
            cached_cost = (cached_tokens / 1_000_000) * pricing.input_per_million
        else:
            cached_cost = 0.0

        # Coste de output
        output_cost = (output_tokens / 1_000_000) * pricing.output_per_million

        return input_cost + cached_cost + output_cost
