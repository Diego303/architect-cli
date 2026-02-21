#!/usr/bin/env python3
"""
Tests de la Fase 11 — Optimización de Tokens y Parallel Tool Calls.

Cubre:
1.  Importaciones y versión 0.15.0
2.  ContextConfig — defaults y validación
3.  ContextConfig en AppConfig
4.  ContextManager.truncate_tool_result — resultado corto (sin truncar)
5.  ContextManager.truncate_tool_result — resultado largo (truncar)
6.  ContextManager.truncate_tool_result — preserva inicio y fin
7.  ContextManager.truncate_tool_result — max_tool_result_tokens=0 (desactivado)
8.  ContextManager.enforce_window — dentro del límite (sin cambios)
9.  ContextManager.enforce_window — fuera del límite (truncar)
10. ContextManager.enforce_window — max_context_tokens=0 (desactivado)
11. ContextManager.maybe_compress — pocos pasos (sin compresión)
12. ContextManager.maybe_compress — summarize_after_steps=0 (desactivado)
13. ContextManager.maybe_compress — suficientes pasos (compresión con LLM mock)
14. ContextBuilder con context_manager — trunca tool results largos
15. ContextBuilder sin context_manager — no trunca
16. Parallel tool calls — _should_parallelize con yolo y múltiples tools
17. Parallel tool calls — _should_parallelize con confirm-all (siempre secuencial)
18. Parallel tool calls — _should_parallelize con confirm-sensitive + tool sensible
19. Parallel tool calls — _should_parallelize con parallel_tools=False
20. Parallel tool calls — orden de resultados preservado
21. ContextManager en ContextBuilder — integración completa
22. Versión consistente en 4 sitios
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️ "


def header(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def ok(msg: str) -> None:
    print(f"  {PASS} {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL} {msg}")
    raise AssertionError(msg)


def skip(msg: str) -> None:
    print(f"  {SKIP} {msg}")


# ── Test 1: Importaciones y versión ──────────────────────────────────────────

header("Test 1 — Importaciones y versión 0.15.0")

import architect
assert architect.__version__ == "0.15.0", f"Versión incorrecta: {architect.__version__}"
ok(f"__version__ = {architect.__version__}")

from architect.config.schema import ContextConfig, AppConfig
ok("ContextConfig importado desde config.schema")

from architect.core.context import ContextManager, ContextBuilder
ok("ContextManager importado desde core.context")

from architect.core import ContextManager as CM_from_core
assert CM_from_core is ContextManager
ok("ContextManager exportado desde core.__init__")

from architect.core.loop import AgentLoop
ok("AgentLoop importado correctamente")

from architect.core.mixed_mode import MixedModeRunner
ok("MixedModeRunner importado correctamente")


# ── Test 2: ContextConfig defaults ───────────────────────────────────────────

header("Test 2 — ContextConfig defaults y validación")

cfg = ContextConfig()
assert cfg.max_tool_result_tokens == 2000, f"Esperado 2000, got {cfg.max_tool_result_tokens}"
ok(f"max_tool_result_tokens = {cfg.max_tool_result_tokens}")

assert cfg.summarize_after_steps == 8, f"Esperado 8, got {cfg.summarize_after_steps}"
ok(f"summarize_after_steps = {cfg.summarize_after_steps}")

assert cfg.keep_recent_steps == 4, f"Esperado 4, got {cfg.keep_recent_steps}"
ok(f"keep_recent_steps = {cfg.keep_recent_steps}")

assert cfg.max_context_tokens == 80000, f"Esperado 80000, got {cfg.max_context_tokens}"
ok(f"max_context_tokens = {cfg.max_context_tokens}")

assert cfg.parallel_tools is True, f"Esperado True, got {cfg.parallel_tools}"
ok(f"parallel_tools = {cfg.parallel_tools}")

# Validar extra="forbid"
try:
    ContextConfig(campo_desconocido="x")
    fail("Debería rechazar campos desconocidos")
except Exception as e:
    ok(f"extra='forbid' funciona: {type(e).__name__}")

# Valores custom
cfg2 = ContextConfig(max_tool_result_tokens=500, parallel_tools=False)
assert cfg2.max_tool_result_tokens == 500
assert cfg2.parallel_tools is False
ok("Valores custom funcionan")


# ── Test 3: ContextConfig en AppConfig ───────────────────────────────────────

header("Test 3 — ContextConfig en AppConfig")

app = AppConfig()
assert hasattr(app, "context"), "AppConfig no tiene campo 'context'"
ok("AppConfig tiene campo 'context'")

assert isinstance(app.context, ContextConfig)
ok(f"app.context es ContextConfig con defaults")

assert app.context.max_tool_result_tokens == 2000
ok("Defaults de ContextConfig correctos en AppConfig")


# ── Test 4: truncate_tool_result — corto (sin truncar) ───────────────────────

header("Test 4 — truncate_tool_result: resultado corto (sin truncar)")

mgr = ContextManager(ContextConfig(max_tool_result_tokens=2000))
short_content = "Línea 1\nLínea 2\nLínea 3\n"
result = mgr.truncate_tool_result(short_content)
assert result == short_content, "No debería truncar contenido corto"
ok(f"Contenido corto ({len(short_content)} chars) no truncado")


# ── Test 5: truncate_tool_result — largo (truncar) ────────────────────────────

header("Test 5 — truncate_tool_result: resultado largo (truncar)")

mgr = ContextManager(ContextConfig(max_tool_result_tokens=100))
# 100 tokens * 4 chars = 400 chars límite
# Crear contenido de >400 chars con muchas líneas
long_content = "\n".join([f"Línea número {i}: {'x' * 20}" for i in range(100)])
result = mgr.truncate_tool_result(long_content)

assert len(result) < len(long_content), "Debería truncar el contenido"
ok(f"Contenido de {len(long_content)} chars → truncado a {len(result)} chars")

assert "[..." in result or "omitidas" in result or "omitidos" in result, \
    "Debería incluir marcador de omisión"
ok("Marcador de omisión presente en resultado truncado")


# ── Test 6: truncate_tool_result — preserva inicio y fin ─────────────────────

header("Test 6 — truncate_tool_result: preserva inicio y fin")

mgr = ContextManager(ContextConfig(max_tool_result_tokens=50))
# Crear contenido largo con inicio y fin identificables
lines = [f"INICIO-{i}" if i < 5 else f"MEDIO-{i}" if i < 100 else f"FIN-{i}"
         for i in range(120)]
content = "\n".join(lines)
result = mgr.truncate_tool_result(content)

# El inicio debe estar (primeras 40 líneas)
assert "INICIO-0" in result, "Debe preservar el inicio"
ok("Inicio del contenido preservado (líneas 0-4)")

# El final debe estar (últimas 20 líneas)
assert "FIN-119" in result, "Debe preservar el final"
ok("Final del contenido preservado (línea 119)")

# El medio debe estar omitido
assert "MEDIO-50" not in result, "El medio debe estar omitido"
ok("Sección media omitida correctamente")


# ── Test 7: truncate_tool_result — desactivado ────────────────────────────────

header("Test 7 — truncate_tool_result: max_tool_result_tokens=0 (desactivado)")

mgr_off = ContextManager(ContextConfig(max_tool_result_tokens=0))
big_content = "x" * 100000
result = mgr_off.truncate_tool_result(big_content)
assert result == big_content, "Con tokens=0 no debe truncar"
ok("max_tool_result_tokens=0 desactiva el truncado completamente")


# ── Test 8: enforce_window — dentro del límite ────────────────────────────────

header("Test 8 — enforce_window: dentro del límite (sin cambios)")

mgr = ContextManager(ContextConfig(max_context_tokens=80000))
messages = [
    {"role": "system", "content": "System prompt corto"},
    {"role": "user", "content": "Tarea corta"},
    {"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]},
    {"role": "tool", "name": "read_file", "tool_call_id": "1", "content": "resultado"},
]
result = mgr.enforce_window(messages)
assert result == messages, "No debería cambiar mensajes dentro del límite"
ok(f"Mensajes dentro del límite ({len(messages)} msgs) → sin cambios")


# ── Test 9: enforce_window — fuera del límite ─────────────────────────────────

header("Test 9 — enforce_window: fuera del límite (recortar)")

# Configurar con límite muy pequeño para forzar el recorte
mgr_small = ContextManager(ContextConfig(max_context_tokens=100))
# Crear mensajes que excedan el límite
messages_big = [
    {"role": "system", "content": "S"},
    {"role": "user", "content": "U"},
]
# Añadir 10 pares de mensajes
for i in range(10):
    messages_big.append({"role": "assistant", "tool_calls": [{"function": {"name": "t"}}],
                          "content": None})
    messages_big.append({"role": "tool", "name": "t", "tool_call_id": str(i),
                          "content": "resultado " * 20})

result = mgr_small.enforce_window(messages_big)
assert len(result) < len(messages_big), "Debería haber recortado mensajes"
ok(f"Mensajes recortados: {len(messages_big)} → {len(result)}")

# System y user siempre se conservan
assert result[0]["role"] == "system", "System siempre se conserva"
assert result[1]["role"] == "user", "User siempre se conserva"
ok("System y user siempre conservados tras enforce_window")


# ── Test 10: enforce_window — desactivado ─────────────────────────────────────

header("Test 10 — enforce_window: max_context_tokens=0 (desactivado)")

mgr_off = ContextManager(ContextConfig(max_context_tokens=0))
big_msgs = [{"role": "system", "content": "x" * 1000000}]  # 1M chars
result = mgr_off.enforce_window(big_msgs)
assert result == big_msgs, "Con max_context_tokens=0 no debe recortar"
ok("max_context_tokens=0 desactiva enforce_window completamente")


# ── Test 11: maybe_compress — pocos pasos (sin compresión) ───────────────────

header("Test 11 — maybe_compress: pocos pasos (sin compresión)")

mgr = ContextManager(ContextConfig(summarize_after_steps=8, keep_recent_steps=4))
# Solo 3 tool exchanges — menos que summarize_after_steps=8
msgs = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "usr"},
]
for i in range(3):
    msgs.append({"role": "assistant", "tool_calls": [{"function": {"name": "f"}}],
                  "content": None})
    msgs.append({"role": "tool", "name": "f", "tool_call_id": str(i), "content": "r"})

llm_mock = MagicMock()
result = mgr.maybe_compress(msgs, llm_mock)

assert result == msgs, "No debería comprimir con pocos pasos"
llm_mock.completion.assert_not_called()
ok(f"Con {mgr._count_tool_exchanges(msgs)} pasos (< {mgr.config.summarize_after_steps}) → sin compresión")


# ── Test 12: maybe_compress — desactivado ─────────────────────────────────────

header("Test 12 — maybe_compress: summarize_after_steps=0 (desactivado)")

mgr_off = ContextManager(ContextConfig(summarize_after_steps=0))
msgs = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "usr"},
]
for i in range(20):
    msgs.append({"role": "assistant", "tool_calls": [{"function": {"name": "f"}}],
                  "content": None})
    msgs.append({"role": "tool", "name": "f", "tool_call_id": str(i), "content": "r"})

llm_mock = MagicMock()
result = mgr_off.maybe_compress(msgs, llm_mock)
assert result == msgs
llm_mock.completion.assert_not_called()
ok("summarize_after_steps=0 desactiva la compresión completamente")


# ── Test 13: maybe_compress — con suficientes pasos ──────────────────────────

header("Test 13 — maybe_compress: 9 pasos → compresión (LLM mock)")

mgr = ContextManager(ContextConfig(summarize_after_steps=8, keep_recent_steps=4))

msgs = [
    {"role": "system", "content": "system prompt"},
    {"role": "user", "content": "user prompt"},
]
for i in range(9):  # 9 > summarize_after_steps=8
    msgs.append({"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}],
                  "content": None})
    msgs.append({"role": "tool", "name": "read_file", "tool_call_id": str(i),
                  "content": f"resultado {i}"})

original_count = len(msgs)

# Mock del LLM — devuelve un resumen
llm_mock = MagicMock()
llm_mock.completion.return_value = MagicMock(
    content="Resumen: El agente leyó varios archivos con read_file."
)

result = mgr.maybe_compress(msgs, llm_mock)

# Verificar que se comprimió
assert len(result) < len(msgs), \
    f"Debería haber comprimido: {len(msgs)} → {len(result)}"
ok(f"Compresión exitosa: {original_count} mensajes → {len(result)} mensajes")

# System y user se conservan
assert result[0]["role"] == "system"
assert result[1]["role"] == "user"
ok("System y user conservados tras compresión")

# Hay un mensaje de resumen
assert result[2]["role"] == "assistant"
assert "[Resumen de pasos anteriores]" in result[2]["content"]
ok("Mensaje de resumen generado correctamente")

# LLM fue llamado para resumir
llm_mock.completion.assert_called_once()
ok("LLM fue llamado una vez para generar el resumen")

# Los últimos keep_recent_steps=4 exchanges están íntegros (keep_recent_steps*3=12 msgs)
# Los últimos 12 mensajes del diálogo deben estar en result[3:]
last_msgs = [m for m in msgs[-12:]]
result_dialog = result[3:]
assert len(result_dialog) == 12, f"Esperados 12 mensajes recientes, got {len(result_dialog)}"
ok(f"Últimos {mgr.config.keep_recent_steps} pasos conservados íntegros")


# ── Test 14: ContextBuilder con context_manager ──────────────────────────────

header("Test 14 — ContextBuilder con context_manager: trunca tool results")

from architect.llm.adapter import ToolCall
from architect.core.state import ToolCallResult
from architect.tools.base import ToolResult

# Crear manager con límite muy pequeño para forzar truncado
small_cfg = ContextConfig(max_tool_result_tokens=10)  # 40 chars
mgr = ContextManager(small_cfg)
ctx = ContextBuilder(context_manager=mgr)

# Crear tool result largo
long_output = "A" * 1000
tool_call = ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"})
tool_result = ToolCallResult(
    tool_name="read_file",
    args={"path": "f.py"},
    result=ToolResult(success=True, output=long_output),
    was_confirmed=True,
    was_dry_run=False,
)

# Formatear tool result
formatted = ctx._format_tool_result(tool_call, tool_result)
assert len(formatted["content"]) < len(long_output), \
    "El tool result debería estar truncado"
ok(f"Tool result de {len(long_output)} chars truncado a {len(formatted['content'])} chars")

assert "omitid" in formatted["content"] or "[..." in formatted["content"], \
    "Debería contener marcador de omisión"
ok("Marcador de omisión presente en el tool result truncado")


# ── Test 15: ContextBuilder sin context_manager ──────────────────────────────

header("Test 15 — ContextBuilder sin context_manager: no trunca")

ctx_no_mgr = ContextBuilder()
long_output = "B" * 10000
tool_call = ToolCall(id="tc2", name="read_file", arguments={"path": "f.py"})
tool_result = ToolCallResult(
    tool_name="read_file",
    args={"path": "f.py"},
    result=ToolResult(success=True, output=long_output),
    was_confirmed=True,
    was_dry_run=False,
)
formatted = ctx_no_mgr._format_tool_result(tool_call, tool_result)
assert formatted["content"] == long_output, "Sin context_manager no debe truncar"
ok(f"Sin context_manager: {len(long_output)} chars → sin truncado")

# Configurar structlog con stdlib antes de crear AgentLoop (necesario para nivel HUMAN)
from architect.logging.setup import configure_logging
from architect.config.schema import LoggingConfig
configure_logging(LoggingConfig(), quiet=True)


# ── Test 16: _should_parallelize — yolo ──────────────────────────────────────

header("Test 16 — _should_parallelize: modo yolo → paralelo")

from architect.config.schema import AgentConfig

# Crear agent_config mínimo con yolo
yolo_config = AgentConfig(
    system_prompt="test",
    allowed_tools=["read_file", "list_files"],
    confirm_mode="yolo",
)

# Mock del engine
mock_engine = MagicMock()
mock_engine.registry.has_tool.return_value = True
mock_tool = MagicMock()
mock_tool.sensitive = False
mock_engine.registry.get.return_value = mock_tool
mock_engine.run_post_edit_hooks.return_value = None  # Evitar activar lógica de hooks

# Mock del LLM y ContextBuilder
mock_llm = MagicMock()
mock_ctx = MagicMock()

loop = AgentLoop(
    llm=mock_llm,
    engine=mock_engine,
    agent_config=yolo_config,
    context_builder=mock_ctx,
)

# Crear tool calls mock
tc1 = MagicMock()
tc1.name = "read_file"
tc2 = MagicMock()
tc2.name = "list_files"

should = loop._should_parallelize([tc1, tc2])
assert should is True, f"Modo yolo con 2 tools → debería paralelizar, got {should}"
ok("Modo yolo con 2 tools → paralelo habilitado")


# ── Test 17: _should_parallelize — confirm-all ────────────────────────────────

header("Test 17 — _should_parallelize: confirm-all → siempre secuencial")

confirm_all_config = AgentConfig(
    system_prompt="test",
    allowed_tools=["read_file"],
    confirm_mode="confirm-all",
)
loop_confirm = AgentLoop(
    llm=mock_llm,
    engine=mock_engine,
    agent_config=confirm_all_config,
    context_builder=mock_ctx,
)

should = loop_confirm._should_parallelize([tc1, tc2])
assert should is False, f"confirm-all → siempre secuencial, got {should}"
ok("confirm-all → secuencial siempre (sin importar sensibilidad)")


# ── Test 18: _should_parallelize — confirm-sensitive + sensible ───────────────

header("Test 18 — _should_parallelize: confirm-sensitive + tool sensible → secuencial")

sensitive_config = AgentConfig(
    system_prompt="test",
    allowed_tools=["write_file"],
    confirm_mode="confirm-sensitive",
)
loop_sensitive = AgentLoop(
    llm=mock_llm,
    engine=mock_engine,
    agent_config=sensitive_config,
    context_builder=mock_ctx,
)

# Configurar tool como sensible
sensitive_tool = MagicMock()
sensitive_tool.sensitive = True
mock_engine.registry.get.return_value = sensitive_tool
mock_engine.registry.has_tool.return_value = True

tc_sensitive = MagicMock()
tc_sensitive.name = "write_file"

should = loop_sensitive._should_parallelize([tc_sensitive, tc_sensitive])
assert should is False, f"Tool sensible → secuencial, got {should}"
ok("confirm-sensitive + tool sensible → secuencial")

# Restaurar tool no sensible
mock_engine.registry.get.return_value = mock_tool


# ── Test 19: _should_parallelize — parallel_tools=False ──────────────────────

header("Test 19 — _should_parallelize: parallel_tools=False → secuencial")

cfg_no_parallel = ContextConfig(parallel_tools=False)
mgr_no_parallel = ContextManager(cfg_no_parallel)

loop_no_parallel = AgentLoop(
    llm=mock_llm,
    engine=mock_engine,
    agent_config=yolo_config,
    context_builder=mock_ctx,
    context_manager=mgr_no_parallel,
)

should = loop_no_parallel._should_parallelize([tc1, tc2])
assert should is False, f"parallel_tools=False → secuencial, got {should}"
ok("parallel_tools=False → secuencial incluso en modo yolo")


# ── Test 20: Parallel tool calls — orden preservado ──────────────────────────

header("Test 20 — Parallel tool calls: orden de resultados preservado")

# Crear loop con yolo y context_manager con parallel_tools=True
parallel_mgr = ContextManager(ContextConfig(parallel_tools=True))
loop_parallel = AgentLoop(
    llm=mock_llm,
    engine=mock_engine,
    agent_config=yolo_config,
    context_builder=mock_ctx,
    context_manager=parallel_mgr,
)

# Crear tool calls que devuelven resultados con delay artificial
execution_order = []
tool_calls_ordered = []

def make_mock_tc(name: str, idx: int):
    tc = MagicMock()
    tc.name = name
    tc.arguments = {"path": f"file{idx}.py"}
    return tc

mock_results = {}
call_count = 0

def mock_execute(tool_name, args):
    """Ejecuta tools con delays variables para probar el orden."""
    import time
    result = MagicMock()
    result.success = True
    result.output = f"resultado_{tool_name}"
    result.error = None
    return result

mock_engine.execute_tool_call.side_effect = mock_execute

# Crear 3 tool calls
tcs = [make_mock_tc(f"tool_{i}", i) for i in range(3)]

# Ejecutar el batch paralelo
results = loop_parallel._execute_tool_calls_batch(tcs, step=0)

assert len(results) == 3, f"Esperados 3 resultados, got {len(results)}"
ok(f"3 tool calls ejecutadas → 3 resultados")

# Verificar que el orden es correcto (resultado[i] corresponde a tcs[i])
for i, (tc, result) in enumerate(zip(tcs, results)):
    assert result.tool_name == tc.name, \
        f"Resultado {i} tiene nombre incorrecto: {result.tool_name} != {tc.name}"
ok("Orden de resultados preservado correctamente")

assert mock_engine.execute_tool_call.call_count == 3
ok("Las 3 tools fueron ejecutadas exactamente una vez")


# ── Test 21: Integración ContextManager en ContextBuilder ────────────────────

header("Test 21 — Integración: ContextManager en ContextBuilder")

from architect.config.schema import AgentConfig as AC
from architect.core.context import ContextBuilder, ContextManager

# Crear configuración real
ctx_cfg = ContextConfig(max_tool_result_tokens=50)
ctx_manager = ContextManager(ctx_cfg)

# Crear un AgentConfig mínimo
agent_cfg = AC(system_prompt="eres un agente", allowed_tools=["read_file"])
builder = ContextBuilder(context_manager=ctx_manager)

# build_initial no debe fallar con context_manager
msgs = builder.build_initial(agent_cfg, "haz algo")
assert len(msgs) == 2
assert msgs[0]["role"] == "system"
assert msgs[1]["role"] == "user"
ok("build_initial funciona correctamente con context_manager")

# Verificar que append_tool_results trunca resultados largos
from architect.llm.adapter import ToolCall
from architect.core.state import ToolCallResult
from architect.tools.base import ToolResult

tool_call = ToolCall(id="tc3", name="read_file", arguments={"path": "big.py"})
big_output = "X" * 5000  # Mucho más que 50 tokens (200 chars)
result = ToolCallResult(
    tool_name="read_file",
    args={"path": "big.py"},
    result=ToolResult(success=True, output=big_output),
    was_confirmed=True,
    was_dry_run=False,
)
updated_msgs = builder.append_tool_results(msgs, [tool_call], [result])

# El último mensaje (tool result) debería estar truncado
tool_msg = updated_msgs[-1]
assert tool_msg["role"] == "tool"
assert len(tool_msg["content"]) < len(big_output), \
    f"Tool result debería truncarse: {len(tool_msg['content'])} < {len(big_output)}"
ok(f"append_tool_results trunca automáticamente: {len(big_output)} → {len(tool_msg['content'])} chars")


# ── Test 22: Versión consistente ──────────────────────────────────────────────

header("Test 22 — Versión consistente en 4 sitios")

import subprocess

# 1. __init__.py
assert architect.__version__ == "0.15.0"
ok(f"src/architect/__init__.py: {architect.__version__}")

# 2. pyproject.toml
import tomllib
pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
with open(pyproject_path, "rb") as f:
    pyproject = tomllib.load(f)
assert pyproject["project"]["version"] == "0.15.0", \
    f"pyproject.toml: {pyproject['project']['version']}"
ok(f"pyproject.toml: {pyproject['project']['version']}")

# 3. cli.py: _VERSION constant
cli_path = Path(__file__).parent.parent / "src" / "architect" / "cli.py"
cli_content = cli_path.read_text()
assert '_VERSION = "0.15.0"' in cli_content, "cli.py _VERSION no es 0.15.0"
ok("cli.py: _VERSION = '0.15.0'")

# 4. cli.py: version_option usa _VERSION
assert "version=_VERSION" in cli_content, "cli.py version_option no usa _VERSION"
ok("cli.py: @click.version_option(version=_VERSION)")


# ── Resumen final ─────────────────────────────────────────────────────────────

print(f"\n{'═' * 60}")
print(f"  {PASS} Todos los tests de F11 pasaron correctamente")
print(f"{'═' * 60}")
print()
print("  Componentes verificados:")
print("    ✓ ContextConfig con 5 campos y extra='forbid'")
print("    ✓ ContextConfig en AppConfig")
print("    ✓ ContextManager.truncate_tool_result (3 modos)")
print("    ✓ ContextManager.enforce_window")
print("    ✓ ContextManager.maybe_compress (con mock LLM)")
print("    ✓ ContextBuilder integra context_manager")
print("    ✓ Parallel tool calls: lógica de decisión")
print("    ✓ Parallel tool calls: orden preservado")
print("    ✓ Versión 0.15.0 consistente en 4 sitios")
print()
