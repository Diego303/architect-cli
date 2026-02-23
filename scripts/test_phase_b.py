#!/usr/bin/env python3
"""
Script de prueba exhaustivo para v4 Fase B — Sessions, Reports, CI/CD Flags, Dry Run.

Cubre integración compleja de las 4 features de Fase B:
  B1  Sessions (8 tests)  — lifecycle, truncación, campos, orden, cleanup, edge cases
  B2  Reports  (8 tests)  — JSON/Markdown/GitHub, zero values, empty, long, status icons
  B3  CI/CD    (5 tests)  — flags CLI, commands, exit codes
  B4  Dry Run  (6 tests)  — multi-tool, interleave, plan summary, complex input
  CMB Combinados (8 tests) — cross-feature, roundtrips, stop reasons, version

Total: ~40 tests, ~100 checks.  No requiere API key.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PASSED = 0
FAILED = 0
VERBOSE = "-v" in sys.argv


def ok(name: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  ✓ {name}")


def fail(name: str, detail: str = "") -> None:
    global FAILED
    FAILED += 1
    msg = f"  ✗ {name}"
    if detail:
        msg += f": {detail}"
    print(msg, file=sys.stderr)


def section(title: str) -> None:
    print(f"\n── {title} {'─' * max(1, 56 - len(title))}")


def _run_cli(*args: str) -> tuple[int, str, str]:
    """Ejecuta architect CLI y retorna (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "architect", *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_session(**overrides) -> "SessionState":
    """Crea un SessionState con defaults razonables para testing."""
    from architect.features.sessions import SessionState, generate_session_id

    defaults = dict(
        session_id=generate_session_id(),
        task="Test task for Phase B",
        agent="build",
        model="gpt-4o",
        status="running",
        steps_completed=0,
        messages=[{"role": "user", "content": "test"}],
        files_modified=[],
        total_cost=0.0,
        started_at=time.time(),
        updated_at=time.time(),
    )
    defaults.update(overrides)
    return SessionState(**defaults)


def _make_full_report(**overrides) -> "ExecutionReport":
    """Crea un ExecutionReport con todos los campos poblados."""
    from architect.features.report import ExecutionReport

    defaults = dict(
        task="Implement feature X",
        agent="build",
        model="gpt-4o",
        status="success",
        duration_seconds=45.2,
        steps=10,
        total_cost=0.1523,
        files_modified=[
            {"path": "src/main.py", "action": "modified", "lines_added": 15, "lines_removed": 3},
            {"path": "tests/test_main.py", "action": "created", "lines_added": 42, "lines_removed": 0},
        ],
        quality_gates=[
            {"name": "lint", "passed": True},
            {"name": "tests", "passed": False, "output": "2 failures in test_edge_cases"},
        ],
        errors=["Step 3, edit_file: old_str no encontrado"],
        git_diff="diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n",
        timeline=[
            {"step": 1, "tool": "read_file", "duration": 0.5},
            {"step": 2, "tool": "edit_file", "duration": 1.2, "cost": 0.003},
            {"step": 3, "tool": "write_file", "duration": 0.8},
        ],
        stop_reason="llm_done",
    )
    defaults.update(overrides)
    return ExecutionReport(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
# B1 — Sessions
# ═══════════════════════════════════════════════════════════════════════════

def test_session_lifecycle(tmpdir: str) -> None:
    section("B1.1 — Session lifecycle completo")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    state = _make_session(steps_completed=5, total_cost=0.042)
    sid = state.session_id

    # Save
    mgr.save(state)
    session_file = Path(tmpdir) / ".architect/sessions" / f"{sid}.json"
    if session_file.exists():
        ok("save: archivo creado en disco")
    else:
        fail("save: archivo NO creado", str(session_file))

    # List
    sessions = mgr.list_sessions()
    if len(sessions) >= 1 and sessions[0]["id"] == sid:
        ok(f"list_sessions: sesión {sid[:16]}... encontrada")
    else:
        fail("list_sessions: sesión no encontrada", str(sessions))

    # Load
    loaded = mgr.load(sid)
    if loaded and loaded.session_id == sid:
        ok("load: session_id coincide")
    else:
        fail("load: session_id NO coincide")

    if loaded and loaded.steps_completed == 5 and loaded.total_cost == 0.042:
        ok("load: steps_completed y total_cost preservados")
    else:
        fail("load: datos no coinciden", f"steps={getattr(loaded, 'steps_completed', '?')}")

    # Delete
    deleted = mgr.delete(sid)
    if deleted:
        ok("delete: retorna True")
    else:
        fail("delete: retorna False")

    # Verify deleted
    loaded2 = mgr.load(sid)
    if loaded2 is None:
        ok("load post-delete: retorna None")
    else:
        fail("load post-delete: debería ser None")

    # Delete non-existent
    deleted2 = mgr.delete("nonexistent-id-12345")
    if not deleted2:
        ok("delete non-existent: retorna False")
    else:
        fail("delete non-existent: debería retornar False")


def test_session_message_truncation(tmpdir: str) -> None:
    section("B1.2 — Truncación de mensajes (>50)")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(60)]
    state = _make_session(messages=messages)
    sid = state.session_id

    mgr.save(state)

    # Leer JSON crudo
    raw_path = Path(tmpdir) / ".architect/sessions" / f"{sid}.json"
    data = json.loads(raw_path.read_text(encoding="utf-8"))

    if data.get("messages_truncated") is True:
        ok("messages_truncated = True en JSON")
    else:
        fail("messages_truncated no está marcado", str(data.get("messages_truncated")))

    if len(data["messages"]) == 30:
        ok(f"mensajes truncados a 30 (de 60)")
    else:
        fail(f"esperaba 30 mensajes, encontré {len(data['messages'])}")

    # Verificar que se quedaron los últimos 30 (indices 30-59)
    last_msg = data["messages"][-1]["content"]
    if last_msg == "msg 59":
        ok("último mensaje = 'msg 59' (preserva los más recientes)")
    else:
        fail("último mensaje incorrecto", last_msg)


def test_session_all_fields_populated(tmpdir: str) -> None:
    section("B1.3 — Todos los campos populated")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    state = _make_session(
        stop_reason="max_steps",
        metadata={"retry": True, "branch": "feature-x", "count": 42},
        files_modified=["a.py", "b.ts", "c.md"],
        total_cost=1.2345,
        status="partial",
    )

    mgr.save(state)
    loaded = mgr.load(state.session_id)

    if loaded and loaded.stop_reason == "max_steps":
        ok("stop_reason preservado")
    else:
        fail("stop_reason no preservado", str(getattr(loaded, "stop_reason", "?")))

    if loaded and loaded.metadata == {"retry": True, "branch": "feature-x", "count": 42}:
        ok("metadata dict preservado exactamente")
    else:
        fail("metadata no coincide", str(getattr(loaded, "metadata", "?")))

    if loaded and loaded.files_modified == ["a.py", "b.ts", "c.md"]:
        ok("files_modified preservado")
    else:
        fail("files_modified no coincide")

    if loaded and loaded.total_cost == 1.2345:
        ok("total_cost preservado")
    else:
        fail("total_cost no coincide")


def test_session_list_order(tmpdir: str) -> None:
    section("B1.4 — Orden de listado (newest first)")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    ids = []
    for i in range(3):
        state = _make_session(task=f"Task {i}")
        mgr.save(state)
        ids.append(state.session_id)
        time.sleep(0.05)  # asegurar mtime distinto

    sessions = mgr.list_sessions()
    listed_ids = [s["id"] for s in sessions]

    # El último guardado debe ser el primero en la lista
    if listed_ids[0] == ids[2]:
        ok("newest session first en list_sessions")
    else:
        fail("orden incorrecto", f"esperaba {ids[2]}, obtuvo {listed_ids[0]}")

    if listed_ids[-1] == ids[0]:
        ok("oldest session last en list_sessions")
    else:
        fail("oldest no está último", f"esperaba {ids[0]}, obtuvo {listed_ids[-1]}")


def test_session_cleanup_boundary(tmpdir: str) -> None:
    section("B1.5 — Cleanup boundary (mantiene recientes, borra viejos)")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)

    # Crear 2 sesiones
    old_state = _make_session(task="Old task")
    new_state = _make_session(task="New task")
    mgr.save(old_state)
    mgr.save(new_state)

    # Hacer la primera "vieja" (30 días atrás)
    old_file = Path(tmpdir) / ".architect/sessions" / f"{old_state.session_id}.json"
    old_mtime = time.time() - (30 * 86400)
    os.utime(str(old_file), (old_mtime, old_mtime))

    removed = mgr.cleanup(older_than_days=7)
    if removed == 1:
        ok("cleanup eliminó 1 sesión vieja")
    else:
        fail(f"cleanup eliminó {removed} sesiones, esperaba 1")

    remaining = mgr.list_sessions()
    if len(remaining) == 1:
        ok("queda exactamente 1 sesión")
    else:
        fail(f"quedan {len(remaining)} sesiones, esperaba 1")

    if remaining[0]["id"] == new_state.session_id:
        ok("la sesión reciente sobrevivió al cleanup")
    else:
        fail("la sesión superviviente no es la esperada")


