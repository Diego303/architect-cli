"""
Registro centralizado de tools disponibles.

El ToolRegistry mantiene todas las tools (locales y remotas MCP)
y proporciona métodos para descubrimiento, filtrado y acceso.
"""

from typing import Any

from .base import BaseTool


class ToolNotFoundError(Exception):
    """Error lanzado cuando una tool solicitada no existe en el registry."""

    pass


class DuplicateToolError(Exception):
    """Error lanzado cuando se intenta registrar una tool con nombre duplicado."""

    pass


class ToolRegistry:
    """Registro centralizado de tools.

    Mantiene un diccionario de tools disponibles y proporciona
    métodos para registrar, buscar y filtrar tools.

    Las tools pueden ser locales (filesystem, etc.) o remotas (MCP).
    Para el sistema, todas son tratadas de forma idéntica.
    """

    def __init__(self) -> None:
        """Inicializa un registry vacío."""
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool, allow_override: bool = False) -> None:
        """Registra una nueva tool.

        Args:
            tool: Instancia de BaseTool a registrar
            allow_override: Si True, permite sobrescribir tools existentes

        Raises:
            DuplicateToolError: Si la tool ya existe y allow_override=False
        """
        if tool.name in self._tools and not allow_override:
            raise DuplicateToolError(
                f"Tool '{tool.name}' ya está registrada. "
                f"Usa allow_override=True para sobrescribir."
            )

        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Obtiene una tool por nombre.

        Args:
            name: Nombre de la tool

        Returns:
            Instancia de BaseTool

        Raises:
            ToolNotFoundError: Si la tool no existe
        """
        if name not in self._tools:
            available = ", ".join(self._tools.keys()) if self._tools else "(ninguna)"
            raise ToolNotFoundError(
                f"Tool '{name}' no encontrada. " f"Tools disponibles: {available}"
            )

        return self._tools[name]

    def list_all(self) -> list[BaseTool]:
        """Lista todas las tools registradas.

        Returns:
            Lista de todas las tools, ordenadas por nombre
        """
        return sorted(self._tools.values(), key=lambda t: t.name)

    def get_schemas(self, allowed: list[str] | None = None) -> list[dict[str, Any]]:
        """Obtiene los JSON schemas de tools para el LLM.

        Args:
            allowed: Lista de nombres de tools permitidas, o None para todas

        Returns:
            Lista de schemas en formato OpenAI function calling

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
        tools = self.filter_by_names(allowed) if allowed else self.list_all()
        return [tool.get_schema() for tool in tools]

    def filter_by_names(self, names: list[str]) -> list[BaseTool]:
        """Filtra tools por lista de nombres.

        Args:
            names: Lista de nombres de tools a incluir

        Returns:
            Lista de tools que coinciden con los nombres

        Raises:
            ToolNotFoundError: Si algún nombre no existe en el registry

        Note:
            Si names es vacío, retorna lista vacía (no todas las tools)
        """
        if not names:
            return []

        tools = []
        for name in names:
            # get() lanzará ToolNotFoundError si no existe
            tools.append(self.get(name))

        return tools

    def has_tool(self, name: str) -> bool:
        """Verifica si una tool está registrada.

        Args:
            name: Nombre de la tool

        Returns:
            True si la tool existe, False en caso contrario
        """
        return name in self._tools

    def count(self) -> int:
        """Retorna el número de tools registradas."""
        return len(self._tools)

    def clear(self) -> None:
        """Elimina todas las tools del registry.

        Útil principalmente para testing.
        """
        self._tools.clear()

    def __repr__(self) -> str:
        return f"<ToolRegistry({self.count()} tools)>"

    def __len__(self) -> int:
        return self.count()
