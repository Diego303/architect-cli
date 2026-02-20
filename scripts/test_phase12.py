"""
Tests para Fase 12 — Self-Evaluation (Critic Agent).

Cubre:
- EvalResult dataclass
- SelfEvaluator._parse_eval (3 estrategias JSON + fallback)
- SelfEvaluator._summarize_steps
- SelfEvaluator._build_correction_prompt
- SelfEvaluator.evaluate_basic (con LLM mock)
- SelfEvaluator.evaluate_full (con LLM y run_fn mocks)
- EvaluationConfig validación Pydantic
- Integración con AppConfig (evaluation: off/basic/full)
- Consistencia de versiones (0.12.0)

Uso:
    python scripts/test_phase12.py
    python scripts/test_phase12.py -v      # verbose
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Helpers ──────────────────────────────────────────────────────────────────

VERBOSE = "-v" in sys.argv

results: list[tuple[str, bool, str]] = []


def test(name: str):
    """Decorador de test que captura el resultado."""
    def decorator(fn):
        try:
            fn()
            results.append((name, True, ""))
            if VERBOSE:
                print(f"  ✓ {name}")
        except Exception as e:
            tb = traceback.format_exc()
            results.append((name, False, str(e) + "\n" + tb))
            if VERBOSE:
                print(f"  ✗ {name}: {e}")
        return fn
    return decorator


def assert_eq(a, b, msg=""):
    assert a == b, f"{msg}: {a!r} != {b!r}"


def assert_true(v, msg=""):
    assert v, msg


def assert_false(v, msg=""):
    assert not v, msg


def assert_in(item, container, msg=""):
    assert item in container, f"{msg}: {item!r} not in {container!r}"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def make_llm_mock(response_content: str) -> MagicMock:
    """Crea un LLMAdapter mock que devuelve response_content."""
    llm = MagicMock()
    completion_result = MagicMock()
    completion_result.content = response_content
    llm.completion.return_value = completion_result
    return llm


def make_state(
    final_output: str = "Tarea completada.",
    status: str = "success",
    steps_count: int = 3,
) -> MagicMock:
    """Crea un AgentState mock con pasos simulados."""
    state = MagicMock()
    state.final_output = final_output
    state.status = status
    state.current_step = steps_count
    state.total_tool_calls = steps_count * 2

    # Crear steps con tool_calls_made
    steps = []
    for i in range(steps_count):
        step = MagicMock()
        step.step_number = i
        tc1 = MagicMock()
        tc1.tool_name = "read_file"
        tc1.result = MagicMock()
        tc1.result.success = True
        tc2 = MagicMock()
        tc2.tool_name = "write_file"
        tc2.result = MagicMock()
        tc2.result.success = i != 2  # Último paso tiene un error
        step.tool_calls_made = [tc1, tc2]
        steps.append(step)

    state.steps = steps
    return state


# ── Tests EvalResult ─────────────────────────────────────────────────────────

@test("EvalResult: importar correctamente")
def _():
    from architect.core.evaluator import EvalResult
    result = EvalResult(completed=True, confidence=0.9)
    assert_eq(result.completed, True)
    assert_eq(result.confidence, 0.9)
    assert_eq(result.issues, [])
    assert_eq(result.suggestion, "")
    assert_eq(result.raw_response, "")


@test("EvalResult: con issues y suggestion")
def _():
    from architect.core.evaluator import EvalResult
    result = EvalResult(
        completed=False,
        confidence=0.3,
        issues=["Falta el archivo config.yaml", "Tests no ejecutados"],
        suggestion="Crea config.yaml y ejecuta pytest",
        raw_response='{"completed": false}',
    )
    assert_eq(len(result.issues), 2)
    assert_in("Falta el archivo config.yaml", result.issues)
    assert_eq(result.suggestion, "Crea config.yaml y ejecuta pytest")


@test("EvalResult: __repr__ muestra campos clave")
def _():
    from architect.core.evaluator import EvalResult
    result = EvalResult(
        completed=True,
        confidence=0.95,
        issues=[],
    )
    r = repr(result)
    assert_in("completed=True", r)
    assert_in("95%", r)
    assert_in("issues=0", r)


# ── Tests _parse_eval ─────────────────────────────────────────────────────────

@test("_parse_eval: JSON directo válido")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    content = '{"completed": true, "confidence": 0.9, "issues": [], "suggestion": ""}'
    result = evaluator._parse_eval(content)
    assert_eq(result.completed, True)
    assert_eq(result.confidence, 0.9)
    assert_eq(result.issues, [])


@test("_parse_eval: JSON en bloque de código ```json```")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    content = (
        "Aquí está mi evaluación:\n"
        "```json\n"
        '{"completed": false, "confidence": 0.4, "issues": ["Falta output"], "suggestion": "Completa la tarea"}\n'
        "```\n"
    )
    result = evaluator._parse_eval(content)
    assert_eq(result.completed, False)
    assert_eq(result.confidence, 0.4)
    assert_eq(result.issues, ["Falta output"])
    assert_eq(result.suggestion, "Completa la tarea")


@test("_parse_eval: JSON en bloque de código ``` sin 'json'```")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    content = (
        "```\n"
        '{"completed": true, "confidence": 0.85, "issues": [], "suggestion": ""}\n'
        "```"
    )
    result = evaluator._parse_eval(content)
    assert_eq(result.completed, True)
    assert_eq(result.confidence, 0.85)


@test("_parse_eval: extrae primer {...} con regex (fallback)")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    content = 'Texto anterior {"completed": true, "confidence": 0.7, "issues": [], "suggestion": ""} texto posterior'
    result = evaluator._parse_eval(content)
    assert_eq(result.completed, True)
    assert_eq(result.confidence, 0.7)


@test("_parse_eval: fallback conservador si no parsea")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    result = evaluator._parse_eval("No puedo evaluar esto correctamente.")
    assert_eq(result.completed, False)
    assert_eq(result.confidence, 0.0)
    assert_true(len(result.issues) > 0)
    assert_in("No se pudo parsear", result.issues[0])


@test("_parse_eval: confidence clamp a [0.0, 1.0]")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())

    # Clamp superior
    r1 = evaluator._parse_eval('{"completed": true, "confidence": 1.5, "issues": [], "suggestion": ""}')
    assert_eq(r1.confidence, 1.0)

    # Clamp inferior
    r2 = evaluator._parse_eval('{"completed": false, "confidence": -0.2, "issues": [], "suggestion": ""}')
    assert_eq(r2.confidence, 0.0)


@test("_parse_eval: issues puede ser string (manejo defensivo)")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    # issues como string en lugar de lista
    content = '{"completed": false, "confidence": 0.5, "issues": "Problema único", "suggestion": ""}'
    result = evaluator._parse_eval(content)
    assert_eq(len(result.issues), 1)
    assert_eq(result.issues[0], "Problema único")


# ── Tests _summarize_steps ────────────────────────────────────────────────────

@test("_summarize_steps: sin steps → mensaje vacío")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    state = MagicMock()
    state.steps = []
    summary = evaluator._summarize_steps(state)
    assert_eq(summary, "(ningún paso ejecutado)")


@test("_summarize_steps: steps con tool calls OK")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    state = make_state(steps_count=2)
    state.steps[0].step_number = 0
    state.steps[1].step_number = 1
    # Todos success
    for step in state.steps:
        for tc in step.tool_calls_made:
            tc.result.success = True

    summary = evaluator._summarize_steps(state)
    assert_in("Paso 1", summary)
    assert_in("Paso 2", summary)
    assert_in("[OK]", summary)


@test("_summarize_steps: step con error muestra 'algunos errores'")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    state = make_state(steps_count=1)
    state.steps[0].step_number = 0
    state.steps[0].tool_calls_made[0].result.success = False

    summary = evaluator._summarize_steps(state)
    assert_in("algunos errores", summary)


@test("_summarize_steps: step sin tool calls")
def _():
    from architect.core.evaluator import SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    state = MagicMock()
    step = MagicMock()
    step.step_number = 0
    step.tool_calls_made = []
    state.steps = [step]
    summary = evaluator._summarize_steps(state)
    assert_in("razonamiento sin tool calls", summary)


# ── Tests _build_correction_prompt ────────────────────────────────────────────

@test("_build_correction_prompt: incluye prompt original, issues y suggestion")
def _():
    from architect.core.evaluator import EvalResult, SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    eval_result = EvalResult(
        completed=False,
        confidence=0.4,
        issues=["Falta el archivo main.py", "Tests no pasan"],
        suggestion="Crea main.py con la función principal",
    )
    prompt = "Genera un módulo Python completo"
    correction = evaluator._build_correction_prompt(prompt, eval_result)

    assert_in("Genera un módulo Python completo", correction)
    assert_in("Falta el archivo main.py", correction)
    assert_in("Tests no pasan", correction)
    assert_in("Crea main.py con la función principal", correction)
    assert_in("correctamente", correction)


@test("_build_correction_prompt: fallback si issues vacío")
def _():
    from architect.core.evaluator import EvalResult, SelfEvaluator
    evaluator = SelfEvaluator(llm=MagicMock())
    eval_result = EvalResult(completed=False, confidence=0.5, issues=[], suggestion="")
    correction = evaluator._build_correction_prompt("tarea", eval_result)
    assert_in("Resultado incompleto o incorrecto", correction)
    assert_in("Revisa el resultado", correction)


# ── Tests evaluate_basic ──────────────────────────────────────────────────────

@test("evaluate_basic: LLM devuelve 'completado' → EvalResult(completed=True)")
def _():
    from architect.core.evaluator import SelfEvaluator
    llm_response = '{"completed": true, "confidence": 0.92, "issues": [], "suggestion": ""}'
    evaluator = SelfEvaluator(llm=make_llm_mock(llm_response))
    state = make_state()
    result = evaluator.evaluate_basic("Crea un archivo README", state)
    assert_eq(result.completed, True)
    assert_eq(result.confidence, 0.92)
    assert_eq(result.issues, [])


@test("evaluate_basic: LLM devuelve 'incompleto' → EvalResult(completed=False)")
def _():
    from architect.core.evaluator import SelfEvaluator
    llm_response = (
        '{"completed": false, "confidence": 0.3, '
        '"issues": ["No se creó el archivo"], "suggestion": "Crea el archivo README.md"}'
    )
    evaluator = SelfEvaluator(llm=make_llm_mock(llm_response))
    state = make_state()
    result = evaluator.evaluate_basic("Crea un archivo README", state)
    assert_eq(result.completed, False)
    assert_eq(result.confidence, 0.3)
    assert_in("No se creó el archivo", result.issues)


@test("evaluate_basic: error de LLM → EvalResult conservador")
def _():
    from architect.core.evaluator import SelfEvaluator
    llm = MagicMock()
    llm.completion.side_effect = RuntimeError("Connection refused")
    evaluator = SelfEvaluator(llm=llm)
    state = make_state()
    result = evaluator.evaluate_basic("tarea", state)
    assert_eq(result.completed, False)
    assert_eq(result.confidence, 0.0)
    assert_true(len(result.issues) > 0)


@test("evaluate_basic: llm.completion recibe tools=None")
def _():
    from architect.core.evaluator import SelfEvaluator
    llm = make_llm_mock('{"completed": true, "confidence": 0.9, "issues": [], "suggestion": ""}')
    evaluator = SelfEvaluator(llm=llm)
    state = make_state()
    evaluator.evaluate_basic("tarea", state)
    # Verificar que se llamó con tools=None
    call_kwargs = llm.completion.call_args
    assert_eq(call_kwargs.kwargs.get("tools"), None)


# ── Tests evaluate_full ───────────────────────────────────────────────────────

@test("evaluate_full: primer intento pasa → devuelve estado original")
def _():
    from architect.core.evaluator import SelfEvaluator
    llm_response = '{"completed": true, "confidence": 0.95, "issues": [], "suggestion": ""}'
    evaluator = SelfEvaluator(
        llm=make_llm_mock(llm_response),
        max_retries=2,
        confidence_threshold=0.8,
    )
    original_state = make_state(status="success")
    run_fn = MagicMock()

    result_state = evaluator.evaluate_full("tarea", original_state, run_fn)

    assert_eq(result_state, original_state)
    run_fn.assert_not_called()  # No debe re-ejecutar


@test("evaluate_full: primer intento falla, segundo pasa → devuelve estado corregido")
def _():
    from architect.core.evaluator import SelfEvaluator

    llm = MagicMock()
    # Primera evaluación: falla
    fail_response = MagicMock()
    fail_response.content = (
        '{"completed": false, "confidence": 0.4, '
        '"issues": ["Incompleto"], "suggestion": "Completa la tarea"}'
    )
    # Segunda evaluación: pasa
    pass_response = MagicMock()
    pass_response.content = '{"completed": true, "confidence": 0.9, "issues": [], "suggestion": ""}'

    llm.completion.side_effect = [fail_response, pass_response]

    evaluator = SelfEvaluator(llm=llm, max_retries=2, confidence_threshold=0.8)

    original_state = make_state(status="success")
    corrected_state = make_state(status="success", final_output="Corregido.")
    run_fn = MagicMock(return_value=corrected_state)

    result_state = evaluator.evaluate_full("tarea", original_state, run_fn)

    assert_eq(result_state, corrected_state)
    run_fn.assert_called_once()


@test("evaluate_full: max_retries agotados → devuelve último estado disponible")
def _():
    from architect.core.evaluator import SelfEvaluator

    llm = MagicMock()
    # Todas las evaluaciones fallan
    fail_response = MagicMock()
    fail_response.content = (
        '{"completed": false, "confidence": 0.3, "issues": ["Siempre falla"], "suggestion": "N/A"}'
    )
    llm.completion.return_value = fail_response

    evaluator = SelfEvaluator(llm=llm, max_retries=2, confidence_threshold=0.8)

    original_state = make_state(status="success")
    final_state = make_state(status="partial")
    run_fn = MagicMock(return_value=final_state)

    result_state = evaluator.evaluate_full("tarea", original_state, run_fn)

    # Debe devolver el último estado (final_state)
    assert_eq(result_state, final_state)
    assert_eq(run_fn.call_count, 2)  # max_retries=2


@test("evaluate_full: confidence < threshold → reintenta aunque completed=True")
def _():
    from architect.core.evaluator import SelfEvaluator

    llm = MagicMock()
    # completed=True pero confidence baja
    low_conf = MagicMock()
    low_conf.content = '{"completed": true, "confidence": 0.5, "issues": [], "suggestion": ""}'
    # Segunda: confidence alta
    high_conf = MagicMock()
    high_conf.content = '{"completed": true, "confidence": 0.95, "issues": [], "suggestion": ""}'

    llm.completion.side_effect = [low_conf, high_conf]

    evaluator = SelfEvaluator(llm=llm, max_retries=2, confidence_threshold=0.8)

    original_state = make_state(status="success")
    corrected_state = make_state(status="success")
    run_fn = MagicMock(return_value=corrected_state)

    result_state = evaluator.evaluate_full("tarea", original_state, run_fn)

    assert_eq(result_state, corrected_state)
    run_fn.assert_called_once()


@test("evaluate_full: error en run_fn → detiene el loop y devuelve estado")
def _():
    from architect.core.evaluator import SelfEvaluator

    fail_response = MagicMock()
    fail_response.content = (
        '{"completed": false, "confidence": 0.3, "issues": ["fallo"], "suggestion": ""}'
    )
    llm = MagicMock()
    llm.completion.return_value = fail_response

    evaluator = SelfEvaluator(llm=llm, max_retries=3, confidence_threshold=0.8)
    original_state = make_state(status="success")
    run_fn = MagicMock(side_effect=RuntimeError("Agente crasheó"))

    # No debe propagar excepción
    result_state = evaluator.evaluate_full("tarea", original_state, run_fn)

    # Devuelve el estado que tenía antes del crash
    assert result_state is not None
    run_fn.assert_called_once()


# ── Tests EvaluationConfig ────────────────────────────────────────────────────

@test("EvaluationConfig: valores por defecto")
def _():
    from architect.config.schema import EvaluationConfig
    cfg = EvaluationConfig()
    assert_eq(cfg.mode, "off")
    assert_eq(cfg.max_retries, 2)
    assert_eq(cfg.confidence_threshold, 0.8)


@test("EvaluationConfig: modo 'basic' válido")
def _():
    from architect.config.schema import EvaluationConfig
    cfg = EvaluationConfig(mode="basic")
    assert_eq(cfg.mode, "basic")


@test("EvaluationConfig: modo 'full' con max_retries 5")
def _():
    from architect.config.schema import EvaluationConfig
    cfg = EvaluationConfig(mode="full", max_retries=5)
    assert_eq(cfg.mode, "full")
    assert_eq(cfg.max_retries, 5)


@test("EvaluationConfig: max_retries fuera de rango → ValidationError")
def _():
    from pydantic import ValidationError
    from architect.config.schema import EvaluationConfig
    try:
        EvaluationConfig(max_retries=0)
        assert False, "Debería lanzar ValidationError"
    except ValidationError:
        pass

    try:
        EvaluationConfig(max_retries=6)
        assert False, "Debería lanzar ValidationError"
    except ValidationError:
        pass


@test("EvaluationConfig: confidence_threshold fuera de [0, 1] → ValidationError")
def _():
    from pydantic import ValidationError
    from architect.config.schema import EvaluationConfig
    try:
        EvaluationConfig(confidence_threshold=1.5)
        assert False, "Debería lanzar ValidationError"
    except ValidationError:
        pass

    try:
        EvaluationConfig(confidence_threshold=-0.1)
        assert False, "Debería lanzar ValidationError"
    except ValidationError:
        pass


@test("EvaluationConfig: modo inválido → ValidationError")
def _():
    from pydantic import ValidationError
    from architect.config.schema import EvaluationConfig
    try:
        EvaluationConfig(mode="turbo")  # type: ignore
        assert False, "Debería lanzar ValidationError"
    except ValidationError:
        pass


@test("EvaluationConfig: extra fields forbidden")
def _():
    from pydantic import ValidationError
    from architect.config.schema import EvaluationConfig
    try:
        EvaluationConfig(mode="off", unknown_field="value")  # type: ignore
        assert False, "Debería lanzar ValidationError"
    except ValidationError:
        pass


@test("AppConfig: incluye evaluation con defaults correctos")
def _():
    from architect.config.schema import AppConfig
    cfg = AppConfig()
    assert_eq(cfg.evaluation.mode, "off")
    assert_eq(cfg.evaluation.max_retries, 2)
    assert_eq(cfg.evaluation.confidence_threshold, 0.8)


@test("AppConfig: evaluation mode 'full' desde dict")
def _():
    from architect.config.schema import AppConfig
    cfg = AppConfig.model_validate({
        "evaluation": {
            "mode": "full",
            "max_retries": 3,
            "confidence_threshold": 0.9,
        }
    })
    assert_eq(cfg.evaluation.mode, "full")
    assert_eq(cfg.evaluation.max_retries, 3)
    assert_eq(cfg.evaluation.confidence_threshold, 0.9)


# ── Tests de consistencia de versiones ────────────────────────────────────────

@test("Versión: architect.__init__ == 0.12.0")
def _():
    import architect
    assert_eq(architect.__version__, "0.12.0")


@test("Versión: pyproject.toml == 0.12.0")
def _():
    import re
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    content = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    assert match, "No se encontró version en pyproject.toml"
    assert_eq(match.group(1), "0.12.0")


@test("SelfEvaluator y EvalResult exportados desde core.__init__")
def _():
    from architect.core import EvalResult, SelfEvaluator
    # Verificar que son importables y tienen la API esperada
    assert hasattr(SelfEvaluator, "evaluate_basic")
    assert hasattr(SelfEvaluator, "evaluate_full")
    assert hasattr(EvalResult, "__dataclass_fields__")


@test("SelfEvaluator: _try_parse_json con JSON inválido → None")
def _():
    from architect.core.evaluator import SelfEvaluator
    assert_eq(SelfEvaluator._try_parse_json("no es json"), None)
    assert_eq(SelfEvaluator._try_parse_json("[1, 2, 3]"), None)  # lista, no dict
    assert_eq(SelfEvaluator._try_parse_json(""), None)


@test("SelfEvaluator: _try_parse_json con JSON válido → dict")
def _():
    from architect.core.evaluator import SelfEvaluator
    result = SelfEvaluator._try_parse_json('{"key": "value"}')
    assert_eq(result, {"key": "value"})


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "=" * 65)
    print("  Tests Fase 12 — Self-Evaluation (Critic Agent)")
    print("=" * 65 + "\n")

    if not VERBOSE:
        for name, ok, _ in results:
            icon = "✓" if ok else "✗"
            print(f"  {icon} {name}")

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    print(f"  Resultado: {passed}/{total} tests pasaron")

    if failed:
        print(f"\n  FALLOS ({failed}):")
        for name, ok, msg in results:
            if not ok:
                print(f"\n  ✗ {name}")
                print("    " + msg.replace("\n", "\n    ")[:500])

    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
