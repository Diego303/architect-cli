"""
Context Builder y Context Manager - Construcción y gestión del contexto LLM.

ContextBuilder: Construye la lista de mensajes OpenAI (system, user, tool results).
ContextManager: Gestiona el context window para evitar que se llene en tareas largas.

F10: Inyección del índice del repositorio en el system prompt.
F11: ContextManager con 3 niveles de pruning (truncado, resumen, ventana deslizante).
"""

from __future__ import annotations

import structlog
from typing import TYPE_CHECKING, Any

from ..config.schema import AgentConfig, ContextConfig
from ..llm.adapter import LLMAdapter, ToolCall
from .state import ToolCallResult

if TYPE_CHECKING:
    from ..indexer.tree import RepoIndex

logger = structlog.get_logger()


class ContextManager:
    """Gestor del context window para evitar que se llene en tareas largas.

    Actúa en tres niveles progresivos (F11):
    - Nivel 1: ``truncate_tool_result`` — trunca tool results individuales.
    - Nivel 2: ``maybe_compress``       — resume pasos antiguos usando el LLM.
    - Nivel 3: ``enforce_window``       — hard limit de tokens totales.

    El nivel 1 se aplica en ``ContextBuilder._format_tool_result()``.
    Los niveles 2 y 3 se aplican en el loop tras cada step.
    """

    def __init__(self, config: ContextConfig) -> None:
        self.config = config
        self.log = logger.bind(component="context_manager")

    # ── Nivel 1: Truncado de tool results ──────────────────────────────────

    def truncate_tool_result(self, content: str) -> str:
        """Trunca el resultado de una tool si supera el límite configurado.

        Preserva las primeras 40 líneas y las últimas 20 para mantener
        el inicio (importante para estructuras) y el final (suele tener
        resúmenes y errores).

        Args:
            content: Contenido del tool result

        Returns:
            Contenido truncado con marcador de omisión, o el original si cabe
        """
        if self.config.max_tool_result_tokens == 0:
            return content

        max_chars = self.config.max_tool_result_tokens * 4  # ~4 chars/token
        if len(content) <= max_chars:
            return content

        lines = content.splitlines()
        head_lines = 40
        tail_lines = 20

        if len(lines) <= head_lines + tail_lines:
            # El contenido es largo pero tiene pocas líneas (líneas muy largas)
            # Truncar por caracteres manteniendo proporción
            head = content[:max_chars // 2]
            tail = content[-(max_chars // 4):]
            omitted_chars = len(content) - len(head) - len(tail)
            return f"{head}\n\n[... {omitted_chars} caracteres omitidos ...]\n\n{tail}"

        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])
        omitted = len(lines) - head_lines - tail_lines
        return f"{head}\n\n[... {omitted} líneas omitidas ...]\n\n{tail}"

    # ── Nivel 2: Resumen de pasos antiguos ─────────────────────────────────

    def maybe_compress(
        self, messages: list[dict[str, Any]], llm: LLMAdapter
    ) -> list[dict[str, Any]]:
        """Comprime mensajes antiguos en un resumen si hay demasiados pasos.

        Se activa cuando el número de intercambios (pasos con tool calls)
        supera ``summarize_after_steps``. Los últimos ``keep_recent_steps``
        intercambios se mantienen íntegros; el resto se resume con el LLM.

        Si la compresión falla (error LLM, red, etc.), devuelve los mensajes
        originales sin modificar.

        Args:
            messages: Lista de mensajes actual del agente
            llm: LLMAdapter para generar el resumen

        Returns:
            Lista de mensajes (posiblemente comprimida)
        """
        if self.config.summarize_after_steps == 0:
            return messages

        tool_exchanges = self._count_tool_exchanges(messages)
        if tool_exchanges <= self.config.summarize_after_steps:
            return messages

        # Separar: system + user | mensajes de diálogo
        if len(messages) < 4:  # system + user + al menos 1 intercambio
            return messages

        system_msg = messages[0]
        user_msg = messages[1]
        dialog_msgs = messages[2:]

        # Mantener los últimos keep_recent_steps*3 mensajes intactos
        keep_count = self.config.keep_recent_steps * 3
        if len(dialog_msgs) <= keep_count:
            return messages  # No hay suficiente para comprimir

        old_msgs = dialog_msgs[:-keep_count]
        recent_msgs = dialog_msgs[-keep_count:]

        self.log.info(
            "context.compressing",
            tool_exchanges=tool_exchanges,
            old_messages=len(old_msgs),
            kept_messages=len(recent_msgs),
        )

        # Resumir mensajes antiguos con el LLM
        try:
            summary = self._summarize_steps(old_msgs, llm)
        except Exception as e:
            self.log.warning("context.compress_failed", error=str(e))
            return messages  # Graceful degradation: sin compresión

        summary_msg: dict[str, Any] = {
            "role": "assistant",
            "content": f"[Resumen de pasos anteriores]\n{summary}",
        }

        compressed = [system_msg, user_msg, summary_msg, *recent_msgs]
        self.log.info(
            "context.compressed",
            original_messages=len(messages),
            compressed_messages=len(compressed),
        )
        return compressed

    def _summarize_steps(
        self, messages: list[dict[str, Any]], llm: LLMAdapter
    ) -> str:
        """Usa el LLM para resumir una secuencia de mensajes.

        Si la llamada al LLM falla, genera un resumen mecánico como fallback
        (lista de tools ejecutadas y archivos involucrados).

        Args:
            messages: Mensajes del diálogo a resumir
            llm: LLMAdapter para la llamada de resumen

        Returns:
            Texto de resumen (~200 palabras)
        """
        formatted = self._format_steps_for_summary(messages)

        try:
            summary_prompt = [
                {
                    "role": "system",
                    "content": (
                        "Resume las siguientes acciones del agente en un párrafo conciso. "
                        "Incluye: qué archivos se leyeron o modificaron, qué se intentó, "
                        "qué funcionó y qué falló. Máximo 200 palabras. "
                        "Solo el párrafo de resumen, sin explicaciones adicionales."
                    ),
                },
                {"role": "user", "content": formatted},
            ]
            response = llm.completion(summary_prompt, tools=None)
            return response.content or formatted
        except Exception as e:
            self.log.warning("context.summarize_llm_failed", error=str(e))
            # Fallback mecánico: usar el texto formateado directamente
            return f"[Resumen mecánico — LLM no disponible]\n{formatted}"

    def _format_steps_for_summary(self, messages: list[dict[str, Any]]) -> str:
        """Convierte mensajes en texto legible para resumir."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            if role == "assistant":
                if msg.get("tool_calls"):
                    tool_names = [
                        tc["function"]["name"]
                        for tc in msg["tool_calls"]
                        if isinstance(tc, dict) and "function" in tc
                    ]
                    parts.append(f"Agente llamó tools: {', '.join(tool_names)}")
                elif msg.get("content"):
                    content = str(msg["content"])[:300]
                    parts.append(f"Agente respondió: {content}")
            elif role == "tool":
                name = msg.get("name", "unknown")
                content = str(msg.get("content") or "")[:300]
                parts.append(f"Resultado de {name}: {content}")
        return "\n".join(parts) or "(sin mensajes)"

    def _count_tool_exchanges(self, messages: list[dict[str, Any]]) -> int:
        """Cuenta el número de pasos con tool calls."""
        return sum(
            1
            for m in messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        )

    # ── Pipeline unificado (v3-M2) ─────────────────────────────────────────

    def manage(
        self, messages: list[dict[str, Any]], llm: LLMAdapter | None = None
    ) -> list[dict[str, Any]]:
        """Pipeline unificado de gestión de contexto.

        Se llama antes de cada llamada al LLM. Aplica en orden:
        1. Comprimir pasos antiguos (Nivel 2) si el contexto supera el 75%
        2. Hard limit de tokens totales (Nivel 3)

        El Nivel 1 (truncado de tool results) se aplica en ContextBuilder
        al añadir cada tool result, no en este pipeline.

        Args:
            messages: Lista de mensajes actual
            llm: LLMAdapter para generar resúmenes (puede ser None)

        Returns:
            Lista de mensajes gestionada (posiblemente comprimida o truncada)
        """
        # Solo comprimir si el contexto supera el 75% del máximo
        if llm and self._is_above_threshold(messages, 0.75):
            messages = self.maybe_compress(messages, llm)
        messages = self.enforce_window(messages)
        return messages

    def _is_above_threshold(
        self, messages: list[dict[str, Any]], threshold: float
    ) -> bool:
        """True si el contexto estimado supera el porcentaje dado del máximo.

        Args:
            messages: Lista de mensajes
            threshold: Fracción del máximo (ej: 0.75 = 75%)

        Returns:
            True si supera el umbral, o True si max_context_tokens == 0
            (sin límite configurado → confiar en summarize_after_steps)
        """
        if self.config.max_context_tokens == 0:
            return True  # Sin límite de tokens → confiar en summarize_after_steps
        limit = int(self.config.max_context_tokens * threshold)
        return self._estimate_tokens(messages) > limit

    def is_critically_full(self, messages: list[dict[str, Any]]) -> bool:
        """True si el contexto está al 95%+ del máximo incluso después de comprimir.

        Se usa como safety net en el loop: si retorna True, el agente
        debe cerrar aunque no haya terminado.

        Args:
            messages: Lista de mensajes actual

        Returns:
            True si el contexto está críticamente lleno
        """
        if self.config.max_context_tokens == 0:
            return False
        limit_95 = int(self.config.max_context_tokens * 0.95)
        return self._estimate_tokens(messages) > limit_95

    # ── Nivel 3: Ventana deslizante (hard limit) ───────────────────────────

    def enforce_window(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Aplica un límite hard de tokens al context window.

        Si el total estimado supera ``max_context_tokens``, elimina pares de
        mensajes antiguos del diálogo (de 2 en 2, empezando por los más viejos)
        hasta que quepa, manteniendo siempre system y user.

        Args:
            messages: Lista de mensajes

        Returns:
            Lista recortada si era necesario, o la original
        """
        if self.config.max_context_tokens == 0:
            return messages

        if self._estimate_tokens(messages) <= self.config.max_context_tokens:
            return messages

        system_msg = messages[0]
        user_msg = messages[1]
        dialog = list(messages[2:])
        removed = 0

        while (
            len(dialog) > 2
            and self._estimate_tokens([system_msg, user_msg] + dialog)
            > self.config.max_context_tokens
        ):
            # Eliminar los 2 mensajes más antiguos del diálogo
            dialog = dialog[2:]
            removed += 2

        if removed > 0:
            self.log.warning(
                "context.window_enforced",
                removed_messages=removed,
                remaining_messages=len(dialog),
            )

        return [system_msg, user_msg] + dialog

    # ── Utilidades ─────────────────────────────────────────────────────────

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estima el número de tokens en una lista de mensajes.

        Aproximación: ~4 caracteres por token (válida para inglés y código).
        Extrae solo los campos de contenido relevantes en vez de serializar
        el dict completo (que sobreestima por las claves JSON y metadatos).

        Args:
            messages: Lista de mensajes

        Returns:
            Estimación de tokens
        """
        total_chars = 0
        for m in messages:
            # Contenido principal del mensaje
            content = m.get("content")
            if content:
                total_chars += len(str(content))
            # Tool calls: contar nombre y argumentos
            for tc in m.get("tool_calls", []):
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    total_chars += len(str(func.get("name", "")))
                    total_chars += len(str(func.get("arguments", "")))
            # Overhead por mensaje (~4 tokens de metadatos por mensaje)
            total_chars += 16
        return total_chars // 4


class ContextBuilder:
    """Constructor de contexto para el LLM.

    Gestiona la construcción y actualización de la lista de mensajes
    que se envía al LLM en cada step.

    Attributes:
        repo_index: Índice del repositorio (F10). Si está presente,
                    se inyecta como sección del system prompt en build_initial().
        context_manager: ContextManager (F11). Si está presente,
                         trunca los tool results largos automáticamente.
    """

    def __init__(
        self,
        repo_index: RepoIndex | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        """Inicializa el ContextBuilder.

        Args:
            repo_index: Índice del repositorio para inyectar en el system prompt.
                        Si es None, no se añade información del proyecto.
            context_manager: ContextManager para truncar tool results largos.
                             Si es None, los tool results no se truncan.
        """
        self.repo_index = repo_index
        self.context_manager = context_manager

    def build_initial(
        self,
        agent_config: AgentConfig,
        prompt: str,
    ) -> list[dict[str, Any]]:
        """Construye los mensajes iniciales para el LLM.

        Si hay un repo_index disponible, lo inyecta al final del system prompt
        como una sección "Estructura del proyecto". Esto permite que el agente
        sepa qué archivos existen sin necesidad de hacer list_files manualmente.

        Args:
            agent_config: Configuración del agente (system_prompt, allowed_tools, etc.)
            prompt: Prompt del usuario

        Returns:
            Lista de mensajes en formato OpenAI: [system, user]
        """
        # System prompt base del agente
        system_content = agent_config.system_prompt

        # Inyectar índice del repositorio si está disponible
        if self.repo_index is not None:
            system_content = self._inject_repo_index(system_content, self.repo_index)

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

    def _inject_repo_index(self, system_prompt: str, index: RepoIndex) -> str:
        """Añade la sección de estructura del proyecto al system prompt.

        Formato compacto que muestra:
        - Total de archivos y líneas
        - Distribución de lenguajes
        - Árbol de directorios (formateado para ser compacto)
        - Guía para usar search_code y grep

        Args:
            system_prompt: Prompt base del agente
            index: Índice del repositorio construido por RepoIndexer

        Returns:
            system_prompt con la sección de estructura añadida al final
        """
        # Formatear resumen de lenguajes (top 5)
        lang_items = list(index.languages.items())[:5]
        lang_str = ", ".join(f"{lang} ({n})" for lang, n in lang_items)
        if not lang_str:
            lang_str = "desconocido"

        repo_section = (
            f"\n\n## Estructura del Proyecto\n\n"
            f"**Total**: {index.total_files} archivos, {index.total_lines:,} líneas  \n"
            f"**Lenguajes**: {lang_str}\n\n"
            f"```\n"
            f"{index.tree_summary}\n"
            f"```\n\n"
            f"**Nota**: Usa `search_code` o `grep` para encontrar código específico, "
            f"`find_files` para localizar archivos por nombre. "
            f"Lee solo los archivos que realmente necesitas."
        )

        return system_prompt + repo_section

    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[ToolCall],
        results: list[ToolCallResult],
    ) -> list[dict[str, Any]]:
        """Añade tool results a la lista de mensajes.

        Formato OpenAI para tool calling:
        1. Assistant message con tool_calls
        2. Tool messages con los resultados

        Args:
            messages: Lista de mensajes existente
            tool_calls: Tool calls solicitadas por el LLM
            results: Resultados de ejecutar las tool calls

        Returns:
            Nueva lista de mensajes con tool results añadidos
        """
        new_messages = messages.copy()

        # 1. Añadir assistant message con tool_calls
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": self._serialize_arguments(tc.arguments),
                    },
                }
                for tc in tool_calls
            ],
        }
        new_messages.append(assistant_message)

        # 2. Añadir tool messages con los resultados
        for tc, result in zip(tool_calls, results):
            tool_message = self._format_tool_result(tc, result)
            new_messages.append(tool_message)

        return new_messages

    def _format_tool_result(
        self,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> dict[str, Any]:
        """Formatea el resultado de una tool para el LLM.

        Aplica truncado (Nivel 1 de F11) si hay un ContextManager configurado.
        """
        if result.was_dry_run:
            content = f"[DRY-RUN] {result.result.output}"
        elif result.result.success:
            content = result.result.output
        else:
            content = f"Error: {result.result.error}"

        # Nivel 1 (F11): Truncar si el resultado es muy largo
        if self.context_manager and content:
            content = self.context_manager.truncate_tool_result(content)

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.name,
            "content": content,
        }

    def _serialize_arguments(self, arguments: dict[str, Any]) -> str:
        """Serializa argumentos de tool call a JSON string."""
        import json
        return json.dumps(arguments)

    def append_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Añade un mensaje del assistant (respuesta final)."""
        new_messages = messages.copy()
        new_messages.append({"role": "assistant", "content": content})
        return new_messages

    def append_user_message(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Añade un mensaje del usuario."""
        new_messages = messages.copy()
        new_messages.append({"role": "user", "content": content})
        return new_messages
