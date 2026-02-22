"""
Tests para la Memoria Procedural (v4-A4).

Cubre:
- detect_correction: detección de patrones de corrección
- add_correction / add_pattern: persistencia en archivo
- get_context: generación de contexto para inyectar en system prompt
- analyze_session_learnings: extracción de correcciones de conversación
- _load: carga de entradas existentes
- Deduplicación de entradas
- MemoryConfig: schema Pydantic
"""

from pathlib import Path

import pytest

from architect.config.schema import AppConfig, MemoryConfig
from architect.skills.memory import ProceduralMemory


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def memory(workspace: Path) -> ProceduralMemory:
    return ProceduralMemory(str(workspace))


# ── Tests: detect_correction ──────────────────────────────────────────


class TestDetectCorrection:
    def test_direct_correction_no_usa(self, memory: ProceduralMemory):
        result = memory.detect_correction("No, usa pytest en vez de unittest")
        assert result is not None
        assert "pytest" in result

    def test_negation_eso_no(self, memory: ProceduralMemory):
        result = memory.detect_correction("Eso no es correcto, el path es otro")
        assert result is not None

    def test_clarification_en_realidad(self, memory: ProceduralMemory):
        result = memory.detect_correction("En realidad el API key va en .env")
        assert result is not None

    def test_should_be_pattern(self, memory: ProceduralMemory):
        result = memory.detect_correction("Debería ser snake_case, no camelCase")
        assert result is not None

    def test_wrong_approach(self, memory: ProceduralMemory):
        result = memory.detect_correction("No funciona así, tienes que usar requests")
        assert result is not None

    def test_absolute_rule_siempre(self, memory: ProceduralMemory):
        result = memory.detect_correction("Siempre usa black para formatear")
        assert result is not None

    def test_absolute_rule_nunca(self, memory: ProceduralMemory):
        result = memory.detect_correction("Nunca hagas print en produccion")
        assert result is not None

    def test_normal_message_not_correction(self, memory: ProceduralMemory):
        result = memory.detect_correction("Ahora crea un archivo de tests")
        assert result is None

    def test_question_not_correction(self, memory: ProceduralMemory):
        result = memory.detect_correction("Que hace esta funcion?")
        assert result is None

    def test_long_message_truncated(self, memory: ProceduralMemory):
        long_msg = "No, usa esto: " + "x" * 400
        result = memory.detect_correction(long_msg)
        assert result is not None
        assert len(result) <= 303  # 300 + "..."


# ── Tests: add_correction ─────────────────────────────────────────────


class TestAddCorrection:
    def test_creates_memory_file(self, memory: ProceduralMemory):
        memory.add_correction("Usa pytest siempre")
        assert memory.memory_path.exists()
        content = memory.memory_path.read_text()
        assert "Usa pytest siempre" in content
        assert "Correccion:" in content

    def test_creates_header(self, memory: ProceduralMemory):
        memory.add_correction("test")
        content = memory.memory_path.read_text()
        assert "# Memoria del Proyecto" in content

    def test_appends_to_existing(self, memory: ProceduralMemory):
        memory.add_correction("Primera correccion")
        memory.add_correction("Segunda correccion")
        content = memory.memory_path.read_text()
        assert "Primera correccion" in content
        assert "Segunda correccion" in content

    def test_deduplication(self, memory: ProceduralMemory):
        memory.add_correction("Duplicada")
        memory.add_correction("Duplicada")
        assert len(memory.entries) == 1

    def test_entry_format(self, memory: ProceduralMemory):
        memory.add_correction("Test correction")
        content = memory.memory_path.read_text()
        # Format: "- [YYYY-MM-DD] Correccion: text"
        import re
        assert re.search(r"- \[\d{4}-\d{2}-\d{2}\] Correccion: Test correction", content)


# ── Tests: add_pattern ────────────────────────────────────────────────


