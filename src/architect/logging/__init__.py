"""
Módulo de logging - Sistema de logging estructurado.

Exporta funciones de configuración y obtención de loggers.
"""

from .setup import configure_logging, configure_logging_basic, get_logger

__all__ = [
    "configure_logging",
    "configure_logging_basic",
    "get_logger",
]
