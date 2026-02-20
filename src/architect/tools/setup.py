"""
Setup helpers para inicializar tools.

Funciones de conveniencia para registrar las tools estándar del sistema.
"""

from pathlib import Path

from ..config.schema import WorkspaceConfig
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


def register_all_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
) -> None:
    """Registra todas las tools disponibles (filesystem + búsqueda).

    Función de conveniencia que combina register_filesystem_tools
    y register_search_tools.

    Args:
        registry: ToolRegistry donde registrar las tools
        workspace_config: Configuración del workspace
    """
    register_filesystem_tools(registry, workspace_config)
    register_search_tools(registry, workspace_config)
