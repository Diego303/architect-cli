# Plan de Implementación v3 — Core Rediseñado

Este plan reemplaza las fases F2 (LLM + Loop), F3 (Agentes), F5 (Logging), F7 (Robustez) y F11 (Token optimization) de los planes anteriores. Las demás fases (F0, F1, F4, F9, F10, F12, F13, F14) siguen vigentes con ajustes menores que se documentan al final.

---

## Cambios Respecto a v1/v2

| Qué cambia | v1/v2 (antes) | v3 (ahora) |
|-------------|---------------|------------|
| Agent loop | `for step in range(max_steps)` | `while True` — el LLM decide cuándo parar |
| Terminación | Counter + timeout | LLM deja de pedir tools = fin natural |
| Safety nets | Cortan abruptamente | Inyectan instrucción de cierre → última llamada al LLM |
| Context | Crece sin límite (F11 lo arreglaba) | `ContextManager` integrado desde el core |
| Plan + Build | Dos fases secuenciales rígidas | Plan integrado en el prompt de build |
| MixedModeRunner | Clase separada | Eliminado — build planifica internamente |
| Log levels | `debug \| info \| warn \| error` | + `human` como nivel de trazabilidad legible |
| Logs human | No existían | Iconos + formato legible para seguir al agente |
| Auto-verify | El agente decide manualmente | Hook en el Engine: lint/test automático post-edit |
| Cierre en límites | `state.status = "partial"` frío | LLM resume qué hizo y qué queda pendiente |

---

## Estructura de Archivos Actualizada (solo cambios)

```
src/architect/
├── core/
│   ├── loop.py              # REESCRITO — while True + safety nets
│   ├── state.py             # AMPLIADO — nuevos estados de cierre
│   ├── context.py           # REESCRITO — ContextManager con budget de tokens
│   └── hooks.py             # NUEVO — post-edit verification hooks
├── agents/
│   ├── prompts.py           # REESCRITO — plan integrado en build
│   └── registry.py          # SIMPLIFICADO — sin MixedModeRunner
└── logging/
    ├── setup.py             # AMPLIADO — pipeline human
    ├── human.py             # NUEVO — formateador de logs humanos
    └── levels.py            # NUEVO — nivel HUMAN custom
```

---

## MEJORA 1 — Agent Loop Rediseñado (`while True`)

### El Principio

> El flujo natural de un agente es: el LLM trabaja hasta que decide que terminó.
> Los límites (max_steps, budget, timeout, context) son watchdogs.
> Cuando un watchdog salta, no corta — pide un cierre limpio.

### 1.1 — El Nuevo Loop

```python
# src/architect/core/loop.py
import time
from enum import Enum

class StopReason(Enum):
    """Por qué se detuvo el agente."""
    LLM_DONE = "llm_done"              # El LLM decidió que terminó (natural)
    MAX_STEPS = "max_steps"            # Watchdog: límite de pasos
    BUDGET_EXCEEDED = "budget_exceeded" # Watchdog: límite de coste
    CONTEXT_FULL = "context_full"      # Watchdog: context window lleno
    TIMEOUT = "timeout"                # Watchdog: tiempo total excedido
    USER_INTERRUPT = "user_interrupt"   # El usuario hizo Ctrl+C
    LLM_ERROR = "llm_error"           # Error irrecuperable del LLM


class AgentLoop:
    def __init__(
        self,
        llm: LLMAdapter,
        engine: ExecutionEngine,
        agent_config: AgentConfig,
        context_mgr: ContextManager,
        cost_tracker: CostTracker | None,
        shutdown: GracefulShutdown,
        logger: structlog.BoundLogger,
        timeout: int | None = None,
    ):
        self.llm = llm
        self.engine = engine
        self.config = agent_config
        self.ctx = context_mgr
        self.costs = cost_tracker
        self.shutdown = shutdown
        self.log = logger
        self.timeout = timeout
        self._start_time: float = 0

    def run(self, prompt: str) -> AgentState:
        self._start_time = time.time()
        state = AgentState()
        state.messages = self.ctx.build_initial(self.config, prompt)
        tools_schema = self.engine.registry.get_schemas(
            self.config.allowed_tools or None
        )
        step = 0

        while True:
            # ─── SAFETY CHECKS (antes de cada step) ───
            stop = self._check_safety_nets(state, step)
            if stop is not None:
                return self._graceful_close(state, stop)

            # ─── CONTEXT MANAGEMENT (antes de cada llamada al LLM) ───
            state.messages = self.ctx.manage(state.messages)

            # ─── LLAMADA AL LLM ───
            self.log.msg(
                "llm.call",
                step=step,
                messages_count=len(state.messages),
                _level="human",
            )

            try:
                response = self.llm.completion(
                    messages=state.messages,
                    tools=tools_schema if tools_schema else None,
                )
            except Exception as e:
                self.log.error("llm.error", error=str(e), step=step)
                # Intentar recuperarse: retry ya lo hizo el adapter.
                # Si llega aquí es irrecuperable.
                state.status = "failed"
                state.stop_reason = StopReason.LLM_ERROR
                state.final_output = f"Error irrecuperable del LLM: {e}"
                return state

            # Registrar coste
            if self.costs and response.usage:
                self.costs.record(
                    step=step,
                    model=self.llm.config.model,
                    usage=response.usage,
                )

            step += 1

            # ─── EL LLM DECIDIÓ TERMINAR ───
            # (respondió con texto, sin pedir tools)
            if not response.tool_calls:
                self.log.msg(
                    "agent.done",
                    step=step,
                    reason="llm_decided",
                    _level="human",
                )
                state.final_output = response.content
                state.status = "success"
                state.stop_reason = StopReason.LLM_DONE
                return state

            # ─── EL LLM PIDIÓ TOOLS → EJECUTAR ───
            state.messages.append(self._assistant_message(response))

            tool_results = []
            for tc in response.tool_calls:
                self.log.msg(
                    "tool.call",
                    tool=tc.name,
                    args_summary=self._summarize_args(tc.arguments),
                    _level="human",
                )

                result = self.engine.execute_tool_call(tc.name, tc.arguments)

                self.log.msg(
                    "tool.result",
                    tool=tc.name,
                    success=result.success,
                    _level="human",
                )

                tool_results.append(ToolCallResult(
                    tool_name=tc.name,
                    args=tc.arguments,
                    result=result,
                ))

                # ─── AUTO-VERIFY POST-EDIT ───
                if tc.name in ("edit_file", "write_file", "apply_patch"):
                    verify_result = self.engine.run_post_edit_hooks(
                        tc.name, tc.arguments
                    )
                    if verify_result:
                        tool_results.append(verify_result)

            # Añadir resultados al contexto
            state.messages = self.ctx.append_tool_results(
                state.messages, response.tool_calls, tool_results
            )

            # Registrar step
            state.steps.append(StepResult(
                step_number=step,
                llm_response=response,
                tool_calls_made=tool_results,
                timestamp=time.time(),
            ))

    # ─── SAFETY NETS ───

    def _check_safety_nets(self, state: AgentState, step: int) -> StopReason | None:
        """
        Comprueba todas las condiciones de seguridad.
        Retorna None si todo OK, o el StopReason si hay que parar.
        """
        # 1. User interrupt (Ctrl+C)
        if self.shutdown.should_stop:
            return StopReason.USER_INTERRUPT

        # 2. Max steps
        if step >= self.config.max_steps:
            self.log.msg(
                "safety.max_steps",
                step=step,
                max=self.config.max_steps,
                _level="human",
            )
            return StopReason.MAX_STEPS

        # 3. Budget
        if self.costs and self.costs.over_budget:
            self.log.msg(
                "safety.budget",
                spent=self.costs.total_cost_usd,
                budget=self.costs.budget_usd,
                _level="human",
            )
            return StopReason.BUDGET_EXCEEDED

        # 4. Timeout
        if self.timeout and (time.time() - self._start_time) > self.timeout:
            self.log.msg("safety.timeout", _level="human")
            return StopReason.TIMEOUT

        # 5. Context window (si después de comprimir sigue lleno)
        if self.ctx.is_critically_full(state.messages):
            return StopReason.CONTEXT_FULL

        return None

    # ─── CIERRE LIMPIO ───

    def _graceful_close(self, state: AgentState, reason: StopReason) -> AgentState:
        """
        Cuando un safety net salta, no cortamos de golpe.
        Le damos al LLM una última oportunidad de cerrar con un resumen.
        """
        self.log.msg(
            "agent.closing",
            reason=reason.value,
            _level="human",
        )

        close_instructions = {
            StopReason.MAX_STEPS: (
                "Has alcanzado el límite máximo de pasos. "
                "Responde con:\n"
                "1. Un resumen de lo que completaste\n"
                "2. Qué queda pendiente\n"
                "3. Sugerencias para continuar"
            ),
            StopReason.BUDGET_EXCEEDED: (
                "Se ha alcanzado el presupuesto máximo de tokens/coste. "
                "Resume lo que completaste y qué falta por hacer."
            ),
            StopReason.CONTEXT_FULL: (
                "El contexto de conversación está lleno. "
                "Resume lo que completaste y qué falta por hacer."
            ),
            StopReason.TIMEOUT: (
                "Se agotó el tiempo asignado. "
                "Resume lo que completaste y qué falta por hacer."
            ),
            StopReason.USER_INTERRUPT: None,  # No llamar al LLM si el usuario cancela
        }

        instruction = close_instructions.get(reason)

        if instruction:
            # Una última llamada SIN tools para que el LLM cierre
            state.messages.append({
                "role": "user",
                "content": f"[SISTEMA] {instruction}",
            })
            try:
                response = self.llm.completion(
                    messages=state.messages,
                    tools=None,  # Sin tools — solo texto de cierre
                )
                state.final_output = response.content
            except Exception:
                state.final_output = (
                    f"El agente se detuvo por: {reason.value}. "
                    f"Pasos completados: {len(state.steps)}."
                )
        else:
            state.final_output = (
                f"Interrumpido por el usuario. "
                f"Pasos completados: {len(state.steps)}."
            )

        state.status = "partial"
        state.stop_reason = reason
        return state
```

