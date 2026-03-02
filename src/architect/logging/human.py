"""
Human Log — Formatter and helper for agent traceability logs.

v3-M5+M6: Produces readable output with icons and clear structure.
The user sees what the agent does step by step, without technical noise.

Example format:
    ─── architect · build · gpt-4.1 ──────────────────

    🔄 Step 1 → LLM call (3 messages)
       ✓ LLM responded with 2 tool calls

       🔧 read_file → src/main.py
          ✓ OK

       🔧 edit_file → src/main.py
          ✓ OK
          🔍 Hook python-lint: OK

    🔄 Step 2 → LLM call (7 messages)
       ✓ LLM responded with final text

    ✅ Agent complete (2 steps)
       Reason: LLM decided it was done
"""

import logging
import sys
from typing import Any

from .levels import HUMAN


class HumanFormatter:
    """Formatter for agent traceability events.

    Converts structured events to readable text with consistent formatting.
    Each event type has its own format. All user-facing strings resolve
    via i18n at render time.
    """

    def format_event(self, event: str, **kw) -> str | None:
        """Format an event to readable text.

        Args:
            event: Event name (e.g. "llm.call", "tool.call")
            **kw: Event parameters

        Returns:
            Formatted text or None if the event has no defined format
        """
        from architect.i18n import t

        match event:

            # ── LLM ─────────────────────────────────────────────────────
            case "agent.step.start":
                return None

            case "agent.llm.call":
                step = kw.get("step", "?")
                msgs = kw.get("messages_count", "?")
                return t("human.llm_call", step=step + 1, messages=msgs)

            case "agent.llm.response":
                tool_count = kw.get("tool_calls", 0)
                if tool_count:
                    s = "s" if tool_count > 1 else ""
                    return t("human.llm_response_tools", count=tool_count, s=s)
                return t("human.llm_response_text")

            case "agent.complete":
                step = kw.get("step", "?")
                cost = kw.get("cost")
                cost_line = ""
                if cost:
                    cost_line = t("human.cost_line", cost=cost)
                return t("human.agent_complete", steps=step, cost_line=cost_line)

            # ── TOOLS ────────────────────────────────────────────────────
            case "agent.tool_call.execute":
                tool = kw.get("tool", "?")
                args = kw.get("args", {})
                summary = _summarize_args(tool, args)
                is_mcp = kw.get("is_mcp", False)
                if is_mcp:
                    server = kw.get("mcp_server", "")
                    return t("human.tool_call_mcp", tool=tool, summary=summary, server=server)
                return t("human.tool_call", tool=tool, summary=summary)

            case "agent.tool_call.complete":
                tool = kw.get("tool", "?")
                success = kw.get("success", True)
                error = kw.get("error")
                if success:
                    return t("human.tool_ok")
                return t("human.tool_error", error=error)

            case "agent.hook.complete":
                hook = kw.get("hook", "")
                success = kw.get("success", True)
                detail = kw.get("detail", "")
                icon = "✓" if success else "⚠️"
                if hook:
                    line = t("human.hook_complete", hook=hook, icon=icon)
                    if detail:
                        line += f" {detail}"
                    return line
                return t("human.hooks_executed")

            # ── SAFETY NETS ──────────────────────────────────────────────
            case "safety.user_interrupt":
                return t("human.user_interrupt")

            case "safety.max_steps":
                step = kw.get("step", "?")
                mx = kw.get("max_steps", "?")
                return t("human.max_steps", step=step, max_steps=mx)

            case "safety.budget_exceeded" | "safety.budget":
                spent = kw.get("spent", kw.get("error", "?"))
                budget = kw.get("budget", "?")
                return t("human.budget_exceeded", spent=spent, budget=budget)

            case "safety.timeout":
                return t("human.timeout")

            case "safety.context_full":
                return t("human.context_full")

            # ── LLM ERRORS ──────────────────────────────────────────────
            case "agent.llm_error":
                error = kw.get("error", "unknown")
                return t("human.llm_error", error=error)

            case "agent.step_timeout":
                seconds = kw.get("seconds", "?")
                return t("human.step_timeout", seconds=seconds)

            # ── AGENT LIFECYCLE ──────────────────────────────────────────
            case "agent.closing":
                reason = kw.get("reason", "?")
                steps = kw.get("steps", "?")
                return t("human.closing", reason=reason, steps=steps)

            case "agent.loop.complete":
                status = kw.get("status", "?")
                stop_reason = kw.get("stop_reason")
                steps = kw.get("total_steps", "?")
                tool_calls = kw.get("total_tool_calls", "?")
                cost = kw.get("cost")
                cost_line = ""
                if cost:
                    cost_line = t("human.cost_line", cost=cost)
                if status == "success":
                    return t("human.loop_complete_success", steps=steps, tool_calls=tool_calls, cost_line=cost_line)
                else:
                    reason_str = f" — {stop_reason}" if stop_reason else ""
                    return t("human.loop_complete_stopped", status=status, reason_str=reason_str, steps=steps, cost_line=cost_line)

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
                return t("human.pipeline_step_skipped", step=step)

            case "pipeline.step_done":
                step = kw.get("step", "?")
                status = kw.get("status", "?")
                cost = kw.get("cost", 0)
                duration = kw.get("duration", 0)
                icon = "✓" if status == "success" else "✗"
                cost_str = f"${cost:.4f}" if cost else "$0"
                dur_str = f"{duration:.1f}s" if duration else "0s"
                return t("human.pipeline_step_done", icon=icon, step=step, status=status, cost_str=cost_str, dur_str=dur_str)

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
                return t("human.ralph_checks", passed=passed, total=total, check_icon=check_icon)

            case "ralph.iteration_done":
                iteration = kw.get("iteration", "?")
                status = kw.get("status", "?")
                cost = kw.get("cost", 0)
                duration = kw.get("duration", 0)
                icon = "✓" if status in ("success", "passed") else "✗"
                cost_str = f"${cost:.4f}" if cost else "$0"
                dur_str = f"{duration:.1f}s" if duration else "0s"
                return t("human.ralph_iteration_done", icon=icon, iteration=iteration, status=status, cost_str=cost_str, dur_str=dur_str)

            case "ralph.complete":
                total_iterations = kw.get("total_iterations", "?")
                status = kw.get("status", "?")
                total_cost = kw.get("total_cost", 0)
                cost_str = f"${total_cost:.4f}" if total_cost else "$0"
                icon = "✅" if status == "success" else "⚠️"
                return t("human.ralph_complete", icon=icon, total_iterations=total_iterations, status=status, cost_str=cost_str)

            # ── AUTO-REVIEWER ───────────────────────────────────────────
            case "reviewer.start":
                diff_lines = kw.get("diff_lines", "?")
                label = t("human.reviewer_start_label", diff_lines=diff_lines)
                bar = f"━{label:━<58}━"
                return f"\n{bar}"

            case "reviewer.complete":
                approved = kw.get("approved", False)
                issues = kw.get("issues", 0)
                score = kw.get("score", "?")
                icon = "✓" if approved else "✗"
                status = t("human.reviewer_status_approved") if approved else t("human.reviewer_status_rejected")
                return t("human.reviewer_complete", icon=icon, status=status, issues=issues, score=score)

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
                return t("human.parallel_worker_done", icon=icon, worker=worker, model=model, status=status, cost_str=cost_str, dur_str=dur_str)

            case "parallel.worker_error":
                worker = kw.get("worker", "?")
                error = kw.get("error", "?")
                return t("human.parallel_worker_error", worker=worker, error=error)

            case "parallel.complete":
                total_workers = kw.get("total_workers", "?")
                succeeded = kw.get("succeeded", 0)
                failed = kw.get("failed", 0)
                total_cost = kw.get("total_cost", 0)
                cost_str = f"${total_cost:.4f}" if total_cost else "$0"
                return t("human.parallel_complete", total_workers=total_workers, succeeded=succeeded, failed=failed, cost_str=cost_str)

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
                    return t("human.competitive_ranking_empty")
                names = [r.get("model", "?") for r in ranking]
                return t("human.competitive_ranking", ranking=" > ".join(names))

            # ── CONTEXT ──────────────────────────────────────────────────
            case "context.compressing":
                exchanges = kw.get("tool_exchanges", "?")
                return t("human.context_compressing", exchanges=exchanges)

            case "context.window_enforced":
                removed = kw.get("removed_messages", "?")
                return t("human.context_window_enforced", removed=removed)

            case _:
                return None


