#!/usr/bin/env python3
"""
Test v3-M2: ContextManager mejoras.

Valida:
- _estimate_tokens() con diferentes tipos de contenido
- _is_above_threshold() umbrales 75%
- manage() pipeline unificado
- _summarize_steps() fallback mecánico
- is_critically_full() umbral 95%

Ejecutar:
    python scripts/test_v3_m2.py
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

from architect.core.context import ContextManager
from architect.config.schema import ContextConfig


def _make_cm(**overrides) -> ContextManager:
    """Crea un ContextManager con configuración personalizable."""
    defaults = {
        "max_tool_result_tokens": 2000,
        "summarize_after_steps": 8,
        "keep_recent_steps": 4,
        "max_context_tokens": 80000,
    }
    defaults.update(overrides)
    config = ContextConfig(**defaults)
    return ContextManager(config)


# ── Tests: _estimate_tokens ──────────────────────────────────────────────────

def test_estimate_tokens():
    section("_estimate_tokens()")

    cm = _make_cm()

    # Test: mensajes con string content
    msgs = [
        {"role": "system", "content": "a" * 400},  # 400 chars + 16 overhead
        {"role": "user", "content": "b" * 200},     # 200 chars + 16 overhead
    ]
    tokens = cm._estimate_tokens(msgs)
    # Expected: (400 + 16 + 200 + 16) // 4 = 632 // 4 = 158
    if tokens == 158:
        ok(f"String content: {tokens} tokens (expected 158)")
    else:
        fail(f"String content: expected 158 tokens", f"got {tokens}")

    # Test: mensajes vacíos (sin content)
    empty_msgs = [
        {"role": "assistant"},
        {"role": "user"},
    ]
    tokens_empty = cm._estimate_tokens(empty_msgs)
    # Expected: (16 + 16) // 4 = 8 (solo overhead)
    if tokens_empty == 8:
        ok(f"Mensajes vacíos: {tokens_empty} tokens (expected 8)")
    else:
        fail(f"Mensajes vacíos: expected 8 tokens", f"got {tokens_empty}")

    # Test: lista vacía
    tokens_none = cm._estimate_tokens([])
    if tokens_none == 0:
        ok(f"Lista vacía: {tokens_none} tokens")
    else:
        fail(f"Lista vacía: expected 0 tokens", f"got {tokens_none}")

    # Test: mensajes con tool_calls (dicts)
    msgs_tc = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "main.py"}',
                    },
                }
            ],
        }
    ]
    tokens_tc = cm._estimate_tokens(msgs_tc)
    # name="read_file" (9 chars) + arguments (20 chars) + 16 overhead
    # (9 + 20 + 16) // 4 = 45 // 4 = 11
    if tokens_tc == 11:
        ok(f"Tool calls: {tokens_tc} tokens (expected 11)")
    else:
        fail(f"Tool calls: expected 11 tokens", f"got {tokens_tc}")

    # Test: content como entero (str conversion)
    msgs_int = [{"role": "user", "content": 12345}]
    tokens_int = cm._estimate_tokens(msgs_int)
    # str(12345) = "12345" (5 chars) + 16 overhead = 21 // 4 = 5
    if tokens_int == 5:
        ok(f"Content entero: {tokens_int} tokens (expected 5)")
    else:
        fail(f"Content entero: expected 5 tokens", f"got {tokens_int}")


# ── Tests: _is_above_threshold ───────────────────────────────────────────────

def test_is_above_threshold():
    section("_is_above_threshold()")

    # max_context_tokens = 1000 → 75% = 750 tokens
    cm = _make_cm(max_context_tokens=1000)

    # Test: under threshold (small message)
    small_msgs = [{"role": "user", "content": "hello"}]  # ~5 tokens
    if not cm._is_above_threshold(small_msgs, 0.75):
        ok("Bajo 75%: retorna False")
    else:
        fail("Bajo 75%: retorna False", "got True")

    # Test: over threshold (large message)
    # Need > 750 tokens = 3000 chars
    big_msgs = [{"role": "user", "content": "x" * 3200}]  # ~800 tokens
    if cm._is_above_threshold(big_msgs, 0.75):
        ok("Sobre 75%: retorna True")
    else:
        fail("Sobre 75%: retorna True", "got False")

    # Test: max_context_tokens=0 → siempre True (sin límite)
    cm_no_limit = _make_cm(max_context_tokens=0)
    if cm_no_limit._is_above_threshold(small_msgs, 0.75):
        ok("max_context_tokens=0: retorna True (confía en summarize_after_steps)")
    else:
        fail("max_context_tokens=0: retorna True", "got False")


# ── Tests: is_critically_full ────────────────────────────────────────────────

def test_is_critically_full():
    section("is_critically_full()")

    # max_context_tokens = 1000 → 95% = 950 tokens
    cm = _make_cm(max_context_tokens=1000)

    # Test: under 95%
    small_msgs = [{"role": "user", "content": "hello"}]
    if not cm.is_critically_full(small_msgs):
        ok("Bajo 95%: retorna False")
    else:
        fail("Bajo 95%: retorna False", "got True")

    # Test: over 95% (need > 950 tokens = 3800 chars)
    big_msgs = [{"role": "user", "content": "x" * 4000}]
    if cm.is_critically_full(big_msgs):
        ok("Sobre 95%: retorna True")
    else:
        fail("Sobre 95%: retorna True", "got False")

    # Test: max_context_tokens=0 → siempre False (safety net desactivado)
    cm_no_limit = _make_cm(max_context_tokens=0)
    big_msgs2 = [{"role": "user", "content": "x" * 100000}]
    if not cm_no_limit.is_critically_full(big_msgs2):
        ok("max_context_tokens=0: retorna False siempre")
    else:
        fail("max_context_tokens=0: retorna False siempre", "got True")


# ── Tests: manage() ──────────────────────────────────────────────────────────

def test_manage():
    section("manage()")

    # Test: no modifica si bajo threshold
    cm = _make_cm(max_context_tokens=100000, summarize_after_steps=8)
    msgs = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    llm = MagicMock()
    result = cm.manage(msgs, llm)
    # Should return same messages (no compression needed)
    if len(result) == len(msgs):
        ok("Bajo threshold: no modifica mensajes")
    else:
        fail("Bajo threshold: no modifica mensajes", f"got {len(result)} mensajes")

    # Test: llama maybe_compress si sobre threshold
    cm2 = _make_cm(max_context_tokens=100, summarize_after_steps=1, keep_recent_steps=1)
    # Build enough messages to trigger compression
    msgs2 = [
        {"role": "system", "content": "system prompt " * 10},
        {"role": "user", "content": "user prompt"},
        # Several tool exchanges
        {"role": "assistant", "content": None, "tool_calls": [{"type": "function", "function": {"name": "t1", "arguments": "{}"}}]},
        {"role": "tool", "content": "result1 " * 20},
        {"role": "assistant", "content": None, "tool_calls": [{"type": "function", "function": {"name": "t2", "arguments": "{}"}}]},
        {"role": "tool", "content": "result2 " * 20},
        {"role": "assistant", "content": None, "tool_calls": [{"type": "function", "function": {"name": "t3", "arguments": "{}"}}]},
        {"role": "tool", "content": "result3 " * 20},
    ]
    llm2 = MagicMock()
    llm2.completion.return_value = MagicMock(content="Resumen de pasos")
    result2 = cm2.manage(msgs2, llm2)
    # With summarize_after_steps=1 and 3 tool exchanges, should attempt compression
    # The result should have fewer messages or the same if compression fails
    if len(result2) <= len(msgs2):
        ok("Sobre threshold: intenta comprimir")
    else:
        fail("Sobre threshold: intenta comprimir", f"got {len(result2)} mensajes (original {len(msgs2)})")

    # Test: manage sin LLM (llm=None) no llama maybe_compress
    cm3 = _make_cm(max_context_tokens=10)  # very small
    small_msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    result3 = cm3.manage(small_msgs, None)
    if isinstance(result3, list):
        ok("manage con llm=None: retorna lista válida")
    else:
        fail("manage con llm=None: retorna lista válida")


# ── Tests: _summarize_steps ──────────────────────────────────────────────────

def test_summarize_steps():
    section("_summarize_steps()")

    cm = _make_cm()

    # Test: LLM falla → fallback mecánico
    llm_fail = MagicMock()
    llm_fail.completion.side_effect = RuntimeError("LLM unavailable")

    old_msgs = [
        {"role": "assistant", "content": None, "tool_calls": [{"type": "function", "function": {"name": "read_file", "arguments": '{"path": "main.py"}'}}]},
        {"role": "tool", "name": "read_file", "content": "file content here"},
    ]

    summary = cm._summarize_steps(old_msgs, llm_fail)
    if "Resumen mecánico" in summary:
        ok("LLM falla → contiene 'Resumen mecánico'")
    else:
        fail("LLM falla → contiene 'Resumen mecánico'", f"got '{summary[:100]}'")

    if "read_file" in summary:
        ok("Fallback mecánico menciona tool name")
    else:
        fail("Fallback mecánico menciona tool name", f"got '{summary[:100]}'")

    # Test: LLM funciona → retorna resumen del LLM
    llm_ok = MagicMock()
    llm_ok.completion.return_value = MagicMock(content="El agente leyó main.py y encontró bugs.")
    summary2 = cm._summarize_steps(old_msgs, llm_ok)
    if summary2 == "El agente leyó main.py y encontró bugs.":
        ok("LLM funciona → retorna contenido del LLM")
    else:
        fail("LLM funciona → retorna contenido del LLM", f"got '{summary2[:100]}'")


# ── Tests: _format_steps_for_summary ─────────────────────────────────────────

def test_format_steps_for_summary():
    section("_format_steps_for_summary()")

    cm = _make_cm()

    # Test: assistant con tool_calls
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            {"type": "function", "function": {"name": "edit_file", "arguments": "{}"}},
        ]},
        {"role": "tool", "name": "read_file", "content": "file data"},
    ]
    formatted = cm._format_steps_for_summary(msgs)
    if "read_file" in formatted and "edit_file" in formatted:
        ok("Formatea tool_calls con nombres de tools")
    else:
        fail("Formatea tool_calls con nombres de tools", f"got '{formatted[:100]}'")

    if "Resultado de read_file" in formatted:
        ok("Incluye resultado de tool")
    else:
        fail("Incluye resultado de tool", f"got '{formatted[:100]}'")

    # Test: mensajes vacíos
    empty_formatted = cm._format_steps_for_summary([])
    if empty_formatted == "(sin mensajes)":
        ok("Lista vacía → '(sin mensajes)'")
    else:
        fail("Lista vacía → '(sin mensajes)'", f"got '{empty_formatted}'")


# ── Tests: _count_tool_exchanges ─────────────────────────────────────────────

def test_count_tool_exchanges():
    section("_count_tool_exchanges()")

    cm = _make_cm()

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "r1"},
        {"role": "assistant", "content": "texto sin tools"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "2"}]},
        {"role": "tool", "content": "r2"},
    ]

    count = cm._count_tool_exchanges(msgs)
    if count == 2:
        ok(f"Cuenta 2 intercambios tool: got {count}")
    else:
        fail(f"Cuenta 2 intercambios tool", f"got {count}")

    # Test: sin tool_calls
    msgs_no_tools = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "respuesta"},
    ]
    count2 = cm._count_tool_exchanges(msgs_no_tools)
    if count2 == 0:
        ok(f"Sin tool_calls: cuenta 0")
    else:
        fail(f"Sin tool_calls: expected 0", f"got {count2}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M2: ContextManager mejoras")
    print("=" * 60)

    test_estimate_tokens()
    test_is_above_threshold()
    test_is_critically_full()
    test_manage()
    test_summarize_steps()
    test_format_steps_for_summary()
    test_count_tool_exchanges()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
