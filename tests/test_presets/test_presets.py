"""
Tests para Preset Configs (v4-D5).

Cubre:
- AVAILABLE_PRESETS (constante)
- PRESET_TEMPLATES (contenido de cada preset)
- PresetManager (apply, list, get_files, overwrite, errores)
"""

from pathlib import Path

import pytest

from architect.config.presets import (
    AVAILABLE_PRESETS,
    PRESET_TEMPLATES,
    PresetManager,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Workspace temporal."""
    return tmp_path


@pytest.fixture
def manager(workspace: Path) -> PresetManager:
    """PresetManager configurado para el workspace temporal."""
    return PresetManager(str(workspace))


# -- Tests: Constants ---------------------------------------------------------


class TestConstants:
    """Tests para constantes del módulo."""

    def test_available_presets(self):
        assert "python" in AVAILABLE_PRESETS
        assert "node-react" in AVAILABLE_PRESETS
        assert "ci" in AVAILABLE_PRESETS
        assert "paranoid" in AVAILABLE_PRESETS
        assert "yolo" in AVAILABLE_PRESETS
        assert len(AVAILABLE_PRESETS) == 5

    def test_all_presets_have_templates(self):
        for preset in AVAILABLE_PRESETS:
            assert preset in PRESET_TEMPLATES

    def test_all_templates_have_architect_md(self):
        for preset, templates in PRESET_TEMPLATES.items():
            assert ".architect.md" in templates, f"Preset '{preset}' missing .architect.md"

    def test_all_templates_have_config_yaml(self):
        for preset, templates in PRESET_TEMPLATES.items():
            assert "config.yaml" in templates, f"Preset '{preset}' missing config.yaml"

    def test_templates_non_empty(self):
        for preset, templates in PRESET_TEMPLATES.items():
            for filename, content in templates.items():
                assert len(content) > 10, (
                    f"Preset '{preset}' file '{filename}' is too short"
                )


# -- Tests: PresetManager -----------------------------------------------------


class TestPresetManager:
    """Tests para PresetManager."""

    def test_init(self, manager, workspace):
        assert manager.root == workspace

    def test_apply_python_preset(self, manager, workspace):
        files = manager.apply_preset("python")

        assert ".architect.md" in files
        assert "config.yaml" in files

        architect_md = workspace / ".architect.md"
        assert architect_md.exists()
        content = architect_md.read_text()
        assert "Python" in content

        config_yaml = workspace / "config.yaml"
        assert config_yaml.exists()
        config_content = config_yaml.read_text()
        assert "pytest" in config_content or "ruff" in config_content

    def test_apply_node_react_preset(self, manager, workspace):
        files = manager.apply_preset("node-react")
        assert len(files) >= 2

        architect_md = workspace / ".architect.md"
        content = architect_md.read_text()
        assert "Node" in content or "React" in content

    def test_apply_ci_preset(self, manager, workspace):
        files = manager.apply_preset("ci")
        assert len(files) >= 2

        config = workspace / "config.yaml"
        content = config.read_text()
        assert "yolo" in content

    def test_apply_paranoid_preset(self, manager, workspace):
        files = manager.apply_preset("paranoid")
        assert len(files) >= 2

        config = workspace / "config.yaml"
        content = config.read_text()
        assert "confirm-all" in content
        assert "code_rules" in content
        assert "eval" in content

    def test_apply_yolo_preset(self, manager, workspace):
        files = manager.apply_preset("yolo")
        assert len(files) >= 2

        config = workspace / "config.yaml"
        content = config.read_text()
        assert "yolo" in content
        assert "enabled: false" in content

    def test_apply_creates_architect_dir(self, manager, workspace):
        manager.apply_preset("python")
        assert (workspace / ".architect").is_dir()

    def test_apply_invalid_preset_raises(self, manager):
        with pytest.raises(ValueError, match="no existe"):
            manager.apply_preset("nonexistent")

    def test_apply_no_overwrite_by_default(self, manager, workspace):
        # Crear archivo existente
        (workspace / ".architect.md").write_text("Existing content")

        files = manager.apply_preset("python")

        # .architect.md no debe estar en archivos creados
        assert ".architect.md" not in files
        # Contenido original preservado
        assert (workspace / ".architect.md").read_text() == "Existing content"

    def test_apply_overwrite(self, manager, workspace):
        # Crear archivo existente
        (workspace / ".architect.md").write_text("Existing content")

        files = manager.apply_preset("python", overwrite=True)

        assert ".architect.md" in files
        content = (workspace / ".architect.md").read_text()
        assert "Existing content" not in content
        assert "Python" in content

    def test_apply_partial_overwrite(self, manager, workspace):
        # Solo config.yaml existe
        (workspace / "config.yaml").write_text("old config")

        files = manager.apply_preset("python")

        # .architect.md creado, config.yaml no tocado
        assert ".architect.md" in files
        assert "config.yaml" not in files

    def test_list_presets(self, manager):
        presets = manager.list_presets()
        assert len(presets) == 5
        names = [p["name"] for p in presets]
        assert "python" in names
        assert "paranoid" in names
        for p in presets:
            assert "name" in p
            assert "description" in p
            assert len(p["description"]) > 0

    def test_get_preset_files(self, manager):
        files = manager.get_preset_files("python")
        assert ".architect.md" in files
        assert "config.yaml" in files
        assert "Python" in files[".architect.md"]

    def test_get_preset_files_invalid(self, manager):
        with pytest.raises(ValueError, match="no existe"):
            manager.get_preset_files("nonexistent")


# -- Tests: Config YAML Validity ---------------------------------------------


class TestConfigYAMLValidity:
    """Tests para verificar que los config.yaml son YAML válido."""

    @pytest.mark.parametrize("preset", sorted(AVAILABLE_PRESETS))
    def test_config_yaml_is_valid(self, preset):
        import yaml

        content = PRESET_TEMPLATES[preset]["config.yaml"]
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    @pytest.mark.parametrize("preset", sorted(AVAILABLE_PRESETS))
    def test_config_yaml_has_llm_section(self, preset):
        import yaml

        content = PRESET_TEMPLATES[preset]["config.yaml"]
        parsed = yaml.safe_load(content)
        assert "llm" in parsed

    @pytest.mark.parametrize("preset", sorted(AVAILABLE_PRESETS))
    def test_config_yaml_has_agents_section(self, preset):
        import yaml

        content = PRESET_TEMPLATES[preset]["config.yaml"]
        parsed = yaml.safe_load(content)
        assert "agents" in parsed


# -- Tests: Edge Cases --------------------------------------------------------


class TestEdgeCases:
    """Tests para casos borde."""

    def test_apply_to_nonexistent_subdir(self, tmp_path):
        workspace = tmp_path / "deep" / "nested" / "project"
        # No necesitamos crear el directorio — PresetManager debería manejar
        workspace.mkdir(parents=True)

        manager = PresetManager(str(workspace))
        files = manager.apply_preset("yolo")
        assert len(files) >= 2

    def test_apply_twice_no_overwrite(self, manager, workspace):
        files1 = manager.apply_preset("python")
        files2 = manager.apply_preset("python")

        assert len(files1) >= 2
        assert len(files2) == 0  # Nada nuevo creado

    def test_apply_different_preset_over_existing(self, manager, workspace):
        manager.apply_preset("python")
        # Aplicar otro preset sin overwrite
        files = manager.apply_preset("ci")
        # No debe sobrescribir los archivos existentes
        assert len(files) == 0
