#!/usr/bin/env python3
"""
Test Parallel Execution: _should_parallelize, batch execution, safety nets.

Valida:
- _should_parallelize() con diferentes confirm_modes y tool sensitivities
- _execute_tool_calls_batch() secuencial vs paralelo
- _check_safety_nets() para cada StopReason
- _graceful_close() comportamiento
- Post-edit hooks integration
- StopReason enum y _CLOSE_INSTRUCTIONS

Ejecutar:
    python scripts/test_parallel_execution.py
"""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
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

from architect.config.schema import AgentConfig, ContextConfig
from architect.core.loop import AgentLoop, _CLOSE_INSTRUCTIONS
from architect.core.state import AgentState, StopReason, ToolCallResult
from architect.llm.adapter import LLMResponse
from architect.tools.base import ToolResult

# Configure structlog for HUMAN level
from architect.config.schema import LoggingConfig
from architect.logging.setup import configure_logging
configure_logging(LoggingConfig(), quiet=True)


# ── Factory helpers ──────────────────────────────────────────────────────────

def _make_tool_call(name="read_file", arguments=None):
    """Create a fake tool call object."""
    return SimpleNamespace(name=name, arguments=arguments or {"path": "/a.py"})


def _make_loop(confirm_mode="yolo", max_steps=20, parallel_tools=True,
               has_context_manager=True):
    """Create an AgentLoop with mocked dependencies."""
    loop = AgentLoop.__new__(AgentLoop)
    loop.agent_config = AgentConfig(
        system_prompt="test",
        confirm_mode=confirm_mode,
        max_steps=max_steps,
    )
    loop.llm = MagicMock()
    loop.engine = MagicMock()
    loop.engine.registry = MagicMock()
    loop.engine.dry_run = False
    loop.engine.check_guardrails.return_value = None  # v4-A2: no bloquear
    loop.engine.run_pre_tool_hooks.return_value = None  # v4-A1: no bloquear
    loop.engine.check_code_rules.return_value = []  # v4-A2: sin violaciones
    loop.engine.run_post_tool_hooks.return_value = None  # v4-A1: sin output extra
    loop.shutdown = None
    loop.step_timeout = 0
    loop.timeout = None
    loop._start_time = time.time()
    loop.log = MagicMock()
    loop.hlog = MagicMock()
    loop.cost_tracker = None

    if has_context_manager:
        ctx_manager = MagicMock()
        ctx_manager.config = ContextConfig(parallel_tools=parallel_tools)
        ctx_manager.is_critically_full.return_value = False
        loop.context_manager = ctx_manager
    else:
        loop.context_manager = None

    loop.ctx = MagicMock()

    return loop


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: _should_parallelize()
# ══════════════════════════════════════════════════════════════════════════════

def test_should_parallelize():
    section("_should_parallelize()")

    # 1.1 yolo mode, no sensitive tools → True
    loop = _make_loop(confirm_mode="yolo")
    tool_calls = [_make_tool_call("read_file"), _make_tool_call("grep")]
    if loop._should_parallelize(tool_calls):
        ok("yolo mode, no sensitive tools → True")
    else:
        fail("yolo + no sensitive", "returned False")

    # 1.2 confirm-all mode → always False
    loop = _make_loop(confirm_mode="confirm-all")
    tool_calls = [_make_tool_call("read_file"), _make_tool_call("grep")]
    if not loop._should_parallelize(tool_calls):
        ok("confirm-all → always False")
    else:
        fail("confirm-all", "returned True")

    # 1.3 confirm-sensitive, no sensitive tools → True
    loop = _make_loop(confirm_mode="confirm-sensitive")
    tool_calls = [_make_tool_call("read_file"), _make_tool_call("grep")]
    mock_tool = MagicMock()
    mock_tool.sensitive = False
    loop.engine.registry.has_tool.return_value = True
    loop.engine.registry.get.return_value = mock_tool
    if loop._should_parallelize(tool_calls):
        ok("confirm-sensitive, no sensitive tools → True")
    else:
        fail("confirm-sensitive no sensitive", "returned False")

    # 1.4 confirm-sensitive, with sensitive tool → False
    loop = _make_loop(confirm_mode="confirm-sensitive")
    tool_calls = [_make_tool_call("read_file"), _make_tool_call("write_file")]
    sensitive_tool = MagicMock()
    sensitive_tool.sensitive = True
    loop.engine.registry.has_tool.return_value = True
    loop.engine.registry.get.return_value = sensitive_tool
    if not loop._should_parallelize(tool_calls):
        ok("confirm-sensitive, with sensitive tool → False")
    else:
        fail("confirm-sensitive + sensitive", "returned True")

    # 1.5 parallel_tools=False in config → False
    loop = _make_loop(confirm_mode="yolo", parallel_tools=False)
    tool_calls = [_make_tool_call("read_file"), _make_tool_call("grep")]
    if not loop._should_parallelize(tool_calls):
        ok("parallel_tools=False in config → False")
    else:
        fail("parallel_tools=False", "returned True")

    # 1.6 No context_manager, yolo → True
    loop = _make_loop(confirm_mode="yolo", has_context_manager=False)
    tool_calls = [_make_tool_call("read_file"), _make_tool_call("grep")]
    if loop._should_parallelize(tool_calls):
        ok("No context_manager, yolo → True")
    else:
        fail("No ctx_manager", "returned False")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: _execute_tool_calls_batch()
