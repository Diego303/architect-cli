#!/usr/bin/env python3
"""
Test v3-M4: PostEditHooks.

Valida:
- HookConfig validación Pydantic
- HooksConfig defaults
- PostEditHooks: EDIT_TOOLS, run_for_tool(), _matches(), _run_hook(),
  {file} placeholder, ARCHITECT_EDITED_FILE env var, _truncate(), _format_result()
- ExecutionEngine.run_post_edit_hooks() integración

Ejecutar:
    python scripts/test_v3_m4.py
"""

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

from architect.config.schema import HookConfig, HooksConfig
from architect.core.hooks import PostEditHooks, HookRunResult


# ── Tests: HookConfig Pydantic ───────────────────────────────────────────────

def test_hook_config():
    section("HookConfig — validación Pydantic")

    # Test: campos requeridos
    try:
        h = HookConfig(
            name="test-lint",
            command="ruff check {file}",
            file_patterns=["*.py"],
        )
        if h.name == "test-lint" and h.command == "ruff check {file}":
            ok("HookConfig con campos requeridos")
        else:
            fail("HookConfig con campos requeridos")
    except Exception as e:
        fail("HookConfig con campos requeridos", str(e))

    # Test: enabled default True
    h2 = HookConfig(name="t", command="echo", file_patterns=["*"])
    if h2.enabled is True:
        ok("enabled default True")
    else:
        fail("enabled default True", f"got {h2.enabled}")

    # Test: timeout default 15
    if h2.timeout == 15:
        ok("timeout default 15")
    else:
        fail("timeout default 15", f"got {h2.timeout}")

    # Test: timeout custom
    h3 = HookConfig(name="t", command="echo", file_patterns=["*"], timeout=30)
    if h3.timeout == 30:
        ok("timeout custom 30")
    else:
        fail("timeout custom 30", f"got {h3.timeout}")

    # Test: timeout validation (ge=1, le=300)
    try:
        HookConfig(name="t", command="echo", file_patterns=["*"], timeout=0)
        fail("timeout=0 debería fallar (ge=1)")
    except Exception:
        ok("timeout=0 rechazado (ge=1)")

    try:
        HookConfig(name="t", command="echo", file_patterns=["*"], timeout=301)
        fail("timeout=301 debería fallar (le=300)")
    except Exception:
        ok("timeout=301 rechazado (le=300)")

    # Test: extra fields forbidden
    try:
        HookConfig(name="t", command="echo", file_patterns=["*"], extra_field="bad")
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
        HookConfig(name="lint", command="ruff {file}", file_patterns=["*.py"]),
    ])
    if len(hc2.post_edit) == 1:
        ok("post_edit acepta lista de HookConfig")
    else:
        fail("post_edit acepta lista de HookConfig", f"got {len(hc2.post_edit)}")


# ── Tests: PostEditHooks.EDIT_TOOLS ──────────────────────────────────────────

def test_edit_tools():
    section("PostEditHooks.EDIT_TOOLS")

    expected = frozenset({"edit_file", "write_file", "apply_patch"})
    if PostEditHooks.EDIT_TOOLS == expected:
        ok(f"EDIT_TOOLS = {expected}")
    else:
        fail(f"EDIT_TOOLS = {expected}", f"got {PostEditHooks.EDIT_TOOLS}")

    if isinstance(PostEditHooks.EDIT_TOOLS, frozenset):
        ok("EDIT_TOOLS es frozenset")
    else:
        fail("EDIT_TOOLS es frozenset", f"type={type(PostEditHooks.EDIT_TOOLS)}")


# ── Tests: PostEditHooks.run_for_tool ────────────────────────────────────────

def _make_hook_config(name="test", command="echo ok", patterns=None, enabled=True, timeout=15):
    return HookConfig(
        name=name,
        command=command,
        file_patterns=patterns or ["*"],
        enabled=enabled,
        timeout=timeout,
    )


def test_run_for_tool():
    section("PostEditHooks.run_for_tool()")

    hooks = PostEditHooks(
        hooks=[_make_hook_config()],
        workspace_root=Path("/tmp"),
    )

    # Test: ignora tools no-edit
    for tool_name in ["read_file", "list_files", "search_code", "grep", "find_files"]:
        result = hooks.run_for_tool(tool_name, {"path": "test.py"})
        if result is None:
            ok(f"Ignora {tool_name}")
        else:
            fail(f"Ignora {tool_name}", f"got '{result}'")

    # Test: ejecuta para edit tools (with subprocess mocked)
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        for tool_name in ["edit_file", "write_file", "apply_patch"]:
            result = hooks.run_for_tool(tool_name, {"path": "test.py"})
            if result is not None:
                ok(f"Ejecuta para {tool_name}")
            else:
                fail(f"Ejecuta para {tool_name}", "got None")

    # Test: sin path en args → None
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        result = hooks.run_for_tool("edit_file", {})
        if result is None:
            ok("Sin path en args → None")
        else:
            fail("Sin path en args → None", f"got '{result}'")


