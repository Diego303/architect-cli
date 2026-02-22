#!/usr/bin/env python3
"""
Test Config Loader: deep_merge, env vars, CLI overrides, full pipeline.

Valida:
- deep_merge() recursivo
- load_yaml_config() con archivos temporales
- load_env_overrides() con ARCHITECT_* env vars
- apply_cli_overrides() con todos los argumentos
- load_config() pipeline completo con precedencia
- Validación Pydantic (extra="forbid", enums)

Ejecutar:
    python scripts/test_config_loader.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ── Helpers ──────────────────────────────────────────────────────────────────

PASSED = 0
FAILED = 0


def ok(name: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  \u2713 {name}")


def fail(name: str, detail: str = "") -> None:
    global FAILED
    FAILED += 1
    msg = f"  \u2717 {name}"
    if detail:
        msg += f": {detail}"
    print(msg)


def section(title: str) -> None:
    print(f"\n\u2500\u2500 {title} {'\u2500' * (55 - len(title))}")


# ── Imports ──────────────────────────────────────────────────────────────────

from architect.config.loader import (
    apply_cli_overrides,
    deep_merge,
    load_config,
    load_env_overrides,
    load_yaml_config,
)
from architect.config.schema import AppConfig


# ── Env var cleanup helper ───────────────────────────────────────────────────

_ENV_VARS = ["ARCHITECT_MODEL", "ARCHITECT_API_BASE", "ARCHITECT_LOG_LEVEL", "ARCHITECT_WORKSPACE"]


def _clean_env():
    """Remove ARCHITECT_* env vars for clean test state."""
    for var in _ENV_VARS:
        os.environ.pop(var, None)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: deep_merge()
# ══════════════════════════════════════════════════════════════════════════════

def test_deep_merge():
    section("deep_merge()")

    # 1.1 Empty dicts
    result = deep_merge({}, {})
    if result == {}:
        ok("Empty dicts → {}")
    else:
        fail("Empty dicts", f"got {result}")

    # 1.2 Flat merge without conflicts
    result = deep_merge({"a": 1}, {"b": 2})
    if result == {"a": 1, "b": 2}:
        ok("Flat merge without conflicts")
    else:
        fail("Flat merge without conflicts", f"got {result}")

    # 1.3 Flat merge with override winning
    result = deep_merge({"a": 1, "b": 2}, {"b": 99})
    if result == {"a": 1, "b": 99}:
        ok("Flat merge: override wins on conflict")
    else:
        fail("Flat merge: override wins", f"got {result}")

    # 1.4 Nested merge preserving deep keys
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 99}, "e": 4}
    result = deep_merge(base, override)
    expected = {"a": {"b": 99, "c": 2}, "d": 3, "e": 4}
    if result == expected:
        ok("Nested merge preserves deep keys (c: 2 kept)")
    else:
        fail("Nested merge", f"got {result}")

    # 1.5 3-level deep merge
    base = {"x": {"y": {"z": 1, "w": 2}}}
    override = {"x": {"y": {"z": 99}}}
    result = deep_merge(base, override)
    if result == {"x": {"y": {"z": 99, "w": 2}}}:
        ok("3-level deep merge (w: 2 preserved)")
    else:
        fail("3-level deep merge", f"got {result}")

    # 1.6 Override replaces dict with scalar
    result = deep_merge({"a": {"nested": True}}, {"a": "flat"})
    if result == {"a": "flat"}:
        ok("Override replaces dict with scalar")
    else:
        fail("Override replaces dict with scalar", f"got {result}")

    # 1.7 Override replaces scalar with dict
    result = deep_merge({"a": "flat"}, {"a": {"nested": True}})
    if result == {"a": {"nested": True}}:
        ok("Override replaces scalar with dict")
    else:
        fail("Override replaces scalar with dict", f"got {result}")

    # 1.8 List values are replaced, not merged
    result = deep_merge({"a": [1, 2]}, {"a": [3, 4, 5]})
    if result == {"a": [3, 4, 5]}:
        ok("List values are replaced (not merged)")
    else:
        fail("List values replacement", f"got {result}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: load_yaml_config()
# ══════════════════════════════════════════════════════════════════════════════

def test_load_yaml_config():
    section("load_yaml_config()")

    # 2.1 None path returns {}
    result = load_yaml_config(None)
    if result == {}:
        ok("None path → {}")
    else:
        fail("None path", f"got {result}")

    # 2.2 Non-existent file raises FileNotFoundError
    try:
        load_yaml_config(Path("/nonexistent/config.yaml"))
        fail("Non-existent file raises FileNotFoundError", "did not raise")
    except FileNotFoundError:
        ok("Non-existent file raises FileNotFoundError")
    except Exception as e:
        fail("Non-existent file", f"raised {type(e).__name__}")

    # 2.3 Valid YAML file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("llm:\n  model: claude-3\n  timeout: 120\n")
        f.flush()
        try:
            result = load_yaml_config(Path(f.name))
            if result == {"llm": {"model": "claude-3", "timeout": 120}}:
                ok("Valid YAML file loads correctly")
            else:
                fail("Valid YAML file", f"got {result}")
        finally:
            os.unlink(f.name)

    # 2.4 Empty YAML returns {}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("")
        f.flush()
        try:
            result = load_yaml_config(Path(f.name))
            if result == {}:
                ok("Empty YAML returns {}")
            else:
                fail("Empty YAML", f"got {result}")
        finally:
            os.unlink(f.name)

    # 2.5 YAML with nested structure loads correctly
    yaml_content = """
