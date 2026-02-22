"""
Cargador de configuración con deep merge.

Orden de precedencia (de menor a mayor):
1. Defaults (definidos en los schemas Pydantic)
2. Archivo YAML
3. Variables de entorno
4. Argumentos CLI

El merge es recursivo para preservar todas las claves en todos los niveles.
"""

import os
from pathlib import Path
from typing import Any

import yaml

from .schema import AppConfig


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge recursivo de diccionarios.

    Args:
        base: Diccionario base
        override: Diccionario que sobreescribe valores del base

    Returns:
        Nuevo diccionario con valores merged. Override gana en conflictos de hojas.

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
    """Carga configuración desde archivo YAML.

    Args:
        config_path: Path al archivo YAML, o None para omitir

    Returns:
        Diccionario con la configuración, o dict vacío si no hay archivo
    """
    if not config_path:
        return {}

    if not config_path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data if data else {}


def load_env_overrides() -> dict[str, Any]:
    """Carga overrides desde variables de entorno.

    Variables soportadas:
        ARCHITECT_MODEL: sobreescribe llm.model
        ARCHITECT_API_BASE: sobreescribe llm.api_base
        ARCHITECT_LOG_LEVEL: sobreescribe logging.level
        ARCHITECT_WORKSPACE: sobreescribe workspace.root

    Returns:
        Diccionario con overrides desde env vars
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

    return overrides


def apply_cli_overrides(config_dict: dict[str, Any], cli_args: dict[str, Any]) -> dict[str, Any]:
    """Aplica overrides desde argumentos CLI.

    Args:
        config_dict: Configuración base (ya merged con YAML y env)
        cli_args: Diccionario con argumentos CLI

    Returns:
        Configuración con overrides de CLI aplicados
    """
    overrides: dict[str, Any] = {}

    # LLM overrides
    if cli_args.get("model"):
        overrides.setdefault("llm", {})["model"] = cli_args["model"]

    if cli_args.get("api_base"):
        overrides.setdefault("llm", {})["api_base"] = cli_args["api_base"]

    if cli_args.get("no_stream") is not None:
        overrides.setdefault("llm", {})["stream"] = not cli_args["no_stream"]

    # NOTA: --timeout de la CLI es el timeout TOTAL de la sesión (watchdog),
    # NO el timeout per-request del LLM. El timeout per-request se configura
    # en el YAML (llm.timeout, default 60s). No aplicar aquí para evitar
    # que un --timeout bajo mate las llamadas individuales al LLM.

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
    """Carga y valida la configuración completa de la aplicación.

    Proceso de carga:
    1. Cargar defaults de Pydantic
    2. Merge con YAML (si existe)
    3. Merge con env vars
    4. Merge con CLI args
    5. Validar con Pydantic

    Args:
        config_path: Path al archivo YAML de configuración
        cli_args: Diccionario con argumentos de la CLI

    Returns:
        AppConfig validado y completo

    Raises:
        FileNotFoundError: Si config_path no existe
        ValidationError: Si la configuración final no es válida
    """
    cli_args = cli_args or {}

    # 1. Defaults vienen de Pydantic (AppConfig())
    # 2. Cargar YAML
    yaml_config = load_yaml_config(config_path)

    # 3. Merge con env vars
    env_overrides = load_env_overrides()
    merged = deep_merge(yaml_config, env_overrides)

    # 4. Merge con CLI args
    merged = apply_cli_overrides(merged, cli_args)

    # 5. Validar con Pydantic (esto aplica los defaults automáticamente)
    return AppConfig(**merged)
