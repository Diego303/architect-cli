"""
HTTP client for MCP (Model Context Protocol) servers.

Implements the JSON-RPC 2.0 protocol over HTTP with support for:
- Initialization handshake (mandatory per MCP spec)
- Session ID management (mcp-session-id)
- SSE (Server-Sent Events) and plain JSON responses
- Bearer token authentication
"""

import json as _json
import os
from typing import Any

import httpx
import structlog

from ..config.schema import MCPServerConfig

logger = structlog.get_logger()

# Supported MCP protocol version
_MCP_PROTOCOL_VERSION = "2024-11-05"

# Client info for the handshake
_CLIENT_INFO = {"name": "architect-cli", "version": "1.0"}


class MCPError(Exception):
    """Base error for MCP operations."""

    pass


class MCPConnectionError(MCPError):
    """Connection error with MCP server."""

    pass


class MCPToolCallError(MCPError):
    """Error executing a tool on an MCP server."""

    pass


class MCPClient:
    """HTTP client for MCP servers.

    Implements the JSON-RPC 2.0 protocol with full support for the
    initialization handshake and SSE responses required by real
    MCP servers.

    Connection flow:
    1. POST initialize -> obtain session ID from headers
    2. POST tools/list (with session ID) -> list tools
    3. POST tools/call (with session ID) -> execute tools
    """

    def __init__(self, server_config: MCPServerConfig):
        """Initialize the MCP client.

        Args:
            server_config: MCP server configuration
        """
        self.config = server_config
        self.base_url = server_config.url
        self.log = logger.bind(component="mcp_client", server=server_config.name)
        self.token = self._resolve_token()
        self._session_id: str | None = None
        self._initialized = False
        self._request_id = 0

        # Configure headers (Accept SSE is mandatory for MCP)
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        # Create HTTP client (without base_url -- we use direct URL)
        self.http = httpx.Client(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )

        self.log.info(
            "mcp.client.initialized",
            url=self.base_url,
            has_token=self.token is not None,
        )

    def _resolve_token(self) -> str | None:
        """Resolve the authentication token.

        Order of precedence:
        1. Direct token in config
        2. Token from environment variable (token_env)

        Returns:
            Token if available, None otherwise
        """
        if self.config.token:
            return self.config.token

        if self.config.token_env:
            token = os.environ.get(self.config.token_env)
            if token:
                self.log.debug(
                    "mcp.token_from_env",
                    env_var=self.config.token_env,
                )
                return token

        return None

    def _next_id(self) -> int:
        """Generate the next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id

    def _ensure_initialized(self) -> None:
        """Ensure the client has completed the initialization handshake.

        The MCP protocol requires an `initialize` call before any other
        operation. The response includes the `mcp-session-id` in the
        headers, which must be used in all subsequent calls.

        Raises:
            MCPConnectionError: If initialization fails
        """
        if self._initialized:
            return

        self.log.info("mcp.initialize.start")

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        }

        try:
            response = self.http.post(self.base_url, json=request)
            response.raise_for_status()
        except httpx.HTTPError as e:
            self.log.error(
                "mcp.initialize.connection_error",
                error=str(e),
                url=self.base_url,
            )
            raise MCPConnectionError(
                f"Error initializing MCP server '{self.config.name}' "
                f"at {self.base_url}: {e}"
            )

        # Extract session ID from response header
        self._session_id = response.headers.get("mcp-session-id")
        if self._session_id:
            self.log.info(
                "mcp.initialize.session",
                session_id=self._session_id[:12] + "...",
            )

        # Parse response (can be SSE or JSON)
        data = self._parse_response(response)

        # Check for errors
        if "error" in data:
            error = data["error"]
            raise MCPConnectionError(
                f"Error in initialize: {error.get('message', 'Unknown error')}"
            )

        # Extract server info
        result = data.get("result", {})
        server_info = result.get("serverInfo", {})
        self.log.info(
            "mcp.initialize.success",
            server_name=server_info.get("name", "unknown"),
            server_version=server_info.get("version", "unknown"),
            protocol=result.get("protocolVersion", "unknown"),
        )

        self._initialized = True

    def _post_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request to the MCP server.

        Automatically handles:
        - Lazy initialization (if not done yet)
        - mcp-session-id header
        - Parsing of SSE and JSON responses

        Args:
            method: JSON-RPC method (e.g.: "tools/list", "tools/call")
            params: Method parameters

        Returns:
            Parsed JSON-RPC response (dict with "result" or "error")

        Raises:
            MCPConnectionError: If there is a network error
            MCPError: If the response is not parseable
        """
        self._ensure_initialized()

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

        # Add session ID if we have one
        headers = {}
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        try:
            response = self.http.post(
                self.base_url, json=request, headers=headers
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MCPConnectionError(
                f"Error in {method} to MCP server '{self.config.name}': {e}"
            )

        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse the HTTP response which can be SSE or JSON.

        MCP servers can respond in two formats:
        1. Plain JSON (Content-Type: application/json)
        2. SSE (Content-Type: text/event-stream) with format:
           event: message
           data: {"jsonrpc": "2.0", ...}

        Args:
            response: HTTP response

        Returns:
            Dict with the parsed JSON-RPC response

        Raises:
            MCPError: If the response cannot be parsed
        """
        content_type = response.headers.get("content-type", "")

        # Case 1: Plain JSON
        if "application/json" in content_type:
            try:
                return response.json()
            except Exception as e:
                raise MCPError(f"Invalid JSON response: {e}")

        # Case 2: SSE (Server-Sent Events)
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text)

        # Fallback: try JSON, then SSE
        try:
            return response.json()
        except Exception:
            pass

        try:
            return self._parse_sse(response.text)
        except Exception:
            pass

        raise MCPError(
            f"Unsupported response format (Content-Type: {content_type}). "
            f"Body: {response.text[:200]}"
        )

    def _parse_sse(self, text: str) -> dict[str, Any]:
        """Parse an SSE response and extract the JSON-RPC.

        SSE format:
            event: message
            data: {"jsonrpc": "2.0", "id": 1, "result": {...}}

        Only processes the first 'message' event with valid JSON-RPC data.

        Args:
            text: Complete SSE text

        Returns:
            Parsed JSON-RPC dict

        Raises:
            MCPError: If no valid event is found
        """
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                json_str = line[5:].strip()
                if not json_str:
                    continue
                try:
                    data = _json.loads(json_str)
                    if isinstance(data, dict) and "jsonrpc" in data:
                        return data
                except _json.JSONDecodeError:
                    continue

        raise MCPError(
            f"No valid JSON-RPC event found in SSE response. "
            f"Body: {text[:200]}"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools on the MCP server.

        Uses the JSON-RPC 'tools/list' method.

        Returns:
            List of tool definitions in MCP format

        Raises:
            MCPConnectionError: If there is a connection error
            MCPError: If the server returns an error
        """
        self.log.info("mcp.list_tools.start")

        data = self._post_rpc("tools/list", {})

        # Check for JSON-RPC errors
        if "error" in data:
            error = data["error"]
            self.log.error(
                "mcp.list_tools.rpc_error",
                code=error.get("code"),
                message=error.get("message"),
            )
            raise MCPError(
                f"MCP server error: {error.get('message', 'Unknown error')}"
            )

        # Extract tools
        result = data.get("result", {})
        tools = result.get("tools", [])

        self.log.info("mcp.list_tools.success", count=len(tools))

        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool on the MCP server.

        Uses the JSON-RPC 'tools/call' method.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments for the tool

        Returns:
            Tool execution result

        Raises:
            MCPConnectionError: If there is a connection error
            MCPToolCallError: If tool execution fails
        """
        self.log.info(
            "mcp.call_tool.start",
            tool=tool_name,
            args=self._sanitize_args(arguments),
        )

        try:
            data = self._post_rpc("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
        except MCPConnectionError:
            raise
        except MCPError as e:
            raise MCPToolCallError(str(e))

        # Check for JSON-RPC errors
        if "error" in data:
            error = data["error"]
            self.log.error(
                "mcp.call_tool.rpc_error",
                tool=tool_name,
                code=error.get("code"),
                message=error.get("message"),
            )
            raise MCPToolCallError(
                f"Error executing tool: {error.get('message', 'Unknown error')}"
            )

        # Extract result
        result = data.get("result", {})

        self.log.info("mcp.call_tool.success", tool=tool_name)

        return result

    def _sanitize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitize arguments for logging.

        Args:
            args: Original arguments

        Returns:
            Sanitized arguments
        """
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + f"... ({len(value)} chars)"
            else:
                sanitized[key] = value
        return sanitized

    def close(self) -> None:
        """Close the HTTP client."""
        self.http.close()
        self.log.info("mcp.client.closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *args):
        """Context manager exit."""
        self.close()

    def __repr__(self) -> str:
        return f"<MCPClient(server='{self.config.name}', url='{self.base_url}')>"
