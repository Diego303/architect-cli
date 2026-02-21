#!/usr/bin/env python3
"""
Test v3-M6: _summarize_args() — resumen inteligente de argumentos de tools.

Valida cada caso del match/case en _summarize_args():
- read_file, write_file, edit_file, apply_patch
- search_code, grep, list_files, find_files
- run_command, delete_file
- Tool desconocido, args vacíos, valores largos

Ejecutar:
    python scripts/test_v3_m6.py
"""

import sys
from pathlib import Path

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


# ── Import ───────────────────────────────────────────────────────────────────

from architect.logging.human import _summarize_args


# ── Tests: read_file ─────────────────────────────────────────────────────────

def test_read_file():
    section("read_file")

    result = _summarize_args("read_file", {"path": "src/main.py"})
    if result == "src/main.py":
        ok(f"read_file → '{result}'")
    else:
        fail(f"read_file → 'src/main.py'", f"got '{result}'")

    # Sin path
    result2 = _summarize_args("read_file", {})
    if result2 == "?":
        ok(f"read_file sin path → '?'")
    else:
        fail(f"read_file sin path → '?'", f"got '{result2}'")


# ── Tests: delete_file ───────────────────────────────────────────────────────

def test_delete_file():
    section("delete_file")

    result = _summarize_args("delete_file", {"path": "old_file.py"})
    if result == "old_file.py":
        ok(f"delete_file → '{result}'")
    else:
        fail(f"delete_file → 'old_file.py'", f"got '{result}'")


# ── Tests: write_file ────────────────────────────────────────────────────────

def test_write_file():
    section("write_file")

    # Test: path + líneas calculadas
    content = "line1\nline2\nline3"
    result = _summarize_args("write_file", {"path": "new.py", "content": content})
    if "new.py" in result and "3 líneas" in result:
        ok(f"write_file → '{result}'")
    else:
        fail(f"write_file → path + líneas", f"got '{result}'")

    # Test: content vacío → 1 línea
    result2 = _summarize_args("write_file", {"path": "empty.py", "content": ""})
    if "empty.py" in result2 and "1 líneas" in result2:
        ok(f"write_file vacío → '{result2}'")
    else:
        fail(f"write_file vacío → path + 1 línea", f"got '{result2}'")


# ── Tests: edit_file ─────────────────────────────────────────────────────────

def test_edit_file():
    section("edit_file")

    result = _summarize_args("edit_file", {
        "path": "main.py",
        "old_str": "def foo():\n    pass",
        "new_str": "def foo():\n    return 42\n    # done",
    })
    if "main.py" in result and "2" in result and "3" in result:
        ok(f"edit_file → '{result}' (2→3 líneas)")
    else:
        fail(f"edit_file → path + old→new líneas", f"got '{result}'")

    # Test: con old_content/new_content (nombres alternativos)
    result2 = _summarize_args("edit_file", {
        "path": "alt.py",
        "old_content": "a\nb",
        "new_content": "a\nb\nc\nd",
    })
    if "alt.py" in result2 and "2" in result2 and "4" in result2:
        ok(f"edit_file alt keys → '{result2}' (2→4 líneas)")
    else:
        fail(f"edit_file alt keys", f"got '{result2}'")


# ── Tests: apply_patch ───────────────────────────────────────────────────────

def test_apply_patch():
    section("apply_patch")

    patch_content = """--- a/main.py
+++ b/main.py
@@ -1,3 +1,4 @@
 import os
+import sys
-import old
 def main():
+    pass"""

    result = _summarize_args("apply_patch", {"path": "main.py", "patch": patch_content})
    if "main.py" in result:
        ok(f"apply_patch → '{result}'")
    else:
        fail(f"apply_patch → path + add/remove", f"got '{result}'")

    # Verify counts: +import sys, +    pass = 2 added; -import old = 1 removed
    if "+2" in result and "-1" in result:
        ok(f"apply_patch cuenta correcta: +2 -1")
    else:
        fail(f"apply_patch cuenta correcta: +2 -1", f"got '{result}'")


# ── Tests: search_code ───────────────────────────────────────────────────────

