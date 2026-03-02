"""
LLM model price loader.

Provides price lookup by model with prefix fallbacks
and a generic price as a last resort.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Generic fallback pricing (unknown model)
_FALLBACK_PRICING_INPUT = 3.0
_FALLBACK_PRICING_OUTPUT = 15.0


@dataclass
class ModelPricing:
    """Prices per million tokens for a given model."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None


class PriceLoader:
    """Loads and resolves LLM model prices.

    Resolution order:
    1. Exact model price
    2. Price by model prefix (e.g., "gpt-4o" matches "gpt-4o-2024-08-06")
    3. Generic fallback price (3.0 / 15.0 USD per million tokens)

    Custom prices override the defaults.
    """

    _DEFAULT_PRICES_PATH = Path(__file__).parent / "default_prices.json"

    def __init__(self, custom_path: Path | None = None) -> None:
        self._prices: dict[str, ModelPricing] = {}
        self._log = logger.bind(component="price_loader")

        # Load embedded defaults
        self._load_file(self._DEFAULT_PRICES_PATH)

        # Override with custom prices if provided
        if custom_path:
            if custom_path.exists():
                self._load_file(custom_path)
                self._log.info("price_loader.custom_loaded", path=str(custom_path))
            else:
                self._log.warning("price_loader.custom_not_found", path=str(custom_path))

    def get_prices(self, model: str) -> ModelPricing:
        """Resolve the price for a given model.

        Never raises exceptions -- always returns a ModelPricing.

        Args:
            model: Model name (e.g., "gpt-4o", "claude-sonnet-4-6")

        Returns:
            ModelPricing with the resolved prices
        """
        # 1. Exact match
        if model in self._prices:
            return self._prices[model]

        # 2. Prefix match (model starts with registered key)
        for key, pricing in self._prices.items():
            if key.startswith("_"):
                continue  # ignore JSON comments
            if model.startswith(key) or key.startswith(model.split("/")[-1] if "/" in model else model):
                self._log.debug("price_loader.prefix_match", model=model, matched_key=key)
                return pricing

        # 3. Attempt by base name without version
        # e.g., "gpt-4o-2024-08-06" -> search "gpt-4o"
        base_model = model.split("-")[0] if "-" in model else model
        for key in self._prices:
            if key.startswith("_"):
                continue
            if key.startswith(base_model):
                return self._prices[key]

        # 4. Generic fallback -- unknown model
        self._log.debug("price_loader.fallback", model=model)
        return ModelPricing(
            input_per_million=_FALLBACK_PRICING_INPUT,
            output_per_million=_FALLBACK_PRICING_OUTPUT,
            cached_input_per_million=None,
        )

    def _load_file(self, path: Path) -> None:
        """Load a JSON prices file and add it to the registry."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if key.startswith("_"):
                    continue  # ignore _comment, _sources, etc.
                self._prices[key] = ModelPricing(
                    input_per_million=float(value["input_per_million"]),
                    output_per_million=float(value["output_per_million"]),
                    cached_input_per_million=(
                        float(value["cached_input_per_million"])
                        if value.get("cached_input_per_million") is not None
                        else None
                    ),
                )
        except Exception as e:
            self._log.error("price_loader.load_failed", path=str(path), error=str(e))
