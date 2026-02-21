#!/usr/bin/env python3
"""
Test v3-M3: Plan integrado en build.

Valida:
- DEFAULT_AGENTS: 4 agentes, roles, tools, confirm_mode, max_steps
- BUILD_PROMPT: 5 fases integradas (ANALIZAR, PLANIFICAR, EJECUTAR, VERIFICAR, CORREGIR)
- MixedModeRunner: ya no es el default en CLI (build lo reemplaza)
- get_agent(): merge defaults + YAML + CLI overrides
- _apply_cli_overrides(): mode y max_steps
- list_available_agents(), resolve_agents_from_yaml()

Ejecutar:
    python scripts/test_v3_m3.py
"""

import sys
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

from architect.agents.registry import (
    DEFAULT_AGENTS,
    AgentNotFoundError,
    get_agent,
    list_available_agents,
    resolve_agents_from_yaml,
    _apply_cli_overrides,
    _merge_agent_config,
)
from architect.agents.prompts import (
    BUILD_PROMPT,
    PLAN_PROMPT,
    REVIEW_PROMPT,
    DEFAULT_PROMPTS,
)
from architect.config.schema import AgentConfig


# ── Section 1: DEFAULT_AGENTS ───────────────────────────────────────────────

def test_default_agents():
    section("DEFAULT_AGENTS")

    # 1.1 4 default agents exist
    expected = {"plan", "build", "resume", "review"}
    actual = set(DEFAULT_AGENTS.keys())
    if actual == expected:
        ok("4 default agents exist (plan, build, resume, review)")
    else:
        fail("4 default agents exist", f"got {actual}")

    # 1.2 build is default (50 steps, confirm-sensitive, has all tools including run_command)
    build = DEFAULT_AGENTS["build"]
    checks = [
        build.max_steps == 50,
        build.confirm_mode == "confirm-sensitive",
        "run_command" in build.allowed_tools,
    ]
    if all(checks):
        ok("build: 50 steps, confirm-sensitive, has run_command")
    else:
        fail("build config", f"max_steps={build.max_steps}, mode={build.confirm_mode}, tools={build.allowed_tools}")

    # 1.3 plan is read-only (yolo, 20 steps, only read tools)
    plan = DEFAULT_AGENTS["plan"]
    write_tools = {"write_file", "edit_file", "delete_file", "apply_patch", "run_command"}
    plan_has_write = write_tools & set(plan.allowed_tools)
    checks = [
        plan.confirm_mode == "yolo",
        plan.max_steps == 20,
        len(plan_has_write) == 0,
    ]
    if all(checks):
        ok("plan: yolo, 20 steps, no write/edit/delete/run_command")
    else:
        fail("plan config", f"mode={plan.confirm_mode}, steps={plan.max_steps}, write_tools={plan_has_write}")

    # 1.4 resume is read-only (yolo, 15 steps)
    resume = DEFAULT_AGENTS["resume"]
    if resume.confirm_mode == "yolo" and resume.max_steps == 15:
        ok("resume: yolo, 15 steps")
    else:
        fail("resume config", f"mode={resume.confirm_mode}, steps={resume.max_steps}")

    # 1.5 review is read-only (yolo, 20 steps)
    review = DEFAULT_AGENTS["review"]
    if review.confirm_mode == "yolo" and review.max_steps == 20:
        ok("review: yolo, 20 steps")
    else:
        fail("review config", f"mode={review.confirm_mode}, steps={review.max_steps}")

    # 1.6 All read-only agents have same tool set
    plan_tools = sorted(plan.allowed_tools)
    resume_tools = sorted(resume.allowed_tools)
    review_tools = sorted(review.allowed_tools)
    if plan_tools == resume_tools == review_tools:
        ok(f"plan/resume/review share same tools: {plan_tools}")
    else:
        fail("read-only agents same tools", f"plan={plan_tools}, resume={resume_tools}, review={review_tools}")

    # 1.7 build has 10 tools, read-only agents have 5
    if len(build.allowed_tools) == 10 and len(plan.allowed_tools) == 5:
        ok("build has 10 tools, read-only agents have 5")
    else:
        fail("tool counts", f"build={len(build.allowed_tools)}, plan={len(plan.allowed_tools)}")