def test_session_special_chars(tmpdir: str) -> None:
    section("B1.6 — Caracteres especiales en task")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    special_task = 'Refactorizar "módulo" con acentos: áéíóú ñ & <html> "quotes"'
    state = _make_session(task=special_task)
    mgr.save(state)

    loaded = mgr.load(state.session_id)
    if loaded and loaded.task == special_task:
        ok("task con chars especiales preservado exactamente")
    else:
        fail("task no coincide", repr(getattr(loaded, "task", "?")))


def test_session_corrupted_json(tmpdir: str) -> None:
    section("B1.7 — JSON corrupto → load retorna None")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    sessions_dir = Path(tmpdir) / ".architect/sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # JSON inválido
    (sessions_dir / "corrupted-id.json").write_text("{not valid json}", encoding="utf-8")
    loaded = mgr.load("corrupted-id")
    if loaded is None:
        ok("JSON inválido → load retorna None")
    else:
        fail("JSON inválido debería retornar None")

    # JSON válido pero faltan campos requeridos
    (sessions_dir / "incomplete-id.json").write_text('{"session_id": "incomplete-id"}', encoding="utf-8")
    loaded2 = mgr.load("incomplete-id")
    if loaded2 is None:
        ok("JSON incompleto → load retorna None")
    else:
        fail("JSON incompleto debería retornar None")


