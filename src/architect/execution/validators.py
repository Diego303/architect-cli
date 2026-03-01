"""
Validators for tool arguments.

Includes critical path validation to prevent path traversal
and other security vulnerabilities.
"""

from pathlib import Path


class PathTraversalError(Exception):
    """Error raised when a path attempts to escape the workspace."""

    pass


class ValidationError(Exception):
    """Generic validation error."""

    pass


def validate_path(path: str, workspace_root: Path) -> Path:
    """Validate and resolve a path, ensuring it is within the workspace.

    This function is CRITICAL for security. It prevents path traversal
    attacks (../../etc/passwd) and ensures that all file operations
    are confined to the workspace.

    Args:
        path: Relative path provided by the user/LLM
        workspace_root: Root directory of the workspace

    Returns:
        Absolute and resolved path, guaranteed to be within the workspace

    Raises:
        PathTraversalError: If the resolved path escapes the workspace

    Example:
        >>> validate_path("src/main.py", Path("/workspace"))
        Path("/workspace/src/main.py")

        >>> validate_path("../../etc/passwd", Path("/workspace"))
        PathTraversalError: Path ../../etc/passwd escapes the workspace

    Security Notes:
        - Uses Path.resolve() to resolve symlinks and '..' components
        - Verifies that the resolved path starts with the resolved workspace_root
        - Prevents both absolute and relative paths from escaping
    """
    # Resolve workspace root to absolute path
    workspace_resolved = workspace_root.resolve()

    # Combine workspace with the user path and resolve
    # resolve() resolves symlinks and eliminates '..' and '.'
    try:
        full_path = (workspace_root / path).resolve()
    except (ValueError, OSError) as e:
        raise ValidationError(f"Invalid path '{path}': {e}")

    # Verify the resolved path is within the workspace
    # Use is_relative_to() if available (Python 3.9+)
    # or fallback to string comparison
    try:
        # Python 3.9+
        if not full_path.is_relative_to(workspace_resolved):
            raise PathTraversalError(
                f"Path '{path}' escapes the workspace. "
                f"Resolved: {full_path}, Workspace: {workspace_resolved}"
            )
    except AttributeError:
        # Fallback for Python < 3.9
        if not str(full_path).startswith(str(workspace_resolved)):
            raise PathTraversalError(
                f"Path '{path}' escapes the workspace. "
                f"Resolved: {full_path}, Workspace: {workspace_resolved}"
            )

    return full_path


def validate_file_exists(path: Path) -> None:
    """Validate that a file exists.

    Args:
        path: Absolute path of the file

    Raises:
        ValidationError: If the file does not exist or is not a regular file
    """
    if not path.exists():
        raise ValidationError(f"File does not exist: {path}")

    if not path.is_file():
        raise ValidationError(f"Path is not a regular file: {path}")


def validate_directory_exists(path: Path) -> None:
    """Validate that a directory exists.

    Args:
        path: Absolute path of the directory

    Raises:
        ValidationError: If the directory does not exist or is not a directory
    """
    if not path.exists():
        raise ValidationError(f"Directory does not exist: {path}")

    if not path.is_dir():
        raise ValidationError(f"Path is not a directory: {path}")


def ensure_parent_directory(path: Path) -> None:
    """Ensure the parent directory of a path exists, creating it if necessary.

    Args:
        path: File path (the parent directory is what gets created)

    Raises:
        ValidationError: If the directory cannot be created
    """
    parent = path.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValidationError(f"Could not create directory {parent}: {e}")
