"""
Agent Loop - Ciclo principal de ejecución del agente.

v3: Rediseñado con while True — el LLM decide cuándo parar.
Los safety nets (max_steps, budget, timeout, context) son watchdogs
que, al dispararse, piden un cierre limpio al LLM en lugar de cortar.

v4-A1: Integración con el sistema de hooks completo.

Invariantes:
- El LLM termina cuando no solicita más tool calls (StopReason.LLM_DONE)
- Los watchdogs inyectan instrucción de cierre → última llamada al LLM
- USER_INTERRUPT es el único caso que NO llama al LLM (corte inmediato)
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

# Instrucciones de cierre para cada watchdog
_CLOSE_INSTRUCTIONS: dict[StopReason, str] = {
    StopReason.MAX_STEPS: (
        "Has alcanzado el límite máximo de pasos permitidos. "
        "Responde con un resumen de lo que completaste, qué queda pendiente "
        "y sugerencias para continuar en otra sesión."
    ),
    StopReason.BUDGET_EXCEEDED: (
        "Se ha alcanzado el presupuesto máximo de coste. "
        "Resume brevemente lo que completaste y qué falta por hacer."
    ),
    StopReason.CONTEXT_FULL: (
        "El contexto de conversación está lleno. "
        "Resume brevemente lo que completaste y qué falta por hacer."
    ),
    StopReason.TIMEOUT: (
        "Se agotó el tiempo asignado para esta ejecución. "
        "Resume brevemente lo que completaste y qué falta por hacer."
    ),
}


class AgentLoop:
    """Loop principal del agente (v3: while True).

    El LLM trabaja hasta que decide que terminó (no pide más tools).
    Los safety nets son watchdogs que comprueban condiciones antes de
    cada llamada al LLM. Si se disparan, piden un cierre limpio.

    Flujo por iteración:
    1. Comprobar safety nets → si saltan, _graceful_close() y terminar
    2. Gestionar contexto (comprimir si es necesario)
    3. Pre-LLM hooks (v4-A1)
    4. Llamar al LLM
    5. Post-LLM hooks (v4-A1)
    6. Si no hay tool_calls → agent_complete hooks → quality gates → salir
    7. Pre/post-tool hooks dentro de execute_tool_call
    8. Añadir resultados al contexto y repetir
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
        """Inicializa el agent loop.

        Args:
            llm: LLMAdapter configurado
            engine: ExecutionEngine configurado
            agent_config: Configuración del agente
            context_builder: ContextBuilder para mensajes
            shutdown: GracefulShutdown para detectar interrupciones
            step_timeout: Segundos máximos por step individual (SIGALRM). 0 = sin límite.
            context_manager: ContextManager para pruning del contexto
            cost_tracker: CostTracker para registrar costes
            timeout: Segundos máximos totales de ejecución. None = sin límite.
            hook_executor: HookExecutor para hooks del lifecycle (v4-A1)
            guardrails: GuardrailsEngine para seguridad determinista (v4-A2)
            skills_loader: SkillsLoader para contexto de proyecto y skills (v4-A3)
            memory: ProceduralMemory para persistir correcciones (v4-A4)
            session_manager: SessionManager para persistir sesiones (v4-B1)
            session_id: ID de sesión para resume. None genera uno nuevo.
            dry_run_tracker: DryRunTracker para registrar acciones en modo dry-run (v4-B4)
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
        """Ejecuta el agent loop completo.

        Args:
            prompt: Prompt inicial del usuario
            stream: Si True, usa streaming del LLM
            on_stream_chunk: Callback opcional para chunks de streaming

        Returns:
            AgentState final con el resultado de la ejecución
        """
        self._start_time = time.time()

        # v4-B1: Generar session_id si no se proporcionó
        if not self.session_id and self.session_manager:
            from ..features.sessions import generate_session_id
            self.session_id = generate_session_id()

        # Inicializar estado
        state = AgentState()
        state.messages = self.ctx.build_initial(self.agent_config, prompt)
        state.model = self.llm.config.model
        state.cost_tracker = self.cost_tracker

        # v4-A3: Inyectar contexto de skills en el system prompt
        if self.skills_loader:
            skills_context = self.skills_loader.build_system_context()
            if skills_context and state.messages and state.messages[0]["role"] == "system":
                state.messages[0]["content"] += "\n\n" + skills_context

        # v4-A4: Inyectar memoria procedural en el system prompt
        if self.memory:
            memory_context = self.memory.get_context()
            if memory_context and state.messages and state.messages[0]["role"] == "system":
                state.messages[0]["content"] += "\n\n" + memory_context

        # Obtener schemas de tools permitidas
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

        # ── Loop principal: el LLM decide cuándo terminar ────────────────
        try:
            while True:

                # ── SAFETY NETS (antes de cada llamada al LLM) ────────────────
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

                # Inyectar contexto pendiente de hooks (si hay)
                if self._pending_context:
                    for ctx_text in self._pending_context:
                        state.messages.append({
                            "role": "user",
                            "content": f"[Contexto de hook]: {ctx_text}",
                        })
                    self._pending_context.clear()

                # ── LLAMADA AL LLM ────────────────────────────────────────────
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
                                raise RuntimeError("Streaming completó sin retornar respuesta final")
                        else:
                            response = self.llm.completion(
                                messages=state.messages,
                                tools=tools_schema if tools_schema else None,
                            )

                except StepTimeoutError:
                    self.log.error("agent.step_timeout", step=step, seconds=self.step_timeout)
                    self.hlog.step_timeout(self.step_timeout)
                    # Tratar timeout de step como timeout total
                    return self._graceful_close(state, StopReason.TIMEOUT, tools_schema)

                except Exception as e:
                    self.log.error("agent.llm_error", error=str(e), step=step)
                    self.hlog.llm_error(str(e))
                    state.status = "failed"
                    state.stop_reason = StopReason.LLM_ERROR
                    state.final_output = f"Error irrecuperable del LLM: {e}"
                    return state

                # ── REGISTRAR COSTE ───────────────────────────────────────────
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
                        # El presupuesto se superó en este step — cierre limpio
                        return self._graceful_close(state, StopReason.BUDGET_EXCEEDED, tools_schema)

                # ── POST-LLM HOOKS (v4-A1) ─────────────────────────────────
                self._run_hooks_safe("post_llm_call", {
                    "step": str(step),
                    "has_tool_calls": str(bool(response.tool_calls)),
                })

                step += 1

                # ── EL LLM DECIDIÓ TERMINAR (no pidió tools) ──────────────────
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
                            feedback = "Quality gates obligatorios no superados:\n"
                            for g in failed_required:
                                feedback += f"  - {g['name']}: {g['output'][:200]}\n"
                            feedback += "\nCorrige estos problemas antes de poder completar la tarea."
                            state.messages.append({"role": "user", "content": feedback})
                            self.log.info(
                                "guardrail.quality_gates_failed",
                                failed=[g["name"] for g in failed_required],
                            )
                            continue  # Vuelve al while True

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

                    # v4-B1: Guardar sesión final
                    self._save_session(state, prompt, step)
                    break

                # ── EL LLM PIDIÓ TOOLS → EJECUTAR ────────────────────────────
                self.hlog.llm_response(tool_calls=len(response.tool_calls))
                self.log.info(
                    "agent.tool_calls_received",
                    step=step,
                    count=len(response.tool_calls),
                    tools=[tc.name for tc in response.tool_calls],
                )

                # Ejecutar tool calls (paralelo o secuencial)
                tool_results = self._execute_tool_calls_batch(response.tool_calls, step)

                # Actualizar mensajes con tool results
                state.messages = self.ctx.append_tool_results(
                    state.messages, response.tool_calls, tool_results
                )

                # Registrar step
                state.steps.append(StepResult(
                    step_number=step,
                    llm_response=response,
                    tool_calls_made=tool_results,
                ))

                # v4-B1: Registrar archivos tocados para la sesión
                for tc in tool_results:
                    if tc.tool_name in ("write_file", "edit_file", "apply_patch", "delete_file"):
                        path = tc.args.get("path", "")
                        if path:
                            self._files_touched.add(path)

                # v4-B1: Guardar sesión después de cada step
                self._save_session(state, prompt, step)

        finally:
            # ── SESSION END HOOK (v4-A1) — siempre se ejecuta ─────────────
            self._run_hooks_safe("session_end", {
                "steps": str(step),
                "status": state.status,
                "cost": str(self.cost_tracker.total_cost_usd if self.cost_tracker else 0),
            })

        # ── Log final ─────────────────────────────────────────────────────
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
        """Ejecuta hooks para un evento de forma segura (sin romper el loop).

        Args:
            event_name: Nombre del evento (debe coincidir con HookEvent value).
            context: Diccionario de contexto para el hook.
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
            # Recoger contexto adicional para inyectar en el siguiente mensaje
            for result in results:
                if result.additional_context:
                    self._pending_context.append(result.additional_context)
        except Exception as e:
            self.log.warning("hooks.lifecycle_error", event=event_name, error=str(e))

    # ── SESSION PERSISTENCE (v4-B1) ──────────────────────────────────────

    def _save_session(self, state: AgentState, task: str, step: int) -> None:
        """Guarda el estado de la sesión actual a disco (si está configurado).

        Args:
            state: Estado actual del agente.
            task: Prompt/tarea original.
            step: Número de step actual.
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
                messages=state.messages[-30:],  # Últimos 30 para no explotar
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
        """Comprueba todas las condiciones de seguridad antes de cada step.

        Retorna None si todo está bien, o el StopReason si hay que parar.
        El orden importa: USER_INTERRUPT primero (más urgente).
        """
        # 1. User interrupt (Ctrl+C / SIGTERM) — corte inmediato
        if self.shutdown and self.shutdown.should_stop:
            self.log.warning("safety.user_interrupt", step=step)
            self.hlog.safety_net("user_interrupt", step=step)
            return StopReason.USER_INTERRUPT

        # 2. Max steps — watchdog de pasos
        if step >= self.agent_config.max_steps:
            self.log.warning(
                "safety.max_steps",
                step=step,
                max_steps=self.agent_config.max_steps,
            )
            self.hlog.safety_net("max_steps", step=step, max_steps=self.agent_config.max_steps)
            return StopReason.MAX_STEPS

        # 3. Timeout total — watchdog de tiempo
        if self.timeout and (time.time() - self._start_time) > self.timeout:
            self.log.warning("safety.timeout", elapsed=time.time() - self._start_time)
            self.hlog.safety_net("timeout")
            return StopReason.TIMEOUT

        # 4. Context window críticamente lleno (incluso después de comprimir)
        if self.context_manager and self.context_manager.is_critically_full(state.messages):
            self.log.warning("safety.context_full", step=step)
            self.hlog.safety_net("context_full", step=step)
            return StopReason.CONTEXT_FULL

        return None

    # ── CIERRE LIMPIO ────────────────────────────────────────────────────

    def _graceful_close(
        self,
        state: AgentState,
        reason: StopReason,
        tools_schema: list | None,
    ) -> AgentState:
        """Cierre limpio cuando salta un watchdog.

        En lugar de cortar abruptamente, le da al LLM una última oportunidad
        de resumir qué hizo y qué queda pendiente.
        USER_INTERRUPT es la excepción: no se llama al LLM.
        """
        self.log.info("agent.closing", reason=reason.value, steps=len(state.steps))
        self.hlog.closing(reason.value, len(state.steps))

        state.stop_reason = reason

        # USER_INTERRUPT: corte inmediato, sin llamar al LLM
        if reason == StopReason.USER_INTERRUPT:
            state.status = "partial"
            state.final_output = (
                f"Interrumpido por el usuario. "
                f"Pasos completados: {state.current_step}."
            )
            return state

        # Para todos los demás watchdogs: pedir resumen al LLM
        instruction = _CLOSE_INSTRUCTIONS.get(reason)
        if instruction:
            state.messages.append({
                "role": "user",
                "content": f"[SISTEMA] {instruction}",
            })

            try:
                # Última llamada SIN tools — solo texto de cierre
                close_response = self.llm.completion(
                    messages=state.messages,
                    tools=None,
                )
                state.final_output = close_response.content
            except Exception as e:
                self.log.warning("agent.close_response_failed", error=str(e))
                state.final_output = (
                    f"El agente se detuvo ({reason.value}). "
                    f"Pasos completados: {state.current_step}."
                )

        state.status = "partial"

        # v4-B1: Guardar sesión con estado parcial
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

    # ── EJECUCIÓN DE TOOL CALLS ──────────────────────────────────────────

    def _execute_tool_calls_batch(
        self,
        tool_calls: list,
        step: int,
    ) -> list[ToolCallResult]:
        """Ejecuta un lote de tool calls, paralelizando si es seguro.

        La paralelización solo se activa cuando:
        - Hay más de una tool call
        - parallel_tools=True en la configuración
        - El modo de confirmación es yolo
        - O confirm-sensitive y ninguna tool es sensible
        """
        if not tool_calls:
            return []

        if len(tool_calls) == 1:
            return [self._execute_single_tool(tool_calls[0], step)]

        if not self._should_parallelize(tool_calls):
            return [self._execute_single_tool(tc, step) for tc in tool_calls]

        # Ejecución paralela preservando orden original
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
        """Ejecuta una sola tool call y retorna el resultado.

        v4-A1: Ejecuta pre-hooks antes del tool y post-hooks después.
        Los pre-hooks pueden bloquear o modificar el input.
        Los post-hooks pueden añadir contexto adicional al resultado.
        """
        tool_name: str = tc.name  # type: ignore[attr-defined]
        tool_args: dict[str, Any] = tc.arguments  # type: ignore[attr-defined]

        self.log.info(
            "agent.tool_call.execute",
            step=step,
            tool=tool_name,
            args=self._sanitize_args_for_log(tool_args),
        )
        # Detectar si es MCP tool para logging diferenciado
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

        # ── PRE-TOOL HOOKS (v4-A1) ─────────────────────────────────────
        pre_result = self.engine.run_pre_tool_hooks(tool_name, tool_args)
        from ..tools.base import ToolResult
        if isinstance(pre_result, ToolResult):
            # Hook bloqueó la acción
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
            # Hook modificó el input
            tool_args = pre_result

        # ── EJECUTAR TOOL ────────────────────────────────────────────────
        result = self.engine.execute_tool_call(tool_name, tool_args)

        # ── DRY-RUN TRACKER (v4-B4) ─────────────────────────────────────
        if self.dry_run_tracker:
            self.dry_run_tracker.record(step, tool_name, tool_args)

        # ── POST-EXECUTION CODE RULES (v4-A2) ──────────────────────────
        code_rule_messages = self.engine.check_code_rules(tool_name, tool_args)
        if code_rule_messages:
            block_msgs = [m for m in code_rule_messages if m.startswith("BLOQUEADO")]
            if block_msgs:
                from ..tools.base import ToolResult as TR
                result = TR(
                    success=False,
                    output="\n".join(block_msgs),
                    error="Code rule violation",
                )

        # ── POST-TOOL HOOKS (v4-A1) ────────────────────────────────────
        hook_output = self.engine.run_post_tool_hooks(
            tool_name, tool_args, result.output or "", result.success
        )

        # Si hay output de hooks, añadirlo al resultado del tool
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
        """Determina si las tool calls se pueden ejecutar en paralelo."""
        # Respetar configuración explícita
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
        """Sanitiza argumentos para logging (truncar valores largos)."""
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + f"... ({len(value)} chars)"
            else:
                sanitized[key] = value
        return sanitized
