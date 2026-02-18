"""
Configuración completa del sistema de logging estructurado.

Implementa dos pipelines independientes:
1. Archivo → JSON estructurado (siempre, si se configura)
2. Stderr → Humano legible (controlado por verbose/quiet)

Logs van a stderr para no romper pipes. Solo el output final va a stdout.
"""

import logging
import sys
from pathlib import Path

import structlog

from ..config.schema import LoggingConfig


def configure_logging(
    config: LoggingConfig,
    json_output: bool = False,
    quiet: bool = False,
) -> None:
    """Configura el sistema completo de logging.

    Dos pipelines independientes:
    1. Archivo (JSON) - Si config.file está configurado
    2. Stderr (humano) - Controlado por verbose/quiet

    Args:
        config: Configuración de logging
        json_output: Si True, el usuario quiere salida JSON (reduce logs)
        quiet: Si True, solo errores críticos
    """
    # Limpiar configuración anterior
    logging.root.handlers.clear()
    structlog.reset_defaults()

    # Determinar nivel según verbose
    if quiet:
        console_level = logging.ERROR
    else:
        console_level = _verbose_to_level(config.verbose)

    # Configurar logging estándar de Python
    # Root logger al nivel más bajo para capturar todo
    logging.basicConfig(
        level=logging.DEBUG,  # Capturar todo, filtrar por handler
        format="%(message)s",
        handlers=[],  # Añadiremos handlers manualmente
    )

    # Handler para stderr (humano)
    if not quiet or console_level <= logging.ERROR:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        logging.root.addHandler(console_handler)

    # Handler para archivo (JSON)
    file_handler = None
    if config.file:
        file_path = Path(config.file)
        # Crear directorio padre si no existe
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Archivo captura todo
        logging.root.addHandler(file_handler)

    # Procesadores compartidos (para ambos pipelines)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    # Procesador final depende del handler
    # Para archivo: JSON
    # Para stderr: ConsoleRenderer (humano)
    if file_handler:
        # Pipeline con JSON
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Pipeline solo consola
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),  # Colores solo si es TTY
            ),
        ]

    # Si tenemos archivo, necesitamos dual pipeline
    if file_handler:
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]

        # Configurar formatter para JSON en archivo
        json_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler.setFormatter(json_formatter)

        # Configurar formatter para consola en stderr
        if console_handler:
            console_formatter = structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(
                    colors=sys.stderr.isatty(),
                ),
                foreign_pre_chain=shared_processors,
            )
            console_handler.setFormatter(console_formatter)

    # Configurar structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _verbose_to_level(verbose: int) -> int:
    """Convierte nivel de verbose a nivel de logging.

    Niveles:
        0 (sin -v)  → WARNING (solo problemas)
        1 (-v)      → INFO (steps del agente, tool calls)
        2 (-vv)     → DEBUG (args, respuestas LLM)
        3+ (-vvv)   → DEBUG (todo, incluyendo HTTP)

    Args:
        verbose: Contador de -v flags

    Returns:
        Nivel de logging de Python
    """
    levels = {
        0: logging.WARNING,  # Solo problemas
        1: logging.INFO,  # Operaciones principales
        2: logging.DEBUG,  # Detalles
    }

    # 3 o más → DEBUG completo
    return levels.get(verbose, logging.DEBUG)


def configure_logging_basic() -> None:
    """Configuración básica de logging para compatibilidad.

    Esta función existe para backward compatibility con código
    que la llama desde fases anteriores.

    La nueva función configure_logging() es más completa.
    """
    config = LoggingConfig(
        level="info",
        verbose=1,
        file=None,
    )
    configure_logging(config, json_output=False, quiet=False)


def get_logger(name: str) -> structlog.BoundLogger:
    """Obtiene un logger estructurado.

    Args:
        name: Nombre del logger (usualmente __name__)

    Returns:
        Logger estructurado de structlog
    """
    return structlog.get_logger(name)
