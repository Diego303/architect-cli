"""
Human Log — Formatter y helper para logs de trazabilidad del agente.

v3-M5+M6: Produce output legible con iconos y estructura clara.
El usuario ve qué hace el agente paso a paso, sin ruido técnico.

Formato de ejemplo:
    ─── architect · build · gpt-4.1 ──────────────────

    🔄 Paso 1 → Llamada al LLM (3 mensajes)
       ✓ LLM respondió con 2 tool calls

       🔧 read_file → src/main.py
          ✓ OK (142 líneas)

       🔧 edit_file → src/main.py
          ✓ OK
          🔍 Hook python-lint: OK

    🔄 Paso 2 → Llamada al LLM (7 mensajes)
       ✓ LLM respondió con texto final

    ✅ Agente completado (2 pasos)
       Razón: LLM decidió que terminó
"""

import logging
import sys
from typing import Any

from .levels import HUMAN


class HumanFormatter:
    """Formateador de eventos de trazabilidad del agente.

    Convierte eventos estructurados a texto legible con formato consistente.
    Cada tipo de evento tiene su formato propio.
    """

    def format_event(self, event: str, **kw) -> str | None:
        """Formatea un evento a texto legible.

        Args:
            event: Nombre del evento (ej: "llm.call", "tool.call")
            **kw: Parámetros del evento

        Returns:
            Texto formateado o None si el evento no tiene formato definido
        """
        match event:

            # ── LLM ─────────────────────────────────────────────────────
            case "agent.step.start":
                # Suprimido — se imprime en agent.llm.call
                return None

            case "agent.llm.call":
                step = kw.get("step", "?")
                msgs = kw.get("messages_count", "?")
                return f"\n🔄 Paso {step + 1} → Llamada al LLM ({msgs} mensajes)"

            case "agent.llm.response":
                tool_count = kw.get("tool_calls", 0)
                if tool_count:
                    s = "s" if tool_count > 1 else ""
                    return f"   ✓ LLM respondió con {tool_count} tool call{s}"
                return "   ✓ LLM respondió con texto final"

            case "agent.complete":
                step = kw.get("step", "?")
                cost = kw.get("cost")
                cost_line = ""
                if cost:
                    cost_line = f"\n   Coste: {cost}"
                return f"\n✅ Agente completado ({step} pasos)\n   Razón: LLM decidió que terminó{cost_line}"

            # ── TOOLS ────────────────────────────────────────────────────
            case "agent.tool_call.execute":
                tool = kw.get("tool", "?")
                args = kw.get("args", {})
                summary = _summarize_args(tool, args)
                is_mcp = kw.get("is_mcp", False)
                if is_mcp:
                    server = kw.get("mcp_server", "")
                    return f"\n   🌐 {tool} → {summary}  (MCP: {server})"
                return f"\n   🔧 {tool} → {summary}"

            case "agent.tool_call.complete":
                tool = kw.get("tool", "?")
                success = kw.get("success", True)
                error = kw.get("error")
                if success:
                    return "      ✓ OK"
                return f"      ✗ ERROR: {error}"

            case "agent.hook.complete":
                hook = kw.get("hook", "")
                success = kw.get("success", True)
                detail = kw.get("detail", "")
                icon = "✓" if success else "⚠️"
                if hook:
                    line = f"      🔍 Hook {hook}: {icon}"
                    if detail:
                        line += f" {detail}"
                    return line
                return "      🔍 hooks ejecutados"

            # ── SAFETY NETS ──────────────────────────────────────────────
            case "safety.user_interrupt":
                return "\n⚠️  Interrumpido por el usuario"

            case "safety.max_steps":
                step = kw.get("step", "?")
                mx = kw.get("max_steps", "?")
                return f"\n⚠️  Límite de pasos alcanzado ({step}/{mx})\n    Pidiendo al agente que resuma..."

            case "safety.budget_exceeded" | "safety.budget":
                spent = kw.get("spent", kw.get("error", "?"))
                budget = kw.get("budget", "?")
                return f"\n⚠️  Presupuesto excedido (${spent}/{budget})\n    Pidiendo al agente que resuma..."

            case "safety.timeout":
                return "\n⚠️  Timeout alcanzado\n    Pidiendo al agente que resuma..."

            case "safety.context_full":
                return "\n⚠️  Contexto lleno\n    Pidiendo al agente que resuma..."

            # ── LLM ERRORS ──────────────────────────────────────────────
            case "agent.llm_error":
                error = kw.get("error", "desconocido")
                return f"\n❌ Error del LLM: {error}"

            case "agent.step_timeout":
                seconds = kw.get("seconds", "?")
                return f"\n⚠️  Step timeout ({seconds}s)\n    Pidiendo al agente que resuma..."

            # ── AGENT LIFECYCLE ──────────────────────────────────────────
            case "agent.closing":
                reason = kw.get("reason", "?")
                steps = kw.get("steps", "?")
                return f"\n🔄 Cerrando ({reason}, {steps} pasos completados)"

            case "agent.loop.complete":
                status = kw.get("status", "?")
                stop_reason = kw.get("stop_reason")
                steps = kw.get("total_steps", "?")
                tool_calls = kw.get("total_tool_calls", "?")
                cost = kw.get("cost")
                cost_line = ""
                if cost:
                    cost_line = f"\n   Coste: {cost}"
                if status == "success":
                    return f"  ({steps} pasos, {tool_calls} tool calls){cost_line}"
                else:
                    reason_str = f" — {stop_reason}" if stop_reason else ""
                    return f"\n⚡ Detenido ({status}{reason_str}, {steps} pasos){cost_line}"

            # ── PIPELINE ─────────────────────────────────────────────────
            case "pipeline.step_start":
                step = kw.get("step", "?")
                agent = kw.get("agent", "build")
                index = kw.get("index", "?")
                total = kw.get("total", "?")
                label = f" Pipeline step {index}/{total}: {step} (agent: {agent}) "
                bar = f"━{label:━<58}━"
                return f"\n{bar}"

            case "pipeline.step_skipped":
                step = kw.get("step", "?")
                return f"\n   ⏭️  Step '{step}' omitido (condición no cumplida)"

            case "pipeline.step_done":
                step = kw.get("step", "?")
                status = kw.get("status", "?")
                cost = kw.get("cost", 0)
                duration = kw.get("duration", 0)
                icon = "✓" if status == "success" else "✗"
                cost_str = f"${cost:.4f}" if cost else "$0"
                dur_str = f"{duration:.1f}s" if duration else "0s"
                return f"\n   {icon} Step '{step}' → {status} ({cost_str}, {dur_str})"

            # ── RALPH LOOP ──────────────────────────────────────────────
            case "ralph.iteration_start":
                iteration = kw.get("iteration", "?")
                max_iterations = kw.get("max_iterations", "?")
                check_cmd = kw.get("check_cmd", "")
                label = f" Ralph iteration {iteration}/{max_iterations}"
                if check_cmd:
                    label += f" (check: {check_cmd})"
                label += " "
                bar = f"━{label:━<58}━"
                return f"\n{bar}"

            case "ralph.checks_result":
                iteration = kw.get("iteration", "?")
                passed = kw.get("passed", 0)
                total = kw.get("total", 0)
                all_passed = kw.get("all_passed", False)
                check_icon = " ✓" if all_passed else ""
                return f"   🧪 Checks: {passed}/{total} passed{check_icon}"

            case "ralph.iteration_done":
                iteration = kw.get("iteration", "?")
                status = kw.get("status", "?")
                cost = kw.get("cost", 0)
                duration = kw.get("duration", 0)
                icon = "✓" if status in ("success", "passed") else "✗"
                cost_str = f"${cost:.4f}" if cost else "$0"
                dur_str = f"{duration:.1f}s" if duration else "0s"
                return f"   {icon} Iteration {iteration} → {status} ({cost_str}, {dur_str})"

            case "ralph.complete":
                total_iterations = kw.get("total_iterations", "?")
                status = kw.get("status", "?")
                total_cost = kw.get("total_cost", 0)
                cost_str = f"${total_cost:.4f}" if total_cost else "$0"
                icon = "✅" if status == "success" else "⚠️"
                return f"\n{icon} Ralph complete — {total_iterations} iterations, {status} ({cost_str})"

            # ── AUTO-REVIEWER ───────────────────────────────────────────
            case "reviewer.start":
                diff_lines = kw.get("diff_lines", "?")
                label = f" Auto-Review ({diff_lines} líneas de diff) "
                bar = f"━{label:━<58}━"
                return f"\n{bar}"

            case "reviewer.complete":
                approved = kw.get("approved", False)
                issues = kw.get("issues", 0)
                score = kw.get("score", "?")
                icon = "✓" if approved else "✗"
                status = "aprobado" if approved else "no aprobado"
                return f"   {icon} Review completo: {status}, {issues} issues, score {score}"

            # ── PARALLEL RUNS ───────────────────────────────────────────
            case "parallel.worker_done":
                worker = kw.get("worker", "?")
                model = kw.get("model", "?")
                status = kw.get("status", "?")
                cost = kw.get("cost", 0)
                duration = kw.get("duration", 0)
                icon = "✓" if status == "success" else "✗"
                cost_str = f"${cost:.4f}" if cost else "$0"
                dur_str = f"{duration:.1f}s" if duration else "0s"
                return f"   {icon} Worker {worker} ({model}) → {status} ({cost_str}, {dur_str})"

            case "parallel.worker_error":
                worker = kw.get("worker", "?")
                error = kw.get("error", "?")
                return f"   ✗ Worker {worker} → error: {error}"

            case "parallel.complete":
                total_workers = kw.get("total_workers", "?")
                succeeded = kw.get("succeeded", 0)
                failed = kw.get("failed", 0)
                total_cost = kw.get("total_cost", 0)
                cost_str = f"${total_cost:.4f}" if total_cost else "$0"
                return f"\n⚡ Parallel complete — {total_workers} workers: {succeeded} success, {failed} failed ({cost_str})"

            # ── COMPETITIVE EVAL ────────────────────────────────────────
            case "competitive.model_done":
                model = kw.get("model", "?")
                rank = kw.get("rank", "?")
                score = kw.get("score", 0)
                cost = kw.get("cost", 0)
                checks_passed = kw.get("checks_passed", 0)
                checks_total = kw.get("checks_total", 0)
                medals = {1: "🏆", 2: "🥈", 3: "🥉"}
                medal = medals.get(rank, f"#{rank}")
                cost_str = f"${cost:.4f}" if cost else "$0"
                return f"   {medal} {model}: #{rank} (score: {score}, {checks_passed}/{checks_total} checks, {cost_str})"

            case "competitive.ranking":
                ranking = kw.get("ranking", [])
                if not ranking:
                    return "\n🏁 Ranking final: (sin resultados)"
                names = [r.get("model", "?") for r in ranking]
                return f"\n🏁 Ranking final: {' > '.join(names)}"

            # ── CONTEXT ──────────────────────────────────────────────────
            case "context.compressing":
                exchanges = kw.get("tool_exchanges", "?")
                return f"   📦 Comprimiendo contexto — {exchanges} intercambios"

            case "context.window_enforced":
                removed = kw.get("removed_messages", "?")
                return f"   📦 Ventana de contexto: eliminados {removed} mensajes antiguos"

            case _:
                return None