### 1.2 — AgentState Actualizado

```python
# src/architect/core/state.py
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class AgentState:
    messages: list[dict] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    status: Literal["running", "success", "partial", "failed"] = "running"
    stop_reason: StopReason | None = None
    final_output: str | None = None

    @property
    def current_step(self) -> int:
        return len(self.steps)

    def to_output_dict(self) -> dict:
        return {
            "status": self.status,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "output": self.final_output,
            "steps_completed": len(self.steps),
            "tools_used": [
                {
                    "step": s.step_number,
                    "tool": tc.tool_name,
                    "success": tc.result.success,
                }
                for s in self.steps
                for tc in s.tool_calls_made
            ],
        }
```

### 1.3 — Por Qué Este Diseño Es Correcto

```
ANTES (v1):                         AHORA (v3):

for i in range(max_steps):          while True:
    response = llm(...)                 if watchdog_triggered:
    if done: break                          graceful_close()  ← LLM resume
    execute_tools()                         break
else:                                   response = llm(...)
    status = "partial"  ← frío          if no tool_calls:
                                            done!  ← LLM decidió
                                            break
                                        execute_tools()
```

La diferencia real: el `for-range` hace que `max_steps` sea la estructura. El `while True` hace que **la decisión del LLM** sea la estructura y `max_steps` sea un guardia.

---

## MEJORA 2 — Context Management Integrado en el Core

### El Principio

> El context window es un recurso finito. Si no lo gestionas activamente,
> cualquier tarea de >8 pasos explota. Esto no es optimización — es necesidad funcional.

### 2.1 — ContextManager (reemplaza al simple ContextBuilder)

