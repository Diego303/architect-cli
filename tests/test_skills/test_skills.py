"""
Tests para el sistema de Skills (v4-A3).

Cubre:
- SkillsLoader: carga de .architect.md, descubrimiento de skills, parsing de frontmatter,
  filtrado por glob, build_system_context
- SkillInstaller: crear skill local, listar, desinstalar
- SkillsConfig: schema Pydantic
"""

from pathlib import Path

import pytest

from architect.config.schema import AppConfig, SkillsConfig
from architect.skills.installer import SkillInstaller
from architect.skills.loader import SkillInfo, SkillsLoader


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


# ── Tests: SkillsLoader — Carga de .architect.md ─────────────────────


class TestProjectContext:
    def test_loads_architect_md(self, workspace: Path):
        (workspace / ".architect.md").write_text("# Proyecto\nInstrucciones aqui.")
        loader = SkillsLoader(str(workspace))
        ctx = loader.load_project_context()
        assert ctx is not None
        assert "Instrucciones aqui" in ctx

    def test_loads_agents_md(self, workspace: Path):
        (workspace / "AGENTS.md").write_text("# Agents\nReglas.")
        loader = SkillsLoader(str(workspace))
        ctx = loader.load_project_context()
        assert ctx is not None
        assert "Reglas" in ctx

    def test_loads_claude_md(self, workspace: Path):
        (workspace / "CLAUDE.md").write_text("# Claude\nDirectivas.")
        loader = SkillsLoader(str(workspace))
        ctx = loader.load_project_context()
        assert ctx is not None
        assert "Directivas" in ctx

    def test_priority_architect_over_agents(self, workspace: Path):
        (workspace / ".architect.md").write_text("Architect context")
        (workspace / "AGENTS.md").write_text("Agents context")
        loader = SkillsLoader(str(workspace))
        ctx = loader.load_project_context()
        assert "Architect context" in ctx

    def test_no_context_file(self, workspace: Path):
        loader = SkillsLoader(str(workspace))
        ctx = loader.load_project_context()
        assert ctx is None

    def test_context_cached_internally(self, workspace: Path):
        (workspace / ".architect.md").write_text("cached content")
        loader = SkillsLoader(str(workspace))
        loader.load_project_context()
        assert loader._project_context == "cached content"


# ── Tests: SkillsLoader — Descubrimiento de Skills ───────────────────


class TestSkillDiscovery:
    def test_discover_local_skills(self, workspace: Path):
        skill_dir = workspace / ".architect" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test skill\nglobs: ['*.py']\n---\n\nContenido."
        )
        loader = SkillsLoader(str(workspace))
        skills = loader.discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == "Test skill"
        assert skills[0].globs == ["*.py"]
        assert skills[0].source == "local"
        assert "Contenido." in skills[0].content

    def test_discover_installed_skills(self, workspace: Path):
        skill_dir = workspace / ".architect" / "installed-skills" / "remote-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: remote-skill\ndescription: Installed\nglobs: []\n---\n\nBody."
        )
        loader = SkillsLoader(str(workspace))
        skills = loader.discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "remote-skill"
        assert skills[0].source == "installed"

    def test_discover_no_skills_dir(self, workspace: Path):
        loader = SkillsLoader(str(workspace))
        skills = loader.discover_skills()
        assert skills == []

    def test_discover_ignores_non_skill_dirs(self, workspace: Path):
        skills_dir = workspace / ".architect" / "skills" / "not-a-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "README.md").write_text("Not a skill")
        loader = SkillsLoader(str(workspace))
        skills = loader.discover_skills()
        assert skills == []

    def test_parse_skill_without_frontmatter(self, workspace: Path):
        skill_dir = workspace / ".architect" / "skills" / "simple"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Simple skill\n\nJust content.")
        loader = SkillsLoader(str(workspace))
        skills = loader.discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "simple"  # Falls back to dir name
        assert "Just content" in skills[0].content


# ── Tests: SkillsLoader — Filtrado por Glob ──────────────────────────


class TestSkillGlobFiltering:
    def _setup_skills(self, workspace: Path) -> SkillsLoader:
        py_skill_dir = workspace / ".architect" / "skills" / "python-lint"
        py_skill_dir.mkdir(parents=True)
        (py_skill_dir / "SKILL.md").write_text(
            "---\nname: python-lint\ndescription: Python linting\nglobs: ['*.py']\n---\n\nUsa ruff."
        )

        ts_skill_dir = workspace / ".architect" / "skills" / "ts-lint"
        ts_skill_dir.mkdir(parents=True)
        (ts_skill_dir / "SKILL.md").write_text(
            "---\nname: ts-lint\ndescription: TypeScript linting\nglobs: ['*.ts', '*.tsx']\n---\n\nUsa eslint."
        )

        no_glob_dir = workspace / ".architect" / "skills" / "general"
        no_glob_dir.mkdir(parents=True)
        (no_glob_dir / "SKILL.md").write_text(
            "---\nname: general\ndescription: General skill\nglobs: []\n---\n\nGeneral."
        )

        loader = SkillsLoader(str(workspace))
        loader.discover_skills()
        return loader

    def test_matching_py_files(self, workspace: Path):
        loader = self._setup_skills(workspace)
        relevant = loader.get_relevant_skills(["src/main.py", "src/util.py"])
        assert len(relevant) == 1
        assert relevant[0].name == "python-lint"

    def test_matching_ts_files(self, workspace: Path):
        loader = self._setup_skills(workspace)
        relevant = loader.get_relevant_skills(["App.tsx"])
        assert len(relevant) == 1
        assert relevant[0].name == "ts-lint"

    def test_no_matching_files(self, workspace: Path):
        loader = self._setup_skills(workspace)
        relevant = loader.get_relevant_skills(["styles.css"])
        assert len(relevant) == 0

    def test_skill_without_glob_never_matches(self, workspace: Path):
        loader = self._setup_skills(workspace)
        relevant = loader.get_relevant_skills(["anything.py"])
        # Only python-lint matches, not "general" (no globs)
        assert len(relevant) == 1
        assert relevant[0].name == "python-lint"


