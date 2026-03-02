"""
Tools for local filesystem operations.

Includes tools for reading, writing, editing, deleting, and listing files,
all with path validation and workspace confinement.
"""

import difflib
import fnmatch
from pathlib import Path
from typing import Any

from ..execution.validators import (
    PathTraversalError,
    ValidationError,
    ensure_parent_directory,
    validate_directory_exists,
    validate_file_exists,
    validate_path,
)
from .base import BaseTool, ToolResult
from .schemas import DeleteFileArgs, EditFileArgs, ListFilesArgs, ReadFileArgs, WriteFileArgs


class ReadFileTool(BaseTool):
    """Reads the contents of a file within the workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "read_file"
        self.description = (
            "Read the full contents of a file. "
            "Use this tool when you need to examine code, "
            "configuration, or any text file."
        )
        self.sensitive = False
        self.args_model = ReadFileArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Read a file from the workspace.

        Args:
            path: Path relative to the workspace

        Returns:
            ToolResult with the file contents or error
        """
        try:
            # Validate arguments
            args = self.validate_args(kwargs)

            # Validate and resolve path
            file_path = validate_path(args.path, self.workspace_root)

            # Verify that the file exists
            validate_file_exists(file_path)

            # Read contents
            content = file_path.read_text(encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Contents of {args.path}:\n\n{content}",
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Security error: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                output="",
                error=f"File {args.path} is not a valid text file (UTF-8)",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error reading {args.path}: {e}",
            )


class WriteFileTool(BaseTool):
    """Writes content to a file within the workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "write_file"
        self.description = (
            "Write or completely replace a file. "
            "Use only for NEW files or when you need to rewrite the entire file. "
            "For partial modifications use edit_file (single block) or apply_patch (multi-hunk). "
            "Can overwrite (mode='overwrite') or append (mode='append'). "
            "Creates parent directories if they don't exist."
        )
        self.sensitive = True  # Sensitive operation
        self.args_model = WriteFileArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Write content to a file.

        Args:
            path: Path relative to the workspace
            content: Content to write
            mode: 'overwrite' or 'append'

        Returns:
            ToolResult indicating success or error
        """
        try:
            # Validate arguments
            args = self.validate_args(kwargs)

            # Validate and resolve path
            file_path = validate_path(args.path, self.workspace_root)

            # Ensure parent directory exists
            ensure_parent_directory(file_path)

            # Write according to mode
            if args.mode == "overwrite":
                file_path.write_text(args.content, encoding="utf-8")
                action = "overwritten"
            else:  # append
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(args.content)
                action = "appended content to"

            return ToolResult(
                success=True,
                output=f"File {args.path} {action} successfully ({len(args.content)} characters)",
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Security error: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error writing {args.path}: {e}",
            )