def test_generate_session_id() -> None:
    section("B1.8 — generate_session_id: formato y uniqueness")
    from architect.features.sessions import generate_session_id

    ids = [generate_session_id() for _ in range(20)]
    pattern = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")

    all_match = all(pattern.match(sid) for sid in ids)
    if all_match:
        ok("20 IDs coinciden con patrón YYYYMMDD-HHMMSS-hexhex")
    else:
        bad = [sid for sid in ids if not pattern.match(sid)]
        fail("IDs no coinciden con patrón", str(bad[:3]))

    if len(set(ids)) == 20:
        ok("20 IDs son únicos")
    else:
        fail("IDs duplicados encontrados")


# ═══════════════════════════════════════════════════════════════════════════
# B2 — Reports
# ═══════════════════════════════════════════════════════════════════════════

def test_report_full_json_parseable() -> None:
    section("B2.1 — Report completo → JSON parseable")
    from architect.features.report import ReportGenerator

    report = _make_full_report()
    gen = ReportGenerator(report)
    json_str = gen.to_json()

    try:
        parsed = json.loads(json_str)
        ok("JSON parseable sin errores")
    except json.JSONDecodeError as e:
        fail("JSON no parseable", str(e))
        return

    expected_keys = {
        "task", "agent", "model", "status", "duration_seconds",
        "steps", "total_cost", "files_modified", "quality_gates",
        "errors", "git_diff", "timeline", "stop_reason",
    }
    actual_keys = set(parsed.keys())
    if expected_keys <= actual_keys:
        ok(f"JSON contiene las {len(expected_keys)} keys esperadas")
    else:
        missing = expected_keys - actual_keys
        fail("JSON faltan keys", str(missing))


def test_report_full_markdown_sections() -> None:
    section("B2.2 — Report completo → Markdown con todas las secciones")
    from architect.features.report import ReportGenerator

    report = _make_full_report()
    md = ReportGenerator(report).to_markdown()

    required_sections = [
        "# Execution Report",
        "## Summary",
        "## Files Modified",
        "## Quality Gates",
        "## Errors",
        "## Timeline",
    ]
    all_found = all(s in md for s in required_sections)
    if all_found:
        ok("Markdown contiene todas las 6 secciones")
    else:
        missing = [s for s in required_sections if s not in md]
        fail("Markdown faltan secciones", str(missing))

    # Verificar contenido del summary
    summary_fields = ["Task", "Agent", "Status", "Duration", "Steps", "Cost"]
    fields_present = all(f in md for f in summary_fields)
    if fields_present:
        ok("Summary table contiene todos los campos")
    else:
        missing = [f for f in summary_fields if f not in md]
        fail("Summary faltan campos", str(missing))


def test_report_full_github_comment() -> None:
    section("B2.3 — Report completo → GitHub PR comment")
    from architect.features.report import ReportGenerator

    report = _make_full_report()
    gh = ReportGenerator(report).to_github_pr_comment()

    if "<details>" in gh and "Files modified" in gh:
        ok("GitHub comment tiene <details> con Files modified")
    else:
        fail("GitHub comment falta <details> para files")

    if "Errors" in gh and "</details>" in gh:
        ok("GitHub comment tiene sección de errores")
    else:
        fail("GitHub comment falta sección de errores")

    if "10 steps" in gh and "$0.152" in gh:
        ok("GitHub comment tiene métricas (steps + cost)")
    else:
        fail("GitHub comment falta métricas", gh[:200])


def test_report_zero_values() -> None:
    section("B2.4 — Report con valores zero → no crash")
    from architect.features.report import ExecutionReport, ReportGenerator

    report = ExecutionReport(
        task="t", agent="build", model="m",
        status="success", duration_seconds=0.0, steps=0, total_cost=0.0,
    )
    gen = ReportGenerator(report)

    try:
        j = gen.to_json()
        json.loads(j)
        ok("to_json() con zeros OK")
    except Exception as e:
        fail("to_json() crash con zeros", str(e))

    try:
        md = gen.to_markdown()
        if "# Execution Report" in md:
            ok("to_markdown() con zeros OK")
        else:
            fail("to_markdown() con zeros no tiene header")
    except Exception as e:
        fail("to_markdown() crash con zeros", str(e))

    try:
        gh = gen.to_github_pr_comment()
        if "##" in gh:
            ok("to_github_pr_comment() con zeros OK")
        else:
            fail("to_github_pr_comment() con zeros no tiene header")
    except Exception as e:
        fail("to_github_pr_comment() crash con zeros", str(e))


