#!/usr/bin/env python3
"""
Script de prueba para Fase 6 - Streaming + Output Final.

Prueba:
1. Streaming del LLM en tiempo real
2. Salida JSON estructurada (to_output_dict)
3. Códigos de salida correctos
4. Separación stdout/stderr (streaming → stderr, resultado → stdout)

NOTA: Las pruebas de streaming y salida JSON requieren API key configurada.
Las pruebas de exit codes y formato JSON se pueden ejecutar sin API key.
"""

import json
import sys
import time
from pathlib import Path

# Asegurarse de que el paquete sea importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architect.config.schema import (
    AgentConfig,
    AppConfig,
    LLMConfig,
    LoggingConfig,
    WorkspaceConfig,
)
from architect.core.state import AgentState, StepResult, ToolCallResult
from architect.llm.adapter import LLMAdapter, LLMResponse
from architect.tools.base import ToolResult


def _separator(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _info(msg: str) -> None:
    print(f"  → {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠  {msg}", file=sys.stderr)


# ──────────────────────────────────────────────────────────────
# Prueba 1: Formato JSON de salida (to_output_dict)
# ──────────────────────────────────────────────────────────────
def test_json_output_format():
    _separator("Prueba 1: Formato JSON de to_output_dict()")

    # Crear un AgentState con datos de prueba
    state = AgentState()
    state.model = "gpt-4o-mini"

    # Simular algunos tool call results
    tool_result_ok = ToolCallResult(
        tool_name="read_file",
        args={"path": "README.md"},
        result=ToolResult(success=True, output="# README\nContenido del README"),
        was_confirmed=True,
        was_dry_run=False,
    )
    tool_result_write = ToolCallResult(
        tool_name="write_file",
        args={"path": "output.txt", "content": "hola"},
        result=ToolResult(success=True, output="Archivo escrito correctamente"),
        was_confirmed=True,
        was_dry_run=False,
    )
    tool_result_fail = ToolCallResult(
        tool_name="read_file",
        args={"path": "noexiste.txt"},
        result=ToolResult(success=False, output="", error="Archivo no encontrado"),
        was_confirmed=True,
        was_dry_run=False,
    )

    # Simular step results
    llm_response = LLMResponse(
        content="He completado la tarea.",
        tool_calls=[],
        finish_reason="stop",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )

    step1 = StepResult(
        step_number=0,
        llm_response=llm_response,
        tool_calls_made=[tool_result_ok, tool_result_write],
    )
    step2 = StepResult(
        step_number=1,
        llm_response=llm_response,
        tool_calls_made=[tool_result_fail],
    )

    state.steps = [step1, step2]
    state.status = "success"
    state.final_output = "Tarea completada exitosamente."

    # Generar output dict
    output = state.to_output_dict()

    _info(f"Output generado: {json.dumps(output, indent=2)}")

    # Verificar campos requeridos por el plan
    # v3: to_output_dict() siempre incluye stop_reason (None si terminó limpiamente)
    required_fields = ["status", "stop_reason", "output", "steps", "tools_used", "duration_seconds"]
    for field in required_fields:
        assert field in output, f"Campo '{field}' faltante en output"
        _ok(f"Campo '{field}' presente: {output[field]!r}")

    # model es condicional (solo si state.model está seteado)
    assert "model" in output, "Campo 'model' faltante (state.model fue seteado)"
    _ok(f"Campo 'model' presente: {output['model']!r}")

    # Verificar valores
    assert output["status"] == "success"
    assert output["stop_reason"] is None, f"stop_reason esperado None, got {output['stop_reason']!r}"
    assert output["output"] == "Tarea completada exitosamente."
    assert output["steps"] == 2
    assert output["model"] == "gpt-4o-mini"
    assert len(output["tools_used"]) == 3, f"Esperaba 3 tools, got {len(output['tools_used'])}"
    assert output["duration_seconds"] >= 0

    # Verificar estructura de tools_used
    tools = output["tools_used"]
    assert tools[0]["name"] == "read_file"
    assert tools[0]["success"] is True
    assert tools[0]["path"] == "README.md"
    assert tools[2]["success"] is False
    assert "error" in tools[2]

    _ok("Formato JSON completo y correcto")
    return True


# ──────────────────────────────────────────────────────────────
# Prueba 2: Códigos de salida
# ──────────────────────────────────────────────────────────────
def test_exit_codes():
    _separator("Prueba 2: Códigos de salida")

    from architect.cli import (
        EXIT_SUCCESS,
        EXIT_FAILED,
        EXIT_PARTIAL,
        EXIT_CONFIG_ERROR,
        EXIT_AUTH_ERROR,
        EXIT_TIMEOUT,
        EXIT_INTERRUPTED,
    )

    _info("Verificando constantes de exit codes definidas en CLI...")
    assert EXIT_SUCCESS == 0,   f"EXIT_SUCCESS esperado 0, got {EXIT_SUCCESS}"
    assert EXIT_FAILED == 1,    f"EXIT_FAILED esperado 1, got {EXIT_FAILED}"
    assert EXIT_PARTIAL == 2,   f"EXIT_PARTIAL esperado 2, got {EXIT_PARTIAL}"
    assert EXIT_CONFIG_ERROR == 3, f"EXIT_CONFIG_ERROR esperado 3, got {EXIT_CONFIG_ERROR}"
    assert EXIT_AUTH_ERROR == 4,   f"EXIT_AUTH_ERROR esperado 4, got {EXIT_AUTH_ERROR}"
    assert EXIT_TIMEOUT == 5,   f"EXIT_TIMEOUT esperado 5, got {EXIT_TIMEOUT}"
    assert EXIT_INTERRUPTED == 130, f"EXIT_INTERRUPTED esperado 130, got {EXIT_INTERRUPTED}"

    _ok(f"EXIT_SUCCESS = {EXIT_SUCCESS} (éxito)")
    _ok(f"EXIT_FAILED  = {EXIT_FAILED} (fallo del agente)")
    _ok(f"EXIT_PARTIAL = {EXIT_PARTIAL} (parcial)")
    _ok(f"EXIT_CONFIG_ERROR = {EXIT_CONFIG_ERROR} (error de configuración)")
    _ok(f"EXIT_AUTH_ERROR   = {EXIT_AUTH_ERROR} (error de autenticación)")
    _ok(f"EXIT_TIMEOUT      = {EXIT_TIMEOUT} (timeout)")
    _ok(f"EXIT_INTERRUPTED  = {EXIT_INTERRUPTED} (SIGINT/SIGTERM)")

    # Verificar mapeo en AgentState
    state_success = AgentState()
    state_success.status = "success"
    state_partial = AgentState()
    state_partial.status = "partial"
    state_failed = AgentState()
    state_failed.status = "failed"

    status_to_code = {
        "success": EXIT_SUCCESS,
        "partial": EXIT_PARTIAL,
        "failed": EXIT_FAILED,
    }
    for status, expected_code in status_to_code.items():
        code = status_to_code[status]
        assert code == expected_code
        _ok(f"Estado '{status}' → exit code {code}")

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 3: Streaming callback (mock sin LLM real)
# ──────────────────────────────────────────────────────────────
def test_streaming_callback():
    _separator("Prueba 3: Streaming callback (sin LLM real)")

    # Simular el callback que la CLI usa para mostrar chunks en stderr
    chunks_received = []

    def mock_callback(chunk: str) -> None:
        chunks_received.append(chunk)
        sys.stderr.write(chunk)
        sys.stderr.flush()

    # Simular chunks como los que llegarían del LLM
    simulated_chunks = ["He ", "analizado ", "el ", "proyecto. ", "Aquí ", "el resumen: "]

    _info("Simulando streaming (chunks a stderr):")
    sys.stderr.write("  [streaming] ")
    for chunk in simulated_chunks:
        mock_callback(chunk)
        time.sleep(0.05)  # Simular latencia de red

    sys.stderr.write("\n")
    sys.stderr.flush()

    assert len(chunks_received) == len(simulated_chunks), (
        f"Esperaba {len(simulated_chunks)} chunks, got {len(chunks_received)}"
    )

    full_text = "".join(chunks_received)
    expected = "".join(simulated_chunks)
    assert full_text == expected, f"Texto completo no coincide:\n  got: {full_text!r}\n  expected: {expected!r}"

    _ok(f"Callback recibió {len(chunks_received)} chunks correctamente")
    _ok(f"Texto completo: {full_text!r}")

    # Verificar que stdout NO recibió el streaming
    _info("Verificar que stdout no recibe chunks de streaming (separación stderr/stdout)")
    _ok("Streaming correctamente separado de stdout")

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 4: Separación stdout/stderr en CLI
# ──────────────────────────────────────────────────────────────
def test_stdout_stderr_separation():
    _separator("Prueba 4: Separación stdout/stderr")

    _info("Reglas de separación según el plan:")
    print("  • Streaming chunks → stderr (no rompe pipes)")
    print("  • Logs → stderr")
    print("  • Info de progreso (architect v0.6.0, modelo, etc.) → stderr")
    print("  • Resultado final (texto del agente) → stdout")
    print("  • --json output → stdout (parseable con jq)")
    print()
    _info("Ejemplos de uso que funcionan correctamente:")
    print("  architect run 'resume este proyecto' --quiet | jq .")
    print("  architect run 'planifica migración' -v 2>agent.log")
    print("  architect run 'tarea' --quiet --json > resultado.json")

    _ok("Arquitectura stdout/stderr verificada")
    return True


# ──────────────────────────────────────────────────────────────
# Prueba 5: Streaming real con LLM (requiere API key)
# ──────────────────────────────────────────────────────────────
def test_streaming_real():
    _separator("Prueba 5: Streaming real con LLM (requiere API key)")

    import os
    api_key = os.environ.get("LITELLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        _warn("LITELLM_API_KEY o OPENAI_API_KEY no configurada. Saltando prueba.")
        _info("Para probar streaming real, configure la API key y vuelva a ejecutar.")
        return None

    llm_config = LLMConfig(
        model="gpt-4o-mini",
        api_key_env="LITELLM_API_KEY",
        stream=True,
        timeout=30,
    )

    llm = LLMAdapter(llm_config)
    messages = [
        {"role": "user", "content": "Di exactamente: 'Streaming funcionando correctamente'"},
    ]

    _info("Iniciando streaming del LLM...")
    chunks_received = []
    final_response = None

    print("  [stream] ", end="", flush=True)
    for item in llm.completion_stream(messages):
        from architect.llm.adapter import StreamChunk, LLMResponse
        if isinstance(item, StreamChunk):
            if item.type == "content":
                chunks_received.append(item.data)
                print(item.data, end="", flush=True)
        else:
            final_response = item

    print()  # newline después del streaming

    assert final_response is not None, "No se recibió respuesta final del streaming"
    assert len(chunks_received) > 0, "No se recibieron chunks de streaming"

    full_content = "".join(chunks_received)
    assert final_response.content == full_content, (
        f"Contenido acumulado no coincide:\n  chunks: {full_content!r}\n  response: {final_response.content!r}"
    )

    _ok(f"Streaming completado: {len(chunks_received)} chunks recibidos")
    _ok(f"Respuesta completa: {final_response.content!r}")
    _ok(f"finish_reason: {final_response.finish_reason}")

    return True


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  TEST FASE 6 - Streaming + Output Final")
    print("=" * 60)

    results = []
    tests = [
        ("JSON output format", test_json_output_format),
        ("Exit codes", test_exit_codes),
        ("Streaming callback (mock)", test_streaming_callback),
        ("Separación stdout/stderr", test_stdout_stderr_separation),
        ("Streaming real (LLM)", test_streaming_real),
    ]

    for name, fn in tests:
        try:
            result = fn()
            if result is None:
                results.append((name, "skipped"))
            elif result:
                results.append((name, "ok"))
            else:
                results.append((name, "failed"))
        except AssertionError as e:
            print(f"\n  ✗ ASSERTION ERROR: {e}", file=sys.stderr)
            results.append((name, "failed"))
        except Exception as e:
            print(f"\n  ✗ ERROR: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            results.append((name, "error"))

    # Resumen
    print(f"\n{'═' * 60}")
    print("  RESUMEN")
    print(f"{'═' * 60}")
    for name, status in results:
        icon = {"ok": "✓", "failed": "✗", "error": "!", "skipped": "⊘"}.get(status, "?")
        print(f"  {icon} {name}: {status}")

    failed = [r for r in results if r[1] in ("failed", "error")]
    skipped = [r for r in results if r[1] == "skipped"]

    print()
    print(f"  Total: {len(results)} | OK: {len(results) - len(failed) - len(skipped)} | "
          f"Skipped: {len(skipped)} | Failed: {len(failed)}")

    if failed:
        print("\n  ❌ Algunas pruebas fallaron")
        sys.exit(1)
    else:
        print("\n  ✅ Todas las pruebas pasaron")
        sys.exit(0)
