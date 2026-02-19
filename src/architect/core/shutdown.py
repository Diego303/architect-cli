"""
GracefulShutdown - Manejo de señales SIGINT y SIGTERM para cierre limpio.

Gestiona la interrupción del agente de forma ordenada:
- Primer SIGINT (Ctrl+C): avisa al usuario y marca el flag, deja terminar el step actual
- Segundo SIGINT: salida inmediata con código 130
- SIGTERM: mismo comportamiento que primer SIGINT (para entornos CI/Docker)

El agent loop consulta should_stop antes de cada iteración para terminar
limpiamente sin cortar a mitad de una operación.
"""

import signal
import sys

import structlog

logger = structlog.get_logger()

EXIT_INTERRUPTED = 130  # Estándar POSIX: 128 + SIGINT(2)


class GracefulShutdown:
    """Gestiona señales de shutdown para cierre limpio del agente.

    Instalar una vez al inicio de la ejecución del comando y pasar
    al AgentLoop para que lo consulte antes de cada step.

    Attributes:
        should_stop: True cuando se ha recibido una señal de interrupción.

    Uso:
        shutdown = GracefulShutdown()
        loop = AgentLoop(llm, engine, config, ctx, shutdown=shutdown)
        state = loop.run(prompt)
    """

    def __init__(self) -> None:
        """Instala los handlers de señales."""
        self._interrupted = False

        # Instalar handlers para ambas señales
        signal.signal(signal.SIGINT, self._handler)
        signal.signal(signal.SIGTERM, self._handler)

        logger.debug("graceful_shutdown.installed")

    def _handler(self, signum: int, frame) -> None:
        """Handler compartido para SIGINT y SIGTERM.

        Primer disparo: avisa y marca el flag.
        Segundo disparo (solo SIGINT): salida inmediata.
        """
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"

        if self._interrupted:
            # Segunda señal → salir inmediatamente
            logger.warning(
                "graceful_shutdown.forced",
                signal=signal_name,
            )
            sys.exit(EXIT_INTERRUPTED)

        # Primera señal → marcar y avisar
        self._interrupted = True
        logger.warning(
            "graceful_shutdown.requested",
            signal=signal_name,
            message="Finalizando al terminar el step actual. Ctrl+C otra vez para salir ya.",
        )

        # Escribir aviso visible al usuario (stderr)
        sys.stderr.write(
            f"\n⚠️  {signal_name} recibido. Finalizando limpiamente...\n"
            "   (Ctrl+C de nuevo para salida inmediata)\n"
        )
        sys.stderr.flush()

    @property
    def should_stop(self) -> bool:
        """True si se ha recibido una señal de interrupción."""
        return self._interrupted

    def reset(self) -> None:
        """Resetea el flag (útil para testing)."""
        self._interrupted = False

    def restore_defaults(self) -> None:
        """Restaura los handlers de señales por defecto."""
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        logger.debug("graceful_shutdown.restored_defaults")