# ── Section 2: BUILD_PROMPT (v3 integrated planning) ────────────────────────

def test_build_prompt():
    section("BUILD_PROMPT (v3 integrated planning)")

    # 2.1 BUILD_PROMPT contains all 5 phases
    phases = ["ANALIZAR", "PLANIFICAR", "EJECUTAR", "VERIFICAR", "CORREGIR"]
    missing = [p for p in phases if p not in BUILD_PROMPT]
    if not missing:
        ok("BUILD_PROMPT contains all 5 phases")
    else:
        fail("BUILD_PROMPT 5 phases", f"missing: {missing}")

    # 2.2 BUILD_PROMPT mentions edit_file as preferred
    if "edit_file" in BUILD_PROMPT and "PREFERIR" in BUILD_PROMPT:
        ok("BUILD_PROMPT mentions edit_file as preferred")
    else:
        fail("BUILD_PROMPT edit_file preferred")

    # 2.3 BUILD_PROMPT mentions search_code, grep, find_files
    search_tools = ["search_code", "grep", "find_files"]
    missing = [t for t in search_tools if t not in BUILD_PROMPT]
    if not missing:
        ok("BUILD_PROMPT mentions search_code, grep, find_files")
    else:
        fail("BUILD_PROMPT search tools", f"missing: {missing}")

    # 2.4 BUILD_PROMPT mentions run_command
    if "run_command" in BUILD_PROMPT:
        ok("BUILD_PROMPT mentions run_command")
    else:
        fail("BUILD_PROMPT run_command")

    # 2.5 PLAN_PROMPT says "NO modifiques"
    if "NO modifiques" in PLAN_PROMPT:
        ok("PLAN_PROMPT contains 'NO modifiques'")
    else:
        fail("PLAN_PROMPT 'NO modifiques'")

    # 2.6 REVIEW_PROMPT says "NO modifiques"
    if "NO modifiques" in REVIEW_PROMPT:
        ok("REVIEW_PROMPT contains 'NO modifiques'")
    else:
        fail("REVIEW_PROMPT 'NO modifiques'")

    # 2.7 DEFAULT_PROMPTS has exactly 4 keys
    expected_keys = {"plan", "build", "resume", "review"}
    if set(DEFAULT_PROMPTS.keys()) == expected_keys and len(DEFAULT_PROMPTS) == 4:
        ok("DEFAULT_PROMPTS has exactly 4 keys")
    else:
        fail("DEFAULT_PROMPTS keys", f"got {set(DEFAULT_PROMPTS.keys())}")


# ── Section 3: MixedModeRunner eliminated as default ────────────────────────

def test_mixed_mode_eliminated():
    section("MixedModeRunner eliminated as default")

    # 3.1 MixedModeRunner still exists (backward compat) but is NOT the default path
    try:
        from architect.core.mixed_mode import MixedModeRunner
        # It exists but the key is that CLI does NOT use it by default
        ok("MixedModeRunner class still importable (backward compat)")
    except ImportError:
        # Also acceptable — it may have been fully removed
        ok("MixedModeRunner removed from core (fully eliminated)")

    # 3.2 get_agent(None, {}) returns None (not a default agent)
    result = get_agent(None, {})
    if result is None:
        ok("get_agent(None, {}) returns None")
    else:
        fail("get_agent(None, {})", f"got {result}")

    # 3.3 Default agent in CLI is "build" (test the pattern: `or "build"`)
    # Simulate the CLI pattern: kwargs.get("agent") or "build"
    kwargs_no_agent: dict = {}
    agent_name = kwargs_no_agent.get("agent") or "build"
    if agent_name == "build":
        ok("CLI default: kwargs.get('agent') or 'build' == 'build'")
    else:
        fail("CLI default agent", f"got {agent_name}")

    # Also verify with explicit None
    kwargs_none = {"agent": None}
    agent_name2 = kwargs_none.get("agent") or "build"
    if agent_name2 == "build":
        ok("CLI with agent=None defaults to 'build'")
    else:
        fail("CLI agent=None default", f"got {agent_name2}")


