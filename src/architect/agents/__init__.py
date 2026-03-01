"""
Agents module — Default agent configurations, prompts, and resolution.

Exports default agents, prompts, and resolution functions.
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
from .reviewer import REVIEW_SYSTEM_PROMPT, AutoReviewer, ReviewResult

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
    # Reviewer (v4-C5)
    "REVIEW_SYSTEM_PROMPT",
    "AutoReviewer",
    "ReviewResult",
]
