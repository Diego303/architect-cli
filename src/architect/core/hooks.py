"""
Hook System — Sistema completo de hooks para el lifecycle del agente.

v4-A1: Reemplaza el sistema PostEditHooks de v3-M4 con un sistema general
de hooks que cubre todo el lifecycle: pre/post tool, pre/post LLM, session,
agent_complete, budget_warning, context_compress, on_error.

Los hooks se ejecutan como subprocesses (shell=True) y reciben contexto
vía env vars (ARCHITECT_EVENT, ARCHITECT_TOOL_NAME, etc.) y stdin JSON.

Protocolo de exit codes:
- Exit 0  = ALLOW  (permitir la acción, opcionalmente con contexto adicional)
- Exit 2  = BLOCK  (bloquear la acción, stderr = razón)
- Otro    = Error del hook (se logea WARNING, no bloquea)

Invariantes:
- Los hooks NUNCA rompen el loop (errores → log + retorno ALLOW)
- El timeout de cada hook es configurable (default 10s)
- Los hooks async se ejecutan en background sin esperar resultado
- Si un pre-hook bloquea, no se ejecutan los hooks siguientes del mismo evento
"""

import fnmatch
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()

__all__ = [
    "HookEvent",
    "HookDecision",
    "HookResult",
    "HookConfig",
    "HooksRegistry",
    "HookExecutor",
]


class HookEvent(Enum):
    """Eventos del lifecycle donde se pueden inyectar hooks."""

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    ON_ERROR = "on_error"
    BUDGET_WARNING = "budget_warning"
    CONTEXT_COMPRESS = "context_compress"
    AGENT_COMPLETE = "agent_complete"


class HookDecision(Enum):
    """Decisión de un pre-hook."""

    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"


@dataclass
class HookResult:
    """Resultado de ejecutar un hook."""

    decision: HookDecision = HookDecision.ALLOW
    reason: str | None = None
    additional_context: str | None = None
    updated_input: dict[str, Any] | None = None
    duration_ms: float = 0


@dataclass
class HookConfig:
    """Configuración de un hook individual.

    Attributes:
        command: Comando shell a ejecutar.
        matcher: Regex/glob del tool name (para tool hooks). '*' matchea todo.
        file_patterns: Filtro por extensión de archivo.
        timeout: Segundos máx de ejecución.
        is_async: Si True, el hook se ejecuta en background sin bloquear.
        enabled: Si False, el hook se ignora.
        name: Nombre descriptivo del hook.
    """

    command: str
    matcher: str = "*"
    file_patterns: list[str] = field(default_factory=list)
    timeout: int = 10
    is_async: bool = False
    enabled: bool = True
    name: str = ""


@dataclass
class HooksRegistry:
    """Registro completo de hooks por evento."""

    hooks: dict[HookEvent, list[HookConfig]] = field(default_factory=dict)

    def get_hooks(self, event: HookEvent) -> list[HookConfig]:
        """Retorna los hooks activos para un evento.

        Args:
            event: Evento del lifecycle.

        Returns:
            Lista de HookConfig habilitados para ese evento.
        """
        return [h for h in self.hooks.get(event, []) if h.enabled]

    def has_hooks(self) -> bool:
        """Retorna True si hay al menos un hook registrado."""
        return any(hooks for hooks in self.hooks.values())


