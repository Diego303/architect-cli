"""
Módulo de agentes - Configuraciones y prompts de agentes especializados.

Exporta agentes por defecto, prompts y funciones de resolución.
"""

from .prompts import (
    BUILD_PROMPT,
    DEFAULT_PROMPTS,
    PLAN_PROMPT,
    RESUME_PROMPT,
    REVIEW_PROMPT,
)
from .registry import (
    DEFAULT_AGENTS,
    AgentNotFoundError,
    get_agent,
    list_available_agents,
    resolve_agents_from_yaml,
)

__all__ = [
    # Prompts
    "PLAN_PROMPT",
    "BUILD_PROMPT",
    "RESUME_PROMPT",
    "REVIEW_PROMPT",
    "DEFAULT_PROMPTS",
    # Registry
    "DEFAULT_AGENTS",
    "get_agent",
    "list_available_agents",
    "resolve_agents_from_yaml",
    "AgentNotFoundError",
]
