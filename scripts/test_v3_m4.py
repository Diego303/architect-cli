#!/usr/bin/env python3
"""
Test v3-M4: Hooks system (actualizado para v4-A1 HookExecutor).

Valida:
- HookConfig validación Pydantic (esquema de config)
- HooksConfig defaults (backward compat con post_edit)
- HookExecutor: run_event(), hook chain, file_patterns, timeouts
- ExecutionEngine.run_post_tool_hooks() integración

Ejecutar:
    python scripts/test_v3_m4.py
"""

import sys
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

from architect.config.schema import HookConfig as HookConfigSchema, HooksConfig, HookItemConfig
from architect.core.hooks import (
    HookExecutor,
    HookEvent,
    HookDecision,
    HookResult,
    HooksRegistry,
    HookConfig,
)


# ── Tests: HookConfig (schema.py) Pydantic ──────────────────────────────────

def test_hook_config_schema():
    section("HookConfigSchema — validación Pydantic (config/schema.py)")

    # Test: campos requeridos
    try:
        h = HookConfigSchema(
            name="test-lint",
            command="ruff check {file}",
            file_patterns=["*.py"],
        )
        if h.name == "test-lint" and h.command == "ruff check {file}":
            ok("HookConfigSchema con campos requeridos")
        else:
            fail("HookConfigSchema con campos requeridos")
    except Exception as e:
        fail("HookConfigSchema con campos requeridos", str(e))

    # Test: enabled default True
    h2 = HookConfigSchema(name="t", command="echo", file_patterns=["*"])
    if h2.enabled is True:
        ok("enabled default True")
    else:
        fail("enabled default True", f"got {h2.enabled}")

    # Test: timeout default 10 (v4-A1 unified HookItemConfig default)
    if h2.timeout == 10:
        ok("timeout default 10")
    else:
        fail("timeout default 10", f"got {h2.timeout}")

    # Test: timeout custom
    h3 = HookConfigSchema(name="t", command="echo", file_patterns=["*"], timeout=30)
    if h3.timeout == 30:
        ok("timeout custom 30")
    else:
        fail("timeout custom 30", f"got {h3.timeout}")

    # Test: timeout validation (ge=1, le=300)
    try:
        HookConfigSchema(name="t", command="echo", file_patterns=["*"], timeout=0)
        fail("timeout=0 debería fallar (ge=1)")
    except Exception:
        ok("timeout=0 rechazado (ge=1)")

    try:
        HookConfigSchema(name="t", command="echo", file_patterns=["*"], timeout=301)
        fail("timeout=301 debería fallar (le=300)")
    except Exception:
        ok("timeout=301 rechazado (le=300)")

    # Test: extra fields forbidden
    try:
        HookConfigSchema(name="t", command="echo", file_patterns=["*"], extra_field="bad")
        fail("Extra field debería ser rechazado")
    except Exception:
        ok("Extra field rechazado (extra='forbid')")


# ── Tests: HooksConfig ───────────────────────────────────────────────────────

def test_hooks_config():
    section("HooksConfig")

    # Test: default empty post_edit
    hc = HooksConfig()
    if hc.post_edit == []:
        ok("post_edit default es lista vacía")
    else:
        fail("post_edit default es lista vacía", f"got {hc.post_edit}")

    # Test: con hooks
    hc2 = HooksConfig(post_edit=[
        HookConfigSchema(name="lint", command="ruff {file}", file_patterns=["*.py"]),
    ])
    if len(hc2.post_edit) == 1:
        ok("post_edit acepta lista de HookConfigSchema")
    else:
        fail("post_edit acepta lista de HookConfigSchema", f"got {len(hc2.post_edit)}")


# ── Tests: HookItemConfig (v4-A1 nuevo schema) ──────────────────────────────

