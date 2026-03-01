"""
Adapter for LiteLLM - Abstraction over multiple LLM providers.

Provides a unified interface for calling any LLM supported
by LiteLLM, with automatic retries, response normalization, and
robust error handling.

Includes support for real-time response streaming.

Retries configurable from LLMConfig:
- Only for transient errors: RateLimitError, ServiceUnavailableError,
  APIConnectionError and Timeout.
- Authentication and configuration errors are not retried.
- Structured logging on each retry with attempt number and wait time.
"""

import json
import os
import uuid
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

# Transient errors that justify retries
_RETRYABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.Timeout,
)


class StreamChunk(BaseModel):
    """Represents a streaming chunk from the LLM.

    Used during streaming to send response fragments
    as they are generated.
    """

    type: str = Field(description="Chunk type: 'content' or 'tool_call'")
    data: str = Field(description="Chunk content")

    model_config = {"extra": "forbid"}


class ToolCall(BaseModel):
    """Represents a tool call requested by the LLM.

    Normalized format independent of the provider.
    """

    id: str = Field(description="Unique ID of the tool call")
    name: str = Field(description="Name of the tool to execute")
    arguments: dict[str, Any] = Field(description="Arguments for the tool")

    model_config = {"extra": "forbid"}


class LLMResponse(BaseModel):
    """Normalized LLM response.

    Internal format independent of the LLM provider used.
    """

    content: str | None = Field(
        default=None,
        description="LLM response text (if there are no tool calls)",
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="Tool calls requested by the LLM",
    )
    finish_reason: str = Field(
        default="stop",
        description="Finish reason: stop, tool_calls, length, etc.",
    )
    usage: dict[str, Any] | None = Field(
        default=None,
        description="Token usage information",
    )

    model_config = {"extra": "forbid"}


