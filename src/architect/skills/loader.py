"""
Skills Loader -- Discovers and loads .architect.md and project skills (v4-A3).

Two complementary layers:
1. .architect.md / AGENTS.md / CLAUDE.md -> context always present in system prompt
2. Skills (.architect/skills/, .architect/installed-skills/) -> workflows invocable by glob
"""

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()


@dataclass
class SkillInfo:
    """Metadata for a skill."""

    name: str
    description: str = ""
    globs: list[str] = field(default_factory=list)
    content: str = ""
    source: str = ""  # "local" | "installed" | "project"


class SkillsLoader:
    """Discovers and loads .architect.md and project skills."""

    ARCHITECT_MD_NAMES = [".architect.md", "AGENTS.md", "CLAUDE.md"]
    SKILLS_DIRS = [".architect/skills", ".architect/installed-skills"]

    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
        self._project_context: str | None = None
        self._skills: list[SkillInfo] = []

    def load_project_context(self) -> str | None:
        """Load .architect.md (or equivalents). Always injected into the system prompt."""
        for name in self.ARCHITECT_MD_NAMES:
            path = self.root / name
            if path.exists():
                content = path.read_text(encoding="utf-8")
                logger.info("project_context_loaded", file=name, chars=len(content))
                self._project_context = content
                return content
        return None

    def discover_skills(self) -> list[SkillInfo]:
        """Discover all available skills in skill directories."""
        skills: list[SkillInfo] = []
        for skills_dir_name in self.SKILLS_DIRS:
            skills_dir = self.root / skills_dir_name
            if not skills_dir.exists():
                continue
            for skill_dir in sorted(skills_dir.iterdir()):
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        skill = self._parse_skill(skill_md)
                        if skill:
                            skills.append(skill)
        self._skills = skills
        logger.info(
            "skills_discovered",
            count=len(skills),
            names=[s.name for s in skills],
        )
        return skills

    def _parse_skill(self, path: Path) -> SkillInfo | None:
        """Parse a SKILL.md with optional YAML frontmatter."""
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("skill_read_error", path=str(path), error=str(e))
            return None

        # Extract YAML frontmatter
        frontmatter_match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL
        )
        if frontmatter_match:
            try:
                meta = yaml.safe_load(frontmatter_match.group(1)) or {}
            except yaml.YAMLError:
                meta = {}
            body = frontmatter_match.group(2)
        else:
            meta = {}
            body = content

        source = "installed" if "installed-skills" in str(path) else "local"
        return SkillInfo(
            name=meta.get("name", path.parent.name),
            description=meta.get("description", ""),
            globs=meta.get("globs", []),
            content=body,
            source=source,
        )

    def get_relevant_skills(self, file_paths: list[str]) -> list[SkillInfo]:
        """Return skills whose glob matches any file in play."""
        relevant: list[SkillInfo] = []
        for skill in self._skills:
            if not skill.globs:
                continue
            for file_path in file_paths:
                if any(fnmatch.fnmatch(file_path, g) for g in skill.globs):
                    relevant.append(skill)
                    break
        return relevant

    def build_system_context(self, active_files: list[str] | None = None) -> str:
        """Build the context block to inject into the system prompt.

        Args:
            active_files: List of active files to filter skills by glob.

        Returns:
            String with the complete context to inject, or "" if there is nothing.
        """
        parts: list[str] = []

        # 1. Project context (.architect.md) -- ALWAYS present
        if self._project_context:
            parts.append(f"# Project Instructions\n\n{self._project_context}")

        # 2. Relevant skills by glob -- only if there are active files
        if active_files:
            relevant = self.get_relevant_skills(active_files)
            for skill in relevant:
                parts.append(
                    f"# Skill: {skill.name}\n"
                    f"{skill.description}\n\n{skill.content}"
                )

        return "\n\n---\n\n".join(parts) if parts else ""
