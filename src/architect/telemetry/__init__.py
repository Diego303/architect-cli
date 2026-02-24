"""
Telemetry — Observabilidad para architect vía OpenTelemetry.

v4-D4: Proporciona trazas distribuidas para sesiones de agente,
llamadas LLM y ejecuciones de tools.

Dependencias opcionales: opentelemetry-api, opentelemetry-sdk,
opentelemetry-exporter-otlp.
"""

from .otel import ArchitectTracer, NoopTracer

__all__ = [
    "ArchitectTracer",
    "NoopTracer",
]