```python
# src/architect/core/context.py
import structlog

class ContextManager:
    """
    Gestiona el contexto del agente: construcción, medición, truncado y compresión.
    Integrado en el core desde el día 1 — no es una optimización posterior.
    """

    # ─── Configuración ───

    # Tokens estimados por carácter (aprox para código/inglés/español)
    CHARS_PER_TOKEN = 4

    # Máximo de tokens que un resultado de tool puede ocupar
    MAX_TOOL_RESULT_TOKENS = 2000

    # Activar compresión cuando el contexto supera este % del máximo
    COMPRESS_THRESHOLD = 0.75

    # Siempre mantener los últimos N pasos completos sin comprimir
    KEEP_RECENT_STEPS = 4

    # Contexto máximo (ajustar según modelo)
    MAX_CONTEXT_TOKENS = 100_000

    def __init__(self, config: ContextConfig | None = None, llm: LLMAdapter | None = None):
        self.log = structlog.get_logger()
        self.llm = llm  # Necesario para resumir (puede ser None si no se quiere)
        if config:
            self.MAX_TOOL_RESULT_TOKENS = config.max_tool_result_tokens
            self.COMPRESS_THRESHOLD = config.compress_threshold
            self.KEEP_RECENT_STEPS = config.keep_recent_steps
            self.MAX_CONTEXT_TOKENS = config.max_context_tokens

    # ─── Construcción de contexto inicial ───

    def build_initial(self, agent_config: AgentConfig, prompt: str,
                      repo_index: RepoIndex | None = None) -> list[dict]:
        """Construye los mensajes iniciales: system + user."""
        system_parts = [agent_config.system_prompt]

        # Inyectar contexto del repo si existe
        if repo_index:
            system_parts.append(self._format_repo_context(repo_index))

        return [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": prompt},
        ]

    def _format_repo_context(self, index: RepoIndex) -> str:
        return (
            "## Estructura del proyecto\n"
            f"Archivos: {index.total_files} | "
            f"Líneas: {index.total_lines} | "
            f"Lenguajes: {', '.join(f'{k}({v})' for k,v in index.languages.items())}\n\n"
            f"```\n{index.tree_summary}\n```\n\n"
            "Usa search_code o grep para encontrar código relevante "
            "antes de hacer cambios."
        )

    # ─── Añadir resultados de tools ───

    def append_tool_results(
        self,
        messages: list[dict],
        tool_calls: list,
        results: list[ToolCallResult],
    ) -> list[dict]:
        """Añade resultados de tools al contexto, truncando si son muy largos."""
        tool_messages = []
        for tc, result in zip(tool_calls, results):
            # Truncar resultados largos ANTES de añadirlos
            output = self._truncate_tool_result(result.result.output)

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": output if result.result.success
                    else f"ERROR: {result.result.error}\n{output}",
            })

        return messages + tool_messages

    # ─── Truncado de resultados de tools ───

    def _truncate_tool_result(self, output: str) -> str:
        """Trunca resultados largos preservando inicio y final."""
        estimated = self._estimate_tokens(output)
        if estimated <= self.MAX_TOOL_RESULT_TOKENS:
            return output

        lines = output.splitlines()
        if len(lines) <= 10:
            # Texto corto pero denso — truncar por caracteres
            max_chars = self.MAX_TOOL_RESULT_TOKENS * self.CHARS_PER_TOKEN
            return output[:max_chars] + "\n\n[... truncado ...]"

        # Mantener primeras 60% y últimas 25% de las líneas permitidas
        max_lines = max(20, len(lines) * self.MAX_TOOL_RESULT_TOKENS // estimated)
        head_lines = int(max_lines * 0.6)
        tail_lines = int(max_lines * 0.25)
        omitted = len(lines) - head_lines - tail_lines

        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])
        return f"{head}\n\n[... {omitted} líneas omitidas ...]\n\n{tail}"

    # ─── Gestión del contexto (llamar antes de cada LLM call) ───

    def manage(self, messages: list[dict]) -> list[dict]:
        """
        Pipeline de gestión de contexto. Se llama antes de cada llamada al LLM.

        1. Medir uso actual
        2. Si supera threshold → comprimir pasos antiguos
        3. Si sigue excediendo → sliding window duro
        """
        current_tokens = self._estimate_total_tokens(messages)
        threshold = int(self.MAX_CONTEXT_TOKENS * self.COMPRESS_THRESHOLD)

        if current_tokens <= threshold:
            return messages  # Todo bien, no hacer nada

        self.log.info(
            "context.compress",
            current_tokens=current_tokens,
            threshold=threshold,
        )

        # Paso 1: Comprimir pasos antiguos
        compressed = self._compress_old_steps(messages)
        new_tokens = self._estimate_total_tokens(compressed)

        if new_tokens <= self.MAX_CONTEXT_TOKENS:
            return compressed

        # Paso 2: Hard limit — mantener solo los últimos N intercambios
        return self._hard_truncate(compressed)

    def _compress_old_steps(self, messages: list[dict]) -> list[dict]:
        """
        Comprime pasos antiguos en un resumen.
        Mantiene: system + user original + resumen + últimos N pasos.
        """
        if len(messages) < 6:
            return messages  # Nada que comprimir

        system_msg = messages[0]
        user_msg = messages[1]

        # Calcular cuántos mensajes son "recientes" (N pasos × ~3 msgs por paso)
        recent_count = self.KEEP_RECENT_STEPS * 3
        if len(messages) - 2 <= recent_count:
            return messages  # No hay suficientes pasos viejos

        old_messages = messages[2:-recent_count]
        recent_messages = messages[-recent_count:]

        # Generar resumen
        summary = self._generate_summary(old_messages)

        return [
            system_msg,
            user_msg,
            {"role": "assistant", "content": f"[Resumen de pasos anteriores]\n{summary}"},
            *recent_messages,
        ]

    def _generate_summary(self, messages: list[dict]) -> str:
        """
        Resume pasos antiguos. Usa el LLM si está disponible,
        sino hace un resumen mecánico (extracto de tool calls).
        """
        if self.llm:
            try:
                resp = self.llm.completion([
                    {"role": "system", "content": (
                        "Resume las siguientes acciones del agente en un párrafo conciso. "
                        "Incluye: archivos leídos/modificados, qué se intentó, "
                        "qué funcionó y qué falló. Máximo 150 palabras."
                    )},
                    {"role": "user", "content": self._extract_actions_text(messages)},
                ])
                return resp.content
            except Exception:
                pass  # Fallback al resumen mecánico

        return self._mechanical_summary(messages)

    def _mechanical_summary(self, messages: list[dict]) -> str:
        """Resumen sin LLM: extrae tool calls y sus resultados."""
        actions = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    actions.append(f"- {tc['function']['name']}({self._brief_args(tc)})")
            elif msg.get("role") == "tool":
                content = msg.get("content", "")
                status = "OK" if not content.startswith("ERROR") else "ERROR"
                actions.append(f"  → {status}")

        return "Acciones previas:\n" + "\n".join(actions[-30:])  # Últimas 30

    def _hard_truncate(self, messages: list[dict]) -> list[dict]:
        """Último recurso: mantener system + user + últimos N mensajes."""
        system_msg = messages[0]
        user_msg = messages[1]
        # Ir cortando hasta que quepa
        for keep in range(len(messages) - 2, 2, -3):
            candidate = [system_msg, user_msg] + messages[-keep:]
            if self._estimate_total_tokens(candidate) <= self.MAX_CONTEXT_TOKENS:
                return candidate
        # Caso extremo: solo system + user
        return [system_msg, user_msg]

    # ─── Medición ───

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // self.CHARS_PER_TOKEN

    def _estimate_total_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            if isinstance(msg.get("content"), str):
                total += self._estimate_tokens(msg["content"])
            if msg.get("tool_calls"):
                total += self._estimate_tokens(str(msg["tool_calls"]))
        return total

    def is_critically_full(self, messages: list[dict]) -> bool:
        """True si el contexto está al 95% incluso después de comprimir."""
        return self._estimate_total_tokens(messages) > int(self.MAX_CONTEXT_TOKENS * 0.95)
```

### 2.2 — Config del ContextManager

```python
# En config/schema.py
class ContextConfig(BaseModel):
    max_tool_result_tokens: int = 2000
    compress_threshold: float = 0.75     # Comprimir al 75% de uso
    keep_recent_steps: int = 4           # Mantener últimos 4 pasos
    max_context_tokens: int = 100_000    # Ajustar según modelo
```

```yaml
# En config.yaml
context:
  max_tool_result_tokens: 2000
  compress_threshold: 0.75
  keep_recent_steps: 4
  max_context_tokens: 100000
```

---

## MEJORA 3 — Plan Integrado en Build

### El Principio

> Claude Code no tiene una "fase plan" → "fase build". El agente planifica,
> ejecuta, verifica y re-planifica todo en el mismo loop. Es más natural.

### 3.1 — Eliminar MixedModeRunner

**Borrar completamente** la clase `MixedModeRunner` del plan v1. No se necesita.

### 3.2 — Nuevo Prompt de Build (con planificación integrada)