class HumanLogHandler(logging.Handler):
    """Handler de logging que filtra eventos HUMAN y los formatea.

    Solo procesa registros de nivel HUMAN (25). El resto los ignora.
    Escribe a stderr para no romper pipes stdout.
    """

    def __init__(self, stream=None) -> None:
        super().__init__(level=HUMAN)
        self.stream = stream or sys.stderr
        self.formatter_inst = HumanFormatter()

    # Campos estándar de LogRecord (para fallback, extracción de record.__dict__)
    _RECORD_FIELDS = frozenset({
        "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName", "name", "event",
        "log_level", "logger", "logger_name", "timestamp",
    })

    # Campos añadidos por procesadores de structlog (para event dict de wrap_for_formatter)
    _STRUCTLOG_META = frozenset({
        "event", "level", "log_level", "logger", "logger_name", "timestamp",
    })

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Solo procesar eventos de nivel HUMAN exacto
            if record.levelno != HUMAN:
                return

            # Extraer event y kwargs del record.
            # wrap_for_formatter almacena el event dict completo en record.msg
            if isinstance(record.msg, dict) and not record.args:
                event_dict = record.msg
                event = event_dict.get("event", "")
                kw = {
                    k: v for k, v in event_dict.items()
                    if k not in self._STRUCTLOG_META
                }
            else:
                # Fallback: extraer de atributos del record
                event = getattr(record, "event", None) or record.getMessage()
                kw = {
                    k: v for k, v in record.__dict__.items()
                    if not k.startswith("_") and k not in self._RECORD_FIELDS
                }

            formatted = self.formatter_inst.format_event(event, **kw)
            if formatted is not None:
                self.stream.write(formatted + "\n")
                self.stream.flush()
        except Exception:
            self.handleError(record)


