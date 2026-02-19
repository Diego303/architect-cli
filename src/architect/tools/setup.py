"""
Setup helpers para inicializar tools.

Funciones de conveniencia para registrar las tools estándar del sistema.
"""

from pathlib import Path

from ..config.schema import WorkspaceConfig
from .filesystem import DeleteFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from .registry import ToolRegistry


def register_filesystem_tools(
    registry: ToolRegistry,
    workspace_config: WorkspaceConfig,
) -> None:
    """Registra todas las tools del filesystem en el registry.

    Args:
        registry: ToolRegistry donde registrar las tools
        workspace_config: Configuración del workspace

    Note:
        Esta función registra:
        - read_file
        - write_file
        - delete_file (solo si allow_delete=True)
        - list_files
    """
    workspace_root = Path(workspace_config.root).resolve()

    # Registrar tools básicas
    registry.register(ReadFileTool(workspace_root))
    registry.register(WriteFileTool(workspace_root))
    registry.register(ListFilesTool(workspace_root))

    # delete_file solo si está permitido
    # (la tool misma verifica allow_delete, pero la registramos siempre
    # para que aparezca en el schema del LLM, y que la tool rechace
    # con mensaje claro si no está permitido)
    registry.register(
        DeleteFileTool(
            workspace_root,
            allow_delete=workspace_config.allow_delete,
        )
    )
