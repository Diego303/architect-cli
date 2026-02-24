"""
Modelos Pydantic para la configuración de architect.

Define todos los schemas de configuración usando Pydantic v2 para validación,
valores por defecto y serialización.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class HookItemConfig(BaseModel):
    """Configuración de un hook individual (v4-A1).

    Un hook es un comando shell que se ejecuta en puntos del lifecycle del agente.
    Recibe contexto vía env vars (ARCHITECT_EVENT, ARCHITECT_TOOL_NAME, etc.) y stdin JSON.

    Protocolo:
    - Exit 0 = ALLOW (JSON en stdout para contexto adicional o modificación de input)
    - Exit 2 = BLOCK (stderr = razón del bloqueo, solo para pre-hooks)
    - Otro   = Error (se logea warning, no bloquea)
    """

    name: str = Field(default="", description="Nombre descriptivo del hook")
    command: str = Field(description="Comando shell a ejecutar")
    matcher: str = Field(
        default="*",
        description="Regex/glob del tool name para filtrar (solo para tool hooks). '*' = todos.",
    )
    file_patterns: list[str] = Field(
        default_factory=list,
        description="Patrones glob de archivos que activan el hook (ej: ['*.py', '*.ts'])",
    )
    timeout: int = Field(default=10, ge=1, le=300, description="Timeout en segundos")
    async_: bool = Field(
        default=False,
        alias="async",
        description="Si True, ejecutar en background sin bloquear",
    )
    enabled: bool = Field(default=True, description="Si False, el hook se ignora")

    model_config = {"extra": "forbid", "populate_by_name": True}


# Backward-compat alias for v3-M4 code that references HookConfig
HookConfig = HookItemConfig


class HooksConfig(BaseModel):
    """Configuración del sistema de hooks (v4-A1).

    Organiza hooks por evento del lifecycle. Cada evento tiene una lista
    de hooks que se ejecutan en orden. Los hooks de post_edit son un alias
    de post_tool_use para backward compatibility con v3-M4.
    """

    pre_tool_use: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados ANTES de cada tool call",
    )
    post_tool_use: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados DESPUÉS de cada tool call",
    )
    pre_llm_call: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados ANTES de cada llamada al LLM",
    )
    post_llm_call: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados DESPUÉS de cada llamada al LLM",
    )
    session_start: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados al iniciar sesión",
    )
    session_end: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados al terminar sesión",
    )
    on_error: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados cuando un tool falla",
    )
    agent_complete: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados cuando el agente declara completado",
    )
    budget_warning: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados cuando se supera % del presupuesto",
    )
    context_compress: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks ejecutados antes de comprimir contexto",
    )
    # Backward compat: post_edit maps to post_tool_use with edit-tool matcher
    post_edit: list[HookItemConfig] = Field(
        default_factory=list,
        description="(Compat v3) Hooks post-edit. Se añaden a post_tool_use con matcher 'write_file|edit_file|apply_patch'.",
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

    @field_validator("mode", mode="before")
    @classmethod
    def _coerce_yaml_bool(cls, v: object) -> object:
        """YAML 1.1 parsea `off` sin comillas como False (bool). Lo convertimos a 'off'."""
        if v is False:
            return "off"
        return v

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


class QualityGateConfig(BaseModel):
    """Configuración de un quality gate individual (v4-A2).

    Los quality gates se ejecutan cuando el agente declara completado.
    Si un gate requerido falla, el agente recibe feedback y continúa.
    """

    name: str = Field(description="Nombre del quality gate (ej: 'lint', 'tests')")
    command: str = Field(description="Comando shell a ejecutar")
    required: bool = Field(
        default=True,
        description="Si True, el agente no puede terminar sin pasarlo",
    )
    timeout: int = Field(default=60, ge=1, le=600, description="Timeout en segundos")

    model_config = {"extra": "forbid"}


class CodeRuleConfig(BaseModel):
    """Configuración de una regla de código (v4-A2).

    Las code rules escanean el contenido escrito por el agente
    con regex para detectar patrones prohibidos.
    """

    pattern: str = Field(description="Regex a buscar en código escrito")
    message: str = Field(description="Mensaje al LLM cuando se detecta el patrón")
    severity: Literal["warn", "block"] = Field(
        default="warn",
        description="'warn' adjunta aviso, 'block' impide el write",
    )

    model_config = {"extra": "forbid"}


class GuardrailsConfig(BaseModel):
    """Configuración de guardrails de seguridad (v4-A2).

    Los guardrails son reglas DETERMINISTAS que se evalúan ANTES que los hooks
    y no pueden ser desactivados por el LLM. Son la capa de seguridad base.
    """

    enabled: bool = Field(
        default=False,
        description="Si True, activa el sistema de guardrails",
    )
    protected_files: list[str] = Field(
        default_factory=list,
        description="Patrones glob de archivos protegidos (ej: ['.env', '*.pem', '*.key'])",
    )
    blocked_commands: list[str] = Field(
        default_factory=list,
        description="Patrones regex de comandos bloqueados (ej: ['rm\\s+-[rf]+\\s+/'])",
    )
    max_files_modified: int | None = Field(
        default=None,
        description="Máximo de archivos que el agente puede modificar. None = sin límite.",
    )
    max_lines_changed: int | None = Field(
        default=None,
        description="Máximo de líneas cambiadas. None = sin límite.",
    )
    max_commands_executed: int | None = Field(
        default=None,
        description="Máximo de comandos que el agente puede ejecutar. None = sin límite.",
    )
    require_test_after_edit: bool = Field(
        default=False,
        description="Si True, fuerza al agente a ejecutar tests después de editar.",
    )
    quality_gates: list[QualityGateConfig] = Field(
        default_factory=list,
        description="Quality gates ejecutados cuando el agente declara completado.",
    )
    code_rules: list[CodeRuleConfig] = Field(
        default_factory=list,
        description="Reglas regex que escanean contenido escrito por el agente.",
    )

    model_config = {"extra": "forbid"}


class MemoryConfig(BaseModel):
    """Configuración de memoria procedural (v4-A4)."""

    enabled: bool = Field(
        default=False,
        description="Si True, activa la memoria procedural.",
    )
    auto_detect_corrections: bool = Field(
        default=True,
        description="Si True, detecta correcciones automáticamente en mensajes del usuario.",
    )

    model_config = {"extra": "forbid"}


class SkillsConfig(BaseModel):
    """Configuración del ecosistema de skills (v4-A3)."""

    auto_discover: bool = Field(
        default=True,
        description="Si True, descubre skills automáticamente en .architect/skills/",
    )
    inject_by_glob: bool = Field(
        default=True,
        description="Si True, inyecta skills relevantes según los globs de archivos activos.",
    )

    model_config = {"extra": "forbid"}


class SessionsConfig(BaseModel):
    """Configuración de persistencia de sesiones (v4-B1).

    Controla si el agente guarda automáticamente el estado de cada sesión
    para poder reanudarla después de una interrupción.
    """

    auto_save: bool = Field(
        default=True,
        description="Si True, guarda estado después de cada step automáticamente.",
    )
    cleanup_after_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Días después de los cuales las sesiones se limpian automáticamente.",
    )

    model_config = {"extra": "forbid"}


# ── Phase C Config Schemas ─────────────────────────────────────────────


class RalphLoopConfig(BaseModel):
    """Configuración del Ralph Loop nativo (v4-C1).

    El Ralph Loop ejecuta iteraciones del agente hasta que todos los checks
    pasen. Cada iteración usa un agente con contexto LIMPIO.
    """

    max_iterations: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Número máximo de iteraciones del loop.",
    )
    max_cost: float | None = Field(
        default=None,
        description="Coste máximo total en USD. None = sin límite.",
    )
    max_time: int | None = Field(
        default=None,
        ge=1,
        description="Tiempo máximo total en segundos. None = sin límite.",
    )
    completion_tag: str = Field(
        default="COMPLETE",
        description="Tag que el agente emite cuando declara completado.",
    )
    agent: str = Field(
        default="build",
        description="Agente a usar en cada iteración.",
    )

    model_config = {"extra": "forbid"}


class ParallelRunsConfig(BaseModel):
    """Configuración de ejecuciones paralelas con worktrees (v4-C2).

    Ejecuta múltiples agentes en paralelo, cada uno en un git worktree
    separado para aislamiento total.
    """

    workers: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Número de workers paralelos.",
    )
    agent: str = Field(
        default="build",
        description="Agente a usar en cada worker.",
    )
    max_steps: int = Field(
        default=50,
        ge=1,
        description="Máximo de pasos por worker.",
    )
    budget_per_worker: float | None = Field(
        default=None,
        description="Presupuesto en USD por worker. None = sin límite.",
    )
    timeout_per_worker: int | None = Field(
        default=None,
        ge=1,
        description="Timeout en segundos por worker. None = 600s.",
    )

    model_config = {"extra": "forbid"}


class CheckpointsConfig(BaseModel):
    """Configuración de checkpoints y rollback (v4-C4).

    Checkpoints son git commits con prefijo especial que permiten
    restaurar el estado del workspace a un punto anterior.
    """

    enabled: bool = Field(
        default=False,
        description="Si True, activa checkpoints automáticos.",
    )
    every_n_steps: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Crear checkpoint cada N pasos del agente.",
    )

    model_config = {"extra": "forbid"}


class AutoReviewConfig(BaseModel):
    """Configuración de auto-review writer/reviewer (v4-C5).

    Cuando está activo, al completar una tarea el agente reviewer
    inspecciona los cambios y, si encuentra problemas, el builder
    realiza un fix-pass.
    """

    enabled: bool = Field(
        default=False,
        description="Si True, activa auto-review tras completar.",
    )
    review_model: str | None = Field(
        default=None,
        description="Modelo LLM para el reviewer. None = usa el mismo que el builder.",
    )
    max_fix_passes: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Máximo de fix-passes tras review. 0 = solo reportar.",
    )

    model_config = {"extra": "forbid"}


# ── Phase D Config Schemas ─────────────────────────────────────────────


class TelemetryConfig(BaseModel):
    """Configuración de OpenTelemetry (v4-D4).

    Cuando está habilitado, emite trazas distribuidas para sesiones,
    llamadas LLM y ejecuciones de tools. Requiere dependencias opcionales:
    opentelemetry-api, opentelemetry-sdk.
    """

    enabled: bool = Field(
        default=False,
        description="Si True, activa la emisión de trazas OpenTelemetry.",
    )
    exporter: Literal["otlp", "console", "json-file"] = Field(
        default="console",
        description="Tipo de exporter: otlp (gRPC), console (stderr), json-file.",
    )
    endpoint: str = Field(
        default="http://localhost:4317",
        description="Endpoint para el exporter OTLP.",
    )
    trace_file: str | None = Field(
        default=None,
        description="Path del archivo para el exporter json-file.",
    )

    model_config = {"extra": "forbid"}


class HealthConfig(BaseModel):
    """Configuración de Code Health Delta (v4-D2).

    Cuando está habilitado, analiza métricas de salud del código antes y
    después de la sesión del agente, generando un delta report.
    Requiere dependencia opcional: radon (para complejidad ciclomática).
    """

    enabled: bool = Field(
        default=False,
        description="Si True, ejecuta análisis de salud antes/después de la sesión.",
    )
    include_patterns: list[str] = Field(
        default_factory=lambda: ["**/*.py"],
        description="Patrones glob de archivos a analizar.",
    )
    exclude_dirs: list[str] = Field(
        default_factory=list,
        description="Directorios adicionales a excluir del análisis.",
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
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)  # v4-A2
    memory: MemoryConfig = Field(default_factory=MemoryConfig)  # v4-A4
    skills: SkillsConfig = Field(default_factory=SkillsConfig)  # v4-A3
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)  # v4-B1
    ralph: RalphLoopConfig = Field(default_factory=RalphLoopConfig)  # v4-C1
    parallel: ParallelRunsConfig = Field(default_factory=ParallelRunsConfig)  # v4-C2
    checkpoints: CheckpointsConfig = Field(default_factory=CheckpointsConfig)  # v4-C4
    auto_review: AutoReviewConfig = Field(default_factory=AutoReviewConfig)  # v4-C5
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)  # v4-D4
    health: HealthConfig = Field(default_factory=HealthConfig)  # v4-D2

    model_config = {"extra": "forbid"}
