"""
Modelos Pydantic para la configuración de architect.

Define todos los schemas de configuración usando Pydantic v2 para validación,
valores por defecto y serialización.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Configuración del proveedor LLM."""

    provider: str = "litellm"
    mode: Literal["proxy", "direct"] = "direct"
    model: str = "gpt-4o"
    api_base: str | None = None
    api_key_env: str = "LITELLM_API_KEY"
    timeout: int = 60
    retries: int = 2
    stream: bool = True

    model_config = {"extra": "forbid"}


class AgentConfig(BaseModel):
    """Configuración de un agente específico."""

    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    confirm_mode: Literal["confirm-all", "confirm-sensitive", "yolo"] = "confirm-sensitive"
    max_steps: int = 20

    model_config = {"extra": "forbid"}


class LoggingConfig(BaseModel):
    """Configuración del sistema de logging."""

    level: Literal["debug", "info", "warn", "error"] = "info"
    file: Path | None = None
    verbose: int = 0

    model_config = {"extra": "forbid"}


class WorkspaceConfig(BaseModel):
    """Configuración del workspace (directorio de trabajo)."""

    root: Path = Path(".")
    allow_delete: bool = False

    model_config = {"extra": "forbid"}


class MCPServerConfig(BaseModel):
    """Configuración de un servidor MCP individual."""

    name: str
    url: str
    token_env: str | None = None
    token: str | None = None

    model_config = {"extra": "forbid"}


class MCPConfig(BaseModel):
    """Configuración global de MCP."""

    servers: list[MCPServerConfig] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AppConfig(BaseModel):
    """Configuración completa de la aplicación.

    Esta es la raíz del árbol de configuración. Combina todas las secciones
    y es el punto de entrada para validación.
    """

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    model_config = {"extra": "forbid"}