def test_hook_item_config():
    section("HookItemConfig — v4-A1 Pydantic schema")

    # Test: defaults
    h = HookItemConfig(command="echo test")
    if h.enabled is True and h.timeout == 10 and h.async_ is False:
        ok("HookItemConfig defaults: enabled=True, timeout=10, async_=False")
    else:
        fail("HookItemConfig defaults", f"enabled={h.enabled}, timeout={h.timeout}, async_={h.async_}")

    # Test: matcher
    h2 = HookItemConfig(command="echo", matcher="write_file")
    if h2.matcher == "write_file":
        ok("HookItemConfig matcher field")
    else:
        fail("HookItemConfig matcher field", f"got {h2.matcher}")

    # Test: file_patterns
    h3 = HookItemConfig(command="echo", file_patterns=["*.py", "*.ts"])
    if h3.file_patterns == ["*.py", "*.ts"]:
        ok("HookItemConfig file_patterns")
    else:
        fail("HookItemConfig file_patterns", f"got {h3.file_patterns}")


# ── Tests: HookEvent enum ────────────────────────────────────────────────────

def test_hook_events():
    section("HookEvent enum — v4-A1")

    events = [e.value for e in HookEvent]
    expected_count = 10
    if len(events) == expected_count:
        ok(f"HookEvent tiene {expected_count} eventos: {events}")
    else:
        fail(f"HookEvent tiene {expected_count} eventos", f"got {len(events)}: {events}")

    # Check key events exist
    for event_name in ["pre_tool_use", "post_tool_use", "session_start", "session_end"]:
        if event_name in events:
            ok(f"Evento '{event_name}' presente")
        else:
            fail(f"Evento '{event_name}' presente")


# ── Tests: HookDecision enum ────────────────────────────────────────────────

def test_hook_decision():
    section("HookDecision enum")

    for decision in ["allow", "block", "modify"]:
        if hasattr(HookDecision, decision.upper()):
            ok(f"HookDecision.{decision.upper()} existe")
        else:
            fail(f"HookDecision.{decision.upper()} existe")


# ── Tests: HooksRegistry ────────────────────────────────────────────────────

def test_hooks_registry():
    section("HooksRegistry")

    # Test: empty registry
    registry = HooksRegistry(hooks={})
    if not registry.has_hooks():
        ok("Registry vacío → has_hooks()=False")
    else:
        fail("Registry vacío → has_hooks()=False")

    # Test: registry with hooks
    registry2 = HooksRegistry(hooks={
        HookEvent.PRE_TOOL_USE: [
            HookConfig(command="echo test", enabled=True, timeout=5)
        ]
    })
    if registry2.has_hooks():
        ok("Registry con hooks → has_hooks()=True")
    else:
        fail("Registry con hooks → has_hooks()=True")

    # Test: get_hooks returns correct hooks
    hooks = registry2.get_hooks(HookEvent.PRE_TOOL_USE)
    if len(hooks) == 1 and hooks[0].command == "echo test":
        ok("get_hooks retorna hooks correctos")
    else:
        fail("get_hooks retorna hooks correctos", f"got {hooks}")


# ── Tests: HookExecutor ─────────────────────────────────────────────────────

