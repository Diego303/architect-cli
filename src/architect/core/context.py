"""
Context Builder - Construcción de mensajes para el LLM.

Gestiona la construcción de la lista de mensajes en formato OpenAI
que se envía al LLM, incluyendo system prompts, user prompts y
tool results.
"""

from typing import Any

from ..config.schema import AgentConfig
from ..llm.adapter import ToolCall
from .state import ToolCallResult


class ContextBuilder:
    """Constructor de contexto para el LLM.

    Gestiona la construcción y actualización de la lista de mensajes
    que se envía al LLM en cada step.
    """

    def build_initial(self, agent_config: AgentConfig, prompt: str) -> list[dict[str, Any]]:
        """Construye los mensajes iniciales para el LLM.

        Args:
            agent_config: Configuración del agente
            prompt: Prompt del usuario

        Returns:
            Lista de mensajes en formato OpenAI
        """
        messages = [
            {"role": "system", "content": agent_config.system_prompt},
            {"role": "user", "content": prompt},
        ]

        return messages

    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[ToolCall],
        results: list[ToolCallResult],
    ) -> list[dict[str, Any]]:
        """Añade tool results a la lista de mensajes.

        Formato OpenAI para tool calling:
        1. Assistant message con tool_calls
        2. Tool messages con los resultados

        Args:
            messages: Lista de mensajes existente
            tool_calls: Tool calls solicitadas por el LLM
            results: Resultados de ejecutar las tool calls

        Returns:
            Nueva lista de mensajes con tool results añadidos
        """
        # Crear una copia para no mutar el original
        new_messages = messages.copy()

        # 1. Añadir assistant message con tool_calls
        # Formato OpenAI: assistant message debe incluir tool_calls
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": None,  # No hay contenido cuando hay tool calls
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": self._serialize_arguments(tc.arguments),
                    },
                }
                for tc in tool_calls
            ],
        }
        new_messages.append(assistant_message)

        # 2. Añadir tool messages con los resultados
        for tc, result in zip(tool_calls, results):
            tool_message = self._format_tool_result(tc, result)
            new_messages.append(tool_message)

        return new_messages

    def _format_tool_result(
        self,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> dict[str, Any]:
        """Formatea el resultado de una tool para el LLM.

        Args:
            tool_call: Tool call original del LLM
            result: Resultado de ejecutar la tool

        Returns:
            Message en formato OpenAI tool result
        """
        # Construir contenido del resultado
        if result.was_dry_run:
            content = f"[DRY-RUN] {result.result.output}"
        elif result.result.success:
            content = result.result.output
        else:
            # Si la tool falló, incluir el error
            content = f"Error: {result.result.error}"

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.name,
            "content": content,
        }

    def _serialize_arguments(self, arguments: dict[str, Any]) -> str:
        """Serializa argumentos de tool call a JSON string.

        Args:
            arguments: Dict con argumentos

        Returns:
            JSON string
        """
        import json

        return json.dumps(arguments)

    def append_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Añade un mensaje del assistant (respuesta final).

        Args:
            messages: Lista de mensajes existente
            content: Contenido del mensaje

        Returns:
            Nueva lista de mensajes
        """
        new_messages = messages.copy()
        new_messages.append({"role": "assistant", "content": content})
        return new_messages

    def append_user_message(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Añade un mensaje del usuario.

        Args:
            messages: Lista de mensajes existente
            content: Contenido del mensaje

        Returns:
            Nueva lista de mensajes
        """
        new_messages = messages.copy()
        new_messages.append({"role": "user", "content": content})
        return new_messages
