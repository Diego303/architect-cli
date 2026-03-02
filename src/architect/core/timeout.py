"""
StepTimeout - Context manager to limit the duration of an agent step.

Uses signal.SIGALRM on POSIX systems (Linux/macOS). On Windows, where SIGALRM
is not available, the timeout is not enforced but the system continues to work.

Designed for use in the agent loop, wrapping each complete iteration
(LLM call + tool execution) to ensure no step
gets blocked indefinitely.
"""

import signal
import structlog

logger = structlog.get_logger()

# Detect SIGALRM support at import time
_SIGALRM_SUPPORTED = hasattr(signal, "SIGALRM")


class StepTimeoutError(TimeoutError):
    """Exception raised when a step exceeds the maximum allowed time."""

    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"Step exceeded the maximum time of {seconds}s")


class StepTimeout:
    """Context manager that limits the duration of an agent step.

    Usage:
        with StepTimeout(seconds=60):
            response = llm.completion(messages)
            result = engine.execute_tool_call(...)

    Raises:
        StepTimeoutError: If the step exceeds the configured timeout.

    Note:
        On Windows (without SIGALRM), the timeout is not enforced but the
        context manager behaves as a no-op to avoid breaking the code.
        In CI/Linux environments the timeout is mandatory.
    """

    def __init__(self, seconds: int):
        """Initialize the timeout.

        Args:
            seconds: Maximum allowed seconds. 0 or negative = no timeout.
        """
        self.seconds = seconds
        self._active = _SIGALRM_SUPPORTED and seconds > 0
        self._previous_handler = None

    def __enter__(self) -> "StepTimeout":
        if self._active:
            # Save previous handler to restore on exit
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
                note="Timeout not enforced (Windows/platform without SIGALRM)",
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._active:
            # Cancel the pending alarm
            signal.alarm(0)
            # Restore the previous handler
            if self._previous_handler is not None:
                signal.signal(signal.SIGALRM, self._previous_handler)
                self._previous_handler = None
            if exc_type is None:
                logger.debug("step_timeout.disarmed")
        # Do not suppress exceptions (including StepTimeoutError)
        return False

    def _handler(self, signum: int, frame) -> None:
        """SIGALRM handler -- raised when the timeout is exceeded."""
        logger.warning(
            "step_timeout.exceeded",
            seconds=self.seconds,
        )
        raise StepTimeoutError(self.seconds)
