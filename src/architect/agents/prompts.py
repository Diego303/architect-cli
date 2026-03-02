"""
System prompts for architect's default agents.

Prompts are resolved lazily via i18n at access time, so they
respect the current language setting. The _PromptProxy dict
provides backward compatibility: DEFAULT_PROMPTS["build"] works
exactly as before, but now resolves from the i18n registry.
"""

from typing import Any

from architect.i18n import get_prompt


def get_default_prompt(agent_name: str) -> str:
    """Get the default system prompt for a built-in agent.

    Args:
        agent_name: One of "plan", "build", "resume", "review".

    Returns:
        The system prompt in the current language.
    """
    return get_prompt(f"prompt.{agent_name}")


# Backward-compatible constants — resolve lazily on each access
# so they always reflect the current language.
_AGENT_NAMES = ("plan", "build", "resume", "review")


class _PromptProxy(dict):
    """Lazy dict that resolves prompts from i18n on each access.

    This preserves backward compatibility for code that reads
    DEFAULT_PROMPTS["build"] or DEFAULT_PROMPTS.get("plan").
    """

    def __getitem__(self, key: str) -> str:
        return get_default_prompt(key)

    def get(self, key: str, default: str = "") -> str:
        if key in _AGENT_NAMES:
            return get_default_prompt(key)
        return default

    def __contains__(self, key: object) -> bool:
        return key in _AGENT_NAMES

    def keys(self):
        return dict.fromkeys(_AGENT_NAMES).keys()

    def values(self):
        return [get_default_prompt(k) for k in _AGENT_NAMES]

    def items(self):
        return [(k, get_default_prompt(k)) for k in _AGENT_NAMES]

    def __iter__(self):
        return iter(_AGENT_NAMES)

    def __len__(self):
        return len(_AGENT_NAMES)


DEFAULT_PROMPTS: dict[str, str] = _PromptProxy()


# Backward-compatible module-level "constants".
# They are actually _LazyStr descriptors so the prompt is resolved
# lazily from the current i18n language on every string operation.

class _LazyStr:
    """String-like descriptor that resolves a prompt lazily."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __str__(self) -> str:
        return get_default_prompt(self._name)

    def __repr__(self) -> str:
        return f"<LazyStr:{self._name}>"

    def __contains__(self, item: str) -> bool:
        return item in str(self)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return str(self) == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(str(self))

    def __len__(self) -> int:
        return len(str(self))

    def lower(self) -> str:
        return str(self).lower()

    def strip(self) -> str:
        return str(self).strip()


# These names are kept for backward compatibility with code that does:
#   from architect.agents.prompts import BUILD_PROMPT
PLAN_PROMPT: Any = _LazyStr("plan")
BUILD_PROMPT: Any = _LazyStr("build")
RESUME_PROMPT: Any = _LazyStr("resume")
REVIEW_PROMPT: Any = _LazyStr("review")
