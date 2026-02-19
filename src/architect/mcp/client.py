"""
Cliente HTTP para servidores MCP (Model Context Protocol).

Implementa el protocolo JSON-RPC 2.0 para comunicación con
servidores MCP remotos vía HTTP.
"""

import os
from typing import Any

import httpx
import structlog

from ..config.schema import MCPServerConfig

logger = structlog.get_logger()


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

    Implementa el protocolo JSON-RPC 2.0 para comunicación con
    servidores MCP que exponen tools remotas.
    """

    def __init__(self, server_config: MCPServerConfig):
        """Inicializa el cliente MCP.

        Args:
            server_config: Configuración del servidor MCP
        """
        self.config = server_config
        self.base_url = server_config.url
        self.token = self._resolve_token()
        self.log = logger.bind(component="mcp_client", server=server_config.name)

        # Configurar headers
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers["Content-Type"] = "application/json"

        # Crear cliente HTTP
        self.http = httpx.Client(
            base_url=self.base_url,
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

        # Preparar request JSON-RPC 2.0
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 1,
        }

        try:
            response = self.http.post("/", json=request)
            response.raise_for_status()
        except httpx.HTTPError as e:
            self.log.error(
                "mcp.list_tools.connection_error",
                error=str(e),
                url=self.base_url,
            )
            raise MCPConnectionError(
                f"Error conectando a servidor MCP '{self.config.name}' en {self.base_url}: {e}"
            )

        # Parsear respuesta JSON-RPC
        try:
            data = response.json()
        except Exception as e:
            self.log.error("mcp.list_tools.parse_error", error=str(e))
            raise MCPError(f"Respuesta JSON inválida del servidor MCP: {e}")

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

        # Preparar request JSON-RPC 2.0
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": 2,
        }

        try:
            response = self.http.post("/", json=request)
            response.raise_for_status()
        except httpx.HTTPError as e:
            self.log.error(
                "mcp.call_tool.connection_error",
                tool=tool_name,
                error=str(e),
            )
            raise MCPConnectionError(
                f"Error ejecutando tool '{tool_name}' en servidor MCP: {e}"
            )

        # Parsear respuesta JSON-RPC
        try:
            data = response.json()
        except Exception as e:
            self.log.error("mcp.call_tool.parse_error", tool=tool_name, error=str(e))
            raise MCPToolCallError(f"Respuesta JSON inválida: {e}")

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
