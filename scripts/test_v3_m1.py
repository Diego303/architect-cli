#!/usr/bin/env python3
"""
Test v3-M1: while True loop + StopReason + safety nets.

Valida:
- StopReason enum (7 valores, strings correctos)
- AgentState.stop_reason (default None, asignable, en to_output_dict())
- _check_safety_nets() para cada StopReason
- _graceful_close() con llamada al LLM
- run() flujo básico: LLM_DONE y tool_calls

Ejecutar:
    python scripts/test_v3_m1.py
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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

from architect.core.state import AgentState, StepResult, StopReason, ToolCallResult
from architect.llm.adapter import LLMResponse
from architect.tools.base import ToolResult
from architect.config.schema import AgentConfig, ContextConfig


# ── Tests: StopReason enum ───────────────────────────────────────────────────

def test_stop_reason_enum():
    section("StopReason enum")

    expected = {
        "LLM_DONE": "llm_done",
        "MAX_STEPS": "max_steps",
        "BUDGET_EXCEEDED": "budget_exceeded",
        "CONTEXT_FULL": "context_full",
        "TIMEOUT": "timeout",
        "USER_INTERRUPT": "user_interrupt",
        "LLM_ERROR": "llm_error",
    }

    # Test: tiene exactamente 7 valores
    members = list(StopReason)
    if len(members) == 7:
        ok("StopReason tiene 7 miembros")
    else:
        fail("StopReason tiene 7 miembros", f"tiene {len(members)}")

    # Test: cada valor tiene el string correcto
    for attr_name, expected_value in expected.items():
        member = StopReason[attr_name]
        if member.value == expected_value:
            ok(f"StopReason.{attr_name} == '{expected_value}'")
        else:
            fail(f"StopReason.{attr_name} == '{expected_value}'", f"got '{member.value}'")

    # Test: es un Enum real
    from enum import Enum
    if issubclass(StopReason, Enum):
        ok("StopReason hereda de Enum")
    else:
        fail("StopReason hereda de Enum")


# ── Tests: AgentState.stop_reason ────────────────────────────────────────────

def test_agent_state_stop_reason():
    section("AgentState.stop_reason")

    # Test: default None
    state = AgentState()
    if state.stop_reason is None:
        ok("stop_reason default es None")
    else:
        fail("stop_reason default es None", f"got {state.stop_reason}")

    # Test: asignable
    state.stop_reason = StopReason.LLM_DONE
    if state.stop_reason == StopReason.LLM_DONE:
        ok("stop_reason se puede asignar StopReason.LLM_DONE")
    else:
        fail("stop_reason se puede asignar StopReason.LLM_DONE")

    # Test: presente en to_output_dict() con valor
    state.stop_reason = StopReason.MAX_STEPS
    output = state.to_output_dict()
    if output.get("stop_reason") == "max_steps":
        ok("to_output_dict() incluye stop_reason='max_steps'")
    else:
        fail("to_output_dict() incluye stop_reason='max_steps'", f"got {output.get('stop_reason')}")

    # Test: to_output_dict() con stop_reason=None
    state2 = AgentState()
    output2 = state2.to_output_dict()
    if output2.get("stop_reason") is None:
        ok("to_output_dict() con stop_reason=None retorna None")
    else:
        fail("to_output_dict() con stop_reason=None retorna None", f"got {output2.get('stop_reason')}")


# ── Tests: _check_safety_nets ────────────────────────────────────────────────

def _make_loop(**overrides):
    """Crea un AgentLoop con mocks mínimos."""
    from architect.core.loop import AgentLoop

    llm = MagicMock()
    engine = MagicMock()
    agent_config = AgentConfig(
        system_prompt="test",
        max_steps=overrides.get("max_steps", 50),
    )
    ctx = MagicMock()
    shutdown = overrides.get("shutdown", None)
    context_manager = overrides.get("context_manager", None)
    cost_tracker = overrides.get("cost_tracker", None)
    timeout = overrides.get("timeout", None)

    loop = AgentLoop(
        llm=llm,
        engine=engine,
        agent_config=agent_config,
        context_builder=ctx,
        shutdown=shutdown,
        context_manager=context_manager,
        cost_tracker=cost_tracker,
        timeout=timeout,
    )
    # Set start time for timeout checks
    loop._start_time = time.time()
    return loop


def test_check_safety_nets():
    section("_check_safety_nets()")

    state = AgentState()

    # Test: USER_INTERRUPT cuando shutdown.should_stop = True
    shutdown = MagicMock()
    shutdown.should_stop = True
    loop = _make_loop(shutdown=shutdown)
    result = loop._check_safety_nets(state, step=0)
    if result == StopReason.USER_INTERRUPT:
        ok("USER_INTERRUPT cuando shutdown.should_stop=True")
    else:
        fail("USER_INTERRUPT cuando shutdown.should_stop=True", f"got {result}")

    # Test: MAX_STEPS cuando step >= max_steps
    loop = _make_loop(max_steps=5)
    result = loop._check_safety_nets(state, step=5)
    if result == StopReason.MAX_STEPS:
        ok("MAX_STEPS cuando step >= max_steps")
    else:
        fail("MAX_STEPS cuando step >= max_steps", f"got {result}")

    # Test: TIMEOUT cuando ha pasado el tiempo
    loop = _make_loop(timeout=1)
    loop._start_time = time.time() - 10  # 10 seconds ago
    result = loop._check_safety_nets(state, step=0)
    if result == StopReason.TIMEOUT:
        ok("TIMEOUT cuando time elapsed > timeout")
    else:
        fail("TIMEOUT cuando time elapsed > timeout", f"got {result}")

    # Test: CONTEXT_FULL cuando context_manager.is_critically_full = True
    cm = MagicMock()
    cm.is_critically_full.return_value = True
    loop = _make_loop(context_manager=cm)
    result = loop._check_safety_nets(state, step=0)
    if result == StopReason.CONTEXT_FULL:
        ok("CONTEXT_FULL cuando is_critically_full=True")
    else:
        fail("CONTEXT_FULL cuando is_critically_full=True", f"got {result}")

    # Test: None cuando todo OK
    loop = _make_loop(max_steps=50)
    result = loop._check_safety_nets(state, step=0)
    if result is None:
        ok("None cuando todo OK (sin watchdogs)")
    else:
        fail("None cuando todo OK (sin watchdogs)", f"got {result}")

    # Test: None con shutdown que no está activo
    shutdown2 = MagicMock()
    shutdown2.should_stop = False
    loop = _make_loop(shutdown=shutdown2, max_steps=50)
    result = loop._check_safety_nets(state, step=0)
    if result is None:
        ok("None con shutdown.should_stop=False")
    else:
        fail("None con shutdown.should_stop=False", f"got {result}")

    # Test: Prioridad — USER_INTERRUPT tiene prioridad sobre MAX_STEPS
    shutdown3 = MagicMock()
    shutdown3.should_stop = True
    loop = _make_loop(shutdown=shutdown3, max_steps=0)
    result = loop._check_safety_nets(state, step=5)
    if result == StopReason.USER_INTERRUPT:
        ok("USER_INTERRUPT tiene prioridad sobre MAX_STEPS")
    else:
        fail("USER_INTERRUPT tiene prioridad sobre MAX_STEPS", f"got {result}")


# ── Tests: _graceful_close ───────────────────────────────────────────────────

def test_graceful_close():
    section("_graceful_close()")

    # Test: USER_INTERRUPT no llama al LLM
    loop = _make_loop()
    state = AgentState()
    result_state = loop._graceful_close(state, StopReason.USER_INTERRUPT, None)
    if result_state.status == "partial":
        ok("USER_INTERRUPT → status='partial'")
    else:
        fail("USER_INTERRUPT → status='partial'", f"got '{result_state.status}'")
    if result_state.stop_reason == StopReason.USER_INTERRUPT:
        ok("USER_INTERRUPT → stop_reason=USER_INTERRUPT")
    else:
        fail("USER_INTERRUPT → stop_reason=USER_INTERRUPT", f"got {result_state.stop_reason}")
    loop.llm.completion.assert_not_called()
    ok("USER_INTERRUPT → LLM no llamado")

    # Test: MAX_STEPS llama al LLM con instrucciones de cierre
    loop2 = _make_loop()
    loop2.llm.completion.return_value = LLMResponse(
        content="Resumen de lo completado", finish_reason="stop", usage=None
    )
    state2 = AgentState()
    result_state2 = loop2._graceful_close(state2, StopReason.MAX_STEPS, None)
    if result_state2.status == "partial":
        ok("MAX_STEPS → status='partial'")
    else:
        fail("MAX_STEPS → status='partial'", f"got '{result_state2.status}'")
    if result_state2.stop_reason == StopReason.MAX_STEPS:
        ok("MAX_STEPS → stop_reason=MAX_STEPS")
    else:
        fail("MAX_STEPS → stop_reason=MAX_STEPS", f"got {result_state2.stop_reason}")
    loop2.llm.completion.assert_called_once()
    ok("MAX_STEPS → LLM llamado una vez")
    if result_state2.final_output == "Resumen de lo completado":
        ok("MAX_STEPS → final_output del LLM")
    else:
        fail("MAX_STEPS → final_output del LLM", f"got '{result_state2.final_output}'")

    # Test: BUDGET_EXCEEDED → corte inmediato sin llamar al LLM
    loop3 = _make_loop()
    loop3.llm.completion.side_effect = RuntimeError("LLM unavailable")
    state3 = AgentState()
    result_state3 = loop3._graceful_close(state3, StopReason.BUDGET_EXCEEDED, None)
    if result_state3.final_output and "Presupuesto excedido" in result_state3.final_output:
        ok("BUDGET_EXCEEDED → corte inmediato sin LLM")
    else:
        fail("BUDGET_EXCEEDED → corte inmediato sin LLM", f"got '{result_state3.final_output}'")
    loop3.llm.completion.assert_not_called()
    ok("BUDGET_EXCEEDED → LLM no llamado (ahorra dinero)")


# ── Tests: run() flujo básico ────────────────────────────────────────────────

def test_run_basic():
    section("run() — flujo básico")

    # Test: LLM retorna sin tool_calls → LLM_DONE
    loop = _make_loop()
    loop.ctx.build_initial.return_value = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "hola"},
    ]
    loop.engine.registry.get_schemas.return_value = []
    loop.llm.completion.return_value = LLMResponse(
        content="Hola, tarea completada",
        finish_reason="stop",
        tool_calls=[],
        usage=None,
    )
    loop.llm.config = MagicMock()
    loop.llm.config.model = "test-model"

    state = loop.run("hola")

    if state.status == "success":
        ok("LLM sin tool_calls → status='success'")
    else:
        fail("LLM sin tool_calls → status='success'", f"got '{state.status}'")

    if state.stop_reason == StopReason.LLM_DONE:
        ok("LLM sin tool_calls → stop_reason=LLM_DONE")
    else:
        fail("LLM sin tool_calls → stop_reason=LLM_DONE", f"got {state.stop_reason}")

    if state.final_output == "Hola, tarea completada":
        ok("LLM sin tool_calls → final_output correcto")
    else:
        fail("LLM sin tool_calls → final_output correcto", f"got '{state.final_output}'")

    # Test: LLM retorna tool_calls → ejecuta y continúa
    loop2 = _make_loop(max_steps=10)
    loop2.ctx.build_initial.return_value = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "lee main.py"},
    ]
    loop2.engine.registry.get_schemas.return_value = [{"type": "function"}]
    loop2.llm.config = MagicMock()
    loop2.llm.config.model = "test-model"

    # First call: returns tool_calls
    from architect.llm.adapter import ToolCall as TC
    tc_mock = TC(id="tc_1", name="read_file", arguments={"path": "main.py"})

    tool_result = ToolResult(success=True, output="file content")

    response_with_tools = LLMResponse(
        content=None,
        finish_reason="tool_calls",
        tool_calls=[tc_mock],
        usage=None,
    )
    response_done = LLMResponse(
        content="Archivo leído correctamente",
        finish_reason="stop",
        tool_calls=[],
        usage=None,
    )

    loop2.llm.completion.side_effect = [response_with_tools, response_done]
    loop2.engine.execute_tool_call.return_value = tool_result
    loop2.engine.run_post_edit_hooks.return_value = None
    loop2.engine.dry_run = False
    loop2.engine.check_guardrails.return_value = None  # v4-A2: no bloquear
    loop2.engine.run_pre_tool_hooks.return_value = None  # v4-A1: no bloquear
    loop2.engine.check_code_rules.return_value = []  # v4-A2: sin violaciones
    loop2.engine.run_post_tool_hooks.return_value = None  # v4-A1: sin output extra
    loop2.ctx.append_tool_results.return_value = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "lee main.py"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_1"}]},
        {"role": "tool", "tool_call_id": "tc_1", "content": "file content"},
    ]

    state2 = loop2.run("lee main.py")

    if state2.status == "success":
        ok("LLM con tool_calls → ejecuta y luego status='success'")
    else:
        fail("LLM con tool_calls → ejecuta y luego status='success'", f"got '{state2.status}'")

    if state2.stop_reason == StopReason.LLM_DONE:
        ok("LLM con tool_calls → stop_reason=LLM_DONE al terminar")
    else:
        fail("LLM con tool_calls → stop_reason=LLM_DONE al terminar", f"got {state2.stop_reason}")

    if loop2.engine.execute_tool_call.called:
        ok("LLM con tool_calls → engine.execute_tool_call() llamado")
    else:
        fail("LLM con tool_calls → engine.execute_tool_call() llamado")


# ── Tests: _CLOSE_INSTRUCTIONS ───────────────────────────────────────────────

def test_close_instructions():
    section("_CLOSE_INSTRUCTIONS")

    from architect.core.loop import _CLOSE_INSTRUCTIONS

    expected_keys = {
        StopReason.MAX_STEPS,
        StopReason.BUDGET_EXCEEDED,
        StopReason.CONTEXT_FULL,
        StopReason.TIMEOUT,
    }

    if set(_CLOSE_INSTRUCTIONS.keys()) == expected_keys:
        ok("_CLOSE_INSTRUCTIONS tiene 4 claves correctas")
    else:
        fail("_CLOSE_INSTRUCTIONS tiene 4 claves correctas",
             f"keys={set(_CLOSE_INSTRUCTIONS.keys())}")

    # Verify each instruction is a non-empty string
    all_str = all(isinstance(v, str) and len(v) > 10 for v in _CLOSE_INSTRUCTIONS.values())
    if all_str:
        ok("Todas las instrucciones son strings no vacíos")
    else:
        fail("Todas las instrucciones son strings no vacíos")

    # USER_INTERRUPT and LLM_ERROR should NOT have close instructions
    if StopReason.USER_INTERRUPT not in _CLOSE_INSTRUCTIONS:
        ok("USER_INTERRUPT no tiene instrucción de cierre")
    else:
        fail("USER_INTERRUPT no tiene instrucción de cierre")

    if StopReason.LLM_ERROR not in _CLOSE_INSTRUCTIONS:
        ok("LLM_ERROR no tiene instrucción de cierre")
    else:
        fail("LLM_ERROR no tiene instrucción de cierre")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M1: while True loop + StopReason + safety nets")
    print("=" * 60)

    # Configurar structlog con stdlib (necesario para nivel HUMAN en AgentLoop)
    from architect.logging.setup import configure_logging
    from architect.config.schema import LoggingConfig
    configure_logging(LoggingConfig(), quiet=True)

    test_stop_reason_enum()
    test_agent_state_stop_reason()
    test_check_safety_nets()
    test_graceful_close()
    test_run_basic()
    test_close_instructions()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
