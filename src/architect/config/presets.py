"""
Preset Configs — Templates de configuración para inicializar proyectos.

v4-D5: Permite inicializar un proyecto con configuraciones predefinidas
según el stack tecnológico o perfil de seguridad deseado.

Presets disponibles:
- python: Configuración para proyectos Python (pytest, ruff, mypy)
- node-react: Configuración para proyectos Node.js/React
- ci: Configuración mínima para CI/CD headless
- paranoid: Configuración con máxima seguridad y guardrails estrictos
- yolo: Configuración mínima sin restricciones
"""

from pathlib import Path

import structlog

logger = structlog.get_logger()

__all__ = [
    "PresetManager",
    "AVAILABLE_PRESETS",
]

AVAILABLE_PRESETS = frozenset({"python", "node-react", "ci", "paranoid", "yolo"})

# ── Template Contents ────────────────────────────────────────────────────────

PRESET_TEMPLATES: dict[str, dict[str, str]] = {
    "python": {
        ".architect.md": (
            "# Project Instructions\n\n"
            "This is a Python project.\n\n"
            "## Conventions\n"
            "- Use Python 3.12+ features\n"
            "- Follow PEP 8 with black formatting (100 char line width)\n"
            "- Use type hints on all public functions\n"
            "- Use structlog for logging (never print())\n"
            "- Write tests with pytest for all new functionality\n"
            "- Use Pydantic v2 for data validation\n\n"
            "## File Structure\n"
            "- Source code in `src/`\n"
            "- Tests in `tests/`\n"
            "- Configuration in project root\n\n"
            "## Testing\n"
            "- Run tests: `pytest tests/ -v`\n"
            "- Run linter: `ruff check src/`\n"
            "- Run formatter: `black --check .`\n"
            "- Run type checker: `mypy src/`\n"
        ),
        "config.yaml": (
            "# architect configuration — Python project\n"
            "llm:\n"
            "  model: claude-sonnet-4-20250514\n"
            "  stream: true\n\n"
            "agents:\n"
            "  build:\n"
            "    confirm_mode: confirm-sensitive\n"
            "    max_steps: 30\n\n"
            "hooks:\n"
            "  post_tool_use:\n"
            "    - name: python-format\n"
            '      matcher: "write_file|edit_file"\n'
            "      file_patterns: ['*.py']\n"
            '      command: "ruff format $ARCHITECT_FILE_PATH --quiet 2>/dev/null || true"\n'
            "      timeout: 10\n"
            "    - name: python-lint\n"
            '      matcher: "write_file|edit_file"\n'
            "      file_patterns: ['*.py']\n"
            '      command: "ruff check $ARCHITECT_FILE_PATH --no-fix 2>/dev/null || true"\n'
            "      timeout: 10\n\n"
            "guardrails:\n"
            "  enabled: true\n"
            "  protected_files:\n"
            '    - ".env"\n'
            '    - ".env.*"\n'
            '    - "*.pem"\n'
            '    - "*.key"\n'
            "  quality_gates:\n"
            "    - name: lint\n"
            '      command: "ruff check src/"\n'
            "      required: true\n"
            "      timeout: 30\n"
            "    - name: tests\n"
            '      command: "pytest tests/ -q --tb=short"\n'
            "      required: true\n"
            "      timeout: 120\n\n"
            "memory:\n"
            "  enabled: true\n\n"
            "sessions:\n"
            "  auto_save: true\n"
        ),
    },
    "node-react": {
        ".architect.md": (
            "# Project Instructions\n\n"
            "This is a Node.js/React project.\n\n"
            "## Conventions\n"
            "- Use TypeScript with strict mode\n"
            "- Follow ESLint + Prettier formatting\n"
            "- Use functional React components with hooks\n"
            "- Write tests with Jest/Vitest\n"
            "- Use path aliases (@/) for imports\n\n"
            "## File Structure\n"
            "- Source code in `src/`\n"
            "- Components in `src/components/`\n"
            "- Tests co-located with source (*.test.ts)\n"
            "- API routes in `src/api/` or `src/pages/api/`\n\n"
            "## Testing\n"
            "- Run tests: `npm test`\n"
            "- Run linter: `npm run lint`\n"
            "- Run type check: `npx tsc --noEmit`\n"
            "- Run build: `npm run build`\n"
        ),
        "config.yaml": (
            "# architect configuration — Node.js/React project\n"
            "llm:\n"
            "  model: claude-sonnet-4-20250514\n"
            "  stream: true\n\n"
            "agents:\n"
            "  build:\n"
            "    confirm_mode: confirm-sensitive\n"
            "    max_steps: 30\n\n"
            "hooks:\n"
            "  post_tool_use:\n"
            "    - name: prettier-format\n"
            '      matcher: "write_file|edit_file"\n'
            "      file_patterns: ['*.ts', '*.tsx', '*.js', '*.jsx']\n"
            '      command: "npx prettier --write $ARCHITECT_FILE_PATH 2>/dev/null || true"\n'
            "      timeout: 10\n\n"
            "guardrails:\n"
            "  enabled: true\n"
            "  protected_files:\n"
            '    - ".env"\n'
            '    - ".env.*"\n'
            '    - "*.pem"\n'
            "  quality_gates:\n"
            "    - name: lint\n"
            '      command: "npm run lint"\n'
            "      required: true\n"
            "      timeout: 30\n"
            "    - name: typecheck\n"
            '      command: "npx tsc --noEmit"\n'
            "      required: false\n"
            "      timeout: 60\n"
            "    - name: tests\n"
            '      command: "npm test -- --watchAll=false"\n'
            "      required: true\n"
            "      timeout: 120\n\n"
            "memory:\n"
            "  enabled: true\n\n"
            "sessions:\n"
            "  auto_save: true\n"
        ),
    },
    "ci": {
        ".architect.md": (
            "# CI/CD Agent Instructions\n\n"
            "You are running in a CI/CD environment.\n\n"
            "## Rules\n"
            "- Execute tasks autonomously without user interaction\n"
            "- Do not ask for confirmation — use yolo mode\n"
            "- Focus on the task and exit cleanly\n"
            "- All output should be structured (JSON when possible)\n"
            "- Keep changes minimal and focused\n"
        ),
        "config.yaml": (
            "# architect configuration — CI/CD headless\n"
            "llm:\n"
            "  model: claude-sonnet-4-20250514\n"
            "  stream: false\n\n"
            "agents:\n"
            "  build:\n"
            "    confirm_mode: yolo\n"
            "    max_steps: 50\n\n"
            "guardrails:\n"
            "  enabled: true\n"
            "  protected_files:\n"
            '    - ".env"\n'
            '    - "*.pem"\n'
            '    - "*.key"\n'
            "  blocked_commands:\n"
            "    - 'git\\s+push'\n"
            "    - 'npm\\s+publish'\n"
            "  max_files_modified: 20\n\n"
            "sessions:\n"
            "  auto_save: false\n\n"
            "memory:\n"
            "  enabled: false\n"
        ),
    },
    "paranoid": {
        ".architect.md": (
            "# Project Instructions — Paranoid Mode\n\n"
            "## Security First\n"
            "- NEVER write secrets, API keys, or credentials to any file\n"
            "- ALWAYS validate all inputs\n"
            "- NEVER use eval(), exec(), pickle, or os.system()\n"
            "- ALWAYS use parameterized queries for database operations\n"
            "- NEVER commit to main/master directly\n\n"
            "## Quality\n"
            "- ALL code must have tests\n"
            "- ALL public functions must have type hints\n"
            "- ALL functions must be < 50 lines\n"
            "- Cyclomatic complexity must be < 10 per function\n"
        ),
        "config.yaml": (
            "# architect configuration — Paranoid mode (maximum security)\n"
            "llm:\n"
            "  model: claude-sonnet-4-20250514\n"
            "  stream: true\n\n"
            "agents:\n"
            "  build:\n"
            "    confirm_mode: confirm-all\n"
            "    max_steps: 20\n\n"
            "guardrails:\n"
            "  enabled: true\n"
            "  protected_files:\n"
            '    - ".env"\n'
            '    - ".env.*"\n'
            '    - "*.pem"\n'
            '    - "*.key"\n'
            '    - "*.secret"\n'
            '    - "credentials.*"\n'
            '    - "secrets.*"\n'
            '    - ".git/config"\n'
            "  blocked_commands:\n"
            "    - 'rm\\s+-[rf]+\\s+/'\n"
            "    - 'curl.*\\|\\s*(sh|bash)'\n"
            "    - 'git\\s+push.*--force.*(main|master)'\n"
            "    - 'DROP\\s+(TABLE|DATABASE)'\n"
            "    - 'TRUNCATE\\s+TABLE'\n"
            "  max_files_modified: 10\n"
            "  max_lines_changed: 500\n"
            "  max_commands_executed: 30\n"
            "  require_test_after_edit: true\n"
            "  quality_gates:\n"
            "    - name: lint\n"
            '      command: "ruff check src/ --select ALL"\n'
            "      required: true\n"
            "      timeout: 30\n"
            "    - name: tests\n"
            '      command: "pytest tests/ -q --tb=short"\n'
            "      required: true\n"
            "      timeout: 120\n"
            "    - name: typecheck\n"
            '      command: "mypy src/ --strict"\n'
            "      required: true\n"
            "      timeout: 60\n"
            "  code_rules:\n"
            "    - pattern: 'eval\\('\n"
            '      message: "Prohibido usar eval(). Usa alternativas seguras."\n'
            "      severity: block\n"
            "    - pattern: 'import\\s+pickle'\n"
            '      message: "Prohibido importar pickle por riesgo de seguridad."\n'
            "      severity: block\n"
            "    - pattern: 'os\\.system\\('\n"
            '      message: "Prohibido usar os.system(). Usa subprocess."\n'
            "      severity: block\n"
            "    - pattern: '\\bprint\\s*\\('\n"
            '      message: "Usa el módulo logging en vez de print()."\n'
            "      severity: warn\n\n"
            "memory:\n"
            "  enabled: true\n\n"
            "auto_review:\n"
            "  enabled: true\n"
            "  max_fix_passes: 2\n\n"
            "sessions:\n"
            "  auto_save: true\n"
        ),
    },
    "yolo": {
        ".architect.md": (
            "# Project Instructions\n\n"
            "No restrictions. Execute tasks as efficiently as possible.\n"
        ),
        "config.yaml": (
            "# architect configuration — YOLO mode (no restrictions)\n"
            "llm:\n"
            "  model: claude-sonnet-4-20250514\n"
            "  stream: true\n\n"
            "agents:\n"
            "  build:\n"
            "    confirm_mode: yolo\n"
            "    max_steps: 100\n\n"
            "guardrails:\n"
            "  enabled: false\n\n"
            "memory:\n"
            "  enabled: false\n\n"
            "sessions:\n"
            "  auto_save: false\n"
        ),
    },
}


