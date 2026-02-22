"""
Guardrails Engine — Capa de seguridad determinista para el agente.

v4-A2: Los guardrails se evalúan ANTES que los hooks de usuario y son
reglas DETERMINISTAS que no dependen del LLM ni pueden ser desactivadas.

Funciones:
- check_file_access: Proteger archivos sensibles (.env, *.pem, etc.)
- check_command: Bloquear comandos peligrosos (rm -rf /, git push --force, etc.)
- check_edit_limits: Limitar archivos/líneas modificados
- check_code_rules: Escanear contenido escrito contra patrones regex
- run_quality_gates: Ejecutar checks al completar (lint, tests, typecheck)

Invariantes:
- Los guardrails NUNCA rompen el loop (retornan tuplas allowed/reason)
- Los quality gates se ejecutan como subprocesses con timeout
- Todo se logea con structlog
"""

import fnmatch
import os
import re
import subprocess
from pathlib import Path

import structlog

from ..config.schema import GuardrailsConfig

logger = structlog.get_logger()

__all__ = [
    "GuardrailsEngine",
]


class GuardrailsEngine:
    """Evalúa guardrails antes de permitir acciones del agente.

    Los guardrails son la primera línea de defensa: se evalúan ANTES
    que los hooks de usuario en el ExecutionEngine.

    State tracking:
    - _files_modified: set de archivos modificados durante la sesión
    - _lines_changed: total acumulado de líneas cambiadas
    - _commands_executed: total de comandos ejecutados
    - _edits_since_last_test: contador para require_test_after_edit
    """

    def __init__(self, config: GuardrailsConfig, workspace_root: str) -> None:
        """Inicializa el engine de guardrails.

        Args:
            config: Configuración de guardrails desde YAML.
            workspace_root: Directorio raíz del workspace.
        """
        self.config = config
        self.workspace_root = workspace_root
        self._files_modified: set[str] = set()
        self._lines_changed: int = 0
        self._commands_executed: int = 0
        self._edits_since_last_test: int = 0
        self.log = logger.bind(component="guardrails")

    def check_file_access(self, file_path: str, action: str) -> tuple[bool, str]:
        """Verifica si un archivo está protegido.

        Args:
            file_path: Path del archivo a acceder.
            action: Tipo de acción ('write_file', 'edit_file', 'delete_file').

        Returns:
            Tupla (allowed, reason). Si allowed=False, reason explica por qué.
        """
        for pattern in self.config.protected_files:
            if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(
                Path(file_path).name, pattern
            ):
                reason = f"Archivo protegido por guardrail: {file_path} (patrón: {pattern})"
                self.log.warning("guardrail.file_blocked", file=file_path, pattern=pattern)
                return False, reason
        return True, ""

    def check_command(self, command: str) -> tuple[bool, str]:
        """Verifica si un comando está bloqueado.

        Args:
            command: Comando shell a verificar.

        Returns:
            Tupla (allowed, reason).
        """
        for pattern in self.config.blocked_commands:
            try:
                if re.search(pattern, command, re.IGNORECASE):
                    reason = f"Comando bloqueado por guardrail: coincide con '{pattern}'"
                    self.log.warning("guardrail.command_blocked", command=command[:60], pattern=pattern)
                    return False, reason
            except re.error:
                self.log.warning("guardrail.invalid_regex", pattern=pattern)
                continue

        if (
            self.config.max_commands_executed is not None
            and self._commands_executed >= self.config.max_commands_executed
        ):
            reason = (
                f"Límite de comandos alcanzado ({self.config.max_commands_executed}). "
                "El guardrail impide ejecutar más comandos."
            )
            self.log.warning("guardrail.commands_limit", count=self._commands_executed)
            return False, reason

        return True, ""

    def check_edit_limits(
        self, file_path: str, lines_added: int = 0, lines_removed: int = 0
    ) -> tuple[bool, str]:
        """Verifica límites de archivos/líneas modificados.

        Args:
            file_path: Archivo modificado.
            lines_added: Líneas añadidas en esta edición.
            lines_removed: Líneas eliminadas en esta edición.

        Returns:
            Tupla (allowed, reason).
        """
        self._files_modified.add(file_path)
        self._lines_changed += lines_added + lines_removed

        if (
            self.config.max_files_modified is not None
            and len(self._files_modified) > self.config.max_files_modified
        ):
            reason = (
                f"Límite de archivos modificados alcanzado "
                f"({self.config.max_files_modified}). Para proteger el codebase, "
                "el guardrail impide tocar más archivos."
            )
            self.log.warning(
                "guardrail.files_limit",
                count=len(self._files_modified),
                limit=self.config.max_files_modified,
            )
            return False, reason

        if (
            self.config.max_lines_changed is not None
            and self._lines_changed > self.config.max_lines_changed
        ):
            reason = (
                f"Límite de líneas cambiadas alcanzado "
                f"({self.config.max_lines_changed}). El guardrail impide "
                "cambios adicionales."
            )
            self.log.warning(
                "guardrail.lines_limit",
                count=self._lines_changed,
                limit=self.config.max_lines_changed,
            )
            return False, reason

        return True, ""

    def check_code_rules(self, content: str, file_path: str) -> list[tuple[str, str]]:
        """Escanea contenido escrito contra code_rules.

        Args:
            content: Contenido del archivo escrito.
            file_path: Path del archivo (para logging).

        Returns:
            Lista de (severity, message) para cada violación encontrada.
        """
        violations: list[tuple[str, str]] = []
        for rule in self.config.code_rules:
            try:
                if re.search(rule.pattern, content):
                    violations.append((rule.severity, rule.message))
                    self.log.info(
                        "guardrail.code_rule_violation",
                        file=file_path,
                        severity=rule.severity,
                        pattern=rule.pattern,
                    )
            except re.error:
                self.log.warning("guardrail.invalid_rule_regex", pattern=rule.pattern)
                continue
        return violations

    def record_command(self) -> None:
        """Registra que se ejecutó un comando."""
        self._commands_executed += 1

    def record_edit(self) -> None:
        """Registra una edición para tracking de require_test."""
        self._edits_since_last_test += 1

    def should_force_test(self) -> bool:
        """True si require_test_after_edit y hay edits pendientes."""
        return self.config.require_test_after_edit and self._edits_since_last_test > 0

    def reset_test_counter(self) -> None:
        """Resetea el contador de edits desde último test."""
        self._edits_since_last_test = 0

    def run_quality_gates(self) -> list[dict]:
        """Ejecuta quality gates. Se llama cuando el agente declara completado.

        Returns:
            Lista de dicts con keys: name, passed, required, output, error.
        """
        results: list[dict] = []
        for gate in self.config.quality_gates:
            try:
                proc = subprocess.run(
                    gate.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=gate.timeout,
                    cwd=self.workspace_root,
                )
                passed = proc.returncode == 0
                results.append({
                    "name": gate.name,
                    "passed": passed,
                    "required": gate.required,
                    "output": proc.stdout[-500:] if not passed else "",
                    "error": proc.stderr[-300:] if not passed else "",
                })
                self.log.info(
                    "guardrail.quality_gate",
                    name=gate.name,
                    passed=passed,
                    required=gate.required,
                )
            except subprocess.TimeoutExpired:
                results.append({
                    "name": gate.name,
                    "passed": False,
                    "required": gate.required,
                    "output": f"Timeout después de {gate.timeout}s",
                    "error": "",
                })
                self.log.warning("guardrail.quality_gate_timeout", name=gate.name)
        return results
