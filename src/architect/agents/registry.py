"""
Registry de agentes - Configuraciones por defecto y gestión.

Define los agentes por defecto del sistema y proporciona funciones
para resolver agentes desde configuración YAML.
"""

from typing import Any

from ..config.schema import AgentConfig
from .prompts import DEFAULT_PROMPTS


# Configuraciones de agentes por defecto
DEFAULT_AGENTS: dict[str, AgentConfig] = {
    "plan": AgentConfig(
        system_prompt=DEFAULT_PROMPTS["plan"],
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="confirm-all",
        max_steps=10,
    ),
    "build": AgentConfig(
        system_prompt=DEFAULT_PROMPTS["build"],
        allowed_tools=[
            "read_file",
            "write_file",
            "edit_file",
            "apply_patch",
            "delete_file",
            "list_files",
            "search_code",
            "grep",
            "find_files",
        ],
        confirm_mode="confirm-sensitive",
        max_steps=25,
    ),
    "resume": AgentConfig(
        system_prompt=DEFAULT_PROMPTS["resume"],
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=10,
    ),
    "review": AgentConfig(
        system_prompt=DEFAULT_PROMPTS["review"],
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=15,
    ),
}


class AgentNotFoundError(Exception):
    """Error lanzado cuando un agente solicitado no existe."""

    pass


def get_agent(
    agent_name: str | None,
    yaml_agents: dict[str, AgentConfig],
    cli_overrides: dict[str, Any] | None = None,
) -> AgentConfig:
    """Obtiene la configuración de un agente, con merge de fuentes.

    Orden de precedencia (de menor a mayor):
    1. Defaults (DEFAULT_AGENTS)
    2. YAML config
    3. CLI overrides

    Args:
        agent_name: Nombre del agente a obtener
        yaml_agents: Agentes definidos en YAML
        cli_overrides: Overrides desde CLI (mode, max_steps, etc.)

    Returns:
        AgentConfig completa con todos los merges aplicados

    Raises:
        AgentNotFoundError: Si el agente no existe en defaults ni YAML
    """
    cli_overrides = cli_overrides or {}

    # Si no se especifica agente, retornar None (indica modo mixto)
    if agent_name is None:
        return None  # type: ignore

    # Merge de configuraciones
    merged = _merge_agent_config(agent_name, yaml_agents)

    # Aplicar CLI overrides
    if cli_overrides:
        merged = _apply_cli_overrides(merged, cli_overrides)

    return merged


def _merge_agent_config(
    agent_name: str,
    yaml_agents: dict[str, AgentConfig],
) -> AgentConfig:
    """Merge de configuración de agente desde defaults y YAML.

    Args:
        agent_name: Nombre del agente
        yaml_agents: Agentes desde YAML

    Returns:
        AgentConfig merged

    Raises:
        AgentNotFoundError: Si el agente no existe
    """
    # Verificar si existe en defaults
    if agent_name in DEFAULT_AGENTS:
        base = DEFAULT_AGENTS[agent_name]

        # Si también está en YAML, hacer merge
        if agent_name in yaml_agents:
            yaml_config = yaml_agents[agent_name]
            # Pydantic model_copy con update hace el merge
            return base.model_copy(update=yaml_config.model_dump(exclude_unset=True))

        return base

    # Si no está en defaults, verificar en YAML
    if agent_name in yaml_agents:
        return yaml_agents[agent_name]

    # No existe en ningún lado
    available = set(DEFAULT_AGENTS.keys()) | set(yaml_agents.keys())
    raise AgentNotFoundError(
        f"Agente '{agent_name}' no encontrado. "
        f"Agentes disponibles: {', '.join(sorted(available))}"
    )


def _apply_cli_overrides(
    agent: AgentConfig,
    overrides: dict[str, Any],
) -> AgentConfig:
    """Aplica overrides desde CLI a un AgentConfig.

    Args:
        agent: Configuración base del agente
        overrides: Dict con overrides (mode, max_steps, etc.)

    Returns:
        Nuevo AgentConfig con overrides aplicados
    """
    update_dict = {}

    # Mapear CLI args a campos de AgentConfig
    if "mode" in overrides and overrides["mode"]:
        update_dict["confirm_mode"] = overrides["mode"]

    if "max_steps" in overrides and overrides["max_steps"]:
        update_dict["max_steps"] = overrides["max_steps"]

    # Si hay overrides, aplicarlos
    if update_dict:
        return agent.model_copy(update=update_dict)

    return agent


def list_available_agents(yaml_agents: dict[str, AgentConfig]) -> list[str]:
    """Lista todos los agentes disponibles (defaults + YAML).

    Args:
        yaml_agents: Agentes desde YAML

    Returns:
        Lista de nombres de agentes disponibles (ordenada)
    """
    available = set(DEFAULT_AGENTS.keys()) | set(yaml_agents.keys())
    return sorted(available)


def resolve_agents_from_yaml(yaml_agents: dict[str, Any]) -> dict[str, AgentConfig]:
    """Resuelve y valida agentes desde configuración YAML.

    Args:
        yaml_agents: Dict raw desde YAML

    Returns:
        Dict de AgentConfig validados

    Note:
        Esta función convierte el dict YAML en AgentConfig instances,
        validando con Pydantic.
    """
    resolved = {}

    for name, config in yaml_agents.items():
        if isinstance(config, AgentConfig):
            # Ya es un AgentConfig (desde load_config)
            resolved[name] = config
        elif isinstance(config, dict):
            # Convertir dict a AgentConfig
            resolved[name] = AgentConfig(**config)
        else:
            raise ValueError(
                f"Configuración de agente '{name}' inválida. "
                f"Debe ser un dict con las claves apropiadas."
            )

    return resolved