class TestAddPattern:
    def test_adds_pattern(self, memory: ProceduralMemory):
        memory.add_pattern("Tests siempre con pytest")
        assert memory.memory_path.exists()
        content = memory.memory_path.read_text()
        assert "Patron:" in content
        assert "Tests siempre con pytest" in content

    def test_pattern_deduplication(self, memory: ProceduralMemory):
        memory.add_pattern("Same pattern")
        memory.add_pattern("Same pattern")
        assert len(memory.entries) == 1


# ── Tests: get_context ────────────────────────────────────────────────


class TestGetContext:
    def test_no_memory_file(self, memory: ProceduralMemory):
        ctx = memory.get_context()
        assert ctx == ""

    def test_with_entries(self, memory: ProceduralMemory):
        memory.add_correction("Siempre usa typing")
        ctx = memory.get_context()
        assert "Memoria del Proyecto" in ctx
        assert "correcciones anteriores" in ctx
        assert "Siempre usa typing" in ctx

    def test_empty_file_returns_empty(self, workspace: Path):
        mem_path = workspace / ".architect" / "memory.md"
        mem_path.parent.mkdir(parents=True)
        mem_path.write_text("")
        mem = ProceduralMemory(str(workspace))
        assert mem.get_context() == ""


# ── Tests: _load (persistencia entre instancias) ─────────────────────


class TestPersistence:
    def test_reload_entries(self, workspace: Path):
        mem1 = ProceduralMemory(str(workspace))
        mem1.add_correction("Persistida")
        mem1.add_pattern("Patron persistido")

        # Nueva instancia carga lo guardado
        mem2 = ProceduralMemory(str(workspace))
        assert len(mem2.entries) == 2
        contents = [e["content"] for e in mem2.entries]
        assert "Persistida" in contents
        assert "Patron persistido" in contents

    def test_types_preserved(self, workspace: Path):
        mem1 = ProceduralMemory(str(workspace))
        mem1.add_correction("Correccion 1")
        mem1.add_pattern("Patron 1")

        mem2 = ProceduralMemory(str(workspace))
        types = [e["type"] for e in mem2.entries]
        assert "Correccion" in types
        assert "Patron" in types


# ── Tests: analyze_session_learnings ──────────────────────────────────


class TestAnalyzeSession:
    def test_extracts_corrections(self, memory: ProceduralMemory):
        conversation = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Haz un script de tests"},
            {"role": "assistant", "content": "Ok, uso unittest..."},
            {"role": "user", "content": "No, usa pytest en vez de unittest"},
            {"role": "assistant", "content": "Ok, cambio a pytest."},
        ]
        corrections = memory.analyze_session_learnings(conversation)
        assert len(corrections) == 1
        assert "pytest" in corrections[0]

    def test_no_corrections_in_normal_conversation(self, memory: ProceduralMemory):
        conversation = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Crea un archivo de tests"},
            {"role": "assistant", "content": "Creado."},
        ]
        corrections = memory.analyze_session_learnings(conversation)
        assert corrections == []

    def test_first_message_ignored(self, memory: ProceduralMemory):
        # First user message (i=0) should not be treated as correction
        conversation = [
            {"role": "user", "content": "No, usa pytest"},
        ]
        corrections = memory.analyze_session_learnings(conversation)
        assert corrections == []

    def test_corrections_persisted(self, memory: ProceduralMemory):
        conversation = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Hola"},
            {"role": "user", "content": "Eso no es correcto, debes usar async"},
        ]
        memory.analyze_session_learnings(conversation)
        assert memory.memory_path.exists()
        assert len(memory.entries) == 1


# ── Tests: Config Schema ──────────────────────────────────────────────


class TestMemoryConfigSchema:
    def test_defaults(self):
        config = MemoryConfig()
        assert config.enabled is False
        assert config.auto_detect_corrections is True

    def test_custom_values(self):
        config = MemoryConfig(enabled=True, auto_detect_corrections=False)
        assert config.enabled is True
        assert config.auto_detect_corrections is False

    def test_app_config_includes_memory(self):
        config = AppConfig()
        assert hasattr(config, "memory")
        assert config.memory.enabled is False
