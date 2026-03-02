"""
Agent registry — Default configurations and resolution.

Defines the system's default agents and provides functions
to resolve agents from YAML configuration.

Prompts are resolved lazily via i18n so they respect the current language.
"""

from typing import Any

from ..config.schema import AgentConfig
from .prompts import get_default_prompt


# Agent definitions WITHOUT system_prompt (resolved lazily)
_AGENT_DEFS: dict[str, dict[str, Any]] = {
    "plan": dict(
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=20,
    ),
    "build": dict(
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
            "run_command",
        ],
        confirm_mode="confirm-sensitive",
        max_steps=50,
    ),
    "resume": dict(
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=15,
    ),
    "review": dict(
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=20,
    ),
}


def _build_agent(name: str) -> AgentConfig:
    """Build an AgentConfig with the current-language prompt."""
    return AgentConfig(
        system_prompt=get_default_prompt(name),
        **_AGENT_DEFS[name],
    )


class _LazyAgentDict(dict):
    """Lazy dict that builds AgentConfig on each access.

    Ensures system_prompt always reflects the current i18n language.
    """

    def __getitem__(self, key: str) -> AgentConfig:
        if key not in _AGENT_DEFS:
            raise KeyError(key)
        return _build_agent(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in _AGENT_DEFS:
            return _build_agent(key)
        return default

    def __contains__(self, key: object) -> bool:
        return key in _AGENT_DEFS

    def keys(self):
        return _AGENT_DEFS.keys()

    def values(self):
        return [_build_agent(k) for k in _AGENT_DEFS]

    def items(self):
        return [(k, _build_agent(k)) for k in _AGENT_DEFS]

    def __iter__(self):
        return iter(_AGENT_DEFS)

    def __len__(self):
        return len(_AGENT_DEFS)


DEFAULT_AGENTS: dict[str, AgentConfig] = _LazyAgentDict()


class AgentNotFoundError(Exception):
    """Error raised when a requested agent does not exist."""

    pass


def get_agent(
    agent_name: str | None,
    yaml_agents: dict[str, AgentConfig],
    cli_overrides: dict[str, Any] | None = None,
) -> AgentConfig:
    """Get the configuration of an agent, merging from multiple sources.

    Precedence order (lowest to highest):
    1. Defaults (DEFAULT_AGENTS)
    2. YAML config
    3. CLI overrides

    Args:
        agent_name: Name of the agent to retrieve
        yaml_agents: Agents defined in YAML
        cli_overrides: Overrides from CLI (mode, max_steps, etc.)

    Returns:
        Complete AgentConfig with all merges applied

    Raises:
        AgentNotFoundError: If the agent does not exist in defaults or YAML
    """
    cli_overrides = cli_overrides or {}

    # If no agent specified, return None (indicates mixed mode)
    if agent_name is None:
        return None  # type: ignore

    # Merge configurations
    merged = _merge_agent_config(agent_name, yaml_agents)

    # Apply CLI overrides
    if cli_overrides:
        merged = _apply_cli_overrides(merged, cli_overrides)

    return merged


def _merge_agent_config(
    agent_name: str,
    yaml_agents: dict[str, AgentConfig],
) -> AgentConfig:
    """Merge agent configuration from defaults and YAML.

    Args:
        agent_name: Name of the agent
        yaml_agents: Agents from YAML

    Returns:
        Merged AgentConfig

    Raises:
        AgentNotFoundError: If the agent does not exist
    """
    # Check if it exists in defaults
    if agent_name in DEFAULT_AGENTS:
        base = DEFAULT_AGENTS[agent_name]

        # If also in YAML, merge
        if agent_name in yaml_agents:
            yaml_config = yaml_agents[agent_name]
            # Pydantic model_copy with update performs the merge
            return base.model_copy(update=yaml_config.model_dump(exclude_unset=True))

        return base

    # If not in defaults, check YAML
    if agent_name in yaml_agents:
        return yaml_agents[agent_name]

    # Does not exist anywhere
    available = set(DEFAULT_AGENTS.keys()) | set(yaml_agents.keys())
    raise AgentNotFoundError(
        f"Agent '{agent_name}' not found. "
        f"Available agents: {', '.join(sorted(available))}"
    )


def _apply_cli_overrides(
    agent: AgentConfig,
    overrides: dict[str, Any],
) -> AgentConfig:
    """Apply overrides from CLI to an AgentConfig.

    Args:
        agent: Base agent configuration
        overrides: Dict with overrides (mode, max_steps, etc.)

    Returns:
        New AgentConfig with overrides applied
    """
    update_dict = {}

    # Map CLI args to AgentConfig fields
    if "mode" in overrides and overrides["mode"]:
        update_dict["confirm_mode"] = overrides["mode"]

    if "max_steps" in overrides and overrides["max_steps"]:
        update_dict["max_steps"] = overrides["max_steps"]

    # If there are overrides, apply them
    if update_dict:
        return agent.model_copy(update=update_dict)

    return agent


def list_available_agents(yaml_agents: dict[str, AgentConfig]) -> list[str]:
    """List all available agents (defaults + YAML).

    Args:
        yaml_agents: Agents from YAML

    Returns:
        Sorted list of available agent names
    """
    available = set(DEFAULT_AGENTS.keys()) | set(yaml_agents.keys())
    return sorted(available)


def resolve_agents_from_yaml(yaml_agents: dict[str, Any]) -> dict[str, AgentConfig]:
    """Resolve and validate agents from YAML configuration.

    Args:
        yaml_agents: Raw dict from YAML

    Returns:
        Dict of validated AgentConfig instances

    Note:
        This function converts the YAML dict into AgentConfig instances,
        validating with Pydantic.
    """
    resolved = {}

    for name, config in yaml_agents.items():
        if isinstance(config, AgentConfig):
            # Already an AgentConfig (from load_config)
            resolved[name] = config
        elif isinstance(config, dict):
            # Convert dict to AgentConfig
            resolved[name] = AgentConfig(**config)
        else:
            raise ValueError(
                f"Invalid agent configuration for '{name}'. "
                f"Must be a dict with the appropriate keys."
            )

    return resolved
