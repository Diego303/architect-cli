#!/usr/bin/env python3
"""
Test MCP Client Internals: SSE parsing, init, response handling, adapter.

Valida:
- _parse_sse() con múltiples formatos SSE
- _parse_response() routing por content-type
- _resolve_token() prioridad de tokens
- _next_id() secuencia incremental
- MCPToolAdapter conversión de tools MCP a BaseTool
- MCPClient inicialización y headers

Ejecutar:
    python scripts/test_mcp_internals.py
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Suppress structlog output to keep test output clean
from architect.config.schema import LoggingConfig
from architect.logging.setup import configure_logging
configure_logging(LoggingConfig(), quiet=True)

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

from architect.config.schema import MCPServerConfig
from architect.mcp.adapter import MCPToolAdapter
from architect.mcp.client import MCPClient, MCPConnectionError, MCPError, MCPToolCallError
from architect.tools.base import ToolResult


# ── Factories ────────────────────────────────────────────────────────────────

def _make_config(url="http://localhost:8080/mcp", token=None, token_env=None):
    return MCPServerConfig(name="test-server", url=url, token=token, token_env=token_env)


def _make_client(config=None):
    """Create MCPClient with mocked httpx to avoid real connections."""
    if config is None:
        config = _make_config()
    with patch("architect.mcp.client.httpx.Client"):
        return MCPClient(config)


def _mock_response(content_type="application/json", body="", json_data=None):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.headers = {"content-type": content_type}
    resp.text = body
    if json_data is not None:
        resp.json.return_value = json_data
        resp.text = json.dumps(json_data)
    else:
        try:
            parsed = json.loads(body)
            resp.json.return_value = parsed
        except (json.JSONDecodeError, TypeError):
            resp.json.side_effect = Exception("Not valid JSON")
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: _parse_sse()
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_sse():
    section("_parse_sse()")

    client = _make_client()

    # 1.1 Valid SSE with "data:" prefix
    sse = 'data: {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}\n'
    try:
        result = client._parse_sse(sse)
        if result == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}:
            ok("Valid SSE with data: prefix extracts JSON-RPC")
        else:
            fail("Valid SSE", f"got {result}")
    except Exception as e:
        fail("Valid SSE", str(e))

    # 1.2 SSE with "event: message" line before data
    sse = 'event: message\ndata: {"jsonrpc": "2.0", "id": 2, "result": {"ok": true}}\n'
    try:
        result = client._parse_sse(sse)
        if result.get("id") == 2:
            ok("SSE with event: message before data works")
        else:
            fail("SSE with event:", f"got {result}")
    except Exception as e:
        fail("SSE with event:", str(e))

    # 1.3 Multiple data lines → returns first valid JSON-RPC
    sse = (
        'data: {"jsonrpc": "2.0", "id": 10, "result": {"first": true}}\n'
        '\n'
        'data: {"jsonrpc": "2.0", "id": 11, "result": {"second": true}}\n'
    )
    try:
        result = client._parse_sse(sse)
        if result.get("id") == 10:
            ok("Multiple data lines → returns first valid JSON-RPC")
        else:
            fail("Multiple data lines", f"got id={result.get('id')}")
    except Exception as e:
        fail("Multiple data lines", str(e))

    # 1.4 Empty data lines → skips them
    sse = 'data:\ndata:   \ndata: {"jsonrpc": "2.0", "id": 3, "result": {}}\n'
    try:
        result = client._parse_sse(sse)
        if result.get("id") == 3:
            ok("Empty data lines are skipped")
        else:
            fail("Empty data lines", f"got {result}")
    except Exception as e:
        fail("Empty data lines", str(e))

    # 1.5 Non-JSON data lines → skips them
    sse = 'data: not json\ndata: {"jsonrpc": "2.0", "id": 4, "result": {}}\n'
    try:
        result = client._parse_sse(sse)
        if result.get("id") == 4:
            ok("Non-JSON data lines skipped")
        else:
            fail("Non-JSON skip", f"got {result}")
    except Exception as e:
        fail("Non-JSON skip", str(e))

    # 1.6 No valid JSON-RPC → raises MCPError
    sse = "data: not json\nevent: heartbeat\n: comment\n"
    try:
        client._parse_sse(sse)
        fail("No valid JSON-RPC raises MCPError", "did not raise")
    except MCPError:
        ok("No valid JSON-RPC raises MCPError")
    except Exception as e:
        fail("No valid JSON-RPC", f"raised {type(e).__name__}")

    # 1.7 JSON without "jsonrpc" key → skips it
    sse = 'data: {"status": "ok"}\ndata: {"jsonrpc": "2.0", "id": 5, "result": {}}\n'
    try:
        result = client._parse_sse(sse)
        if result.get("id") == 5:
            ok("JSON without jsonrpc key skipped, returns real JSON-RPC")
        else:
            fail("No jsonrpc key", f"got {result}")
    except Exception as e:
        fail("No jsonrpc key", str(e))

    # 1.8 Empty string → raises MCPError
    try:
        client._parse_sse("")
        fail("Empty string raises MCPError", "did not raise")
    except MCPError:
        ok("Empty string raises MCPError")
    except Exception as e:
        fail("Empty string", f"raised {type(e).__name__}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: _parse_response()
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_response():
    section("_parse_response()")

    client = _make_client()

    # 2.1 Content-Type application/json → parses as JSON
    json_data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    resp = _mock_response(content_type="application/json", json_data=json_data)
    try:
        result = client._parse_response(resp)
        if result == json_data:
            ok("Content-Type application/json → parses as JSON")
        else:
            fail("application/json", f"got {result}")
    except Exception as e:
        fail("application/json", str(e))

    # 2.2 Content-Type text/event-stream → parses as SSE
    sse_body = 'data: {"jsonrpc": "2.0", "id": 2, "result": {}}\n'
    resp = _mock_response(content_type="text/event-stream", body=sse_body)
    try:
        result = client._parse_response(resp)
        if result.get("id") == 2:
            ok("Content-Type text/event-stream → parses as SSE")
        else:
            fail("text/event-stream", f"got {result}")
    except Exception as e:
        fail("text/event-stream", str(e))

    # 2.3 Content-Type with charset → still parses JSON
    json_data = {"jsonrpc": "2.0", "id": 3, "result": {}}
    resp = _mock_response(content_type="application/json; charset=utf-8", json_data=json_data)
    try:
        result = client._parse_response(resp)
        if result == json_data:
            ok("application/json; charset=utf-8 → still parses JSON")
        else:
            fail("JSON with charset", f"got {result}")
    except Exception as e:
        fail("JSON with charset", str(e))

    # 2.4 Unknown content-type with valid JSON → fallback JSON
    json_data = {"jsonrpc": "2.0", "id": 4, "result": {}}
    resp = _mock_response(content_type="text/plain", json_data=json_data)
    try:
        result = client._parse_response(resp)
        if result == json_data:
            ok("Unknown content-type with valid JSON → fallback works")
        else:
            fail("JSON fallback", f"got {result}")
    except Exception as e:
        fail("JSON fallback", str(e))

    # 2.5 Unknown content-type with valid SSE → fallback SSE
    sse_body = 'data: {"jsonrpc": "2.0", "id": 5, "result": {}}\n'
    resp = _mock_response(content_type="text/plain", body=sse_body)
    resp.json.side_effect = Exception("Not JSON")
    try:
        result = client._parse_response(resp)
        if result.get("id") == 5:
            ok("Unknown content-type with valid SSE → fallback works")
        else:
            fail("SSE fallback", f"got {result}")
    except Exception as e:
        fail("SSE fallback", str(e))

    # 2.6 Unknown content-type with garbage → raises MCPError
    resp = _mock_response(content_type="application/octet-stream", body="garbage")
    resp.json.side_effect = Exception("Not JSON")
    try:
        client._parse_response(resp)
        fail("Garbage body raises MCPError", "did not raise")
    except MCPError:
        ok("Garbage body raises MCPError")
    except Exception as e:
        fail("Garbage body", f"raised {type(e).__name__}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: _resolve_token()
# ══════════════════════════════════════════════════════════════════════════════

def test_resolve_token():
    section("_resolve_token()")

    # 3.1 config.token set → returns it
    config = _make_config(token="my-secret")
    client = _make_client(config)
    if client.token == "my-secret":
        ok("config.token set → returns it directly")
    else:
        fail("config.token direct", f"got {client.token!r}")

    # 3.2 config.token_env with existing env var
    env_var = "_TEST_MCP_TOKEN_RESOLVE"
    os.environ[env_var] = "from-env"
    try:
        config = _make_config(token_env=env_var)
        client = _make_client(config)
        if client.token == "from-env":
            ok("config.token_env with existing env var → returns from env")
        else:
            fail("token_env with env", f"got {client.token!r}")
    finally:
        del os.environ[env_var]

    # 3.3 config.token_env with missing env var → None
    config = _make_config(token_env="_NONEXISTENT_TOKEN_VAR_12345")
    client = _make_client(config)
    if client.token is None:
        ok("config.token_env with missing env var → None")
    else:
        fail("token_env missing", f"got {client.token!r}")

    # 3.4 Neither token nor token_env → None
    config = _make_config()
    client = _make_client(config)
    if client.token is None:
        ok("Neither token nor token_env → None")
    else:
        fail("Neither token", f"got {client.token!r}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: _next_id()
# ══════════════════════════════════════════════════════════════════════════════

def test_next_id():
    section("_next_id() and request ID sequence")

    client = _make_client()

    # 4.1 First call returns 1
    first = client._next_id()
    if first == 1:
        ok("First call returns 1")
    else:
        fail("First call", f"got {first}")

    # 4.2 Sequential calls increment
    second = client._next_id()
    third = client._next_id()
    if second == 2 and third == 3:
        ok("Sequential calls: 2, 3")
    else:
        fail("Sequential", f"got {second}, {third}")

    # 4.3 All IDs unique
    ids = {first, second, third}
    for _ in range(50):
        ids.add(client._next_id())
    if len(ids) == 53:
        ok("All 53 generated IDs are unique")
    else:
        fail("Uniqueness", f"only {len(ids)} unique out of 53")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: MCPToolAdapter
# ══════════════════════════════════════════════════════════════════════════════

def test_mcp_tool_adapter():
    section("MCPToolAdapter")

    mock_client = MagicMock(spec=MCPClient)

    tool_def = {
        "name": "search_docs",
        "description": "Search documentation",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "include_meta": {"type": "boolean"},
            },
            "required": ["query"],
        },
    }

    adapter = MCPToolAdapter(client=mock_client, tool_definition=tool_def, server_name="docs")

    # 5.1 Name is prefixed
    if adapter.name == "mcp_docs_search_docs":
        ok("Name prefixed: mcp_docs_search_docs")
    else:
        fail("Name prefix", f"got {adapter.name!r}")

    # 5.2 Description from tool_definition
    if adapter.description == "Search documentation":
        ok("Description from tool_definition")
    else:
        fail("Description", f"got {adapter.description!r}")

    # 5.3 Sensitive is True
    if adapter.sensitive is True:
        ok("sensitive is always True")
    else:
        fail("sensitive", f"got {adapter.sensitive}")

    # 5.4 Empty inputSchema → empty model
    empty_def = {"name": "ping", "description": "Ping"}
    empty_adapter = MCPToolAdapter(client=mock_client, tool_definition=empty_def, server_name="test")
    if len(empty_adapter.args_model.model_fields) == 0:
        ok("No inputSchema → empty args_model")
    else:
        fail("Empty model", f"fields: {list(empty_adapter.args_model.model_fields.keys())}")

    # 5.5 Properties create model fields
    fields = adapter.args_model.model_fields
    if "query" in fields and "max_results" in fields and "include_meta" in fields:
        ok("inputSchema properties → model fields created")
    else:
        fail("Model fields", f"got {list(fields.keys())}")

    # 5.6 Required fields have no default
    if fields["query"].is_required():
        ok("Required field 'query' has is_required=True")
    else:
        fail("Required field", "query is not required")

    # 5.7 Optional fields have default None
    if not fields["max_results"].is_required() and fields["max_results"].default is None:
        ok("Optional field 'max_results' has default None")
    else:
        fail("Optional field", f"required={fields['max_results'].is_required()}")

    # 5.8 Type mapping
    type_checks = {
        "string": str, "integer": int, "number": float,
        "boolean": bool, "array": list, "object": dict,
    }
    all_ok = True
    for json_type, py_type in type_checks.items():
        result = adapter._json_schema_type_to_python({"type": json_type})
        if result is not py_type:
            all_ok = False
    if all_ok:
        ok("_json_schema_type_to_python maps all 6 types correctly")
    else:
        fail("Type mapping")

    # 5.9 _extract_content with list of text blocks
    result = adapter._extract_content({
        "content": [{"type": "text", "text": "Line 1"}, {"type": "text", "text": "Line 2"}]
    })
    if result == "Line 1\nLine 2":
        ok("_extract_content: list of text blocks → joined with newline")
    else:
        fail("extract list", f"got {result!r}")

    # 5.10 _extract_content with string
    result = adapter._extract_content({"content": "Hello!"})
    if result == "Hello!":
        ok("_extract_content: string content → returned directly")
    else:
        fail("extract string", f"got {result!r}")

    # 5.11 _extract_content with "output" key
    result = adapter._extract_content({"output": "cmd result"})
    if result == "cmd result":
        ok("_extract_content: 'output' key fallback works")
    else:
        fail("extract output", f"got {result!r}")

    # 5.12 _extract_content with unknown structure → JSON dump
    result = adapter._extract_content({"foo": "bar", "baz": 42})
    try:
        parsed = json.loads(result)
        if parsed == {"foo": "bar", "baz": 42}:
            ok("_extract_content: unknown structure → JSON dump")
        else:
            fail("extract unknown", f"got {result!r}")
    except json.JSONDecodeError:
        fail("extract unknown", "not valid JSON")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5b: MCPToolAdapter.execute()
# ══════════════════════════════════════════════════════════════════════════════

def test_mcp_tool_adapter_execute():
    section("MCPToolAdapter.execute()")

    mock_client = MagicMock(spec=MCPClient)
    tool_def = {
        "name": "echo",
        "description": "Echo tool",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    }
    adapter = MCPToolAdapter(client=mock_client, tool_definition=tool_def, server_name="test")

    # Successful execution
    mock_client.call_tool.return_value = {"content": [{"type": "text", "text": "echoed: hi"}]}
    result = adapter.execute(message="hi")
    if isinstance(result, ToolResult) and result.success and result.output == "echoed: hi":
        ok("Successful execute → ToolResult(success=True)")
    else:
        fail("Successful execute", f"got success={result.success}, output={result.output!r}")

    # Calls with original name
    mock_client.call_tool.assert_called_with("echo", {"message": "hi"})
    ok("execute() calls client.call_tool with original tool name")

    # MCPConnectionError
    mock_client.call_tool.side_effect = MCPConnectionError("refused")
    result = adapter.execute(message="hi")
    if not result.success and result.error:
        ok("MCPConnectionError → ToolResult(success=False)")
    else:
        fail("MCPConnectionError", f"success={result.success}")

    # MCPToolCallError
    mock_client.call_tool.side_effect = MCPToolCallError("tool failed")
    result = adapter.execute(message="hi")
    if not result.success and result.error:
        ok("MCPToolCallError → ToolResult(success=False)")
    else:
        fail("MCPToolCallError", f"success={result.success}")

    # Unexpected exception
    mock_client.call_tool.side_effect = RuntimeError("unexpected")
    result = adapter.execute(message="hi")
    if not result.success and result.error:
        ok("Unexpected exception → ToolResult(success=False)")
    else:
        fail("Unexpected exception", f"success={result.success}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: MCPClient initialization
# ══════════════════════════════════════════════════════════════════════════════

def test_client_initialization():
    section("MCPClient initialization")

    # 6.1 Headers include Content-Type and Accept SSE
    config = _make_config()
    with patch("architect.mcp.client.httpx.Client") as MockHttp:
        MCPClient(config)
        headers = MockHttp.call_args.kwargs.get("headers", {})
        if headers.get("Content-Type") == "application/json":
            ok("Headers: Content-Type=application/json")
        else:
            fail("Content-Type", f"got {headers.get('Content-Type')!r}")
        if "text/event-stream" in headers.get("Accept", ""):
            ok("Headers: Accept includes text/event-stream")
        else:
            fail("Accept SSE", f"got {headers.get('Accept')!r}")

    # 6.2 Token in headers
    config = _make_config(token="bearer-test")
    with patch("architect.mcp.client.httpx.Client") as MockHttp:
        MCPClient(config)
        headers = MockHttp.call_args.kwargs.get("headers", {})
        if headers.get("Authorization") == "Bearer bearer-test":
            ok("Token: Authorization=Bearer bearer-test")
        else:
            fail("Token header", f"got {headers.get('Authorization')!r}")

    # 6.3 No Authorization without token
    config = _make_config()
    with patch("architect.mcp.client.httpx.Client") as MockHttp:
        MCPClient(config)
        headers = MockHttp.call_args.kwargs.get("headers", {})
        if "Authorization" not in headers:
            ok("No token: Authorization header absent")
        else:
            fail("No token", f"got {headers.get('Authorization')!r}")

    # 6.4 Base URL stored
    config = _make_config(url="http://custom:9090/mcp")
    client = _make_client(config)
    if client.base_url == "http://custom:9090/mcp":
        ok("Base URL stored from config")
    else:
        fail("Base URL", f"got {client.base_url!r}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: _ensure_initialized()
# ══════════════════════════════════════════════════════════════════════════════

def test_ensure_initialized():
    section("_ensure_initialized()")

    # 7.1 Already initialized → no HTTP call
    client = _make_client()
    client._initialized = True
    mock_http = MagicMock()
    client.http = mock_http
    client._ensure_initialized()
    mock_http.post.assert_not_called()
    ok("Already initialized → skips HTTP call")

    # 7.2 Successful handshake
    client = _make_client()
    mock_resp = MagicMock()
    mock_resp.headers = {
        "content-type": "application/json",
        "mcp-session-id": "sess-abc-123",
    }
    mock_resp.json.return_value = {
        "jsonrpc": "2.0", "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "test", "version": "1.0"},
            "capabilities": {},
        },
    }
    mock_http = MagicMock()
    mock_http.post.return_value = mock_resp
    client.http = mock_http

    client._ensure_initialized()
    if client._initialized:
        ok("Successful handshake sets _initialized=True")
    else:
        fail("initialized flag")
    if client._session_id == "sess-abc-123":
        ok("Handshake extracts mcp-session-id")
    else:
        fail("session-id", f"got {client._session_id!r}")

    # 7.3 HTTP error → MCPConnectionError
    import httpx
    client = _make_client()
    mock_http = MagicMock()
    mock_http.post.side_effect = httpx.ConnectError("Connection refused")
    client.http = mock_http
    try:
        client._ensure_initialized()
        fail("HTTP error raises MCPConnectionError", "did not raise")
    except MCPConnectionError:
        ok("HTTP error raises MCPConnectionError")
    except Exception as e:
        fail("HTTP error", f"raised {type(e).__name__}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test MCP Client Internals")
    print("=" * 60)

    test_parse_sse()
    test_parse_response()
    test_resolve_token()
    test_next_id()
    test_mcp_tool_adapter()
    test_mcp_tool_adapter_execute()
    test_client_initialization()
    test_ensure_initialized()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
