"""
Adapter para LiteLLM - Abstracción sobre múltiples proveedores LLM.

Proporciona una interfaz unificada para llamar a cualquier LLM soportado
por LiteLLM, con retries automáticos, normalización de respuestas y
manejo robusto de errores.

Incluye soporte para streaming de respuestas en tiempo real.
"""

import os
from typing import Any, Generator

import litellm
import structlog
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config.schema import LLMConfig

logger = structlog.get_logger()


class StreamChunk(BaseModel):
    """Representa un chunk de streaming del LLM.

    Usado durante streaming para enviar fragmentos de la respuesta
    a medida que se generan.
    """

    type: str = Field(description="Tipo de chunk: 'content' o 'tool_call'")
    data: str = Field(description="Contenido del chunk")

    model_config = {"extra": "forbid"}


class ToolCall(BaseModel):
    """Representa un tool call solicitado por el LLM.

    Formato normalizado independiente del proveedor.
    """

    id: str = Field(description="ID único del tool call")
    name: str = Field(description="Nombre de la tool a ejecutar")
    arguments: dict[str, Any] = Field(description="Argumentos para la tool")

    model_config = {"extra": "forbid"}


class LLMResponse(BaseModel):
    """Respuesta normalizada del LLM.

    Formato interno independiente del proveedor LLM usado.
    """

    content: str | None = Field(
        default=None,
        description="Texto de respuesta del LLM (si no hay tool calls)",
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="Tool calls solicitadas por el LLM",
    )
    finish_reason: str = Field(
        default="stop",
        description="Razón de finalización: stop, tool_calls, length, etc.",
    )
    usage: dict[str, Any] | None = Field(
        default=None,
        description="Información de uso de tokens",
    )

    model_config = {"extra": "forbid"}


