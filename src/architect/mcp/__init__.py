"""
Módulo MCP - Cliente y adapter para Model Context Protocol.

Exporta cliente, adapter y discovery para tools MCP remotas.
"""

from .adapter import MCPToolAdapter
from .client import (
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPToolCallError,
)
from .discovery import MCPDiscovery

__all__ = [
    # Client
    "MCPClient",
    "MCPError",
    "MCPConnectionError",
    "MCPToolCallError",
    # Adapter
    "MCPToolAdapter",
    # Discovery
    "MCPDiscovery",
]
