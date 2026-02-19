"""
Descubrimiento y registro de tools MCP.

Conecta a servidores MCP, descubre sus tools disponibles,
y las registra en el ToolRegistry como tools locales.
"""

import structlog

from ..config.schema import MCPServerConfig
from ..tools.registry import ToolRegistry
from .adapter import MCPToolAdapter
from .client import MCPClient, MCPError

logger = structlog.get_logger()


class MCPDiscovery:
    """Descubridor y registrador de tools MCP.

    Se conecta a servidores MCP configurados, descubre sus tools
    disponibles, y las registra en el ToolRegistry para que estén
    disponibles para los agentes.
    """

    def __init__(self):
        """Inicializa el discovery."""
        self.log = logger.bind(component="mcp_discovery")

    def discover_and_register(
        self,
        servers: list[MCPServerConfig],
        registry: ToolRegistry,
    ) -> dict[str, Any]:
        """Descubre y registra tools de todos los servidores MCP.

        Args:
            servers: Lista de configuraciones de servidores MCP
            registry: ToolRegistry donde registrar las tools

        Returns:
            Dict con estadísticas del descubrimiento:
            {
                "servers_total": int,
                "servers_success": int,
                "servers_failed": int,
                "tools_discovered": int,
                "tools_registered": int,
                "errors": list[str],
            }
        """
        stats = {
            "servers_total": len(servers),
            "servers_success": 0,
            "servers_failed": 0,
            "tools_discovered": 0,
            "tools_registered": 0,
            "errors": [],
        }

        if not servers:
            self.log.info("mcp.discovery.no_servers")
            return stats

        self.log.info("mcp.discovery.start", servers=len(servers))

        for server_config in servers:
            try:
                self._discover_server(server_config, registry, stats)
                stats["servers_success"] += 1
            except Exception as e:
                self.log.error(
                    "mcp.discovery.server_failed",
                    server=server_config.name,
                    error=str(e),
                )
                stats["servers_failed"] += 1
                stats["errors"].append(f"{server_config.name}: {str(e)}")

        self.log.info(
            "mcp.discovery.complete",
            servers_success=stats["servers_success"],
            servers_failed=stats["servers_failed"],
            tools_registered=stats["tools_registered"],
        )

        return stats

    def _discover_server(
        self,
        server_config: MCPServerConfig,
        registry: ToolRegistry,
        stats: dict,
    ) -> None:
        """Descubre y registra tools de un servidor MCP específico.

        Args:
            server_config: Configuración del servidor
            registry: ToolRegistry donde registrar
            stats: Dict de estadísticas a actualizar

        Raises:
            MCPError: Si hay error conectando o listando tools
        """
        self.log.info(
            "mcp.discovery.server_start",
            server=server_config.name,
            url=server_config.url,
        )

        # Crear cliente MCP
        client = MCPClient(server_config)

        try:
            # Listar tools disponibles
            tools = client.list_tools()
            stats["tools_discovered"] += len(tools)

            self.log.info(
                "mcp.discovery.tools_found",
                server=server_config.name,
                count=len(tools),
            )

            # Registrar cada tool
            for tool_def in tools:
                try:
                    self._register_tool(client, tool_def, server_config.name, registry)
                    stats["tools_registered"] += 1
                except Exception as e:
                    tool_name = tool_def.get("name", "unknown")
                    self.log.warning(
                        "mcp.discovery.tool_registration_failed",
                        server=server_config.name,
                        tool=tool_name,
                        error=str(e),
                    )
                    # Continuar con las demás tools

        except MCPError as e:
            # Re-lanzar errores de MCP para que se capturen en el nivel superior
            raise

    def _register_tool(
        self,
        client: MCPClient,
        tool_def: dict,
        server_name: str,
        registry: ToolRegistry,
    ) -> None:
        """Registra una tool MCP individual en el registry.

        Args:
            client: Cliente MCP
            tool_def: Definición de la tool desde MCP
            server_name: Nombre del servidor MCP
            registry: ToolRegistry donde registrar
        """
        tool_name = tool_def.get("name", "unknown")

        # Crear adapter
        adapter = MCPToolAdapter(
            client=client,
            tool_definition=tool_def,
            server_name=server_name,
        )

        # Registrar en el registry
        # allow_override=True porque pueden haber múltiples servidores
        # con tools del mismo nombre (el prefijo mcp_{server}_ las diferencia)
        registry.register(adapter, allow_override=False)

        self.log.info(
            "mcp.discovery.tool_registered",
            server=server_name,
            tool=tool_name,
            full_name=adapter.name,
        )

    def discover_server_info(self, server_config: MCPServerConfig) -> dict:
        """Obtiene información de un servidor MCP sin registrar tools.

        Útil para diagnóstico y testing.

        Args:
            server_config: Configuración del servidor

        Returns:
            Dict con información del servidor:
            {
                "name": str,
                "url": str,
                "connected": bool,
                "tools_count": int,
                "tools": list[str],
                "error": str | None,
            }
        """
        info = {
            "name": server_config.name,
            "url": server_config.url,
            "connected": False,
            "tools_count": 0,
            "tools": [],
            "error": None,
        }

        try:
            client = MCPClient(server_config)
            tools = client.list_tools()

            info["connected"] = True
            info["tools_count"] = len(tools)
            info["tools"] = [t.get("name", "unknown") for t in tools]

        except Exception as e:
            info["error"] = str(e)

        return info