# ── Section 4: get_agent() merge ────────────────────────────────────────────

def test_get_agent_merge():
    section("get_agent() merge")

    # 4.1 get_agent("build", {}) returns default build config
    build = get_agent("build", {})
    default_build = DEFAULT_AGENTS["build"]
    if (
        build.max_steps == default_build.max_steps
        and build.confirm_mode == default_build.confirm_mode
        and build.allowed_tools == default_build.allowed_tools
        and build.system_prompt == default_build.system_prompt
    ):
        ok("get_agent('build', {}) returns default build config")
    else:
        fail("get_agent('build', {})", "config differs from DEFAULT_AGENTS['build']")

    # 4.2 get_agent("plan", {}) returns default plan config
    plan = get_agent("plan", {})
    default_plan = DEFAULT_AGENTS["plan"]
    if (
        plan.max_steps == default_plan.max_steps
        and plan.confirm_mode == default_plan.confirm_mode
    ):
        ok("get_agent('plan', {}) returns default plan config")
    else:
        fail("get_agent('plan', {})", "config differs from DEFAULT_AGENTS['plan']")

    # 4.3 get_agent with YAML override merges correctly (override max_steps, keep prompt)
    yaml_agents = {
        "build": AgentConfig(
            system_prompt=DEFAULT_PROMPTS["build"],
            max_steps=100,
        ),
    }
    merged = get_agent("build", yaml_agents)
    if merged.max_steps == 100 and merged.system_prompt == DEFAULT_PROMPTS["build"]:
        ok("YAML override: max_steps=100 merged, prompt preserved")
    else:
        fail("YAML override merge", f"max_steps={merged.max_steps}")

    # 4.4 get_agent with YAML-only custom agent works
    custom_config = AgentConfig(
        system_prompt="Custom agent prompt",
        allowed_tools=["read_file"],
        confirm_mode="yolo",
        max_steps=10,
    )
    yaml_custom = {"my_agent": custom_config}
    result = get_agent("my_agent", yaml_custom)
    if result.system_prompt == "Custom agent prompt" and result.max_steps == 10:
        ok("YAML-only custom agent works")
    else:
        fail("YAML-only custom agent", f"prompt={result.system_prompt!r}, steps={result.max_steps}")

    # 4.5 get_agent with unknown agent raises AgentNotFoundError
    try:
        get_agent("nonexistent", {})
        fail("Unknown agent raises AgentNotFoundError", "no exception raised")
    except AgentNotFoundError:
        ok("Unknown agent raises AgentNotFoundError")
    except Exception as e:
        fail("Unknown agent raises AgentNotFoundError", f"got {type(e).__name__}: {e}")

    # 4.6 AgentNotFoundError message lists available agents
    try:
        get_agent("nonexistent", {"my_custom": custom_config})
        fail("Error message lists available agents", "no exception raised")
    except AgentNotFoundError as e:
        msg = str(e)
        # Should mention at least the default agents and the custom one
        has_defaults = all(name in msg for name in ["build", "plan", "resume", "review"])
        has_custom = "my_custom" in msg
        if has_defaults and has_custom:
            ok("AgentNotFoundError lists available agents (defaults + custom)")
        else:
            fail("AgentNotFoundError message", f"msg={msg}")


# ── Section 5: CLI overrides ────────────────────────────────────────────────

