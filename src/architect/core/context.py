"""
Context Builder and Context Manager - LLM context construction and management.

ContextBuilder: Builds the OpenAI message list (system, user, tool results).
ContextManager: Manages the context window to prevent overflow in long tasks.

F10: Repository index injection into the system prompt.
F11: ContextManager with 3 pruning levels (truncation, summarization, sliding window).
"""

from __future__ import annotations

import structlog
from typing import TYPE_CHECKING, Any

from ..config.schema import AgentConfig, ContextConfig
from ..llm.adapter import LLMAdapter, ToolCall
from .state import ToolCallResult

if TYPE_CHECKING:
    from ..indexer.tree import RepoIndex

logger = structlog.get_logger()


class ContextManager:
    """Context window manager to prevent overflow in long tasks.

    Operates at three progressive levels (F11):
    - Level 1: ``truncate_tool_result`` — truncates individual tool results.
    - Level 2: ``maybe_compress``       — summarizes old steps using the LLM.
    - Level 3: ``enforce_window``       — hard limit on total tokens.

    Level 1 is applied in ``ContextBuilder._format_tool_result()``.
    Levels 2 and 3 are applied in the loop after each step.
    """

    def __init__(self, config: ContextConfig) -> None:
        self.config = config
        self.log = logger.bind(component="context_manager")

    # ── Level 1: Tool result truncation ──────────────────────────────────

    def truncate_tool_result(self, content: str) -> str:
        """Truncate a tool result if it exceeds the configured limit.

        Preserves the first 40 lines and the last 20 to keep
        the beginning (important for structures) and the end (usually has
        summaries and errors).

        Args:
            content: Tool result content

        Returns:
            Truncated content with omission marker, or the original if it fits
        """
        if self.config.max_tool_result_tokens == 0:
            return content

        max_chars = self.config.max_tool_result_tokens * 4  # ~4 chars/token
        if len(content) <= max_chars:
            return content

        lines = content.splitlines()
        head_lines = 40
        tail_lines = 20

        if len(lines) <= head_lines + tail_lines:
            # Content is long but has few lines (very long lines)
            # Truncate by characters preserving proportion
            head = content[:max_chars // 2]
            tail = content[-(max_chars // 4):]
            omitted_chars = len(content) - len(head) - len(tail)
            from ..i18n import t
            marker = t("context.chars_omitted", n=omitted_chars)
            return f"{head}\n\n{marker}\n\n{tail}"

        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])
        omitted = len(lines) - head_lines - tail_lines
        from ..i18n import t
        marker = t("context.lines_omitted", n=omitted)
        return f"{head}\n\n{marker}\n\n{tail}"

    # ── Level 2: Old step summarization ─────────────────────────────────

    def maybe_compress(
        self, messages: list[dict[str, Any]], llm: LLMAdapter
    ) -> list[dict[str, Any]]:
        """Compress old messages into a summary if there are too many steps.

        Activates when the number of exchanges (steps with tool calls)
        exceeds ``summarize_after_steps``. The last ``keep_recent_steps``
        exchanges are kept intact; the rest is summarized with the LLM.

        If compression fails (LLM error, network, etc.), returns the
        original messages unmodified.

        Args:
            messages: Current agent message list
            llm: LLMAdapter to generate the summary

        Returns:
            Message list (possibly compressed)
        """
        if self.config.summarize_after_steps == 0:
            return messages

        tool_exchanges = self._count_tool_exchanges(messages)
        if tool_exchanges <= self.config.summarize_after_steps:
            return messages

        # Separate: system + user | dialog messages
        if len(messages) < 4:  # system + user + at least 1 exchange
            return messages

        system_msg = messages[0]
        user_msg = messages[1]
        dialog_msgs = messages[2:]

        # Keep the last keep_recent_steps*3 messages intact
        keep_count = self.config.keep_recent_steps * 3
        if len(dialog_msgs) <= keep_count:
            return messages  # Not enough to compress

        old_msgs = dialog_msgs[:-keep_count]
        recent_msgs = dialog_msgs[-keep_count:]

        self.log.info(
            "context.compressing",
            tool_exchanges=tool_exchanges,
            old_messages=len(old_msgs),
            kept_messages=len(recent_msgs),
        )

        # Summarize old messages with the LLM
        try:
            summary = self._summarize_steps(old_msgs, llm)
        except Exception as e:
            self.log.warning("context.compress_failed", error=str(e))
            return messages  # Graceful degradation: no compression

        from ..i18n import t
        summary_msg: dict[str, Any] = {
            "role": "assistant",
            "content": f"{t('context.summary_header')}\n{summary}",
        }

        compressed = [system_msg, user_msg, summary_msg, *recent_msgs]
        self.log.info(
            "context.compressed",
            original_messages=len(messages),
            compressed_messages=len(compressed),
        )
        return compressed

    def _summarize_steps(
        self, messages: list[dict[str, Any]], llm: LLMAdapter
    ) -> str:
        """Use the LLM to summarize a sequence of messages.

        If the LLM call fails, generates a mechanical summary as fallback
        (list of tools executed and files involved).

        Args:
            messages: Dialog messages to summarize
            llm: LLMAdapter for the summary call

        Returns:
            Summary text (~200 words)
        """
        formatted = self._format_steps_for_summary(messages)

        from ..i18n import t
        try:
            summary_prompt = [
                {
                    "role": "system",
                    "content": t("context.summary_prompt", content=formatted),
                },
            ]
            response = llm.completion(summary_prompt, tools=None)
            return response.content or formatted
        except Exception as e:
            self.log.warning("context.summarize_llm_failed", error=str(e))
            return t("context.mechanical_summary", content=formatted)

    def _format_steps_for_summary(self, messages: list[dict[str, Any]]) -> str:
        """Convert messages to readable text for summarization."""
        from ..i18n import t
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            if role == "assistant":
                if msg.get("tool_calls"):
                    tool_names = [
                        tc["function"]["name"]
                        for tc in msg["tool_calls"]
                        if isinstance(tc, dict) and "function" in tc
                    ]
                    parts.append(t("context.agent_called_tools", tools=", ".join(tool_names)))
                elif msg.get("content"):
                    content = str(msg["content"])[:300]
                    parts.append(t("context.agent_responded", content=content))
            elif role == "tool":
                name = msg.get("name", "unknown")
                content = str(msg.get("content") or "")[:300]
                parts.append(t("context.tool_result", name=name, content=content))
        return "\n".join(parts) or t("context.no_messages")

    def _count_tool_exchanges(self, messages: list[dict[str, Any]]) -> int:
        """Count the number of steps with tool calls."""
        return sum(
            1
            for m in messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        )

    # ── Unified pipeline (v3-M2) ─────────────────────────────────────────

    def manage(
        self, messages: list[dict[str, Any]], llm: LLMAdapter | None = None
    ) -> list[dict[str, Any]]:
        """Unified context management pipeline.

        Called before each LLM call. Applies in order:
        1. Compress old steps (Level 2) if context exceeds 75%
        2. Hard token limit (Level 3)

        Level 1 (tool result truncation) is applied in ContextBuilder
        when adding each tool result, not in this pipeline.

        Args:
            messages: Current message list
            llm: LLMAdapter for generating summaries (can be None)

        Returns:
            Managed message list (possibly compressed or truncated)
        """
        # Only compress if context exceeds 75% of maximum
        if llm and self._is_above_threshold(messages, 0.75):
            messages = self.maybe_compress(messages, llm)
        messages = self.enforce_window(messages)
        return messages

    def _is_above_threshold(
        self, messages: list[dict[str, Any]], threshold: float
    ) -> bool:
        """True if the estimated context exceeds the given percentage of maximum.

        Args:
            messages: Message list
            threshold: Fraction of maximum (e.g.: 0.75 = 75%)

        Returns:
            True if exceeds threshold, or True if max_context_tokens == 0
            (no limit configured -> rely on summarize_after_steps)
        """
        if self.config.max_context_tokens == 0:
            return True  # No token limit -> rely on summarize_after_steps
        limit = int(self.config.max_context_tokens * threshold)
        return self._estimate_tokens(messages) > limit

    def is_critically_full(self, messages: list[dict[str, Any]]) -> bool:
        """True if the context is at 95%+ of maximum even after compression.

        Used as a safety net in the loop: if it returns True, the agent
        must close even if it hasn't finished.

        Args:
            messages: Current message list

        Returns:
            True if the context is critically full
        """
        if self.config.max_context_tokens == 0:
            return False
        limit_95 = int(self.config.max_context_tokens * 0.95)
        return self._estimate_tokens(messages) > limit_95

    # ── Level 3: Sliding window (hard limit) ───────────────────────────

    def enforce_window(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Apply a hard token limit to the context window.

        If the estimated total exceeds ``max_context_tokens``, removes pairs of
        old dialog messages (2 at a time, starting from the oldest)
        until it fits, always keeping system and user messages.

        Args:
            messages: Message list

        Returns:
            Trimmed list if needed, or the original
        """
        if self.config.max_context_tokens == 0:
            return messages

        if self._estimate_tokens(messages) <= self.config.max_context_tokens:
            return messages

        system_msg = messages[0]
        user_msg = messages[1]
        dialog = list(messages[2:])
        removed = 0

        while (
            len(dialog) > 2
            and self._estimate_tokens([system_msg, user_msg] + dialog)
            > self.config.max_context_tokens
        ):
            # Remove the 2 oldest dialog messages
            dialog = dialog[2:]
            removed += 2

        if removed > 0:
            self.log.warning(
                "context.window_enforced",
                removed_messages=removed,
                remaining_messages=len(dialog),
            )

        return [system_msg, user_msg] + dialog

    # ── Utilities ─────────────────────────────────────────────────────────

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate the number of tokens in a message list.

        Approximation: ~4 characters per token (valid for English and code).
        Extracts only the relevant content fields instead of serializing
        the full dict (which overestimates due to JSON keys and metadata).

        Args:
            messages: Message list

        Returns:
            Token estimate
        """
        total_chars = 0
        for m in messages:
            # Main message content
            content = m.get("content")
            if content:
                total_chars += len(str(content))
            # Tool calls: count name and arguments
            for tc in m.get("tool_calls", []):
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    total_chars += len(str(func.get("name", "")))
                    total_chars += len(str(func.get("arguments", "")))
            # Overhead per message (~4 metadata tokens per message)
            total_chars += 16
        return total_chars // 4


class ContextBuilder:
    """Context builder for the LLM.

    Manages the construction and updating of the message list
    sent to the LLM at each step.

    Attributes:
        repo_index: Repository index (F10). If present,
                    injected as a section of the system prompt in build_initial().
        context_manager: ContextManager (F11). If present,
                         truncates long tool results automatically.
    """

    def __init__(
        self,
        repo_index: RepoIndex | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        """Initialize the ContextBuilder.

        Args:
            repo_index: Repository index to inject into the system prompt.
                        If None, no project information is added.
            context_manager: ContextManager for truncating long tool results.
                             If None, tool results are not truncated.
        """
        self.repo_index = repo_index
        self.context_manager = context_manager

    def build_initial(
        self,
        agent_config: AgentConfig,
        prompt: str,
    ) -> list[dict[str, Any]]:
        """Build the initial messages for the LLM.

        If a repo_index is available, injects it at the end of the system prompt
        as a "Project Structure" section. This allows the agent to know which
        files exist without needing to manually call list_files.

        Args:
            agent_config: Agent configuration (system_prompt, allowed_tools, etc.)
            prompt: User prompt

        Returns:
            Message list in OpenAI format: [system, user]
        """
        # Base agent system prompt
        system_content = agent_config.system_prompt

        # Inject repository index if available
        if self.repo_index is not None:
            system_content = self._inject_repo_index(system_content, self.repo_index)

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

    def _inject_repo_index(self, system_prompt: str, index: RepoIndex) -> str:
        """Add the project structure section to the system prompt.

        Compact format showing:
        - Total files and lines
        - Language distribution
        - Directory tree (formatted compactly)
        - Guide for using search_code and grep

        Args:
            system_prompt: Base agent prompt
            index: Repository index built by RepoIndexer

        Returns:
            system_prompt with the structure section appended
        """
        # Format language summary (top 5)
        lang_items = list(index.languages.items())[:5]
        lang_str = ", ".join(f"{lang} ({n})" for lang, n in lang_items)
        if not lang_str:
            lang_str = "unknown"

        repo_section = (
            f"\n\n## Project Structure\n\n"
            f"**Total**: {index.total_files} files, {index.total_lines:,} lines  \n"
            f"**Languages**: {lang_str}\n\n"
            f"```\n"
            f"{index.tree_summary}\n"
            f"```\n\n"
            f"**Note**: Use `search_code` or `grep` to find specific code, "
            f"`find_files` to locate files by name. "
            f"Only read the files you actually need."
        )

        return system_prompt + repo_section

    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[ToolCall],
        results: list[ToolCallResult],
    ) -> list[dict[str, Any]]:
        """Append tool results to the message list.

        OpenAI format for tool calling:
        1. Assistant message with tool_calls
        2. Tool messages with the results

        Args:
            messages: Existing message list
            tool_calls: Tool calls requested by the LLM
            results: Results from executing the tool calls

        Returns:
            New message list with tool results appended
        """
        new_messages = messages.copy()

        # 1. Add assistant message with tool_calls
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
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

        # 2. Add tool messages with the results
        for tc, result in zip(tool_calls, results):
            tool_message = self._format_tool_result(tc, result)
            new_messages.append(tool_message)

        return new_messages

    def _format_tool_result(
        self,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> dict[str, Any]:
        """Format a tool result for the LLM.

        Applies truncation (Level 1 of F11) if a ContextManager is configured.
        """
        if result.was_dry_run:
            content = f"[DRY-RUN] {result.result.output}"
        elif result.result.success:
            content = result.result.output
        else:
            content = f"Error: {result.result.error}"

        # Level 1 (F11): Truncate if the result is too long
        if self.context_manager and content:
            content = self.context_manager.truncate_tool_result(content)

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.name,
            "content": content,
        }

    def _serialize_arguments(self, arguments: dict[str, Any]) -> str:
        """Serialize tool call arguments to a JSON string."""
        import json
        return json.dumps(arguments)

    def append_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Append an assistant message (final response)."""
        new_messages = messages.copy()
        new_messages.append({"role": "assistant", "content": content})
        return new_messages

    def append_user_message(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Append a user message."""
        new_messages = messages.copy()
        new_messages.append({"role": "user", "content": content})
        return new_messages