def test_report_empty_collections() -> None:
    section("B2.5 — Report con colecciones vacías → secciones omitidas")
    from architect.features.report import ExecutionReport, ReportGenerator

    report = ExecutionReport(
        task="t", agent="a", model="m", status="success",
        duration_seconds=1.0, steps=1, total_cost=0.01,
        files_modified=[], quality_gates=[], errors=[], timeline=[],
    )
    md = ReportGenerator(report).to_markdown()

    if "## Files Modified" not in md:
        ok("Files Modified omitido cuando vacío")
    else:
        fail("Files Modified presente con lista vacía")

    if "## Quality Gates" not in md:
        ok("Quality Gates omitido cuando vacío")
    else:
        fail("Quality Gates presente con lista vacía")

    if "## Errors" not in md:
        ok("Errors omitido cuando vacío")
    else:
        fail("Errors presente con lista vacía")

    if "## Timeline" not in md:
        ok("Timeline omitido cuando vacío")
    else:
        fail("Timeline presente con lista vacía")

    if "## Summary" in md:
        ok("Summary siempre presente")
    else:
        fail("Summary debería estar presente siempre")


def test_report_long_paths_and_errors() -> None:
    section("B2.6 — Paths y errores muy largos → no crash")
    from architect.features.report import ReportGenerator

    report = _make_full_report(
        files_modified=[{"path": "a/" * 100 + "file.py", "action": "modified"}],
        errors=["X" * 500],
    )
    gen = ReportGenerator(report)

    try:
        gen.to_json()
        ok("to_json() con paths largos OK")
    except Exception as e:
        fail("to_json() crash con paths largos", str(e))

    try:
        gen.to_markdown()
        ok("to_markdown() con paths largos OK")
    except Exception as e:
        fail("to_markdown() crash con paths largos", str(e))

    try:
        gen.to_github_pr_comment()
        ok("to_github_pr_comment() con paths largos OK")
    except Exception as e:
        fail("to_github_pr_comment() crash con paths largos", str(e))


def test_report_status_icons() -> None:
    section("B2.7 — Status icons correctos")
    from architect.features.report import ExecutionReport, ReportGenerator

    icon_map = {
        "success": "OK",
        "partial": "WARN",
        "failed": "FAIL",
    }
    for status, expected_icon in icon_map.items():
        report = ExecutionReport(
            task="t", agent="a", model="m", status=status,
            duration_seconds=1.0, steps=1, total_cost=0.0,
        )
        md = ReportGenerator(report).to_markdown()
        if expected_icon in md:
            ok(f"Markdown status '{status}' → {expected_icon}")
        else:
            fail(f"Markdown status '{status}' no contiene '{expected_icon}'")

    # GitHub: success → "## OK", partial/failed → "## WARN"
    report_partial = ExecutionReport(
        task="t", agent="a", model="m", status="partial",
        duration_seconds=1.0, steps=1, total_cost=0.0,
    )
    gh = ReportGenerator(report_partial).to_github_pr_comment()
    if "## WARN" in gh:
        ok("GitHub partial → '## WARN'")
    else:
        fail("GitHub partial no contiene '## WARN'")


def test_collect_git_diff() -> None:
    section("B2.8 — collect_git_diff()")
    from architect.features.report import collect_git_diff

    # En el repo actual — debería retornar string o None (hay cambios pendientes)
    project_root = str(Path(__file__).parent.parent)
    result = collect_git_diff(project_root)
    if result is None or isinstance(result, str):
        ok(f"collect_git_diff(project_root) → {'string' if result else 'None'} (OK)")
    else:
        fail("collect_git_diff retornó tipo inesperado", type(result).__name__)

    # Path inexistente → None (no crash)
    result2 = collect_git_diff("/nonexistent/path/xyz123")
    if result2 is None:
        ok("collect_git_diff(path inexistente) → None (no crash)")
    else:
        fail("collect_git_diff(path inexistente) debería ser None")


# ═══════════════════════════════════════════════════════════════════════════
# B3 — CI/CD Native Flags
# ═══════════════════════════════════════════════════════════════════════════