class HumanLog:
    """Helper tipado para emitir logs de nivel HUMAN desde el código.

    En lugar de llamar log.log(HUMAN, "event", ...) directamente,
    usa métodos con nombres semánticos claros.

    Uso:
        hlog = HumanLog(structlog.get_logger())
        hlog.llm_call(step=0, messages_count=2)
        hlog.tool_call("read_file", {"path": "main.py"})
    """

    def __init__(self, logger) -> None:
        self._log = logger

    def llm_call(self, step: int, messages_count: int) -> None:
        self._log.log(HUMAN, "agent.llm.call", step=step, messages_count=messages_count)

    def llm_response(self, tool_calls: int = 0) -> None:
        self._log.log(HUMAN, "agent.llm.response", tool_calls=tool_calls)

    def tool_call(
        self,
        name: str,
        args: dict,
        is_mcp: bool = False,
        mcp_server: str = "",
    ) -> None:
        self._log.log(
            HUMAN, "agent.tool_call.execute",
            tool=name, args=args, is_mcp=is_mcp, mcp_server=mcp_server,
        )

    def tool_result(self, name: str, success: bool, error: str | None = None) -> None:
        self._log.log(HUMAN, "agent.tool_call.complete", tool=name, success=success, error=error)

    def hook_complete(
        self,
        name: str,
        hook: str = "",
        success: bool = True,
        detail: str = "",
    ) -> None:
        self._log.log(
            HUMAN, "agent.hook.complete",
            tool=name, hook=hook, success=success, detail=detail,
        )

    def agent_done(self, step: int, cost: str | None = None) -> None:
        self._log.log(HUMAN, "agent.complete", step=step, cost=cost)

    def safety_net(self, reason: str, **kw) -> None:
        self._log.log(HUMAN, f"safety.{reason}", **kw)

    def closing(self, reason: str, steps: int) -> None:
        self._log.log(HUMAN, "agent.closing", reason=reason, steps=steps)

    def llm_error(self, error: str) -> None:
        self._log.log(HUMAN, "agent.llm_error", error=error)

    def step_timeout(self, seconds: int) -> None:
        self._log.log(HUMAN, "agent.step_timeout", seconds=seconds)

    def loop_complete(self, status: str, stop_reason: str | None, total_steps: int, total_tool_calls: int) -> None:
        self._log.log(
            HUMAN, "agent.loop.complete",
            status=status,
            stop_reason=stop_reason,
            total_steps=total_steps,
            total_tool_calls=total_tool_calls,
        )

    def pipeline_step_start(self, step: str, agent: str, index: int, total: int) -> None:
        self._log.log(
            HUMAN, "pipeline.step_start",
            step=step, agent=agent, index=index, total=total,
        )

    def pipeline_step_skipped(self, step: str) -> None:
        self._log.log(HUMAN, "pipeline.step_skipped", step=step)

    def pipeline_step_done(self, step: str, status: str, cost: float, duration: float) -> None:
        self._log.log(
            HUMAN, "pipeline.step_done",
            step=step, status=status, cost=cost, duration=duration,
        )

    # ── Ralph Loop ──────────────────────────────────────────────

    def ralph_iteration_start(self, iteration: int, max_iterations: int, check_cmd: str = "") -> None:
        self._log.log(
            HUMAN, "ralph.iteration_start",
            iteration=iteration, max_iterations=max_iterations, check_cmd=check_cmd,
        )

    def ralph_checks_result(self, iteration: int, passed: int, total: int, all_passed: bool) -> None:
        self._log.log(
            HUMAN, "ralph.checks_result",
            iteration=iteration, passed=passed, total=total, all_passed=all_passed,
        )

    def ralph_iteration_done(self, iteration: int, status: str, cost: float, duration: float) -> None:
        self._log.log(
            HUMAN, "ralph.iteration_done",
            iteration=iteration, status=status, cost=cost, duration=duration,
        )

    def ralph_complete(self, total_iterations: int, status: str, total_cost: float) -> None:
        self._log.log(
            HUMAN, "ralph.complete",
            total_iterations=total_iterations, status=status, total_cost=total_cost,
        )

    # ── Auto-Reviewer ───────────────────────────────────────────

    def reviewer_start(self, diff_lines: int) -> None:
        self._log.log(HUMAN, "reviewer.start", diff_lines=diff_lines)

    def reviewer_complete(self, approved: bool, issues: int, score: str = "N/A") -> None:
        self._log.log(
            HUMAN, "reviewer.complete",
            approved=approved, issues=issues, score=score,
        )

    # ── Parallel Runs ───────────────────────────────────────────

    def parallel_worker_done(self, worker: int, model: str, status: str, cost: float, duration: float) -> None:
        self._log.log(
            HUMAN, "parallel.worker_done",
            worker=worker, model=model, status=status, cost=cost, duration=duration,
        )

    def parallel_worker_error(self, worker: int, error: str) -> None:
        self._log.log(HUMAN, "parallel.worker_error", worker=worker, error=error)

    def parallel_complete(self, total_workers: int, succeeded: int, failed: int, total_cost: float) -> None:
        self._log.log(
            HUMAN, "parallel.complete",
            total_workers=total_workers, succeeded=succeeded, failed=failed, total_cost=total_cost,
        )

    # ── Competitive Eval ────────────────────────────────────────

    def competitive_model_done(
        self, model: str, rank: int, score: float, cost: float, checks_passed: int, checks_total: int,
    ) -> None:
        self._log.log(
            HUMAN, "competitive.model_done",
            model=model, rank=rank, score=score, cost=cost,
            checks_passed=checks_passed, checks_total=checks_total,
        )

    def competitive_ranking(self, ranking: list[dict[str, Any]]) -> None:
        self._log.log(HUMAN, "competitive.ranking", ranking=ranking)


