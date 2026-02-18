"""
Módulo de tools - Herramientas disponibles para los agentes.

Exporta todas las tools, el registry y los componentes base.
"""

from .base import BaseTool, ToolResult
from .filesystem import DeleteFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from .registry import DuplicateToolError, ToolNotFoundError, ToolRegistry
from .schemas import DeleteFileArgs, ListFilesArgs, ReadFileArgs, WriteFileArgs
from .setup import register_filesystem_tools

__all__ = [
    # Base
    "BaseTool",
    "ToolResult",
    # Registry
    "ToolRegistry",
    "ToolNotFoundError",
    "DuplicateToolError",
    # Filesystem tools
    "ReadFileTool",
    "WriteFileTool",
    "DeleteFileTool",
    "ListFilesTool",
    # Schemas
    "ReadFileArgs",
    "WriteFileArgs",
    "DeleteFileArgs",
    "ListFilesArgs",
    # Setup
    "register_filesystem_tools",
]
