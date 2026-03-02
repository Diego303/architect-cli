"""
Complete structured logging system configuration.

v3-M5: Three independent pipelines:
1. File (JSON) — If config.file is configured. Captures everything (DEBUG+).
2. Human handler (stderr) — Only HUMAN events: what the agent is doing.
3. Technical console (stderr) — DEBUG/INFO, controlled by -v. Excludes HUMAN.

Default behavior (without -v):
- The user sees only HUMAN logs (agent traceability).
- No technical noise from system INFO/DEBUG.

With -v: adds INFO. With -vv: adds DEBUG. With --quiet: silences everything.
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
    """Configure the complete logging system with three pipelines.

    Args:
        config: Logging configuration (level, file, verbose).
        json_output: If True, disables human and console handlers (--json).
        quiet: If True, disables human and console handlers (--quiet).
    """
    # Clear previous configuration
    logging.root.handlers.clear()
    structlog.reset_defaults()

    # Root logger captures everything — handlers filter by level
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(message)s",
        handlers=[],
    )

    # Shared processors for structlog -> stdlib
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    show_human = not quiet and not json_output
    show_console = not quiet and not json_output

    # -- Pipeline 1: JSON File -------------------------------------------------
    file_handler = None
    if config.file:
        file_path = Path(config.file)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(str(file_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # JSON format for file
        json_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler.setFormatter(json_formatter)
        logging.root.addHandler(file_handler)

    # -- Pipeline 2: Human handler (v3-M5) -------------------------------------
    if show_human:
        human_handler = HumanLogHandler(stream=sys.stderr)
        # Only exact HUMAN level (25), not INFO or DEBUG
        human_handler.setLevel(HUMAN)
        human_handler.addFilter(lambda record: record.levelno == HUMAN)
        logging.root.addHandler(human_handler)

    # -- Pipeline 3: Technical console -----------------------------------------
    if show_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_level = _verbose_to_level(config.verbose)
        console_handler.setLevel(console_level)
        # Exclude HUMAN events from console handler (already shown by human_handler)
        console_handler.addFilter(lambda record: record.levelno != HUMAN)

        # Always use ProcessorFormatter so stdlib handlers receive
        # structured LogRecords (needed for HumanLogHandler)
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),
            ),
            foreign_pre_chain=shared_processors,
        )
        console_handler.setFormatter(console_formatter)

        logging.root.addHandler(console_handler)

    # -- Configure structlog ---------------------------------------------------
    # Always use wrap_for_formatter so events flow through
    # stdlib handlers (HumanLogHandler needs structured LogRecords)
    processors = shared_processors + [
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _verbose_to_level(verbose: int) -> int:
    """Convert verbose level to logging level for the console handler.

    No -v  -> WARNING (only problems; human goes through its own handler)
    -v     -> INFO (system operations, config, tool registrations)
    -vv    -> DEBUG (full args, LLM responses, timing)
    -vvv+  -> DEBUG (everything, including HTTP)

    Args:
        verbose: Count of -v flags.

    Returns:
        Python logging level.
    """
    levels = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }
    return levels.get(verbose, logging.DEBUG)


def configure_logging_basic() -> None:
    """Basic configuration for backward compatibility."""
    config = LoggingConfig(level="human", verbose=1, file=None)
    configure_logging(config, json_output=False, quiet=False)


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger.

    Args:
        name: Logger name (usually __name__).

    Returns:
        Structured structlog logger.
    """
    return structlog.get_logger(name)
