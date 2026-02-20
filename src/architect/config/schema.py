"""
Modelos Pydantic para la configuración de architect.

Define todos los schemas de configuración usando Pydantic v2 para validación,
valores por defecto y serialización.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Configuración del proveedor LLM."""

    provider: str = "litellm"
    mode: Literal["proxy", "direct"] = "direct"
    model: str = "gpt-4o"
    api_base: str | None = None
    api_key_env: str = "LITELLM_API_KEY"
    timeout: int = 60
    retries: int = 2
    stream: bool = True

    model_config = {"extra": "forbid"}


class AgentConfig(BaseModel):
    """Configuración de un agente específico."""

    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    confirm_mode: Literal["confirm-all", "confirm-sensitive", "yolo"] = "confirm-sensitive"
    max_steps: int = 20

    model_config = {"extra": "forbid"}


class LoggingConfig(BaseModel):
    """Configuración del sistema de logging."""

    level: Literal["debug", "info", "warn", "error"] = "info"
    file: Path | None = None
    verbose: int = 0

    model_config = {"extra": "forbid"}


class WorkspaceConfig(BaseModel):
    """Configuración del workspace (directorio de trabajo)."""

    root: Path = Path(".")
    allow_delete: bool = False

    model_config = {"extra": "forbid"}


class MCPServerConfig(BaseModel):
    """Configuración de un servidor MCP individual."""

    name: str
    url: str
    token_env: str | None = None
    token: str | None = None

    model_config = {"extra": "forbid"}


class MCPConfig(BaseModel):
    """Configuración global de MCP."""

    servers: list[MCPServerConfig] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class IndexerConfig(BaseModel):
    """Configuración del indexador de repositorio (F10).

    El indexador construye un árbol ligero del workspace al inicio
    y lo inyecta en el system prompt del agente. Esto permite que el
    agente conozca la estructura del proyecto sin leer cada archivo.
    """

    enabled: bool = True
    """Si False, el indexador no se ejecuta y el agente no recibe el árbol."""

    max_file_size: int = Field(
        default=1_000_000,
        description="Tamaño máximo de archivo a indexar en bytes (default: 1MB)",
    )

    exclude_dirs: list[str] = Field(
        default_factory=list,
        description=(
            "Directorios adicionales a excluir (además de los defaults: "
            ".git, node_modules, __pycache__, .venv, etc.)"
        ),
    )

    exclude_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Patrones de archivos adicionales a excluir (además de los defaults: "
            "*.pyc, *.min.js, *.map, etc.)"
        ),
    )

    use_cache: bool = Field(
        default=True,
        description=(
            "Si True, cachea el índice en disco por 5 minutos para "
            "evitar reconstruirlo en cada llamada."
        ),
    )

    model_config = {"extra": "forbid"}


class ContextConfig(BaseModel):
    """Configuración del gestor de context window (F11).

    Controla el comportamiento del ContextManager, que evita que el contexto
    del LLM se llene en tareas largas. Actúa en tres niveles:
    - Nivel 1: Truncar tool results muy largos (siempre activo si enabled)
    - Nivel 2: Resumir pasos antiguos con el propio LLM cuando hay muchos steps
    - Nivel 3: Ventana deslizante con hard limit de tokens totales
    """

    max_tool_result_tokens: int = Field(
        default=2000,
        description=(
            "Tokens máximos por tool result antes de truncar (~4 chars/token). "
            "0 = sin truncado."
        ),
    )

    summarize_after_steps: int = Field(
        default=8,
        description=(
            "Número de intercambios tool call (pasos con tool calls) antes de "
            "intentar comprimir mensajes antiguos. 0 = desactivar resumen."
        ),
    )

    keep_recent_steps: int = Field(
        default=4,
        description="Pasos recientes completos a conservar durante la compresión.",
    )

    max_context_tokens: int = Field(
        default=80000,
        description=(
            "Límite hard del context window total estimado en tokens (~4 chars/token). "
            "0 = sin límite."
        ),
    )

    parallel_tools: bool = Field(
        default=True,
        description=(
            "Ejecutar tool calls independientes en paralelo usando ThreadPoolExecutor. "
            "Solo aplica cuando hay >1 tool call y ninguna requiere confirmación."
        ),
    )

    model_config = {"extra": "forbid"}


class EvaluationConfig(BaseModel):
    """Configuración de self-evaluation (F12).

    Controla si el agente evalúa automáticamente su propio resultado
    al terminar. Por defecto está desactivado para no consumir tokens extra.

    Modos disponibles:
    - ``"off"``   — Sin evaluación (default)
    - ``"basic"`` — Pregunta al LLM si la tarea se completó; si no, marca como ``partial``
    - ``"full"``  — Evaluación + hasta ``max_retries`` reintentos automáticos de corrección
    """

    mode: Literal["off", "basic", "full"] = "off"

    max_retries: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Número máximo de reintentos en modo 'full'.",
    )

    confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "Umbral de confianza mínimo para considerar la tarea completada en modo 'full'. "
            "Si el LLM evalúa confianza < threshold, se reintenta."
        ),
    )

    model_config = {"extra": "forbid"}


class AppConfig(BaseModel):
    """Configuración completa de la aplicación.

    Esta es la raíz del árbol de configuración. Combina todas las secciones
    y es el punto de entrada para validación.
    """

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    model_config = {"extra": "forbid"}
