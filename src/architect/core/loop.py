"""
Agent Loop - Ciclo principal de ejecución del agente.

Este es el corazón del sistema. Orquesta la interacción entre
el LLM y las tools, gestionando el flujo completo de ejecución.
"""

import sys
from typing import Callable

import structlog

from ..config.schema import AgentConfig
from ..execution.engine import ExecutionEngine
from ..llm.adapter import LLMAdapter, StreamChunk
from .context import ContextBuilder
from .state import AgentState, StepResult, ToolCallResult

logger = structlog.get_logger()


class AgentLoop:
    """Loop principal del agente.

    Orquesta el ciclo completo:
    1. Enviar mensajes al LLM
    2. Recibir respuesta (texto o tool calls)
    3. Ejecutar tool calls si las hay
    4. Enviar resultados de vuelta al LLM
    5. Repetir hasta que el agente termine o se alcance max_steps
    """

    def __init__(
        self,
        llm: LLMAdapter,
        engine: ExecutionEngine,
        agent_config: AgentConfig,
        context_builder: ContextBuilder,
    ):
        """Inicializa el agent loop.

        Args:
            llm: LLMAdapter configurado
            engine: ExecutionEngine configurado
            agent_config: Configuración del agente
            context_builder: ContextBuilder para mensajes
        """
        self.llm = llm
        self.engine = engine
        self.agent_config = agent_config
        self.ctx = context_builder
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
            self.log.info("agent.step.start", step=step)

            # 1. Llamar al LLM (con o sin streaming)
            try:
                if stream:
                    # Modo streaming
                    response = None
                    for chunk_or_response in self.llm.completion_stream(
                        messages=state.messages,
                        tools=tools_schema if tools_schema else None,
                    ):
                        # El último yield es la respuesta completa
                        if isinstance(chunk_or_response, StreamChunk):
                            # Es un chunk de streaming
                            if on_stream_chunk and chunk_or_response.type == "content":
                                on_stream_chunk(chunk_or_response.data)
                        else:
                            # Es la respuesta completa (último yield)
                            response = chunk_or_response

                    # Verificar que obtuvimos respuesta
                    if response is None:
                        raise RuntimeError("Streaming completó sin retornar respuesta final")
                else:
                    # Modo sin streaming (normal)
                    response = self.llm.completion(
                        messages=state.messages,
                        tools=tools_schema if tools_schema else None,
                    )
            except Exception as e:
                self.log.error("agent.llm_error", error=str(e), step=step)
                state.status = "failed"
                state.final_output = f"Error al comunicarse con el LLM: {e}"
                break

            # 2. Verificar si el LLM terminó con una respuesta final
            if response.finish_reason == "stop" and not response.tool_calls:
                # El agente ha terminado con éxito
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

                tool_results = []
                for tc in response.tool_calls:
                    self.log.info(
                        "agent.tool_call.execute",
                        step=step,
                        tool=tc.name,
                        args=self._sanitize_args_for_log(tc.arguments),
                    )

                    # Ejecutar tool
                    result = self.engine.execute_tool_call(tc.name, tc.arguments)

                    # Registrar resultado
                    tool_result = ToolCallResult(
                        tool_name=tc.name,
                        args=tc.arguments,
                        result=result,
                        was_confirmed=True,  # TODO: track real confirmation status
                        was_dry_run=self.engine.dry_run,
                    )
                    tool_results.append(tool_result)

                    self.log.info(
                        "agent.tool_call.complete",
                        step=step,
                        tool=tc.name,
                        success=result.success,
                        error=result.error if not result.success else None,
                    )

                # 4. Actualizar mensajes con tool results
                state.messages = self.ctx.append_tool_results(
                    state.messages, response.tool_calls, tool_results
                )

                # 5. Registrar step
                step_result = StepResult(
                    step_number=step,
                    llm_response=response,
                    tool_calls_made=tool_results,
                )
                state.steps.append(step_result)

            else:
                # El LLM respondió pero sin tool calls y sin finalizar correctamente
                # Esto puede pasar si el finish_reason es "length" u otro
                self.log.warning(
                    "agent.unexpected_response",
                    step=step,
                    finish_reason=response.finish_reason,
                    has_content=response.content is not None,
                )

                # Registrar step sin tool calls
                step_result = StepResult(
                    step_number=step,
                    llm_response=response,
                    tool_calls_made=[],
                )
                state.steps.append(step_result)

                # Decidir si continuar o terminar
                if response.finish_reason == "length":
                    # Token limit alcanzado, intentar continuar
                    self.log.info("agent.token_limit", step=step)
                    continue
                else:
                    # Otro finish_reason inesperado, terminar
                    state.status = "partial"
                    state.final_output = response.content or "El agente no produjo una respuesta clara."
                    break

        else:
            # Se agotaron los pasos sin terminar
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
