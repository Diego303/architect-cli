#!/usr/bin/env python3
"""
Test v3-M5: HUMAN log level + HumanLog + HumanFormatter + HumanLogHandler.

Valida:
- HUMAN level = 25, entre INFO(20) y WARNING(30)
- HumanFormatter.format_event() para cada event_type
- HumanLog: 10 métodos emiten log con HUMAN level y event correcto
- HumanLogHandler: filtra solo nivel HUMAN
- configure_logging(): crea los 3 handlers

Ejecutar:
    python scripts/test_v3_m5.py
"""

import io
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ── Helpers ──────────────────────────────────────────────────────────────────

PASSED = 0
FAILED = 0


def ok(name: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  \u2713 {name}")


def fail(name: str, detail: str = "") -> None:
    global FAILED
    FAILED += 1
    msg = f"  \u2717 {name}"
    if detail:
        msg += f": {detail}"
    print(msg)


def section(title: str) -> None:
    print(f"\n\u2500\u2500 {title} {'\u2500' * (55 - len(title))}")


# ── Imports ──────────────────────────────────────────────────────────────────

from architect.logging.levels import HUMAN
from architect.logging.human import HumanFormatter, HumanLogHandler, HumanLog


# ── Tests: HUMAN level ───────────────────────────────────────────────────────

def test_human_level():
    section("HUMAN level")

    # Test: valor = 25
    if HUMAN == 25:
        ok("HUMAN = 25")
    else:
        fail("HUMAN = 25", f"got {HUMAN}")

    # Test: entre INFO y WARNING
    if logging.INFO < HUMAN < logging.WARNING:
        ok(f"INFO({logging.INFO}) < HUMAN({HUMAN}) < WARNING({logging.WARNING})")
    else:
        fail(f"INFO < HUMAN < WARNING", f"INFO={logging.INFO}, HUMAN={HUMAN}, WARNING={logging.WARNING}")

    # Test: registrado en logging
    level_name = logging.getLevelName(25)
    if level_name == "HUMAN":
        ok(f"logging.getLevelName(25) == 'HUMAN'")
    else:
        fail(f"logging.getLevelName(25) == 'HUMAN'", f"got '{level_name}'")


# ── Tests: HumanFormatter ────────────────────────────────────────────────────

def test_human_formatter():
    section("HumanFormatter.format_event()")

    fmt = HumanFormatter()

    # Test: llm_call
    result = fmt.format_event("agent.llm.call", step=0, messages_count=5)
    if result and "Paso 1" in result and "5 mensajes" in result:
        ok("agent.llm.call → 'Paso 1 → LLM (5 mensajes)'")
    else:
        fail("agent.llm.call", f"got '{result}'")

    # Test: agent.complete
    result = fmt.format_event("agent.complete", step=3)
    if result and "Completado" in result and "3" in result:
        ok("agent.complete → '✓ Completado (3 pasos)'")
    else:
        fail("agent.complete", f"got '{result}'")

    # Test: tool_call
    result = fmt.format_event("agent.tool_call.execute", tool="read_file", args={"path": "main.py"})
    if result and "tool read_file" in result:
        ok("agent.tool_call.execute → 'tool read_file → ...'")
    else:
        fail("agent.tool_call.execute", f"got '{result}'")

    # Test: tool_result success
    result = fmt.format_event("agent.tool_call.complete", tool="read_file", success=True)
    if result and "OK" in result:
        ok("agent.tool_call.complete (success) → 'OK'")
    else:
        fail("agent.tool_call.complete (success)", f"got '{result}'")

    # Test: tool_result failure
    result = fmt.format_event("agent.tool_call.complete", tool="edit_file", success=False, error="file not found")
    if result and "ERROR" in result and "file not found" in result:
        ok("agent.tool_call.complete (failure) → 'ERROR: file not found'")
    else:
        fail("agent.tool_call.complete (failure)", f"got '{result}'")

    # Test: hook complete
    result = fmt.format_event("agent.hook.complete")
    if result and "hooks" in result:
        ok("agent.hook.complete → '[hooks ejecutados]'")
    else:
        fail("agent.hook.complete", f"got '{result}'")

    # Test: safety_net user_interrupt
    result = fmt.format_event("safety.user_interrupt")
    if result and "Interrumpido" in result:
        ok("safety.user_interrupt → 'Interrumpido por el usuario'")
    else:
        fail("safety.user_interrupt", f"got '{result}'")

    # Test: safety_net max_steps
    result = fmt.format_event("safety.max_steps", step=50, max_steps=50)
    if result and "Límite de pasos" in result:
        ok("safety.max_steps → 'Límite de pasos alcanzado'")
    else:
        fail("safety.max_steps", f"got '{result}'")

    # Test: safety_net timeout
    result = fmt.format_event("safety.timeout")
    if result and "Timeout" in result:
        ok("safety.timeout → 'Timeout alcanzado'")
    else:
        fail("safety.timeout", f"got '{result}'")

    # Test: safety_net context_full
    result = fmt.format_event("safety.context_full")
    if result and "Contexto lleno" in result:
        ok("safety.context_full → 'Contexto lleno'")
    else:
        fail("safety.context_full", f"got '{result}'")

    # Test: llm_error
    result = fmt.format_event("agent.llm_error", error="timeout")
    if result and "Error del LLM" in result and "timeout" in result:
        ok("agent.llm_error → 'Error del LLM: timeout'")
    else:
        fail("agent.llm_error", f"got '{result}'")

    # Test: step_timeout
    result = fmt.format_event("agent.step_timeout", seconds=30)
    if result and "Step timeout" in result and "30" in result:
        ok("agent.step_timeout → 'Step timeout (30s)'")
    else:
        fail("agent.step_timeout", f"got '{result}'")

    # Test: agent.closing
    result = fmt.format_event("agent.closing", reason="max_steps", steps=10)
    if result and "Cerrando" in result and "max_steps" in result:
        ok("agent.closing → 'Cerrando (max_steps, 10 pasos)'")
    else:
        fail("agent.closing", f"got '{result}'")

    # Test: loop_complete success
    result = fmt.format_event("agent.loop.complete", status="success", total_steps=5, total_tool_calls=12)
    if result and "5 pasos" in result and "12 tool calls" in result:
        ok("agent.loop.complete (success) → '(5 pasos, 12 tool calls)'")
    else:
        fail("agent.loop.complete (success)", f"got '{result}'")

    # Test: loop_complete partial
    result = fmt.format_event("agent.loop.complete", status="partial", stop_reason="max_steps", total_steps=50, total_tool_calls=100)
    if result and "Detenido" in result and "max_steps" in result:
        ok("agent.loop.complete (partial) → 'Detenido (partial — max_steps)'")
    else:
        fail("agent.loop.complete (partial)", f"got '{result}'")

    # Test: context.compressing
    result = fmt.format_event("context.compressing", tool_exchanges=12)
    if result and "comprimiendo" in result and "12" in result:
        ok("context.compressing → '[comprimiendo contexto]'")
    else:
        fail("context.compressing", f"got '{result}'")

    # Test: context.window_enforced
    result = fmt.format_event("context.window_enforced", removed_messages=6)
    if result and "eliminados" in result and "6" in result:
        ok("context.window_enforced → '[eliminados 6 mensajes]'")
    else:
        fail("context.window_enforced", f"got '{result}'")

    # Test: unknown event → None
    result = fmt.format_event("unknown.event.xyz")
    if result is None:
        ok("Evento desconocido → None")
    else:
        fail("Evento desconocido → None", f"got '{result}'")

    # Test: agent.step.start → None (suppressed)
    result = fmt.format_event("agent.step.start", step=0)
    if result is None:
        ok("agent.step.start → None (suprimido)")
    else:
        fail("agent.step.start → None (suprimido)", f"got '{result}'")


# ── Tests: HumanLog ──────────────────────────────────────────────────────────

def test_human_log():
    section("HumanLog — métodos")

    mock_logger = MagicMock()
    hlog = HumanLog(mock_logger)

    # Test each method
    hlog.llm_call(step=0, messages_count=5)
    mock_logger.log.assert_called_with(HUMAN, "agent.llm.call", step=0, messages_count=5)
    ok("llm_call() → log(HUMAN, 'agent.llm.call', ...)")
    mock_logger.reset_mock()

    hlog.tool_call("read_file", {"path": "test.py"})
    mock_logger.log.assert_called_with(HUMAN, "agent.tool_call.execute", tool="read_file", args={"path": "test.py"})
    ok("tool_call() → log(HUMAN, 'agent.tool_call.execute', ...)")
    mock_logger.reset_mock()

    hlog.tool_result("read_file", True, None)
    mock_logger.log.assert_called_with(HUMAN, "agent.tool_call.complete", tool="read_file", success=True, error=None)
    ok("tool_result() → log(HUMAN, 'agent.tool_call.complete', ...)")
    mock_logger.reset_mock()

    hlog.hook_complete("edit_file")
    mock_logger.log.assert_called_with(HUMAN, "agent.hook.complete", tool="edit_file")
    ok("hook_complete() → log(HUMAN, 'agent.hook.complete', ...)")
    mock_logger.reset_mock()

    hlog.agent_done(5)
    mock_logger.log.assert_called_with(HUMAN, "agent.complete", step=5)
    ok("agent_done() → log(HUMAN, 'agent.complete', ...)")
    mock_logger.reset_mock()

    hlog.safety_net("max_steps", step=50, max_steps=50)
    mock_logger.log.assert_called_with(HUMAN, "safety.max_steps", step=50, max_steps=50)
    ok("safety_net() → log(HUMAN, 'safety.max_steps', ...)")
    mock_logger.reset_mock()

    hlog.closing("timeout", 10)
    mock_logger.log.assert_called_with(HUMAN, "agent.closing", reason="timeout", steps=10)
    ok("closing() → log(HUMAN, 'agent.closing', ...)")
    mock_logger.reset_mock()

    hlog.llm_error("timeout error")
    mock_logger.log.assert_called_with(HUMAN, "agent.llm_error", error="timeout error")
    ok("llm_error() → log(HUMAN, 'agent.llm_error', ...)")
    mock_logger.reset_mock()

    hlog.step_timeout(30)
    mock_logger.log.assert_called_with(HUMAN, "agent.step_timeout", seconds=30)
    ok("step_timeout() → log(HUMAN, 'agent.step_timeout', ...)")
    mock_logger.reset_mock()

    hlog.loop_complete("success", None, 5, 12)
    mock_logger.log.assert_called_with(
        HUMAN, "agent.loop.complete",
        status="success", stop_reason=None, total_steps=5, total_tool_calls=12,
    )
    ok("loop_complete() → log(HUMAN, 'agent.loop.complete', ...)")
    mock_logger.reset_mock()


# ── Tests: HumanLogHandler ───────────────────────────────────────────────────

def test_human_log_handler():
    section("HumanLogHandler — filtrado")

    stream = io.StringIO()
    handler = HumanLogHandler(stream=stream)

    # Test: acepta nivel HUMAN
    record_human = logging.LogRecord(
        name="test", level=HUMAN, pathname="", lineno=0,
        msg="agent.llm.call", args=None, exc_info=None,
    )
    record_human.event = "agent.llm.call"
    record_human.step = 0
    record_human.messages_count = 5
    handler.emit(record_human)
    output = stream.getvalue()
    if "Paso 1" in output:
        ok("Nivel HUMAN → acepta y formatea")
    else:
        fail("Nivel HUMAN → acepta y formatea", f"output='{output}'")

    # Test: rechaza INFO
    stream2 = io.StringIO()
    handler2 = HumanLogHandler(stream=stream2)
    record_info = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="info message", args=None, exc_info=None,
    )
    handler2.emit(record_info)
    if stream2.getvalue() == "":
        ok("Nivel INFO → rechazado")
    else:
        fail("Nivel INFO → rechazado", f"output='{stream2.getvalue()}'")

    # Test: rechaza WARNING
    stream3 = io.StringIO()
    handler3 = HumanLogHandler(stream=stream3)
    record_warn = logging.LogRecord(
        name="test", level=logging.WARNING, pathname="", lineno=0,
        msg="warning message", args=None, exc_info=None,
    )
    handler3.emit(record_warn)
    if stream3.getvalue() == "":
        ok("Nivel WARNING → rechazado")
    else:
        fail("Nivel WARNING → rechazado", f"output='{stream3.getvalue()}'")

    # Test: rechaza DEBUG
    stream4 = io.StringIO()
    handler4 = HumanLogHandler(stream=stream4)
    record_debug = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="debug message", args=None, exc_info=None,
    )
    handler4.emit(record_debug)
    if stream4.getvalue() == "":
        ok("Nivel DEBUG → rechazado")
    else:
        fail("Nivel DEBUG → rechazado", f"output='{stream4.getvalue()}'")


