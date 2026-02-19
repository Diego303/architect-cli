"""
Módulo de tools - Herramientas disponibles para los agentes.

Exporta todas las tools, el registry y los componentes base.
"""

from .base import BaseTool, ToolResult
from .filesystem import DeleteFileTool, EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from .patch import ApplyPatchTool, PatchError
from .registry import DuplicateToolError, ToolNotFoundError, ToolRegistry
from .schemas import (
    ApplyPatchArgs,
    DeleteFileArgs,
    EditFileArgs,
    ListFilesArgs,
    ReadFileArgs,
    WriteFileArgs,
)
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
    "EditFileTool",
    "DeleteFileTool",
    "ListFilesTool",
    # Patch tool
    "ApplyPatchTool",
    "PatchError",
    # Schemas
    "ReadFileArgs",
    "WriteFileArgs",
    "EditFileArgs",
    "ApplyPatchArgs",
    "DeleteFileArgs",
    "ListFilesArgs",
    # Setup
    "register_filesystem_tools",
]
