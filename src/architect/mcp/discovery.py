"""
MCP tool discovery and registration.

Connects to MCP servers, discovers their available tools,
and registers them in the ToolRegistry as local tools.
"""

import structlog
from typing import Any

from ..config.schema import MCPServerConfig
from ..tools.registry import ToolRegistry
from .adapter import MCPToolAdapter
from .client import MCPClient, MCPError

logger = structlog.get_logger()


class MCPDiscovery:
    """MCP tool discoverer and registrar.

    Connects to configured MCP servers, discovers their available
    tools, and registers them in the ToolRegistry so they are
    available to agents.
    """

    def __init__(self):
        """Initialize the discovery."""
        self.log = logger.bind(component="mcp_discovery")

    def discover_and_register(
        self,
        servers: list[MCPServerConfig],
        registry: ToolRegistry,
    ) -> dict[str, Any]:
        """Discover and register tools from all MCP servers.

        Args:
            servers: List of MCP server configurations
            registry: ToolRegistry where to register the tools

        Returns:
            Dict with discovery statistics:
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
        """Discover and register tools from a specific MCP server.

        Args:
            server_config: Server configuration
            registry: ToolRegistry where to register
            stats: Statistics dict to update

        Raises:
            MCPError: If there is an error connecting or listing tools
        """
        self.log.info(
            "mcp.discovery.server_start",
            server=server_config.name,
            url=server_config.url,
        )

        # Create MCP client
        client = MCPClient(server_config)

        try:
            # List available tools
            tools = client.list_tools()
            stats["tools_discovered"] += len(tools)

            self.log.info(
                "mcp.discovery.tools_found",
                server=server_config.name,
                count=len(tools),
            )

            # Register each tool
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
                    # Continue with the remaining tools

        except MCPError as e:
            # Re-raise MCP errors to be caught at the upper level
            raise

    def _register_tool(
        self,
        client: MCPClient,
        tool_def: dict,
        server_name: str,
        registry: ToolRegistry,
    ) -> None:
        """Register an individual MCP tool in the registry.

        Args:
            client: MCP client
            tool_def: Tool definition from MCP
            server_name: Name of the MCP server
            registry: ToolRegistry where to register
        """
        tool_name = tool_def.get("name", "unknown")

        # Create adapter
        adapter = MCPToolAdapter(
            client=client,
            tool_definition=tool_def,
            server_name=server_name,
        )

        # Register in the registry
        # allow_override=False because there may be multiple servers
        # with tools of the same name (the mcp_{server}_ prefix differentiates them)
        registry.register(adapter, allow_override=False)

        self.log.info(
            "mcp.discovery.tool_registered",
            server=server_name,
            tool=tool_name,
            full_name=adapter.name,
        )

    def discover_server_info(self, server_config: MCPServerConfig) -> dict:
        """Get information about an MCP server without registering tools.

        Useful for diagnostics and testing.

        Args:
            server_config: Server configuration

        Returns:
            Dict with server information:
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