class LLMAdapter:
    """Adapter for LiteLLM with configuration, retries and normalization.

    Provides a clean interface over LiteLLM that:
    - Configures the provider (direct or proxy)
    - Handles API keys from environment variables
    - Applies automatic retries with exponential backoff
    - Normalizes responses to a consistent internal format
    - Handles errors with structured logging
    """

    def __init__(self, config: LLMConfig, local_cache: LocalLLMCache | None = None):
        """Initialize the adapter with configuration.

        Args:
            config: LLM configuration
            local_cache: Local response cache (optional, for development only)
        """
        self.config = config
        self._local_cache = local_cache
        self.log = logger.bind(component="llm_adapter", model=config.model)

        # Configure LiteLLM
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
        """Callback called before each retry. Logs the attempt and wait time."""
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
        """Execute fn with automatic retries only for transient errors.

        Uses config.retries to determine the maximum number of attempts.
        Retries are applied only to transient errors (_RETRYABLE_ERRORS).
        Authentication and configuration errors are propagated immediately.
        """
        max_attempts = self.config.retries + 1  # 1 original attempt + N retries
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
        """Mark the system prompt with cache_control for provider prompt caching.

        Adds cache_control to the system message content so that
        Anthropic and OpenAI (compatible) cache it automatically.
        The markup is ignored by providers that don't support it.

        Args:
            messages: Original list of messages

        Returns:
            List of messages with cache_control on the system (if applicable)
        """
        if not self.config.prompt_caching:
            return messages

        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                # Anthropic requires content as a list of blocks with cache_control
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
                    # Already a list (e.g. from indexer) — add cache_control to the last block
                    enhanced = dict(msg)
                result.append(enhanced)
            else:
                result.append(msg)
        return result

    def _configure_litellm(self) -> None:
        """Configure LiteLLM according to the configuration."""

        # Configure API base if specified
        if self.config.api_base:
            litellm.api_base = self.config.api_base
            self.log.debug("llm.api_base_set", api_base=self.config.api_base)

        # Configure API key from environment variable
        api_key = os.environ.get(self.config.api_key_env)
        if api_key:
            # LiteLLM uses different env vars depending on the provider
            # Set the generic and specific ones
            os.environ["LITELLM_API_KEY"] = api_key
            self.log.debug("llm.api_key_configured", env_var=self.config.api_key_env)
        else:
            self.log.warning(
                "llm.no_api_key",
                env_var=self.config.api_key_env,
                message=f"Environment variable {self.config.api_key_env} not found",
            )

        # Configure LiteLLM logging mode (reduce verbosity)
        litellm.suppress_debug_info = True
        litellm.set_verbose = False

    def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Execute an LLM call with automatic retries for transient errors.

        Only retries on transient errors (rate limits, service unavailable,
        connection problems, timeouts). Authentication and configuration
        errors are propagated immediately without retrying.

        Args:
            messages: List of messages in OpenAI format
            tools: List of tool schemas (optional)
            stream: If True, raises ValueError -- use completion_stream() instead

        Returns:
            Normalized LLMResponse

        Raises:
            ValueError: If stream=True (use completion_stream)
            litellm.RateLimitError: If retries for rate limit are exhausted
            litellm.AuthenticationError: Immediately (no retry)
            Exception: Any other error after exhausting retries
        """
        if stream:
            raise ValueError(
                "For streaming, use completion_stream() instead of completion(stream=True)"
            )

        # Apply prompt caching if enabled
        messages = self._prepare_messages_with_caching(messages)

        self.log.info(
            "llm.completion.start",
            messages_count=len(messages),
            has_tools=tools is not None,
            tools_count=len(tools) if tools else 0,
        )

        # Query local cache (development)
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

            # Save to local cache if enabled
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
        """Execute an LLM call with streaming.

        Yields chunks as they are generated, and returns
        the complete response at the end.

        Args:
            messages: List of messages in OpenAI format
            tools: List of tool schemas (optional)

        Yields:
            StreamChunk: Content fragments as they are generated
            LLMResponse: Complete response at the end (last yield)

        Raises:
            Exception: If the LLM call fails
        """
        # Apply prompt caching if enabled
        messages = self._prepare_messages_with_caching(messages)

        self.log.info(
            "llm.completion_stream.start",
            messages_count=len(messages),
            has_tools=tools is not None,
            tools_count=len(tools) if tools else 0,
        )

        try:
            # Prepare kwargs for LiteLLM
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "timeout": self.config.timeout,
                "stream": True,
                # Request usage in streaming (OpenAI-compatible APIs)
                # Without this, usage is not returned and the cost tracker does not record data
                "stream_options": {"include_usage": True},
            }

            # Add tools if available
            if tools:
                kwargs["tools"] = tools

            # Accumulators for building the complete response
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

                # Text content
                if hasattr(delta, "content") and delta.content:
                    collected_content.append(delta.content)
                    yield StreamChunk(type="content", data=delta.content)

                # Tool calls (accumulated incrementally)
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {
                                "id": getattr(tc_delta, "id", ""),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }

                        # Accumulate fields
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

                # Usage (only comes in the last chunk)
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_info = {
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(
                            chunk.usage, "completion_tokens", 0
                        ) or 0,
                        "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                        # Tokens served from provider cache (Anthropic: cache_read_input_tokens)
                        "cache_read_input_tokens": (
                            getattr(chunk.usage, "cache_read_input_tokens", 0) or 0
                        ),
                    }

            # Build complete response
            content = "".join(collected_content) if collected_content else None

            # Convert accumulated tool calls to ToolCall objects
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

            # Fallback: if the provider did not return usage in streaming,
            # estimate tokens using litellm.token_counter so that the
            # cost tracker can record approximate data.
            if usage_info is None or (
                usage_info.get("prompt_tokens", 0) == 0
                and usage_info.get("completion_tokens", 0) == 0
            ):
                usage_info = self._estimate_streaming_usage(
                    messages, content, collected_tool_calls
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

            # Yield complete response at the end
            yield response

        except Exception as e:
            self.log.error(
                "llm.completion_stream.error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    def _normalize_response(self, response: Any) -> LLMResponse:
        """Normalize the LiteLLM response to internal format.

        Args:
            response: Raw response from litellm.completion()

        Returns:
            Normalized LLMResponse
        """
        # LiteLLM returns a ModelResponse object
        choice = response.choices[0]
        message = choice.message

        # Extract content
        content = getattr(message, "content", None)

        # Extract tool calls if they exist
        tool_calls_raw = getattr(message, "tool_calls", None) or []
        tool_calls = []

        for tc in tool_calls_raw:
            # LiteLLM normalizes tool calls to OpenAI format
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=self._parse_arguments(tc.function.arguments),
                )
            )

        # Fallback: some models (llama3.1, mistral via ollama) return tool calls
        # as JSON in the content field instead of using the OpenAI tool_calls field.
        if not tool_calls and content:
            text_tool_calls = self._try_parse_text_tool_calls(content)
            if text_tool_calls:
                self.log.debug(
                    "llm.text_tool_calls_detected",
                    count=len(text_tool_calls),
                    tools=[tc.name for tc in text_tool_calls],
                )
                tool_calls = text_tool_calls
                content = None  # The content was just the tool call, not text to the user

        # Extract finish_reason
        finish_reason = choice.finish_reason or "stop"

        # Extract usage if available
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
                # Tokens served from provider cache (Anthropic: cache_read_input_tokens)
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

    def _try_parse_text_tool_calls(self, content: str) -> list[ToolCall]:
        """Attempt to parse tool calls embedded as text in the content.

        Some models (llama3.1, mistral via ollama) don't use the tool_calls field
        of the OpenAI API and return the call as JSON in the content field.

        Detected formats:
          {"name": "tool", "arguments": {...}}
          {"type": "function", "name": "tool", "parameters": {...}}
          [{"name": "tool1", ...}, {"name": "tool2", ...}]

        Only activates if the JSON has 'name' (str) + 'arguments'/'parameters'/'args'.
        """
        text = content.strip()

        # Remove markdown code blocks if present
        if text.startswith("```"):
            lines = text.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            text = "\n".join(inner).strip()

        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []

        def _to_tool_call(d: dict) -> ToolCall | None:
            # Native nested OpenAI format:
            # {"id": "...", "type": "function", "function": {"name": "...", "arguments": {...}}}
            if "function" in d and isinstance(d["function"], dict):
                fn = d["function"]
                name = fn.get("name")
                if name and isinstance(name, str):
                    raw_args = fn.get("arguments") or fn.get("parameters") or {}
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except (json.JSONDecodeError, ValueError):
                            raw_args = {}
                    tc_id = d.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                    return ToolCall(id=tc_id, name=name, arguments=raw_args or {})

            # Flat format: {"name": "tool", "arguments": {...}}
            # or {"type": "function", "name": "tool", "parameters": {...}}
            name = d.get("name") or d.get("tool_name")
            if not name or not isinstance(name, str):
                return None
            # Must have an explicit arguments field to distinguish from normal JSON
            if not any(k in d for k in ("arguments", "parameters", "args")):
                return None
            raw_args = d.get("arguments") or d.get("parameters") or d.get("args") or {}
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except (json.JSONDecodeError, ValueError):
                    raw_args = {}
            if not isinstance(raw_args, dict):
                raw_args = {}
            return ToolCall(
                id=d.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=name,
                arguments=raw_args,
            )

        if isinstance(parsed, dict):
            tc = _to_tool_call(parsed)
            return [tc] if tc else []

        if isinstance(parsed, list):
            result = []
            for item in parsed:
                if isinstance(item, dict):
                    tc = _to_tool_call(item)
                    if tc:
                        result.append(tc)
            return result

        return []

    def _estimate_streaming_usage(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls_raw: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        """Estimate usage when the provider does not return it in streaming.

        Uses litellm.token_counter to count input message tokens
        and estimates output tokens from the generated content (~4 chars/token).

        Args:
            messages: Messages sent to the LLM (input)
            content: Generated text content (output)
            tool_calls_raw: Tool calls accumulated in streaming

        Returns:
            Dict with estimates for prompt_tokens and completion_tokens
        """
        try:
            prompt_tokens = litellm.token_counter(
                model=self.config.model,
                messages=messages,
            )
        except Exception:
            # Fallback: estimate ~4 chars/token
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages
            )
            prompt_tokens = total_chars // 4

        # Estimate output tokens
        output_text = content or ""
        for tc_dict in tool_calls_raw.values():
            output_text += tc_dict.get("function", {}).get("name", "")
            output_text += tc_dict.get("function", {}).get("arguments", "")
        completion_tokens = max(1, len(output_text) // 4)

        self.log.debug(
            "llm.streaming_usage_estimated",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cache_read_input_tokens": 0,
        }

    def _parse_arguments(self, arguments: Any) -> dict[str, Any]:
        """Parse the arguments of a tool call.

        LiteLLM can return arguments as a JSON string or dict.

        Args:
            arguments: Arguments in string or dict format.

        Returns:
            Dict with parsed arguments.
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
