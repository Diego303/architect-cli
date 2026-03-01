"""
Agent Loop - Main agent execution loop.

v3: Redesigned with while True — the LLM decides when to stop.
Safety nets (max_steps, budget, timeout, context) are watchdogs
that, when triggered, request a graceful close from the LLM instead of cutting.

v4-A1: Integration with the complete hook system.

Invariants:
- The LLM finishes when it no longer requests tool calls (StopReason.LLM_DONE)
- Watchdogs inject close instructions -> final LLM call
- USER_INTERRUPT is the only case that does NOT call the LLM (immediate cut)
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Callable

import structlog

from ..config.schema import AgentConfig
from ..costs.tracker import BudgetExceededError
from ..execution.engine import ExecutionEngine
from ..llm.adapter import LLMAdapter, StreamChunk
from ..logging.human import HumanLog
from .context import ContextBuilder, ContextManager
from .shutdown import GracefulShutdown
from .state import AgentState, StepResult, StopReason, ToolCallResult
from .timeout import StepTimeout, StepTimeoutError

if TYPE_CHECKING:
    from ..costs.tracker import CostTracker
    from ..features.dryrun import DryRunTracker
    from ..features.sessions import SessionManager
    from ..llm.adapter import ToolCall
    from ..skills.loader import SkillsLoader
    from ..skills.memory import ProceduralMemory
    from .guardrails import GuardrailsEngine
    from .hooks import HookExecutor

logger = structlog.get_logger()

# Map StopReason -> i18n key for close instructions (resolved lazily via t())
_CLOSE_KEYS: dict[StopReason, str] = {
    StopReason.MAX_STEPS: "close.max_steps",
    StopReason.BUDGET_EXCEEDED: "close.budget_exceeded",
    StopReason.CONTEXT_FULL: "close.context_full",
    StopReason.TIMEOUT: "close.timeout",
}


class AgentLoop:
    """Main agent loop (v3: while True).

    The LLM works until it decides it is done (no more tool requests).
    Safety nets are watchdogs that check conditions before each LLM call.
    If triggered, they request a graceful close.

    Per-iteration flow:
    1. Check safety nets -> if triggered, _graceful_close() and finish
    2. Manage context (compress if needed)
    3. Pre-LLM hooks (v4-A1)
    4. Call the LLM
    5. Post-LLM hooks (v4-A1)
    6. If no tool_calls -> agent_complete hooks -> quality gates -> exit
    7. Pre/post-tool hooks inside execute_tool_call
    8. Append results to context and repeat
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
        cost_tracker: "CostTracker | None" = None,
        timeout: int | None = None,
        hook_executor: "HookExecutor | None" = None,
        guardrails: "GuardrailsEngine | None" = None,
        skills_loader: "SkillsLoader | None" = None,
        memory: "ProceduralMemory | None" = None,
        session_manager: "SessionManager | None" = None,
        session_id: str | None = None,
        dry_run_tracker: "DryRunTracker | None" = None,
    ):
        """Initialize the agent loop.

        Args:
            llm: Configured LLMAdapter
            engine: Configured ExecutionEngine
            agent_config: Agent configuration
            context_builder: ContextBuilder for messages
            shutdown: GracefulShutdown to detect interruptions
            step_timeout: Maximum seconds per individual step (SIGALRM). 0 = no limit.
            context_manager: ContextManager for context pruning
            cost_tracker: CostTracker to record costs
            timeout: Maximum total execution seconds. None = no limit.
            hook_executor: HookExecutor for lifecycle hooks (v4-A1)
            guardrails: GuardrailsEngine for deterministic security (v4-A2)
            skills_loader: SkillsLoader for project context and skills (v4-A3)
            memory: ProceduralMemory to persist corrections (v4-A4)
            session_manager: SessionManager to persist sessions (v4-B1)
            session_id: Session ID for resume. None generates a new one.
            dry_run_tracker: DryRunTracker to record actions in dry-run mode (v4-B4)
        """
        self.llm = llm
        self.engine = engine
        self.agent_config = agent_config
        self.ctx = context_builder
        self.shutdown = shutdown
        self.step_timeout = step_timeout
        self.context_manager = context_manager
        self.cost_tracker = cost_tracker
        self.timeout = timeout
        self.hook_executor = hook_executor
        self.guardrails = guardrails
        self.skills_loader = skills_loader
        self.memory = memory
        self.session_manager = session_manager
        self.session_id = session_id
        self.dry_run_tracker = dry_run_tracker
        self._start_time: float = 0.0
        self._pending_context: list[str] = []
        self._files_touched: set[str] = set()
        self.log = logger.bind(component="agent_loop")
        self.hlog = HumanLog(self.log)

    def run(
        self,
        prompt: str,
        stream: bool = False,
        on_stream_chunk: Callable[[str], None] | None = None,
    ) -> AgentState:
        """Execute the complete agent loop.

        Args:
            prompt: Initial user prompt
            stream: If True, use LLM streaming
            on_stream_chunk: Optional callback for streaming chunks

        Returns:
            Final AgentState with the execution result
        """
        self._start_time = time.time()

        # v4-B1: Generate session_id if not provided
        if not self.session_id and self.session_manager:
            from ..features.sessions import generate_session_id
            self.session_id = generate_session_id()

        # Initialize state
        state = AgentState()
        state.messages = self.ctx.build_initial(self.agent_config, prompt)
        state.model = self.llm.config.model
        state.cost_tracker = self.cost_tracker

        # v4-A3: Inject skills context into the system prompt
        if self.skills_loader:
            skills_context = self.skills_loader.build_system_context()
            if skills_context and state.messages and state.messages[0]["role"] == "system":
                state.messages[0]["content"] += "\n\n" + skills_context

        # v4-A4: Inject procedural memory into the system prompt
        if self.memory:
            memory_context = self.memory.get_context()
            if memory_context and state.messages and state.messages[0]["role"] == "system":
                state.messages[0]["content"] += "\n\n" + memory_context

        # Get schemas of allowed tools
        tools_schema = self.engine.registry.get_schemas(
            self.agent_config.allowed_tools or None
        )

        self.log.info(
            "agent.loop.start",
            prompt=prompt[:100] + "..." if len(prompt) > 100 else prompt,
            max_steps=self.agent_config.max_steps,
            allowed_tools=self.agent_config.allowed_tools or "all",
            timeout=self.timeout,
        )

        # ── SESSION START HOOK (v4-A1) ─────────────────────────────────
        self._run_hooks_safe("session_start", {
            "task": prompt[:200],
            "agent": "build",
            "model": self.llm.config.model,
        })

        step = 0

        # ── Main loop: the LLM decides when to finish ────────────────
        try:
            while True:

                # ── SAFETY NETS (before each LLM call) ────────────────
                stop_reason = self._check_safety_nets(state, step)
                if stop_reason is not None:
                    return self._graceful_close(state, stop_reason, tools_schema)

                # ── CONTEXT MANAGEMENT ────────────────────────────────────────
                if self.context_manager:
                    state.messages = self.context_manager.manage(
                        state.messages, self.llm
                    )

                # ── PRE-LLM HOOKS (v4-A1) ──────────────────────────────────
                self._run_hooks_safe("pre_llm_call", {
                    "step": str(step),
                })

                # Inject pending hook context (if any)
                if self._pending_context:
                    for ctx_text in self._pending_context:
                        state.messages.append({
                            "role": "user",
                            "content": f"[Hook context]: {ctx_text}",
                        })
                    self._pending_context.clear()

                # ── LLM CALL ────────────────────────────────────────────
                self.log.info("agent.step.start", step=step)
                self.hlog.llm_call(step, messages_count=len(state.messages))

                try:
                    with StepTimeout(self.step_timeout):
                        if stream:
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
                                raise RuntimeError("Streaming completed without returning final response")
                        else:
                            response = self.llm.completion(
                                messages=state.messages,
                                tools=tools_schema if tools_schema else None,
                            )

                except StepTimeoutError:
                    self.log.error("agent.step_timeout", step=step, seconds=self.step_timeout)
                    self.hlog.step_timeout(self.step_timeout)
                    # Treat step timeout as total timeout
                    return self._graceful_close(state, StopReason.TIMEOUT, tools_schema)

                except Exception as e:
                    self.log.error("agent.llm_error", error=str(e), step=step)
                    self.hlog.llm_error(str(e))
                    state.status = "failed"
                    state.stop_reason = StopReason.LLM_ERROR
                    state.final_output = f"Unrecoverable LLM error: {e}"
                    return state

                # ── RECORD COST ───────────────────────────────────────────
                if self.cost_tracker and response.usage:
                    try:
                        self.cost_tracker.record(
                            step=step,
                            model=self.llm.config.model,
                            usage=response.usage,
                            source="agent",
                        )
                    except BudgetExceededError as e:
                        self.log.error("agent.budget_exceeded", step=step, error=str(e))
                        # Budget exceeded on this step — graceful close
                        return self._graceful_close(state, StopReason.BUDGET_EXCEEDED, tools_schema)

                # ── POST-LLM HOOKS (v4-A1) ─────────────────────────────────
                self._run_hooks_safe("post_llm_call", {
                    "step": str(step),
                    "has_tool_calls": str(bool(response.tool_calls)),
                })

                step += 1

                # ── THE LLM DECIDED TO FINISH (no tools requested) ──────────────────
                if not response.tool_calls:
                    self.hlog.llm_response(tool_calls=0)
                    self.log.info(
                        "agent.complete",
                        step=step,
                        reason="llm_decided",
                        output_preview=(
                            response.content[:100] + "..."
                            if response.content and len(response.content) > 100
                            else response.content
                        ),
                    )

                    # ── QUALITY GATES (v4-A2) ────────────────────────────────
                    if self.guardrails and self.guardrails.config.quality_gates:
                        gate_results = self.guardrails.run_quality_gates()
                        failed_required = [
                            g for g in gate_results if not g["passed"] and g["required"]
                        ]
                        if failed_required:
                            feedback = "Required quality gates not passed:\n"
                            for g in failed_required:
                                feedback += f"  - {g['name']}: {g['output'][:200]}\n"
                            feedback += "\nFix these issues before the task can be completed."
                            state.messages.append({"role": "user", "content": feedback})
                            self.log.info(
                                "guardrail.quality_gates_failed",
                                failed=[g["name"] for g in failed_required],
                            )
                            continue  # Back to while True

                    # ── AGENT COMPLETE HOOKS (v4-A1) ─────────────────────────
                    self._run_hooks_safe("agent_complete", {
                        "step": str(step),
                        "total_cost": str(self.cost_tracker.total_cost_usd if self.cost_tracker else 0),
                    })

                    # Include cost in completion message if tracker available
                    cost_str = None
                    if self.cost_tracker:
                        cost_str = self.cost_tracker.format_summary_line()
                    self.hlog.agent_done(step, cost=cost_str)
                    state.final_output = response.content
                    state.status = "success"
                    state.stop_reason = StopReason.LLM_DONE

                    # v4-B1: Save final session
                    self._save_session(state, prompt, step)
                    break

                # ── THE LLM REQUESTED TOOLS -> EXECUTE ────────────────────────────
                self.hlog.llm_response(tool_calls=len(response.tool_calls))
                self.log.info(
                    "agent.tool_calls_received",
                    step=step,
                    count=len(response.tool_calls),
                    tools=[tc.name for tc in response.tool_calls],
                )

                # Execute tool calls (parallel or sequential)
                tool_results = self._execute_tool_calls_batch(response.tool_calls, step)

                # Update messages with tool results
                state.messages = self.ctx.append_tool_results(
                    state.messages, response.tool_calls, tool_results
                )

                # Record step
                state.steps.append(StepResult(
                    step_number=step,
                    llm_response=response,
                    tool_calls_made=tool_results,
                ))

                # v4-B1: Track touched files for the session
                for tc in tool_results:
                    if tc.tool_name in ("write_file", "edit_file", "apply_patch", "delete_file"):
                        path = tc.args.get("path", "")
                        if path:
                            self._files_touched.add(path)

                # v4-B1: Save session after each step
                self._save_session(state, prompt, step)

        finally:
            # ── SESSION END HOOK (v4-A1) — always runs ─────────────
            self._run_hooks_safe("session_end", {
                "steps": str(step),
                "status": state.status,
                "cost": str(self.cost_tracker.total_cost_usd if self.cost_tracker else 0),
            })

        # ── Final log ─────────────────────────────────────────────────────
        self.log.info(
            "agent.loop.complete",
            status=state.status,
            stop_reason=state.stop_reason.value if state.stop_reason else None,
            total_steps=state.current_step,
            total_tool_calls=state.total_tool_calls,
        )
        self.hlog.loop_complete(
            status=state.status,
            stop_reason=state.stop_reason.value if state.stop_reason else None,
            total_steps=state.current_step,
            total_tool_calls=state.total_tool_calls,
        )

        return state

    # ── HOOKS HELPERS (v4-A1) ─────────────────────────────────────────────

    def _run_hooks_safe(self, event_name: str, context: dict[str, Any]) -> None:
        """Execute hooks for an event safely (without breaking the loop).

        Args:
            event_name: Event name (must match a HookEvent value).
            context: Context dictionary for the hook.
        """
        if not self.hook_executor:
            return

        from .hooks import HookEvent

        try:
            event = HookEvent(event_name)
        except ValueError:
            return

        try:
            results = self.hook_executor.run_event(event, context)
            # Collect additional context to inject into the next message
            for result in results:
                if result.additional_context:
                    self._pending_context.append(result.additional_context)
        except Exception as e:
            self.log.warning("hooks.lifecycle_error", event=event_name, error=str(e))

    # ── SESSION PERSISTENCE (v4-B1) ──────────────────────────────────────

    def _save_session(self, state: AgentState, task: str, step: int) -> None:
        """Save the current session state to disk (if configured).

        Args:
            state: Current agent state.
            task: Original prompt/task.
            step: Current step number.
        """
        if not self.session_manager or not self.session_id:
            return

        try:
            from ..features.sessions import SessionState

            session_state = SessionState(
                session_id=self.session_id,
                task=task,
                agent="build",
                model=self.llm.config.model,
                status=state.status,
                steps_completed=step,
                messages=state.messages[-30:],  # Last 30 to avoid explosion
                files_modified=sorted(self._files_touched),
                total_cost=(
                    self.cost_tracker.total_cost_usd if self.cost_tracker else 0.0
                ),
                started_at=self._start_time,
                updated_at=time.time(),
                stop_reason=state.stop_reason.value if state.stop_reason else None,
            )
            self.session_manager.save(session_state)
        except Exception as e:
            self.log.warning("session.save_error", error=str(e))

    # ── SAFETY NETS ───────────────────────────────────────────────────────

    def _check_safety_nets(
        self, state: AgentState, step: int
    ) -> StopReason | None:
        """Check all safety conditions before each step.

        Returns None if everything is fine, or the StopReason if we must stop.
        Order matters: USER_INTERRUPT first (most urgent).
        """
        # 1. User interrupt (Ctrl+C / SIGTERM) — immediate cut
        if self.shutdown and self.shutdown.should_stop:
            self.log.warning("safety.user_interrupt", step=step)
            self.hlog.safety_net("user_interrupt", step=step)
            return StopReason.USER_INTERRUPT

        # 2. Max steps — step count watchdog
        if step >= self.agent_config.max_steps:
            self.log.warning(
                "safety.max_steps",
                step=step,
                max_steps=self.agent_config.max_steps,
            )
            self.hlog.safety_net("max_steps", step=step, max_steps=self.agent_config.max_steps)
            return StopReason.MAX_STEPS

        # 3. Budget — cost watchdog (pre-LLM check)
        if self.cost_tracker and self.cost_tracker.is_budget_exceeded():
            self.log.warning(
                "safety.budget_exceeded",
                step=step,
                total_cost=self.cost_tracker.total_cost_usd,
            )
            self.hlog.safety_net("budget_exceeded", step=step)
            return StopReason.BUDGET_EXCEEDED

        # 4. Total timeout — time watchdog
        if self.timeout and (time.time() - self._start_time) > self.timeout:
            self.log.warning("safety.timeout", elapsed=time.time() - self._start_time)
            self.hlog.safety_net("timeout")
            return StopReason.TIMEOUT

        # 4. Context window critically full (even after compression)
        if self.context_manager and self.context_manager.is_critically_full(state.messages):
            self.log.warning("safety.context_full", step=step)
            self.hlog.safety_net("context_full", step=step)
            return StopReason.CONTEXT_FULL

        return None

    # ── GRACEFUL CLOSE ────────────────────────────────────────────────────

    def _graceful_close(
        self,
        state: AgentState,
        reason: StopReason,
        tools_schema: list | None,
    ) -> AgentState:
        """Graceful close when a watchdog triggers.

        Instead of cutting abruptly, gives the LLM one last chance
        to summarize what was done and what remains pending.
        USER_INTERRUPT is the exception: the LLM is not called.
        """
        self.log.info("agent.closing", reason=reason.value, steps=len(state.steps))
        self.hlog.closing(reason.value, len(state.steps))

        state.stop_reason = reason

        # USER_INTERRUPT: immediate cut, no LLM call
        if reason == StopReason.USER_INTERRUPT:
            state.status = "partial"
            state.final_output = (
                f"Interrupted by user. "
                f"Steps completed: {state.current_step}."
            )
            return state

        # BUDGET_EXCEEDED: immediate cut, do NOT spend more money on summary
        if reason == StopReason.BUDGET_EXCEEDED:
            cost_info = ""
            if self.cost_tracker:
                cost_info = f" Total cost: ${self.cost_tracker.total_cost_usd:.4f}."
            state.status = "partial"
            state.final_output = (
                f"Budget exceeded.{cost_info} "
                f"Steps completed: {state.current_step}."
            )
            # Skip LLM summary call — no point spending more money
            state.status = "partial"
            self._save_session(state, state.messages[1]["content"] if len(state.messages) > 1 else "", state.current_step)
            self.log.info(
                "agent.loop.complete",
                status=state.status,
                stop_reason=state.stop_reason.value,
                total_steps=state.current_step,
                total_tool_calls=state.total_tool_calls,
            )
            self.hlog.loop_complete(
                status=state.status,
                stop_reason=state.stop_reason.value,
                total_steps=state.current_step,
                total_tool_calls=state.total_tool_calls,
            )
            return state

        # For all other watchdogs: ask LLM for a summary
        from ..i18n import t
        close_key = _CLOSE_KEYS.get(reason)
        if close_key:
            instruction = t(close_key)
            state.messages.append({
                "role": "user",
                "content": f"[SYSTEM] {instruction}",
            })

            try:
                # Last call WITHOUT tools — close summary only
                close_response = self.llm.completion(
                    messages=state.messages,
                    tools=None,
                )
                state.final_output = close_response.content
            except Exception as e:
                self.log.warning("agent.close_response_failed", error=str(e))
                state.final_output = t(
                    "close.agent_stopped",
                    reason=reason.value,
                    steps=state.current_step,
                )

        state.status = "partial"

        # v4-B1: Save session with partial state
        self._save_session(state, state.messages[1]["content"] if len(state.messages) > 1 else "", state.current_step)

        self.log.info(
            "agent.loop.complete",
            status=state.status,
            stop_reason=state.stop_reason.value,
            total_steps=state.current_step,
            total_tool_calls=state.total_tool_calls,
        )
        self.hlog.loop_complete(
            status=state.status,
            stop_reason=state.stop_reason.value,
            total_steps=state.current_step,
            total_tool_calls=state.total_tool_calls,
        )
        return state

    # ── TOOL CALL EXECUTION ──────────────────────────────────────────

    def _execute_tool_calls_batch(
        self,
        tool_calls: list,
        step: int,
    ) -> list[ToolCallResult]:
        """Execute a batch of tool calls, parallelizing when safe.

        Parallelization is only enabled when:
        - There is more than one tool call
        - parallel_tools=True in configuration
        - The confirmation mode is yolo
        - Or confirm-sensitive and no tool is sensitive
        """
        if not tool_calls:
            return []

        if len(tool_calls) == 1:
            return [self._execute_single_tool(tool_calls[0], step)]

        if not self._should_parallelize(tool_calls):
            return [self._execute_single_tool(tc, step) for tc in tool_calls]

        # Parallel execution preserving original order
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
        """Execute a single tool call and return the result.

        v4-A1: Runs pre-hooks before the tool and post-hooks after.
        Pre-hooks can block or modify the input.
        Post-hooks can add additional context to the result.
        """
        tool_name: str = tc.name  # type: ignore[attr-defined]
        tool_args: dict[str, Any] = tc.arguments  # type: ignore[attr-defined]

        self.log.info(
            "agent.tool_call.execute",
            step=step,
            tool=tool_name,
            args=self._sanitize_args_for_log(tool_args),
        )
        # Detect if it's an MCP tool for differentiated logging
        is_mcp = tool_name.startswith("mcp_")
        mcp_server = tool_name.split("_")[1] if is_mcp and "_" in tool_name[4:] else ""
        self.hlog.tool_call(
            tool_name, tool_args,
            is_mcp=is_mcp, mcp_server=mcp_server,
        )

        # ── GUARDRAILS (v4-A2) — before hooks ──────────────────────────
        guardrail_result = self.engine.check_guardrails(tool_name, tool_args)
        if guardrail_result is not None:
            self.log.info("agent.tool_call.blocked_by_guardrail", tool=tool_name)
            self.hlog.tool_result(tool_name, False, guardrail_result.error or guardrail_result.output)
            return ToolCallResult(
                tool_name=tool_name,
                args=tool_args,
                result=guardrail_result,
                was_confirmed=True,
                was_dry_run=self.engine.dry_run,
            )

        # ── PRE-EXECUTION CODE RULES (v4-A2) — block BEFORE write ────
        code_rule_messages = self.engine.check_code_rules(tool_name, tool_args)
        if code_rule_messages:
            block_msgs = [m for m in code_rule_messages if m.startswith("BLOCKED") or m.startswith("BLOQUEADO")]
            if block_msgs:
                from ..tools.base import ToolResult as TR
                blocked_result = TR(
                    success=False,
                    output="\n".join(block_msgs),
                    error="Code rule violation (blocked before execution)",
                )
                self.log.info("agent.tool_call.blocked_by_code_rule", tool=tool_name)
                self.hlog.tool_result(tool_name, False, blocked_result.error)
                return ToolCallResult(
                    tool_name=tool_name,
                    args=tool_args,
                    result=blocked_result,
                    was_confirmed=True,
                    was_dry_run=self.engine.dry_run,
                )
            # Warnings: log them but allow execution
            for warn_msg in code_rule_messages:
                self.log.warning("agent.code_rule.warning", msg=warn_msg)

        # ── PRE-TOOL HOOKS (v4-A1) ─────────────────────────────────────
        pre_result = self.engine.run_pre_tool_hooks(tool_name, tool_args)
        from ..tools.base import ToolResult
        if isinstance(pre_result, ToolResult):
            # Hook blocked the action
            self.log.info("agent.tool_call.blocked_by_hook", tool=tool_name)
            self.hlog.tool_result(tool_name, False, pre_result.error)
            return ToolCallResult(
                tool_name=tool_name,
                args=tool_args,
                result=pre_result,
                was_confirmed=True,
                was_dry_run=self.engine.dry_run,
            )
        elif isinstance(pre_result, dict):
            # Hook modified the input
            tool_args = pre_result

        # ── EXECUTE TOOL ────────────────────────────────────────────────
        result = self.engine.execute_tool_call(tool_name, tool_args)

        # ── DRY-RUN TRACKER (v4-B4) ─────────────────────────────────────
        if self.dry_run_tracker:
            self.dry_run_tracker.record(step, tool_name, tool_args)

        # ── POST-TOOL HOOKS (v4-A1) ────────────────────────────────────
        hook_output = self.engine.run_post_tool_hooks(
            tool_name, tool_args, result.output or "", result.success
        )

        # If there's hook output, append it to the tool result
        if hook_output and result.success:
            from ..tools.base import ToolResult as TR
            combined_output = (result.output or "") + "\n\n" + hook_output
            result = TR(
                success=result.success,
                output=combined_output,
                error=result.error,
            )
            self.log.info("agent.hook.complete", step=step, tool=tool_name)
            self.hlog.hook_complete(tool_name, hook="post-tool", success=True)

        self.log.info(
            "agent.tool_call.complete",
            step=step,
            tool=tool_name,
            success=result.success,
            error=result.error if not result.success else None,
        )
        self.hlog.tool_result(tool_name, result.success, result.error if not result.success else None)

        return ToolCallResult(
            tool_name=tool_name,
            args=tool_args,
            result=result,
            was_confirmed=True,
            was_dry_run=self.engine.dry_run,
        )

    def _should_parallelize(self, tool_calls: list) -> bool:
        """Determine whether tool calls can be executed in parallel."""
        # Respect explicit configuration
        if self.context_manager and not self.context_manager.config.parallel_tools:
            return False

        confirm_mode = self.agent_config.confirm_mode

        if confirm_mode == "confirm-all":
            return False

        if confirm_mode == "confirm-sensitive":
            for tc in tool_calls:
                if self.engine.registry.has_tool(tc.name):  # type: ignore[attr-defined]
                    tool = self.engine.registry.get(tc.name)  # type: ignore[attr-defined]
                    if tool.sensitive:
                        return False

        return True

    def _sanitize_args_for_log(self, args: dict) -> dict:
        """Sanitize arguments for logging (truncate long values)."""
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + f"... ({len(value)} chars)"
            else:
                sanitized[key] = value
        return sanitized