```python
# src/architect/agents/prompts.py

BUILD_PROMPT = """Eres un agente de desarrollo de software. Trabajas de forma metódica y verificas tu trabajo.

## Tu proceso de trabajo

1. ANALIZAR: Lee los archivos relevantes y entiende el contexto antes de actuar
2. PLANIFICAR: Piensa en los pasos necesarios y el orden correcto
3. EJECUTAR: Haz los cambios paso a paso
4. VERIFICAR: Después de cada cambio, comprueba que funciona
5. CORREGIR: Si algo falla, analiza el error y corrígelo

## Reglas

- Siempre lee un archivo antes de editarlo
- Usa search_code o grep para encontrar código relevante en vez de adivinar
- Para cambios pequeños, usa edit_file (reemplazar texto exacto)
- Para cambios múltiples dispersos, usa apply_patch (unified diff)
- Solo usa write_file para archivos nuevos o reescrituras completas
- Si un comando o test falla, analiza el error e intenta corregirlo
- Cuando hayas completado la tarea, explica qué hiciste y qué archivos cambiaste

## Importante

- NO pidas confirmación ni hagas preguntas — actúa con la información disponible
- Si no tienes suficiente información, busca en el código antes de asumir
- Haz el mínimo de cambios necesarios para completar la tarea"""


PLAN_PROMPT = """Eres un agente de análisis y planificación. Tu trabajo es entender una tarea
y producir un plan detallado SIN ejecutar cambios.

## Tu proceso

1. Lee los archivos relevantes para entender el contexto
2. Analiza qué cambios son necesarios
3. Produce un plan estructurado con:
   - Qué archivos hay que crear/modificar/borrar
   - Qué cambios concretos en cada archivo
   - En qué orden hacerlos
   - Posibles riesgos o dependencias

## Reglas

- NO modifiques ningún archivo
- Usa read_file, search_code, grep y list_files para investigar
- Sé específico: no digas "modificar auth.py", di "en auth.py, añadir validación de token en la función validate() línea ~45"
- Si algo es ambiguo, indica las opciones y recomienda una"""


RESUME_PROMPT = """Eres un agente de análisis y resumen. Tu trabajo es leer información
y producir un resumen claro y conciso. No modificas archivos.

Sé directo. No repitas lo que ya sabe el usuario. Céntrate en lo importante."""


REVIEW_PROMPT = """Eres un agente de revisión de código. Tu trabajo es inspeccionar código
y dar feedback constructivo y accionable.

## Qué buscar
- Bugs y errores lógicos
- Problemas de seguridad
- Oportunidades de simplificación
- Code smells y violaciones de principios SOLID
- Tests que faltan

## Reglas
- NO modifiques ningún archivo
- Sé específico: indica archivo, línea y el problema concreto
- Prioriza: primero bugs/seguridad, luego mejoras, luego estilo"""
```

### 3.3 — Nuevo Agente Default

Cuando el usuario ejecuta `architect run "..."` **sin especificar `-a`**, se usa directamente el agente `build`:

```python
# src/architect/agents/registry.py

DEFAULT_AGENTS = {
    "build": AgentConfig(
        system_prompt=BUILD_PROMPT,
        allowed_tools=[
            "read_file", "write_file", "edit_file", "apply_patch",
            "delete_file", "list_files", "search_code", "grep",
            "find_files", "run_command",
        ],
        confirm_mode="confirm-sensitive",
        max_steps=50,  # ← Más holgado porque el LLM decide cuándo parar
    ),
    "plan": AgentConfig(
        system_prompt=PLAN_PROMPT,
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",  # Plan no modifica nada, no necesita confirmar
        max_steps=20,
    ),
    "resume": AgentConfig(
        system_prompt=RESUME_PROMPT,
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=15,
    ),
    "review": AgentConfig(
        system_prompt=REVIEW_PROMPT,
        allowed_tools=["read_file", "list_files", "search_code", "grep", "find_files"],
        confirm_mode="yolo",
        max_steps=20,
    ),
}

DEFAULT_AGENT = "build"
```

Nota: `max_steps=50` parece alto, pero recuerda que ahora es un watchdog, no el driver del loop. Claude Code en modo interactivo **no tiene límite de steps** — el modelo para cuando quiere. 50 es un safety net generoso para modo headless.

---

## MEJORA 4 — Auto-Verificación Post-Edit

### El Principio

> Después de editar un archivo, ejecutar automáticamente linter/tests
> y devolver el resultado al agente para que pueda auto-corregir.

### 4.1 — Sistema de Hooks

```python
# src/architect/core/hooks.py
from dataclasses import dataclass

@dataclass
class HookConfig:
    """Configuración de un hook post-edit."""
    name: str
    command: str              # Comando a ejecutar
    file_patterns: list[str]  # Globs: ["*.py", "*.js"]
    timeout: int = 15         # Timeout del comando
    enabled: bool = True

class PostEditHooks:
    """
    Ejecuta hooks automáticamente después de que el agente edite un archivo.
    Los resultados se devuelven al agente como tool results adicionales.
    """

    def __init__(self, hooks: list[HookConfig], workspace_root: Path):
        self.hooks = [h for h in hooks if h.enabled]
        self.root = workspace_root

    def run_for_file(self, file_path: str) -> ToolCallResult | None:
        """
        Ejecuta hooks que matchean el archivo editado.
        Retorna el resultado combinado, o None si no hay hooks que apliquen.
        """
        matching = [
            h for h in self.hooks
            if self._matches(file_path, h.file_patterns)
        ]
        if not matching:
            return None

        combined_output = []
        any_failed = False

        for hook in matching:
            try:
                result = subprocess.run(
                    hook.command,
                    shell=True,
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    timeout=hook.timeout,
                    stdin=subprocess.DEVNULL,
                    env={**os.environ, "ARCHITECT_EDITED_FILE": file_path},
                )
                if result.returncode != 0:
                    any_failed = True
                    combined_output.append(
                        f"⚠️ Hook '{hook.name}' falló (exit {result.returncode}):\n"
                        f"{result.stdout[-500:]}\n{result.stderr[-300:]}"
                    )
                else:
                    combined_output.append(f"✓ Hook '{hook.name}': OK")
            except subprocess.TimeoutExpired:
                combined_output.append(f"⚠️ Hook '{hook.name}': timeout ({hook.timeout}s)")
                any_failed = True

        if not combined_output:
            return None

        return ToolCallResult(
            tool_name="_auto_verify",
            args={"file": file_path, "hooks": [h.name for h in matching]},
            result=ToolResult(
                success=not any_failed,
                output="\n".join(combined_output),
                error="Algunos hooks de verificación fallaron" if any_failed else None,
            ),
        )

    def _matches(self, file_path: str, patterns: list[str]) -> bool:
        from fnmatch import fnmatch
        return any(fnmatch(file_path, p) for p in patterns)
```

### 4.2 — Integración en Execution Engine

```python
# En execution/engine.py
class ExecutionEngine:
    def __init__(self, ..., hooks: PostEditHooks | None = None):
        self.hooks = hooks

    def run_post_edit_hooks(self, tool_name: str, args: dict) -> ToolCallResult | None:
        """Ejecuta hooks después de una edición. Llamado por el loop."""
        if not self.hooks:
            return None
        file_path = args.get("path")
        if not file_path:
            return None
        return self.hooks.run_for_file(file_path)
```

