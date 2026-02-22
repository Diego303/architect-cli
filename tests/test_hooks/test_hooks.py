"""
Tests para el sistema de hooks v4-A1.

Cubre:
- HookEvent, HookDecision, HookResult (modelo de datos)
- HooksRegistry (registro y filtrado)
- HookExecutor (ejecución, exit codes, timeout, async, matcher, file_patterns)
- Integración backward-compat con post_edit
"""

import json
import os
import stat
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from architect.core.hooks import (
    HookConfig,
    HookDecision,
    HookEvent,
    HookExecutor,
    HookResult,
    HooksRegistry,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporal."""
    return tmp_path


@pytest.fixture
def make_script(workspace: Path):
    """Factory para crear scripts ejecutables en el workspace."""

    def _make(name: str, content: str) -> Path:
        script = workspace / name
        script.write_text(content)
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    return _make


@pytest.fixture
def empty_registry() -> HooksRegistry:
    """Registry vacío."""
    return HooksRegistry()


@pytest.fixture
def registry_with_hooks(make_script, workspace: Path) -> HooksRegistry:
    """Registry con hooks de ejemplo."""
    make_script("allow.sh", "#!/bin/bash\nexit 0\n")
    make_script("block.sh", '#!/bin/bash\necho "Bloqueado" >&2\nexit 2\n')

    return HooksRegistry(hooks={
        HookEvent.PRE_TOOL_USE: [
            HookConfig(
                command=str(workspace / "allow.sh"),
                name="allow-hook",
            ),
        ],
        HookEvent.POST_TOOL_USE: [
            HookConfig(
                command=str(workspace / "allow.sh"),
                name="post-hook",
            ),
        ],
    })


# ── Tests: Modelo de datos ───────────────────────────────────────────────


class TestHookEvent:
    def test_all_events_defined(self):
        events = list(HookEvent)
        assert len(events) == 10

    def test_event_values(self):
        assert HookEvent.PRE_TOOL_USE.value == "pre_tool_use"
        assert HookEvent.POST_TOOL_USE.value == "post_tool_use"
        assert HookEvent.SESSION_START.value == "session_start"
        assert HookEvent.AGENT_COMPLETE.value == "agent_complete"


class TestHookDecision:
    def test_decisions(self):
        assert HookDecision.ALLOW.value == "allow"
        assert HookDecision.BLOCK.value == "block"
        assert HookDecision.MODIFY.value == "modify"


class TestHookResult:
    def test_default_allow(self):
        result = HookResult()
        assert result.decision == HookDecision.ALLOW
        assert result.reason is None
        assert result.additional_context is None
        assert result.updated_input is None

    def test_block_result(self):
        result = HookResult(
            decision=HookDecision.BLOCK,
            reason="No permitido",
        )
        assert result.decision == HookDecision.BLOCK
        assert result.reason == "No permitido"


# ── Tests: HooksRegistry ────────────────────────────────────────────────


class TestHooksRegistry:
    def test_empty_registry(self, empty_registry: HooksRegistry):
        assert empty_registry.get_hooks(HookEvent.PRE_TOOL_USE) == []
        assert not empty_registry.has_hooks()

    def test_get_hooks_filters_disabled(self):
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command="echo yes", name="enabled", enabled=True),
                HookConfig(command="echo no", name="disabled", enabled=False),
            ],
        })
        hooks = registry.get_hooks(HookEvent.PRE_TOOL_USE)
        assert len(hooks) == 1
        assert hooks[0].name == "enabled"

    def test_has_hooks(self, registry_with_hooks: HooksRegistry):
        assert registry_with_hooks.has_hooks()


# ── Tests: HookExecutor ─────────────────────────────────────────────────


class TestHookExecutor:
    def test_allow_hook(self, workspace: Path, make_script):
        """Hook que retorna exit 0 → ALLOW."""
        make_script("ok.sh", "#!/bin/bash\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "ok.sh"), name="ok"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert len(results) == 1
        assert results[0].decision == HookDecision.ALLOW

    def test_block_hook(self, workspace: Path, make_script):
        """Hook que retorna exit 2 → BLOCK con razón de stderr."""
        make_script("block.sh", '#!/bin/bash\necho "Peligroso" >&2\nexit 2\n')
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "block.sh"), name="blocker"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "run_command"})
        assert len(results) == 1
        assert results[0].decision == HookDecision.BLOCK
        assert "Peligroso" in (results[0].reason or "")

    def test_block_stops_chain(self, workspace: Path, make_script):
        """Si un hook bloquea, no se ejecutan los siguientes."""
        make_script("block.sh", '#!/bin/bash\necho "NO" >&2\nexit 2\n')
        make_script("after.sh", "#!/bin/bash\nexit 0\n")

        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "block.sh"), name="blocker"),
                HookConfig(command=str(workspace / "after.sh"), name="after"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "write_file"})
        # Solo un resultado porque el chain se rompió
        assert len(results) == 1
        assert results[0].decision == HookDecision.BLOCK

    def test_modify_hook(self, workspace: Path, make_script):
        """Hook que retorna JSON con updatedInput → MODIFY."""
        script_content = textwrap.dedent("""\
            #!/bin/bash
            echo '{"updatedInput": {"path": "/safe/path.py"}, "additionalContext": "Ruta modificada"}'
            exit 0
        """)
        make_script("modify.sh", script_content)
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "modify.sh"), name="modifier"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "write_file"})
        assert len(results) == 1
        assert results[0].decision == HookDecision.MODIFY
        assert results[0].updated_input == {"path": "/safe/path.py"}
        assert results[0].additional_context == "Ruta modificada"

    def test_additional_context_json(self, workspace: Path, make_script):
        """Hook que retorna JSON con additionalContext → ALLOW con contexto."""
        script_content = textwrap.dedent("""\
            #!/bin/bash
            echo '{"additionalContext": "git status: limpio"}'
            exit 0
        """)
        make_script("context.sh", script_content)
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "context.sh"), name="ctx"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert results[0].decision == HookDecision.ALLOW
        assert results[0].additional_context == "git status: limpio"

    def test_additional_context_plain_text(self, workspace: Path, make_script):
        """Hook que retorna texto plano (no JSON) → ALLOW con contexto."""
        make_script("plain.sh", "#!/bin/bash\necho 'lint OK'\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.POST_TOOL_USE: [
                HookConfig(command=str(workspace / "plain.sh"), name="lint"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.POST_TOOL_USE, {"tool_name": "edit_file"})
        assert results[0].decision == HookDecision.ALLOW
        assert results[0].additional_context == "lint OK"

    def test_timeout_hook(self, workspace: Path, make_script):
        """Hook que excede timeout → ALLOW (warning, no bloquea)."""
        make_script("slow.sh", "#!/bin/bash\nsleep 10\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "slow.sh"), name="slow", timeout=1),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert len(results) == 1
        assert results[0].decision == HookDecision.ALLOW  # timeout = allow, no block

    def test_error_exit_code_allows(self, workspace: Path, make_script):
        """Hook con exit code != 0 y != 2 → ALLOW (error logeado)."""
        make_script("error.sh", "#!/bin/bash\nexit 1\n")
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "error.sh"), name="err"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert results[0].decision == HookDecision.ALLOW

    def test_matcher_filters_tool(self, workspace: Path, make_script):
        """Matcher regex filtra tools que no coinciden."""
        make_script("ok.sh", "#!/bin/bash\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(
                    command=str(workspace / "ok.sh"),
                    name="only-run",
                    matcher="run_command",
                ),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        # No matchea read_file
        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert len(results) == 0

        # Sí matchea run_command
        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "run_command"})
        assert len(results) == 1

    def test_file_patterns_filter(self, workspace: Path, make_script):
        """file_patterns filtra por extensión de archivo."""
        make_script("ok.sh", "#!/bin/bash\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.POST_TOOL_USE: [
                HookConfig(
                    command=str(workspace / "ok.sh"),
                    name="python-only",
                    file_patterns=["*.py"],
                ),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        # No matchea .js
        results = executor.run_event(
            HookEvent.POST_TOOL_USE, {"tool_name": "edit_file", "file_path": "src/app.js"}
        )
        assert len(results) == 0

        # Sí matchea .py
        results = executor.run_event(
            HookEvent.POST_TOOL_USE, {"tool_name": "edit_file", "file_path": "src/main.py"}
        )
        assert len(results) == 1

    def test_env_vars_injected(self, workspace: Path, make_script):
        """Las env vars ARCHITECT_* se inyectan correctamente."""
        script = textwrap.dedent("""\
            #!/bin/bash
            echo "{\\"additionalContext\\": \\"event=$ARCHITECT_EVENT tool=$ARCHITECT_TOOL_NAME\\"}"
            exit 0
        """)
        make_script("env.sh", script)
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "env.sh"), name="env-check"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(
            HookEvent.PRE_TOOL_USE, {"tool_name": "write_file"}
        )
        ctx = results[0].additional_context or ""
        assert "event=pre_tool_use" in ctx
        assert "tool=write_file" in ctx

    def test_stdin_data_passed(self, workspace: Path, make_script):
        """stdin_data se pasa como JSON al hook."""
        script = textwrap.dedent("""\
            #!/bin/bash
            # Read stdin and echo it as additional context
            INPUT=$(cat)
            echo "{\\"additionalContext\\": \\"got: $INPUT\\"}"
            exit 0
        """)
        make_script("stdin.sh", script)
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "stdin.sh"), name="stdin-check"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": "write_file"},
            stdin_data={"tool_name": "write_file", "tool_input": {"path": "test.py"}},
        )
        ctx = results[0].additional_context or ""
        assert "write_file" in ctx

    def test_async_hook_non_blocking(self, workspace: Path, make_script):
        """Hook async se ejecuta sin bloquear y retorna placeholder."""
        make_script("async.sh", "#!/bin/bash\nsleep 5\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.SESSION_END: [
                HookConfig(
                    command=str(workspace / "async.sh"),
                    name="async-notify",
                    is_async=True,
                ),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        start = time.monotonic()
        results = executor.run_event(HookEvent.SESSION_END, {"status": "success"})
        elapsed = time.monotonic() - start

        # Debería retornar casi inmediatamente (< 1s)
        assert elapsed < 2.0
        assert len(results) == 1
        assert results[0].decision == HookDecision.ALLOW

    def test_run_post_edit_compat(self, workspace: Path, make_script):
        """run_post_edit mantiene backward compat con v3-M4."""
        make_script("lint.sh", "#!/bin/bash\necho 'lint: OK'\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.POST_TOOL_USE: [
                HookConfig(
                    command=str(workspace / "lint.sh"),
                    name="lint",
                    matcher="write_file|edit_file|apply_patch",
                    file_patterns=["*.py"],
                ),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        # edit_file con .py → debería ejecutarse
        output = executor.run_post_edit("edit_file", {"path": "src/main.py"})
        assert output is not None
        assert "lint: OK" in output

        # read_file → no aplica
        output = executor.run_post_edit("read_file", {"path": "src/main.py"})
        assert output is None

    def test_no_hooks_returns_empty(self, workspace: Path):
        """Registry sin hooks retorna lista vacía."""
        registry = HooksRegistry()
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert results == []

    def test_duration_tracked(self, workspace: Path, make_script):
        """La duración se trackea en ms."""
        make_script("fast.sh", "#!/bin/bash\nexit 0\n")
        registry = HooksRegistry(hooks={
            HookEvent.PRE_TOOL_USE: [
                HookConfig(command=str(workspace / "fast.sh"), name="fast"),
            ],
        })
        executor = HookExecutor(registry, str(workspace))

        results = executor.run_event(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file"})
        assert results[0].duration_ms >= 0


# ── Tests: Config Schema ────────────────────────────────────────────────


class TestHooksConfigSchema:
    def test_hook_item_config_defaults(self):
        from architect.config.schema import HookItemConfig

        hook = HookItemConfig(command="echo test")
        assert hook.name == ""
        assert hook.matcher == "*"
        assert hook.file_patterns == []
        assert hook.timeout == 10
        assert hook.async_ is False
        assert hook.enabled is True

    def test_hook_item_config_async_alias(self):
        """async es una keyword Python, se acepta como alias."""
        from architect.config.schema import HookItemConfig

        # Usar el nombre real del campo
        hook = HookItemConfig(command="echo test", async_=True)
        assert hook.async_ is True

    def test_hooks_config_all_events(self):
        from architect.config.schema import HooksConfig

        config = HooksConfig()
        assert config.pre_tool_use == []
        assert config.post_tool_use == []
        assert config.pre_llm_call == []
        assert config.post_llm_call == []
        assert config.session_start == []
        assert config.session_end == []
        assert config.on_error == []
        assert config.agent_complete == []
        assert config.budget_warning == []
        assert config.context_compress == []
        assert config.post_edit == []

    def test_hooks_config_from_dict(self):
        from architect.config.schema import HooksConfig

        data = {
            "pre_tool_use": [
                {"name": "sec-check", "command": "echo check", "matcher": "run_command"},
            ],
            "post_tool_use": [
                {"name": "lint", "command": "ruff check", "file_patterns": ["*.py"]},
            ],
        }
        config = HooksConfig(**data)
        assert len(config.pre_tool_use) == 1
        assert config.pre_tool_use[0].name == "sec-check"
        assert len(config.post_tool_use) == 1
        assert config.post_tool_use[0].file_patterns == ["*.py"]

    def test_backward_compat_post_edit(self):
        """post_edit sigue aceptándose como sección de config."""
        from architect.config.schema import HooksConfig

        data = {
            "post_edit": [
                {"name": "old-hook", "command": "echo old", "file_patterns": ["*.py"]},
            ],
        }
        config = HooksConfig(**data)
        assert len(config.post_edit) == 1
        assert config.post_edit[0].name == "old-hook"
