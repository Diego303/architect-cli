"""
Execution Engine - Orquestador central de ejecución de tools.

El ExecutionEngine es el punto de paso obligatorio para toda ejecución
de tools. Aplica validación, políticas de confirmación, dry-run y logging.
"""

from typing import Any

import structlog

from ..config.schema import AppConfig
from ..tools.base import BaseTool, ToolResult
from ..tools.registry import ToolNotFoundError, ToolRegistry
from .policies import ConfirmationPolicy, NoTTYError

logger = structlog.get_logger()


class ExecutionEngine:
    """Motor de ejecución de tools con validación y políticas.

    El ExecutionEngine aplica un pipeline completo a cada tool call:
    1. Buscar tool en registry
    2. Validar argumentos (Pydantic)
    3. Validar paths si aplica (ya dentro de cada tool)
    4. Aplicar política de confirmación
    5. Ejecutar (o simular en dry-run)
    6. Loggear resultado
    7. Retornar resultado (nunca excepción)

    Características clave:
    - NUNCA lanza excepciones al caller (siempre retorna ToolResult)
    - Soporta dry-run (simulación sin efectos secundarios)
    - Aplica políticas de confirmación configurables
    - Logging estructurado de todas las operaciones
    """

    def __init__(
        self,
        registry: ToolRegistry,
        config: AppConfig,
        confirm_mode: str | None = None,
    ):
        """Inicializa el execution engine.

        Args:
            registry: ToolRegistry con las tools disponibles
            config: Configuración completa de la aplicación
            confirm_mode: Override del modo de confirmación (opcional)
        """
        self.registry = registry
        self.config = config
        self.dry_run = False

        # Determinar modo de confirmación
        # Prioridad: argumento confirm_mode > config de agente > default
        mode = confirm_mode or "confirm-sensitive"
        self.policy = ConfirmationPolicy(mode)

        self.log = logger.bind(component="execution_engine")

    def execute_tool_call(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Ejecuta una tool call con el pipeline completo.

        Este es el método principal del ExecutionEngine. Aplica todas
        las validaciones y políticas antes de ejecutar la tool.

        Args:
            tool_name: Nombre de la tool a ejecutar
            args: Diccionario con argumentos sin validar

        Returns:
            ToolResult con el resultado de la ejecución o error

        Note:
            Este método NUNCA lanza excepciones. Todos los errores se
            capturan y retornan como ToolResult con success=False.
        """
        self.log.info(
            "tool.call.start",
            tool=tool_name,
            args=self._sanitize_args_for_log(args),
            dry_run=self.dry_run,
        )

        try:
            # 1. Buscar tool en registry
            try:
                tool = self.registry.get(tool_name)
            except ToolNotFoundError as e:
                self.log.error("tool.not_found", tool=tool_name)
                return ToolResult(
                    success=False,
                    output="",
                    error=str(e),
                )

            # 2. Validar argumentos con Pydantic
            try:
                validated_args = tool.validate_args(args)
            except Exception as e:
                self.log.error("tool.validation_error", tool=tool_name, error=str(e))
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Argumentos inválidos: {e}",
                )

            # 3. Aplicar política de confirmación
            if self.policy.should_confirm(tool):
                try:
                    confirmed = self.policy.request_confirmation(
                        tool_name,
                        args,
                        dry_run=self.dry_run,
                    )

                    if not confirmed:
                        self.log.info("tool.cancelled", tool=tool_name)
                        return ToolResult(
                            success=False,
                            output="",
                            error="Operación cancelada por el usuario",
                        )

                except NoTTYError as e:
                    self.log.error("tool.no_tty", tool=tool_name)
                    return ToolResult(
                        success=False,
                        output="",
                        error=str(e),
                    )

            # 4. Ejecutar (o simular en dry-run)
            if self.dry_run:
                self.log.info(
                    "tool.dry_run",
                    tool=tool_name,
                    args=validated_args.model_dump(),
                )
                return ToolResult(
                    success=True,
                    output=f"[DRY-RUN] Se ejecutaría {tool_name} con args: {validated_args.model_dump()}",
                )

            # 5. Ejecución real
            try:
                result = tool.execute(**validated_args.model_dump())
            except Exception as e:
                # Las tools NO deberían lanzar excepciones, pero
                # capturamos por si acaso (defensive programming)
                self.log.error(
                    "tool.execution_error",
                    tool=tool_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                result = ToolResult(
                    success=False,
                    output="",
                    error=f"Error interno de la tool: {e}",
                )

            # 6. Loggear resultado
            self.log.info(
                "tool.call.complete",
                tool=tool_name,
                success=result.success,
                output_length=len(result.output) if result.output else 0,
                has_error=result.error is not None,
            )

            return result

        except Exception as e:
            # Captura de último recurso para errores inesperados
            # en el propio ExecutionEngine
            self.log.error(
                "engine.unexpected_error",
                tool=tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado en el execution engine: {e}",
            )

    def _sanitize_args_for_log(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitiza argumentos para logging seguro.

        Trunca valores muy largos (como content) para evitar
        logs masivos.

        Args:
            args: Argumentos originales

        Returns:
            Diccionario sanitizado para logging
        """
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 200:
                sanitized[key] = value[:200] + f"... ({len(value)} chars total)"
            else:
                sanitized[key] = value

        return sanitized

    def set_dry_run(self, enabled: bool) -> None:
        """Habilita o deshabilita el modo dry-run.

        Args:
            enabled: True para habilitar dry-run, False para deshabilitar
        """
        self.dry_run = enabled
        self.log.info("engine.dry_run_mode", enabled=enabled)

    def __repr__(self) -> str:
        return (
            f"<ExecutionEngine("
            f"tools={self.registry.count()}, "
            f"mode={self.policy.mode}, "
            f"dry_run={self.dry_run})>"
        )
