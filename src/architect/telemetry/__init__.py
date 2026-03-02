"""
Telemetry -- Observability for architect via OpenTelemetry.

v4-D4: Provides distributed traces for agent sessions,
LLM calls, and tool executions.

Optional dependencies: opentelemetry-api, opentelemetry-sdk,
opentelemetry-exporter-otlp.
"""

from .otel import ArchitectTracer, NoopTracer

__all__ = [
    "ArchitectTracer",
    "NoopTracer",
]
