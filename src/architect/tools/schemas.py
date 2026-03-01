"""
Pydantic models for tool arguments.

Each tool defines its argument schema as a Pydantic model,
which provides automatic validation and JSON Schema generation.
"""

from pydantic import BaseModel, Field, field_validator


class ReadFileArgs(BaseModel):
    """Arguments for the read_file tool."""

    path: str = Field(
        description="Path relative to the workspace of the file to read",
        examples=["README.md", "src/main.py", "config/settings.yaml"],
    )

    model_config = {"extra": "forbid"}


class WriteFileArgs(BaseModel):
    """Arguments for the write_file tool."""

    path: str = Field(
        description="Path relative to the workspace of the file to write",
        examples=["output.txt", "src/generated.py"],
    )
    content: str = Field(
        description="Content to write to the file",
    )
    mode: str = Field(
        default="overwrite",
        description="Write mode: 'overwrite' (replaces) or 'append' (adds to the end)",
        pattern="^(overwrite|append)$",
    )

    model_config = {"extra": "forbid"}


class DeleteFileArgs(BaseModel):
    """Arguments for the delete_file tool."""

    path: str = Field(
        description="Path relative to the workspace of the file to delete",
        examples=["temp.txt", "old_config.yaml"],
    )

    model_config = {"extra": "forbid"}


class EditFileArgs(BaseModel):
    """Arguments for the edit_file tool (str_replace)."""

    path: str = Field(
        description="Path relative to the workspace of the file to edit",
        examples=["src/main.py", "README.md"],
    )
    old_str: str = Field(
        description=(
            "Exact text to replace. Must appear exactly once in the file. "
            "Include neighboring context lines to make it unambiguous if necessary."
        ),
    )
    new_str: str = Field(
        description=(
            "Replacement text. Can be an empty string to delete the block. "
            "Maintain correct indentation."
        ),
    )

    model_config = {"extra": "forbid"}


class ApplyPatchArgs(BaseModel):
    """Arguments for the apply_patch tool (unified diff)."""

    path: str = Field(
        description="Path relative to the workspace of the file to patch",
        examples=["src/main.py", "config.yaml"],
    )
    patch: str = Field(
        description=(
            "Patch in unified diff format. Can include one or more @@ -a,b +c,d @@ sections. "
            "The --- / +++ headers are optional. "
            "Example: '@@ -3,4 +3,5 @@\\n context\\n-old line\\n+new line\\n context'"
        ),
    )

    model_config = {"extra": "forbid"}


class ListFilesArgs(BaseModel):
    """Arguments for the list_files tool."""

    path: str = Field(
        default=".",
        description="Path relative to the workspace of the directory to list",
        examples=[".", "src", "tests/fixtures"],
    )
    pattern: str | None = Field(
        default=None,
        description="Optional glob pattern to filter files (e.g.: '*.py', 'test_*.py')",
        examples=["*.py", "*.md", "test_*.py"],
    )
    recursive: bool = Field(
        default=False,
        description="If True, list files recursively in subdirectories",
    )

    model_config = {"extra": "forbid"}


class SearchCodeArgs(BaseModel):
    """Arguments for the search_code tool."""

    pattern: str = Field(
        description=(
            "Regex pattern to search for in code. "
            "Examples: 'def process_', 'class.*Tool', 'import (os|sys)'"
        ),
    )
    path: str = Field(
        default=".",
        description="Directory or file to search in (relative to the workspace)",
    )
    file_pattern: str | None = Field(
        default=None,
        description="File filter by name glob (e.g.: '*.py', '*.ts')",
        examples=["*.py", "*.js", "*.ts", "*.yaml"],
    )
    max_results: int = Field(
        default=20,
        description="Maximum number of results to return",
        ge=1,
        le=200,
    )
    context_lines: int = Field(
        default=2,
        description="Context lines before and after each match",
        ge=0,
        le=10,
    )
    case_sensitive: bool = Field(
        default=True,
        description="If False, the search ignores case",
    )

    model_config = {"extra": "forbid"}


class GrepArgs(BaseModel):
    """Arguments for the grep tool."""

    text: str = Field(
        description=(
            "Literal text to search for (not regex). "
            "Faster than search_code for simple strings."
        ),
    )
    path: str = Field(
        default=".",
        description="Directory or file to search in (relative to the workspace)",
    )
    file_pattern: str | None = Field(
        default=None,
        description="File filter by name glob (e.g.: '*.py')",
        examples=["*.py", "*.js", "*.md"],
    )
    max_results: int = Field(
        default=30,
        description="Maximum number of results to return",
        ge=1,
        le=500,
    )
    case_sensitive: bool = Field(
        default=True,
        description="If False, the search ignores case",
    )

    model_config = {"extra": "forbid"}


class FindFilesArgs(BaseModel):
    """Arguments for the find_files tool."""

    pattern: str = Field(
        description=(
            "Glob pattern for file names. "
            "Examples: '*.test.py', 'Dockerfile*', 'config.yaml', '*.env'"
        ),
    )
    path: str = Field(
        default=".",
        description="Directory to search in (relative to the workspace)",
    )

    model_config = {"extra": "forbid"}


class RunCommandArgs(BaseModel):
    """Arguments for the run_command tool (F13)."""

    command: str = Field(
        description=(
            "Command to execute in the shell. Can include pipes and redirections. "
            "Examples: 'pytest tests/', 'python -m mypy src/', 'git status', 'make build'"
        ),
    )
    cwd: str | None = Field(
        default=None,
        description=(
            "Working directory relative to the workspace (optional). "
            "If not specified, the workspace root is used."
        ),
        examples=["src", "tests", "frontend"],
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Timeout in seconds for the command (1-600). Default: 30s.",
    )
    env: dict[str, str] | None = Field(
        default=None,
        description=(
            "Additional environment variables for the process (merged with the current environment). "
            "Example: {'DEBUG': '1', 'PYTHONPATH': 'src'}"
        ),
    )

    @field_validator("timeout", mode="before")
    @classmethod
    def _normalize_timeout(cls, v: int) -> int:
        """Auto-convert milliseconds to seconds when LLM sends ms values."""
        if isinstance(v, (int, float)) and v > 600:
            return max(1, min(600, int(v / 1000)))
        return int(v) if isinstance(v, float) else v

    model_config = {"extra": "forbid"}
