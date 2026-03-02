"""Tests for the i18n module — registry, translation, config integration."""

import pytest

from architect.i18n import get_language, get_prompt, set_language, t
from architect.i18n.registry import LanguageRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset singleton before and after each test."""
    LanguageRegistry.reset()
    yield
    LanguageRegistry.reset()


# ── LanguageRegistry ────────────────────────────────────────────────────


class TestLanguageRegistry:
    def test_singleton(self):
        a = LanguageRegistry.get()
        b = LanguageRegistry.get()
        assert a is b

    def test_default_language_is_english(self):
        reg = LanguageRegistry.get()
        assert reg.language == "en"

    def test_available_languages(self):
        reg = LanguageRegistry.get()
        assert "en" in reg.available_languages
        assert "es" in reg.available_languages

    def test_set_language_valid(self):
        reg = LanguageRegistry.get()
        reg.set_language("es")
        assert reg.language == "es"

    def test_set_language_invalid(self):
        reg = LanguageRegistry.get()
        with pytest.raises(ValueError, match="Unsupported language"):
            reg.set_language("fr")

    def test_reset(self):
        reg = LanguageRegistry.get()
        reg.set_language("es")
        assert reg.language == "es"
        LanguageRegistry.reset()
        reg2 = LanguageRegistry.get()
        assert reg2.language == "en"

    def test_register_custom_language(self):
        reg = LanguageRegistry.get()
        reg.register_language("fr", {"human.tool_ok": "      ✓ Bon"})
        reg.set_language("fr")
        assert reg.t("human.tool_ok") == "      ✓ Bon"

    def test_fallback_to_english(self):
        reg = LanguageRegistry.get()
        reg.register_language("fr", {})
        reg.set_language("fr")
        # Not in fr dict, falls back to en
        result = reg.t("human.tool_ok")
        assert result == "      ✓ OK"

    def test_fallback_to_raw_key(self):
        reg = LanguageRegistry.get()
        result = reg.t("nonexistent.key.here")
        assert result == "nonexistent.key.here"


# ── Public API ──────────────────────────────────────────────────────────


class TestPublicAPI:
    def test_t_basic(self):
        result = t("human.tool_ok")
        assert result == "      ✓ OK"

    def test_t_interpolation(self):
        result = t("human.llm_call", step=1, messages=5)
        assert "Step 1" in result
        assert "5 messages" in result

    def test_t_missing_key(self):
        result = t("missing.key")
        assert result == "missing.key"

    def test_t_bad_interpolation_keys(self):
        # If kwargs don't match template, return template without error
        result = t("human.llm_call", wrong_key=42)
        assert "step" in result.lower() or "{step}" in result

    def test_get_prompt(self):
        prompt = get_prompt("prompt.build")
        assert "software development agent" in prompt.lower()

    def test_get_language_default(self):
        assert get_language() == "en"

    def test_set_and_get_language(self):
        set_language("es")
        assert get_language() == "es"


# ── Language switching ──────────────────────────────────────────────────


class TestLanguageSwitching:
    def test_english_output(self):
        result = t("human.user_interrupt")
        assert "Interrupted by user" in result

    def test_spanish_output(self):
        set_language("es")
        result = t("human.user_interrupt")
        assert "Interrumpido por el usuario" in result

    def test_switch_back_and_forth(self):
        assert "Interrupted" in t("human.user_interrupt")
        set_language("es")
        assert "Interrumpido" in t("human.user_interrupt")
        set_language("en")
        assert "Interrupted" in t("human.user_interrupt")

    def test_prompt_switching(self):
        en_prompt = get_prompt("prompt.build")
        set_language("es")
        es_prompt = get_prompt("prompt.build")
        assert en_prompt != es_prompt
        assert "software development agent" in en_prompt.lower()
        assert "agente de desarrollo" in es_prompt.lower()

    def test_close_instructions_switching(self):
        en = t("close.max_steps")
        set_language("es")
        es = t("close.max_steps")
        assert "maximum allowed step limit" in en.lower()
        assert "límite máximo de pasos" in es.lower()


# ── Key parity ──────────────────────────────────────────────────────────


class TestKeyParity:
    def test_en_and_es_have_same_keys(self):
        from architect.i18n import en, es

        en_keys = set(en.STRINGS.keys())
        es_keys = set(es.STRINGS.keys())

        missing_in_es = en_keys - es_keys
        missing_in_en = es_keys - en_keys

        assert not missing_in_es, f"Keys in EN but not ES: {missing_in_es}"
        assert not missing_in_en, f"Keys in ES but not EN: {missing_in_en}"

    def test_no_empty_values_in_en(self):
        from architect.i18n import en

        empty = [k for k, v in en.STRINGS.items() if not v.strip()]
        assert not empty, f"Empty values in EN: {empty}"

    def test_no_empty_values_in_es(self):
        from architect.i18n import es

        empty = [k for k, v in es.STRINGS.items() if not v.strip()]
        assert not empty, f"Empty values in ES: {empty}"


# ── Config integration ──────────────────────────────────────────────────


class TestConfigIntegration:
    def test_appconfig_language_default(self):
        from architect.config.schema import AppConfig

        cfg = AppConfig()
        assert cfg.language == "en"

    def test_appconfig_language_es(self):
        from architect.config.schema import AppConfig

        cfg = AppConfig(language="es")
        assert cfg.language == "es"

    def test_appconfig_language_invalid(self):
        from pydantic import ValidationError

        from architect.config.schema import AppConfig

        with pytest.raises(ValidationError):
            AppConfig(language="fr")

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("ARCHITECT_LANGUAGE", "es")
        from architect.config.loader import load_env_overrides

        overrides = load_env_overrides()
        assert overrides.get("language") == "es"

    def test_env_var_uppercase(self, monkeypatch):
        monkeypatch.setenv("ARCHITECT_LANGUAGE", "ES")
        from architect.config.loader import load_env_overrides

        overrides = load_env_overrides()
        assert overrides.get("language") == "es"


# ── Specific namespace checks ───────────────────────────────────────────


class TestNamespaces:
    def test_human_namespace_has_keys(self):
        from architect.i18n import en

        human_keys = [k for k in en.STRINGS if k.startswith("human.")]
        assert len(human_keys) >= 30

    def test_prompt_namespace_has_all_agents(self):
        for agent in ("build", "plan", "resume", "review", "review_system"):
            prompt = get_prompt(f"prompt.{agent}")
            assert len(prompt) > 50, f"Prompt for {agent} is too short"

    def test_close_namespace(self):
        for reason in ("max_steps", "budget_exceeded", "context_full", "timeout"):
            text = t(f"close.{reason}")
            assert len(text) > 20, f"Close instruction for {reason} is too short"

    def test_eval_namespace(self):
        text = t("eval.system_prompt")
        assert "json" in text.lower()

    def test_guardrail_namespace(self):
        text = t("guardrail.sensitive_blocked", file="secret.key", pattern="*.key")
        assert "secret.key" in text
        assert "*.key" in text

    def test_dispatch_namespace(self):
        text = t("dispatch.description")
        assert "sub-task" in text.lower() or "sub-agent" in text.lower()

    def test_ralph_namespace(self):
        text = t("ralph.task_header", task="My task")
        assert "My task" in text

    def test_reviewer_namespace(self):
        text = t("reviewer.prompt", task="Do X", diff="+line")
        assert "Do X" in text
        assert "+line" in text

    def test_health_namespace(self):
        text = t("health.title")
        assert "Health" in text

    def test_competitive_namespace(self):
        text = t("competitive.report_title")
        assert "Competitive" in text
