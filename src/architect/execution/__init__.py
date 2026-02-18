"""
Módulo de ejecución - Engine y políticas para ejecución controlada de tools.

Exporta el ExecutionEngine, políticas de confirmación y validadores.
"""

from .engine import ExecutionEngine
from .policies import ConfirmationPolicy, NoTTYError
from .validators import (
    PathTraversalError,
    ValidationError,
    ensure_parent_directory,
    validate_directory_exists,
    validate_file_exists,
    validate_path,
)

__all__ = [
    # Engine
    "ExecutionEngine",
    # Policies
    "ConfirmationPolicy",
    "NoTTYError",
    # Validators
    "validate_path",
    "validate_file_exists",
    "validate_directory_exists",
    "ensure_parent_directory",
    "PathTraversalError",
    "ValidationError",
]
