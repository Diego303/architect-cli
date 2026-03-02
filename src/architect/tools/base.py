"""
Abstract base class for all system tools.

Defines the common interface that all tools must implement,
including argument validation and schema generation.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Result of a tool execution.

    Attributes:
        success: True if the tool executed successfully
        output: Output/result of the tool (always string)
        error: Error message if success=False, None otherwise
    """

    success: bool
    output: str
    error: str | None = None

    model_config = {"extra": "forbid"}


class BaseTool(ABC):
    """Abstract base class for all tools.

    Each tool must:
    1. Define name, description and args_model
    2. Implement execute()
    3. Optionally set sensitive=True

    The get_schema() method automatically generates the JSON Schema
    compatible with OpenAI function calling from the args_model.
    """

    name: str
    description: str
    sensitive: bool = False
    args_model: type[BaseModel]

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the provided arguments.

        Args:
            **kwargs: Arguments validated by args_model

        Returns:
            ToolResult with the execution result

        Note:
            This method must NEVER raise exceptions to the caller.
            All errors must be caught and returned in ToolResult.
        """
        pass

    def get_schema(self) -> dict[str, Any]:
        """Generate JSON Schema compatible with OpenAI function calling.

        Returns:
            Dict with the schema in OpenAI tool/function calling format

        Example:
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Reads the contents of a file",
                    "parameters": {...Pydantic schema...}
                }
            }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def validate_args(self, args: dict[str, Any]) -> BaseModel:
        """Validate arguments using the Pydantic model.

        Args:
            args: Dictionary with unvalidated arguments

        Returns:
            Validated args_model instance

        Raises:
            ValidationError: If the arguments are not valid
        """
        return self.args_model(**args)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', sensitive={self.sensitive})>"
