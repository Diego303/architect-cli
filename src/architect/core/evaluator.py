"""
Self-Evaluator — Automatic evaluation of the agent's result (F12).

The SelfEvaluator allows the agent to review its own output and, in
``full`` mode, retry the task if it detects it was not completed correctly.

Modes:
- ``basic``: One extra LLM call (~500 tokens). If evaluation fails,
  marks the state as ``partial`` and reports the issues.
- ``full``: Up to ``max_retries`` evaluation + correction cycles. More expensive
  (N * ~500 eval tokens + potentially N full agent runs),
  but achieves higher quality results on complex tasks.

Typical CLI usage:
    architect run "task" --self-eval basic
    architect run "task" --self-eval full
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import structlog

if TYPE_CHECKING:
    from ..llm.adapter import LLMAdapter
    from .state import AgentState

logger = structlog.get_logger()


@dataclass
class EvalResult:
    """Result of an agent evaluation.

    Attributes:
        completed: True if the task is considered correctly completed.
        confidence: Evaluator confidence level (0.0 - 1.0).
        issues: List of detected issues (empty if completed).
        suggestion: Suggestion for improving the result.
        raw_response: Raw LLM response (for debugging).
    """

    completed: bool
    confidence: float
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""
    raw_response: str = ""

    def __repr__(self) -> str:
        return (
            f"<EvalResult("
            f"completed={self.completed}, "
            f"confidence={self.confidence:.0%}, "
            f"issues={len(self.issues)})>"
        )


class SelfEvaluator:
    """Automatic evaluator of the agent's result.

    Uses the LLM to verify whether the task was completed correctly
    and, in ``full`` mode, retry with a correction prompt.

    Attributes:
        llm: LLMAdapter for evaluation calls.
        max_retries: Maximum number of retries in ``full`` mode.
        confidence_threshold: Minimum confidence threshold to accept the result.
        log: Structured logger.
    """

    # Eval system prompt is resolved lazily via i18n
    _EVAL_SYSTEM_PROMPT: str = ""  # placeholder; actual value comes from t()

    def __init__(
        self,
        llm: LLMAdapter,
        max_retries: int = 2,
        confidence_threshold: float = 0.8,
    ) -> None:
        """Initialize the evaluator.

        Args:
            llm: LLMAdapter for evaluation calls.
            max_retries: Maximum number of retries in ``full`` mode.
            confidence_threshold: Confidence threshold to accept the result.
        """
        self.llm = llm
        self.max_retries = max_retries
        self.confidence_threshold = confidence_threshold
        self.log = logger.bind(component="self_evaluator")

    # ── Basic mode ──────────────────────────────────────────────────────────

    def evaluate_basic(
        self, original_prompt: str, state: AgentState
    ) -> EvalResult:
        """Evaluate whether the task was completed correctly (single LLM call).

        Builds a context with the original prompt, the agent's output, and
        a summary of the executed steps, then asks the LLM whether the task
        was completed. Costs ~500 extra tokens.

        Args:
            original_prompt: Original user prompt.
            state: Final agent state.

        Returns:
            EvalResult with the evaluator's verdict.
        """
        self.log.info(
            "eval.basic.start",
            prompt_preview=original_prompt[:80],
            agent_steps=state.current_step,
            agent_tool_calls=state.total_tool_calls,
        )

        from ..i18n import t

        steps_summary = self._summarize_steps(state)
        output_preview = (state.final_output or t("eval.no_output"))[:500]

        eval_messages = [
            {"role": "system", "content": t("eval.system_prompt")},
            {
                "role": "user",
                "content": t(
                    "eval.user_prompt",
                    original_prompt=original_prompt,
                    output_preview=output_preview,
                    steps_summary=steps_summary,
                ),
            },
        ]

        try:
            response = self.llm.completion(eval_messages, tools=None)
            raw = response.content or ""
        except Exception as e:
            self.log.warning("eval.basic.llm_error", error=str(e))
            return EvalResult(
                completed=False,
                confidence=0.0,
                issues=[t("eval.error", error=str(e))],
                suggestion=t("eval.error_suggestion"),
                raw_response="",
            )

        result = self._parse_eval(raw)

        self.log.info(
            "eval.basic.complete",
            completed=result.completed,
            confidence=result.confidence,
            issues_count=len(result.issues),
        )

        return result

    # ── Full mode ───────────────────────────────────────────────────────────

    def evaluate_full(
        self,
        original_prompt: str,
        state: AgentState,
        run_fn: Callable[[str], AgentState],
    ) -> AgentState:
        """Evaluate the result and retry if issues are detected.

        Cycle:
        1. Evaluate with ``evaluate_basic``
        2. If completed=True and confidence >= threshold -> return state
        3. Otherwise -> build correction prompt and re-run the agent
        4. Repeat up to ``max_retries`` times

        Args:
            original_prompt: Original user prompt.
            state: Agent state after initial execution.
            run_fn: Function that re-runs the agent with a new prompt.
                    Signature: ``(prompt: str) -> AgentState``

        Returns:
            Best available AgentState (may be the original if all retries failed).
        """
        self.log.info(
            "eval.full.start",
            max_retries=self.max_retries,
            confidence_threshold=self.confidence_threshold,
        )

        for attempt in range(self.max_retries):
            eval_result = self.evaluate_basic(original_prompt, state)

            # Check if the result is acceptable
            if eval_result.completed and eval_result.confidence >= self.confidence_threshold:
                self.log.info(
                    "eval.full.passed",
                    attempt=attempt,
                    confidence=eval_result.confidence,
                )
                return state

            self.log.warning(
                "eval.full.retry",
                attempt=attempt + 1,
                max_retries=self.max_retries,
                completed=eval_result.completed,
                confidence=eval_result.confidence,
                issues=eval_result.issues,
            )

            # Build correction prompt with detailed context
            correction_prompt = self._build_correction_prompt(
                original_prompt, eval_result
            )

            # Re-run the agent with the correction prompt
            try:
                state = run_fn(correction_prompt)
            except Exception as e:
                self.log.error("eval.full.run_error", attempt=attempt, error=str(e))
                break

        self.log.warning(
            "eval.full.max_retries_reached",
            attempts=self.max_retries,
            final_status=state.status,
        )
        return state

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _build_correction_prompt(
        self, original_prompt: str, eval_result: EvalResult
    ) -> str:
        """Build the correction prompt with the problem context.

        Args:
            original_prompt: Original user prompt.
            eval_result: Evaluation result that failed.

        Returns:
            Correction prompt for re-running the agent.
        """
        from ..i18n import t

        issues_text = (
            "\n".join(f"  - {issue}" for issue in eval_result.issues)
            if eval_result.issues
            else t("eval.correction_default_issues")
        )
        suggestion_text = (
            eval_result.suggestion
            if eval_result.suggestion
            else t("eval.correction_default_suggestion")
        )

        return t(
            "eval.correction_prompt",
            original_prompt=original_prompt,
            issues_text=issues_text,
            suggestion_text=suggestion_text,
        )

    def _summarize_steps(self, state: AgentState) -> str:
        """Summarize the agent's steps into readable text for the evaluator.

        Args:
            state: Agent state.

        Returns:
            Concise summary of the executed steps.
        """
        from ..i18n import t

        if not state.steps:
            return t("eval.no_steps")

        parts: list[str] = []
        for step in state.steps:
            if step.tool_calls_made:
                tool_names = [tc.tool_name for tc in step.tool_calls_made]
                successes = [tc.result.success for tc in step.tool_calls_made]
                status_str = t("eval.status_ok") if all(successes) else t("eval.status_errors")
                parts.append(t(
                    "eval.step_line",
                    step=step.step_number + 1,
                    tools=", ".join(tool_names),
                    status=status_str,
                ))
            else:
                parts.append(t("eval.step_no_tools", step=step.step_number + 1))

        return "\n".join(parts)

    def _parse_eval(self, content: str) -> EvalResult:
        """Parse the JSON response from the evaluator LLM.

        Tries three strategies in order:
        1. Parse the content directly as JSON
        2. Extract the first ``{...}`` block with regex
        3. Extract from a code block ```json ... ```

        If all fail, returns a conservative EvalResult (not completed).

        Args:
            content: Raw LLM response.

        Returns:
            Parsed EvalResult or conservative fallback.
        """
        content = content.strip()

        # Strategy 1: Direct JSON
        data = self._try_parse_json(content)

        # Strategy 2: Extract from code block ```json ... ```
        if data is None:
            code_block_match = re.search(
                r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content
            )
            if code_block_match:
                data = self._try_parse_json(code_block_match.group(1))

        # Strategy 3: Extract first valid {...}
        if data is None:
            brace_match = re.search(r"\{[\s\S]*?\}", content)
            if brace_match:
                data = self._try_parse_json(brace_match.group(0))

        # Fallback: conservative evaluation
        if data is None:
            from ..i18n import t
            self.log.warning(
                "eval.parse_failed",
                content_preview=content[:100],
            )
            return EvalResult(
                completed=False,
                confidence=0.0,
                issues=[t("eval.parse_failed")],
                suggestion=t("eval.parse_failed_suggestion"),
                raw_response=content,
            )

        # Extract fields with safe default values
        completed = bool(data.get("completed", False))
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))  # Clamp a [0, 1]

        raw_issues = data.get("issues", [])
        if isinstance(raw_issues, list):
            issues = [str(i) for i in raw_issues if i]
        else:
            issues = [str(raw_issues)] if raw_issues else []

        suggestion = str(data.get("suggestion", ""))

        return EvalResult(
            completed=completed,
            confidence=confidence,
            issues=issues,
            suggestion=suggestion,
            raw_response=content,
        )

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Try to parse text as JSON.

        Args:
            text: Text to parse.

        Returns:
            Dict if parsing succeeded, None if it failed.
        """
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None
