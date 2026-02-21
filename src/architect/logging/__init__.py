"""
Módulo de logging - Sistema de logging estructurado.

v3-M5: Añadido nivel HUMAN (25), HumanLogHandler, HumanLog helper.
"""

from .human import HumanLog, HumanLogHandler, _summarize_args
from .levels import HUMAN
from .setup import configure_logging, configure_logging_basic, get_logger

__all__ = [
    "configure_logging",
    "configure_logging_basic",
    "get_logger",
    "HUMAN",
    "HumanLog",
    "HumanLogHandler",
    "_summarize_args",
]
