# OpenTelemetry Traces

Trazabilidad opcional con OpenTelemetry para monitorear sesiones, llamadas LLM y ejecución de tools.

Implementado en `src/architect/telemetry/otel.py`. Disponible desde v1.0.0 (Plan base v4 Phase D — D4).

---

## Concepto

El `ArchitectTracer` emite spans OpenTelemetry en tres niveles:

1. **Session span**: engloba toda la ejecución (`architect run "..."`)
2. **LLM call spans**: cada llamada al modelo (tokens, coste, modelo)
3. **Tool spans**: cada ejecución de tool (nombre, éxito, duración)

Si OpenTelemetry no está instalado, se usa un `NoopTracer` transparente sin impacto en rendimiento.

---

## Configuración

### Config YAML

```yaml
telemetry:
  enabled: true
  exporter: otlp                        # otlp | console | json-file
  endpoint: http://localhost:4317       # para otlp (gRPC)
  trace_file: .architect/traces.json    # para json-file
```

### Dependencias opcionales

```bash
# Instalar el extra de telemetry
pip install architect[telemetry]

# O instalar manualmente
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

---

## Exportadores

### OTLP (OpenTelemetry Protocol)

Envía spans vía gRPC al endpoint configurado. Compatible con:
- **Jaeger** (backend de tracing)
- **Grafana Tempo** (observabilidad)
- **Datadog**, **Honeycomb**, **Lightstep**, etc.
- Cualquier collector OpenTelemetry

```yaml
telemetry:
  enabled: true
  exporter: otlp
  endpoint: http://localhost:4317   # collector o Jaeger
```

### Console

Imprime spans formateados en stderr. Ideal para debugging.

```yaml
telemetry:
  enabled: true
  exporter: console
```

### JSON File

Escribe spans como JSON a un archivo. Útil para análisis offline.

```yaml
telemetry:
  enabled: true
  exporter: json-file
  trace_file: .architect/traces.json
```

---

## Atributos semánticos

Se usan las [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) de OpenTelemetry:

### Session span

| Atributo | Descripción |
|----------|-------------|
| `architect.task` | Tarea del usuario (primeros 200 chars) |
| `architect.agent` | Nombre del agente |
| `gen_ai.request.model` | Modelo LLM |
| `architect.session_id` | ID de sesión |

### LLM call span

| Atributo | Descripción |
|----------|-------------|
| `gen_ai.request.model` | Modelo usado |
| `gen_ai.usage.input_tokens` | Tokens de entrada |
| `gen_ai.usage.output_tokens` | Tokens de salida |
| `gen_ai.usage.cost` | Coste en USD |
| `architect.step` | Número de paso |

### Tool span

| Atributo | Descripción |
|----------|-------------|
| `architect.tool_name` | Nombre de la tool |
| `architect.tool_success` | Si se ejecutó correctamente |
| `architect.tool_duration_ms` | Duración en milisegundos |

---

## API

### `create_tracer()`

Factory que retorna `ArchitectTracer` o `NoopTracer` según configuración y disponibilidad de OpenTelemetry.

```python
def create_tracer(
    enabled: bool = False,
    exporter: str = "console",
    endpoint: str = "http://localhost:4317",
    trace_file: str | None = None,
) -> ArchitectTracer | NoopTracer:
```

### `ArchitectTracer`

```python
class ArchitectTracer:
    def start_session(self, task: str, agent: str, model: str, session_id: str = "") -> ContextManager:
        """Span de nivel sesión."""

    def trace_llm_call(self, model: str, tokens_in: int, tokens_out: int, cost: float, step: int) -> ContextManager:
        """Span por llamada LLM."""

    def trace_tool(self, tool_name: str, success: bool, duration_ms: float, **attrs) -> ContextManager:
        """Span por ejecución de tool."""

    def shutdown(self) -> None:
        """Flush y cierre del tracer provider."""
```

### `NoopTracer` / `NoopSpan`

Implementación no-op para cuando OpenTelemetry no está disponible:

```python
class NoopSpan:
    def set_attribute(self, key, value): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass

class NoopTracer:
    def start_session(self, **kwargs): return NoopSpan()
    def trace_llm_call(self, **kwargs): return NoopSpan()
    def trace_tool(self, **kwargs): return NoopSpan()
    def shutdown(self): pass
```

### Constantes

```python
SERVICE_NAME = "architect"
SERVICE_VERSION = "1.0.0"
```

---

## Wiring en CLI

```python
# En cli.py (comando run)
tracer = create_tracer(
    enabled=config.telemetry.enabled,
    exporter=config.telemetry.exporter,
    endpoint=config.telemetry.endpoint,
    trace_file=config.telemetry.trace_file,
)

with tracer.start_session(task=prompt, agent=agent_name, model=model, session_id=session_id):
    state = loop.run(prompt, stream=use_stream)

tracer.shutdown()
```

---

## Ejemplo con Jaeger

```bash
# Levantar Jaeger
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest

# Configurar architect
cat > config.yaml << 'EOF'
telemetry:
  enabled: true
  exporter: otlp
  endpoint: http://localhost:4317
EOF

# Ejecutar con telemetry
architect run "refactoriza utils.py" -c config.yaml --mode yolo

# Ver traces en Jaeger UI
open http://localhost:16686
# → Servicio "architect" → buscar traces recientes
```

---

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `src/architect/telemetry/__init__.py` | Exports del módulo |
| `src/architect/telemetry/otel.py` | `ArchitectTracer`, `NoopTracer`, `NoopSpan`, `create_tracer()` |
| `src/architect/config/schema.py` | `TelemetryConfig` (Pydantic model) |
| `src/architect/cli.py` | Wiring: `create_tracer()` + `start_session()` + `shutdown()` |
| `tests/test_telemetry/test_telemetry.py` | 20 tests (9 skipped sin OpenTelemetry) |
| `tests/test_bugfixes/test_bugfixes.py` | Tests BUG-5 (wiring) |