# ══════════════════════════════════════════════════════════════════════════════

def test_execute_tool_calls_batch():
    section("_execute_tool_calls_batch()")

    def make_result(tool_name):
        return ToolCallResult(
            tool_name=tool_name,
            args={},
            result=ToolResult(success=True, output=f"result_{tool_name}"),
        )

    # 2.1 Empty list → []
    loop = _make_loop()
    result = loop._execute_tool_calls_batch([], step=0)
    if result == []:
        ok("Empty list → []")
    else:
        fail("Empty list", f"got {result}")

    # 2.2 Single tool call → sequential
    loop = _make_loop()
    tc = _make_tool_call("read_file")
    expected = make_result("read_file")
    with patch.object(loop, '_execute_single_tool', return_value=expected) as mock_exec:
        results = loop._execute_tool_calls_batch([tc], step=0)
        mock_exec.assert_called_once_with(tc, 0)
        if len(results) == 1 and results[0].tool_name == "read_file":
            ok("Single tool call → sequential (called once)")
        else:
            fail("Single tool", f"got {results}")

    # 2.3 Multiple tool calls with yolo → parallel
    loop = _make_loop(confirm_mode="yolo")
    tcs = [_make_tool_call("read_file"), _make_tool_call("grep"), _make_tool_call("list_files")]

    call_count = 0
    def mock_execute(tc, step):
        nonlocal call_count
        call_count += 1
        return make_result(tc.name)

    with patch.object(loop, '_execute_single_tool', side_effect=mock_execute):
        with patch.object(loop, '_should_parallelize', return_value=True):
            results = loop._execute_tool_calls_batch(tcs, step=0)
            if call_count == 3 and len(results) == 3:
                ok("Multiple tool calls → parallel (3 calls)")
            else:
                fail("Multiple parallel", f"calls={call_count}, results={len(results)}")

    # 2.4 Results preserve order
    loop = _make_loop(confirm_mode="yolo")
    tcs = [_make_tool_call("aaa"), _make_tool_call("bbb"), _make_tool_call("ccc")]

    def mock_execute_ordered(tc, step):
        if tc.name == "aaa":
            time.sleep(0.05)
        return make_result(tc.name)

    with patch.object(loop, '_execute_single_tool', side_effect=mock_execute_ordered):
        with patch.object(loop, '_should_parallelize', return_value=True):
            results = loop._execute_tool_calls_batch(tcs, step=0)
            names = [r.tool_name for r in results]
            if names == ["aaa", "bbb", "ccc"]:
                ok("Results preserve original order after parallel execution")
            else:
                fail("Order preservation", f"got {names}")

    # 2.5 Sequential fallback when _should_parallelize=False
    loop = _make_loop(confirm_mode="confirm-all")
    tcs = [_make_tool_call("read_file"), _make_tool_call("grep")]

    call_order = []
    def mock_execute_seq(tc, step):
        call_order.append(tc.name)
        return make_result(tc.name)

    with patch.object(loop, '_execute_single_tool', side_effect=mock_execute_seq):
        results = loop._execute_tool_calls_batch(tcs, step=0)
        if call_order == ["read_file", "grep"] and len(results) == 2:
            ok("Sequential fallback when _should_parallelize=False")
        else:
            fail("Sequential fallback", f"order={call_order}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: _check_safety_nets()
# ══════════════════════════════════════════════════════════════════════════════

def test_check_safety_nets():
    section("_check_safety_nets()")

    state = AgentState()

    # 3.1 All clear → None
    loop = _make_loop(max_steps=20)
    result = loop._check_safety_nets(state, step=0)
    if result is None:
        ok("All clear → None")
    else:
        fail("All clear", f"got {result}")

    # 3.2 shutdown.should_stop → USER_INTERRUPT
    loop = _make_loop(max_steps=20)
    loop.shutdown = MagicMock()
    loop.shutdown.should_stop = True
    result = loop._check_safety_nets(state, step=0)
    if result == StopReason.USER_INTERRUPT:
        ok("shutdown.should_stop → USER_INTERRUPT")
    else:
        fail("USER_INTERRUPT", f"got {result}")

    # 3.3 step >= max_steps → MAX_STEPS
    loop = _make_loop(max_steps=5)
    loop.shutdown = None
    result = loop._check_safety_nets(state, step=5)
    if result == StopReason.MAX_STEPS:
        ok("step >= max_steps → MAX_STEPS")
    else:
        fail("MAX_STEPS", f"got {result}")

    # 3.4 timeout exceeded → TIMEOUT
    loop = _make_loop(max_steps=100)
    loop.timeout = 1
    loop._start_time = time.time() - 10
    result = loop._check_safety_nets(state, step=0)
    if result == StopReason.TIMEOUT:
        ok("Timeout exceeded → TIMEOUT")
    else:
        fail("TIMEOUT", f"got {result}")

    # 3.5 Context critically full → CONTEXT_FULL
    loop = _make_loop(max_steps=100)
    loop.timeout = None
    loop.context_manager.is_critically_full.return_value = True
    result = loop._check_safety_nets(state, step=0)
    if result == StopReason.CONTEXT_FULL:
        ok("Context critically full → CONTEXT_FULL")
    else:
        fail("CONTEXT_FULL", f"got {result}")

    # 3.6 Priority: USER_INTERRUPT first
    loop = _make_loop(max_steps=5)
    loop.shutdown = MagicMock()
    loop.shutdown.should_stop = True
    result = loop._check_safety_nets(state, step=10)
    if result == StopReason.USER_INTERRUPT:
        ok("Priority: USER_INTERRUPT checked first (even if max_steps exceeded)")
    else:
        fail("Priority", f"got {result}")

    # 3.7 Budget NOT in safety nets
    loop = _make_loop(max_steps=100)
    loop.timeout = None
    loop.context_manager.is_critically_full.return_value = False
    result = loop._check_safety_nets(state, step=0)
    if result is None:
        ok("Budget NOT checked in _check_safety_nets (happens after LLM call)")
    else:
        fail("Budget not in safety nets", f"got {result}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: _graceful_close()
# ══════════════════════════════════════════════════════════════════════════════

def test_graceful_close():
    section("_graceful_close()")

    # 4.1 USER_INTERRUPT → no LLM call, status=partial
    loop = _make_loop()
    state = AgentState()
    result = loop._graceful_close(state, StopReason.USER_INTERRUPT, None)
    loop.llm.completion.assert_not_called()
    if result.status == "partial" and result.stop_reason == StopReason.USER_INTERRUPT:
        ok("USER_INTERRUPT → no LLM call, status='partial'")
    else:
        fail("USER_INTERRUPT", f"status={result.status}")

    # 4.2 MAX_STEPS → injects message, calls LLM
    loop = _make_loop()
    loop.llm.completion.return_value = LLMResponse(content="Summary of work done")
    state = AgentState()
    result = loop._graceful_close(state, StopReason.MAX_STEPS, None)
    loop.llm.completion.assert_called_once()
    if result.status == "partial" and result.final_output == "Summary of work done":
        ok("MAX_STEPS → injects message, calls LLM, status='partial'")
    else:
        fail("MAX_STEPS", f"status={result.status}, output={result.final_output!r}")

    # 4.3 TIMEOUT → same behavior
    loop = _make_loop()
    loop.llm.completion.return_value = LLMResponse(content="Timeout summary")
    state = AgentState()
    result = loop._graceful_close(state, StopReason.TIMEOUT, None)
    if result.status == "partial" and result.final_output == "Timeout summary":
        ok("TIMEOUT → injects message, calls LLM")
    else:
        fail("TIMEOUT close", f"output={result.final_output!r}")

    # 4.4 LLM failure → fallback message
    loop = _make_loop()
    loop.llm.completion.side_effect = RuntimeError("LLM is down")
    state = AgentState()
    result = loop._graceful_close(state, StopReason.MAX_STEPS, None)
    if result.status == "partial" and result.final_output and "max_steps" in result.final_output:
        ok("LLM failure during close → fallback message")
    else:
        fail("LLM failure fallback", f"output={result.final_output!r}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Post-edit hooks integration
# ══════════════════════════════════════════════════════════════════════════════

def test_post_edit_hooks():
    section("Post-edit hooks integration")

    # 5.1 Hook output appended when tool succeeds
    loop = _make_loop()
    tc = _make_tool_call("edit_file", {"path": "/a.py", "old_str": "x", "new_str": "y"})
    loop.engine.execute_tool_call.return_value = ToolResult(success=True, output="File edited")
    loop.engine.run_post_tool_hooks.return_value = "[lint] OK - no errors"

    result = loop._execute_single_tool(tc, step=0)
    if "File edited" in result.result.output and "[lint] OK" in result.result.output:
        ok("Hook output appended to successful tool result")
    else:
        fail("Hook appended", f"got {result.result.output!r}")

    # 5.2 Hook output NOT appended when tool fails
    loop = _make_loop()
    tc = _make_tool_call("edit_file", {"path": "/a.py"})
    loop.engine.execute_tool_call.return_value = ToolResult(success=False, output="", error="File not found")
    loop.engine.run_post_tool_hooks.return_value = "[lint] some output"

    result = loop._execute_single_tool(tc, step=0)
    if not result.result.success and "[lint]" not in (result.result.output or ""):
        ok("Hook output NOT appended when tool fails")
    else:
        fail("Hook not appended on fail", f"output={result.result.output!r}")

    # 5.3 No hooks → result unchanged
    loop = _make_loop()
    tc = _make_tool_call("read_file")
    loop.engine.execute_tool_call.return_value = ToolResult(success=True, output="content here")
    loop.engine.run_post_tool_hooks.return_value = None

    result = loop._execute_single_tool(tc, step=0)
    if result.result.output == "content here":
        ok("No hooks (returns None) → result unchanged")
    else:
        fail("No hooks", f"got {result.result.output!r}")

    # 5.4 Hook empty string → treated as no output
    loop = _make_loop()
    tc = _make_tool_call("write_file")
    loop.engine.execute_tool_call.return_value = ToolResult(success=True, output="Written")
    loop.engine.run_post_tool_hooks.return_value = ""

    result = loop._execute_single_tool(tc, step=0)
    if result.result.output == "Written":
        ok("Empty hook output → result unchanged")
    else:
        fail("Empty hook", f"got {result.result.output!r}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: StopReason enum and _CLOSE_INSTRUCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_reason_and_instructions():
    section("StopReason enum and _CLOSE_INSTRUCTIONS")

    # 6.1 All 7 StopReason values
    members = list(StopReason)
    if len(members) == 7:
        ok("StopReason has exactly 7 members")
    else:
        fail("StopReason count", f"got {len(members)}")

    # 6.2 _CLOSE_INSTRUCTIONS keys
    expected_keys = {StopReason.MAX_STEPS, StopReason.BUDGET_EXCEEDED,
                     StopReason.CONTEXT_FULL, StopReason.TIMEOUT}
    if set(_CLOSE_INSTRUCTIONS.keys()) == expected_keys:
        ok("_CLOSE_INSTRUCTIONS has MAX_STEPS, BUDGET_EXCEEDED, CONTEXT_FULL, TIMEOUT")
    else:
        fail("Close instructions keys", f"got {set(_CLOSE_INSTRUCTIONS.keys())}")

    # 6.3 USER_INTERRUPT NOT in _CLOSE_INSTRUCTIONS
    if StopReason.USER_INTERRUPT not in _CLOSE_INSTRUCTIONS:
        ok("USER_INTERRUPT NOT in _CLOSE_INSTRUCTIONS (handled specially)")
    else:
        fail("USER_INTERRUPT in instructions")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test Parallel Execution & Safety Nets")
    print("=" * 60)

    test_should_parallelize()
    test_execute_tool_calls_batch()
    test_check_safety_nets()
    test_graceful_close()
    test_post_edit_hooks()
    test_stop_reason_and_instructions()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