def test_search_code():
    section("search_code")

    result = _summarize_args("search_code", {"pattern": "def main", "path": "src/"})
    if '"def main"' in result and "src/" in result:
        ok(f"search_code → '{result}'")
    else:
        fail(f"search_code → pattern en path", f"got '{result}'")

    # Test: pattern largo truncado a 40 chars
    long_pattern = "a" * 50
    result2 = _summarize_args("search_code", {"pattern": long_pattern})
    if "..." in result2:
        ok(f"search_code pattern largo truncado")
    else:
        fail(f"search_code pattern largo truncado", f"got '{result2}'")

    # Test: sin path → default "."
    result3 = _summarize_args("search_code", {"pattern": "test"})
    if '"test"' in result3 and "." in result3:
        ok(f"search_code sin path → default '.'")
    else:
        fail(f"search_code sin path → default '.'", f"got '{result3}'")


# ── Tests: grep ──────────────────────────────────────────────────────────────

def test_grep():
    section("grep")

    result = _summarize_args("grep", {"text": "TODO", "path": "src/"})
    if '"TODO"' in result and "src/" in result:
        ok(f"grep → '{result}'")
    else:
        fail(f"grep → text en path", f"got '{result}'")

    # Test: con pattern key (alternativa)
    result2 = _summarize_args("grep", {"pattern": "FIXME"})
    if '"FIXME"' in result2:
        ok(f"grep con pattern key → '{result2}'")
    else:
        fail(f"grep con pattern key", f"got '{result2}'")

    # Test: text largo truncado
    long_text = "b" * 50
    result3 = _summarize_args("grep", {"text": long_text, "path": "."})
    if "..." in result3:
        ok(f"grep text largo truncado")
    else:
        fail(f"grep text largo truncado", f"got '{result3}'")


# ── Tests: list_files / find_files ───────────────────────────────────────────

def test_list_find_files():
    section("list_files / find_files")

    result = _summarize_args("list_files", {"path": "src/architect"})
    if result == "src/architect":
        ok(f"list_files → '{result}'")
    else:
        fail(f"list_files → 'src/architect'", f"got '{result}'")

    result2 = _summarize_args("find_files", {"pattern": "*.py"})
    if result2 == "*.py":
        ok(f"find_files → '{result2}'")
    else:
        fail(f"find_files → '*.py'", f"got '{result2}'")

    # Test: sin args → default "."
    result3 = _summarize_args("list_files", {})
    if result3 == ".":
        ok(f"list_files sin args → '.'")
    else:
        fail(f"list_files sin args → '.'", f"got '{result3}'")


# ── Tests: run_command ───────────────────────────────────────────────────────

def test_run_command():
    section("run_command")

    result = _summarize_args("run_command", {"command": "pytest tests/"})
    if result == "pytest tests/":
        ok(f"run_command → '{result}'")
    else:
        fail(f"run_command → 'pytest tests/'", f"got '{result}'")

    # Test: comando largo truncado a 60 chars
    long_cmd = "x" * 80
    result2 = _summarize_args("run_command", {"command": long_cmd})
    if len(result2) <= 64 and "..." in result2:
        ok(f"run_command largo truncado ({len(result2)} chars)")
    else:
        fail(f"run_command largo truncado", f"got len={len(result2)}, '{result2}'")


# ── Tests: tool desconocido ──────────────────────────────────────────────────

def test_unknown_tool():
    section("Tool desconocido (MCP u otra)")

    # Test: con args → muestra primer valor
    result = _summarize_args("mcp_custom_tool", {"url": "https://example.com"})
    if "https://example.com" in result:
        ok(f"Tool desconocido con args → primer valor '{result}'")
    else:
        fail(f"Tool desconocido con args → primer valor", f"got '{result}'")

    # Test: valor largo truncado a 60 chars
    result2 = _summarize_args("mcp_custom_tool", {"data": "y" * 100})
    if "..." in result2 and len(result2) <= 64:
        ok(f"Tool desconocido valor largo truncado")
    else:
        fail(f"Tool desconocido valor largo truncado", f"got '{result2}'")

    # Test: args vacíos → "(sin args)"
    result3 = _summarize_args("mcp_custom_tool", {})
    if result3 == "(sin args)":
        ok(f"Tool desconocido sin args → '{result3}'")
    else:
        fail(f"Tool desconocido sin args → '(sin args)'", f"got '{result3}'")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M6: _summarize_args()")
    print("=" * 60)

    test_read_file()
    test_delete_file()
    test_write_file()
    test_edit_file()
    test_apply_patch()
    test_search_code()
    test_grep()
    test_list_find_files()
    test_run_command()
    test_unknown_tool()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
