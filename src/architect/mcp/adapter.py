"""
Adapter to convert MCP tools to BaseTool.

Allows remote MCP tools to integrate seamlessly
with the local tool system.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..tools.base import BaseTool, ToolResult
from .client import MCPClient, MCPConnectionError, MCPToolCallError


class MCPToolAdapter(BaseTool):
    """Adapts a remote MCP tool to the local BaseTool interface.

    This class makes an MCP tool indistinguishable from a local tool
    for the rest of the system (ExecutionEngine, AgentLoop, etc.).
    """

    def __init__(
        self,
        client: MCPClient,
        tool_definition: dict[str, Any],
        server_name: str,
    ):
        """Initialize the adapter.

        Args:
            client: Configured MCP client
            tool_definition: Tool definition from MCP
            server_name: Name of the MCP server
        """
        self.client = client
        self._original_name = tool_definition.get("name", "unknown")
        self._server_name = server_name

        # Prefixed name to avoid collisions
        # Format: mcp_{server}_{tool}
        self.name = f"mcp_{server_name}_{self._original_name}"

        # Tool description
        self.description = tool_definition.get(
            "description", f"Remote MCP tool: {self._original_name}"
        )

        # MCP tools are sensitive by default (remote operations)
        self.sensitive = True

        # Arguments schema
        self._raw_schema = tool_definition.get("inputSchema", {})

        # Generate dynamic Pydantic model from JSON Schema
        self.args_model = self._build_args_model()

    def _build_args_model(self) -> type[BaseModel]:
        """Build a dynamic Pydantic model from JSON Schema.

        Converts the MCP inputSchema (JSON Schema) to a Pydantic model
        that can be used for validation.

        Returns:
            Dynamically generated Pydantic class
        """
        # If no schema or empty, create empty model
        if not self._raw_schema or not self._raw_schema.get("properties"):
            return create_model(
                f"{self.name}_Args",
                __config__=ConfigDict(extra="forbid"),
            )

        # Extract schema properties
        properties = self._raw_schema.get("properties", {})
        required_fields = set(self._raw_schema.get("required", []))

        # Reserved Pydantic BaseModel names that cannot be used directly
        _RESERVED = frozenset(dir(BaseModel))

        # Build fields for Pydantic
        fields = {}
        for field_name, field_schema in properties.items():
            # Determine Python type from JSON Schema type
            field_type = self._json_schema_type_to_python(field_schema)

            # If the field collides with BaseModel attributes (e.g. "schema"),
            # use alias to avoid the Pydantic UserWarning.
            alias = None
            python_name = field_name
            if field_name in _RESERVED:
                python_name = f"{field_name}_"
                alias = field_name

            # If the field is required, use the type directly
            # If optional, use type | None with default None
            if alias:
                if field_name in required_fields:
                    fields[python_name] = (field_type, Field(..., alias=alias))
                else:
                    fields[python_name] = (field_type | None, Field(default=None, alias=alias))
            elif field_name in required_fields:
                fields[field_name] = (field_type, ...)
            else:
                fields[field_name] = (field_type | None, None)

        # Create dynamic model
        model = create_model(
            f"{self.name}_Args",
            __config__=ConfigDict(extra="forbid", populate_by_name=True),
            **fields,
        )

        return model

    def _json_schema_type_to_python(self, schema: dict[str, Any]) -> type:
        """Convert a JSON Schema type to a Python type.

        Args:
            schema: JSON schema of the field

        Returns:
            Corresponding Python type
        """
        json_type = schema.get("type", "string")

        # Basic type mapping
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        return type_mapping.get(json_type, str)

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the remote tool via MCP.

        Args:
            **kwargs: Arguments validated by args_model

        Returns:
            ToolResult with the execution result
        """
        try:
            # Call the remote tool
            result = self.client.call_tool(self._original_name, kwargs)

            # MCP returns result with varied structure
            # Try to extract content robustly
            content = self._extract_content(result)

            return ToolResult(
                success=True,
                output=content,
            )

        except MCPConnectionError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error with MCP server '{self._server_name}': {e}",
            )

        except MCPToolCallError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error executing remote tool: {e}",
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error in MCP tool: {e}",
            )

    def _extract_content(self, result: dict[str, Any]) -> str:
        """Extract content from the MCP result.

        MCP can return results in different formats.
        This function tries to extract it robustly.

        Args:
            result: Result from MCP

        Returns:
            Content as string
        """
        # If result has 'content', use it
        if "content" in result:
            content = result["content"]

            # If content is a list (MCP format with multiple blocks)
            if isinstance(content, list):
                # Concatenate all text blocks
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        # Blocks can have 'text' or 'data'
                        if "text" in block:
                            parts.append(block["text"])
                        elif "data" in block:
                            parts.append(str(block["data"]))
                    else:
                        parts.append(str(block))
                return "\n".join(parts) if parts else ""

            # If content is a direct string
            if isinstance(content, str):
                return content

            # If content is a dict, convert to string
            if isinstance(content, dict):
                import json

                return json.dumps(content, indent=2)

        # If result has other known fields
        if "output" in result:
            return str(result["output"])

        if "result" in result:
            return str(result["result"])

        # Fallback: convert the entire result to string
        import json

        return json.dumps(result, indent=2)

    def __repr__(self) -> str:
        return (
            f"<MCPToolAdapter("
            f"name='{self.name}', "
            f"server='{self._server_name}', "
            f"original='{self._original_name}')>"
        )