class PresetManager:
    """Gestiona presets de configuración para inicializar proyectos.

    Los presets son templates de configuración que incluyen:
    - .architect.md (instrucciones del proyecto)
    - config.yaml (configuración de architect)

    Se copian al directorio del proyecto, creando la estructura necesaria.
    """

    def __init__(self, workspace_root: str) -> None:
        """Inicializa el manager.

        Args:
            workspace_root: Directorio raíz del proyecto.
        """
        self.root = Path(workspace_root)
        self.log = logger.bind(component="presets")

    def apply_preset(
        self, preset_name: str, overwrite: bool = False
    ) -> list[str]:
        """Aplica un preset al proyecto.

        Args:
            preset_name: Nombre del preset (python, node-react, ci, paranoid, yolo).
            overwrite: Si True, sobrescribe archivos existentes.

        Returns:
            Lista de archivos creados/actualizados.

        Raises:
            ValueError: Si el preset no existe.
        """
        if preset_name not in AVAILABLE_PRESETS:
            raise ValueError(
                f"Preset '{preset_name}' no existe. "
                f"Disponibles: {', '.join(sorted(AVAILABLE_PRESETS))}"
            )

        templates = PRESET_TEMPLATES[preset_name]
        created_files: list[str] = []

        for filename, content in templates.items():
            target = self.root / filename
            if target.exists() and not overwrite:
                self.log.info(
                    "preset.skip_existing",
                    file=filename,
                    preset=preset_name,
                )
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            created_files.append(filename)
            self.log.info(
                "preset.file_created",
                file=filename,
                preset=preset_name,
            )

        # Crear directorio .architect si no existe
        architect_dir = self.root / ".architect"
        architect_dir.mkdir(parents=True, exist_ok=True)

        self.log.info(
            "preset.applied",
            preset=preset_name,
            files_created=len(created_files),
        )

        return created_files

    def list_presets(self) -> list[dict[str, str]]:
        """Lista presets disponibles con descripción.

        Returns:
            Lista de {name, description} para cada preset.
        """
        descriptions = {
            "python": "Python project (pytest, ruff, mypy, black)",
            "node-react": "Node.js/React project (TypeScript, ESLint, Prettier)",
            "ci": "CI/CD headless mode (minimal, autonomous)",
            "paranoid": "Maximum security (strict guardrails, confirm-all, code rules)",
            "yolo": "No restrictions (yolo mode, no guardrails)",
        }
        return [
            {"name": name, "description": descriptions.get(name, "")}
            for name in sorted(AVAILABLE_PRESETS)
        ]

    def get_preset_files(self, preset_name: str) -> dict[str, str]:
        """Obtiene los archivos de un preset sin aplicarlos.

        Args:
            preset_name: Nombre del preset.

        Returns:
            Dict de {filename: content}.

        Raises:
            ValueError: Si el preset no existe.
        """
        if preset_name not in AVAILABLE_PRESETS:
            raise ValueError(
                f"Preset '{preset_name}' no existe. "
                f"Disponibles: {', '.join(sorted(AVAILABLE_PRESETS))}"
            )
        return dict(PRESET_TEMPLATES[preset_name])
