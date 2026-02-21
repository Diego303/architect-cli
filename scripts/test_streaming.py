#!/usr/bin/env python3
"""
Test LLM Adapter Streaming: completion_stream, _parse_arguments, models.

Valida:
- StreamChunk y LLMResponse models
- _parse_arguments() con dict, JSON string, invalid
- _try_parse_text_tool_calls() fallback parsing
- completion_stream() con litellm mockeado
- _prepare_messages_with_caching()
- _normalize_response()

Ejecutar:
    python scripts/test_streaming.py
"""

import json
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

from architect.config.schema import LLMConfig
from architect.llm.adapter import LLMAdapter, LLMResponse, StreamChunk, ToolCall


# ── Fake streaming chunks ───────────────────────────────────────────────────

class FakeFunction:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class FakeToolCallDelta:
    def __init__(self, index=0, id=None, function_name=None, function_arguments=None):
        self.index = index
        self.id = id
        self.function = FakeFunction(name=function_name, arguments=function_arguments)


class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta or FakeDelta()
        self.finish_reason = finish_reason


class FakeUsage:
    def __init__(self, prompt_tokens=0, completion_tokens=0, total_tokens=0,
                 cache_read_input_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class FakeChunk:
    def __init__(self, content=None, tool_calls=None, finish_reason=None, usage=None):
        delta = FakeDelta(content=content, tool_calls=tool_calls)
        self.choices = [FakeChoice(delta=delta, finish_reason=finish_reason)]
        self.usage = usage


# ── Factory ──────────────────────────────────────────────────────────────────

def _make_adapter(prompt_caching=False):
    config = LLMConfig(model="gpt-4o", prompt_caching=prompt_caching)
    with patch.object(LLMAdapter, '_configure_litellm'):
        return LLMAdapter(config)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: StreamChunk and LLMResponse models
# ══════════════════════════════════════════════════════════════════════════════

def test_models():
    section("StreamChunk and LLMResponse models")

    # 1.1 StreamChunk creation
    sc = StreamChunk(type="content", data="hello")
    if sc.type == "content" and sc.data == "hello":
        ok("StreamChunk creation with type='content' and data")
    else:
        fail("StreamChunk creation")

    # 1.2 StreamChunk rejects extra fields
    try:
        StreamChunk(type="content", data="hello", extra="bad")
        fail("StreamChunk rejects extra fields", "did not raise")
    except Exception:
        ok("StreamChunk rejects extra fields (extra='forbid')")

    # 1.3 LLMResponse defaults
    r = LLMResponse()
    if r.content is None and r.tool_calls == [] and r.finish_reason == "stop" and r.usage is None:
        ok("LLMResponse defaults: content=None, tool_calls=[], finish_reason='stop', usage=None")
    else:
        fail("LLMResponse defaults")

    # 1.4 LLMResponse with full data
    tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/a.py"})
    r = LLMResponse(
        content="Done",
        tool_calls=[tc],
        finish_reason="tool_calls",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )
    if r.content == "Done" and len(r.tool_calls) == 1 and r.usage["total_tokens"] == 150:
        ok("LLMResponse with full data")
    else:
        fail("LLMResponse full data")

    # 1.5 ToolCall creation
    tc = ToolCall(id="call_abc", name="write_file", arguments={"path": "/b.py", "content": "x"})
    if tc.id == "call_abc" and tc.name == "write_file" and tc.arguments["content"] == "x":
        ok("ToolCall creation and validation")
    else:
        fail("ToolCall creation")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: _parse_arguments()
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_arguments():
    section("_parse_arguments()")
    adapter = _make_adapter()

    # 2.1 Dict → pass-through
    result = adapter._parse_arguments({"key": "value"})
    if result == {"key": "value"}:
        ok("Dict input → pass-through")
    else:
        fail("Dict pass-through", f"got {result}")

    # 2.2 Valid JSON string
    result = adapter._parse_arguments('{"name": "test", "count": 3}')
    if result == {"name": "test", "count": 3}:
        ok("Valid JSON string → parsed dict")
    else:
        fail("Valid JSON", f"got {result}")

    # 2.3 Invalid JSON string → {}
    result = adapter._parse_arguments("not valid json {{{")
    if result == {}:
        ok("Invalid JSON string → {}")
    else:
        fail("Invalid JSON", f"got {result}")

    # 2.4 Non-string non-dict → {}
    result = adapter._parse_arguments(12345)
    if result == {}:
        ok("Non-string non-dict → {}")
    else:
        fail("Non-string", f"got {result}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: _try_parse_text_tool_calls()
# ══════════════════════════════════════════════════════════════════════════════

def test_try_parse_text_tool_calls():
    section("_try_parse_text_tool_calls()")
    adapter = _make_adapter()

    # 3.1 Plain JSON with name + arguments
    content = json.dumps({"name": "read_file", "arguments": {"path": "/a.py"}})
    result = adapter._try_parse_text_tool_calls(content)
    if len(result) == 1 and result[0].name == "read_file":
        ok('Plain JSON {name, arguments} → [ToolCall]')
    else:
        fail("Plain JSON tool call", f"got {result}")

    # 3.2 JSON with "function" wrapper (OpenAI format)
    content = json.dumps({
        "id": "call_001", "type": "function",
        "function": {"name": "write_file", "arguments": {"path": "/b.py", "content": "hi"}},
    })
    result = adapter._try_parse_text_tool_calls(content)
    if len(result) == 1 and result[0].name == "write_file" and result[0].id == "call_001":
        ok('JSON with "function" wrapper → [ToolCall]')
    else:
        fail("OpenAI function wrapper", f"got {result}")

    # 3.3 JSON array
    content = json.dumps([
        {"name": "read_file", "arguments": {"path": "/a.py"}},
        {"name": "list_files", "arguments": {"directory": "/src"}},
    ])
    result = adapter._try_parse_text_tool_calls(content)
    if len(result) == 2 and result[0].name == "read_file" and result[1].name == "list_files":
        ok("JSON array → multiple ToolCalls")
    else:
        fail("JSON array", f"got {len(result)} tool calls")

    # 3.4 Markdown code block
    content = '```json\n{"name": "grep", "arguments": {"pattern": "foo"}}\n```'
    result = adapter._try_parse_text_tool_calls(content)
    if len(result) == 1 and result[0].name == "grep":
        ok("Markdown code block → strips and parses")
    else:
        fail("Markdown block", f"got {result}")

    # 3.5 No "name" → []
    content = json.dumps({"arguments": {"path": "/a.py"}})
    result = adapter._try_parse_text_tool_calls(content)
    if result == []:
        ok('JSON without "name" → []')
    else:
        fail("No name", f"got {result}")

    # 3.6 Name but no arguments/parameters/args → []
    content = json.dumps({"name": "read_file", "data": {"path": "/a.py"}})
    result = adapter._try_parse_text_tool_calls(content)
    if result == []:
        ok("Name but no arguments/parameters/args → []")
    else:
        fail("No args key", f"got {result}")

    # 3.7 Valid JSON but not tool call → []
    content = json.dumps({"key": "value", "other": 123})
    result = adapter._try_parse_text_tool_calls(content)
    if result == []:
        ok('Valid JSON but not tool call → []')
    else:
        fail("Not tool call", f"got {result}")

    # 3.8 Invalid JSON → []
    result = adapter._try_parse_text_tool_calls("Not JSON at all")
    if result == []:
        ok("Invalid JSON string → []")
    else:
        fail("Invalid JSON", f"got {result}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: completion_stream() with mocked litellm
# ══════════════════════════════════════════════════════════════════════════════

def test_completion_stream():
    section("completion_stream() with mocked litellm")
    adapter = _make_adapter()

    # 4.1 Simple text streaming
    chunks = [
        FakeChunk(content="Hello"),
        FakeChunk(content=" world"),
        FakeChunk(content="!"),
        FakeChunk(finish_reason="stop"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(messages=[{"role": "user", "content": "hi"}]))
    stream_chunks = [r for r in results if isinstance(r, StreamChunk)]
    final = [r for r in results if isinstance(r, LLMResponse)]
    if len(stream_chunks) == 3 and len(final) == 1:
        ok("Simple text: 3 StreamChunks + 1 LLMResponse")
    else:
        fail("Simple text", f"chunks={len(stream_chunks)}, responses={len(final)}")

    # 4.2 Content accumulation
    chunks = [
        FakeChunk(content="Hel"),
        FakeChunk(content="lo "),
        FakeChunk(content="world"),
        FakeChunk(finish_reason="stop"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(messages=[{"role": "user", "content": "hi"}]))
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    if final.content == "Hello world":
        ok("Content accumulation: 'Hel'+'lo '+'world' → 'Hello world'")
    else:
        fail("Accumulation", f"got {final.content!r}")

    # 4.3 Tool call delta accumulation
    chunks = [
        FakeChunk(tool_calls=[
            FakeToolCallDelta(index=0, id="call_123", function_name="read_file",
                              function_arguments='{"pa'),
        ]),
        FakeChunk(tool_calls=[
            FakeToolCallDelta(index=0, function_name=None,
                              function_arguments='th": "/a.py"}'),
        ]),
        FakeChunk(finish_reason="tool_calls"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(
            messages=[{"role": "user", "content": "read a.py"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        ))
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    if (len(final.tool_calls) == 1
            and final.tool_calls[0].id == "call_123"
            and final.tool_calls[0].name == "read_file"
            and final.tool_calls[0].arguments == {"path": "/a.py"}):
        ok("Tool call delta accumulation → complete ToolCall")
    else:
        fail("Tool call delta", f"got {final.tool_calls}")

    # 4.4 finish_reason captured
    chunks = [
        FakeChunk(content="thinking..."),
        FakeChunk(content=" done", finish_reason="length"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(messages=[{"role": "user", "content": "hi"}]))
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    if final.finish_reason == "length":
        ok("finish_reason captured from last chunk ('length')")
    else:
        fail("finish_reason", f"got {final.finish_reason!r}")

    # 4.5 Usage info from last chunk
    usage = FakeUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70,
                      cache_read_input_tokens=10)
    chunks = [
        FakeChunk(content="hi"),
        FakeChunk(finish_reason="stop", usage=usage),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(messages=[{"role": "user", "content": "hi"}]))
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    if (final.usage is not None
            and final.usage["prompt_tokens"] == 50
            and final.usage["cache_read_input_tokens"] == 10):
        ok("Usage info extracted (including cache_read_input_tokens)")
    else:
        fail("Usage info", f"got {final.usage}")

    # 4.6 Empty content chunks skipped
    chunks = [
        FakeChunk(content=None),
        FakeChunk(content="hello"),
        FakeChunk(content=None),
        FakeChunk(content=" there"),
        FakeChunk(finish_reason="stop"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(messages=[{"role": "user", "content": "hi"}]))
    stream_chunks = [r for r in results if isinstance(r, StreamChunk)]
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    if len(stream_chunks) == 2 and final.content == "hello there":
        ok("Empty content chunks (None) skipped, content='hello there'")
    else:
        fail("Empty chunks", f"chunks={len(stream_chunks)}, content={final.content!r}")

    # 4.7 Multiple tool calls across different indices
    chunks = [
        FakeChunk(tool_calls=[
            FakeToolCallDelta(index=0, id="call_a", function_name="read_file",
                              function_arguments='{"path": "/x.py"}'),
        ]),
        FakeChunk(tool_calls=[
            FakeToolCallDelta(index=1, id="call_b", function_name="list_files",
                              function_arguments='{"directory": "/src"}'),
        ]),
        FakeChunk(finish_reason="tool_calls"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(
            messages=[{"role": "user", "content": "read"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        ))
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    names = {tc.name for tc in final.tool_calls}
    if len(final.tool_calls) == 2 and "read_file" in names and "list_files" in names:
        ok("Multiple tool calls across indices → 2 ToolCalls")
    else:
        fail("Multiple tool calls", f"got {final.tool_calls}")

    # 4.8 No content, only tool calls → content is None
    chunks = [
        FakeChunk(tool_calls=[
            FakeToolCallDelta(index=0, id="call_only", function_name="grep",
                              function_arguments='{"pattern": "TODO"}'),
        ]),
        FakeChunk(finish_reason="tool_calls"),
    ]
    with patch("litellm.completion", return_value=iter(chunks)):
        results = list(adapter.completion_stream(
            messages=[{"role": "user", "content": "find"}],
            tools=[{"type": "function", "function": {"name": "grep"}}],
        ))
    final = [r for r in results if isinstance(r, LLMResponse)][0]
    if final.content is None and len(final.tool_calls) == 1:
        ok("No content, only tool calls → content is None")
    else:
        fail("No content", f"content={final.content!r}, tools={len(final.tool_calls)}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: _prepare_messages_with_caching()
# ══════════════════════════════════════════════════════════════════════════════

def test_prepare_messages_with_caching():
    section("_prepare_messages_with_caching()")

    # 5.1 prompt_caching=False → unchanged
    adapter = _make_adapter(prompt_caching=False)
    msgs = [{"role": "system", "content": "Helper."}, {"role": "user", "content": "Hello"}]
    result = adapter._prepare_messages_with_caching(msgs)
    if result == msgs:
        ok("prompt_caching=False → messages unchanged")
    else:
        fail("caching=False")

    # 5.2 prompt_caching=True + system string → adds cache_control
    adapter = _make_adapter(prompt_caching=True)
    msgs = [{"role": "system", "content": "Helper."}, {"role": "user", "content": "Hello"}]
    result = adapter._prepare_messages_with_caching(msgs)
    sys_msg = result[0]
    if (isinstance(sys_msg["content"], list)
            and len(sys_msg["content"]) == 1
            and sys_msg["content"][0]["text"] == "Helper."
            and sys_msg["content"][0]["cache_control"] == {"type": "ephemeral"}):
        ok("prompt_caching=True + system string → cache_control block added")
    else:
        fail("caching=True system", f"got {sys_msg}")

    # 5.3 Non-system messages unchanged
    adapter = _make_adapter(prompt_caching=True)
    msgs = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    result = adapter._prepare_messages_with_caching(msgs)
    if result[0] == msgs[0] and result[1] == msgs[1]:
        ok("prompt_caching=True + non-system → unchanged")
    else:
        fail("non-system msgs")

    # 5.4 System message already as list → preserved
    adapter = _make_adapter(prompt_caching=True)
    list_content = [{"type": "text", "text": "Part 1"}, {"type": "text", "text": "Part 2"}]
    msgs = [{"role": "system", "content": list_content}]
    result = adapter._prepare_messages_with_caching(msgs)
    if result[0]["content"] == list_content or result[0]["content"] is list_content:
        ok("System message already as list → preserved")
    else:
        fail("list content", f"got {result[0]['content']}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: _normalize_response()
# ══════════════════════════════════════════════════════════════════════════════

def _make_mock_response(content=None, tool_calls=None, finish_reason="stop", usage=None):
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    response = MagicMock()
    response.choices = [choice]

    if usage:
        u = MagicMock()
        u.prompt_tokens = usage.get("prompt_tokens", 0)
        u.completion_tokens = usage.get("completion_tokens", 0)
        u.total_tokens = usage.get("total_tokens", 0)
        u.cache_read_input_tokens = usage.get("cache_read_input_tokens", 0)
        response.usage = u
    else:
        response.usage = None

    return response


def _make_mock_tool_call(tc_id, name, arguments):
    tc = MagicMock()
    tc.id = tc_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def test_normalize_response():
    section("_normalize_response()")
    adapter = _make_adapter()

    # 6.1 Text-only response
    mock = _make_mock_response(content="Hello!", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    result = adapter._normalize_response(mock)
    if result.content == "Hello!" and result.tool_calls == [] and result.usage["prompt_tokens"] == 10:
        ok("Text-only → LLMResponse with content, no tool_calls")
    else:
        fail("Text-only normalize")

    # 6.2 Response with tool_calls
    tc1 = _make_mock_tool_call("call_1", "read_file", '{"path": "/foo.py"}')
    tc2 = _make_mock_tool_call("call_2", "grep", {"pattern": "TODO"})
    mock = _make_mock_response(content=None, tool_calls=[tc1, tc2], finish_reason="tool_calls")
    result = adapter._normalize_response(mock)
    if (len(result.tool_calls) == 2
            and result.tool_calls[0].name == "read_file"
            and result.tool_calls[0].arguments == {"path": "/foo.py"}
            and result.tool_calls[1].arguments == {"pattern": "TODO"}):
        ok("Response with tool_calls → ToolCall objects (string + dict args)")
    else:
        fail("Tool calls normalize", f"got {result.tool_calls}")

    # 6.3 Text tool calls in content (fallback)
    tool_json = json.dumps({"name": "find_files", "arguments": {"pattern": "*.py"}})
    mock = _make_mock_response(content=tool_json, tool_calls=None, finish_reason="stop")
    result = adapter._normalize_response(mock)
    if result.content is None and len(result.tool_calls) == 1 and result.tool_calls[0].name == "find_files":
        ok("Text tool calls in content → detected, converted, content=None")
    else:
        fail("Text tool calls fallback", f"content={result.content!r}, tools={len(result.tool_calls)}")

    # 6.4 Usage with cache_read_input_tokens
    mock = _make_mock_response(
        content="ok",
        usage={"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250, "cache_read_input_tokens": 150},
    )
    result = adapter._normalize_response(mock)
    if result.usage and result.usage["cache_read_input_tokens"] == 150:
        ok("Usage extraction with cache_read_input_tokens")
    else:
        fail("Usage cache tokens", f"got {result.usage}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test LLM Adapter Streaming")
    print("=" * 60)

    test_models()
    test_parse_arguments()
    test_try_parse_text_tool_calls()
    test_completion_stream()
    test_prepare_messages_with_caching()
    test_normalize_response()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
