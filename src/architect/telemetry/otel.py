"""
OpenTelemetry integration -- Distributed traces for architect.

v4-D4: Implements ArchitectTracer that emits spans for:
- Complete agent sessions
- Individual LLM calls
- Tool executions

Follows the OpenTelemetry GenAI Semantic Conventions:
- gen_ai.request.model
- gen_ai.usage.input_tokens
- gen_ai.usage.output_tokens
- gen_ai.usage.cost

Supported exporters:
- otlp: OpenTelemetry Protocol (gRPC)
- console: Prints spans to stderr (debugging)
- json-file: Writes spans to a JSON file

If OpenTelemetry is not installed, uses NoopTracer which does nothing.
"""

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import structlog

logger = structlog.get_logger()

__all__ = [
    "ArchitectTracer",
    "NoopTracer",
    "create_tracer",
]

# Try to import OpenTelemetry (optional dependency)
try:
    from opentelemetry import trace  # type: ignore[import-untyped]
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace.export import (  # type: ignore[import-untyped]
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


# Service name and version for traces
SERVICE_NAME = "architect"
SERVICE_VERSION = "1.1.0"


class NoopSpan:
    """Span that does nothing (for when OTel is not available)."""

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op."""

    def set_status(self, status: Any) -> None:
        """No-op."""

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """No-op."""

    def end(self) -> None:
        """No-op."""

    def __enter__(self) -> "NoopSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class NoopTracer:
    """Tracer that does nothing (when OpenTelemetry is not installed).

    Allows code to use the same interface without conditionals.
    """

    @contextmanager
    def start_session(
        self, task: str, agent: str, model: str, session_id: str = ""
    ) -> Generator[NoopSpan, None, None]:
        """No-op session span."""
        yield NoopSpan()

    @contextmanager
    def trace_llm_call(
        self,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        step: int = 0,
    ) -> Generator[NoopSpan, None, None]:
        """No-op LLM call span."""
        yield NoopSpan()

    @contextmanager
    def trace_tool(
        self,
        tool_name: str,
        success: bool = True,
        duration_ms: float = 0.0,
        **attrs: Any,
    ) -> Generator[NoopSpan, None, None]:
        """No-op tool span."""
        yield NoopSpan()

    def shutdown(self) -> None:
        """No-op."""


class ArchitectTracer:
    """OpenTelemetry tracer for architect.

    Emits spans for sessions, LLM calls, and tools using the
    OpenTelemetry GenAI Semantic Conventions.

    If OpenTelemetry is not installed, behaves as NoopTracer.

    Attributes:
        enabled: Whether the tracer is active.
        exporter_type: Configured exporter type.
    """

    def __init__(
        self,
        enabled: bool = True,
        exporter: str = "console",
        endpoint: str = "http://localhost:4317",
        trace_file: str | None = None,
    ) -> None:
        """Initialize the tracer.

        Args:
            enabled: If False, acts as NoopTracer.
            exporter: Exporter type ('otlp', 'console', 'json-file').
            endpoint: Endpoint for the OTLP exporter.
            trace_file: File path for the json-file exporter.
        """
        self.enabled = enabled and OTEL_AVAILABLE
        self.exporter_type = exporter
        self._provider: Any = None
        self._tracer: Any = None
        self._noop = NoopTracer()
        self.log = logger.bind(component="telemetry")

        if self.enabled:
            self._setup(exporter, endpoint, trace_file)
        elif enabled and not OTEL_AVAILABLE:
            self.log.warning(
                "telemetry.otel_not_available",
                msg="OpenTelemetry not installed. Install with: pip install architect-ai-cli[telemetry]",
            )

    def _setup(
        self, exporter: str, endpoint: str, trace_file: str | None
    ) -> None:
        """Configure the TracerProvider and exporter.

        Args:
            exporter: Exporter type.
            endpoint: OTLP endpoint.
            trace_file: File path for json-file exporter.
        """
        resource = Resource.create({
            "service.name": SERVICE_NAME,
            "service.version": SERVICE_VERSION,
        })
        self._provider = TracerProvider(resource=resource)

        match exporter:
            case "otlp":
                self._setup_otlp(endpoint)
            case "console":
                self._setup_console()
            case "json-file":
                self._setup_json_file(trace_file)
            case _:
                self.log.warning(
                    "telemetry.unknown_exporter",
                    exporter=exporter,
                    msg="Using console exporter as default",
                )
                self._setup_console()

        trace.set_tracer_provider(self._provider)
        self._tracer = trace.get_tracer(SERVICE_NAME, SERVICE_VERSION)

        self.log.info(
            "telemetry.initialized",
            exporter=exporter,
            endpoint=endpoint if exporter == "otlp" else None,
        )

    def _setup_otlp(self, endpoint: str) -> None:
        """Configure the OTLP exporter."""
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-untyped]
                OTLPSpanExporter,
            )

            otel_exporter = OTLPSpanExporter(endpoint=endpoint)
            self._provider.add_span_processor(BatchSpanProcessor(otel_exporter))
        except ImportError:
            self.log.warning(
                "telemetry.otlp_not_available",
                msg="opentelemetry-exporter-otlp not installed. Using console.",
            )
            self._setup_console()

    def _setup_console(self) -> None:
        """Configure the console exporter."""
        self._provider.add_span_processor(
            SimpleSpanProcessor(ConsoleSpanExporter())
        )

    def _setup_json_file(self, trace_file: str | None) -> None:
        """Configure the JSON file exporter."""
        # Uses a console exporter that writes to a file
        # (SimpleSpanProcessor is synchronous -- suitable for files)
        path = trace_file or ".architect/traces.json"
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        try:
            from opentelemetry.sdk.trace.export import (  # type: ignore[import-untyped]
                SpanExporter,
                SpanExportResult,
            )
            from opentelemetry.sdk.trace import ReadableSpan  # type: ignore[import-untyped]

            class JsonFileExporter(SpanExporter):
                """Writes spans as JSON to a file."""

                def __init__(self, file_path: str) -> None:
                    self.file_path = file_path

                def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
                    with open(self.file_path, "a") as f:
                        for span in spans:
                            data = {
                                "name": span.name,
                                "trace_id": format(span.context.trace_id, "032x"),
                                "span_id": format(span.context.span_id, "016x"),
                                "start_time": span.start_time,
                                "end_time": span.end_time,
                                "attributes": dict(span.attributes) if span.attributes else {},
                                "status": str(span.status),
                            }
                            f.write(json.dumps(data, default=str) + "\n")
                    return SpanExportResult.SUCCESS

                def shutdown(self) -> None:
                    pass

            self._provider.add_span_processor(
                SimpleSpanProcessor(JsonFileExporter(path))
            )
        except Exception as e:
            self.log.warning(
                "telemetry.json_file_fallback",
                error=str(e),
                msg="Fallback to console exporter",
            )
            self._setup_console()

    @contextmanager
    def start_session(
        self, task: str, agent: str, model: str, session_id: str = ""
    ) -> Generator[Any, None, None]:
        """Start a session span.

        Args:
            task: Agent task.
            agent: Agent name.
            model: LLM model.
            session_id: Session ID.

        Yields:
            Session span.
        """
        if not self.enabled or not self._tracer:
            yield NoopSpan()
            return

        with self._tracer.start_as_current_span(
            "architect.session",
            attributes={
                "architect.task": task[:200],
                "architect.agent": agent,
                "gen_ai.request.model": model,
                "architect.session_id": session_id,
            },
        ) as span:
            yield span

    @contextmanager
    def trace_llm_call(
        self,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        step: int = 0,
    ) -> Generator[Any, None, None]:
        """Trace an LLM call.

        Args:
            model: LLM model used.
            tokens_in: Input tokens.
            tokens_out: Output tokens.
            cost: Cost in USD.
            step: Current agent step.

        Yields:
            LLM call span.
        """
        if not self.enabled or not self._tracer:
            yield NoopSpan()
            return

        with self._tracer.start_as_current_span(
            "architect.llm.call",
            attributes={
                "gen_ai.request.model": model,
                "gen_ai.usage.input_tokens": tokens_in,
                "gen_ai.usage.output_tokens": tokens_out,
                "gen_ai.usage.cost": cost,
                "architect.step": step,
            },
        ) as span:
            yield span

    @contextmanager
    def trace_tool(
        self,
        tool_name: str,
        success: bool = True,
        duration_ms: float = 0.0,
        **attrs: Any,
    ) -> Generator[Any, None, None]:
        """Trace a tool execution.

        Args:
            tool_name: Name of the tool executed.
            success: Whether the execution was successful.
            duration_ms: Duration in milliseconds.
            **attrs: Additional attributes.

        Yields:
            Tool span.
        """
        if not self.enabled or not self._tracer:
            yield NoopSpan()
            return

        attributes: dict[str, Any] = {
            "architect.tool.name": tool_name,
            "architect.tool.success": success,
            "architect.tool.duration_ms": duration_ms,
        }
        # Add extra attributes (filter None)
        for key, value in attrs.items():
            if value is not None:
                attributes[f"architect.tool.{key}"] = str(value)

        with self._tracer.start_as_current_span(
            f"architect.tool.{tool_name}",
            attributes=attributes,
        ) as span:
            yield span

    def shutdown(self) -> None:
        """Stop the tracer and flush pending spans."""
        if self._provider:
            try:
                self._provider.shutdown()
            except Exception as e:
                self.log.warning("telemetry.shutdown_error", error=str(e))


def create_tracer(
    enabled: bool = False,
    exporter: str = "console",
    endpoint: str = "http://localhost:4317",
    trace_file: str | None = None,
) -> ArchitectTracer | NoopTracer:
    """Factory to create the appropriate tracer.

    If disabled or OTel is not installed, returns NoopTracer.

    Args:
        enabled: If True, attempts to create ArchitectTracer.
        exporter: Exporter type.
        endpoint: OTLP endpoint.
        trace_file: Path for json-file exporter.

    Returns:
        ArchitectTracer or NoopTracer based on configuration.
    """
    if not enabled:
        return NoopTracer()

    if not OTEL_AVAILABLE:
        logger.warning(
            "telemetry.otel_not_installed",
            msg="OpenTelemetry not available. Install with: pip install architect-ai-cli[telemetry]",
        )
        return NoopTracer()

    return ArchitectTracer(
        enabled=True,
        exporter=exporter,
        endpoint=endpoint,
        trace_file=trace_file,
    )