### 4.3 — Configuración

```yaml
hooks:
  post_edit:
    - name: "python-lint"
      command: "ruff check $ARCHITECT_EDITED_FILE --no-fix"
      file_patterns: ["*.py"]
      timeout: 10

    - name: "python-typecheck"
      command: "mypy $ARCHITECT_EDITED_FILE --no-error-summary"
      file_patterns: ["*.py"]
      timeout: 15
      enabled: false  # Deshabilitado por defecto

    - name: "js-lint"
      command: "eslint $ARCHITECT_EDITED_FILE"
      file_patterns: ["*.js", "*.ts", "*.jsx", "*.tsx"]
      timeout: 10

    - name: "test-runner"
      command: "pytest --tb=short -q"
      file_patterns: ["*.py"]
      timeout: 30
      enabled: false  # Activar manualmente
```

El hook `_auto_verify` se devuelve al LLM como un tool result más. Si el linter falla, el LLM ve el error y puede corregirlo automáticamente en el siguiente step — sin que nadie se lo pida.

---

## MEJORA 5 — Log Level "Human"

### El Principio

> Un nuevo nivel de log que muestre la trazabilidad del agente
> de forma legible para humanos: qué está haciendo en cada momento,
> con iconos y formato claro, sin ruido técnico.

### 5.1 — Diseño del Nivel "Human"

El nivel `human` se sitúa entre `info` y `warn` en jerarquía. Pero conceptualmente es diferente: no indica severidad, indica **trazabilidad de alto nivel**.

```
Jerarquía de niveles:
  debug   → Todo (HTTP payloads, args completos, timing)
  info    → Operaciones del sistema (config loaded, tool registered, etc)
  human   → ★ Trazabilidad del agente (LLM call, tool use, resultado)
  warn    → Problemas no fatales
  error   → Errores
```

Lo que muestra `human` y lo que no:

| Muestra | No muestra |
|---------|-----------|
| Llamada al LLM (paso N) | Payload HTTP |
| Resultado LLM (OK/error) | Contenido completo de la respuesta |
| Tool invocada (nombre + path/resumen) | Argumentos completos |
| Resultado de tool (OK/error + resumen) | Output completo de la tool |
| Safety net activado | Detalles internos del context manager |
| Agente terminó (razón) | Estimaciones de tokens |
| Coste acumulado (si tracking activo) | Detalles de pricing |

### 5.2 — Formato Visual

```
─── architect · build · gpt-4.1 ───────────────────

🔄 Paso 1 → Llamada al LLM (3 mensajes)
   ✓ LLM respondió con 2 tool calls

   🔧 read_file → src/main.py
      ✓ OK (142 líneas)

   🔧 read_file → src/config.py
      ✓ OK (89 líneas)

🔄 Paso 2 → Llamada al LLM (7 mensajes)
   ✓ LLM respondió con 1 tool call

   🔧 edit_file → src/main.py
      ✓ Editado (+5 -3 líneas)
      🔍 Hook python-lint: OK
      🔍 Hook python-typecheck: 1 error
         → src/main.py:45: error: Argument 1 has incompatible type

🔄 Paso 3 → Llamada al LLM (10 mensajes)
   ✓ LLM respondió con 1 tool call

   🔧 edit_file → src/main.py
      ✓ Editado (+2 -1 líneas)
      🔍 Hook python-lint: OK
      🔍 Hook python-typecheck: OK

🔄 Paso 4 → Llamada al LLM (13 mensajes)
   ✓ LLM respondió con texto final

✅ Agente completado (4 pasos)
   Razón: LLM decidió que terminó
   Coste: $0.0234 (12,450 tokens in / 3,200 out)

─── Resultado ─────────────────────────────────
He modificado src/main.py para añadir validación
de tipos en la función process_data()...
```

Con MCP tools se diferencia visualmente:

```
   🔧 read_file → src/main.py           (tool local)
   🌐 mcp_tools1_search → "auth utils"   (tool MCP: tools1)
```

Cuando un safety net salta:

```
⚠️  Límite de pasos alcanzado (50/50)
    Pidiendo al agente que resuma...

🔄 Cierre → Llamada al LLM (sin tools)
   ✓ LLM respondió con resumen

⚡ Agente detenido parcialmente (50 pasos)
   Razón: Límite de pasos
   Coste: $0.1523
```

### 5.3 — Implementación

```python
# src/architect/logging/levels.py
import logging

# Nivel custom entre INFO (20) y WARNING (30)
HUMAN = 25
logging.addLevelName(HUMAN, "HUMAN")


def human(self, message, *args, **kwargs):
    """Logger method para nivel HUMAN."""
    if self.isEnabledFor(HUMAN):
        self._log(HUMAN, message, *args, **kwargs)


# Monkey-patch en Logger
logging.Logger.human = human
```

