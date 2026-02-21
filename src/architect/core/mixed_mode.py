"""
Mixed Mode Runner - Ejecuta plan → build automáticamente.

El modo mixto se activa con ``architect run --mode mixed "prompt"``
o como alias ``architect plan-build "prompt"``.
Ejecuta primero el agente 'plan' para analizar la tarea,
y luego el agente 'build' con el plan como contexto.
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
    """Ejecuta plan primero, luego build con el plan como contexto.

    Flujo:
    1. Ejecutar agente 'plan' con el prompt del usuario
    2. Si plan falla o se recibe shutdown, retornar el estado
    3. Si plan tiene éxito, ejecutar agente 'build' con:
       - Prompt original del usuario
       - Plan generado como contexto adicional
    4. Retornar el estado de build
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
        """Inicializa el mixed mode runner.

        Args:
            llm: LLMAdapter configurado
            engine: ExecutionEngine configurado
            plan_config: Configuración del agente plan
            build_config: Configuración del agente build
            context_builder: ContextBuilder para mensajes
            shutdown: GracefulShutdown para detectar interrupciones (opcional)
            step_timeout: Segundos máximos por step. 0 = sin timeout.
            context_manager: ContextManager para pruning del contexto (F11).
            cost_tracker: CostTracker para registrar costes (F14, opcional).
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
        """Ejecuta el flujo plan → build.

        Args:
            prompt: Prompt original del usuario
            stream: Si True, usa streaming del LLM en la fase build
            on_stream_chunk: Callback opcional para chunks de streaming

        Returns:
            AgentState final (del agente build, o plan si plan falló)
        """
        self.log.info(
            "mixed_mode.start",
            prompt=prompt[:100] + "..." if len(prompt) > 100 else prompt,
        )

        # Fase 1: Ejecutar plan (sin streaming — plan es rápido y silencioso)
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

        # Si se recibió shutdown durante la fase plan, retornar inmediatamente
        if self.shutdown and self.shutdown.should_stop:
            self.log.warning("mixed_mode.shutdown_after_plan")
            return plan_state

        # Verificar resultado del plan
        if plan_state.status == "failed":
            self.log.error(
                "mixed_mode.plan_failed",
                error=plan_state.final_output,
            )
            return plan_state

        if not plan_state.final_output:
            self.log.warning("mixed_mode.plan_no_output")
            # Continuar de todos modos con plan vacío
            plan_output = "(El agente de planificación no produjo output)"
        else:
            plan_output = plan_state.final_output

        self.log.info(
            "mixed_mode.plan_complete",
            status=plan_state.status,
            plan_preview=plan_output[:200] + "..."
            if len(plan_output) > 200
            else plan_output,
        )

        # Fase 2: Ejecutar build con el plan como contexto
        self.log.info("mixed_mode.phase.build")

        # Construir prompt enriquecido con el plan
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

        # Ejecutar build (con streaming si está habilitado)
        build_state = build_loop.run(enriched_prompt, stream=stream, on_stream_chunk=on_stream_chunk)

        self.log.info(
            "mixed_mode.complete",
            final_status=build_state.status,
            total_steps=plan_state.current_step + build_state.current_step,
            total_tool_calls=plan_state.total_tool_calls + build_state.total_tool_calls,
        )

        # Retornar el estado de build
        # TODO: En el futuro, podríamos combinar ambos estados
        return build_state

    def _build_enriched_prompt(self, original_prompt: str, plan: str) -> str:
        """Construye un prompt enriquecido con el plan.

        Args:
            original_prompt: Prompt original del usuario
            plan: Plan generado por el agente plan

        Returns:
            Prompt enriquecido para el agente build
        """
        return f"""El usuario pidió:
{original_prompt}

Un agente de planificación analizó la tarea y generó este plan:

---
{plan}
---

Tu trabajo es ejecutar este plan paso a paso. Usa las herramientas disponibles
para completar la tarea según lo planificado. Si algo del plan no es claro o
necesita ajustes, usa tu criterio para adaptarlo."""