# ── Tests: configure_logging ─────────────────────────────────────────────────

def test_configure_logging():
    section("configure_logging()")

    from architect.logging.setup import configure_logging
    from architect.config.schema import LoggingConfig

    # Save current handlers
    original_handlers = logging.root.handlers.copy()

    try:
        # Test: sin file, sin quiet, sin json → 2 handlers (human + console)
        config = LoggingConfig(level="human", verbose=0, file=None)
        configure_logging(config, json_output=False, quiet=False)

        handlers = logging.root.handlers
        handler_types = [type(h).__name__ for h in handlers]

        if len(handlers) == 2:
            ok(f"Sin file: 2 handlers ({handler_types})")
        else:
            fail(f"Sin file: 2 handlers", f"got {len(handlers)} ({handler_types})")

        # Verify one is HumanLogHandler
        has_human = any(isinstance(h, HumanLogHandler) for h in handlers)
        if has_human:
            ok("Tiene HumanLogHandler")
        else:
            fail("Tiene HumanLogHandler", f"types={handler_types}")

        # Verify one is StreamHandler (console)
        has_console = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, HumanLogHandler)
            for h in handlers
        )
        if has_console:
            ok("Tiene StreamHandler (console)")
        else:
            fail("Tiene StreamHandler (console)", f"types={handler_types}")

        # Test: quiet=True → 0 handlers
        configure_logging(config, json_output=False, quiet=True)
        handlers_quiet = logging.root.handlers
        if len(handlers_quiet) == 0:
            ok("quiet=True: 0 handlers")
        else:
            fail("quiet=True: 0 handlers", f"got {len(handlers_quiet)}")

        # Test: json_output=True → 0 handlers (no file)
        configure_logging(config, json_output=True, quiet=False)
        handlers_json = logging.root.handlers
        if len(handlers_json) == 0:
            ok("json_output=True (sin file): 0 handlers")
        else:
            fail("json_output=True (sin file): 0 handlers", f"got {len(handlers_json)}")

    finally:
        # Restore handlers
        logging.root.handlers = original_handlers


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M5: HUMAN log level + HumanLog + HumanFormatter")
    print("=" * 60)

    test_human_level()
    test_human_formatter()
    test_human_log()
    test_human_log_handler()
    test_configure_logging()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