def test_cli_b3_flags() -> None:
    section("B3.1 — architect run --help contiene flags de Fase B")

    rc, stdout, stderr = _run_cli("run", "--help")
    if rc != 0:
        fail("architect run --help falló", f"rc={rc}")
        return

    flags = [
        "--json", "--dry-run", "--confirm-mode", "--exit-code-on-partial",
        "--context-git-diff", "--report", "--report-file", "--session",
    ]
    found = []
    missing = []
    for flag in flags:
        if flag in stdout:
            found.append(flag)
        else:
            missing.append(flag)

    if not missing:
        ok(f"run --help contiene los {len(flags)} flags de Fase B")
    else:
        fail(f"faltan {len(missing)} flags en --help", str(missing))

    # Verificar choices específicos
    if "yolo" in stdout and "confirm-sensitive" in stdout and "confirm-all" in stdout:
        ok("--confirm-mode muestra las 3 opciones")
    else:
        fail("--confirm-mode falta alguna opción")

    if "json" in stdout and "markdown" in stdout and "github" in stdout:
        ok("--report muestra las 3 opciones de formato")
    else:
        fail("--report falta alguna opción de formato")


def test_cli_sessions_command() -> None:
    section("B3.2 — architect sessions")

    rc, stdout, stderr = _run_cli("sessions")
    if rc == 0:
        ok(f"architect sessions → exit code 0")
    else:
        fail(f"architect sessions → exit code {rc}", stderr[:200])

    # Debe mostrar algo (tabla vacía o sesiones)
    combined = stdout + stderr
    if "sesion" in combined.lower() or "session" in combined.lower() or "ID" in combined:
        ok("output contiene referencia a sesiones")
    else:
        fail("output no menciona sesiones", combined[:200])


def test_cli_cleanup_command() -> None:
    section("B3.3 — architect cleanup")

    rc, stdout, stderr = _run_cli("cleanup")
    if rc == 0:
        ok("architect cleanup → exit code 0")
    else:
        fail(f"architect cleanup → exit code {rc}", stderr[:200])

    combined = stdout + stderr
    if "sesion" in combined.lower() or "eliminada" in combined.lower() or "cleanup" in combined.lower():
        ok("output contiene mensaje de cleanup")
    else:
        # Puede que no muestre nada si no hay sesiones — eso también es válido
        ok("cleanup sin sesiones (output vacío aceptable)")


def test_cli_resume_nonexistent() -> None:
    section("B3.4 — architect resume NONEXISTENT → exit code 3")

    rc, stdout, stderr = _run_cli("resume", "nonexistent-session-id-99999")
    if rc == 3:
        ok("resume nonexistent → EXIT_CONFIG_ERROR (3)")
    else:
        fail(f"resume nonexistent → exit code {rc}, esperaba 3", stderr[:200])

    combined = stdout + stderr
    if "no encontrada" in combined.lower() or "not found" in combined.lower() or "no se encontró" in combined.lower():
        ok("resume nonexistent muestra error descriptivo")
    else:
        fail("resume nonexistent no muestra error descriptivo", combined[:200])


def test_exit_code_constants() -> None:
    section("B3.5 — Exit code constants")
    from architect.cli import (
        EXIT_AUTH_ERROR,
        EXIT_CONFIG_ERROR,
        EXIT_FAILED,
        EXIT_INTERRUPTED,
        EXIT_PARTIAL,
        EXIT_SUCCESS,
        EXIT_TIMEOUT,
    )

    checks = [
        (EXIT_SUCCESS, 0, "EXIT_SUCCESS"),
        (EXIT_FAILED, 1, "EXIT_FAILED"),
        (EXIT_PARTIAL, 2, "EXIT_PARTIAL"),
        (EXIT_CONFIG_ERROR, 3, "EXIT_CONFIG_ERROR"),
        (EXIT_AUTH_ERROR, 4, "EXIT_AUTH_ERROR"),
        (EXIT_TIMEOUT, 5, "EXIT_TIMEOUT"),
        (EXIT_INTERRUPTED, 130, "EXIT_INTERRUPTED"),
    ]
    for actual, expected, name in checks:
        if actual == expected:
            ok(f"{name} == {expected}")
        else:
            fail(f"{name} == {actual}, esperaba {expected}")


# ═══════════════════════════════════════════════════════════════════════════
# B4 — Dry Run
# ═══════════════════════════════════════════════════════════════════════════

def test_dryrun_multiple_write_tools() -> None:
    section("B4.1 — Múltiples write tools → action_count correcto")
    from architect.features.dryrun import DryRunTracker

    tracker = DryRunTracker()
    tracker.record(1, "write_file", {"path": "a.py", "content": "hello"})
    tracker.record(2, "edit_file", {"path": "b.py", "old_str": "x", "new_str": "y"})
    tracker.record(3, "delete_file", {"path": "c.py"})
    tracker.record(4, "apply_patch", {"path": "d.py", "patch": "..."})
    tracker.record(5, "run_command", {"command": "make build"})

    if tracker.action_count == 5:
        ok("5 write tools → action_count == 5")
    else:
        fail(f"action_count == {tracker.action_count}, esperaba 5")

    tools_recorded = [a.tool for a in tracker.actions]
    expected = ["write_file", "edit_file", "delete_file", "apply_patch", "run_command"]
    if tools_recorded == expected:
        ok("tools registrados en orden correcto")
    else:
        fail("tools no coinciden", str(tools_recorded))


