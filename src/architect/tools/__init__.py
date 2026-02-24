"""
Módulo de tools - Herramientas disponibles para los agentes.

Exporta todas las tools, el registry y los componentes base.
"""

from .base import BaseTool, ToolResult
from .commands import RunCommandTool
from .dispatch import DispatchSubagentArgs, DispatchSubagentTool
from .filesystem import DeleteFileTool, EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from .patch import ApplyPatchTool, PatchError
from .registry import DuplicateToolError, ToolNotFoundError, ToolRegistry
from .schemas import (
    ApplyPatchArgs,
    DeleteFileArgs,
    EditFileArgs,
    FindFilesArgs,
    GrepArgs,
    ListFilesArgs,
    ReadFileArgs,
    RunCommandArgs,
    SearchCodeArgs,
    WriteFileArgs,
)
from .search import FindFilesTool, GrepTool, SearchCodeTool
from .setup import register_all_tools, register_command_tools, register_dispatch_tool, register_filesystem_tools, register_search_tools

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
    # Search tools (F10)
    "SearchCodeTool",
    "GrepTool",
    "FindFilesTool",
    # Command tool (F13)
    "RunCommandTool",
    # Dispatch tool (D1)
    "DispatchSubagentTool",
    "DispatchSubagentArgs",
    # Schemas
    "ReadFileArgs",
    "WriteFileArgs",
    "EditFileArgs",
    "ApplyPatchArgs",
    "DeleteFileArgs",
    "ListFilesArgs",
    "SearchCodeArgs",
    "GrepArgs",
    "FindFilesArgs",
    "RunCommandArgs",
    # Setup
    "register_filesystem_tools",
    "register_search_tools",
    "register_command_tools",
    "register_dispatch_tool",
    "register_all_tools",
]