# ── Tests: SkillsLoader — build_system_context ────────────────────────


class TestBuildSystemContext:
    def test_empty_context(self, workspace: Path):
        loader = SkillsLoader(str(workspace))
        assert loader.build_system_context() == ""

    def test_project_context_only(self, workspace: Path):
        (workspace / ".architect.md").write_text("Project rules here.")
        loader = SkillsLoader(str(workspace))
        loader.load_project_context()
        ctx = loader.build_system_context()
        assert "Project Instructions" in ctx
        assert "Project rules here." in ctx

    def test_project_context_plus_skills(self, workspace: Path):
        (workspace / ".architect.md").write_text("Global rules.")
        skill_dir = workspace / ".architect" / "skills" / "py-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: py-skill\ndescription: Python\nglobs: ['*.py']\n---\n\nUsa black."
        )
        loader = SkillsLoader(str(workspace))
        loader.load_project_context()
        loader.discover_skills()
        ctx = loader.build_system_context(active_files=["main.py"])
        assert "Global rules." in ctx
        assert "Skill: py-skill" in ctx
        assert "Usa black." in ctx

    def test_no_active_files_no_skills_injected(self, workspace: Path):
        skill_dir = workspace / ".architect" / "skills" / "py-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: py-skill\nglobs: ['*.py']\n---\n\nContent."
        )
        loader = SkillsLoader(str(workspace))
        loader.discover_skills()
        ctx = loader.build_system_context()  # No active_files
        assert "py-skill" not in ctx


# ── Tests: SkillInstaller ─────────────────────────────────────────────


class TestSkillInstaller:
    def test_create_local_skill(self, workspace: Path):
        installer = SkillInstaller(str(workspace))
        path = installer.create_local("my-test-skill")
        assert path.exists()
        skill_md = path / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "name: my-test-skill" in content

    def test_create_local_idempotent(self, workspace: Path):
        installer = SkillInstaller(str(workspace))
        installer.create_local("my-skill")
        # Modify the SKILL.md
        skill_md = workspace / ".architect" / "skills" / "my-skill" / "SKILL.md"
        skill_md.write_text("Custom content")
        # Create again should not overwrite
        installer.create_local("my-skill")
        assert skill_md.read_text() == "Custom content"

    def test_list_installed_empty(self, workspace: Path):
        installer = SkillInstaller(str(workspace))
        assert installer.list_installed() == []

    def test_list_installed_local(self, workspace: Path):
        installer = SkillInstaller(str(workspace))
        installer.create_local("skill-a")
        skills = installer.list_installed()
        assert len(skills) == 1
        assert skills[0]["name"] == "skill-a"
        assert skills[0]["source"] == "local"

    def test_list_installed_mixed(self, workspace: Path):
        installer = SkillInstaller(str(workspace))
        installer.create_local("local-skill")
        # Simulate an installed skill
        installed_dir = workspace / ".architect" / "installed-skills" / "remote-skill"
        installed_dir.mkdir(parents=True)
        (installed_dir / "SKILL.md").write_text("---\nname: remote-skill\n---\n")
        skills = installer.list_installed()
        assert len(skills) == 2
        names = [s["name"] for s in skills]
        assert "local-skill" in names
        assert "remote-skill" in names

    def test_uninstall_existing(self, workspace: Path):
        installed_dir = workspace / ".architect" / "installed-skills" / "to-remove"
        installed_dir.mkdir(parents=True)
        (installed_dir / "SKILL.md").write_text("content")
        installer = SkillInstaller(str(workspace))
        assert installer.uninstall("to-remove") is True
        assert not installed_dir.exists()

    def test_uninstall_nonexistent(self, workspace: Path):
        installer = SkillInstaller(str(workspace))
        assert installer.uninstall("nonexistent") is False


# ── Tests: Config Schema ──────────────────────────────────────────────


class TestSkillsConfigSchema:
    def test_defaults(self):
        config = SkillsConfig()
        assert config.auto_discover is True
        assert config.inject_by_glob is True

    def test_custom_values(self):
        config = SkillsConfig(auto_discover=False, inject_by_glob=False)
        assert config.auto_discover is False
        assert config.inject_by_glob is False

    def test_app_config_includes_skills(self):
        config = AppConfig()
        assert hasattr(config, "skills")
        assert config.skills.auto_discover is True
