"""
Mixed Mode Runner - Executes plan -> build automatically.

Mixed mode is activated with ``architect run --mode mixed "prompt"``
or as an alias ``architect plan-build "prompt"``.
First runs the 'plan' agent to analyze the task,
then runs the 'build' agent with the plan as context.
"""

from typing import TYPE_CHECKING, Callable

import structlog

from ..config.schema import AgentConfig
from ..execution.engine import ExecutionEngine
from ..llm.adapter import LLMAdapter
from .context import ContextBuilder, ContextManager
from .loop import AgentLoop
from .shutdown import GracefulShutdown
from .state import AgentState

if TYPE_CHECKING:
    from ..costs.tracker import CostTracker

logger = structlog.get_logger()


class MixedModeRunner:
    """Executes plan first, then build with the plan as context.

    Flow:
    1. Run 'plan' agent with the user's prompt
    2. If plan fails or shutdown is received, return the state
    3. If plan succeeds, run 'build' agent with:
       - Original user prompt
       - Generated plan as additional context
    4. Return the build state
    """

    def __init__(
        self,
        llm: LLMAdapter,
        engine: ExecutionEngine,
        plan_config: AgentConfig,
        build_config: AgentConfig,
        context_builder: ContextBuilder,
        shutdown: GracefulShutdown | None = None,
        step_timeout: int = 0,
        context_manager: ContextManager | None = None,
        cost_tracker: "CostTracker | None" = None,
    ):
        """Initialize the mixed mode runner.

        Args:
            llm: Configured LLMAdapter
            engine: Configured ExecutionEngine
            plan_config: Plan agent configuration
            build_config: Build agent configuration
            context_builder: ContextBuilder for messages
            shutdown: GracefulShutdown to detect interruptions (optional)
            step_timeout: Maximum seconds per step. 0 = no timeout.
            context_manager: ContextManager for context pruning (F11).
            cost_tracker: CostTracker to record costs (F14, optional).
        """
        self.llm = llm
        self.engine = engine
        self.plan_config = plan_config
        self.build_config = build_config
        self.ctx = context_builder
        self.shutdown = shutdown
        self.step_timeout = step_timeout
        self.context_manager = context_manager
        self.cost_tracker = cost_tracker
        self.log = logger.bind(component="mixed_mode_runner")

    def run(
        self,
        prompt: str,
        stream: bool = False,
        on_stream_chunk: Callable[[str], None] | None = None,
    ) -> AgentState:
        """Execute the plan -> build flow.

        Args:
            prompt: Original user prompt
            stream: If True, use LLM streaming in the build phase
            on_stream_chunk: Optional callback for streaming chunks

        Returns:
            Final AgentState (from the build agent, or plan if plan failed)
        """
        self.log.info(
            "mixed_mode.start",
            prompt=prompt[:100] + "..." if len(prompt) > 100 else prompt,
        )

        # Phase 1: Run plan (without streaming -- plan is fast and silent)
        self.log.info("mixed_mode.phase.plan")
        plan_loop = AgentLoop(
            self.llm,
            self.engine,
            self.plan_config,
            self.ctx,
            shutdown=self.shutdown,
            step_timeout=self.step_timeout,
            context_manager=self.context_manager,
            cost_tracker=self.cost_tracker,
        )

        plan_state = plan_loop.run(prompt, stream=False)

        # If shutdown was received during the plan phase, return immediately
        if self.shutdown and self.shutdown.should_stop:
            self.log.warning("mixed_mode.shutdown_after_plan")
            return plan_state

        # Check plan result
        if plan_state.status == "failed":
            self.log.error(
                "mixed_mode.plan_failed",
                error=plan_state.final_output,
            )
            return plan_state

        if not plan_state.final_output:
            self.log.warning("mixed_mode.plan_no_output")
            # Continue anyway with empty plan
            plan_output = "(The planning agent produced no output)"
        else:
            plan_output = plan_state.final_output

        self.log.info(
            "mixed_mode.plan_complete",
            status=plan_state.status,
            plan_preview=plan_output[:200] + "..."
            if len(plan_output) > 200
            else plan_output,
        )

        # Phase 2: Run build with the plan as context
        self.log.info("mixed_mode.phase.build")

        # Build enriched prompt with the plan
        enriched_prompt = self._build_enriched_prompt(prompt, plan_output)

        build_loop = AgentLoop(
            self.llm,
            self.engine,
            self.build_config,
            self.ctx,
            shutdown=self.shutdown,
            step_timeout=self.step_timeout,
            context_manager=self.context_manager,
            cost_tracker=self.cost_tracker,
        )

        # Run build (with streaming if enabled)
        build_state = build_loop.run(enriched_prompt, stream=stream, on_stream_chunk=on_stream_chunk)

        self.log.info(
            "mixed_mode.complete",
            final_status=build_state.status,
            total_steps=plan_state.current_step + build_state.current_step,
            total_tool_calls=plan_state.total_tool_calls + build_state.total_tool_calls,
        )

        # Return the build state
        # TODO: In the future, we could combine both states
        return build_state

    def _build_enriched_prompt(self, original_prompt: str, plan: str) -> str:
        """Build an enriched prompt with the plan.

        Args:
            original_prompt: Original user prompt
            plan: Plan generated by the plan agent

        Returns:
            Enriched prompt for the build agent
        """
        return f"""The user requested:
{original_prompt}

A planning agent analyzed the task and generated this plan:

---
{plan}
---

Your job is to execute this plan step by step. Use the available tools
to complete the task as planned. If something in the plan is unclear or
needs adjustments, use your judgment to adapt it."""
