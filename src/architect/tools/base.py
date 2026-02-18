"""
Base abstracta para todas las tools del sistema.

Define la interfaz común que todas las tools deben implementar,
incluyendo validación de argumentos y generación de schemas.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Resultado de la ejecución de una tool.

    Attributes:
        success: True si la tool se ejecutó correctamente
        output: Salida/resultado de la tool (siempre string)
        error: Mensaje de error si success=False, None en caso contrario
    """

    success: bool
    output: str
    error: str | None = None

    model_config = {"extra": "forbid"}


class BaseTool(ABC):
    """Clase base abstracta para todas las tools.

    Cada tool debe:
    1. Definir name, description y args_model
    2. Implementar execute()
    3. Opcionalmente marcar sensitive=True

    El método get_schema() genera automáticamente el JSON Schema
    compatible con OpenAI function calling a partir del args_model.
    """

    name: str
    description: str
    sensitive: bool = False
    args_model: type[BaseModel]

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Ejecuta la tool con los argumentos proporcionados.

        Args:
            **kwargs: Argumentos validados por args_model

        Returns:
            ToolResult con el resultado de la ejecución

        Note:
            Este método NUNCA debe lanzar excepciones al caller.
            Todos los errores deben capturarse y retornarse en ToolResult.
        """
        pass

    def get_schema(self) -> dict[str, Any]:
        """Genera JSON Schema compatible con OpenAI function calling.

        Returns:
            Dict con el schema en formato OpenAI tool/function calling

        Example:
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Lee el contenido de un archivo",
                    "parameters": {...schema de Pydantic...}
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
        """Valida argumentos usando el modelo Pydantic.

        Args:
            args: Diccionario con argumentos sin validar

        Returns:
            Instancia del args_model validada

        Raises:
            ValidationError: Si los argumentos no son válidos
        """
        return self.args_model(**args)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', sensitive={self.sensitive})>"
