"""
Tests para el sistema de sub-agentes / dispatch (v4-D1).

Cubre:
- DispatchSubagentArgs (validación Pydantic)
- DispatchSubagentTool (init, execute con tipos válidos/inválidos, truncado, errores)
- Prompt building (explore, test, review)
- Constantes (SUBAGENT_ALLOWED_TOOLS, VALID_SUBAGENT_TYPES, max chars/steps)
- Integración con agent_factory (mock)
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from architect.tools.base import ToolResult
from architect.tools.dispatch import (
    SUBAGENT_ALLOWED_TOOLS,
    SUBAGENT_MAX_STEPS,
    SUBAGENT_SUMMARY_MAX_CHARS,
    VALID_SUBAGENT_TYPES,
    DispatchSubagentArgs,
    DispatchSubagentTool,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def mock_agent_result():
    """Crea un mock de resultado de AgentLoop.run()."""
    result = Mock()
    result.final_response = "El archivo main.py contiene una función process() que..."
    result.total_cost = 0.015
    result.steps_completed = 5
    return result


@pytest.fixture
def mock_agent_factory(mock_agent_result):
    """Factory que retorna un mock AgentLoop."""
    agent = Mock()
    agent.run.return_value = mock_agent_result
    factory = Mock(return_value=agent)
    return factory


@pytest.fixture
def tool(mock_agent_factory):
    """DispatchSubagentTool con factory mock."""
    return DispatchSubagentTool(
        agent_factory=mock_agent_factory,
        workspace_root="/tmp/workspace",
    )


# -- Tests: DispatchSubagentArgs --------------------------------------------


class TestDispatchSubagentArgs:
    """Tests para el modelo de argumentos."""

    def test_default_values(self):
        args = DispatchSubagentArgs(task="Investiga el bug")
        assert args.task == "Investiga el bug"
        assert args.agent_type == "explore"
        assert args.relevant_files == []

    def test_all_fields(self):
        args = DispatchSubagentArgs(
            task="Ejecuta tests",
            agent_type="test",
            relevant_files=["src/main.py", "tests/test_main.py"],
        )
        assert args.agent_type == "test"
        assert len(args.relevant_files) == 2

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            DispatchSubagentArgs(task="test", unknown_field="bad")

    def test_task_required(self):
        with pytest.raises(Exception):
            DispatchSubagentArgs()


# -- Tests: Constantes -------------------------------------------------------


class TestConstants:
    """Tests para constantes del módulo."""

    def test_valid_subagent_types(self):
        assert "explore" in VALID_SUBAGENT_TYPES
        assert "test" in VALID_SUBAGENT_TYPES
        assert "review" in VALID_SUBAGENT_TYPES
        assert len(VALID_SUBAGENT_TYPES) == 3

    def test_allowed_tools_explore_readonly(self):
        tools = SUBAGENT_ALLOWED_TOOLS["explore"]
        assert "read_file" in tools
        assert "search_code" in tools
        assert "grep" in tools
        assert "write_file" not in tools
        assert "edit_file" not in tools
        assert "run_command" not in tools

    def test_allowed_tools_test_has_run_command(self):
        tools = SUBAGENT_ALLOWED_TOOLS["test"]
        assert "run_command" in tools
        assert "read_file" in tools

    def test_allowed_tools_review_readonly(self):
        tools = SUBAGENT_ALLOWED_TOOLS["review"]
        assert "read_file" in tools
        assert "write_file" not in tools
        assert "run_command" not in tools

    def test_max_steps_is_low(self):
        assert SUBAGENT_MAX_STEPS == 15

    def test_summary_max_chars(self):
        assert SUBAGENT_SUMMARY_MAX_CHARS == 1000


# -- Tests: DispatchSubagentTool ---------------------------------------------


class TestDispatchSubagentTool:
    """Tests para el tool de dispatch."""

    def test_init(self, tool):
        assert tool.name == "dispatch_subagent"
        assert tool.sensitive is False
        assert tool.args_model is DispatchSubagentArgs

    def test_description_non_empty(self, tool):
        assert len(tool.description) > 50

    def test_get_schema(self, tool):
        schema = tool.get_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "dispatch_subagent"
        assert "parameters" in schema["function"]

    def test_execute_explore_success(self, tool, mock_agent_factory, mock_agent_result):
        result = tool.execute(task="Investiga cómo funciona el parser")

        assert result.success is True
        assert mock_agent_result.final_response in result.output

        # Verificar que factory fue llamada con los argumentos correctos
        mock_agent_factory.assert_called_once_with(
            agent="explore",
            max_steps=SUBAGENT_MAX_STEPS,
            allowed_tools=SUBAGENT_ALLOWED_TOOLS["explore"],
        )

    def test_execute_test_type(self, tool, mock_agent_factory):
        result = tool.execute(task="Ejecuta los tests de main.py", agent_type="test")

        assert result.success is True
        mock_agent_factory.assert_called_once_with(
            agent="test",
            max_steps=SUBAGENT_MAX_STEPS,
            allowed_tools=SUBAGENT_ALLOWED_TOOLS["test"],
        )

    def test_execute_review_type(self, tool, mock_agent_factory):
        result = tool.execute(task="Revisa el código", agent_type="review")

        assert result.success is True
        mock_agent_factory.assert_called_once_with(
            agent="review",
            max_steps=SUBAGENT_MAX_STEPS,
            allowed_tools=SUBAGENT_ALLOWED_TOOLS["review"],
        )

    def test_execute_invalid_type(self, tool, mock_agent_factory):
        result = tool.execute(task="Test", agent_type="invalid_type")

        assert result.success is False
        assert "inválido" in result.error
        assert "explore" in result.error
        mock_agent_factory.assert_not_called()

    def test_execute_with_relevant_files(self, tool, mock_agent_factory):
        result = tool.execute(
            task="Investiga",
            relevant_files=["src/main.py", "src/utils.py"],
        )

        assert result.success is True
        # El agente debe haber sido llamado con un prompt que incluya los archivos
        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]
        assert "src/main.py" in prompt
        assert "src/utils.py" in prompt

    def test_execute_truncates_long_response(self, tool, mock_agent_result):
        # Respuesta más larga que SUBAGENT_SUMMARY_MAX_CHARS
        mock_agent_result.final_response = "X" * 2000

        result = tool.execute(task="Investiga")

        assert result.success is True
        assert len(result.output) < 2000
        assert "truncado" in result.output

    def test_execute_no_response(self, tool, mock_agent_result):
        mock_agent_result.final_response = None

        result = tool.execute(task="Investiga")

        assert result.success is True
        assert "Sin resultado" in result.output

    def test_execute_empty_response(self, tool, mock_agent_result):
        mock_agent_result.final_response = ""

        result = tool.execute(task="Investiga")

        assert result.success is True
        # Empty string is falsy, so should get fallback
        assert "Sin resultado" in result.output

    def test_execute_agent_factory_error(self, tool, mock_agent_factory):
        mock_agent_factory.side_effect = RuntimeError("Factory failed")

        result = tool.execute(task="Investiga")

        assert result.success is False
        assert "Error ejecutando sub-agente" in result.error

    def test_execute_agent_run_error(self, tool, mock_agent_factory):
        agent = mock_agent_factory.return_value
        agent.run.side_effect = RuntimeError("LLM failed")

        result = tool.execute(task="Investiga")

        assert result.success is False
        assert "Error ejecutando sub-agente" in result.error

    def test_execute_relevant_files_none(self, tool):
        result = tool.execute(task="Investiga", relevant_files=None)

        assert result.success is True

    def test_validate_args(self, tool):
        validated = tool.validate_args({
            "task": "Test task",
            "agent_type": "explore",
        })
        assert isinstance(validated, DispatchSubagentArgs)
        assert validated.task == "Test task"


# -- Tests: Prompt Building --------------------------------------------------


class TestPromptBuilding:
    """Tests para la construcción del prompt del sub-agente."""

    def test_explore_prompt_has_instructions(self, tool, mock_agent_factory):
        tool.execute(task="Busca imports de os.system", agent_type="explore")

        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]

        assert "explore" in prompt
        assert "Investiga" in prompt or "lectura" in prompt
        assert "NO modifiques" in prompt

    def test_test_prompt_has_instructions(self, tool, mock_agent_factory):
        tool.execute(task="Ejecuta pytest tests/", agent_type="test")

        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]

        assert "test" in prompt.lower()
        assert "NO modifiques" in prompt

    def test_review_prompt_has_instructions(self, tool, mock_agent_factory):
        tool.execute(task="Revisa seguridad", agent_type="review")

        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]

        assert "Revisa" in prompt
        assert "bugs" in prompt or "problemas" in prompt

    def test_prompt_includes_relevant_files(self, tool, mock_agent_factory):
        files = ["src/auth.py", "src/db.py", "tests/test_auth.py"]
        tool.execute(task="Revisa", agent_type="review", relevant_files=files)

        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]

        assert "src/auth.py" in prompt
        assert "src/db.py" in prompt
        assert "tests/test_auth.py" in prompt

    def test_prompt_limits_relevant_files(self, tool, mock_agent_factory):
        # Más de 10 archivos — se limita a 10
        files = [f"file_{i}.py" for i in range(20)]
        tool.execute(task="Investiga", relevant_files=files)

        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]

        # Solo los primeros 10 deben estar
        assert "file_0.py" in prompt
        assert "file_9.py" in prompt
        assert "file_10.py" not in prompt

    def test_prompt_without_files(self, tool, mock_agent_factory):
        tool.execute(task="Investiga la estructura general")

        agent = mock_agent_factory.return_value
        prompt = agent.run.call_args[0][0]

        assert "Archivos Relevantes" not in prompt


# -- Tests: Edge Cases -------------------------------------------------------


class TestEdgeCases:
    """Tests para casos borde."""

    def test_exact_max_chars_no_truncation(self, tool, mock_agent_result):
        mock_agent_result.final_response = "X" * SUBAGENT_SUMMARY_MAX_CHARS

        result = tool.execute(task="Test")

        assert result.success is True
        assert "truncado" not in result.output

    def test_one_over_max_chars_triggers_truncation(self, tool, mock_agent_result):
        mock_agent_result.final_response = "X" * (SUBAGENT_SUMMARY_MAX_CHARS + 1)

        result = tool.execute(task="Test")

        assert result.success is True
        assert "truncado" in result.output

    def test_result_without_attributes(self, tool, mock_agent_factory):
        # Resultado sin atributos esperados (solo final_response)
        result = Mock(spec=[])
        result.final_response = "Resultado simple"
        agent = mock_agent_factory.return_value
        agent.run.return_value = result

        tool_result = tool.execute(task="Test")

        assert tool_result.success is True
        assert "Resultado simple" in tool_result.output

    def test_very_long_task_doesnt_crash(self, tool):
        long_task = "X" * 10000
        result = tool.execute(task=long_task)
        assert result.success is True
