"""
LLM call cost tracker (F14).

Records the cost of each agent step, groups by source
(agent/eval/summary) and enforces budget limits.
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

from .prices import PriceLoader

logger = structlog.get_logger()


class BudgetExceededError(Exception):
    """Error raised when the total cost exceeds the configured budget."""
    pass


@dataclass
class StepCost:
    """Cost of an individual LLM call."""

    step: int
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int   # tokens read from provider cache (Anthropic/OpenAI)
    cost_usd: float
    source: str          # "agent" | "eval" | "summary"


class CostTracker:
    """Records and aggregates LLM call costs.

    Features:
    - Records cost per step with breakdown by source (agent/eval/summary)
    - Support for prompt caching tokens (reduced cost for cached_tokens)
    - Budget enforcement: raises BudgetExceededError if limit is exceeded
    - Warn threshold: warning log when a configurable threshold is reached

    Invariant: record() never raises exceptions except BudgetExceededError.
    """

    def __init__(
        self,
        price_loader: PriceLoader,
        budget_usd: float | None = None,
        warn_at_usd: float | None = None,
    ) -> None:
        """Initialize the tracker.

        Args:
            price_loader: PriceLoader to resolve prices by model
            budget_usd: Spending limit in USD. If exceeded, raises BudgetExceededError.
            warn_at_usd: Warning threshold in USD. Logs a warning when reached.
        """
        self._price_loader = price_loader
        self._budget_usd = budget_usd
        self._warn_at_usd = warn_at_usd
        self._steps: list[StepCost] = []
        self._budget_warned = False
        self._log = logger.bind(component="cost_tracker")

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        step: int,
        model: str,
        usage: dict[str, Any],
        source: str = "agent",
    ) -> None:
        """Record the cost of an LLM call.

        Args:
            step: Agent step number
            model: Name of the model used (e.g., "gpt-4o")
            usage: Dict with LLM usage info (prompt_tokens, completion_tokens, etc.)
            source: Call source: "agent" | "eval" | "summary"

        Raises:
            BudgetExceededError: If total cost exceeds budget_usd
        """
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        # cache_read_input_tokens: tokens the provider served from cache
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

        # Warn threshold (only once per session)
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
                f"Budget exceeded: ${self.total_cost_usd:.4f} > ${self._budget_usd:.4f} USD"
            )

    # ------------------------------------------------------------------
    # Aggregation properties
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
        """Return True if at least one step has been recorded."""
        return len(self._steps) > 0

    def is_budget_exceeded(self) -> bool:
        """Return True if the total cost already exceeds the configured budget.

        Useful for pre-LLM checks: avoids making additional LLM calls
        if the budget has already been exceeded.
        """
        if self._budget_usd is None:
            return False
        return self.total_cost_usd > self._budget_usd

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a dict with cost summary for JSON/terminal output.

        Returns:
            Dict with totals, breakdown by source, and metadata
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
        """Format a compact summary line for terminal display.

        Returns:
            String like: "$0.0042 (12,450 in / 3,200 out / 500 cached)"
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
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
    ) -> float:
        """Calculate the cost of a call with support for cached tokens.

        Cached tokens are charged at the reduced price (cached_input_per_million).
        Non-cached tokens are charged at the normal price (input_per_million).

        Args:
            model: Model name
            input_tokens: Total input tokens (includes cached)
            output_tokens: Output tokens
            cached_tokens: Tokens served from provider cache

        Returns:
            Cost in USD
        """
        pricing = self._price_loader.get_prices(model)

        # Non-cached tokens = normal input - cached
        non_cached = max(0, input_tokens - cached_tokens)

        # Cost of non-cached tokens
        input_cost = (non_cached / 1_000_000) * pricing.input_per_million

        # Cost of cached tokens (reduced price if defined)
        if cached_tokens > 0 and pricing.cached_input_per_million is not None:
            cached_cost = (cached_tokens / 1_000_000) * pricing.cached_input_per_million
        elif cached_tokens > 0:
            # No cache price defined -> use normal price
            cached_cost = (cached_tokens / 1_000_000) * pricing.input_per_million
        else:
            cached_cost = 0.0

        # Output cost
        output_cost = (output_tokens / 1_000_000) * pricing.output_per_million

        return input_cost + cached_cost + output_cost