class HookExecutor:
    """Ejecuta hooks inyectando contexto vía env vars y stdin.

    El executor es el punto central de ejecución de hooks. Se encarga de:
    - Construir el environment con ARCHITECT_* variables
    - Ejecutar el subprocess con timeout
    - Interpretar el exit code y stdout/stderr
    - Filtrar hooks por matcher y file_patterns
    - Manejar hooks async (background)
    """

    def __init__(self, registry: HooksRegistry, workspace_root: str) -> None:
        """Inicializa el executor.

        Args:
            registry: Registro de hooks por evento.
            workspace_root: Directorio raíz del workspace para CWD.
        """
        self.registry = registry
        self.workspace_root = workspace_root
        self.log = logger.bind(component="hooks")

    def _build_env(self, event: HookEvent, context: dict[str, Any]) -> dict[str, str]:
        """Construye variables de entorno para el hook.

        Inyecta ARCHITECT_EVENT, ARCHITECT_WORKSPACE y cada clave del
        contexto como ARCHITECT_{KEY.upper()}.

        Args:
            event: Evento que disparó el hook.
            context: Diccionario de contexto con datos del evento.

        Returns:
            Dict de env vars para subprocess.
        """
        env = os.environ.copy()
        env["ARCHITECT_EVENT"] = event.value
        env["ARCHITECT_WORKSPACE"] = self.workspace_root
        for key, value in context.items():
            env_key = f"ARCHITECT_{key.upper()}"
            env[env_key] = str(value) if value is not None else ""
        return env

    def execute_hook(
        self,
        hook: HookConfig,
        event: HookEvent,
        context: dict[str, Any],
        stdin_data: dict[str, Any] | None = None,
    ) -> HookResult:
        """Ejecuta un hook individual.

        Args:
            hook: Configuración del hook a ejecutar.
            event: Evento que disparó el hook.
            context: Diccionario de contexto para env vars.
            stdin_data: Datos JSON opcionales para pasar por stdin.

        Returns:
            HookResult con la decisión y datos asociados.
        """
        start = time.monotonic()
        env = self._build_env(event, context)
        stdin_json = json.dumps(stdin_data) if stdin_data else ""

        try:
            proc = subprocess.run(
                hook.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=hook.timeout,
                cwd=self.workspace_root,
                env=env,
                input=stdin_json,
            )
            duration = (time.monotonic() - start) * 1000

            if proc.returncode == 0:
                result = self._parse_allow_output(proc.stdout)
                result.duration_ms = duration
                return result
            elif proc.returncode == 2:
                reason = proc.stderr.strip() or f"Hook '{hook.name}' bloqueó la acción"
                return HookResult(
                    decision=HookDecision.BLOCK,
                    reason=reason,
                    duration_ms=duration,
                )
            else:
                self.log.warning(
                    "hook.error",
                    hook=hook.name,
                    exit_code=proc.returncode,
                    stderr=proc.stderr[:200],
                )
                return HookResult(duration_ms=duration)

        except subprocess.TimeoutExpired:
            self.log.warning("hook.timeout", hook=hook.name, timeout=hook.timeout)
            return HookResult(duration_ms=hook.timeout * 1000)
        except Exception as e:
            self.log.error("hook.exception", hook=hook.name, error=str(e))
            return HookResult()

    def _parse_allow_output(self, stdout: str) -> HookResult:
        """Parsea stdout JSON de un hook que permite la acción.

        Si stdout es JSON con 'updatedInput', retorna MODIFY.
        Si tiene 'additionalContext', lo adjunta.
        Si no es JSON, lo trata como contexto adicional de texto.

        Args:
            stdout: Salida estándar del hook.

        Returns:
            HookResult con ALLOW o MODIFY.
        """
        if not stdout.strip():
            return HookResult(decision=HookDecision.ALLOW)
        try:
            data = json.loads(stdout)
            if "updatedInput" in data:
                return HookResult(
                    decision=HookDecision.MODIFY,
                    updated_input=data["updatedInput"],
                    additional_context=data.get("additionalContext"),
                )
            return HookResult(
                decision=HookDecision.ALLOW,
                additional_context=data.get("additionalContext"),
            )
        except json.JSONDecodeError:
            return HookResult(
                decision=HookDecision.ALLOW,
                additional_context=stdout.strip(),
            )

    def run_event(
        self,
        event: HookEvent,
        context: dict[str, Any],
        stdin_data: dict[str, Any] | None = None,
    ) -> list[HookResult]:
        """Ejecuta todos los hooks de un evento.

        Filtra hooks por matcher (para tool hooks) y file_patterns.
        Si un hook bloquea, no se ejecutan los siguientes.
        Los hooks async se ejecutan en background.

        Args:
            event: Evento del lifecycle.
            context: Diccionario de contexto con datos del evento.
            stdin_data: Datos JSON opcionales para pasar por stdin.

        Returns:
            Lista de HookResult (uno por hook ejecutado).
        """
        hooks = self.registry.get_hooks(event)
        results: list[HookResult] = []

        for hook in hooks:
            # Filtro por matcher (para tool hooks)
            if hook.matcher != "*" and "tool_name" in context:
                if not re.match(hook.matcher, context["tool_name"]):
                    continue

            # Filtro por file_patterns
            if hook.file_patterns and "file_path" in context:
                file_path = context["file_path"]
                if not any(fnmatch.fnmatch(file_path, p) for p in hook.file_patterns):
                    continue

            if hook.is_async:
                threading.Thread(
                    target=self.execute_hook,
                    args=(hook, event, context, stdin_data),
                    daemon=True,
                ).start()
                results.append(HookResult())
            else:
                result = self.execute_hook(hook, event, context, stdin_data)
                results.append(result)

                # Si un pre-hook bloquea, no ejecutar los siguientes
                if result.decision == HookDecision.BLOCK:
                    break

        return results

    # ── Backward compatibility with PostEditHooks (v3-M4) ─────────────

    def run_post_edit(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """Ejecuta post-edit hooks para backward compatibility con v3-M4.

        Esto permite que el código existente que llamaba a
        PostEditHooks.run_for_tool() siga funcionando con el nuevo sistema.

        Args:
            tool_name: Nombre del tool ejecutado.
            args: Argumentos del tool.

        Returns:
            Texto con resultados concatenados, o None si no aplican.
        """
        edit_tools = frozenset({"edit_file", "write_file", "apply_patch"})
        if tool_name not in edit_tools:
            return None

        file_path = args.get("path")
        if not file_path:
            return None

        context: dict[str, Any] = {
            "tool_name": tool_name,
            "file_path": str(file_path),
        }
        results = self.run_event(HookEvent.POST_TOOL_USE, context)

        # Recolectar contexto adicional de hooks que produjeron output
        outputs: list[str] = []
        for result in results:
            if result.additional_context:
                outputs.append(result.additional_context)

        return "\n".join(outputs) if outputs else None
