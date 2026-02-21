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
    prompt_caching: bool = Field(
        default=False,
        description=(
            "Si True, marca el system prompt con cache_control para que el proveedor "
            "(Anthropic, OpenAI) lo cachee. Reduce el coste 50-90% en llamadas repetidas."
        ),
    )

    model_config = {"extra": "forbid"}


class AgentConfig(BaseModel):
    """Configuración de un agente específico."""

    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    confirm_mode: Literal["confirm-all", "confirm-sensitive", "yolo"] = "confirm-sensitive"
    max_steps: int = 20

    model_config = {"extra": "forbid"}


class HookConfig(BaseModel):
    """Configuración de un hook post-edit individual (v3-M4).

    Un hook es un comando que se ejecuta automáticamente cuando el agente
    edita un archivo que coincide con file_patterns. El resultado se devuelve
    al LLM para que pueda auto-corregir errores de lint/test.
    """

    name: str = Field(description="Nombre identificador del hook (ej: 'python-lint')")
    command: str = Field(description="Comando a ejecutar (shell). Recibe ARCHITECT_EDITED_FILE como env var.")
    file_patterns: list[str] = Field(
        description="Patrones glob de archivos que activan el hook (ej: ['*.py', '*.ts'])"
    )
    timeout: int = Field(default=15, ge=1, le=300, description="Timeout del comando en segundos")
    enabled: bool = Field(default=True, description="Si False, el hook se ignora")

    model_config = {"extra": "forbid"}


class HooksConfig(BaseModel):
    """Configuración de hooks post-edit (v3-M4)."""

    post_edit: list[HookConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados automáticamente después de editar un archivo",
    )

    model_config = {"extra": "forbid"}


class LoggingConfig(BaseModel):
    """Configuración del sistema de logging."""

    # v3: añadido "human" como nivel de trazabilidad del agente
    level: Literal["debug", "info", "human", "warn", "error"] = "human"
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


class CostsConfig(BaseModel):
    """Configuración del cost tracking (F14).

    Controla si se registran los costes de las llamadas al LLM y si se
    aplica un límite de presupuesto por ejecución.
    """

    enabled: bool = Field(
        default=True,
        description="Si True, se registran los costes de cada llamada al LLM.",
    )

    prices_file: Path | None = Field(
        default=None,
        description=(
            "Path a un archivo JSON con precios custom que sobreescriben los defaults. "
            "Mismo formato que default_prices.json."
        ),
    )

    budget_usd: float | None = Field(
        default=None,
        description=(
            "Límite de gasto en USD por ejecución. Si se supera, el agente se detiene "
            "con status 'partial'. None = sin límite."
        ),
    )

    warn_at_usd: float | None = Field(
        default=None,
        description=(
            "Umbral de aviso en USD. Cuando el gasto acumulado supera este valor "
            "se emite un log warning (sin detener la ejecución)."
        ),
    )

    model_config = {"extra": "forbid"}


class LLMCacheConfig(BaseModel):
    """Configuración del cache local de respuestas LLM (F14).

    El cache local es determinista: guarda respuestas completas en disco
    para evitar llamadas repetidas al LLM. Útil en desarrollo para ahorrar tokens.

    ATENCIÓN: Solo para desarrollo. No usar en producción (las respuestas
    cacheadas pueden quedar obsoletas si el contexto cambia).
    """

    enabled: bool = Field(
        default=False,
        description="Si True, activa el cache local de respuestas LLM.",
    )

    dir: Path = Field(
        default=Path("~/.architect/cache"),
        description="Directorio donde guardar las entradas de cache.",
    )

    ttl_hours: int = Field(
        default=24,
        ge=1,
        le=8760,  # 1 año
        description="Horas de validez de cada entrada de cache. Después se considera expirada.",
    )

    model_config = {"extra": "forbid"}


class CommandsConfig(BaseModel):
    """Configuración de la tool run_command (F13).

    Controla si el agente puede ejecutar comandos del sistema y qué restricciones
    de seguridad se aplican. La tool incluye cuatro capas de seguridad integradas:
    bloqueada por patrones, clasificación dinámica, timeouts y sandboxing de cwd.
    """

    enabled: bool = Field(
        default=True,
        description="Si False, la tool run_command no se registra y el agente no puede ejecutar comandos.",
    )

    default_timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Timeout por defecto en segundos para run_command si no se especifica uno explícito.",
    )

    max_output_lines: int = Field(
        default=200,
        ge=10,
        le=5000,
        description="Líneas máximas de stdout/stderr antes de truncar para evitar llenar el contexto.",
    )

    blocked_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Patrones regex adicionales a bloquear (además de los built-in: "
            "rm -rf /, sudo, chmod 777, curl|bash, etc.)."
        ),
    )

    safe_commands: list[str] = Field(
        default_factory=list,
        description=(
            "Comandos adicionales considerados seguros (no requieren confirmación). "
            "Se suman a los built-in: ls, cat, git status, etc."
        ),
    )

    allowed_only: bool = Field(
        default=False,
        description=(
            "Si True, solo se permiten comandos clasificados como 'safe' o 'dev'. "
            "Comandos 'dangerous' son rechazados en execute(), no solo en confirmación."
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
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    llm_cache: LLMCacheConfig = Field(default_factory=LLMCacheConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)  # v3-M4

    model_config = {"extra": "forbid"}
