"""
Internationalization (i18n) for architect-cli.

Public API:
    t(key, **kwargs)      — Translate a key with optional interpolation.
    get_prompt(key)       — Get a multiline agent prompt for the current language.
    set_language(lang)    — Set the active language ("en", "es").
    get_language()        — Get the current language code.

Usage:
    from architect.i18n import t, set_language

    set_language("es")
    print(t("human.llm_call", step=1, messages=5))
"""

from .registry import LanguageRegistry

__all__ = [
    "t",
    "get_prompt",
    "set_language",
    "get_language",
]


def t(key: str, **kwargs: object) -> str:
    """Translate a key with optional interpolation.

    Uses the current language with English fallback.

    Args:
        key: Translation key (e.g. "human.llm_call").
        **kwargs: Format string arguments.

    Returns:
        Translated and formatted string.
    """
    return LanguageRegistry.get().t(key, **kwargs)


def get_prompt(key: str) -> str:
    """Get a multiline agent prompt for the current language.

    Equivalent to t(key) but semantically clearer for prompt retrieval.

    Args:
        key: Prompt key (e.g. "prompt.build").

    Returns:
        Full prompt text in the current language.
    """
    return LanguageRegistry.get().t(key)


def set_language(lang: str) -> None:
    """Set the active language.

    Args:
        lang: Language code ("en" or "es").

    Raises:
        ValueError: If the language is not supported.
    """
    LanguageRegistry.get().set_language(lang)


def get_language() -> str:
    """Get the current language code.

    Returns:
        Current language code (e.g. "en").
    """
    return LanguageRegistry.get().language