llm:
  model: gpt-4o
  api_base: http://localhost:4000
logging:
  level: debug
workspace:
  root: /tmp/test
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            result = load_yaml_config(Path(f.name))
            if (result.get("llm", {}).get("model") == "gpt-4o"
                    and result.get("logging", {}).get("level") == "debug"
                    and result.get("workspace", {}).get("root") == "/tmp/test"):
                ok("YAML with nested structure loads correctly")
            else:
                fail("Nested YAML", f"got {result}")
        finally:
            os.unlink(f.name)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: load_env_overrides()
# ══════════════════════════════════════════════════════════════════════════════

def test_load_env_overrides():
    section("load_env_overrides()")

    # 3.1 No env vars returns {}
    _clean_env()
    result = load_env_overrides()
    if result == {}:
        ok("No ARCHITECT_* env vars → {}")
    else:
        fail("No env vars", f"got {result}")

    # 3.2 ARCHITECT_MODEL sets llm.model
    _clean_env()
    os.environ["ARCHITECT_MODEL"] = "claude-3-opus"
    result = load_env_overrides()
    if result.get("llm", {}).get("model") == "claude-3-opus":
        ok("ARCHITECT_MODEL → llm.model")
    else:
        fail("ARCHITECT_MODEL", f"got {result}")

    # 3.3 ARCHITECT_API_BASE sets llm.api_base
    _clean_env()
    os.environ["ARCHITECT_API_BASE"] = "http://proxy:4000"
    result = load_env_overrides()
    if result.get("llm", {}).get("api_base") == "http://proxy:4000":
        ok("ARCHITECT_API_BASE → llm.api_base")
    else:
        fail("ARCHITECT_API_BASE", f"got {result}")

    # 3.4 ARCHITECT_LOG_LEVEL sets logging.level (lowercased)
    _clean_env()
    os.environ["ARCHITECT_LOG_LEVEL"] = "DEBUG"
    result = load_env_overrides()
    if result.get("logging", {}).get("level") == "debug":
        ok("ARCHITECT_LOG_LEVEL=DEBUG → logging.level='debug' (lowercased)")
    else:
        fail("ARCHITECT_LOG_LEVEL", f"got {result}")

    # 3.5 ARCHITECT_WORKSPACE sets workspace.root
    _clean_env()
    os.environ["ARCHITECT_WORKSPACE"] = "/custom/workspace"
    result = load_env_overrides()
    if result.get("workspace", {}).get("root") == "/custom/workspace":
        ok("ARCHITECT_WORKSPACE → workspace.root")
    else:
        fail("ARCHITECT_WORKSPACE", f"got {result}")

    # 3.6 Multiple env vars combine correctly
    _clean_env()
    os.environ["ARCHITECT_MODEL"] = "gpt-4o-mini"
    os.environ["ARCHITECT_LOG_LEVEL"] = "warn"
    result = load_env_overrides()
    if (result.get("llm", {}).get("model") == "gpt-4o-mini"
            and result.get("logging", {}).get("level") == "warn"):
        ok("Multiple env vars combine correctly")
    else:
        fail("Multiple env vars", f"got {result}")

    _clean_env()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: apply_cli_overrides()
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_cli_overrides():
    section("apply_cli_overrides()")

    base = {"llm": {"model": "gpt-4o", "timeout": 60}}

    # 4.1 Empty cli_args returns unchanged config
    result = apply_cli_overrides(base, {})
    if result == base:
        ok("Empty cli_args returns unchanged config")
    else:
        fail("Empty cli_args", f"got {result}")

    # 4.2 model override
    result = apply_cli_overrides({}, {"model": "claude-3"})
    if result.get("llm", {}).get("model") == "claude-3":
        ok("model override → llm.model")
    else:
        fail("model override", f"got {result}")

    # 4.3 api_base override
    result = apply_cli_overrides({}, {"api_base": "http://localhost:4000"})
    if result.get("llm", {}).get("api_base") == "http://localhost:4000":
        ok("api_base override → llm.api_base")
    else:
        fail("api_base override", f"got {result}")

    # 4.4 no_stream=True sets stream=False
    result = apply_cli_overrides({}, {"no_stream": True})
    if result.get("llm", {}).get("stream") is False:
        ok("no_stream=True → llm.stream=False")
    else:
        fail("no_stream", f"got {result}")

    # 4.5 timeout CLI flag does NOT override llm.timeout
    # --timeout is the total session watchdog, not the per-request LLM timeout
    result = apply_cli_overrides({}, {"timeout": 120})
    if "llm" not in result or "timeout" not in result.get("llm", {}):
        ok("timeout CLI flag does NOT set llm.timeout (separate concerns)")
    else:
        fail("timeout should not set llm.timeout", f"got {result}")

    # 4.6 workspace override
    result = apply_cli_overrides({}, {"workspace": "/tmp/ws"})
    if result.get("workspace", {}).get("root") == "/tmp/ws":
        ok("workspace override → workspace.root")
    else:
        fail("workspace override", f"got {result}")

    # 4.7 log_level override
    result = apply_cli_overrides({}, {"log_level": "error"})
    if result.get("logging", {}).get("level") == "error":
        ok("log_level override → logging.level")
    else:
        fail("log_level override", f"got {result}")

    # 4.8 log_file override
    result = apply_cli_overrides({}, {"log_file": "/tmp/app.log"})
    if result.get("logging", {}).get("file") == "/tmp/app.log":
        ok("log_file override → logging.file")
    else:
        fail("log_file override", f"got {result}")

    # 4.9 verbose override
    result = apply_cli_overrides({}, {"verbose": 2})
    if result.get("logging", {}).get("verbose") == 2:
        ok("verbose override → logging.verbose")
    else:
        fail("verbose override", f"got {result}")

    # 4.10 Multiple overrides combine with existing config
    base = {"llm": {"model": "gpt-4o", "timeout": 60}, "logging": {"level": "info"}}
    result = apply_cli_overrides(base, {"model": "claude-3", "log_level": "debug"})
    if (result.get("llm", {}).get("model") == "claude-3"
            and result.get("llm", {}).get("timeout") == 60  # preserved
            and result.get("logging", {}).get("level") == "debug"):
        ok("Multiple CLI overrides merge correctly with existing config")
    else:
        fail("Multiple overrides", f"got {result}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: load_config() full pipeline
# ══════════════════════════════════════════════════════════════════════════════

def test_load_config():
    section("load_config() full pipeline")

    _clean_env()

    # 5.1 No args returns valid AppConfig with defaults
    config = load_config()
    if isinstance(config, AppConfig) and config.llm.model == "gpt-4o" and config.llm.timeout == 60:
        ok("No args → valid AppConfig with defaults (model=gpt-4o, timeout=60)")
    else:
        fail("No args defaults", f"got model={config.llm.model}")

    # 5.2 YAML file overrides defaults
    yaml_content = "llm:\n  model: gpt-4o-mini\n  timeout: 120\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            config = load_config(config_path=Path(f.name))
            if config.llm.model == "gpt-4o-mini" and config.llm.timeout == 120:
                ok("YAML overrides defaults (model=gpt-4o-mini, timeout=120)")
            else:
                fail("YAML overrides", f"got model={config.llm.model}, timeout={config.llm.timeout}")
        finally:
            os.unlink(f.name)

    # 5.3 Env vars override YAML
    yaml_content = "llm:\n  model: gpt-4o-mini\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        os.environ["ARCHITECT_MODEL"] = "claude-3-opus"
        try:
            config = load_config(config_path=Path(f.name))
            if config.llm.model == "claude-3-opus":
                ok("Env var overrides YAML (ARCHITECT_MODEL wins)")
            else:
                fail("Env overrides YAML", f"got model={config.llm.model}")
        finally:
            _clean_env()
            os.unlink(f.name)

    # 5.4 CLI args override env vars
    os.environ["ARCHITECT_MODEL"] = "from-env"
    try:
        config = load_config(cli_args={"model": "from-cli"})
        if config.llm.model == "from-cli":
            ok("CLI args override env vars (model=from-cli)")
        else:
            fail("CLI overrides env", f"got model={config.llm.model}")
    finally:
        _clean_env()

    # 5.5 Full precedence chain: defaults < YAML < env < CLI
    yaml_content = "llm:\n  model: from-yaml\n  timeout: 120\nlogging:\n  level: info\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        os.environ["ARCHITECT_MODEL"] = "from-env"
        os.environ["ARCHITECT_LOG_LEVEL"] = "warn"
        try:
            config = load_config(
                config_path=Path(f.name),
                cli_args={"model": "from-cli"},
            )
            # model: from-cli (CLI wins over env and YAML)
            # timeout: 120 (from YAML, no env/CLI override)
            # log_level: warn (from env, no CLI override)
            # retries: 2 (from defaults, no override)
            if (config.llm.model == "from-cli"
                    and config.llm.timeout == 120
                    and config.logging.level == "warn"
                    and config.llm.retries == 2):
                ok("Full precedence: defaults < YAML < env < CLI")
            else:
                fail("Full precedence", (
                    f"model={config.llm.model}, timeout={config.llm.timeout}, "
                    f"level={config.logging.level}, retries={config.llm.retries}"
                ))
        finally:
            _clean_env()
            os.unlink(f.name)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Pydantic validation in load_config()
# ══════════════════════════════════════════════════════════════════════════════

def test_pydantic_validation():
    section("Pydantic validation in load_config()")

    _clean_env()

    # 6.1 Invalid log level raises ValidationError
    from pydantic import ValidationError

    yaml_content = "logging:\n  level: invalid_level\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            load_config(config_path=Path(f.name))
            fail("Invalid log level raises ValidationError", "did not raise")
        except ValidationError:
            ok("Invalid log level raises ValidationError")
        except Exception as e:
            fail("Invalid log level", f"raised {type(e).__name__}: {e}")
        finally:
            os.unlink(f.name)

    # 6.2 Extra unknown keys raise ValidationError (extra="forbid")
    yaml_content = "llm:\n  model: gpt-4o\n  unknown_field: value\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            load_config(config_path=Path(f.name))
            fail("Extra unknown keys raise ValidationError", "did not raise")
        except ValidationError:
            ok("Extra unknown keys raise ValidationError (extra='forbid')")
        except Exception as e:
            fail("Extra unknown keys", f"raised {type(e).__name__}: {e}")
        finally:
            os.unlink(f.name)

    # 6.3 Valid custom config returns correct AppConfig
    yaml_content = """
llm:
  model: claude-3-haiku
  timeout: 30
  retries: 5
  stream: false
logging:
  level: debug
  verbose: 2
workspace:
  root: /tmp/custom
  allow_delete: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        try:
            config = load_config(config_path=Path(f.name))
            if (config.llm.model == "claude-3-haiku"
                    and config.llm.timeout == 30
                    and config.llm.retries == 5
                    and config.llm.stream is False
                    and config.logging.level == "debug"
                    and config.logging.verbose == 2
                    and config.workspace.allow_delete is True):
                ok("Valid custom config returns correct AppConfig")
            else:
                fail("Valid custom config", f"got {config}")
        except Exception as e:
            fail("Valid custom config", str(e))
        finally:
            os.unlink(f.name)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test Config Loader")
    print("=" * 60)

    test_deep_merge()
    test_load_yaml_config()
    test_load_env_overrides()
    test_apply_cli_overrides()
    test_load_config()
    test_pydantic_validation()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
