"""
Execution module - Engine and policies for controlled tool execution.

Exports the ExecutionEngine, confirmation policies, and validators.
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