class HumanLogHandler(logging.Handler):
    """Logging handler that filters HUMAN events and formats them.

    Only processes records at HUMAN level (25). Ignores everything else.
    Writes to stderr so it doesn't break stdout pipes.
    """

    def __init__(self, stream=None) -> None:
        super().__init__(level=HUMAN)
        self.stream = stream or sys.stderr
        self.formatter_inst = HumanFormatter()

    _RECORD_FIELDS = frozenset({
        "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName", "name", "event",
        "log_level", "logger", "logger_name", "timestamp",
    })

    _STRUCTLOG_META = frozenset({
        "event", "level", "log_level", "logger", "logger_name", "timestamp",
    })

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno != HUMAN:
                return

            if isinstance(record.msg, dict) and not record.args:
                event_dict = record.msg
                event = event_dict.get("event", "")
                kw = {
                    k: v for k, v in event_dict.items()
                    if k not in self._STRUCTLOG_META
                }
            else:
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
    """Typed helper for emitting HUMAN-level logs from code.

    Instead of calling log.log(HUMAN, "event", ...) directly,
    use methods with clear semantic names.

    Usage:
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
    """Summarize tool arguments for human-readable logs.

    Each tool has an optimal summary so the user understands
    what the agent is doing at a glance.

    Args:
        tool_name: Tool name
        args: Tool arguments

    Returns:
        Summary string (e.g. "src/main.py", '"def foo" in src/')
    """
    from architect.i18n import t

    match tool_name:
        case "read_file" | "delete_file":
            return str(args.get("path", "?"))

        case "write_file":
            path = args.get("path", "?")
            content = str(args.get("content", ""))
            lines = content.count("\n") + 1
            return t("human.summary_lines", path=path, lines=lines)

        case "edit_file":
            path = args.get("path", "?")
            old = str(args.get("old_str", args.get("old_content", "")))
            new = str(args.get("new_str", args.get("new_content", "")))
            return t("human.summary_edit", path=path, old=len(old.splitlines()), new=len(new.splitlines()))

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
            return t("human.summary_search", pattern=short_pattern, path=path)

        case "grep":
            text = args.get("text", args.get("pattern", "?"))
            path = args.get("path", args.get("file_pattern", "."))
            short_text = str(text)[:40] + "..." if len(str(text)) > 40 else text
            return t("human.summary_search", pattern=short_text, path=path)

        case "list_files" | "find_files":
            return str(args.get("path", args.get("pattern", ".")))

        case "run_command":
            cmd = str(args.get("command", "?"))
            return cmd[:60] + "..." if len(cmd) > 60 else cmd

        case _:
            if args:
                first_val = next(iter(args.values()), "")
                val_str = str(first_val)
                return val_str[:60] + "..." if len(val_str) > 60 else val_str
            return t("human.summary_no_args")
