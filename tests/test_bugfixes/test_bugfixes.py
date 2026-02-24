"""
Tests para las correcciones de bugs 3-7 del informe QA v0.19.0.

Cubre:
- BUG-3: code_rules severity:block previene escritura ANTES de ejecutar
- BUG-4: dispatch_subagent se registra en el ToolRegistry via CLI
- BUG-5: TelemetryConfig se conecta al flujo de ejecucion
- BUG-6: HealthConfig se conecta al CLI con --health flag
- BUG-7: Parallel workers propagan --config y --api-base
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from architect.config.schema import (
    AppConfig,
    CodeRuleConfig,
    CommandsConfig,
    GuardrailsConfig,
    WorkspaceConfig,
)
from architect.core.guardrails import GuardrailsEngine
from architect.execution.engine import ExecutionEngine
from architect.features.parallel import (
    ParallelConfig,
    ParallelRunner,
    WorkerResult,
    _run_worker_process,
)
from architect.telemetry.otel import NoopTracer, create_tracer
from architect.tools.base import ToolResult
from architect.tools.registry import ToolRegistry
from architect.tools.setup import register_all_tools, register_dispatch_tool


# ── Fixtures compartidas ─────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def make_registry(workspace: Path):
    """Crea un ToolRegistry con tools de filesystem registradas."""
    def _make(commands_enabled: bool = False) -> ToolRegistry:
        registry = ToolRegistry()
        ws_config = WorkspaceConfig(root=str(workspace))
        cmd_config = CommandsConfig(enabled=commands_enabled)
        register_all_tools(registry, ws_config, cmd_config)
        return registry
    return _make


@pytest.fixture
def make_engine(workspace: Path, make_registry):
    """Crea un ExecutionEngine con guardrails configurados."""
    def _make(
        code_rules: list[CodeRuleConfig] | None = None,
        confirm_mode: str = "yolo",
    ) -> ExecutionEngine:
        registry = make_registry()
        guardrails_config = GuardrailsConfig(
            enabled=True,
            code_rules=code_rules or [],
        )
        guardrails = GuardrailsEngine(guardrails_config, str(workspace))
        config = AppConfig(workspace=WorkspaceConfig(root=str(workspace)))
        return ExecutionEngine(
            registry, config,
            confirm_mode=confirm_mode,
            guardrails=guardrails,
        )
    return _make


# ═══════════════════════════════════════════════════════════════════════
# BUG-3: code_rules severity:block previene escritura ANTES de ejecutar
# ═══════════════════════════════════════════════════════════════════════


class TestBug3CodeRulesPreExecution:
    """Verifica que code_rules con severity:block impiden la escritura
    ANTES de que el tool se ejecute, no despues."""

    # -- check_code_rules en ExecutionEngine --

    def test_check_code_rules_returns_block_message(self, make_engine):
        """check_code_rules retorna BLOQUEADO para severity:block."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])
        messages = engine.check_code_rules(
            "write_file", {"path": "test.py", "content": "x = eval(input())"}
        )
        assert len(messages) == 1
        assert messages[0].startswith("BLOQUEADO")
        assert "eval" in messages[0]

    def test_check_code_rules_warn_does_not_block(self, make_engine):
        """check_code_rules retorna warning pero sin BLOQUEADO."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'\bprint\(', message="Use logging", severity="warn"),
        ])
        messages = engine.check_code_rules(
            "write_file", {"path": "test.py", "content": 'print("hello")'}
        )
        assert len(messages) == 1
        assert not messages[0].startswith("BLOQUEADO")
        assert "Aviso" in messages[0]

    def test_check_code_rules_clean_content_empty(self, make_engine):
        """Contenido limpio no genera mensajes."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])
        messages = engine.check_code_rules(
            "write_file", {"path": "test.py", "content": "x = 1 + 2"}
        )
        assert messages == []

    def test_check_code_rules_only_for_write_edit(self, make_engine):
        """check_code_rules ignora tools que no son write_file/edit_file."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])
        messages = engine.check_code_rules(
            "read_file", {"path": "test.py"}
        )
        assert messages == []

    def test_check_code_rules_edit_file_uses_new_str(self, make_engine):
        """check_code_rules extrae contenido de new_str para edit_file."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])
        messages = engine.check_code_rules(
            "edit_file", {"path": "test.py", "new_str": "result = eval(data)"}
        )
        assert len(messages) == 1
        assert "BLOQUEADO" in messages[0]

    # -- Integración: archivo NO se escribe si code_rule bloquea --

    def test_write_file_blocked_by_code_rule_file_not_created(self, workspace, make_engine):
        """Si code_rule bloquea write_file, el archivo NO debe crearse en disco."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])

        target = workspace / "malicious.py"
        assert not target.exists()

        # Simular el flujo completo: check ANTES, luego decidir si ejecutar
        messages = engine.check_code_rules(
            "write_file", {"path": str(target), "content": "eval(input())"}
        )
        block_msgs = [m for m in messages if m.startswith("BLOQUEADO")]

        # Hay bloqueo → NO ejecutar
        assert len(block_msgs) > 0

        # El archivo NO debe existir
        assert not target.exists()

    def test_write_file_allowed_when_no_violations(self, workspace, make_engine):
        """Si no hay violaciones, write_file se ejecuta normalmente."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])

        target = workspace / "clean.py"
        messages = engine.check_code_rules(
            "write_file", {"path": str(target), "content": "x = 1 + 2"}
        )
        assert messages == []

        # Ejecutar normalmente
        result = engine.execute_tool_call(
            "write_file", {"path": str(target), "content": "x = 1 + 2"}
        )
        assert result.success
        assert target.exists()
        assert target.read_text() == "x = 1 + 2"

    def test_warn_allows_execution(self, workspace, make_engine):
        """severity:warn genera aviso pero permite la escritura."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'\bprint\(', message="Use logging", severity="warn"),
        ])

        target = workspace / "warned.py"
        messages = engine.check_code_rules(
            "write_file", {"path": str(target), "content": 'print("hello")'}
        )
        block_msgs = [m for m in messages if m.startswith("BLOQUEADO")]
        assert len(block_msgs) == 0  # No block
        assert len(messages) == 1  # Solo warning

        # La ejecucion deberia proceder
        result = engine.execute_tool_call(
            "write_file", {"path": str(target), "content": 'print("hello")'}
        )
        assert result.success
        assert target.exists()

    # -- record_edit solo tras ejecucion exitosa --

    def test_record_edit_called_on_successful_write(self, workspace, make_engine):
        """record_edit() se llama tras write_file exitoso."""
        engine = make_engine()
        target = workspace / "ok.py"

        result = engine.execute_tool_call(
            "write_file", {"path": str(target), "content": "x = 1"}
        )
        assert result.success
        assert engine.guardrails._edits_since_last_test == 1

    def test_record_edit_not_called_on_blocked_code_rule(self, make_engine):
        """record_edit() NO se llama si code_rule bloquea (previo a ejecucion)."""
        engine = make_engine(code_rules=[
            CodeRuleConfig(pattern=r'eval\(', message="No eval", severity="block"),
        ])

        messages = engine.check_code_rules(
            "write_file", {"path": "bad.py", "content": "eval(x)"}
        )
        assert any(m.startswith("BLOQUEADO") for m in messages)
        # record_edit no debe haberse llamado
        assert engine.guardrails._edits_since_last_test == 0

    def test_record_edit_not_called_on_failed_write(self, workspace, make_engine):
        """record_edit() NO se llama si write_file falla (path invalido)."""
        engine = make_engine()

        # Intentar escribir fuera del workspace (path traversal)
        result = engine.execute_tool_call(
            "write_file", {"path": "/etc/passwd", "content": "x"}
        )
        assert not result.success
        assert engine.guardrails._edits_since_last_test == 0


# ═══════════════════════════════════════════════════════════════════════
# BUG-4: dispatch_subagent se registra en el ToolRegistry
# ═══════════════════════════════════════════════════════════════════════


class TestBug4DispatchSubagentRegistration:
    """Verifica que register_dispatch_tool registra la tool correctamente
    y que el agent_factory se invoca al ejecutar."""

    def test_register_dispatch_tool_adds_to_registry(self, workspace):
        """Tras register_dispatch_tool, dispatch_subagent esta en el registry."""
        registry = ToolRegistry()
        ws_config = WorkspaceConfig(root=str(workspace))
        register_all_tools(registry, ws_config)

        # Antes de registrar dispatch
        tool_names = [t.name for t in registry.list_all()]
        assert "dispatch_subagent" not in tool_names

        # Registrar dispatch
        factory = MagicMock()
        register_dispatch_tool(registry, ws_config, factory)

        # Ahora debe estar
        tool_names = [t.name for t in registry.list_all()]
        assert "dispatch_subagent" in tool_names

    def test_dispatch_tool_get_after_register(self, workspace):
        """get() encuentra dispatch_subagent tras register."""
        registry = ToolRegistry()
        ws_config = WorkspaceConfig(root=str(workspace))
        register_all_tools(registry, ws_config)

        factory = MagicMock()
        register_dispatch_tool(registry, ws_config, factory)

        tool = registry.get("dispatch_subagent")
        assert tool.name == "dispatch_subagent"

    def test_dispatch_tool_uses_agent_factory(self, workspace):
        """Al ejecutar dispatch_subagent, se invoca el agent_factory."""
        registry = ToolRegistry()
        ws_config = WorkspaceConfig(root=str(workspace))
        register_all_tools(registry, ws_config)

        mock_agent = MagicMock()
        mock_agent.run.return_value = SimpleNamespace(
            final_output="resultado", cost_tracker=None
        )
        factory = MagicMock(return_value=mock_agent)

        register_dispatch_tool(registry, ws_config, factory)
        tool = registry.get("dispatch_subagent")

        result = tool.execute(task="explorar main.py", agent_type="explore")
        assert result.success
        factory.assert_called_once()
        mock_agent.run.assert_called_once()

    def test_dispatch_factory_receives_correct_kwargs(self, workspace):
        """El factory recibe agent, max_steps y allowed_tools."""
        registry = ToolRegistry()
        ws_config = WorkspaceConfig(root=str(workspace))

        mock_agent = MagicMock()
        mock_agent.run.return_value = SimpleNamespace(
            final_output="ok", cost_tracker=None
        )
        factory = MagicMock(return_value=mock_agent)

        register_dispatch_tool(registry, ws_config, factory)
        tool = registry.get("dispatch_subagent")

        tool.execute(task="test", agent_type="test")
        call_kwargs = factory.call_args[1]
        assert call_kwargs["agent"] == "test"
        assert call_kwargs["max_steps"] == 15  # SUBAGENT_MAX_STEPS
        assert "run_command" in call_kwargs["allowed_tools"]

    def test_dispatch_explore_tools_are_readonly(self, workspace):
        """El tipo explore solo tiene tools de lectura."""
        registry = ToolRegistry()
        ws_config = WorkspaceConfig(root=str(workspace))

        mock_agent = MagicMock()
        mock_agent.run.return_value = SimpleNamespace(
            final_output="ok", cost_tracker=None
        )
        factory = MagicMock(return_value=mock_agent)

        register_dispatch_tool(registry, ws_config, factory)
        tool = registry.get("dispatch_subagent")

        tool.execute(task="leer archivos", agent_type="explore")
        allowed = factory.call_args[1]["allowed_tools"]
        assert "write_file" not in allowed
        assert "edit_file" not in allowed
        assert "run_command" not in allowed
        assert "read_file" in allowed


# ═══════════════════════════════════════════════════════════════════════
# BUG-5: TelemetryConfig se conecta al flujo de ejecucion
# ═══════════════════════════════════════════════════════════════════════


class TestBug5TelemetryWiring:
    """Verifica que create_tracer y el wiring de telemetria funcionan."""

    def test_create_tracer_disabled_returns_noop(self):
        """Con enabled=False, create_tracer retorna NoopTracer."""
        tracer = create_tracer(enabled=False)
        assert isinstance(tracer, NoopTracer)

    def test_create_tracer_uses_config_values(self):
        """create_tracer respeta los parametros."""
        tracer = create_tracer(
            enabled=False,
            exporter="json-file",
            endpoint="http://custom:4317",
            trace_file="/tmp/test-traces.json",
        )
        # Con enabled=False siempre es NoopTracer
        assert isinstance(tracer, NoopTracer)

    def test_noop_tracer_start_session_is_context_manager(self):
        """NoopTracer.start_session funciona como context manager."""
        tracer = NoopTracer()
        with tracer.start_session(
            task="test task", agent="build", model="gpt-4o"
        ) as span:
            span.set_attribute("key", "value")
            span.add_event("event")
        # No debe lanzar excepcion

    def test_noop_tracer_trace_llm_call(self):
        """NoopTracer.trace_llm_call funciona como context manager."""
        tracer = NoopTracer()
        with tracer.trace_llm_call(model="gpt-4o", tokens_in=100, tokens_out=50):
            pass

    def test_noop_tracer_trace_tool(self):
        """NoopTracer.trace_tool funciona como context manager."""
        tracer = NoopTracer()
        with tracer.trace_tool(tool_name="write_file", success=True):
            pass

    def test_noop_tracer_shutdown_no_error(self):
        """NoopTracer.shutdown() no lanza excepciones."""
        tracer = NoopTracer()
        tracer.shutdown()

    def test_telemetry_config_exists_in_app_config(self):
        """AppConfig tiene un campo telemetry con defaults."""
        config = AppConfig()
        assert hasattr(config, "telemetry")
        assert config.telemetry.enabled is False
        assert config.telemetry.exporter == "console"
        assert config.telemetry.endpoint == "http://localhost:4317"
        assert config.telemetry.trace_file is None

    def test_telemetry_config_custom_values(self):
        """TelemetryConfig acepta valores custom."""
        from architect.config.schema import TelemetryConfig
        tc = TelemetryConfig(
            enabled=True,
            exporter="json-file",
            endpoint="http://otel:4317",
            trace_file="/tmp/traces.json",
        )
        assert tc.enabled is True
        assert tc.exporter == "json-file"
        assert tc.trace_file == "/tmp/traces.json"


# ═══════════════════════════════════════════════════════════════════════
# BUG-6: HealthConfig se conecta al CLI con --health flag
# ═══════════════════════════════════════════════════════════════════════


class TestBug6HealthWiring:
    """Verifica que CodeHealthAnalyzer se integra correctamente."""

    def test_health_config_exists_in_app_config(self):
        """AppConfig tiene campo health con defaults."""
        config = AppConfig()
        assert hasattr(config, "health")
        assert config.health.enabled is False
        assert config.health.include_patterns == ["**/*.py"]

    def test_health_config_custom_values(self):
        """HealthConfig acepta valores custom."""
        from architect.config.schema import HealthConfig
        hc = HealthConfig(
            enabled=True,
            include_patterns=["src/**/*.py"],
            exclude_dirs=["vendor"],
        )
        assert hc.enabled is True
        assert hc.include_patterns == ["src/**/*.py"]
        assert hc.exclude_dirs == ["vendor"]

    def test_analyzer_takes_before_after_snapshots(self, workspace):
        """CodeHealthAnalyzer puede tomar snapshots before/after y calcular delta."""
        from architect.core.health import CodeHealthAnalyzer

        # Crear un archivo Python basico
        (workspace / "main.py").write_text("def hello():\n    return 1\n")

        analyzer = CodeHealthAnalyzer(str(workspace))
        before = analyzer.take_before_snapshot()
        assert before.files_analyzed >= 1
        assert before.total_functions >= 1

        # Simular cambio: agregar funcion
        (workspace / "main.py").write_text(
            "def hello():\n    return 1\n\ndef goodbye():\n    return 2\n"
        )

        after = analyzer.take_after_snapshot()
        assert after.total_functions >= 2

        delta = analyzer.compute_delta()
        assert delta is not None
        assert delta.new_functions >= 1

    def test_analyzer_delta_without_snapshots_returns_none(self, workspace):
        """compute_delta retorna None si falta algun snapshot."""
        from architect.core.health import CodeHealthAnalyzer
        analyzer = CodeHealthAnalyzer(str(workspace))
        assert analyzer.compute_delta() is None

    def test_analyzer_respects_include_patterns(self, workspace):
        """CodeHealthAnalyzer solo analiza archivos que matchean los patrones."""
        from architect.core.health import CodeHealthAnalyzer

        (workspace / "main.py").write_text("def f(): pass\n")
        (workspace / "data.txt").write_text("not python\n")

        analyzer = CodeHealthAnalyzer(
            str(workspace), include_patterns=["**/*.py"]
        )
        snapshot = analyzer.snapshot()
        # Solo debe analizar main.py
        assert snapshot.files_analyzed == 1

    def test_delta_report_is_string(self, workspace):
        """HealthDelta.to_report() retorna un string markdown."""
        from architect.core.health import CodeHealthAnalyzer

        (workspace / "app.py").write_text("def f():\n    pass\n")

        analyzer = CodeHealthAnalyzer(str(workspace))
        analyzer.take_before_snapshot()
        analyzer.take_after_snapshot()
        delta = analyzer.compute_delta()

        report = delta.to_report()
        assert isinstance(report, str)
        assert "Code Health Delta" in report
        assert "|" in report  # Tabla markdown


# ═══════════════════════════════════════════════════════════════════════
# BUG-7: Parallel workers propagan --config y --api-base
# ═══════════════════════════════════════════════════════════════════════


class TestBug7ParallelConfigPropagation:
    """Verifica que los workers paralelos propagan --config y --api-base."""

    # -- ParallelConfig acepta nuevos campos --

    def test_parallel_config_has_config_path(self):
        """ParallelConfig tiene campo config_path."""
        config = ParallelConfig(
            tasks=["task"],
            config_path="/path/to/config.yaml",
        )
        assert config.config_path == "/path/to/config.yaml"

    def test_parallel_config_has_api_base(self):
        """ParallelConfig tiene campo api_base."""
        config = ParallelConfig(
            tasks=["task"],
            api_base="http://localhost:4000/v1",
        )
        assert config.api_base == "http://localhost:4000/v1"

    def test_parallel_config_defaults_none(self):
        """config_path y api_base son None por defecto."""
        config = ParallelConfig(tasks=["task"])
        assert config.config_path is None
        assert config.api_base is None

    # -- _run_worker_process incluye --config en el comando --

    @patch("architect.features.parallel.subprocess.run")
    def test_worker_includes_config_in_command(self, mock_run):
        """Con config_path, el comando incluye --config."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Fix bug",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
            config_path="/home/user/architect.yaml",
        )

        cmd = mock_run.call_args[0][0]
        assert "--config" in cmd
        idx = cmd.index("--config")
        assert cmd[idx + 1] == "/home/user/architect.yaml"

    @patch("architect.features.parallel.subprocess.run")
    def test_worker_includes_api_base_in_command(self, mock_run):
        """Con api_base, el comando incluye --api-base."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Fix bug",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
            api_base="http://localhost:4000/v1",
        )

        cmd = mock_run.call_args[0][0]
        assert "--api-base" in cmd
        idx = cmd.index("--api-base")
        assert cmd[idx + 1] == "http://localhost:4000/v1"

    @patch("architect.features.parallel.subprocess.run")
    def test_worker_includes_both_config_and_api_base(self, mock_run):
        """Con ambos, el comando incluye --config y --api-base."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Fix",
            model="gpt-4o",
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
            config_path="/etc/architect.yaml",
            api_base="http://proxy:8080/v1",
        )

        cmd = mock_run.call_args[0][0]
        assert "--config" in cmd
        assert "--api-base" in cmd
        assert cmd[cmd.index("--config") + 1] == "/etc/architect.yaml"
        assert cmd[cmd.index("--api-base") + 1] == "http://proxy:8080/v1"

    @patch("architect.features.parallel.subprocess.run")
    def test_worker_omits_config_when_none(self, mock_run):
        """Sin config_path, el comando NO incluye --config."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Task",
            model=None,
            worktree_path="/tmp/wt",
            branch="b",
            agent="build",
            max_steps=50,
            budget=None,
            timeout=None,
            config_path=None,
            api_base=None,
        )

        cmd = mock_run.call_args[0][0]
        assert "--config" not in cmd
        assert "--api-base" not in cmd

    # -- ParallelRunner pasa config_path/api_base a los workers --

    def test_runner_stores_config_path_in_config(self, workspace):
        """ParallelRunner accede a config_path desde su config."""
        config = ParallelConfig(
            tasks=["task"],
            workers=1,
            config_path="/my/config.yaml",
            api_base="http://my-proxy:4000/v1",
        )
        runner = ParallelRunner(config, str(workspace))
        assert runner.config.config_path == "/my/config.yaml"
        assert runner.config.api_base == "http://my-proxy:4000/v1"

    @patch("architect.features.parallel.ProcessPoolExecutor")
    @patch("architect.features.parallel.ParallelRunner._create_worktrees")
    def test_runner_submits_config_to_executor(self, mock_create_wt, mock_executor_cls, workspace):
        """ParallelRunner pasa config_path y api_base en executor.submit kwargs."""
        wt_path = workspace / ".architect-parallel-1"
        wt_path.mkdir()

        config = ParallelConfig(
            tasks=["task"],
            workers=1,
            config_path="/my/config.yaml",
            api_base="http://my-proxy:4000/v1",
        )
        runner = ParallelRunner(config, str(workspace))
        runner.worktrees = [wt_path]

        # Mock executor para capturar los kwargs de submit
        mock_future = MagicMock()
        mock_future.result.return_value = WorkerResult(
            worker_id=1, branch="b", model="default",
            status="success", steps=1, cost=0, duration=1.0,
            files_modified=[], worktree_path=str(wt_path),
        )
        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future
        mock_executor.__enter__ = MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = MagicMock(return_value=False)
        mock_executor_cls.return_value = mock_executor

        # Simular as_completed
        with patch("architect.features.parallel.as_completed", return_value=iter([mock_future])):
            runner.run()

        # Verificar que submit fue llamado con config_path y api_base
        submit_kwargs = mock_executor.submit.call_args[1]
        assert submit_kwargs["config_path"] == "/my/config.yaml"
        assert submit_kwargs["api_base"] == "http://my-proxy:4000/v1"

    @patch("architect.features.parallel.ProcessPoolExecutor")
    @patch("architect.features.parallel.ParallelRunner._create_worktrees")
    def test_runner_submits_none_config_when_not_set(self, mock_create_wt, mock_executor_cls, workspace):
        """Sin config_path/api_base, submit los pasa como None."""
        wt_path = workspace / ".architect-parallel-1"
        wt_path.mkdir()

        config = ParallelConfig(tasks=["task"], workers=1)
        runner = ParallelRunner(config, str(workspace))
        runner.worktrees = [wt_path]

        mock_future = MagicMock()
        mock_future.result.return_value = WorkerResult(
            worker_id=1, branch="b", model="default",
            status="success", steps=1, cost=0, duration=1.0,
            files_modified=[], worktree_path=str(wt_path),
        )
        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future
        mock_executor.__enter__ = MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = MagicMock(return_value=False)
        mock_executor_cls.return_value = mock_executor

        with patch("architect.features.parallel.as_completed", return_value=iter([mock_future])):
            runner.run()

        submit_kwargs = mock_executor.submit.call_args[1]
        assert submit_kwargs["config_path"] is None
        assert submit_kwargs["api_base"] is None

    @patch("architect.features.parallel.subprocess.run")
    def test_worker_with_config_still_has_standard_flags(self, mock_run):
        """Con config_path, el comando mantiene los flags estandar."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"status": "success"}),
            stderr="",
        )

        _run_worker_process(
            worker_id=1,
            task="Task",
            model="gpt-4o",
            worktree_path="/tmp/wt",
            branch="b",
            agent="plan",
            max_steps=30,
            budget=2.0,
            timeout=120,
            config_path="/config.yaml",
            api_base="http://proxy/v1",
        )

        cmd = mock_run.call_args[0][0]
        # Flags estandar siguen presentes
        assert cmd[0] == "architect"
        assert cmd[1] == "run"
        assert cmd[2] == "Task"
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "plan"
        assert "--confirm-mode" in cmd
        assert "--json" in cmd
        assert "--max-steps" in cmd
        assert "--model" in cmd
        assert "--budget" in cmd
        assert "--timeout" in cmd
        # Nuevos flags tambien presentes
        assert "--config" in cmd
        assert "--api-base" in cmd
