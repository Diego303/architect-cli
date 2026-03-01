"""
MCP module - Client and adapter for Model Context Protocol.

Exports client, adapter, and discovery for remote MCP tools.
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