class LLMAdapter:
    """Adapter para LiteLLM con configuración, retries y normalización.

    Proporciona una interfaz limpia sobre LiteLLM que:
    - Configura el provider (directo o proxy)
    - Maneja API keys desde variables de entorno
    - Aplica retries automáticos con backoff exponencial
    - Normaliza respuestas a un formato interno consistente
    - Maneja errores con logging estructurado
    """

    def __init__(self, config: LLMConfig):
        """Inicializa el adapter con configuración.

        Args:
            config: Configuración del LLM
        """
        self.config = config
        self.log = logger.bind(component="llm_adapter", model=config.model)

        # Configurar LiteLLM
        self._configure_litellm()

        self.log.info(
            "llm.adapter.initialized",
            provider=config.provider,
            mode=config.mode,
            model=config.model,
        )

    def _configure_litellm(self) -> None:
        """Configura LiteLLM según la configuración."""

        # Configurar API base si está especificada
        if self.config.api_base:
            litellm.api_base = self.config.api_base
            self.log.debug("llm.api_base_set", api_base=self.config.api_base)

        # Configurar API key desde variable de entorno
        api_key = os.environ.get(self.config.api_key_env)
        if api_key:
            # LiteLLM usa diferentes env vars según el provider
            # Setear la genérica y las específicas
            os.environ["LITELLM_API_KEY"] = api_key
            self.log.debug("llm.api_key_configured", env_var=self.config.api_key_env)
        else:
            self.log.warning(
                "llm.no_api_key",
                env_var=self.config.api_key_env,
                message=f"Variable de entorno {self.config.api_key_env} no encontrada",
            )

        # Configurar modo de logging de LiteLLM (reducir verbosidad)
        litellm.suppress_debug_info = True
        litellm.set_verbose = False

    @retry(
        retry=retry_if_exception_type((Exception,)),  # Retry on any exception
        stop=stop_after_attempt(3),  # Max 3 intentos (1 original + 2 retries)
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Ejecuta una llamada al LLM con retries automáticos.

        Args:
            messages: Lista de mensajes en formato OpenAI
            tools: Lista de tool schemas (opcional)
            stream: Si True, retorna None y debe usar completion_stream()

        Returns:
            LLMResponse normalizada (si stream=False)
            None (si stream=True, usar completion_stream())

        Raises:
            Exception: Si falla después de todos los retries
        """
        # Si stream=True, caller debe usar completion_stream() directamente
        if stream:
            raise ValueError(
                "Para streaming, use completion_stream() en lugar de completion(stream=True)"
            )

        self.log.info(
            "llm.completion.start",
            messages_count=len(messages),
            has_tools=tools is not None,
            tools_count=len(tools) if tools else 0,
        )

        try:
            # Preparar kwargs para LiteLLM
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "timeout": self.config.timeout,
                "stream": False,
            }

            # Añadir tools si están disponibles
            if tools:
                kwargs["tools"] = tools
                # tool_choice="auto" es el default, LiteLLM lo maneja

            # Llamar a LiteLLM (sin streaming)
            response = litellm.completion(**kwargs)

            # Normalizar respuesta
            normalized = self._normalize_response(response)

            self.log.info(
                "llm.completion.success",
                finish_reason=normalized.finish_reason,
                has_content=normalized.content is not None,
                tool_calls_count=len(normalized.tool_calls),
                usage=normalized.usage,
            )

            return normalized

        except Exception as e:
            self.log.error(
                "llm.completion.error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    def completion_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[StreamChunk | LLMResponse, None, None]:
        """Ejecuta una llamada al LLM con streaming.

        Yields chunks a medida que se generan, y al final retorna
        la respuesta completa.

        Args:
            messages: Lista de mensajes en formato OpenAI
            tools: Lista de tool schemas (opcional)

        Yields:
            StreamChunk: Fragmentos de contenido a medida que se generan
            LLMResponse: Respuesta completa al final (último yield)

        Raises:
            Exception: Si falla la llamada al LLM
        """
        self.log.info(
            "llm.completion_stream.start",
            messages_count=len(messages),
            has_tools=tools is not None,
            tools_count=len(tools) if tools else 0,
        )

        try:
            # Preparar kwargs para LiteLLM
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "timeout": self.config.timeout,
                "stream": True,
            }

            # Añadir tools si están disponibles
            if tools:
                kwargs["tools"] = tools

            # Acumuladores para construir respuesta completa
            collected_content: list[str] = []
            collected_tool_calls: dict[int, dict[str, Any]] = {}
            finish_reason = "stop"
            usage_info = None

            # Streaming
            for chunk in litellm.completion(**kwargs):
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = choice.delta

                # Contenido de texto
                if hasattr(delta, "content") and delta.content:
                    collected_content.append(delta.content)
                    yield StreamChunk(type="content", data=delta.content)

                # Tool calls (se acumulan incrementalmente)
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {
                                "id": getattr(tc_delta, "id", ""),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }

                        # Acumular campos
                        if tc_delta.id:
                            collected_tool_calls[idx]["id"] = tc_delta.id

                        if hasattr(tc_delta, "function"):
                            if tc_delta.function.name:
                                collected_tool_calls[idx]["function"]["name"] = (
                                    tc_delta.function.name
                                )
                            if tc_delta.function.arguments:
                                collected_tool_calls[idx]["function"]["arguments"] += (
                                    tc_delta.function.arguments
                                )

                # Finish reason
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                # Usage (solo viene en el último chunk)
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_info = {
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(
                            chunk.usage, "completion_tokens", 0
                        ),
                        "total_tokens": getattr(chunk.usage, "total_tokens", 0),
                    }

            # Construir respuesta completa
            content = "".join(collected_content) if collected_content else None

            # Convertir tool calls acumulados a ToolCall objects
            tool_calls = []
            for tc_dict in collected_tool_calls.values():
                tool_calls.append(
                    ToolCall(
                        id=tc_dict["id"],
                        name=tc_dict["function"]["name"],
                        arguments=self._parse_arguments(
                            tc_dict["function"]["arguments"]
                        ),
                    )
                )

            response = LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage_info,
            )

            self.log.info(
                "llm.completion_stream.complete",
                finish_reason=response.finish_reason,
                has_content=response.content is not None,
                tool_calls_count=len(response.tool_calls),
                usage=response.usage,
            )

            # Yield respuesta completa al final
            yield response

        except Exception as e:
            self.log.error(
                "llm.completion_stream.error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    def _normalize_response(self, response: Any) -> LLMResponse:
        """Normaliza la respuesta de LiteLLM a formato interno.

        Args:
            response: Respuesta cruda de litellm.completion()

        Returns:
            LLMResponse normalizada
        """
        # LiteLLM retorna un objeto ModelResponse
        choice = response.choices[0]
        message = choice.message

        # Extraer content
        content = getattr(message, "content", None)

        # Extraer tool calls si existen
        tool_calls_raw = getattr(message, "tool_calls", None) or []
        tool_calls = []

        for tc in tool_calls_raw:
            # LiteLLM normaliza tool calls al formato OpenAI
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=self._parse_arguments(tc.function.arguments),
                )
            )

        # Extraer finish_reason
        finish_reason = choice.finish_reason or "stop"

        # Extraer usage si está disponible
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def _parse_arguments(self, arguments: Any) -> dict[str, Any]:
        """Parsea los argumentos de un tool call.

        LiteLLM puede retornar arguments como string JSON o dict.

        Args:
            arguments: Arguments en formato string o dict

        Returns:
            Dict con argumentos parseados
        """
        if isinstance(arguments, dict):
            return arguments

        if isinstance(arguments, str):
            import json

            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                self.log.warning(
                    "llm.arguments_parse_error",
                    arguments=arguments,
                )
                return {}

        return {}

    def __repr__(self) -> str:
        return f"<LLMAdapter(model='{self.config.model}', provider='{self.config.provider}')>"
