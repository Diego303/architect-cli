"""
Tests para OpenTelemetry integration (v4-D4).

Cubre:
- NoopSpan (no-op methods)
- NoopTracer (context managers que retornan NoopSpan)
- ArchitectTracer (init, setup, spans, shutdown)
- create_tracer factory
- Comportamiento cuando OTel no está instalado
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from architect.telemetry.otel import (
    OTEL_AVAILABLE,
    SERVICE_NAME,
    SERVICE_VERSION,
    ArchitectTracer,
    NoopSpan,
    NoopTracer,
    create_tracer,
)


# -- Tests: NoopSpan --------------------------------------------------------


class TestNoopSpan:
    """Tests para NoopSpan."""

    def test_set_attribute(self):
        span = NoopSpan()
        span.set_attribute("key", "value")  # No debe crashear

    def test_set_status(self):
        span = NoopSpan()
        span.set_status("ok")  # No debe crashear

    def test_add_event(self):
        span = NoopSpan()
        span.add_event("test", {"key": "value"})  # No debe crashear

    def test_end(self):
        span = NoopSpan()
        span.end()  # No debe crashear

    def test_context_manager(self):
        span = NoopSpan()
        with span as s:
            assert isinstance(s, NoopSpan)


# -- Tests: NoopTracer -------------------------------------------------------


class TestNoopTracer:
    """Tests para NoopTracer."""

    def test_start_session(self):
        tracer = NoopTracer()
        with tracer.start_session(task="test", agent="build", model="gpt-4o") as span:
            assert isinstance(span, NoopSpan)

    def test_trace_llm_call(self):
        tracer = NoopTracer()
        with tracer.trace_llm_call(model="gpt-4o", tokens_in=100, tokens_out=50) as span:
            assert isinstance(span, NoopSpan)

    def test_trace_tool(self):
        tracer = NoopTracer()
        with tracer.trace_tool(tool_name="read_file", success=True) as span:
            assert isinstance(span, NoopSpan)

    def test_shutdown(self):
        tracer = NoopTracer()
        tracer.shutdown()  # No debe crashear


# -- Tests: create_tracer factory --------------------------------------------


class TestCreateTracer:
    """Tests para la factory create_tracer."""

    def test_disabled_returns_noop(self):
        tracer = create_tracer(enabled=False)
        assert isinstance(tracer, NoopTracer)

    def test_enabled_without_otel_returns_noop(self):
        with patch("architect.telemetry.otel.OTEL_AVAILABLE", False):
            tracer = create_tracer(enabled=True)
            assert isinstance(tracer, NoopTracer)

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_enabled_with_otel_returns_architect_tracer(self):
        tracer = create_tracer(enabled=True, exporter="console")
        assert isinstance(tracer, ArchitectTracer)
        tracer.shutdown()


# -- Tests: ArchitectTracer --------------------------------------------------


class TestArchitectTracer:
    """Tests para ArchitectTracer."""

    def test_disabled_tracer(self):
        tracer = ArchitectTracer(enabled=False)
        assert not tracer.enabled

        # Debe comportarse como noop
        with tracer.start_session("t", "a", "m") as span:
            assert isinstance(span, NoopSpan)

    def test_disabled_context_managers(self):
        tracer = ArchitectTracer(enabled=False)

        with tracer.trace_llm_call(model="m") as span:
            assert isinstance(span, NoopSpan)

        with tracer.trace_tool(tool_name="t") as span:
            assert isinstance(span, NoopSpan)

    def test_shutdown_noop(self):
        tracer = ArchitectTracer(enabled=False)
        tracer.shutdown()  # No debe crashear

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_console_exporter_setup(self):
        tracer = ArchitectTracer(enabled=True, exporter="console")
        assert tracer.enabled
        assert tracer._tracer is not None
        tracer.shutdown()

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_session_span(self):
        tracer = ArchitectTracer(enabled=True, exporter="console")
        with tracer.start_session(
            task="test task",
            agent="build",
            model="gpt-4o",
            session_id="test-123",
        ) as span:
            assert span is not None
            # span debe tener atributos
        tracer.shutdown()

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_llm_call_span(self):
        tracer = ArchitectTracer(enabled=True, exporter="console")
        with tracer.trace_llm_call(
            model="gpt-4o",
            tokens_in=500,
            tokens_out=200,
            cost=0.01,
            step=3,
        ) as span:
            assert span is not None
        tracer.shutdown()

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_tool_span(self):
        tracer = ArchitectTracer(enabled=True, exporter="console")
        with tracer.trace_tool(
            tool_name="read_file",
            success=True,
            duration_ms=15.3,
            file_path="src/main.py",
        ) as span:
            assert span is not None
        tracer.shutdown()

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_json_file_exporter(self, tmp_path):
        trace_file = str(tmp_path / "traces.json")
        tracer = ArchitectTracer(
            enabled=True,
            exporter="json-file",
            trace_file=trace_file,
        )
        with tracer.start_session("task", "build", "gpt-4o"):
            pass
        tracer.shutdown()
        # El archivo debería existir (o haberse creado el directorio)

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_unknown_exporter_falls_back(self):
        tracer = ArchitectTracer(enabled=True, exporter="unknown_exporter")
        assert tracer.enabled  # Debería usar console como fallback
        tracer.shutdown()

    def test_otel_not_available_warns(self):
        with patch("architect.telemetry.otel.OTEL_AVAILABLE", False):
            tracer = ArchitectTracer(enabled=True, exporter="console")
            assert not tracer.enabled

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_nested_spans(self):
        tracer = ArchitectTracer(enabled=True, exporter="console")
        with tracer.start_session("task", "build", "gpt-4o"):
            with tracer.trace_llm_call("gpt-4o", 100, 50, 0.01):
                pass
            with tracer.trace_tool("read_file"):
                pass
        tracer.shutdown()

    @pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry not installed")
    def test_tool_span_extra_attrs(self):
        tracer = ArchitectTracer(enabled=True, exporter="console")
        with tracer.trace_tool(
            tool_name="write_file",
            success=True,
            duration_ms=25.0,
            file_path="src/new.py",
            lines_written=50,
        ) as span:
            assert span is not None
        tracer.shutdown()


# -- Tests: Constants --------------------------------------------------------


class TestConstants:
    """Tests para constantes."""

    def test_service_name(self):
        assert SERVICE_NAME == "architect"

    def test_service_version(self):
        assert SERVICE_VERSION == "1.1.0"
