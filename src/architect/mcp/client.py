"""
Cliente HTTP para servidores MCP (Model Context Protocol).

Implementa el protocolo JSON-RPC 2.0 sobre HTTP con soporte para:
- Handshake de inicialización (obligatorio según spec MCP)
- Gestión de session ID (mcp-session-id)
- Respuestas SSE (Server-Sent Events) y JSON plano
- Autenticación Bearer token
"""

import json as _json
import os
from typing import Any

import httpx
import structlog

from ..config.schema import MCPServerConfig

logger = structlog.get_logger()

# Versión del protocolo MCP soportada
_MCP_PROTOCOL_VERSION = "2024-11-05"

# Info del cliente para el handshake
_CLIENT_INFO = {"name": "architect-cli", "version": "1.0"}


class MCPError(Exception):
    """Error base para operaciones MCP."""

    pass


class MCPConnectionError(MCPError):
    """Error de conexión con servidor MCP."""

    pass


class MCPToolCallError(MCPError):
    """Error al ejecutar una tool en servidor MCP."""

    pass


class MCPClient:
    """Cliente HTTP para servidores MCP.

    Implementa el protocolo JSON-RPC 2.0 con soporte completo para
    el handshake de inicialización y respuestas SSE que requieren
    los servidores MCP reales.

    Flujo de conexión:
    1. POST initialize → obtener session ID de headers
    2. POST tools/list (con session ID) → listar tools
    3. POST tools/call (con session ID) → ejecutar tools
    """

    def __init__(self, server_config: MCPServerConfig):
        """Inicializa el cliente MCP.

        Args:
            server_config: Configuración del servidor MCP
        """
        self.config = server_config
        self.base_url = server_config.url
        self.log = logger.bind(component="mcp_client", server=server_config.name)
        self.token = self._resolve_token()
        self._session_id: str | None = None
        self._initialized = False
        self._request_id = 0

        # Configurar headers (Accept SSE es obligatorio para MCP)
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        # Crear cliente HTTP (sin base_url — usamos URL directa)
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
        """Resuelve el token de autenticación.

        Orden de precedencia:
        1. token directo en config
        2. token desde variable de entorno (token_env)

        Returns:
            Token si está disponible, None en caso contrario
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
        """Genera el siguiente ID de request JSON-RPC."""
        self._request_id += 1
        return self._request_id

    def _ensure_initialized(self) -> None:
        """Asegura que el cliente ha completado el handshake de inicialización.

        El protocolo MCP requiere una llamada `initialize` antes de
        cualquier otra operación. La respuesta incluye el `mcp-session-id`
        en los headers, que debe usarse en todas las llamadas posteriores.

        Raises:
            MCPConnectionError: Si la inicialización falla
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
                f"Error inicializando servidor MCP '{self.config.name}' "
                f"en {self.base_url}: {e}"
            )

        # Extraer session ID del header de respuesta
        self._session_id = response.headers.get("mcp-session-id")
        if self._session_id:
            self.log.info(
                "mcp.initialize.session",
                session_id=self._session_id[:12] + "...",
            )

        # Parsear respuesta (puede ser SSE o JSON)
        data = self._parse_response(response)

        # Verificar que no hubo error
        if "error" in data:
            error = data["error"]
            raise MCPConnectionError(
                f"Error en initialize: {error.get('message', 'Unknown error')}"
            )

        # Extraer info del servidor
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
        """Envía una petición JSON-RPC al servidor MCP.

        Gestiona automáticamente:
        - Inicialización lazy (si no se ha hecho)
        - Header mcp-session-id
        - Parsing de respuestas SSE y JSON

        Args:
            method: Método JSON-RPC (ej: "tools/list", "tools/call")
            params: Parámetros del método

        Returns:
            Respuesta JSON-RPC parseada (dict con "result" o "error")

        Raises:
            MCPConnectionError: Si hay error de red
            MCPError: Si la respuesta no es parseable
        """
        self._ensure_initialized()

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

        # Añadir session ID si lo tenemos
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
                f"Error en {method} al servidor MCP '{self.config.name}': {e}"
            )

        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parsea la respuesta HTTP que puede ser SSE o JSON.

        Los servidores MCP pueden responder en dos formatos:
        1. JSON plano (Content-Type: application/json)
        2. SSE (Content-Type: text/event-stream) con formato:
           event: message
           data: {"jsonrpc": "2.0", ...}

        Args:
            response: Respuesta HTTP

        Returns:
            Dict con la respuesta JSON-RPC parseada

        Raises:
            MCPError: Si no se puede parsear la respuesta
        """
        content_type = response.headers.get("content-type", "")

        # Caso 1: JSON plano
        if "application/json" in content_type:
            try:
                return response.json()
            except Exception as e:
                raise MCPError(f"Respuesta JSON inválida: {e}")

        # Caso 2: SSE (Server-Sent Events)
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text)

        # Fallback: intentar JSON, luego SSE
        try:
            return response.json()
        except Exception:
            pass

        try:
            return self._parse_sse(response.text)
        except Exception:
            pass

        raise MCPError(
            f"Formato de respuesta no soportado (Content-Type: {content_type}). "
            f"Body: {response.text[:200]}"
        )

    def _parse_sse(self, text: str) -> dict[str, Any]:
        """Parsea una respuesta SSE y extrae el JSON-RPC.

        Formato SSE:
            event: message
            data: {"jsonrpc": "2.0", "id": 1, "result": {...}}

        Solo procesa el primer evento 'message' con data JSON-RPC válido.

        Args:
            text: Texto SSE completo

        Returns:
            Dict JSON-RPC parseado

        Raises:
            MCPError: Si no se encuentra un evento válido
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
            f"No se encontró evento JSON-RPC válido en respuesta SSE. "
            f"Body: {text[:200]}"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """Lista todas las tools disponibles en el servidor MCP.

        Usa el método JSON-RPC 'tools/list'.

        Returns:
            Lista de definiciones de tools en formato MCP

        Raises:
            MCPConnectionError: Si hay error de conexión
            MCPError: Si el servidor retorna error
        """
        self.log.info("mcp.list_tools.start")

        data = self._post_rpc("tools/list", {})

        # Verificar errores JSON-RPC
        if "error" in data:
            error = data["error"]
            self.log.error(
                "mcp.list_tools.rpc_error",
                code=error.get("code"),
                message=error.get("message"),
            )
            raise MCPError(
                f"Error en servidor MCP: {error.get('message', 'Unknown error')}"
            )

        # Extraer tools
        result = data.get("result", {})
        tools = result.get("tools", [])

        self.log.info("mcp.list_tools.success", count=len(tools))

        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una tool en el servidor MCP.

        Usa el método JSON-RPC 'tools/call'.

        Args:
            tool_name: Nombre de la tool a ejecutar
            arguments: Argumentos para la tool

        Returns:
            Resultado de la ejecución de la tool

        Raises:
            MCPConnectionError: Si hay error de conexión
            MCPToolCallError: Si la ejecución de la tool falla
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

        # Verificar errores JSON-RPC
        if "error" in data:
            error = data["error"]
            self.log.error(
                "mcp.call_tool.rpc_error",
                tool=tool_name,
                code=error.get("code"),
                message=error.get("message"),
            )
            raise MCPToolCallError(
                f"Error ejecutando tool: {error.get('message', 'Unknown error')}"
            )

        # Extraer resultado
        result = data.get("result", {})

        self.log.info("mcp.call_tool.success", tool=tool_name)

        return result

    def _sanitize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitiza argumentos para logging.

        Args:
            args: Argumentos originales

        Returns:
            Argumentos sanitizados
        """
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + f"... ({len(value)} chars)"
            else:
                sanitized[key] = value
        return sanitized

    def close(self) -> None:
        """Cierra el cliente HTTP."""
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
