"""
Configuración completa del sistema de logging estructurado.

v3-M5: Tres pipelines independientes:
1. Archivo (JSON) — Si config.file está configurado. Captura todo (DEBUG+).
2. Human handler (stderr) — Solo eventos HUMAN: qué hace el agente.
3. Console técnico (stderr) — DEBUG/INFO, controlado por -v. Excluye HUMAN.

Comportamiento por defecto (sin -v):
- El usuario ve solo los logs HUMAN (trazabilidad del agente).
- Sin ruido técnico de INFO/DEBUG del sistema.

Con -v: añade INFO. Con -vv: añade DEBUG. Con --quiet: silencia todo.
"""

import logging
import sys
from pathlib import Path

import structlog

from ..config.schema import LoggingConfig
from .levels import HUMAN
from .human import HumanLogHandler


def configure_logging(
    config: LoggingConfig,
    json_output: bool = False,
    quiet: bool = False,
) -> None:
    """Configura el sistema completo de logging con tres pipelines.

    Args:
        config: Configuración de logging (level, file, verbose)
        json_output: Si True, desactiva human y console handlers (--json)
        quiet: Si True, desactiva human y console handlers (--quiet)
    """
    # Limpiar configuración anterior
    logging.root.handlers.clear()
    structlog.reset_defaults()

    # Root logger captura todo — los handlers filtran por nivel
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(message)s",
        handlers=[],
    )

    # Procesadores compartidos para structlog → stdlib
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    show_human = not quiet and not json_output
    show_console = not quiet and not json_output

    # ── Pipeline 1: Archivo JSON ──────────────────────────────────────────
    file_handler = None
    if config.file:
        file_path = Path(config.file)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(str(file_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # Formato JSON para archivo
        json_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler.setFormatter(json_formatter)
        logging.root.addHandler(file_handler)

    # ── Pipeline 2: Human handler (v3-M5) ────────────────────────────────
    if show_human:
        human_handler = HumanLogHandler(stream=sys.stderr)
        # Solo nivel HUMAN exacto (25), no INFO ni DEBUG
        human_handler.setLevel(HUMAN)
        human_handler.addFilter(lambda record: record.levelno == HUMAN)
        logging.root.addHandler(human_handler)

    # ── Pipeline 3: Console técnico ───────────────────────────────────────
    if show_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_level = _verbose_to_level(config.verbose)
        console_handler.setLevel(console_level)
        # Excluir eventos HUMAN del console handler (ya los muestra el human_handler)
        console_handler.addFilter(lambda record: record.levelno != HUMAN)

        if file_handler:
            # Dual pipeline: usar ProcessorFormatter para consistencia
            console_formatter = structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(
                    colors=sys.stderr.isatty(),
                ),
                foreign_pre_chain=shared_processors,
            )
            console_handler.setFormatter(console_formatter)

        logging.root.addHandler(console_handler)

    # ── Configurar structlog ──────────────────────────────────────────────
    if file_handler:
        # Con archivo: usar ProcessorFormatter.wrap_for_formatter para dual pipeline
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
    else:
        # Sin archivo: pipeline directo a ConsoleRenderer
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _verbose_to_level(verbose: int) -> int:
    """Convierte nivel de verbose a nivel de logging para el console handler.

    Sin -v  → WARNING (solo problemas; human va por su propio handler)
    -v      → INFO (operaciones del sistema, config, tool registrations)
    -vv     → DEBUG (args completos, respuestas LLM, timing)
    -vvv+   → DEBUG (todo, incluyendo HTTP)

    Args:
        verbose: Contador de flags -v

    Returns:
        Nivel de logging de Python
    """
    levels = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }
    return levels.get(verbose, logging.DEBUG)


def configure_logging_basic() -> None:
    """Configuración básica para backward compatibility."""
    config = LoggingConfig(level="human", verbose=1, file=None)
    configure_logging(config, json_output=False, quiet=False)


def get_logger(name: str) -> structlog.BoundLogger:
    """Obtiene un logger estructurado.

    Args:
        name: Nombre del logger (usualmente __name__)

    Returns:
        Logger estructurado de structlog
    """
    return structlog.get_logger(name)
