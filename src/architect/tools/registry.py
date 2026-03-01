"""
Centralized registry of available tools.

The ToolRegistry maintains all tools (local and remote MCP)
and provides methods for discovery, filtering, and access.
"""

from typing import Any

from .base import BaseTool


class ToolNotFoundError(Exception):
    """Error raised when a requested tool does not exist in the registry."""

    pass


class DuplicateToolError(Exception):
    """Error raised when attempting to register a tool with a duplicate name."""

    pass


class ToolRegistry:
    """Centralized tool registry.

    Maintains a dictionary of available tools and provides
    methods for registering, searching, and filtering tools.

    Tools can be local (filesystem, etc.) or remote (MCP).
    For the system, all are treated identically.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool, allow_override: bool = False) -> None:
        """Register a new tool.

        Args:
            tool: BaseTool instance to register
            allow_override: If True, allows overwriting existing tools

        Raises:
            DuplicateToolError: If the tool already exists and allow_override=False
        """
        if tool.name in self._tools and not allow_override:
            raise DuplicateToolError(
                f"Tool '{tool.name}' is already registered. "
                f"Use allow_override=True to overwrite."
            )

        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Get a tool by name.

        Args:
            name: Name of the tool

        Returns:
            BaseTool instance

        Raises:
            ToolNotFoundError: If the tool does not exist
        """
        if name not in self._tools:
            available = ", ".join(self._tools.keys()) if self._tools else "(none)"
            raise ToolNotFoundError(
                f"Tool '{name}' not found. " f"Available tools: {available}"
            )

        return self._tools[name]

    def list_all(self) -> list[BaseTool]:
        """List all registered tools.

        Returns:
            List of all tools, sorted by name
        """
        return sorted(self._tools.values(), key=lambda t: t.name)

    def get_schemas(self, allowed: list[str] | None = None) -> list[dict[str, Any]]:
        """Get JSON schemas of tools for the LLM.

        Silently skips tool names that are not registered (e.g., run_command
        when --no-commands is used, or MCP tools whose server is down).

        Args:
            allowed: List of allowed tool names, or None for all

        Returns:
            List of schemas in OpenAI function calling format

        Example:
            >>> registry.get_schemas(["read_file", "write_file"])
            [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "...",
                        "parameters": {...}
                    }
                },
                ...
            ]
        """
        if allowed:
            tools = [self._tools[name] for name in allowed if name in self._tools]
        else:
            tools = self.list_all()
        return [tool.get_schema() for tool in tools]

    def filter_by_names(self, names: list[str]) -> list[BaseTool]:
        """Filter tools by list of names.

        Args:
            names: List of tool names to include

        Returns:
            List of tools matching the names

        Raises:
            ToolNotFoundError: If any name does not exist in the registry

        Note:
            If names is empty, returns an empty list (not all tools)
        """
        if not names:
            return []

        tools = []
        for name in names:
            # get() will raise ToolNotFoundError if it doesn't exist
            tools.append(self.get(name))

        return tools

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered.

        Args:
            name: Name of the tool

        Returns:
            True if the tool exists, False otherwise
        """
        return name in self._tools

    def count(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def clear(self) -> None:
        """Remove all tools from the registry.

        Primarily useful for testing.
        """
        self._tools.clear()

    def __repr__(self) -> str:
        return f"<ToolRegistry({self.count()} tools)>"

    def __len__(self) -> int:
        return self.count()
