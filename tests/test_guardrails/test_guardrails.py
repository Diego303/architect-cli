"""
Tests para el sistema de guardrails v4-A2.

Cubre:
- check_file_access: archivos protegidos
- check_command: comandos bloqueados y límite de comandos
- check_edit_limits: límite de archivos y líneas
- check_code_rules: regex en contenido escrito
- run_quality_gates: ejecución de gates con timeout
- Config schema: GuardrailsConfig, QualityGateConfig, CodeRuleConfig
"""

import stat
import textwrap
from pathlib import Path

import pytest

from architect.config.schema import (
    CodeRuleConfig,
    GuardrailsConfig,
    QualityGateConfig,
)
from architect.core.guardrails import GuardrailsEngine


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def make_script(workspace: Path):
    def _make(name: str, content: str) -> Path:
        script = workspace / name
        script.write_text(content)
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script
    return _make


@pytest.fixture
def basic_config() -> GuardrailsConfig:
    return GuardrailsConfig(
        enabled=True,
        protected_files=[".env", ".env.*", "*.pem", "*.key"],
        blocked_commands=[
            r'rm\s+-[rf]+\s+/',
            r'git\s+push.*--force.*(main|master)',
            r'DROP\s+TABLE',
        ],
        max_files_modified=5,
        max_lines_changed=100,
        max_commands_executed=10,
    )


@pytest.fixture
def engine(basic_config: GuardrailsConfig, workspace: Path) -> GuardrailsEngine:
    return GuardrailsEngine(basic_config, str(workspace))


# ── Tests: check_file_access ──────────────────────────────────────────


