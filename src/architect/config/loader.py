"""
Configuration loader with deep merge.

Order of precedence (lowest to highest):
1. Defaults (defined in Pydantic schemas)
2. YAML file
3. Environment variables
4. CLI arguments

The merge is recursive to preserve all keys at all levels.
"""

import os
from pathlib import Path
from typing import Any

import yaml

from .schema import AppConfig


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive dictionary merge.

    Args:
        base: Base dictionary
        override: Dictionary that overrides values from base

    Returns:
        New dictionary with merged values. Override wins on leaf conflicts.

    Example:
        >>> base = {"a": {"b": 1, "c": 2}, "d": 3}
        >>> override = {"a": {"b": 99}, "e": 4}
        >>> deep_merge(base, override)
        {"a": {"b": 99, "c": 2}, "d": 3, "e": 4}
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_config(config_path: Path | None) -> dict[str, Any]:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the YAML file, or None to skip

    Returns:
        Dictionary with configuration, or empty dict if no file
    """
    if not config_path:
        return {}

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data if data else {}


def load_env_overrides() -> dict[str, Any]:
    """Load overrides from environment variables.

    Supported variables:
        ARCHITECT_MODEL: overrides llm.model
        ARCHITECT_API_BASE: overrides llm.api_base
        ARCHITECT_LOG_LEVEL: overrides logging.level
        ARCHITECT_WORKSPACE: overrides workspace.root

    Returns:
        Dictionary with overrides from env vars
    """
    overrides: dict[str, Any] = {}

    # LLM config
    if model := os.environ.get("ARCHITECT_MODEL"):
        overrides.setdefault("llm", {})["model"] = model

    if api_base := os.environ.get("ARCHITECT_API_BASE"):
        overrides.setdefault("llm", {})["api_base"] = api_base

    # Logging config
    if log_level := os.environ.get("ARCHITECT_LOG_LEVEL"):
        overrides.setdefault("logging", {})["level"] = log_level.lower()

    # Workspace config
    if workspace := os.environ.get("ARCHITECT_WORKSPACE"):
        overrides.setdefault("workspace", {})["root"] = workspace

    # Language config
    if lang := os.environ.get("ARCHITECT_LANGUAGE"):
        overrides["language"] = lang.lower()

    return overrides


def apply_cli_overrides(config_dict: dict[str, Any], cli_args: dict[str, Any]) -> dict[str, Any]:
    """Apply overrides from CLI arguments.

    Args:
        config_dict: Base configuration (already merged with YAML and env)
        cli_args: Dictionary with CLI arguments

    Returns:
        Configuration with CLI overrides applied
    """
    overrides: dict[str, Any] = {}

    # LLM overrides
    if cli_args.get("model"):
        overrides.setdefault("llm", {})["model"] = cli_args["model"]

    if cli_args.get("api_base"):
        overrides.setdefault("llm", {})["api_base"] = cli_args["api_base"]

    if cli_args.get("no_stream") is not None:
        overrides.setdefault("llm", {})["stream"] = not cli_args["no_stream"]

    # NOTE: --timeout from the CLI is the TOTAL session timeout (watchdog),
    # NOT the per-request LLM timeout. The per-request timeout is configured
    # in the YAML (llm.timeout, default 60s). Not applied here to avoid
    # a low --timeout killing individual LLM calls.

    # Workspace overrides
    if cli_args.get("workspace"):
        overrides.setdefault("workspace", {})["root"] = cli_args["workspace"]

    # Logging overrides
    if cli_args.get("log_level"):
        overrides.setdefault("logging", {})["level"] = cli_args["log_level"]

    if cli_args.get("log_file"):
        overrides.setdefault("logging", {})["file"] = cli_args["log_file"]

    if cli_args.get("verbose") is not None:
        overrides.setdefault("logging", {})["verbose"] = cli_args["verbose"]

    return deep_merge(config_dict, overrides)


def load_config(
    config_path: Path | None = None,
    cli_args: dict[str, Any] | None = None,
) -> AppConfig:
    """Load and validate the complete application configuration.

    Loading process:
    1. Load Pydantic defaults
    2. Merge with YAML (if it exists)
    3. Merge with env vars
    4. Merge with CLI args
    5. Validate with Pydantic

    Args:
        config_path: Path to the YAML configuration file
        cli_args: Dictionary with CLI arguments

    Returns:
        Validated and complete AppConfig

    Raises:
        FileNotFoundError: If config_path does not exist
        ValidationError: If the final configuration is not valid
    """
    cli_args = cli_args or {}

    # 1. Defaults come from Pydantic (AppConfig())
    # 2. Load YAML
    yaml_config = load_yaml_config(config_path)

    # 3. Merge with env vars
    env_overrides = load_env_overrides()
    merged = deep_merge(yaml_config, env_overrides)

    # 4. Merge with CLI args
    merged = apply_cli_overrides(merged, cli_args)

    # 5. Validate with Pydantic (this applies defaults automatically)
    return AppConfig(**merged)