class EditFileTool(BaseTool):
    """Edits a file by replacing an exact text block (str_replace)."""

    def __init__(self, workspace_root: Path):
        self.name = "edit_file"
        self.description = (
            "Replace an exact block of text in a file (str_replace). "
            "PREFER over write_file for partial modifications in existing files. "
            "old_str must be unique in the file; include neighboring context lines if ambiguous. "
            "For changes in multiple non-contiguous sections, use apply_patch. "
            "For new files or complete rewrites, use write_file."
        )
        self.sensitive = True
        self.args_model = EditFileArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Replace an exact block of text in a file.

        Args:
            path: Path relative to the workspace
            old_str: Exact text to replace (must be unique in the file)
            new_str: Replacement text (can be empty to delete the block)

        Returns:
            ToolResult with the generated diff or descriptive error
        """
        try:
            args = self.validate_args(kwargs)

            if not args.old_str:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "old_str cannot be empty. "
                        "To insert at the end use write_file with mode='append', "
                        "or use apply_patch with an insertion hunk."
                    ),
                )

            file_path = validate_path(args.path, self.workspace_root)
            validate_file_exists(file_path)

            original = file_path.read_text(encoding="utf-8")

            # Count exact occurrences
            count = original.count(args.old_str)
            if count == 0:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"old_str not found in {args.path}. "
                        "Check spaces, indentation, and line breaks."
                    ),
                )
            if count > 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"old_str appears {count} times in {args.path}. "
                        "Add more context lines to make it unique."
                    ),
                )

            # Replace the single occurrence
            modified = original.replace(args.old_str, args.new_str, 1)
            file_path.write_text(modified, encoding="utf-8")

            # Generate diff for output
            diff_lines = list(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    modified.splitlines(keepends=True),
                    fromfile=f"a/{args.path}",
                    tofile=f"b/{args.path}",
                    lineterm="",
                )
            )
            diff_str = "\n".join(diff_lines) if diff_lines else "(no visible changes)"

            return ToolResult(
                success=True,
                output=f"File {args.path} edited successfully.\n\nDiff:\n{diff_str}",
            )

        except PathTraversalError as e:
            return ToolResult(success=False, output="", error=f"Security error: {e}")
        except ValidationError as e:
            return ToolResult(success=False, output="", error=str(e))
        except UnicodeDecodeError:
            path_str = kwargs.get("path", "?")
            return ToolResult(
                success=False,
                output="",
                error=f"File {path_str} is not a valid text file (UTF-8)",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error editing {kwargs.get('path', '?')}: {e}",
            )


class DeleteFileTool(BaseTool):
    """Deletes a file within the workspace."""

    def __init__(self, workspace_root: Path, allow_delete: bool):
        self.name = "delete_file"
        self.description = (
            "Delete a file from the workspace. "
            "Requires allow_delete=true in the configuration."
        )
        self.sensitive = True  # VERY sensitive operation
        self.args_model = DeleteFileArgs
        self.workspace_root = workspace_root
        self.allow_delete = allow_delete

    def execute(self, **kwargs: Any) -> ToolResult:
        """Delete a file from the workspace.

        Args:
            path: Path relative to the workspace

        Returns:
            ToolResult indicating success or error
        """
        try:
            # Check that delete is allowed
            if not self.allow_delete:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "Delete operations are disabled. "
                        "Set workspace.allow_delete=true to allow them."
                    ),
                )

            # Validate arguments
            args = self.validate_args(kwargs)

            # Validate and resolve path
            file_path = validate_path(args.path, self.workspace_root)

            # Verify that the file exists
            validate_file_exists(file_path)

            # Delete file
            file_path.unlink()

            return ToolResult(
                success=True,
                output=f"File {args.path} deleted successfully",
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Security error: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error deleting {args.path}: {e}",
            )


class ListFilesTool(BaseTool):
    """Lists files and directories within the workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "list_files"
        self.description = (
            "List files and directories at a path. "
            "Supports glob patterns (*.py) and recursive listing. "
            "Useful for exploring the project structure."
        )
        self.sensitive = False
        self.args_model = ListFilesArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """List files in a directory.

        Args:
            path: Path relative to the workspace (default: ".")
            pattern: Optional glob pattern (e.g.: "*.py")
            recursive: If True, list recursively

        Returns:
            ToolResult with the file list or error
        """
        try:
            # Validate arguments
            args = self.validate_args(kwargs)

            # Validate and resolve path
            dir_path = validate_path(args.path, self.workspace_root)

            # Verify that it is a directory
            validate_directory_exists(dir_path)

            # List files
            if args.recursive:
                # List recursively
                if args.pattern:
                    files = list(dir_path.rglob(args.pattern))
                else:
                    files = list(dir_path.rglob("*"))
            else:
                # List only this level
                files = list(dir_path.iterdir())
                # Apply pattern if specified
                if args.pattern:
                    files = [f for f in files if fnmatch.fnmatch(f.name, args.pattern)]

            # Sort and format
            files.sort()

            # Generate formatted output
            output_lines = [f"Contents of {args.path}:"]
            output_lines.append("")

            if not files:
                output_lines.append("(empty directory)")
            else:
                for file_path in files:
                    # Path relative to workspace for output
                    try:
                        rel_path = file_path.relative_to(self.workspace_root)
                    except ValueError:
                        rel_path = file_path

                    # Type indicator
                    if file_path.is_dir():
                        indicator = "📁"
                        type_str = "DIR"
                    else:
                        indicator = "📄"
                        type_str = "FILE"

                    output_lines.append(f"{indicator} {type_str:4s} {rel_path}")

            output_lines.append("")
            output_lines.append(f"Total: {len(files)} items")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Security error: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error listing {args.path}: {e}",
            )
