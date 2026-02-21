"""
Cargador de precios de modelos LLM.

Proporciona lookup de precios por modelo con fallbacks por prefijo
y precio genérico como último recurso.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Precio genérico de fallback (no se conoce el modelo)
_FALLBACK_PRICING_INPUT = 3.0
_FALLBACK_PRICING_OUTPUT = 15.0


@dataclass
class ModelPricing:
    """Precios por millón de tokens para un modelo dado."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None


class PriceLoader:
    """Carga y resuelve precios de modelos LLM.

    Orden de resolución:
    1. Precio exacto del modelo
    2. Precio por prefijo del modelo (e.g., "gpt-4o" matchea "gpt-4o-2024-08-06")
    3. Precio genérico de fallback (3.0 / 15.0 USD por millón de tokens)

    Los precios custom sobreescriben los defaults.
    """

    _DEFAULT_PRICES_PATH = Path(__file__).parent / "default_prices.json"

    def __init__(self, custom_path: Path | None = None) -> None:
        self._prices: dict[str, ModelPricing] = {}
        self._log = logger.bind(component="price_loader")

        # Cargar defaults embebidos
        self._load_file(self._DEFAULT_PRICES_PATH)

        # Sobreescribir con precios custom si se proporcionan
        if custom_path:
            if custom_path.exists():
                self._load_file(custom_path)
                self._log.info("price_loader.custom_loaded", path=str(custom_path))
            else:
                self._log.warning("price_loader.custom_not_found", path=str(custom_path))

    def get_prices(self, model: str) -> ModelPricing:
        """Resuelve el precio para un modelo dado.

        Nunca lanza excepciones — siempre retorna un ModelPricing.

        Args:
            model: Nombre del modelo (e.g., "gpt-4o", "claude-sonnet-4-6")

        Returns:
            ModelPricing con los precios resueltos
        """
        # 1. Match exacto
        if model in self._prices:
            return self._prices[model]

        # 2. Match por prefijo (el modelo empieza con la clave registrada)
        for key, pricing in self._prices.items():
            if key.startswith("_"):
                continue  # ignorar comentarios del JSON
            if model.startswith(key) or key.startswith(model.split("/")[-1] if "/" in model else model):
                self._log.debug("price_loader.prefix_match", model=model, matched_key=key)
                return pricing

        # 3. Intento por el nombre base sin versión
        # e.g., "gpt-4o-2024-08-06" → buscar "gpt-4o"
        base_model = model.split("-")[0] if "-" in model else model
        for key in self._prices:
            if key.startswith("_"):
                continue
            if key.startswith(base_model):
                return self._prices[key]

        # 4. Fallback genérico — no se conoce el modelo
        self._log.debug("price_loader.fallback", model=model)
        return ModelPricing(
            input_per_million=_FALLBACK_PRICING_INPUT,
            output_per_million=_FALLBACK_PRICING_OUTPUT,
            cached_input_per_million=None,
        )

    def _load_file(self, path: Path) -> None:
        """Carga un archivo JSON de precios y lo añade al registro."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if key.startswith("_"):
                    continue  # ignorar _comment, _sources, etc.
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