def test_dryrun_interleave_read_write() -> None:
    section("B4.2 — Interleave read+write → solo writes registrados")
    from architect.features.dryrun import DryRunTracker

    tracker = DryRunTracker()
    tracker.record(1, "read_file", {"path": "x.py"})
    tracker.record(2, "write_file", {"path": "a.py"})
    tracker.record(3, "search_code", {"pattern": "foo"})
    tracker.record(4, "edit_file", {"path": "b.py"})
    tracker.record(5, "grep", {"pattern": "bar"})
    tracker.record(6, "run_command", {"command": "ls"})
    tracker.record(7, "find_files", {"pattern": "*.py"})
    tracker.record(8, "delete_file", {"path": "c.py"})

    if tracker.action_count == 4:
        ok("8 calls (4 read + 4 write) → action_count == 4")
    else:
        fail(f"action_count == {tracker.action_count}, esperaba 4")

    tools = [a.tool for a in tracker.actions]
    if tools == ["write_file", "edit_file", "run_command", "delete_file"]:
        ok("solo write tools registrados en orden")
    else:
        fail("tools registrados incorrectos", str(tools))


def test_dryrun_plan_summary_format() -> None:
    section("B4.3 — Plan summary formato")
    from architect.features.dryrun import DryRunTracker

    # Con acciones
    tracker = DryRunTracker()
    for i in range(1, 6):
        tracker.record(i, "write_file", {"path": f"file{i}.py"})
    summary = tracker.get_plan_summary()

    if "## Dry Run Plan" in summary:
        ok("summary tiene header '## Dry Run Plan'")
    else:
        fail("summary falta header")

    if "5 write action(s)" in summary:
        ok("summary dice '5 write action(s)'")
    else:
        fail("summary no dice '5 write action(s)'", summary[:100])

    # Verificar numeración
    has_numbers = all(f"{i}." in summary for i in range(1, 6))
    if has_numbers:
        ok("summary tiene numeración 1-5")
    else:
        fail("summary falta numeración")

    # Sin acciones
    empty_tracker = DryRunTracker()
    empty_summary = empty_tracker.get_plan_summary()
    if "No write actions were planned" in empty_summary:
        ok("empty tracker → 'No write actions were planned'")
    else:
        fail("empty tracker mensaje incorrecto", empty_summary)


def test_dryrun_complex_tool_input() -> None:
    section("B4.4 — tool_input complejo (nested, long commands)")
    from architect.features.dryrun import DryRunTracker

    tracker = DryRunTracker()

    # Nested dict con contenido largo
    tracker.record(1, "write_file", {
        "path": "output.py",
        "content": "a" * 10000,
        "metadata": {"nested": True, "level": 2},
    })

    # Comando largo (>60 chars)
    long_cmd = "python3 -c 'import sys; print(sys.version_info); " + "x" * 100 + "'"
    tracker.record(2, "run_command", {"command": long_cmd})

    if tracker.action_count == 2:
        ok("complex input → 2 acciones registradas")
    else:
        fail(f"action_count == {tracker.action_count}, esperaba 2")

    # Verificar truncación del comando
    cmd_action = tracker.actions[1]
    if "..." in cmd_action.summary:
        ok("comando largo truncado con '...'")
    else:
        fail("comando largo no truncado", cmd_action.summary[:80])


def test_write_read_tools_no_overlap() -> None:
    section("B4.5 — WRITE_TOOLS ∩ READ_TOOLS = ∅")
    from architect.features.dryrun import READ_TOOLS, WRITE_TOOLS

    overlap = WRITE_TOOLS & READ_TOOLS
    if len(overlap) == 0:
        ok("WRITE_TOOLS y READ_TOOLS no se solapan")
    else:
        fail("overlap encontrado", str(overlap))

    if len(WRITE_TOOLS) >= 5:
        ok(f"WRITE_TOOLS tiene {len(WRITE_TOOLS)} elementos (≥5)")
    else:
        fail(f"WRITE_TOOLS solo tiene {len(WRITE_TOOLS)} elementos")

    if len(READ_TOOLS) >= 5:
        ok(f"READ_TOOLS tiene {len(READ_TOOLS)} elementos (≥5)")
    else:
        fail(f"READ_TOOLS solo tiene {len(READ_TOOLS)} elementos")


