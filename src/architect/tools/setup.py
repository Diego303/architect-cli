"""
Setup helpers para inicializar tools.

Funciones de conveniencia para registrar las tools estándar del sistema.
"""

from pathlib import Path

from ..config.schema import CommandsConfig, WorkspaceConfig
from .commands import RunCommandTool
from .filesystem import DeleteFileTool, EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from .patch import ApplyPatchTool
from .registry import ToolRegistry
from .search import FindFilesTool, GrepTool, SearchCodeTool


def register_filesystem_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
) -> None:
    """Registra todas las tools del filesystem en el registry.

    Registra:
    - read_file
    - write_file
    - edit_file
    - apply_patch
    - list_files
    - delete_file (siempre registrada; la tool misma comprueba allow_delete)

    Args:
        registry: ToolRegistry donde registrar las tools
        workspace_config: Configuración del workspace
    """
    workspace_root = Path(workspace_config.root).resolve()

    registry.register(ReadFileTool(workspace_root))
    registry.register(WriteFileTool(workspace_root))
    registry.register(EditFileTool(workspace_root))
    registry.register(ApplyPatchTool(workspace_root))
    registry.register(ListFilesTool(workspace_root))

    # delete_file siempre registrada para que aparezca en el schema del LLM;
    # la tool rechaza con mensaje claro si allow_delete=False.
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
    """Registra las tools de búsqueda de código (F10).

    Registra:
    - search_code: búsqueda regex con contexto
    - grep: búsqueda de texto literal (usa rg/grep del sistema si está disponible)
    - find_files: búsqueda de archivos por patrón glob

    Args:
        registry: ToolRegistry donde registrar las tools
        workspace_config: Configuración del workspace
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
    """Registra la tool run_command si está habilitada (F13).

    La tool solo se registra si ``commands_config.enabled`` es True.
    Si no está habilitada, el agente recibirá un error claro cuando
    intente llamarla ("tool no encontrada").

    Args:
        registry: ToolRegistry donde registrar las tools
        workspace_config: Configuración del workspace
        commands_config: Configuración de la tool run_command
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
    """Registra todas las tools disponibles (filesystem + búsqueda + comandos).

    Función de conveniencia que combina register_filesystem_tools,
    register_search_tools y register_command_tools.

    Args:
        registry: ToolRegistry donde registrar las tools
        workspace_config: Configuración del workspace
        commands_config: Configuración de run_command (F13). Si es None, usa defaults.
    """
    register_filesystem_tools(registry, workspace_config)
    register_search_tools(registry, workspace_config)
    if commands_config is None:
        commands_config = CommandsConfig()
    register_command_tools(registry, workspace_config, commands_config)