def _summarize_args(tool_name: str, args: dict) -> str:
    """Resume los argumentos de una tool para logs human legibles (v3-M6).

    Cada tool tiene su resumen óptimo para que el usuario entienda
    qué está haciendo el agente de un vistazo.

    Args:
        tool_name: Nombre del tool
        args: Argumentos del tool

    Returns:
        String resumen (ej: "src/main.py", '"def foo" en src/')
    """
    match tool_name:
        case "read_file" | "delete_file":
            return str(args.get("path", "?"))

        case "write_file":
            path = args.get("path", "?")
            content = str(args.get("content", ""))
            lines = content.count("\n") + 1
            return f"{path} ({lines} líneas)"

        case "edit_file":
            path = args.get("path", "?")
            old = str(args.get("old_str", args.get("old_content", "")))
            new = str(args.get("new_str", args.get("new_content", "")))
            return f"{path} ({len(old.splitlines())}→{len(new.splitlines())} líneas)"

        case "apply_patch":
            path = args.get("path", "?")
            patch = str(args.get("patch", ""))
            added = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
            return f"{path} (+{added} -{removed})"

        case "search_code":
            pattern = args.get("pattern", "?")
            path = args.get("path", args.get("file_pattern", "."))
            short_pattern = pattern[:40] + "..." if len(str(pattern)) > 40 else pattern
            return f'"{short_pattern}" en {path}'

        case "grep":
            text = args.get("text", args.get("pattern", "?"))
            path = args.get("path", args.get("file_pattern", "."))
            short_text = str(text)[:40] + "..." if len(str(text)) > 40 else text
            return f'"{short_text}" en {path}'

        case "list_files" | "find_files":
            return str(args.get("path", args.get("pattern", ".")))

        case "run_command":
            cmd = str(args.get("command", "?"))
            return cmd[:60] + "..." if len(cmd) > 60 else cmd

        case _:
            # MCP u otra tool: mostrar primer arg o resumen genérico
            if args:
                first_val = next(iter(args.values()), "")
                val_str = str(first_val)
                return val_str[:60] + "..." if len(val_str) > 60 else val_str
            return "(sin args)"