class TestCheckFileAccess:
    def test_env_file_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_file_access(".env", "write_file")
        assert not allowed
        assert ".env" in reason

    def test_env_variant_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_file_access(".env.production", "write_file")
        assert not allowed

    def test_pem_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_file_access("server.pem", "edit_file")
        assert not allowed

    def test_key_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_file_access("private.key", "delete_file")
        assert not allowed

    def test_normal_file_allowed(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_file_access("src/main.py", "write_file")
        assert allowed
        assert reason == ""

    def test_path_with_directory(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_file_access("config/.env", "write_file")
        assert not allowed  # Matches on basename


# ── Tests: check_command ─────────────────────────────────────────────


class TestCheckCommand:
    def test_rm_rf_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_command("rm -rf /")
        assert not allowed
        assert "rm" in reason.lower() or "bloqueado" in reason.lower()

    def test_force_push_main_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_command("git push --force origin main")
        assert not allowed

    def test_drop_table_blocked(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_command("DROP TABLE users;")
        assert not allowed

    def test_safe_command_allowed(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_command("pytest tests/ -v")
        assert allowed

    def test_ls_allowed(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_command("ls -la")
        assert allowed

    def test_command_limit(self, workspace: Path):
        config = GuardrailsConfig(enabled=True, max_commands_executed=2)
        eng = GuardrailsEngine(config, str(workspace))

        eng.record_command()
        eng.record_command()
        allowed, reason = eng.check_command("echo ok")
        assert not allowed
        assert "Límite" in reason

    def test_redirect_to_env_blocked(self, engine: GuardrailsEngine):
        """Redirección shell a .env debe ser bloqueada."""
        allowed, reason = engine.check_command("echo 'SECRET=123' > .env")
        assert not allowed
        assert ".env" in reason

    def test_append_redirect_to_env_blocked(self, engine: GuardrailsEngine):
        """Redirección append (>>) a .env debe ser bloqueada."""
        allowed, reason = engine.check_command("echo 'MORE=456' >> .env")
        assert not allowed
        assert ".env" in reason

    def test_tee_to_env_blocked(self, engine: GuardrailsEngine):
        """Pipe a tee hacia .env debe ser bloqueado."""
        allowed, reason = engine.check_command("echo 'data' | tee .env")
        assert not allowed
        assert ".env" in reason

    def test_tee_append_to_pem_blocked(self, engine: GuardrailsEngine):
        """Pipe a tee -a hacia archivo .pem debe ser bloqueado."""
        allowed, reason = engine.check_command("cat data | tee -a server.pem")
        assert not allowed
        assert "server.pem" in reason

    def test_redirect_to_safe_file_allowed(self, engine: GuardrailsEngine):
        """Redirección a archivo no protegido debe permitirse."""
        allowed, reason = engine.check_command("echo 'hello' > output.txt")
        assert allowed

    def test_redirect_to_env_with_path_blocked(self, engine: GuardrailsEngine):
        """Redirección a config/.env (basename .env) debe ser bloqueada."""
        allowed, reason = engine.check_command("echo 'x' > config/.env")
        assert not allowed


# ── Tests: _extract_redirect_targets ─────────────────────────────────


class TestExtractRedirectTargets:
    """Tests para la función _extract_redirect_targets."""

    def test_simple_redirect(self):
        from architect.core.guardrails import _extract_redirect_targets
        targets = _extract_redirect_targets("echo hello > file.txt")
        assert "file.txt" in targets

    def test_append_redirect(self):
        from architect.core.guardrails import _extract_redirect_targets
        targets = _extract_redirect_targets("echo hello >> file.txt")
        assert "file.txt" in targets

    def test_tee_redirect(self):
        from architect.core.guardrails import _extract_redirect_targets
        targets = _extract_redirect_targets("echo hello | tee file.txt")
        assert "file.txt" in targets

    def test_tee_append(self):
        from architect.core.guardrails import _extract_redirect_targets
        targets = _extract_redirect_targets("echo hello | tee -a file.txt")
        assert "file.txt" in targets

    def test_no_redirect(self):
        from architect.core.guardrails import _extract_redirect_targets
        targets = _extract_redirect_targets("echo hello")
        assert targets == []

    def test_quoted_target(self):
        from architect.core.guardrails import _extract_redirect_targets
        targets = _extract_redirect_targets("echo hello > '.env'")
        assert ".env" in targets


# ── Tests: check_edit_limits ─────────────────────────────────────────


class TestCheckEditLimits:
    def test_within_limits(self, engine: GuardrailsEngine):
        allowed, reason = engine.check_edit_limits("src/a.py", 10, 5)
        assert allowed

    def test_files_limit_exceeded(self, workspace: Path):
        config = GuardrailsConfig(enabled=True, max_files_modified=2)
        eng = GuardrailsEngine(config, str(workspace))

        eng.check_edit_limits("a.py", 1, 0)
        eng.check_edit_limits("b.py", 1, 0)
        allowed, reason = eng.check_edit_limits("c.py", 1, 0)
        assert not allowed
        assert "archivos" in reason.lower()

    def test_lines_limit_exceeded(self, workspace: Path):
        config = GuardrailsConfig(enabled=True, max_lines_changed=10)
        eng = GuardrailsEngine(config, str(workspace))

        eng.check_edit_limits("a.py", 5, 0)
        allowed, reason = eng.check_edit_limits("a.py", 6, 0)
        assert not allowed
        assert "líneas" in reason.lower()

    def test_same_file_counted_once(self, engine: GuardrailsEngine):
        engine.check_edit_limits("src/main.py", 5, 0)
        engine.check_edit_limits("src/main.py", 5, 0)
        # Should count as 1 file modified
        assert len(engine._files_modified) == 1


# ── Tests: check_code_rules ─────────────────────────────────────────


class TestCheckCodeRules:
    def test_eval_blocked(self, workspace: Path):
        config = GuardrailsConfig(
            enabled=True,
            code_rules=[
                CodeRuleConfig(
                    pattern=r'eval\(',
                    message="Prohibido usar eval().",
                    severity="block",
                ),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        violations = eng.check_code_rules("result = eval(user_input)", "main.py")
        assert len(violations) == 1
        assert violations[0][0] == "block"
        assert "eval" in violations[0][1]

    def test_print_warned(self, workspace: Path):
        config = GuardrailsConfig(
            enabled=True,
            code_rules=[
                CodeRuleConfig(
                    pattern=r'\bprint\s*\(',
                    message="Usa logging en vez de print().",
                    severity="warn",
                ),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        violations = eng.check_code_rules('print("hello")', "test.py")
        assert len(violations) == 1
        assert violations[0][0] == "warn"

    def test_clean_code_no_violations(self, workspace: Path):
        config = GuardrailsConfig(
            enabled=True,
            code_rules=[
                CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        violations = eng.check_code_rules("x = 1 + 2", "clean.py")
        assert len(violations) == 0


# ── Tests: run_quality_gates ─────────────────────────────────────────


class TestRunQualityGates:
    def test_passing_gate(self, workspace: Path, make_script):
        make_script("pass.sh", "#!/bin/bash\nexit 0\n")
        config = GuardrailsConfig(
            enabled=True,
            quality_gates=[
                QualityGateConfig(
                    name="lint",
                    command=str(workspace / "pass.sh"),
                    required=True,
                ),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        results = eng.run_quality_gates()
        assert len(results) == 1
        assert results[0]["passed"] is True
        assert results[0]["name"] == "lint"

    def test_failing_required_gate(self, workspace: Path, make_script):
        make_script("fail.sh", '#!/bin/bash\necho "ERROR: missing types" && exit 1\n')
        config = GuardrailsConfig(
            enabled=True,
            quality_gates=[
                QualityGateConfig(
                    name="typecheck",
                    command=str(workspace / "fail.sh"),
                    required=True,
                ),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        results = eng.run_quality_gates()
        assert len(results) == 1
        assert results[0]["passed"] is False
        assert results[0]["required"] is True

    def test_failing_optional_gate(self, workspace: Path, make_script):
        make_script("fail.sh", "#!/bin/bash\nexit 1\n")
        config = GuardrailsConfig(
            enabled=True,
            quality_gates=[
                QualityGateConfig(
                    name="optional-check",
                    command=str(workspace / "fail.sh"),
                    required=False,
                ),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        results = eng.run_quality_gates()
        assert results[0]["passed"] is False
        assert results[0]["required"] is False

    def test_timeout_gate(self, workspace: Path, make_script):
        make_script("slow.sh", "#!/bin/bash\nsleep 10\nexit 0\n")
        config = GuardrailsConfig(
            enabled=True,
            quality_gates=[
                QualityGateConfig(
                    name="slow-test",
                    command=str(workspace / "slow.sh"),
                    timeout=1,
                ),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        results = eng.run_quality_gates()
        assert results[0]["passed"] is False
        assert "Timeout" in results[0]["output"]

    def test_multiple_gates(self, workspace: Path, make_script):
        make_script("pass.sh", "#!/bin/bash\nexit 0\n")
        make_script("fail.sh", "#!/bin/bash\nexit 1\n")
        config = GuardrailsConfig(
            enabled=True,
            quality_gates=[
                QualityGateConfig(name="lint", command=str(workspace / "pass.sh")),
                QualityGateConfig(name="tests", command=str(workspace / "fail.sh")),
            ],
        )
        eng = GuardrailsEngine(config, str(workspace))

        results = eng.run_quality_gates()
        assert len(results) == 2
        assert results[0]["passed"] is True
        assert results[1]["passed"] is False


# ── Tests: State tracking ────────────────────────────────────────────


class TestStateTracking:
    def test_record_command(self, engine: GuardrailsEngine):
        assert engine._commands_executed == 0
        engine.record_command()
        assert engine._commands_executed == 1

    def test_record_edit_and_force_test(self, workspace: Path):
        config = GuardrailsConfig(enabled=True, require_test_after_edit=True)
        eng = GuardrailsEngine(config, str(workspace))

        assert not eng.should_force_test()
        eng.record_edit()
        assert eng.should_force_test()
        eng.reset_test_counter()
        assert not eng.should_force_test()


# ── Tests: Config schema ────────────────────────────────────────────


class TestGuardrailsConfigSchema:
    def test_defaults(self):
        config = GuardrailsConfig()
        assert config.enabled is False
        assert config.protected_files == []
        assert config.blocked_commands == []
        assert config.max_files_modified is None
        assert config.quality_gates == []
        assert config.code_rules == []

    def test_from_dict(self):
        data = {
            "enabled": True,
            "protected_files": [".env", "*.key"],
            "blocked_commands": [r"rm\s+-rf"],
            "max_files_modified": 20,
            "quality_gates": [
                {"name": "lint", "command": "ruff check", "required": True},
            ],
            "code_rules": [
                {"pattern": r"eval\(", "message": "No eval", "severity": "block"},
            ],
        }
        config = GuardrailsConfig(**data)
        assert config.enabled is True
        assert len(config.protected_files) == 2
        assert len(config.quality_gates) == 1
        assert config.quality_gates[0].name == "lint"
        assert len(config.code_rules) == 1
        assert config.code_rules[0].severity == "block"

    def test_app_config_includes_guardrails(self):
        from architect.config.schema import AppConfig
        config = AppConfig()
        assert hasattr(config, "guardrails")
        assert config.guardrails.enabled is False
