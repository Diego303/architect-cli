"""
Setup helpers for initializing tools.

Convenience functions for registering the standard system tools.
"""

from pathlib import Path
from typing import Any, Callable

from ..config.schema import CommandsConfig, WorkspaceConfig
from .commands import RunCommandTool
from .dispatch import DispatchSubagentTool
from .filesystem import DeleteFileTool, EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from .patch import ApplyPatchTool
from .registry import ToolRegistry
from .search import FindFilesTool, GrepTool, SearchCodeTool


def register_filesystem_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
) -> None:
    """Register all filesystem tools in the registry.

    Registers:
    - read_file
    - write_file
    - edit_file
    - apply_patch
    - list_files
    - delete_file (always registered; the tool itself checks allow_delete)

    Args:
        registry: ToolRegistry where to register the tools
        workspace_config: Workspace configuration
    """
    workspace_root = Path(workspace_config.root).resolve()

    registry.register(ReadFileTool(workspace_root))
    registry.register(WriteFileTool(workspace_root))
    registry.register(EditFileTool(workspace_root))
    registry.register(ApplyPatchTool(workspace_root))
    registry.register(ListFilesTool(workspace_root))

    # delete_file always registered so it appears in the LLM schema;
    # the tool rejects with a clear message if allow_delete=False.
    registry.register(
        DeleteFileTool(
            workspace_root,
            allow_delete=workspace_config.allow_delete,
        )
    )


def register_search_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
) -> None:
    """Register code search tools (F10).

    Registers:
    - search_code: regex search with context
    - grep: literal text search (uses system rg/grep if available)
    - find_files: file search by glob pattern

    Args:
        registry: ToolRegistry where to register the tools
        workspace_config: Workspace configuration
    """
    workspace_root = Path(workspace_config.root).resolve()

    registry.register(SearchCodeTool(workspace_root))
    registry.register(GrepTool(workspace_root))
    registry.register(FindFilesTool(workspace_root))


def register_command_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
    commands_config: CommandsConfig,
) -> None:
    """Register the run_command tool if enabled (F13).

    The tool is only registered if ``commands_config.enabled`` is True.
    If not enabled, the agent will receive a clear error when
    it tries to call it ("tool not found").

    Args:
        registry: ToolRegistry where to register the tools
        workspace_config: Workspace configuration
        commands_config: Configuration for the run_command tool
    """
    if not commands_config.enabled:
        return

    workspace_root = Path(workspace_config.root).resolve()
    registry.register(RunCommandTool(workspace_root, commands_config))


def register_all_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
    commands_config: CommandsConfig | None = None,
) -> None:
    """Register all available tools (filesystem + search + commands).

    Convenience function that combines register_filesystem_tools,
    register_search_tools and register_command_tools.

    Args:
        registry: ToolRegistry where to register the tools
        workspace_config: Workspace configuration
        commands_config: Configuration for run_command (F13). If None, uses defaults.
    """
    register_filesystem_tools(registry, workspace_config)
    register_search_tools(registry, workspace_config)
    if commands_config is None:
        commands_config = CommandsConfig()
    register_command_tools(registry, workspace_config, commands_config)


def register_dispatch_tool(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
    agent_factory: Callable[..., Any],
) -> None:
    """Register the dispatch_subagent tool (D1).

    Registered separately because it requires an agent_factory that is only
    available after configuring the AgentLoop.

    Args:
        registry: ToolRegistry where to register the tool.
        workspace_config: Workspace configuration.
        agent_factory: Callable that creates a configured AgentLoop.
    """
    workspace_root = str(Path(workspace_config.root).resolve())
    registry.register(DispatchSubagentTool(agent_factory, workspace_root))
