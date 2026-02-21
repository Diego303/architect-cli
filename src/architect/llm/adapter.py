"""
Adapter para LiteLLM - Abstracción sobre múltiples proveedores LLM.

Proporciona una interfaz unificada para llamar a cualquier LLM soportado
por LiteLLM, con retries automáticos, normalización de respuestas y
manejo robusto de errores.

Incluye soporte para streaming de respuestas en tiempo real.

Retries configurables desde LLMConfig:
- Solo para errores transitorios: RateLimitError, ServiceUnavailableError,
  APIConnectionError y Timeout.
- No se reintenta en errores de autenticación ni de configuración.
- Logging estructurado en cada reintento con número de intento y espera.
"""

import os
from typing import Any, Generator

import litellm
import structlog
from pydantic import BaseModel, Field
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config.schema import LLMConfig
from .cache import LocalLLMCache

logger = structlog.get_logger()

# Errores transitorios que justifican reintentos
_RETRYABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.Timeout,
)


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

    def __init__(self, config: LLMConfig, local_cache: LocalLLMCache | None = None):
        """Inicializa el adapter con configuración.

        Args:
            config: Configuración del LLM
            local_cache: Cache local de respuestas (opcional, solo para desarrollo)
        """
        self.config = config
        self._local_cache = local_cache
        self.log = logger.bind(component="llm_adapter", model=config.model)

        # Configurar LiteLLM
        self._configure_litellm()

        self.log.info(
            "llm.adapter.initialized",
            provider=config.provider,
            mode=config.mode,
            model=config.model,
            retries=config.retries,
            prompt_caching=config.prompt_caching,
            local_cache=local_cache is not None,
        )

    def _on_retry_sleep(self, retry_state: RetryCallState) -> None:
        """Callback llamado antes de cada reintento. Logea el intento y la espera."""
        next_wait = retry_state.next_action.sleep if retry_state.next_action else 0
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        self.log.warning(
            "llm.retry",
            attempt=retry_state.attempt_number,
            wait_seconds=round(next_wait, 1),
            error=str(exc) if exc else None,
            error_type=type(exc).__name__ if exc else None,
        )

    def _call_with_retry(self, fn, *args, **kwargs) -> Any:
        """Ejecuta fn con retries automáticos solo para errores transitorios.

        Usa config.retries para determinar el número máximo de intentos.
        Retries se aplican solo a errores transitorios (_RETRYABLE_ERRORS).
        Errores de autenticación y configuración se propagan inmediatamente.
        """
        max_attempts = self.config.retries + 1  # 1 intento original + N retries
        for attempt in Retrying(
            retry=retry_if_exception_type(_RETRYABLE_ERRORS),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=60),
            before_sleep=self._on_retry_sleep,
            reraise=True,
        ):
            with attempt:
                return fn(*args, **kwargs)

    def _prepare_messages_with_caching(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Marca el system prompt con cache_control para prompt caching del proveedor.

        Añade cache_control al contenido del mensaje system para que
        Anthropic y OpenAI (compatible) lo cacheen automáticamente.
        El markup se ignora en proveedores que no lo soportan.

        Args:
            messages: Lista de mensajes originales

        Returns:
            Lista de mensajes con cache_control en el system (si aplica)
        """
        if not self.config.prompt_caching:
            return messages

        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                # Anthropic requiere content como lista de bloques con cache_control
                if isinstance(content, str):
                    enhanced = {
                        **msg,
                        "content": [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                else:
                    # Ya es lista (p.ej. desde indexer) — añadir cache_control al último bloque
                    enhanced = dict(msg)
                result.append(enhanced)
            else:
                result.append(msg)
        return result

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

    def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Ejecuta una llamada al LLM con retries automáticos para errores transitorios.

        Solo reintenta en errores transitorios (rate limits, servicio no disponible,
        problemas de conexión, timeouts). Los errores de autenticación y de
        configuración se propagan inmediatamente sin reintentar.

        Args:
            messages: Lista de mensajes en formato OpenAI
            tools: Lista de tool schemas (opcional)
            stream: Si True, lanza ValueError — usar completion_stream() en su lugar

        Returns:
            LLMResponse normalizada

        Raises:
            ValueError: Si stream=True (usar completion_stream)
            litellm.RateLimitError: Si se agotan los retries por rate limit
            litellm.AuthenticationError: Inmediatamente (sin retry)
            Exception: Cualquier otro error después de agotar retries
        """
        if stream:
            raise ValueError(
                "Para streaming, use completion_stream() en lugar de completion(stream=True)"
            )

        # Aplicar prompt caching si está habilitado
        messages = self._prepare_messages_with_caching(messages)

        self.log.info(
            "llm.completion.start",
            messages_count=len(messages),
            has_tools=tools is not None,
            tools_count=len(tools) if tools else 0,
        )

        # Consultar local cache (desarrollo)
        if self._local_cache:
            cached = self._local_cache.get(messages, tools)
            if cached is not None:
                return cached

        def _call() -> Any:
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "timeout": self.config.timeout,
                "stream": False,
            }
            if tools:
                kwargs["tools"] = tools
            return litellm.completion(**kwargs)

        try:
            response = self._call_with_retry(_call)
            normalized = self._normalize_response(response)

            # Guardar en local cache si está habilitado
            if self._local_cache:
                self._local_cache.set(messages, tools, normalized)

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
        # Aplicar prompt caching si está habilitado
        messages = self._prepare_messages_with_caching(messages)

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
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(
                            chunk.usage, "completion_tokens", 0
                        ) or 0,
                        "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                        # Tokens servidos desde caché del proveedor (Anthropic: cache_read_input_tokens)
                        "cache_read_input_tokens": (
                            getattr(chunk.usage, "cache_read_input_tokens", 0) or 0
                        ),
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
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
                # Tokens servidos desde caché del proveedor (Anthropic: cache_read_input_tokens)
                "cache_read_input_tokens": (
                    getattr(response.usage, "cache_read_input_tokens", 0) or 0
                ),
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
