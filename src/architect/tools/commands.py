"""
Tool run_command — Ejecución de comandos del sistema (F13).

Implementa cuatro capas de seguridad:
  1. Blocklist: patrones regex que nunca se ejecutan
  2. Clasificación dinámica: safe / dev / dangerous → política de confirmación
  3. Timeouts y output limit: evita procesos colgados o contextos saturados
  4. Directory sandboxing: cwd siempre dentro del workspace
"""

import os
import re
import subprocess
from pathlib import Path

import structlog

from ..config.schema import CommandsConfig
from ..execution.validators import PathTraversalError, validate_path
from .base import BaseTool, ToolResult
from .schemas import RunCommandArgs

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constantes de seguridad built-in
# ---------------------------------------------------------------------------

# Patrones regex que NUNCA se ejecutan (Capa 1 — blocklist dura)
BLOCKED_PATTERNS: list[str] = [
    r"\brm\s+-rf\s+/",          # rm -rf / (eliminación del sistema)
    r"\brm\s+-rf\s+~",          # rm -rf ~ (home del usuario)
    r"\bsudo\b",                 # escalada de privilegios
    r"\bsu\b",                   # cambio de usuario
    r"\bchmod\s+777\b",          # permisos universales inseguros
    r"\bcurl\b.*\|\s*(ba)?sh",   # curl | bash / curl | sh
    r"\bwget\b.*\|\s*(ba)?sh",   # wget | bash / wget | sh
    r"\bdd\b.*\bof=/dev/",       # escritura directa a dispositivos
    r">\s*/dev/sd",              # redirección a discos
    r"\bmkfs\b",                 # formatear discos
    r"\b:()\s*\{\s*:\|:&\s*\};?:", # fork bomb
    r"\bpkill\s+-9\s+-f\b",     # matar todos los procesos por nombre
    r"\bkillall\s+-9\b",        # matar todos los procesos
]

# Comandos base considerados seguros (read-only, sin efectos secundarios)
SAFE_COMMANDS: set[str] = {
    "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
    "tree", "file", "which", "echo", "pwd", "env", "date",
    "python --version", "python3 --version",
    "node --version", "npm --version",
    "pip list", "pip show", "pip freeze",
    "git status", "git log", "git diff", "git show", "git branch",
    "git remote", "git fetch",
    "go version", "cargo --version", "rustc --version",
    "java -version", "mvn --version",
    "docker --version", "docker ps",
    "kubectl version", "kubectl get",
}

# Prefijos de comandos de desarrollo (semi-seguros — herramientas de dev)
DEV_PREFIXES: set[str] = {
    "pytest", "python -m pytest",
    "python -m mypy", "mypy",
    "python -m ruff", "ruff",
    "python -m black", "black --check",
    "python -m coverage", "coverage",
    "python -m unittest",
    "npm test", "npm run", "npm ci", "npm audit",
    "yarn test", "yarn run",
    "cargo test", "cargo build", "cargo check", "cargo clippy", "cargo fmt",
    "go test", "go build", "go vet", "go fmt", "golangci-lint",
    "make", "tsc", "eslint", "prettier --check",
    "pip install", "pip install -r",
    "npm install", "yarn install",
    "mvn test", "mvn compile", "mvn package",
    "gradle test", "gradle build",
}


