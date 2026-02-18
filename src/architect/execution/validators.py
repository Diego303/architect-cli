"""
Validadores para argumentos de tools.

Incluye validación crítica de paths para prevenir path traversal
y otras vulnerabilidades de seguridad.
"""

from pathlib import Path


class PathTraversalError(Exception):
    """Error lanzado cuando un path intenta escapar del workspace."""

    pass


class ValidationError(Exception):
    """Error genérico de validación."""

    pass


def validate_path(path: str, workspace_root: Path) -> Path:
    """Valida y resuelve un path, asegurando que esté dentro del workspace.

    Esta función es CRÍTICA para la seguridad. Previene path traversal
    attacks (../../etc/passwd) y asegura que todas las operaciones de
    archivos estén confinadas al workspace.

    Args:
        path: Path relativo proporcionado por el usuario/LLM
        workspace_root: Directorio raíz del workspace

    Returns:
        Path absoluto y resuelto, garantizado dentro del workspace

    Raises:
        PathTraversalError: Si el path resuelto escapa del workspace

    Example:
        >>> validate_path("src/main.py", Path("/workspace"))
        Path("/workspace/src/main.py")

        >>> validate_path("../../etc/passwd", Path("/workspace"))
        PathTraversalError: Path ../../etc/passwd escapa del workspace

    Security Notes:
        - Usa Path.resolve() para resolver symlinks y '..' components
        - Verifica que el path resuelto comience con workspace_root resuelto
        - Previene tanto paths absolutos como relativos que escapen
    """
    # Resolver workspace root a path absoluto
    workspace_resolved = workspace_root.resolve()

    # Combinar workspace con el path del usuario y resolver
    # resolve() resuelve symlinks y elimina '..' y '.'
    try:
        full_path = (workspace_root / path).resolve()
    except (ValueError, OSError) as e:
        raise ValidationError(f"Path inválido '{path}': {e}")

    # Verificar que el path resuelto esté dentro del workspace
    # Usamos is_relative_to() si está disponible (Python 3.9+)
    # o fallback a comparación de strings
    try:
        # Python 3.9+
        if not full_path.is_relative_to(workspace_resolved):
            raise PathTraversalError(
                f"Path '{path}' escapa del workspace. "
                f"Resuelto: {full_path}, Workspace: {workspace_resolved}"
            )
    except AttributeError:
        # Fallback para Python < 3.9
        if not str(full_path).startswith(str(workspace_resolved)):
            raise PathTraversalError(
                f"Path '{path}' escapa del workspace. "
                f"Resuelto: {full_path}, Workspace: {workspace_resolved}"
            )

    return full_path


def validate_file_exists(path: Path) -> None:
    """Valida que un archivo exista.

    Args:
        path: Path absoluto del archivo

    Raises:
        ValidationError: Si el archivo no existe o no es un archivo regular
    """
    if not path.exists():
        raise ValidationError(f"El archivo no existe: {path}")

    if not path.is_file():
        raise ValidationError(f"El path no es un archivo regular: {path}")


def validate_directory_exists(path: Path) -> None:
    """Valida que un directorio exista.

    Args:
        path: Path absoluto del directorio

    Raises:
        ValidationError: Si el directorio no existe o no es un directorio
    """
    if not path.exists():
        raise ValidationError(f"El directorio no existe: {path}")

    if not path.is_dir():
        raise ValidationError(f"El path no es un directorio: {path}")


def ensure_parent_directory(path: Path) -> None:
    """Asegura que el directorio padre de un path exista, creándolo si es necesario.

    Args:
        path: Path del archivo (el directorio padre es el que se crea)

    Raises:
        ValidationError: Si no se puede crear el directorio
    """
    parent = path.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValidationError(f"No se pudo crear el directorio {parent}: {e}")