# ── Tests: PostEditHooks._matches ────────────────────────────────────────────

def test_matches():
    section("PostEditHooks._matches()")

    hooks = PostEditHooks(hooks=[], workspace_root=Path("/tmp"))

    # Test: simple extension match
    if hooks._matches("main.py", "src/main.py", ["*.py"]):
        ok("*.py matches main.py")
    else:
        fail("*.py matches main.py")

    # Test: no match
    if not hooks._matches("main.py", "src/main.py", ["*.ts"]):
        ok("*.ts no matches main.py")
    else:
        fail("*.ts no matches main.py")

    # Test: path pattern match
    if hooks._matches("main.py", "src/main.py", ["src/*.py"]):
        ok("src/*.py matches src/main.py (full path)")
    else:
        fail("src/*.py matches src/main.py (full path)")

    # Test: multiple patterns
    if hooks._matches("style.css", "styles/style.css", ["*.py", "*.css"]):
        ok("Multi pattern: *.css matches style.css")
    else:
        fail("Multi pattern: *.css matches style.css")

    # Test: wildcard all
    if hooks._matches("anything.xyz", "dir/anything.xyz", ["*"]):
        ok("Pattern * matches everything")
    else:
        fail("Pattern * matches everything")


# ── Tests: PostEditHooks._truncate ───────────────────────────────────────────

def test_truncate():
    section("PostEditHooks._truncate()")

    hooks = PostEditHooks(hooks=[], workspace_root=Path("/tmp"))

    # Test: short text unchanged
    short = "hello world"
    if hooks._truncate(short, max_chars=100) == short:
        ok("Short text unchanged")
    else:
        fail("Short text unchanged")

    # Test: long text truncated
    long_text = "x" * 2000
    truncated = hooks._truncate(long_text, max_chars=100)
    if len(truncated) < len(long_text):
        ok(f"Long text truncated ({len(truncated)} < {len(long_text)})")
    else:
        fail("Long text truncated", f"len={len(truncated)}")

    if "truncado" in truncated:
        ok("Truncated text contains 'truncado' marker")
    else:
        fail("Truncated text contains 'truncado' marker")


# ── Tests: PostEditHooks._format_result ──────────────────────────────────────

def test_format_result():
    section("PostEditHooks._format_result()")

    hooks = PostEditHooks(hooks=[], workspace_root=Path("/tmp"))

    # Test: success
    result_ok = HookRunResult(hook_name="lint", success=True, output="All good", exit_code=0)
    formatted = hooks._format_result(result_ok)
    if "[Hook lint: OK]" in formatted and "All good" in formatted:
        ok("Success format: [Hook lint: OK] + output")
    else:
        fail("Success format", f"got '{formatted}'")

    # Test: failure
    result_fail = HookRunResult(hook_name="typecheck", success=False, output="Error en línea 5", exit_code=1)
    formatted2 = hooks._format_result(result_fail)
    if "FALLÓ" in formatted2 and "exit 1" in formatted2 and "Error en línea 5" in formatted2:
        ok("Failure format: FALLÓ (exit 1) + output")
    else:
        fail("Failure format", f"got '{formatted2}'")

    # Test: success without output
    result_no_out = HookRunResult(hook_name="check", success=True, output="", exit_code=0)
    formatted3 = hooks._format_result(result_no_out)
    if formatted3 == "[Hook check: OK]":
        ok("Success sin output: solo status line")
    else:
        fail("Success sin output: solo status line", f"got '{formatted3}'")


# ── Tests: PostEditHooks._run_hook ───────────────────────────────────────────

