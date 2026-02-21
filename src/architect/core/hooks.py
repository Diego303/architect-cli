"""
Post-Edit Hooks - Verificación automática después de editar archivos.

v3-M4: Cuando el agente edita un archivo, estos hooks se ejecutan automáticamente
(lint, typecheck, tests). El resultado vuelve al LLM para que pueda auto-corregir.

Invariantes:
- Los hooks NUNCA rompen el loop (errores → log + retorno None)
- El timeout de cada hook es configurable (default 15s)
- Los hooks se filtran por file_pattern (ej: "*.py", "*.ts")
"""

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class HookRunResult:
    """Resultado de la ejecución de un hook post-edit."""

    hook_name: str
    success: bool
    output: str
    exit_code: int


class PostEditHooks:
    """Ejecuta hooks automáticamente después de que el agente edite un archivo.

    Los resultados se devuelven como texto adicional en el output del tool result,
    para que el LLM pueda leerlos y auto-corregir si hay errores.

    Ejemplo de uso:
        hooks = PostEditHooks(config.hooks.post_edit, workspace_root)
        extra_output = hooks.run_for_file("src/main.py")
        # extra_output: "Hook python-lint: OK\\nHook python-typecheck: 1 error..."
    """

    # Nombres de tools de edición que disparan los hooks
    EDIT_TOOLS = frozenset({"edit_file", "write_file", "apply_patch"})

    def __init__(self, hooks: list, workspace_root: Path) -> None:
        """Inicializa los post-edit hooks.

        Args:
            hooks: Lista de HookConfig (desde config.hooks.post_edit)
            workspace_root: Directorio raíz del workspace para CWD y PATH validation
        """
        # Filtrar hooks deshabilitados
        self.hooks = [h for h in hooks if getattr(h, "enabled", True)]
        self.root = workspace_root
        self.log = logger.bind(component="post_edit_hooks")

    def run_for_tool(self, tool_name: str, args: dict) -> str | None:
        """Ejecuta hooks si el tool es una operación de edición.

        Args:
            tool_name: Nombre del tool ejecutado
            args: Argumentos del tool

        Returns:
            Texto con los resultados de los hooks, o None si no aplican
        """
        if tool_name not in self.EDIT_TOOLS:
            return None

        file_path = args.get("path")
        if not file_path:
            return None

        return self.run_for_file(str(file_path))

    def run_for_file(self, file_path: str) -> str | None:
        """Ejecuta los hooks que aplican al archivo editado.

        Args:
            file_path: Path del archivo editado (relativo o absoluto)

        Returns:
            Texto con los resultados concatenados, o None si ningún hook aplica
        """
        if not self.hooks:
            return None

        # Normalizar path para matching
        file_name = Path(file_path).name

        # Filtrar hooks que aplican a este archivo
        matching = [
            h for h in self.hooks
            if self._matches(file_name, file_path, h.file_patterns)
        ]

        if not matching:
            return None

        results: list[str] = []

        for hook in matching:
            result = self._run_hook(hook, file_path)
            if result:
                results.append(self._format_result(result))
                self.log.info(
                    "hook.executed",
                    hook=hook.name,
                    file=file_path,
                    success=result.success,
                    exit_code=result.exit_code,
                )

        if not results:
            return None

        return "\n".join(results)

    def _run_hook(self, hook, file_path: str) -> HookRunResult | None:
        """Ejecuta un hook individual.

        Args:
            hook: HookConfig con name, command, timeout
            file_path: Path del archivo editado

        Returns:
            HookRunResult o None si el hook falla de forma irrecuperable
        """
        timeout = getattr(hook, "timeout", 15)

        try:
            # Sustituir placeholder {file} en el comando con el path real
            command = hook.command.replace("{file}", file_path)

            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "ARCHITECT_EDITED_FILE": file_path},
            )

            # Combinar stdout + stderr, truncar si es muy largo
            combined = (result.stdout + result.stderr).strip()
            combined = self._truncate(combined, max_chars=1000)

            return HookRunResult(
                hook_name=hook.name,
                success=result.returncode == 0,
                output=combined,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            self.log.warning(
                "hook.timeout",
                hook=hook.name,
                file=file_path,
                timeout=timeout,
            )
            return HookRunResult(
                hook_name=hook.name,
                success=False,
                output=f"Timeout después de {timeout}s",
                exit_code=-1,
            )

        except Exception as e:
            self.log.warning("hook.error", hook=hook.name, error=str(e))
            return None

    def _matches(self, file_name: str, file_path: str, patterns: list[str]) -> bool:
        """Comprueba si el archivo coincide con alguno de los patrones.

        Acepta tanto el nombre del archivo (ej: "main.py") como el path
        completo para patrones con directorio (ej: "src/*.py").

        Args:
            file_name: Solo el nombre del archivo
            file_path: Path completo o relativo
            patterns: Lista de patrones glob (ej: ["*.py", "src/**/*.ts"])
        """
        for pattern in patterns:
            if fnmatch.fnmatch(file_name, pattern):
                return True
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False

    def _format_result(self, result: HookRunResult) -> str:
        """Formatea el resultado de un hook para el LLM."""
        status = "OK" if result.success else f"FALLÓ (exit {result.exit_code})"
        if result.output:
            return f"[Hook {result.hook_name}: {status}]\n{result.output}"
        return f"[Hook {result.hook_name}: {status}]"

    def _truncate(self, text: str, max_chars: int = 1000) -> str:
        """Trunca texto largo preservando inicio y final."""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n...[truncado]...\n" + text[-half // 2:]