```python
# src/architect/logging/human.py
import sys
from typing import Any

class HumanFormatter:
    """
    Formateador de logs nivel HUMAN.
    Produce output legible con iconos y estructura clara.
    """

    # Iconos por tipo de evento
    ICONS = {
        "llm.call":        "🔄",
        "llm.response":    "   ✓",
        "llm.error":       "   ✗",
        "tool.call":       "   🔧",
        "tool.call.mcp":   "   🌐",
        "tool.result":     "      ✓",
        "tool.result.err": "      ✗",
        "hook.result":     "      🔍",
        "hook.result.err": "      🔍",
        "safety.max_steps":    "⚠️ ",
        "safety.budget":       "⚠️ ",
        "safety.timeout":      "⚠️ ",
        "safety.context_full": "⚠️ ",
        "agent.done":      "✅",
        "agent.closing":   "⚡",
        "agent.failed":    "❌",
        "context.compress":"   📦",
    }

    def __init__(self, show_costs: bool = True):
        self.show_costs = show_costs
        self.current_step = -1

    def format(self, event: str, **kw) -> str | None:
        """Formatea un evento a texto legible. Retorna None si no aplica."""

        match event:

            # ─── LLM ───
            case "llm.call":
                step = kw.get("step", "?")
                msgs = kw.get("messages_count", "?")
                if step != self.current_step:
                    self.current_step = step
                    return f"\n🔄 Paso {step + 1} → Llamada al LLM ({msgs} mensajes)"
                return None

            case "llm.response":
                tool_count = kw.get("tool_calls", 0)
                if tool_count:
                    return f"   ✓ LLM respondió con {tool_count} tool call{'s' if tool_count > 1 else ''}"
                return "   ✓ LLM respondió con texto final"

            case "llm.error":
                return f"   ✗ Error del LLM: {kw.get('error', 'desconocido')}"

            # ─── TOOLS ───
            case "tool.call":
                tool = kw.get("tool", "?")
                summary = kw.get("args_summary", "")
                is_mcp = kw.get("is_mcp", False)

                if is_mcp:
                    server = kw.get("mcp_server", "")
                    return f"   🌐 {tool} → {summary}  (MCP: {server})"
                return f"   🔧 {tool} → {summary}"

            case "tool.result":
                tool = kw.get("tool", "?")
                ok = kw.get("success", False)
                detail = kw.get("detail", "")
                icon = "✓" if ok else "✗"
                line = f"      {icon} {detail}" if detail else f"      {icon} {'OK' if ok else 'Error'}"
                return line

            # ─── HOOKS ───
            case "hook.result":
                hook = kw.get("hook", "?")
                ok = kw.get("success", True)
                icon = "✓" if ok else "⚠️"
                detail = kw.get("detail", "")
                return f"      🔍 Hook {hook}: {icon} {detail}".rstrip()

            # ─── SAFETY ───
            case "safety.max_steps":
                step = kw.get("step", "?")
                mx = kw.get("max", "?")
                return f"\n⚠️  Límite de pasos alcanzado ({step}/{mx})\n    Pidiendo al agente que resuma..."

            case "safety.budget":
                spent = kw.get("spent", 0)
                budget = kw.get("budget", 0)
                return f"\n⚠️  Presupuesto excedido (${spent:.4f} / ${budget:.4f})\n    Pidiendo al agente que resuma..."

            case "safety.timeout":
                return "\n⚠️  Timeout alcanzado\n    Pidiendo al agente que resuma..."

            # ─── AGENT LIFECYCLE ───
            case "agent.done":
                step = kw.get("step", "?")
                return f"\n✅ Agente completado ({step} pasos)\n   Razón: LLM decidió que terminó"

            case "agent.closing":
                reason = kw.get("reason", "?")
                return f"\n🔄 Cierre → Llamada al LLM (sin tools)"

            case "agent.partial":
                steps = kw.get("steps", "?")
                reason = kw.get("reason", "?")
                cost_line = ""
                if self.show_costs and kw.get("cost"):
                    cost_line = f"\n   Coste: ${kw['cost']:.4f}"
                return f"\n⚡ Agente detenido parcialmente ({steps} pasos)\n   Razón: {reason}{cost_line}"

            # ─── CONTEXT ───
            case "context.compress":
                before = kw.get("before_tokens", "?")
                after = kw.get("after_tokens", "?")
                return f"   📦 Contexto comprimido ({before} → {after} tokens)"

            case _:
                return None


class HumanLogHandler(logging.Handler):
    """Handler que filtra solo eventos HUMAN y los formatea."""

    def __init__(self, stream=None, show_costs=True):
        super().__init__(level=HUMAN)
        self.stream = stream or sys.stderr
        self.formatter = HumanFormatter(show_costs=show_costs)

    def emit(self, record):
        try:
            event = getattr(record, "event", record.getMessage())
            kw = getattr(record, "kw", {})
            formatted = self.formatter.format(event, **kw)
            if formatted:
                self.stream.write(formatted + "\n")
                self.stream.flush()
        except Exception:
            self.handleError(record)
```

### 5.4 — Integración con structlog

```python
# src/architect/logging/setup.py
import structlog
import logging
from .levels import HUMAN
from .human import HumanLogHandler

def configure_logging(
    config: LoggingConfig,
    json_output: bool,
    quiet: bool,
    show_costs: bool = True,
):
    """
    Configura tres pipelines de logging:

    1. Archivo JSON (si configurado) → Todo, estructurado
    2. Human handler (stderr) → Solo eventos de trazabilidad del agente
    3. Console handler (stderr) → Debug/info técnico (controlado por -v)
    """

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    # ─── 1. Archivo JSON (siempre, si configurado) ───
    if config.file:
        file_handler = logging.FileHandler(str(config.file))
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(message)s'  # structlog ya formatea como JSON
        ))
        root_logger.addHandler(file_handler)

    # ─── 2. Human handler (el nuevo) ───
    if not quiet and not json_output:
        human_handler = HumanLogHandler(show_costs=show_costs)
        # Solo pasa eventos nivel HUMAN (25), no INFO, no DEBUG
        human_handler.setLevel(HUMAN)
        human_handler.addFilter(lambda record: record.levelno == HUMAN)
        root_logger.addHandler(human_handler)

    # ─── 3. Console técnico (controlado por -v) ───
    if not quiet and not json_output:
        console_handler = logging.StreamHandler(sys.stderr)
        verbose_level = _verbose_to_level(config.verbose)
        console_handler.setLevel(verbose_level)
        # Excluir eventos HUMAN del console handler (ya los muestra human_handler)
        console_handler.addFilter(lambda record: record.levelno != HUMAN)
        root_logger.addHandler(console_handler)

    # Configurar structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )


def _verbose_to_level(verbose: int) -> int:
    """
    Sin -v  → Solo human (no se ve info ni debug técnico)
    -v      → INFO (steps internos, config, etc)
    -vv     → DEBUG (args completos, HTTP, timing)
    """
    match verbose:
        case 0:
            return logging.WARNING  # Solo warnings/errors (human va por otro handler)
        case 1:
            return logging.INFO
        case _:
            return logging.DEBUG
```

### 5.5 — Cómo Emitir Logs Human desde el Código

Para emitir un log `human` con structlog:

```python
# Opción A: usar el nivel directamente
import structlog
log = structlog.get_logger()

# Dentro del agent loop:
log.log(HUMAN, "llm.call", step=step, messages_count=len(messages))
log.log(HUMAN, "tool.call", tool="read_file", args_summary="src/main.py", is_mcp=False)
log.log(HUMAN, "tool.result", tool="read_file", success=True, detail="142 líneas")
```

Alternativa más limpia con un wrapper:

```python
# src/architect/logging/human.py (añadir al final)

class HumanLog:
    """Helper para emitir logs de nivel HUMAN con semántica clara."""

    def __init__(self, logger: structlog.BoundLogger):
        self._log = logger

    def llm_call(self, step: int, messages_count: int):
        self._log.log(HUMAN, "llm.call", step=step, messages_count=messages_count)

    def llm_response(self, tool_calls: int = 0):
        self._log.log(HUMAN, "llm.response", tool_calls=tool_calls)

    def llm_error(self, error: str):
        self._log.log(HUMAN, "llm.error", error=error)

    def tool_call(self, name: str, args_summary: str, is_mcp: bool = False,
                  mcp_server: str = ""):
        self._log.log(HUMAN, "tool.call", tool=name, args_summary=args_summary,
                       is_mcp=is_mcp, mcp_server=mcp_server)

    def tool_result(self, name: str, success: bool, detail: str = ""):
        self._log.log(HUMAN, "tool.result", tool=name, success=success, detail=detail)

    def hook_result(self, hook: str, success: bool, detail: str = ""):
        self._log.log(HUMAN, "hook.result", hook=hook, success=success, detail=detail)

    def safety_net(self, reason: str, **kw):
        self._log.log(HUMAN, f"safety.{reason}", **kw)

    def agent_done(self, step: int):
        self._log.log(HUMAN, "agent.done", step=step)

    def agent_partial(self, steps: int, reason: str, cost: float | None = None):
        self._log.log(HUMAN, "agent.partial", steps=steps, reason=reason, cost=cost)

    def context_compress(self, before_tokens: int, after_tokens: int):
        self._log.log(HUMAN, "context.compress",
                       before_tokens=before_tokens, after_tokens=after_tokens)
```

