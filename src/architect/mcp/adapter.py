"""
Adapter para convertir tools MCP a BaseTool.

Permite que las tools remotas de MCP se integren perfectamente
con el sistema local de tools.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from ..tools.base import BaseTool, ToolResult
from .client import MCPClient, MCPConnectionError, MCPToolCallError


class MCPToolAdapter(BaseTool):
    """Adapta una tool MCP remota al interfaz BaseTool local.

    Esta clase hace que una tool MCP sea indistinguible de una tool local
    para el resto del sistema (ExecutionEngine, AgentLoop, etc.).
    """

    def __init__(
        self,
        client: MCPClient,
        tool_definition: dict[str, Any],
        server_name: str,
    ):
        """Inicializa el adapter.

        Args:
            client: Cliente MCP configurado
            tool_definition: Definición de la tool desde MCP
            server_name: Nombre del servidor MCP
        """
        self.client = client
        self._original_name = tool_definition.get("name", "unknown")
        self._server_name = server_name

        # Nombre prefijado para evitar colisiones
        # Formato: mcp_{server}_{tool}
        self.name = f"mcp_{server_name}_{self._original_name}"

        # Descripción de la tool
        self.description = tool_definition.get(
            "description", f"Tool MCP remota: {self._original_name}"
        )

        # Tools MCP son sensibles por defecto (operaciones remotas)
        self.sensitive = True

        # Schema de argumentos
        self._raw_schema = tool_definition.get("inputSchema", {})

        # Generar modelo Pydantic dinámico desde JSON Schema
        self.args_model = self._build_args_model()

    def _build_args_model(self) -> type[BaseModel]:
        """Construye un modelo Pydantic dinámico desde JSON Schema.

        Convierte el inputSchema de MCP (JSON Schema) a un modelo
        Pydantic que se puede usar para validación.

        Returns:
            Clase Pydantic generada dinámicamente
        """
        # Si no hay schema o está vacío, crear modelo vacío
        if not self._raw_schema or not self._raw_schema.get("properties"):
            return create_model(
                f"{self.name}_Args",
                __config__=ConfigDict(extra="forbid"),
            )

        # Extraer propiedades del schema
        properties = self._raw_schema.get("properties", {})
        required_fields = set(self._raw_schema.get("required", []))

        # Construir campos para Pydantic
        fields = {}
        for field_name, field_schema in properties.items():
            # Determinar tipo Python desde JSON Schema type
            field_type = self._json_schema_type_to_python(field_schema)

            # Si el campo es requerido, usar el tipo directo
            # Si es opcional, usar tipo | None con default None
            if field_name in required_fields:
                fields[field_name] = (field_type, ...)
            else:
                fields[field_name] = (field_type | None, None)

        # Crear modelo dinámico
        model = create_model(
            f"{self.name}_Args",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )

        return model

    def _json_schema_type_to_python(self, schema: dict[str, Any]) -> type:
        """Convierte un tipo JSON Schema a tipo Python.

        Args:
            schema: Schema JSON del campo

        Returns:
            Tipo Python correspondiente
        """
        json_type = schema.get("type", "string")

        # Mapeo básico de tipos
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
        """Ejecuta la tool remota vía MCP.

        Args:
            **kwargs: Argumentos validados por args_model

        Returns:
            ToolResult con el resultado de la ejecución
        """
        try:
            # Llamar a la tool remota
            result = self.client.call_tool(self._original_name, kwargs)

            # MCP retorna result con estructura variada
            # Intentar extraer contenido de forma robusta
            content = self._extract_content(result)

            return ToolResult(
                success=True,
                output=content,
            )

        except MCPConnectionError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error de conexión con servidor MCP '{self._server_name}': {e}",
            )

        except MCPToolCallError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error ejecutando tool remota: {e}",
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado en tool MCP: {e}",
            )

    def _extract_content(self, result: dict[str, Any]) -> str:
        """Extrae el contenido del resultado MCP.

        MCP puede retornar resultados en diferentes formatos.
        Esta función intenta extraerlo de forma robusta.

        Args:
            result: Resultado desde MCP

        Returns:
            Contenido como string
        """
        # Si result tiene 'content', usarlo
        if "content" in result:
            content = result["content"]

            # Si content es lista (formato MCP con múltiples bloques)
            if isinstance(content, list):
                # Concatenar todos los bloques de texto
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        # Bloques pueden tener 'text' o 'data'
                        if "text" in block:
                            parts.append(block["text"])
                        elif "data" in block:
                            parts.append(str(block["data"]))
                    else:
                        parts.append(str(block))
                return "\n".join(parts) if parts else ""

            # Si content es string directo
            if isinstance(content, str):
                return content

            # Si content es dict, convertir a string
            if isinstance(content, dict):
                import json

                return json.dumps(content, indent=2)

        # Si result tiene otros campos conocidos
        if "output" in result:
            return str(result["output"])

        if "result" in result:
            return str(result["result"])

        # Fallback: convertir todo el result a string
        import json

        return json.dumps(result, indent=2)

    def __repr__(self) -> str:
        return (
            f"<MCPToolAdapter("
            f"name='{self.name}', "
            f"server='{self._server_name}', "
            f"original='{self._original_name}')>"
        )
