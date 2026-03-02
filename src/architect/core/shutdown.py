"""
GracefulShutdown - SIGINT and SIGTERM signal handling for clean shutdown.

Manages agent interruption in an orderly fashion:
- First SIGINT (Ctrl+C): warns the user and sets the flag, lets the current step finish
- Second SIGINT: immediate exit with code 130
- SIGTERM: same behavior as first SIGINT (for CI/Docker environments)

The agent loop checks should_stop before each iteration to terminate
cleanly without cutting in the middle of an operation.
"""

import signal
import sys

import structlog

logger = structlog.get_logger()

EXIT_INTERRUPTED = 130  # POSIX standard: 128 + SIGINT(2)


class GracefulShutdown:
    """Manages shutdown signals for clean agent termination.

    Install once at the start of command execution and pass
    to AgentLoop so it can check before each step.

    Attributes:
        should_stop: True when an interruption signal has been received.

    Usage:
        shutdown = GracefulShutdown()
        loop = AgentLoop(llm, engine, config, ctx, shutdown=shutdown)
        state = loop.run(prompt)
    """

    def __init__(self) -> None:
        """Install signal handlers."""
        self._interrupted = False

        # Install handlers for both signals
        signal.signal(signal.SIGINT, self._handler)
        signal.signal(signal.SIGTERM, self._handler)

        logger.debug("graceful_shutdown.installed")

    def _handler(self, signum: int, frame) -> None:
        """Shared handler for SIGINT and SIGTERM.

        First trigger: warns and sets the flag.
        Second trigger (SIGINT only): immediate exit.
        """
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"

        if self._interrupted:
            # Second signal -> exit immediately
            logger.warning(
                "graceful_shutdown.forced",
                signal=signal_name,
            )
            sys.exit(EXIT_INTERRUPTED)

        # First signal -> mark and warn
        self._interrupted = True
        logger.warning(
            "graceful_shutdown.requested",
            signal=signal_name,
            message="Finishing after current step completes. Ctrl+C again to exit now.",
        )

        # Write visible warning to the user (stderr)
        sys.stderr.write(
            f"\n⚠️  {signal_name} received. Shutting down cleanly...\n"
            "   (Ctrl+C again for immediate exit)\n"
        )
        sys.stderr.flush()

    @property
    def should_stop(self) -> bool:
        """True if an interruption signal has been received."""
        return self._interrupted

    def reset(self) -> None:
        """Reset the flag (useful for testing)."""
        self._interrupted = False

    def restore_defaults(self) -> None:
        """Restore the default signal handlers."""
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        logger.debug("graceful_shutdown.restored_defaults")