def test_hook_executor():
    section("HookExecutor — run_event()")

    # Test: run_event with allow hook (exit 0)
    registry = HooksRegistry(hooks={
        HookEvent.PRE_TOOL_USE: [
            HookConfig(command="echo allowed", enabled=True, timeout=5)
        ]
    })
    executor = HookExecutor(registry, workspace_root=Path("/tmp"))

    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="allowed\n", stderr="")
        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        if len(results) == 1 and results[0].decision == HookDecision.ALLOW:
            ok("Exit 0 → ALLOW")
        else:
            fail("Exit 0 → ALLOW", f"got {[r.decision for r in results]}")

    # Test: run_event with block hook (exit 2)
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=2, stdout="blocked\n", stderr="")
        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "write_file"})
        if len(results) == 1 and results[0].decision == HookDecision.BLOCK:
            ok("Exit 2 → BLOCK")
        else:
            fail("Exit 2 → BLOCK", f"got {[r.decision for r in results]}")

    # Test: run_event with modify hook (exit 0 + updatedInput JSON)
    # Note: MODIFY comes from exit 0 + JSON with "updatedInput", NOT exit 3
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"updatedInput": {"path": "safe.py"}}\n',
            stderr="",
        )
        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "write_file"})
        if len(results) == 1 and results[0].decision == HookDecision.MODIFY:
            ok("Exit 0 + updatedInput → MODIFY")
        else:
            fail("Exit 0 + updatedInput → MODIFY", f"got {[r.decision for r in results]}")

    # Test: no hooks for event → empty list
    results = executor.run_event(HookEvent.SESSION_START, {})
    if len(results) == 0:
        ok("Sin hooks para evento → lista vacía")
    else:
        fail("Sin hooks para evento → lista vacía", f"got {len(results)} results")


# ── Tests: HookExecutor timeout ─────────────────────────────────────────────

def test_hook_timeout():
    section("HookExecutor — timeout")

    import subprocess as sp

    registry = HooksRegistry(hooks={
        HookEvent.PRE_TOOL_USE: [
            HookConfig(command="sleep 100", enabled=True, timeout=1)
        ]
    })
    executor = HookExecutor(registry, workspace_root=Path("/tmp"))

    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.side_effect = sp.TimeoutExpired("sleep", 1)
        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        # On timeout, the hook should allow (error does not block)
        if len(results) == 1 and results[0].decision == HookDecision.ALLOW:
            ok("Timeout → ALLOW (error no bloquea)")
        else:
            decisions = [r.decision for r in results] if results else "[]"
            fail("Timeout → ALLOW (error no bloquea)", f"got {decisions}")


# ── Tests: ExecutionEngine.run_post_tool_hooks ───────────────────────────────

def test_engine_run_post_tool_hooks():
    section("ExecutionEngine.run_post_tool_hooks()")

    from architect.execution.engine import ExecutionEngine

    # Test: sin hooks configurados → None
    registry = MagicMock()
    config = MagicMock()
    engine = ExecutionEngine(registry=registry, config=config, hook_executor=None)

    result = engine.run_post_tool_hooks("edit_file", {"path": "test.py"}, "output", True)
    if result is None:
        ok("Sin hooks → None")
    else:
        fail("Sin hooks → None", f"got '{result}'")

    # Test: con hook_executor mock
    mock_executor = MagicMock()
    mock_executor.run_event.return_value = [
        MagicMock(decision=HookDecision.ALLOW, additional_context="lint passed")
    ]
    engine2 = ExecutionEngine(registry=registry, config=config, hook_executor=mock_executor)

    result2 = engine2.run_post_tool_hooks("edit_file", {"path": "test.py"}, "file written", True)
    if result2 is not None:
        ok(f"Con hooks → retorna output: '{result2[:40]}...'")
    else:
        fail("Con hooks → retorna output", "got None")

    # Test: dry_run → no ejecuta hooks
    engine3 = ExecutionEngine(registry=registry, config=config, hook_executor=mock_executor)
    engine3.dry_run = True
    mock_executor.run_event.reset_mock()
    result3 = engine3.run_post_tool_hooks("edit_file", {"path": "test.py"}, "output", True)
    if result3 is None:
        ok("dry_run=True → no ejecuta hooks")
    else:
        fail("dry_run=True → no ejecuta hooks", f"got '{result3}'")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M4: Hooks (v4-A1 HookExecutor)")
    print("=" * 60)

    test_hook_config_schema()
    test_hooks_config()
    test_hook_item_config()
    test_hook_events()
    test_hook_decision()
    test_hooks_registry()
    test_hook_executor()
    test_hook_timeout()
    test_engine_run_post_tool_hooks()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
