"""
Agent Loop - Ciclo principal de ejecución del agente.

Este es el corazón del sistema. Orquesta la interacción entre
el LLM y las tools, gestionando el flujo completo de ejecución.

Incluye:
- Timeout por step (StepTimeout) para evitar bloqueos indefinidos
- Comprobación de shutdown antes de cada iteración (GracefulShutdown)
- Manejo robusto de errores que no rompe el loop
- Parallel tool calls (F11): ejecución concurrente de tools independientes
- Context pruning (F11): compresión de mensajes cuando el contexto crece
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Callable

import structlog

from ..config.schema import AgentConfig
from ..execution.engine import ExecutionEngine
from ..llm.adapter import LLMAdapter, StreamChunk
from .context import ContextBuilder, ContextManager
from .shutdown import GracefulShutdown
from .state import AgentState, StepResult, ToolCallResult
from .timeout import StepTimeout, StepTimeoutError

if TYPE_CHECKING:
    from ..llm.adapter import ToolCall

logger = structlog.get_logger()


class AgentLoop:
    """Loop principal del agente.

    Orquesta el ciclo completo:
    1. Comprobar si hay señal de shutdown — salir limpiamente si la hay
    2. Enviar mensajes al LLM (con timeout por step)
    3. Recibir respuesta (texto o tool calls)
    4. Ejecutar tool calls si las hay (con timeout)
    5. Enviar resultados de vuelta al LLM
    6. Repetir hasta que el agente termine o se alcance max_steps
    """

    def __init__(
        self,
        llm: LLMAdapter,
        engine: ExecutionEngine,
        agent_config: AgentConfig,
        context_builder: ContextBuilder,
        shutdown: GracefulShutdown | None = None,
        step_timeout: int = 0,
        context_manager: ContextManager | None = None,
    ):
        """Inicializa el agent loop.

        Args:
            llm: LLMAdapter configurado
            engine: ExecutionEngine configurado
            agent_config: Configuración del agente
            context_builder: ContextBuilder para mensajes
            shutdown: GracefulShutdown para detectar interrupciones (opcional)
            step_timeout: Segundos máximos por step. 0 = sin timeout.
            context_manager: ContextManager para pruning del contexto (F11).
                             Si es None, no se aplica pruning.
        """
        self.llm = llm
        self.engine = engine
        self.agent_config = agent_config
        self.ctx = context_builder
        self.shutdown = shutdown
        self.step_timeout = step_timeout
        self.context_manager = context_manager
        self.log = logger.bind(component="agent_loop")

    def run(
        self,
        prompt: str,
        stream: bool = False,
        on_stream_chunk: Callable[[str], None] | None = None,
    ) -> AgentState:
        """Ejecuta el agent loop completo.

        Args:
            prompt: Prompt inicial del usuario
            stream: Si True, usa streaming del LLM
            on_stream_chunk: Callback opcional para chunks (recibe el texto del chunk)

        Returns:
            AgentState final con el resultado de la ejecución
        """
        # Inicializar estado
        state = AgentState()
        state.messages = self.ctx.build_initial(self.agent_config, prompt)
        state.model = self.llm.config.model

        # Obtener schemas de tools permitidas
        tools_schema = self.engine.registry.get_schemas(
            self.agent_config.allowed_tools or None
        )

        self.log.info(
            "agent.loop.start",
            prompt=prompt[:100] + "..." if len(prompt) > 100 else prompt,
            max_steps=self.agent_config.max_steps,
            allowed_tools=self.agent_config.allowed_tools or "all",
        )

        # Loop principal
        for step in range(self.agent_config.max_steps):

            # 0. Comprobar señal de shutdown antes de cada step
            if self.shutdown and self.shutdown.should_stop:
                self.log.warning(
                    "agent.shutdown_requested",
                    step=step,
                )
                state.status = "partial"
                state.final_output = (
                    state.final_output
                    or "Ejecución interrumpida por señal de shutdown."
                )
                break

            self.log.info("agent.step.start", step=step)

            # 1. Llamar al LLM envuelto en StepTimeout
            try:
                with StepTimeout(self.step_timeout):
                    if stream:
                        # Modo streaming
                        response = None
                        for chunk_or_response in self.llm.completion_stream(
                            messages=state.messages,
                            tools=tools_schema if tools_schema else None,
                        ):
                            if isinstance(chunk_or_response, StreamChunk):
                                if on_stream_chunk and chunk_or_response.type == "content":
                                    on_stream_chunk(chunk_or_response.data)
                            else:
                                response = chunk_or_response

                        if response is None:
                            raise RuntimeError("Streaming completó sin retornar respuesta final")
                    else:
                        response = self.llm.completion(
                            messages=state.messages,
                            tools=tools_schema if tools_schema else None,
                        )

            except StepTimeoutError as e:
                self.log.error(
                    "agent.step_timeout",
                    step=step,
                    seconds=self.step_timeout,
                )
                state.status = "partial"
                state.final_output = (
                    f"Step {step} excedió el tiempo máximo de {self.step_timeout}s. "
                    f"El agente completó {state.total_tool_calls} tool calls antes del timeout."
                )
                break

            except Exception as e:
                self.log.error("agent.llm_error", error=str(e), step=step)
                state.status = "failed"
                state.final_output = f"Error al comunicarse con el LLM: {e}"
                break

            # 2. Verificar si el LLM terminó con una respuesta final
            if response.finish_reason == "stop" and not response.tool_calls:
                state.final_output = response.content
                state.status = "success"
                self.log.info(
                    "agent.complete",
                    step=step,
                    output_preview=response.content[:100] + "..."
                    if response.content and len(response.content) > 100
                    else response.content,
                )
                break

            # 3. Si hay tool calls, ejecutarlas
            if response.tool_calls:
                self.log.info(
                    "agent.tool_calls_received",
                    step=step,
                    count=len(response.tool_calls),
                    tools=[tc.name for tc in response.tool_calls],
                )

                # Ejecutar tool calls (paralelo o secuencial según configuración)
                tool_results = self._execute_tool_calls_batch(
                    response.tool_calls, step
                )

                # 4. Actualizar mensajes con tool results
                state.messages = self.ctx.append_tool_results(
                    state.messages, response.tool_calls, tool_results
                )

                # F11: Comprimir contexto si hay demasiados pasos (Nivel 2)
                if self.context_manager:
                    state.messages = self.context_manager.maybe_compress(
                        state.messages, self.llm
                    )
                    # Nivel 3: Hard limit de tokens
                    state.messages = self.context_manager.enforce_window(
                        state.messages
                    )

                # 5. Registrar step
                state.steps.append(StepResult(
                    step_number=step,
                    llm_response=response,
                    tool_calls_made=tool_results,
                ))

            else:
                # El LLM respondió sin tool calls y sin finish_reason="stop"
                self.log.warning(
                    "agent.unexpected_response",
                    step=step,
                    finish_reason=response.finish_reason,
                    has_content=response.content is not None,
                )

                state.steps.append(StepResult(
                    step_number=step,
                    llm_response=response,
                    tool_calls_made=[],
                ))

                if response.finish_reason == "length":
                    # Token limit alcanzado → intentar continuar
                    self.log.info("agent.token_limit", step=step)
                    continue
                else:
                    state.status = "partial"
                    state.final_output = (
                        response.content or "El agente no produjo una respuesta clara."
                    )
                    break

        else:
            # Se agotaron todos los pasos
            self.log.warning(
                "agent.max_steps_reached",
                max_steps=self.agent_config.max_steps,
            )
            state.status = "partial"
            state.final_output = (
                f"Se alcanzó el límite de {self.agent_config.max_steps} pasos. "
                f"El agente ejecutó {state.total_tool_calls} tool calls pero no terminó completamente."
            )

        # Log final
        self.log.info(
            "agent.loop.complete",
            status=state.status,
            total_steps=state.current_step,
            total_tool_calls=state.total_tool_calls,
        )

        return state

    def _execute_tool_calls_batch(
        self,
        tool_calls: list,
        step: int,
    ) -> list[ToolCallResult]:
        """Ejecuta un lote de tool calls, paralelizando si es seguro (F11).

        La paralelización solo se activa cuando:
        - Hay más de una tool call
        - ``parallel_tools=True`` en la configuración (o no hay context_manager)
        - El modo de confirmación es ``yolo``
        - O el modo es ``confirm-sensitive`` y ninguna tool es sensible

        En cualquier otro caso (``confirm-all``, tools sensibles, una sola tool),
        la ejecución es secuencial para permitir la interacción con el usuario.

        Args:
            tool_calls: Lista de ToolCall del LLM
            step: Número de step actual (para logging)

        Returns:
            Lista de ToolCallResult en el mismo orden que tool_calls
        """
        if not tool_calls:
            return []

        if len(tool_calls) == 1:
            return [self._execute_single_tool(tool_calls[0], step)]

        if not self._should_parallelize(tool_calls):
            # Ejecución secuencial
            return [self._execute_single_tool(tc, step) for tc in tool_calls]

        # Ejecución paralela: preservar orden original
        self.log.info(
            "agent.tool_calls.parallel",
            step=step,
            count=len(tool_calls),
            tools=[tc.name for tc in tool_calls],
        )
        results: list[ToolCallResult | None] = [None] * len(tool_calls)
        max_workers = min(len(tool_calls), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._execute_single_tool, tc, step): i
                for i, tc in enumerate(tool_calls)
            }
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()

        return results  # type: ignore[return-value]

    def _execute_single_tool(self, tc: object, step: int) -> ToolCallResult:
        """Ejecuta una sola tool call y devuelve el resultado.

        Args:
            tc: ToolCall del LLM
            step: Número de step (para logging)

        Returns:
            ToolCallResult con el resultado de la ejecución
        """
        # tc es un ToolCall de llm.adapter
        self.log.info(
            "agent.tool_call.execute",
            step=step,
            tool=tc.name,  # type: ignore[attr-defined]
            args=self._sanitize_args_for_log(tc.arguments),  # type: ignore[attr-defined]
        )

        result = self.engine.execute_tool_call(
            tc.name,  # type: ignore[attr-defined]
            tc.arguments,  # type: ignore[attr-defined]
        )

        self.log.info(
            "agent.tool_call.complete",
            step=step,
            tool=tc.name,  # type: ignore[attr-defined]
            success=result.success,
            error=result.error if not result.success else None,
        )

        return ToolCallResult(
            tool_name=tc.name,  # type: ignore[attr-defined]
            args=tc.arguments,  # type: ignore[attr-defined]
            result=result,
            was_confirmed=True,
            was_dry_run=self.engine.dry_run,
        )

    def _should_parallelize(self, tool_calls: list) -> bool:
        """Determina si las tool calls se pueden ejecutar en paralelo.

        Reglas:
        - Si ``parallel_tools=False`` en config → no
        - Si ``confirm-all`` → no (interacción secuencial)
        - Si ``confirm-sensitive`` y alguna tool es sensible → no
        - En cualquier otro caso → sí

        Args:
            tool_calls: Lista de ToolCall a evaluar

        Returns:
            True si se pueden ejecutar en paralelo
        """
        # Respetar configuración explícita de parallel_tools
        if self.context_manager and not self.context_manager.config.parallel_tools:
            return False

        confirm_mode = self.agent_config.confirm_mode

        # confirm-all: siempre secuencial (requiere confirmación interactiva)
        if confirm_mode == "confirm-all":
            return False

        # confirm-sensitive: verificar si alguna tool es sensible
        if confirm_mode == "confirm-sensitive":
            for tc in tool_calls:
                if self.engine.registry.has_tool(tc.name):  # type: ignore[attr-defined]
                    tool = self.engine.registry.get(tc.name)  # type: ignore[attr-defined]
                    if tool.sensitive:
                        return False

        # yolo o confirm-sensitive con tools no sensibles → paralelo
        return True

    def _sanitize_args_for_log(self, args: dict) -> dict:
        """Sanitiza argumentos para logging (truncar valores largos).

        Args:
            args: Argumentos originales

        Returns:
            Argumentos sanitizados
        """
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + f"... ({len(value)} chars)"
            else:
                sanitized[key] = value
        return sanitized
