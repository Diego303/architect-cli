"""
Tool for applying patches in unified diff format.

Implements a pure-Python unified diff parser and applies the hunks
to the target file. Falls back to the system `patch` command
if the pure parser fails.
"""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..execution.validators import (
    PathTraversalError,
    ValidationError,
    validate_file_exists,
    validate_path,
)
from .base import BaseTool, ToolResult
from .schemas import ApplyPatchArgs

# ─────────────────────────────────────────────────────────────────────────────
# Internals: unified diff parser and applier
# ─────────────────────────────────────────────────────────────────────────────

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    """Error parsing or applying a unified diff patch."""


@dataclass
class _Hunk:
    """Represents a hunk (@@ ... @@) from a unified diff."""

    orig_start: int  # 1-based line number in the original where the hunk starts
    orig_count: int  # Number of original lines consumed by the hunk
    new_start: int   # 1-based line number in the result
    new_count: int   # Number of lines in the result
    lines: list[str] = field(default_factory=list)  # Hunk lines (without trailing newline from diff)


def _parse_hunks(patch_text: str) -> list[_Hunk]:
    """Parse a unified diff text and return a list of hunks.

    Ignores --- / +++ headers if present.
    Accepts patches with or without file headers.

    Args:
        patch_text: Patch content in unified diff format

    Returns:
        List of _Hunk in order of appearance

    Raises:
        PatchError: If the format is invalid
    """
    hunks: list[_Hunk] = []
    current: _Hunk | None = None

    for line in patch_text.split("\n"):
        # Ignore file headers (--- / +++)
        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        m = _HUNK_HEADER.match(line)
        if m:
            if current is not None:
                hunks.append(current)
            orig_start = int(m.group(1))
            orig_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            current = _Hunk(orig_start, orig_count, new_start, new_count)
        elif current is not None:
            # Accumulate lines for the current hunk
            if line.startswith(("-", "+", " ")):
                current.lines.append(line)
            # Ignore "\ No newline at end of file" and other annotations

    if current is not None:
        hunks.append(current)

    return hunks


def _apply_hunks_to_lines(
    lines: list[str],
    hunks: list[_Hunk],
    path: str,
) -> list[str]:
    """Apply a list of hunks to a list of file lines.

    Each line in `lines` should end with '\\n' (except possibly the last).
    Hunk lines are strings without '\\n' at the end (only the +/-/ prefix).

    Args:
        lines: File content as list of lines (with endings)
        hunks: Hunks to apply in order
        path: File path (only for error messages)

    Returns:
        Modified content as list of lines

    Raises:
        PatchError: If a hunk does not match the current content
    """
    result = list(lines)
    offset = 0  # Accumulated delta of added/removed lines

    for hunk in hunks:
        # Separate orig_content (what should be there) and new_content (what will go)
        orig_content: list[str] = []
        new_content: list[str] = []

        for hunk_line in hunk.lines:
            if hunk_line.startswith("-"):
                orig_content.append(hunk_line[1:])
            elif hunk_line.startswith("+"):
                new_content.append(hunk_line[1:])
            else:
                # Context line (starts with " " or is empty)
                content = hunk_line[1:] if hunk_line.startswith(" ") else hunk_line
                orig_content.append(content)
                new_content.append(content)

        # Calculate insertion position in the result (with accumulated offset)
        if hunk.orig_count == 0:
            # Pure insertion: insert AFTER the orig_start line
            insert_at = hunk.orig_start + offset
        else:
            # Replacement: starts at orig_start (1-based -> 0-based)
            insert_at = hunk.orig_start - 1 + offset

        # Validate that orig_content matches the current file content
        if hunk.orig_count > 0:
            actual_slice = result[insert_at : insert_at + hunk.orig_count]
            actual_stripped = [ln.rstrip("\n\r") for ln in actual_slice]
            expected_stripped = [ln.rstrip("\n\r") for ln in orig_content]

            if actual_stripped != expected_stripped:
                raise PatchError(
                    f"Hunk @@ -{hunk.orig_start},{hunk.orig_count} does not match the "
                    f"current content of {path}. "
                    f"Does the patch correspond to a different version of the file?"
                )

        # Build the new lines with correct endings
        # If patch content has no \n, add it (to match the file format)
        new_file_lines: list[str] = []
        for content in new_content:
            if content.endswith("\n"):
                new_file_lines.append(content)
            else:
                new_file_lines.append(content + "\n")

        # Apply the hunk
        result[insert_at : insert_at + hunk.orig_count] = new_file_lines
        offset += len(new_file_lines) - hunk.orig_count

    return result


