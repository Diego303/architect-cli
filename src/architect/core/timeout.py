"""
StepTimeout - Context manager para limitar la duración de un step del agente.

Usa signal.SIGALRM en sistemas POSIX (Linux/macOS). En Windows, donde SIGALRM
no está disponible, el timeout no se aplica pero el sistema sigue funcionando.

Diseñado para usarse en el agent loop, envolviendo cada iteración completa
(llamada al LLM + ejecución de tools) para garantizar que ningún step
se quede bloqueado indefinidamente.
"""

import signal
import structlog

logger = structlog.get_logger()

# Detectar soporte de SIGALRM en tiempo de importación
_SIGALRM_SUPPORTED = hasattr(signal, "SIGALRM")


class StepTimeoutError(TimeoutError):
    """Excepción lanzada cuando un step supera el tiempo máximo permitido."""

    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"El step excedió el tiempo máximo de {seconds}s")


class StepTimeout:
    """Context manager que limita la duración de un step del agente.

    Uso:
        with StepTimeout(seconds=60):
            response = llm.completion(messages)
            result = engine.execute_tool_call(...)

    Raises:
        StepTimeoutError: Si el step supera el timeout configurado.

    Note:
        En Windows (sin SIGALRM), el timeout no se aplica pero el
        context manager se comporta como no-op para no romper el código.
        En entornos CI/Linux el timeout es obligatorio.
    """

    def __init__(self, seconds: int):
        """Inicializa el timeout.

        Args:
            seconds: Segundos máximos permitidos. 0 o negativo = sin timeout.
        """
        self.seconds = seconds
        self._active = _SIGALRM_SUPPORTED and seconds > 0
        self._previous_handler = None

    def __enter__(self) -> "StepTimeout":
        if self._active:
            # Guardar handler anterior para restaurarlo al salir
            self._previous_handler = signal.signal(signal.SIGALRM, self._handler)
            signal.alarm(self.seconds)
            logger.debug(
                "step_timeout.armed",
                seconds=self.seconds,
            )
        elif not _SIGALRM_SUPPORTED and self.seconds > 0:
            logger.debug(
                "step_timeout.sigalrm_not_supported",
                seconds=self.seconds,
                note="Timeout no aplicado (Windows/plataforma sin SIGALRM)",
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._active:
            # Cancelar la alarma pendiente
            signal.alarm(0)
            # Restaurar el handler anterior
            if self._previous_handler is not None:
                signal.signal(signal.SIGALRM, self._previous_handler)
                self._previous_handler = None
            if exc_type is None:
                logger.debug("step_timeout.disarmed")
        # No suprimir excepciones (incluyendo StepTimeoutError)
        return False

    def _handler(self, signum: int, frame) -> None:
        """Handler de SIGALRM — lanzado cuando se supera el timeout."""
        logger.warning(
            "step_timeout.exceeded",
            seconds=self.seconds,
        )
        raise StepTimeoutError(self.seconds)