def test_summarize_action_all_paths() -> None:
    section("B4.6 — _summarize_action: todos los code paths")
    from architect.features.dryrun import _summarize_action

    # Path
    result = _summarize_action("write_file", {"path": "foo.py", "content": "..."})
    if result == "path=foo.py":
        ok("path → 'path=foo.py'")
    else:
        fail("path branch incorrecto", repr(result))

    # Command corto
    result = _summarize_action("run_command", {"command": "make test"})
    if result == "command=make test":
        ok("command corto → 'command=make test'")
    else:
        fail("command branch incorrecto", repr(result))

    # Command largo (>60)
    long_cmd = "x" * 80
    result = _summarize_action("run_command", {"command": long_cmd})
    if "..." in result and len(result) < 80:
        ok("command largo truncado correctamente")
    else:
        fail("command largo no truncado", repr(result))

    # Fallback: keys
    result = _summarize_action("apply_patch", {"diff_content": "---", "base_dir": "."})
    if "args=" in result and "diff_content" in result and "base_dir" in result:
        ok("fallback → 'args=[diff_content, base_dir]'")
    else:
        fail("fallback branch incorrecto", repr(result))

    # Empty dict
    result = _summarize_action("write_file", {})
    if result == "args=[]":
        ok("empty dict → 'args=[]'")
    else:
        fail("empty dict branch incorrecto", repr(result))


# ═══════════════════════════════════════════════════════════════════════════
# Combinados — Cross-feature tests
# ═══════════════════════════════════════════════════════════════════════════

def test_combined_session_files_preserved(tmpdir: str) -> None:
    section("CMB.1 — Session save→load preserva files_modified")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    files = ["src/main.py", "tests/test_main.py", "README.md", "docs/api.md"]
    state = _make_session(files_modified=files)
    mgr.save(state)

    loaded = mgr.load(state.session_id)
    if loaded and loaded.files_modified == files:
        ok("files_modified (4 archivos) preservado exactamente")
    else:
        fail("files_modified no coincide", str(getattr(loaded, "files_modified", "?")))


def test_combined_session_updated_at_changes(tmpdir: str) -> None:
    section("CMB.2 — Save→sleep→save → updated_at cambia")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    state = _make_session()
    mgr.save(state)

    loaded1 = mgr.load(state.session_id)
    first_updated = loaded1.updated_at if loaded1 else 0

    time.sleep(0.1)
    state.steps_completed = 5
    mgr.save(state)

    loaded2 = mgr.load(state.session_id)
    second_updated = loaded2.updated_at if loaded2 else 0

    if second_updated > first_updated:
        ok(f"updated_at incrementó ({second_updated:.2f} > {first_updated:.2f})")
    else:
        fail("updated_at no incrementó", f"{second_updated} <= {first_updated}")


def test_combined_report_timeline() -> None:
    section("CMB.3 — Report timeline con múltiples steps")
    from architect.features.report import ReportGenerator

    report = _make_full_report(timeline=[
        {"step": 1, "tool": "read_file", "duration": 0.5},
        {"step": 2, "tool": "edit_file", "duration": 1.2, "cost": 0.003},
        {"step": 3, "tool": "write_file", "duration": 0.8},
        {"step": 4, "tool": "run_command", "duration": 2.5, "cost": 0.010},
    ])
    md = ReportGenerator(report).to_markdown()

    if "## Timeline" in md:
        ok("timeline section presente")
    else:
        fail("timeline section falta")

    # Verificar que los 4 steps están
    steps_present = all(f"Step {i}" in md for i in range(1, 5))
    if steps_present:
        ok("todos los 4 steps presentes en timeline")
    else:
        fail("faltan steps en timeline")


def test_combined_dryrun_to_report() -> None:
    section("CMB.4 — DryRunTracker data → compatible con ExecutionReport")
    from architect.features.dryrun import DryRunTracker
    from architect.features.report import ExecutionReport, ReportGenerator

    tracker = DryRunTracker()
    tracker.record(1, "write_file", {"path": "new.py"})
    tracker.record(2, "edit_file", {"path": "exist.py"})
    tracker.record(3, "run_command", {"command": "make test"})

    # Construir report desde tracker data
    files = [
        {"path": a.summary.replace("path=", "").replace("command=", ""), "action": "planned"}
        for a in tracker.actions
    ]
    report = ExecutionReport(
        task="Dry run test",
        agent="build",
        model="gpt-4o",
        status="partial",
        duration_seconds=0.0,
        steps=tracker.action_count,
        total_cost=0.0,
        files_modified=files,
    )

    try:
        json_str = ReportGenerator(report).to_json()
        parsed = json.loads(json_str)
        if parsed["steps"] == 3 and len(parsed["files_modified"]) == 3:
            ok("DryRunTracker data → ExecutionReport → JSON válido")
        else:
            fail("datos no coinciden", f"steps={parsed['steps']}, files={len(parsed['files_modified'])}")
    except Exception as e:
        fail("report desde dryrun data crash", str(e))

    # Plan summary también funciona
    summary = tracker.get_plan_summary()
    if "3 write action(s)" in summary:
        ok("plan summary coherente con report (3 acciones)")
    else:
        fail("plan summary incoherente", summary[:80])


