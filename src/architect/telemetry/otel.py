"""
OpenTelemetry integration — Trazas distribuidas para architect.

v4-D4: Implementa ArchitectTracer que emite spans para:
- Sesiones completas del agente
- Llamadas individuales al LLM
- Ejecuciones de tools

Sigue las GenAI Semantic Conventions de OpenTelemetry:
- gen_ai.request.model
- gen_ai.usage.input_tokens
- gen_ai.usage.output_tokens
- gen_ai.usage.cost

Exporters soportados:
- otlp: OpenTelemetry Protocol (gRPC)
- console: Imprime spans en stderr (debugging)
- json-file: Escribe spans a un archivo JSON

Si OpenTelemetry no está instalado, usa NoopTracer que no hace nada.
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

# Intentar importar OpenTelemetry (dependencia opcional)
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


# Nombre y versión del servicio para las trazas
SERVICE_NAME = "architect"
SERVICE_VERSION = "1.0.0"


class NoopSpan:
    """Span que no hace nada (para cuando OTel no está disponible)."""

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
    """Tracer que no hace nada (cuando OpenTelemetry no está instalado).

    Permite que el código use la misma interfaz sin condicionales.
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
    """Tracer de OpenTelemetry para architect.

    Emite spans para sesiones, llamadas LLM y tools usando las
    GenAI Semantic Conventions de OpenTelemetry.

    Si OpenTelemetry no está instalado, se comporta como NoopTracer.

    Attributes:
        enabled: Si el tracer está activo.
        exporter_type: Tipo de exporter configurado.
    """

    def __init__(
        self,
        enabled: bool = True,
        exporter: str = "console",
        endpoint: str = "http://localhost:4317",
        trace_file: str | None = None,
    ) -> None:
        """Inicializa el tracer.

        Args:
            enabled: Si False, actúa como NoopTracer.
            exporter: Tipo de exporter ('otlp', 'console', 'json-file').
            endpoint: Endpoint para el exporter OTLP.
            trace_file: Path del archivo para el exporter json-file.
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
                msg="OpenTelemetry no instalado. Instala con: pip install architect[telemetry]",
            )

    def _setup(
        self, exporter: str, endpoint: str, trace_file: str | None
    ) -> None:
        """Configura el TracerProvider y exporter.

        Args:
            exporter: Tipo de exporter.
            endpoint: Endpoint OTLP.
            trace_file: Path del archivo para json-file exporter.
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
                    msg="Usando console exporter por defecto",
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
        """Configura el exporter OTLP."""
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-untyped]
                OTLPSpanExporter,
            )

            otel_exporter = OTLPSpanExporter(endpoint=endpoint)
            self._provider.add_span_processor(BatchSpanProcessor(otel_exporter))
        except ImportError:
            self.log.warning(
                "telemetry.otlp_not_available",
                msg="opentelemetry-exporter-otlp no instalado. Usando console.",
            )
            self._setup_console()

    def _setup_console(self) -> None:
        """Configura el exporter de consola."""
        self._provider.add_span_processor(
            SimpleSpanProcessor(ConsoleSpanExporter())
        )

    def _setup_json_file(self, trace_file: str | None) -> None:
        """Configura el exporter a archivo JSON."""
        # Usa un exporter de consola que escribe a archivo
        # (SimpleSpanProcessor es síncrono — adecuado para archivos)
        path = trace_file or ".architect/traces.json"
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        try:
            from opentelemetry.sdk.trace.export import (  # type: ignore[import-untyped]
                SpanExporter,
                SpanExportResult,
            )
            from opentelemetry.sdk.trace import ReadableSpan  # type: ignore[import-untyped]

            class JsonFileExporter(SpanExporter):
                """Escribe spans como JSON a un archivo."""

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
                msg="Fallback a console exporter",
            )
            self._setup_console()

    @contextmanager
    def start_session(
        self, task: str, agent: str, model: str, session_id: str = ""
    ) -> Generator[Any, None, None]:
        """Inicia un span de sesión.

        Args:
            task: Tarea del agente.
            agent: Nombre del agente.
            model: Modelo LLM.
            session_id: ID de sesión.

        Yields:
            Span de la sesión.
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
        """Traza una llamada al LLM.

        Args:
            model: Modelo LLM usado.
            tokens_in: Tokens de input.
            tokens_out: Tokens de output.
            cost: Coste en USD.
            step: Paso actual del agente.

        Yields:
            Span de la llamada LLM.
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
        """Traza una ejecución de tool.

        Args:
            tool_name: Nombre del tool ejecutado.
            success: Si la ejecución fue exitosa.
            duration_ms: Duración en milisegundos.
            **attrs: Atributos adicionales.

        Yields:
            Span del tool.
        """
        if not self.enabled or not self._tracer:
            yield NoopSpan()
            return

        attributes: dict[str, Any] = {
            "architect.tool.name": tool_name,
            "architect.tool.success": success,
            "architect.tool.duration_ms": duration_ms,
        }
        # Añadir atributos extra (filtrar None)
        for key, value in attrs.items():
            if value is not None:
                attributes[f"architect.tool.{key}"] = str(value)

        with self._tracer.start_as_current_span(
            f"architect.tool.{tool_name}",
            attributes=attributes,
        ) as span:
            yield span

    def shutdown(self) -> None:
        """Detiene el tracer y hace flush de spans pendientes."""
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
    """Factory para crear el tracer apropiado.

    Si está deshabilitado o OTel no está instalado, retorna NoopTracer.

    Args:
        enabled: Si True, intenta crear ArchitectTracer.
        exporter: Tipo de exporter.
        endpoint: Endpoint OTLP.
        trace_file: Path para json-file exporter.

    Returns:
        ArchitectTracer o NoopTracer según configuración.
    """
    if not enabled:
        return NoopTracer()

    if not OTEL_AVAILABLE:
        logger.warning(
            "telemetry.otel_not_installed",
            msg="OpenTelemetry no disponible. Instala con: pip install architect[telemetry]",
        )
        return NoopTracer()

    return ArchitectTracer(
        enabled=True,
        exporter=exporter,
        endpoint=endpoint,
        trace_file=trace_file,
    )