Uso en el loop:

```python
class AgentLoop:
    def __init__(self, ...):
        self.hlog = HumanLog(structlog.get_logger())

    def run(self, prompt):
        # ...
        self.hlog.llm_call(step=step, messages_count=len(state.messages))
        response = self.llm.completion(...)
        self.hlog.llm_response(tool_calls=len(response.tool_calls))

        for tc in response.tool_calls:
            self.hlog.tool_call(
                name=tc.name,
                args_summary=self._summarize_args(tc.arguments),
                is_mcp=tc.name.startswith("mcp_"),
                mcp_server=tc.name.split("_")[1] if tc.name.startswith("mcp_") else "",
            )
```

### 5.6 — Qué Nivel Se Ve Con Cada Flag

| Flag | Ve HUMAN | Ve INFO | Ve DEBUG | Ve archivos JSON |
|------|----------|---------|----------|------------------|
| (ninguno) | ✅ | ❌ | ❌ | Si configurado |
| `-v` | ✅ | ✅ | ❌ | Si configurado |
| `-vv` | ✅ | ✅ | ✅ | Si configurado |
| `--quiet` | ❌ | ❌ | ❌ | Si configurado |
| `--json` | ❌ | ❌ | ❌ | Si configurado |
| `--log-level human` | ✅ | ❌ | ❌ | Si configurado |

**Comportamiento por defecto (sin flags)**: El usuario solo ve los logs `human`. Es la experiencia ideal para seguir qué hace el agente sin ruido.

### 5.7 — Banner Inicial y Resultado Final

```python
# Al inicio de la ejecución:
def print_banner(agent: str, model: str):
    """Banner human-readable al inicio."""
    print(f"\n─── architect · {agent} · {model} {'─' * (40 - len(agent) - len(model))}\n",
          file=sys.stderr)

# Al final:
def print_result_separator():
    print(f"\n─── Resultado {'─' * 40}\n", file=sys.stderr)
```

---

## MEJORA 6 — Ajustes Args Summarizer para Logs

Para que los logs human sean legibles, necesitamos un helper que resuma los argumentos de cada tool de forma inteligente:

```python
# En core/loop.py (o en logging/human.py)

def _summarize_args(self, tool_name: str, args: dict) -> str:
    """
    Resume args de una tool para el log human.
    Cada tool tiene su resumen óptimo.
    """
    match tool_name:
        case "read_file" | "delete_file":
            return args.get("path", "?")

        case "write_file":
            path = args.get("path", "?")
            content = args.get("content", "")
            lines = content.count("\n") + 1
            return f"{path} ({lines} líneas)"

        case "edit_file":
            path = args.get("path", "?")
            old = args.get("old_content", "")
            new = args.get("new_content", "")
            return f"{path} ({len(old.splitlines())}→{len(new.splitlines())} líneas)"

        case "apply_patch":
            path = args.get("path", "?")
            patch = args.get("patch", "")
            added = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
            return f"{path} (+{added} -{removed})"

        case "search_code":
            return f'"{args.get("pattern", "?")}" en {args.get("path", ".")}'

        case "grep":
            return f'"{args.get("text", "?")}" en {args.get("path", ".")}'

        case "list_files" | "find_files":
            return args.get("path", args.get("pattern", "."))

        case "run_command":
            cmd = args.get("command", "?")
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            return cmd

        case _:
            # MCP u otra tool — mostrar primer arg o resumen genérico
            first_val = next(iter(args.values()), "")
            if isinstance(first_val, str) and len(first_val) > 60:
                first_val = first_val[:57] + "..."
            return str(first_val) if first_val else "(sin args)"
```

---

## Integración: Cómo Queda el Flujo Completo

```python
# src/architect/cli.py — Flujo principal simplificado

@main.command()
def run(prompt, **kwargs):
    # 1. Config
    config = load_config(kwargs)

    # 2. Logging (con human level)
    configure_logging(config.logging, kwargs["json_output"], kwargs["quiet"])
    print_banner(agent_name, config.llm.model)

    # 3. LLM
    llm = LLMAdapter(config.llm)

    # 4. Tools
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)
    register_search_tools(registry, config.workspace)
    register_command_tool(registry, config.commands)

    # 5. MCP (si habilitado)
    if not kwargs["disable_mcp"]:
        MCPDiscovery().discover_and_register(config.mcp.servers, registry)

    # 6. Hooks post-edit
    hooks = PostEditHooks(config.hooks.post_edit, config.workspace.root)

    # 7. Context Manager (NUEVO — integrado desde el core)
    context_mgr = ContextManager(config.context, llm)

    # 8. Cost Tracker
    cost_tracker = CostTracker(budget_usd=kwargs.get("budget")) if config.costs.enabled else None

    # 9. Agent Config
    agent_config = resolve_agent(kwargs["agent"], config.agents)
    if kwargs.get("mode"):
        agent_config = agent_config.model_copy(update={"confirm_mode": kwargs["mode"]})

    # 10. Execution Engine
    engine = ExecutionEngine(
        registry=registry,
        config=config,
        confirm_mode=agent_config.confirm_mode,
        hooks=hooks,
    )
    engine.dry_run = kwargs["dry_run"]

    # 11. Agent Loop (NUEVO — while True)
    shutdown = GracefulShutdown()
    loop = AgentLoop(
        llm=llm,
        engine=engine,
        agent_config=agent_config,
        context_mgr=context_mgr,
        cost_tracker=cost_tracker,
        shutdown=shutdown,
        logger=structlog.get_logger(),
        timeout=kwargs.get("timeout"),
    )

    # 12. Ejecutar
    state = loop.run(prompt)

    # 13. Output
    print_result_separator()
    if kwargs["json_output"]:
        output = state.to_output_dict()
        if cost_tracker:
            output["costs"] = cost_tracker.summary()
        print(json.dumps(output, indent=2))
    elif not kwargs["quiet"]:
        print(state.final_output or "Sin resultado.")
        if cost_tracker and config.logging.verbose >= 0:
            c = cost_tracker.summary()
            print(
                f"\n   Coste: ${c['total_cost_usd']:.4f} "
                f"({c['total_input_tokens']} in / {c['total_output_tokens']} out)",
                file=sys.stderr,
            )

    # 14. Exit code
    exit_codes = {
        "success": 0,
        "partial": 2,
        "failed": 1,
    }
    sys.exit(exit_codes.get(state.status, 1))
```

---

## Cronograma de Esta v3

Estas mejoras reemplazan y re-orderan varias fases del plan original.