def _apply_patch_pure(file_content: str, patch_text: str, path: str) -> str:
    """Apply a unified diff to file content using pure Python.

    Args:
        file_content: Current file content
        patch_text: Patch in unified diff format
        path: File path (for error messages)

    Returns:
        Modified content

    Raises:
        PatchError: If the patch cannot be applied
    """
    if not patch_text.strip():
        raise PatchError("The patch is empty.")

    hunks = _parse_hunks(patch_text)
    if not hunks:
        raise PatchError(
            "No valid hunks found in the patch. "
            "Expected format: @@ -a,b +c,d @@ (one or more sections)."
        )

    lines = file_content.splitlines(keepends=True)
    result_lines = _apply_hunks_to_lines(lines, hunks, path)
    return "".join(result_lines)


def _apply_patch_system(file_path: Path, patch_text: str) -> str:
    """Apply a patch using the system `patch` command as fallback.

    Runs a --dry-run first to validate, then applies.

    Args:
        file_path: Path to the file to patch
        patch_text: Patch in unified diff format

    Returns:
        Modified file content

    Raises:
        PatchError: If `patch` is not available or the patch fails
    """
    patch_exe = shutil.which("patch")
    if patch_exe is None:
        raise PatchError(
            "The `patch` command is not available on the system. "
            "Install with: apt install patch / brew install gpatch"
        )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(patch_text)
        patch_file = Path(tmp.name)

    try:
        # Dry-run first to validate without modifying the file
        dry = subprocess.run(
            [patch_exe, "--dry-run", "-f", "-i", str(patch_file), str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if dry.returncode != 0:
            raise PatchError(
                f"Patch cannot be applied (dry-run): {dry.stderr.strip() or dry.stdout.strip()}"
            )

        # Apply for real
        apply = subprocess.run(
            [patch_exe, "-f", "-i", str(patch_file), str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if apply.returncode != 0:
            raise PatchError(
                f"Error applying patch: {apply.stderr.strip() or apply.stdout.strip()}"
            )

        return file_path.read_text(encoding="utf-8")

    finally:
        patch_file.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Public tool
# ─────────────────────────────────────────────────────────────────────────────


class ApplyPatchTool(BaseTool):
    """Applies a unified diff patch to a file in the workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "apply_patch"
        self.description = (
            "Apply a unified diff patch to an existing file. "
            "Ideal for changes that affect multiple non-contiguous sections (multi-hunk). "
            "For a single block of changes use edit_file (simpler). "
            "For new files or complete rewrites use write_file."
        )
        self.sensitive = True
        self.args_model = ApplyPatchArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Apply a unified diff patch to the file.

        Args:
            path: Path relative to the workspace
            patch: Patch text in unified diff format

        Returns:
            ToolResult indicating success with summary or descriptive error
        """
        try:
            args = self.validate_args(kwargs)
            file_path = validate_path(args.path, self.workspace_root)
            validate_file_exists(file_path)

            original = file_path.read_text(encoding="utf-8")

            # Try with the pure-Python parser first
            try:
                modified = _apply_patch_pure(original, args.patch, args.path)
                method = "pure-Python"
            except PatchError as pure_err:
                # Fallback: try with the system `patch` command
                try:
                    modified = _apply_patch_system(file_path, args.patch)
                    method = "system patch"
                except PatchError as sys_err:
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            f"Could not apply patch to {args.path}.\n"
                            f"  Pure parser: {pure_err}\n"
                            f"  System patch: {sys_err}"
                        ),
                    )

            # Write the result (no-op if system patch already did it)
            file_path.write_text(modified, encoding="utf-8")

            # Summary
            try:
                hunks = _parse_hunks(args.patch)
                lines_changed = sum(
                    sum(1 for ln in h.lines if ln.startswith(("+", "-")))
                    for h in hunks
                )
                summary = (
                    f"Patch applied to {args.path} ({method}). "
                    f"{len(hunks)} hunk(s), ~{lines_changed} lines changed."
                )
            except Exception:
                summary = f"Patch applied to {args.path} ({method})."

            return ToolResult(success=True, output=summary)

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
                error=f"Unexpected error applying patch to {kwargs.get('path', '?')}: {e}",
            )
