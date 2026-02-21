"""
Human Log — Formatter y helper para logs de trazabilidad del agente.

v3-M5+M6: Produce output legible con iconos y estructura clara.
El usuario ve qué hace el agente paso a paso, sin ruido técnico.

Formato de ejemplo:
    ─── architect · build · gpt-4.1 ──────────────────

    Paso 1 → LLM (2 mensajes)
      tool read_file → src/main.py
        OK (142 líneas)
      tool edit_file → src/main.py
        OK
        [Hook python-lint: OK]

    Paso 2 → LLM (7 mensajes)
      LLM terminó sin tools

    ✓ Completado (2 pasos)
"""

import logging
import sys

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
                step = kw.get("step", "?")
                # No imprimir "Paso 0" antes del primer step visible
                return None  # Se imprime en llm.call

            case "agent.llm.call":
                step = kw.get("step", "?")
                msgs = kw.get("messages_count", "?")
                return f"\nPaso {step + 1} → LLM ({msgs} mensajes)"

            case "agent.complete":
                step = kw.get("step", "?")
                return f"\n✓ Completado ({step} pasos)"

            # ── TOOLS ────────────────────────────────────────────────────
            case "agent.tool_call.execute":
                tool = kw.get("tool", "?")
                args = kw.get("args", {})
                summary = _summarize_args(tool, args)
                return f"  tool {tool} → {summary}"

            case "agent.tool_call.complete":
                tool = kw.get("tool", "?")
                success = kw.get("success", True)
                error = kw.get("error")
                if success:
                    return "    OK"
                return f"    ERROR: {error}"

            case "agent.hook.complete":
                return "    [hooks ejecutados]"

            # ── SAFETY NETS ──────────────────────────────────────────────
            case "safety.user_interrupt":
                return "\n⚠  Interrumpido por el usuario"

            case "safety.max_steps":
                step = kw.get("step", "?")
                mx = kw.get("max_steps", "?")
                return f"\n⚠  Límite de pasos alcanzado ({step}/{mx}) — pidiendo resumen..."

            case "safety.budget_exceeded" | "safety.budget":
                spent = kw.get("spent", kw.get("error", "?"))
                return f"\n⚠  Presupuesto excedido ({spent}) — pidiendo resumen..."

            case "safety.timeout":
                return "\n⚠  Timeout alcanzado — pidiendo resumen..."

            case "safety.context_full":
                return "\n⚠  Contexto lleno — pidiendo resumen..."

            # ── LLM ERRORS ──────────────────────────────────────────────
            case "agent.llm_error":
                error = kw.get("error", "desconocido")
                return f"\n✗ Error del LLM: {error}"

            case "agent.step_timeout":
                seconds = kw.get("seconds", "?")
                return f"\n⚠  Step timeout ({seconds}s) — pidiendo resumen..."

            # ── AGENT LIFECYCLE ──────────────────────────────────────────
            case "agent.closing":
                reason = kw.get("reason", "?")
                steps = kw.get("steps", "?")
                return f"\n→ Cerrando ({reason}, {steps} pasos completados)"

            case "agent.loop.complete":
                status = kw.get("status", "?")
                stop_reason = kw.get("stop_reason")
                steps = kw.get("total_steps", "?")
                tool_calls = kw.get("total_tool_calls", "?")
                if status == "success":
                    return f"  ({steps} pasos, {tool_calls} tool calls)"
                else:
                    reason_str = f" — {stop_reason}" if stop_reason else ""
                    return f"\n⚡ Detenido ({status}{reason_str}, {steps} pasos)"

            # ── CONTEXT ──────────────────────────────────────────────────
            case "context.compressing":
                exchanges = kw.get("tool_exchanges", "?")
                return f"  [comprimiendo contexto — {exchanges} intercambios]"

            case "context.window_enforced":
                removed = kw.get("removed_messages", "?")
                return f"  [ventana de contexto: eliminados {removed} mensajes antiguos]"

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

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Solo procesar eventos de nivel HUMAN exacto
            if record.levelno != HUMAN:
                return

            # Extraer event y kwargs del record de structlog
            event = getattr(record, "event", None) or record.getMessage()
            # structlog pone los kwargs en el dict del record
            kw = {
                k: v for k, v in record.__dict__.items()
                if not k.startswith("_") and k not in (
                    "msg", "args", "levelname", "levelno", "pathname",
                    "filename", "module", "exc_info", "exc_text", "stack_info",
                    "lineno", "funcName", "created", "msecs", "relativeCreated",
                    "thread", "threadName", "processName", "process", "message",
                    "taskName", "name", "event",
                )
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

    def tool_call(self, name: str, args: dict) -> None:
        self._log.log(HUMAN, "agent.tool_call.execute", tool=name, args=args)

    def tool_result(self, name: str, success: bool, error: str | None = None) -> None:
        self._log.log(HUMAN, "agent.tool_call.complete", tool=name, success=success, error=error)

    def hook_complete(self, name: str) -> None:
        self._log.log(HUMAN, "agent.hook.complete", tool=name)

    def agent_done(self, step: int) -> None:
        self._log.log(HUMAN, "agent.complete", step=step)

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