| Mejora v3 | Reemplaza | Días | Cuándo |
|-----------|-----------|------|--------|
| M1: Loop while True + safety nets | F2 (parcial) + F7 | 2 | Día 3-4 (con F2) |
| M2: ContextManager integrado | F11 (absorbido) | 1 | Día 4-5 (con F2) |
| M3: Plan integrado en build | F3 (simplificado) | 0.5 | Día 5 (con F3) |
| M4: Post-edit hooks | Nuevo | 1 | Día 6 (con F1) |
| M5: Log level human | F5 (ampliado) | 1.5 | Día 7-8 (con F5) |
| M6: Args summarizer | Nuevo (parte de M5) | 0.5 | Día 8 (con M5) |

**Ahorro neto**: F7 y F11 se absorben en M1 y M2. F3 se simplifica.

### Nuevo Cronograma Completo

```
F0  Scaffolding + Config            1 día      Día 1
F1  Tools + Engine + Hooks (M4)     3 días     Día 2-4
F2  LLM + Loop (M1) + Context (M2) 3 días     Día 4-6
F3  Agentes (M3 integrado)         0.5 días   Día 7
F5  Logging + Human (M5+M6)         2 días     Día 7-8
F9  Diff inteligente                 3 días     Día 9-11
F10 Contexto inteligente (indexer)   3 días     Día 12-14
F13 run_command                      2 días     Día 14-15
F4  MCP                             2 días     Día 16-17
F6  Streaming + Output              1 día      Día 18
F12 Self-eval (opcional)             2 días     Día 19-20
F14 Cost + Cache                     2 días     Día 21-22
F8  Integración + docs              1 día      Día 23
────────────────────────────────────────────────
TOTAL                              ~23 días
```

Nota: Ahorramos ~4 días respecto al plan v2 (~27 días) porque F7 y F11 se absorben, F3 se simplifica, y la ruta crítica es más directa.

---

## Dependencias Actualizadas

```
F0 (scaffolding)
 ├── F1 (tools + engine + hooks M4)
 │    ├── F9 (diff inteligente)
 │    ├── F10 (contexto inteligente)
 │    ├── F13 (run_command)
 │    └── F2 (LLM + loop M1 + context M2)  ← CORE CRÍTICO
 │         ├── F3 (agentes M3)
 │         ├── F6 (streaming)
 │         ├── F12 (self-eval)
 │         └── F14 (cost + cache)
 ├── F4 (MCP) ← requiere F1
 └── F5 (logging + human M5) ← puede ser paralelo

F8 (integración) ← requiere todo
```

**Ruta crítica**: F0 → F1 → F2 (con M1+M2) → F3 (con M3) → F9 → F10 → F13

---

## Cambios Menores en Fases Existentes

### F0 — Config Schema

Añadir al schema de Pydantic:

```python
class ContextConfig(BaseModel):
    max_tool_result_tokens: int = 2000
    compress_threshold: float = 0.75
    keep_recent_steps: int = 4
    max_context_tokens: int = 100_000

class HookConfig(BaseModel):
    name: str
    command: str
    file_patterns: list[str]
    timeout: int = 15
    enabled: bool = True

class HooksConfig(BaseModel):
    post_edit: list[HookConfig] = Field(default_factory=list)

class LoggingConfig(BaseModel):
    level: Literal["debug", "info", "human", "warn", "error"] = "human"  # ← default cambiado
    file: Path | None = None
    verbose: int = 0
```

### F1 — Tool Registry

Cada tool debe implementar un método `summarize_args()` que el HumanLog usa:

```python
class BaseTool(ABC):
    # ... existente ...

    def summarize_args(self, args: dict) -> str:
        """Resumen legible de los argumentos para logs human."""
        return str(next(iter(args.values()), ""))
```

### F4 — MCP Tools

Las MCP tools deben marcarse para que los logs human las distingan:

```python
class MCPToolAdapter(BaseTool):
    is_mcp = True
    mcp_server_name: str  # Para el log human
```

### F14 — Cost Tracker

El cost tracker debe poder reportar coste acumulado al HumanLog al final de cada step:

```python
class CostTracker:
    def record(self, ...):
        # ... existente ...
        # Emitir log human si hay budget configurado y estamos al >70%
        if self.budget_usd and self.total_cost_usd > self.budget_usd * 0.7:
            self.log.log(HUMAN, "cost.warning",
                         spent=self.total_cost_usd, budget=self.budget_usd)
```

---

## Config YAML Ejemplo Completo (v3)

```yaml
llm:
  provider: litellm
  model: gpt-4.1
  api_base: http://localhost:8000
  api_key_env: LITELLM_API_KEY
  timeout: 60
  retries: 2
  stream: true
  prompt_caching: true

agents:
  build:
    confirm_mode: confirm-sensitive
    max_steps: 50
    # system_prompt se usa el default (BUILD_PROMPT)
    # allowed_tools se usa el default (todas)

  plan:
    confirm_mode: yolo
    max_steps: 20

  # Agente custom
  deploy:
    system_prompt: "Eres un agente de deployment..."
    allowed_tools: [read_file, run_command, search_code]
    confirm_mode: confirm-all
    max_steps: 15

context:
  max_tool_result_tokens: 2000
  compress_threshold: 0.75
  keep_recent_steps: 4
  max_context_tokens: 100000

logging:
  level: human          # ← nuevo default
  file: ~/.architect/logs.json
  verbose: 0

workspace:
  root: .
  allow_delete: true

hooks:
  post_edit:
    - name: python-lint
      command: "ruff check $ARCHITECT_EDITED_FILE --no-fix"
      file_patterns: ["*.py"]
      timeout: 10

    - name: test-runner
      command: "pytest --tb=short -q"
      file_patterns: ["*.py"]
      timeout: 30
      enabled: false

commands:
  enabled: true
  default_timeout: 30
  max_output_lines: 200

mcp:
  servers:
    - name: tools1
      url: https://mcp.example.com
      token_env: MCP_TOKEN

indexer:
  enabled: true
  max_file_size: 1000000

costs:
  enabled: true
  budget_usd: null
  warn_at_usd: null

evaluation:
  mode: "off"

cache:
  enabled: false
  dir: ~/.architect/cache
```

---

## Resumen de Todo Lo Que Cambia

```
CORE (cambios fundamentales):
  ✓ while True (LLM decide) en vez de for-range
  ✓ Cierre limpio en todos los safety nets
  ✓ ContextManager integrado desde el core
  ✓ Plan integrado en build (no fases separadas)
  ✓ MixedModeRunner eliminado

LOGGING (nuevo):
  ✓ Nivel HUMAN (25) entre INFO y WARNING
  ✓ HumanFormatter con iconos y formato legible
  ✓ HumanLog helper para emitir eventos tipados
  ✓ Distinción visual local vs MCP
  ✓ Banner + separador de resultado
  ✓ Default: solo human logs (sin -v)

AUTO-VERIFY (nuevo):
  ✓ PostEditHooks ejecuta lint/test después de editar
  ✓ Resultados vuelven al LLM como tool results
  ✓ Configurable por file pattern
  ✓ Deshabilitables individualmente

ARGS SUMMARIZER (nuevo):
  ✓ Cada tool produce un resumen legible de sus args
  ✓ Usado por HumanLog para logs concisos
```