def test_combined_multiple_sessions_selective_cleanup(tmpdir: str) -> None:
    section("CMB.5 — 4 sessions + cleanup selectivo")
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)

    # Crear 4 sesiones
    states = [_make_session(task=f"Task {i}") for i in range(4)]
    for s in states:
        mgr.save(s)

    # Hacer las primeras 2 "viejas" (15 días)
    for s in states[:2]:
        path = Path(tmpdir) / ".architect/sessions" / f"{s.session_id}.json"
        old_time = time.time() - (15 * 86400)
        os.utime(str(path), (old_time, old_time))

    removed = mgr.cleanup(older_than_days=10)
    if removed == 2:
        ok("cleanup eliminó 2 sesiones viejas")
    else:
        fail(f"cleanup eliminó {removed}, esperaba 2")

    remaining = mgr.list_sessions()
    remaining_ids = {s["id"] for s in remaining}
    expected_ids = {states[2].session_id, states[3].session_id}

    if remaining_ids == expected_ids:
        ok("quedan exactamente las 2 sesiones recientes")
    else:
        fail("sesiones restantes incorrectas", str(remaining_ids))


def test_combined_report_json_roundtrip() -> None:
    section("CMB.6 — Report JSON roundtrip: todos los campos coinciden")
    from architect.features.report import ReportGenerator

    report = _make_full_report()
    gen = ReportGenerator(report)
    parsed = json.loads(gen.to_json())

    checks = [
        ("task", parsed["task"], report.task),
        ("status", parsed["status"], report.status),
        ("steps", parsed["steps"], report.steps),
        ("total_cost", parsed["total_cost"], report.total_cost),
        ("stop_reason", parsed["stop_reason"], report.stop_reason),
    ]
    for field, actual, expected in checks:
        if actual == expected:
            ok(f"roundtrip {field} == {expected!r}")
        else:
            fail(f"roundtrip {field}: {actual!r} != {expected!r}")


def test_combined_all_stop_reasons(tmpdir: str) -> None:
    section("CMB.7 — Session con cada StopReason → roundtrip")
    from architect.core.state import StopReason
    from architect.features.sessions import SessionManager

    mgr = SessionManager(tmpdir)
    reasons = list(StopReason)

    for sr in reasons:
        state = _make_session(stop_reason=sr.value, status="partial")
        mgr.save(state)
        loaded = mgr.load(state.session_id)

        if loaded and loaded.stop_reason == sr.value:
            ok(f"StopReason.{sr.name} ('{sr.value}') roundtrip OK")
        else:
            fail(f"StopReason.{sr.name} no preservado",
                 str(getattr(loaded, "stop_reason", "?")))


def test_combined_version_consistency() -> None:
    section("CMB.8 — Version consistency (dinámica)")
    import architect

    version = architect.__version__
    if version and re.match(r"^\d+\.\d+\.\d+", version):
        ok(f"architect.__version__ = {version!r} (formato válido)")
    else:
        fail("architect.__version__ inválido", repr(version))

    # Verificar que pyproject.toml coincide
    toml_path = Path(__file__).parent.parent / "pyproject.toml"
    toml_content = toml_path.read_text()
    if f'version = "{version}"' in toml_content:
        ok(f"pyproject.toml version coincide con __version__")
    else:
        fail("pyproject.toml version no coincide")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 60)
    print("  Test Phase B — Sessions + Reports + CI/CD + Dry Run")
    print("=" * 60)

    # ── B1: Sessions ──
    # Cada test que verifica conteos/orden de list_sessions necesita su propio tmpdir
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_lifecycle(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_message_truncation(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_all_fields_populated(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_list_order(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_cleanup_boundary(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_special_chars(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_session_corrupted_json(tmpdir)
    test_generate_session_id()

    # ── B2: Reports ──
    test_report_full_json_parseable()
    test_report_full_markdown_sections()
    test_report_full_github_comment()
    test_report_zero_values()
    test_report_empty_collections()
    test_report_long_paths_and_errors()
    test_report_status_icons()
    test_collect_git_diff()

    # ── B3: CI/CD Flags ──
    test_cli_b3_flags()
    test_cli_sessions_command()
    test_cli_cleanup_command()
    test_cli_resume_nonexistent()
    test_exit_code_constants()

    # ── B4: Dry Run ──
    test_dryrun_multiple_write_tools()
    test_dryrun_interleave_read_write()
    test_dryrun_plan_summary_format()
    test_dryrun_complex_tool_input()
    test_write_read_tools_no_overlap()
    test_summarize_action_all_paths()

    # ── Combinados ──
    with tempfile.TemporaryDirectory() as tmpdir:
        test_combined_session_files_preserved(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_combined_session_updated_at_changes(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_combined_multiple_sessions_selective_cleanup(tmpdir)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_combined_all_stop_reasons(tmpdir)
    test_combined_report_timeline()
    test_combined_dryrun_to_report()
    test_combined_report_json_roundtrip()
    test_combined_version_consistency()

    # ── Resumen ──
    print(f"\n{'=' * 60}")
    total = PASSED + FAILED
    if FAILED == 0:
        print(f"Resultado: {PASSED}/{total} pasados — todos OK")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"Resultado: {PASSED}/{total} pasados ({FAILED} fallaron)")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
