"""
Language Registry — Singleton thread-safe for managing translations.

Provides a central registry of language strings with fallback chain:
current_lang → "en" → raw key.
"""

import threading


class LanguageRegistry:
    """Thread-safe singleton that stores and resolves translation strings.

    The registry holds dictionaries of strings for each supported language.
    Resolution follows a fallback chain: current language → English → raw key.

    Usage:
        registry = LanguageRegistry.get()
        registry.set_language("es")
        text = registry.t("human.llm_call", step=1, messages=5)
    """

    _instance: "LanguageRegistry | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._languages: dict[str, dict[str, str]] = {}
        self._current = "en"

    @classmethod
    def get(cls) -> "LanguageRegistry":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = cls()
                    inst._load_defaults()
                    cls._instance = inst
        return cls._instance

    def _load_defaults(self) -> None:
        """Load built-in language packs (EN and ES)."""
        from . import en, es

        self._languages["en"] = en.STRINGS
        self._languages["es"] = es.STRINGS

    @property
    def language(self) -> str:
        """Current language code."""
        return self._current

    @property
    def available_languages(self) -> list[str]:
        """List of registered language codes."""
        return sorted(self._languages.keys())

    def set_language(self, lang: str) -> None:
        """Set the active language.

        Args:
            lang: Language code (e.g. "en", "es").

        Raises:
            ValueError: If the language is not registered.
        """
        if lang not in self._languages:
            raise ValueError(
                f"Unsupported language: {lang}. "
                f"Available: {sorted(self._languages)}"
            )
        self._current = lang

    def t(self, key: str, **kwargs: object) -> str:
        """Translate a key with optional interpolation.

        Fallback chain: current language → English → raw key.

        Args:
            key: Translation key (e.g. "human.llm_call").
            **kwargs: Format string arguments.

        Returns:
            Translated and formatted string.
        """
        strings = self._languages.get(self._current, {})
        template = (
            strings.get(key)
            or self._languages.get("en", {}).get(key)
            or key
        )
        if kwargs:
            try:
                return template.format(**kwargs)
            except (KeyError, IndexError):
                return template
        return template

    def register_language(self, lang: str, strings: dict[str, str]) -> None:
        """Register a new language pack.

        Args:
            lang: Language code.
            strings: Dictionary mapping keys to translated strings.
        """
        self._languages[lang] = strings

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None