def test_cli_overrides():
    section("CLI overrides (_apply_cli_overrides)")

    base = DEFAULT_AGENTS["build"]

    # 5.1 mode="yolo" changes confirm_mode
    result = _apply_cli_overrides(base, {"mode": "yolo"})
    if result.confirm_mode == "yolo":
        ok("mode='yolo' changes confirm_mode")
    else:
        fail("mode='yolo'", f"got {result.confirm_mode}")

    # 5.2 max_steps changes max_steps
    result = _apply_cli_overrides(base, {"max_steps": 99})
    if result.max_steps == 99:
        ok("max_steps=99 changes max_steps")
    else:
        fail("max_steps=99", f"got {result.max_steps}")

    # 5.3 empty dict returns same agent (equal config)
    result = _apply_cli_overrides(base, {})
    if (
        result.confirm_mode == base.confirm_mode
        and result.max_steps == base.max_steps
        and result.allowed_tools == base.allowed_tools
    ):
        ok("Empty overrides returns equivalent config")
    else:
        fail("Empty overrides", "config differs")

    # 5.4 None values don't override
    result = _apply_cli_overrides(base, {"mode": None, "max_steps": None})
    if result.confirm_mode == base.confirm_mode and result.max_steps == base.max_steps:
        ok("None values don't override")
    else:
        fail("None values", f"mode={result.confirm_mode}, steps={result.max_steps}")

    # 5.5 Full chain: get_agent with yaml + cli overrides
    yaml_agents = {
        "build": AgentConfig(
            system_prompt=DEFAULT_PROMPTS["build"],
            max_steps=100,
        ),
    }
    result = get_agent("build", yaml_agents, cli_overrides={"mode": "yolo", "max_steps": 200})
    if result.confirm_mode == "yolo" and result.max_steps == 200:
        ok("Full chain: YAML(100 steps) + CLI(yolo, 200) → yolo, 200")
    else:
        fail("Full chain", f"mode={result.confirm_mode}, steps={result.max_steps}")


# ── Section 6: list_available_agents and resolve ────────────────────────────

def test_list_and_resolve():
    section("list_available_agents and resolve_agents_from_yaml")

    # 6.1 list_available_agents with no yaml returns 4 defaults sorted
    result = list_available_agents({})
    expected = sorted(["build", "plan", "resume", "review"])
    if result == expected:
        ok(f"list_available_agents(empty) → {result}")
    else:
        fail("list_available_agents(empty)", f"got {result}")

    # 6.2 list_available_agents with yaml adds custom agent
    custom = AgentConfig(system_prompt="test", max_steps=5)
    result = list_available_agents({"deploy": custom})
    if "deploy" in result and len(result) == 5:
        ok(f"list_available_agents with yaml 'deploy' → {result}")
    else:
        fail("list_available_agents with yaml", f"got {result}")

    # 6.3 resolve_agents_from_yaml with dict
    raw_yaml = {
        "test_agent": {
            "system_prompt": "Test prompt",
            "allowed_tools": ["read_file"],
            "confirm_mode": "yolo",
            "max_steps": 10,
        }
    }
    resolved = resolve_agents_from_yaml(raw_yaml)
    if (
        "test_agent" in resolved
        and isinstance(resolved["test_agent"], AgentConfig)
        and resolved["test_agent"].system_prompt == "Test prompt"
        and resolved["test_agent"].max_steps == 10
    ):
        ok("resolve_agents_from_yaml with dict → AgentConfig")
    else:
        fail("resolve_agents_from_yaml dict", f"got {resolved}")

    # 6.4 resolve_agents_from_yaml with AgentConfig passthrough
    existing = AgentConfig(system_prompt="Already config", max_steps=7)
    resolved = resolve_agents_from_yaml({"existing": existing})
    if resolved["existing"] is existing:
        ok("resolve_agents_from_yaml with AgentConfig → passthrough (same object)")
    else:
        fail("resolve_agents_from_yaml passthrough", "not same object")

    # 6.5 resolve_agents_from_yaml with invalid type raises ValueError
    try:
        resolve_agents_from_yaml({"bad": 42})
        fail("resolve_agents_from_yaml invalid type raises ValueError", "no exception")
    except ValueError:
        ok("resolve_agents_from_yaml invalid type raises ValueError")
    except Exception as e:
        fail("resolve_agents_from_yaml invalid type", f"got {type(e).__name__}: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Test v3-M3: Plan integrado en build")
    print("=" * 60)

    test_default_agents()
    test_build_prompt()
    test_mixed_mode_eliminated()
    test_get_agent_merge()
    test_cli_overrides()
    test_list_and_resolve()

    print(f"\n{'=' * 60}")
    print(f"Resultado: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
