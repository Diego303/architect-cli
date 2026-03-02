"""
Skills Installer -- Installs, creates and manages skills (v4-A3).

Supports:
- Installation from GitHub repos (sparse checkout)
- Creation of local skills with template
- Listing and uninstallation
"""

import shutil
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger()


class SkillInstaller:
    """Installs skills from GitHub repos or URLs."""

    INSTALL_DIR = ".architect/installed-skills"

    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
        self.install_dir = self.root / self.INSTALL_DIR

    def install_from_github(self, repo_spec: str) -> bool:
        """Install skill from GitHub. Format: user/repo or user/repo/path/to/skill.

        Args:
            repo_spec: Repository specification (e.g.: 'vercel/architect-skills/python-lint')

        Returns:
            True if the installation was successful.
        """
        parts = repo_spec.split("/")
        if len(parts) < 2:
            logger.error("invalid_repo_spec", spec=repo_spec)
            return False

        user_repo = f"{parts[0]}/{parts[1]}"
        skill_path = "/".join(parts[2:]) if len(parts) > 2 else ""
        skill_name = parts[-1] if len(parts) > 2 else parts[1]

        # Sparse checkout clone
        temp_dir = self.root / ".architect" / "tmp" / skill_name
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            clone_url = f"https://github.com/{user_repo}.git"
            proc = subprocess.run(
                [
                    "git", "clone", "--depth", "1", "--filter=blob:none",
                    "--sparse", clone_url, str(temp_dir),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                logger.error(
                    "git_clone_failed",
                    repo=user_repo,
                    stderr=proc.stderr[:200],
                )
                return False

            if skill_path:
                subprocess.run(
                    [
                        "git", "-C", str(temp_dir),
                        "sparse-checkout", "set", skill_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            # Copy skill to installation directory
            source = temp_dir / skill_path if skill_path else temp_dir
            dest = self.install_dir / skill_name
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True, exist_ok=True)

            # Copy SKILL.md and relevant files
            skill_md = source / "SKILL.md"
            if skill_md.exists():
                shutil.copy2(skill_md, dest / "SKILL.md")
                # Copy scripts/ if it exists
                scripts_dir = source / "scripts"
                if scripts_dir.exists():
                    shutil.copytree(scripts_dir, dest / "scripts")
                logger.info("skill_installed", name=skill_name, source=repo_spec)
                return True
            else:
                logger.error("no_skill_md", source=str(source))
                return False

        except subprocess.TimeoutExpired:
            logger.error("git_clone_timeout", repo=user_repo)
            return False
        except Exception as e:
            logger.error("skill_install_error", error=str(e))
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_local(self, name: str) -> Path:
        """Create a local skill with template.

        Args:
            name: Name of the skill to create.

        Returns:
            Path to the created skill directory.
        """
        skill_dir = self.root / ".architect" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            skill_md.write_text(
                f"---\n"
                f"name: {name}\n"
                f'description: "TODO: Describe this skill"\n'
                f"globs: []\n"
                f"---\n\n"
                f"# {name}\n\n"
                f"Instructions for the agent here.\n",
                encoding="utf-8",
            )
        return skill_dir

    def list_installed(self) -> list[dict[str, str]]:
        """List installed skills (local and installed).

        Returns:
            List of dicts with name, source, path.
        """
        skills: list[dict[str, str]] = []
        for skills_base in [
            self.root / ".architect/skills",
            self.root / ".architect/installed-skills",
        ]:
            if not skills_base.exists():
                continue
            for skill_dir in sorted(skills_base.iterdir()):
                if (skill_dir / "SKILL.md").exists():
                    source = "local" if skills_base.name == "skills" else "installed"
                    skills.append({
                        "name": skill_dir.name,
                        "source": source,
                        "path": str(skill_dir),
                    })
        return skills

    def uninstall(self, name: str) -> bool:
        """Uninstall a skill.

        Args:
            name: Name of the skill to uninstall.

        Returns:
            True if the skill was found and removed.
        """
        path = self.install_dir / name
        if path.exists():
            shutil.rmtree(path)
            logger.info("skill_uninstalled", name=name)
            return True
        return False