class RunCommandTool(BaseTool):
    """Ejecuta comandos del sistema con cuatro capas de seguridad.

    Capa 1 — Blocklist: patrones regex bloqueados permanentemente (rm -rf /, sudo, etc.).
    Capa 2 — Clasificación: safe/dev/dangerous determina la política de confirmación.
    Capa 3 — Timeouts + output limit: evita procesos colgados y contextos saturados.
    Capa 4 — Directory sandboxing: cwd siempre dentro del workspace_root.
    """

    name = "run_command"
    description = (
        "Ejecuta un comando en el shell del sistema. Útil para:\n"
        "- Ejecutar tests: pytest tests/, npm test, go test ./...\n"
        "- Verificar tipos: mypy src/, tsc --noEmit\n"
        "- Linting: ruff check ., eslint src/\n"
        "- Compilar: make build, cargo build, tsc\n"
        "- Verificar estado: git status, git log --oneline -5\n"
        "- Ejecutar scripts: python script.py, bash setup.sh\n"
        "El comando se ejecuta en el directorio del workspace (o en cwd si se especifica)."
    )
    sensitive = True  # Base: sensitive. El engine aplica clasificación dinámica.
    args_model = RunCommandArgs

    def __init__(self, workspace_root: Path, commands_config: CommandsConfig) -> None:
        self.workspace_root = workspace_root
        self.commands_config = commands_config

        # Combinar patrones y comandos built-in con los extras del config
        self._blocked_patterns: list[str] = BLOCKED_PATTERNS + list(commands_config.blocked_patterns)
        self._safe_commands: set[str] = SAFE_COMMANDS | set(commands_config.safe_commands)
        self._max_lines: int = commands_config.max_output_lines
        self._default_timeout: int = commands_config.default_timeout

        self.log = logger.bind(component="run_command_tool")

    # ------------------------------------------------------------------
    # Clasificación de sensibilidad (usada también por el engine)
    # ------------------------------------------------------------------

    def classify_sensitivity(self, command: str) -> str:
        """Clasifica el comando para la política de confirmación.

        Returns:
            'safe'      — No requiere confirmación (read-only, info-gathering)
            'dev'       — Herramientas de desarrollo (tests, linters, build)
            'dangerous' — Desconocido; siempre confirmar en modo interactivo
        """
        cmd_stripped = command.strip()

        # Verificar safe commands (match exacto de prefijo)
        if any(cmd_stripped.startswith(safe) for safe in self._safe_commands):
            return "safe"

        # Verificar dev prefixes
        if any(cmd_stripped.startswith(prefix) for prefix in DEV_PREFIXES):
            return "dev"

        return "dangerous"

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------

    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> ToolResult:
        """Ejecuta el comando con las cuatro capas de seguridad.

        Args:
            command: Comando a ejecutar (puede incluir pipes y redirecciones)
            cwd: Directorio de trabajo relativo al workspace (opcional)
            timeout: Timeout en segundos (usa default_timeout del config si es 30 y config difiere)
            env: Variables de entorno adicionales

        Returns:
            ToolResult con stdout, stderr y exit_code. Nunca lanza excepciones.
        """
        try:
            # Capa 1: Blocklist dura
            if self._is_blocked(command):
                self.log.warning("run_command.blocked", command=command[:100])
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Comando bloqueado por política de seguridad: '{command}'",
                )

            # Capa 2: allowed_only mode — rechaza 'dangerous' en execute
            sensitivity = self.classify_sensitivity(command)
            if self.commands_config.allowed_only and sensitivity == "dangerous":
                self.log.warning("run_command.allowed_only_rejected", command=command[:100])
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Modo allowed_only activo: solo se permiten comandos safe/dev. "
                        f"Comando clasificado como 'dangerous': '{command}'"
                    ),
                )

            # Capa 3: Resolver directorio de trabajo (dentro del workspace)
            work_dir = self._resolve_cwd(cwd)

            # Preparar entorno (merge con environ actual)
            proc_env = {**os.environ, **(env or {})}

            # Usar timeout del config si el caller usa el default del schema (30s)
            # y el config tiene un valor diferente
            effective_timeout = timeout if timeout != 30 else self._default_timeout

            self.log.info(
                "run_command.execute",
                command=command[:100],
                cwd=str(work_dir),
                timeout=effective_timeout,
            )

            # Ejecutar el proceso (Capa 3 — timeout, Capa 4 — cwd sandboxing)
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                env=proc_env,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                stdin=subprocess.DEVNULL,  # Headless: nunca espera input
            )

            # Truncar outputs largos para no saturar el contexto
            stdout = self._truncate(result.stdout, self._max_lines)
            stderr = self._truncate(result.stderr, max(self._max_lines // 4, 10))

            # Componer output estructurado
            parts: list[str] = []
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            parts.append(f"exit_code: {result.returncode}")

            output = "\n\n".join(parts)
            success = result.returncode == 0

            self.log.info(
                "run_command.complete",
                command=command[:100],
                exit_code=result.returncode,
                success=success,
            )

            return ToolResult(
                success=success,
                output=output,
                error=stderr if not success and stderr else None,
            )

        except subprocess.TimeoutExpired:
            self.log.warning("run_command.timeout", command=command[:100], timeout=effective_timeout)
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"El comando excedió el timeout de {effective_timeout}s: '{command}'. "
                    "Considera aumentar el timeout o dividir el comando en partes más pequeñas."
                ),
            )
        except PathTraversalError as e:
            self.log.error("run_command.path_traversal", error=str(e))
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            self.log.error("run_command.unexpected_error", error=str(e), error_type=type(e).__name__)
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado ejecutando comando: {e}",
            )

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _is_blocked(self, command: str) -> bool:
        """Verifica si el comando coincide con algún patrón bloqueado."""
        return any(re.search(pattern, command, re.IGNORECASE) for pattern in self._blocked_patterns)

    def _resolve_cwd(self, cwd: str | None) -> Path:
        """Resuelve el directorio de trabajo, garantizando que esté dentro del workspace.

        Si cwd es None, retorna workspace_root.
        Si cwd es una ruta relativa, la valida contra workspace_root.
        """
        if cwd is None:
            return self.workspace_root
        return validate_path(cwd, self.workspace_root)

    def _truncate(self, text: str, max_lines: int) -> str:
        """Trunca texto largo preservando el inicio y el final.

        Mantiene la primera mitad y el último cuarto del output
        para conservar el contexto más relevante.
        """
        if not text:
            return text
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text

        head_count = max_lines // 2
        tail_count = max_lines // 4
        omitted = len(lines) - head_count - tail_count

        head = "\n".join(lines[:head_count])
        tail = "\n".join(lines[-tail_count:])
        return f"{head}\n\n[... {omitted} líneas omitidas ...]\n\n{tail}"
