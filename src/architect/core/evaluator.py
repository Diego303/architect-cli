"""
Self-Evaluator — Evaluación automática del resultado del agente (F12).

El SelfEvaluator permite al agente revisar su propio output y, en modo
``full``, reintentar la tarea si detecta que no se completó correctamente.

Modos:
- ``basic``: Una llamada extra al LLM (~500 tokens). Si la evaluación falla,
  marca el estado como ``partial`` y reporta los problemas.
- ``full``: Hasta ``max_retries`` ciclos de evaluación + corrección. Más caro
  (N * ~500 tokens de eval + potencialmente N ejecuciones completas del agente),
  pero consigue resultados de mayor calidad en tareas complejas.

Uso típico desde CLI:
    architect run "tarea" --self-eval basic
    architect run "tarea" --self-eval full
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import structlog

if TYPE_CHECKING:
    from ..llm.adapter import LLMAdapter
    from .state import AgentState

logger = structlog.get_logger()


@dataclass
class EvalResult:
    """Resultado de una evaluación del agente.

    Attributes:
        completed: True si la tarea se considera completada correctamente.
        confidence: Nivel de confianza del evaluador (0.0 – 1.0).
        issues: Lista de problemas detectados (vacía si completado).
        suggestion: Sugerencia para mejorar el resultado.
        raw_response: Respuesta cruda del LLM (para debugging).
    """

    completed: bool
    confidence: float
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""
    raw_response: str = ""

    def __repr__(self) -> str:
        return (
            f"<EvalResult("
            f"completed={self.completed}, "
            f"confidence={self.confidence:.0%}, "
            f"issues={len(self.issues)})>"
        )


class SelfEvaluator:
    """Evaluador automático del resultado del agente.

    Usa el LLM para verificar si la tarea se completó correctamente
    y, en modo ``full``, reintentar con un prompt de corrección.

    Attributes:
        llm: LLMAdapter para las llamadas de evaluación.
        max_retries: Número máximo de reintentos en modo ``full``.
        confidence_threshold: Umbral mínimo de confianza para aceptar el resultado.
        log: Logger estructurado.
    """

    # System prompt del evaluador — diseñado para producir JSON válido
    _EVAL_SYSTEM_PROMPT = (
        "Eres un evaluador de resultados de agentes de IA. "
        "Tu trabajo es verificar si una tarea se completó correctamente.\n\n"
        "IMPORTANTE: Responde ÚNICAMENTE con un JSON válido con esta estructura exacta:\n"
        '{"completed": true_o_false, "confidence": número_entre_0_y_1, '
        '"issues": ["lista", "de", "problemas"], "suggestion": "sugerencia_de_mejora"}\n\n'
        "- completed: true si la tarea se realizó completa y correctamente\n"
        "- confidence: tu nivel de seguridad (1.0 = totalmente seguro)\n"
        "- issues: lista vacía [] si todo está bien; lista de problemas si no\n"
        "- suggestion: qué debería hacer el agente para mejorar (vacío si completed=true)\n\n"
        "No incluyas explicaciones ni texto fuera del JSON."
    )

    def __init__(
        self,
        llm: LLMAdapter,
        max_retries: int = 2,
        confidence_threshold: float = 0.8,
    ) -> None:
        """Inicializa el evaluador.

        Args:
            llm: LLMAdapter para las llamadas de evaluación.
            max_retries: Número máximo de reintentos en modo ``full``.
            confidence_threshold: Umbral de confianza para aceptar el resultado.
        """
        self.llm = llm
        self.max_retries = max_retries
        self.confidence_threshold = confidence_threshold
        self.log = logger.bind(component="self_evaluator")

    # ── Modo basic ──────────────────────────────────────────────────────────

    def evaluate_basic(
        self, original_prompt: str, state: AgentState
    ) -> EvalResult:
        """Evalúa si la tarea se completó correctamente (una sola llamada LLM).

        Construye un contexto con el prompt original, el output del agente y
        un resumen de los pasos ejecutados, y pregunta al LLM si la tarea
        se completó. Cuesta ~500 tokens extra.

        Args:
            original_prompt: Prompt original del usuario.
            state: Estado final del agente.

        Returns:
            EvalResult con el veredicto del evaluador.
        """
        self.log.info(
            "eval.basic.start",
            prompt_preview=original_prompt[:80],
            agent_steps=state.current_step,
            agent_tool_calls=state.total_tool_calls,
        )

        steps_summary = self._summarize_steps(state)
        output_preview = (state.final_output or "(sin output)")[:500]

        eval_messages = [
            {"role": "system", "content": self._EVAL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"**Tarea original del usuario:**\n{original_prompt}\n\n"
                    f"**Resultado del agente:**\n{output_preview}\n\n"
                    f"**Acciones ejecutadas:**\n{steps_summary}\n\n"
                    f"¿La tarea se completó correctamente?"
                ),
            },
        ]

        try:
            response = self.llm.completion(eval_messages, tools=None)
            raw = response.content or ""
        except Exception as e:
            self.log.warning("eval.basic.llm_error", error=str(e))
            return EvalResult(
                completed=False,
                confidence=0.0,
                issues=[f"Error al evaluar: {e}"],
                suggestion="Verifica el resultado manualmente.",
                raw_response="",
            )

        result = self._parse_eval(raw)

        self.log.info(
            "eval.basic.complete",
            completed=result.completed,
            confidence=result.confidence,
            issues_count=len(result.issues),
        )

        return result

    # ── Modo full ───────────────────────────────────────────────────────────

    def evaluate_full(
        self,
        original_prompt: str,
        state: AgentState,
        run_fn: Callable[[str], AgentState],
    ) -> AgentState:
        """Evalúa el resultado y reintenta si detecta problemas.

        Ciclo:
        1. Evalúa con ``evaluate_basic``
        2. Si completed=True y confidence >= threshold → retorna estado
        3. Si no → construye prompt de corrección y re-ejecuta el agente
        4. Repite hasta ``max_retries`` veces

        Args:
            original_prompt: Prompt original del usuario.
            state: Estado del agente tras la ejecución inicial.
            run_fn: Función que re-ejecuta el agente con un nuevo prompt.
                    Signature: ``(prompt: str) -> AgentState``

        Returns:
            Mejor AgentState disponible (puede ser el original si todo falló).
        """
        self.log.info(
            "eval.full.start",
            max_retries=self.max_retries,
            confidence_threshold=self.confidence_threshold,
        )

        for attempt in range(self.max_retries):
            eval_result = self.evaluate_basic(original_prompt, state)

            # Verificar si el resultado es aceptable
            if eval_result.completed and eval_result.confidence >= self.confidence_threshold:
                self.log.info(
                    "eval.full.passed",
                    attempt=attempt,
                    confidence=eval_result.confidence,
                )
                return state

            self.log.warning(
                "eval.full.retry",
                attempt=attempt + 1,
                max_retries=self.max_retries,
                completed=eval_result.completed,
                confidence=eval_result.confidence,
                issues=eval_result.issues,
            )

            # Construir prompt de corrección con contexto detallado
            correction_prompt = self._build_correction_prompt(
                original_prompt, eval_result
            )

            # Re-ejecutar el agente con el prompt de corrección
            try:
                state = run_fn(correction_prompt)
            except Exception as e:
                self.log.error("eval.full.run_error", attempt=attempt, error=str(e))
                break

        self.log.warning(
            "eval.full.max_retries_reached",
            attempts=self.max_retries,
            final_status=state.status,
        )
        return state

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _build_correction_prompt(
        self, original_prompt: str, eval_result: EvalResult
    ) -> str:
        """Construye el prompt de corrección con el contexto del problema.

        Args:
            original_prompt: Prompt original del usuario.
            eval_result: Resultado de la evaluación que falló.

        Returns:
            Prompt de corrección para re-ejecutar el agente.
        """
        issues_text = (
            "\n".join(f"  - {issue}" for issue in eval_result.issues)
            if eval_result.issues
            else "  - Resultado incompleto o incorrecto."
        )
        suggestion_text = (
            eval_result.suggestion
            if eval_result.suggestion
            else "Revisa el resultado y completa la tarea."
        )

        return (
            f"La tarea anterior no se completó correctamente.\n\n"
            f"**Tarea original:**\n{original_prompt}\n\n"
            f"**Problemas detectados:**\n{issues_text}\n\n"
            f"**Sugerencia:**\n{suggestion_text}\n\n"
            f"Por favor, corrige estos problemas y completa la tarea correctamente."
        )

    def _summarize_steps(self, state: AgentState) -> str:
        """Resume los steps del agente en texto legible para el evaluador.

        Args:
            state: Estado del agente.

        Returns:
            Resumen conciso de los steps ejecutados.
        """
        if not state.steps:
            return "(ningún paso ejecutado)"

        parts: list[str] = []
        for step in state.steps:
            if step.tool_calls_made:
                tool_names = [tc.tool_name for tc in step.tool_calls_made]
                successes = [tc.result.success for tc in step.tool_calls_made]
                status_str = "OK" if all(successes) else "algunos errores"
                parts.append(f"  Paso {step.step_number + 1}: {', '.join(tool_names)} [{status_str}]")
            else:
                parts.append(f"  Paso {step.step_number + 1}: (razonamiento sin tool calls)")

        return "\n".join(parts)

    def _parse_eval(self, content: str) -> EvalResult:
        """Parsea la respuesta JSON del evaluador LLM.

        Intenta tres estrategias en orden:
        1. Parsear el contenido directamente como JSON
        2. Extraer el primer bloque ``{...}`` con regex
        3. Extraer de bloque de código ```json ... ````

        Si todas fallan, retorna un EvalResult conservador (no completado).

        Args:
            content: Respuesta cruda del LLM.

        Returns:
            EvalResult parseado o fallback conservador.
        """
        content = content.strip()

        # Estrategia 1: JSON directo
        data = self._try_parse_json(content)

        # Estrategia 2: Extraer de bloque de código ```json ... ```
        if data is None:
            code_block_match = re.search(
                r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content
            )
            if code_block_match:
                data = self._try_parse_json(code_block_match.group(1))

        # Estrategia 3: Extraer primer {...} válido
        if data is None:
            brace_match = re.search(r"\{[\s\S]*?\}", content)
            if brace_match:
                data = self._try_parse_json(brace_match.group(0))

        # Fallback: evaluación conservadora
        if data is None:
            self.log.warning(
                "eval.parse_failed",
                content_preview=content[:100],
            )
            return EvalResult(
                completed=False,
                confidence=0.0,
                issues=["No se pudo parsear la evaluación del LLM."],
                suggestion="Revisa manualmente el resultado.",
                raw_response=content,
            )

        # Extraer campos con valores por defecto seguros
        completed = bool(data.get("completed", False))
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))  # Clamp a [0, 1]

        raw_issues = data.get("issues", [])
        if isinstance(raw_issues, list):
            issues = [str(i) for i in raw_issues if i]
        else:
            issues = [str(raw_issues)] if raw_issues else []

        suggestion = str(data.get("suggestion", ""))

        return EvalResult(
            completed=completed,
            confidence=confidence,
            issues=issues,
            suggestion=suggestion,
            raw_response=content,
        )

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Intenta parsear texto como JSON.

        Args:
            text: Texto a parsear.

        Returns:
            Dict si el parseo fue exitoso, None si falló.
        """
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None