def test_run_hook():
    section("PostEditHooks._run_hook()")

    hooks = PostEditHooks(hooks=[], workspace_root=Path("/tmp"))

    hook_cfg = _make_hook_config(name="test-hook", command="echo {file}", timeout=15)

    # Test: subprocess success (rc=0)
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = hooks._run_hook(hook_cfg, "main.py")
        if result and result.success and result.exit_code == 0:
            ok("subprocess rc=0 → success=True")
        else:
            fail("subprocess rc=0 → success=True", f"got {result}")

        # Verify {file} placeholder replaced
        called_cmd = mock_run.call_args[0][0]
        if "main.py" in called_cmd:
            ok("{file} placeholder sustituido por path")
        else:
            fail("{file} placeholder sustituido por path", f"cmd='{called_cmd}'")

        # Verify ARCHITECT_EDITED_FILE env var
        called_env = mock_run.call_args[1].get("env", {})
        if called_env.get("ARCHITECT_EDITED_FILE") == "main.py":
            ok("ARCHITECT_EDITED_FILE env var seteada")
        else:
            fail("ARCHITECT_EDITED_FILE env var seteada", f"env={called_env}")

    # Test: subprocess failure (rc!=0)
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error found\n")
        result = hooks._run_hook(hook_cfg, "main.py")
        if result and not result.success and result.exit_code == 1:
            ok("subprocess rc=1 → success=False, exit_code=1")
        else:
            fail("subprocess rc=1 → success=False, exit_code=1", f"got {result}")

    # Test: subprocess timeout
    import subprocess
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 15)
        result = hooks._run_hook(hook_cfg, "main.py")
        if result and not result.success and result.exit_code == -1:
            ok("subprocess timeout → success=False, exit_code=-1")
        else:
            fail("subprocess timeout → success=False, exit_code=-1", f"got {result}")
        if result and "Timeout" in result.output:
            ok("timeout output menciona 'Timeout'")
        else:
            fail("timeout output menciona 'Timeout'")

    # Test: subprocess exception genérica
    with patch("architect.core.hooks.subprocess.run") as mock_run:
        mock_run.side_effect = OSError("permission denied")
        result = hooks._run_hook(hook_cfg, "main.py")
        if result is None:
            ok("OSError → retorna None (irrecuperable)")
        else:
            fail("OSError → retorna None", f"got {result}")


# ── Tests: Hook disabled ─────────────────────────────────────────────────────

def test_hook_disabled():
    section("Hook disabled")

    disabled_hook = _make_hook_config(name="disabled", enabled=False)
    hooks = PostEditHooks(
        hooks=[disabled_hook],
        workspace_root=Path("/tmp"),
    )

    # Disabled hooks are filtered out in __init__
    if len(hooks.hooks) == 0:
        ok("Hook disabled filtrado en __init__")
    else:
        fail("Hook disabled filtrado en __init__", f"got {len(hooks.hooks)} hooks")

    result = hooks.run_for_tool("edit_file", {"path": "test.py"})
    if result is None:
        ok("run_for_tool con hooks deshabilitados → None")
    else:
        fail("run_for_tool con hooks deshabilitados → None", f"got '{result}'")


# ── Tests: ExecutionEngine.run_post_edit_hooks ───────────────────────────────

def test_engine_run_post_edit_hooks():
    section("ExecutionEngine.run_post_edit_hooks()")

    from architect.execution.engine import ExecutionEngine

    # Test: sin hooks configurados → None
    registry = MagicMock()
    config = MagicMock()
    engine = ExecutionEngine(registry=registry, config=config, hooks=None)

    result = engine.run_post_edit_hooks("edit_file", {"path": "test.py"})
    if result is None:
        ok("Sin hooks → None")
    else:
        fail("Sin hooks → None", f"got '{result}'")

    # Test: con hooks mock
    mock_hooks = MagicMock()
    mock_hooks.run_for_tool.return_value = "[Hook lint: OK]\nAll good"
    engine2 = ExecutionEngine(registry=registry, config=config, hooks=mock_hooks)

    result2 = engine2.run_post_edit_hooks("edit_file", {"path": "test.py"})
    if result2 == "[Hook lint: OK]\nAll good":
        ok("Con hooks → retorna output de hooks")
    else:
        fail("Con hooks → retorna output de hooks", f"got '{result2}'")

    # Verify it delegates to hooks.run_for_tool
    mock_hooks.run_for_tool.assert_called_with("edit_file", {"path": "test.py"})
    ok("Delega a hooks.run_for_tool con args correctos")

    # Test: dry_run → no ejecuta hooks
    engine3 = ExecutionEngine(registry=registry, config=config, hooks=mock_hooks)
    engine3.dry_run = True
    mock_hooks.run_for_tool.reset_mock()
    result3 = engine3.run_post_edit_hooks("edit_file", {"path": "test.py"})
    if result3 is None:
        ok("dry_run=True → no ejecuta hooks")
    else:
        fail("dry_run=True → no ejecuta hooks", f"got '{result3}'")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M4: PostEditHooks")
    print("=" * 60)

    test_hook_config()
    test_hooks_config()
    test_edit_tools()
    test_run_for_tool()
    test_matches()
    test_truncate()
    test_format_result()
    test_run_hook()
    test_hook_disabled()
    test_engine_run_post_edit_hooks()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
