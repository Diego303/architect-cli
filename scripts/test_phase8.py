#!/usr/bin/env python3
"""
Script de prueba para Fase 8 - Integración Final y Pulido.

Pruebas de integración que verifican que el sistema completo está
correctamente ensamblado. No requieren API key para la mayoría.

Prueba:
1. Importaciones de todos los módulos
2. Versión consistente en todos los puntos
3. CLI: --help, --version, validate-config, agents
4. Subcomando agents con agentes por defecto
5. Flujo completo de inicialización (sin LLM)
6. config.example.yaml parseable como configuración válida
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

EXPECTED_VERSION = "0.15.0"


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


def _run_cli(*args) -> tuple[int, str, str]:
    """Ejecuta el CLI architect y retorna (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["python", "-m", "architect", *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    return result.returncode, result.stdout, result.stderr


# ──────────────────────────────────────────────────────────────
# Prueba 1: Importaciones
# ──────────────────────────────────────────────────────────────
def test_imports():
    _separator("Prueba 1: Importaciones de todos los módulos")

    modules = [
        ("architect", "paquete principal"),
        ("architect.cli", "CLI"),
        ("architect.config.schema", "config schema"),
        ("architect.config.loader", "config loader"),
        ("architect.agents.registry", "agents registry"),
        ("architect.agents.prompts", "agents prompts"),
        ("architect.core.loop", "agent loop"),
        ("architect.core.state", "agent state"),
        ("architect.core.context", "context builder"),
        ("architect.core.mixed_mode", "mixed mode runner"),
        ("architect.core.shutdown", "graceful shutdown"),
        ("architect.core.timeout", "step timeout"),
        ("architect.llm.adapter", "LLM adapter"),
        ("architect.tools.base", "tools base"),
        ("architect.tools.filesystem", "filesystem tools"),
        ("architect.tools.registry", "tool registry"),
        ("architect.execution.engine", "execution engine"),
        ("architect.execution.policies", "confirmation policies"),
        ("architect.execution.validators", "path validators"),
        ("architect.mcp.client", "MCP client"),
        ("architect.mcp.adapter", "MCP adapter"),
        ("architect.mcp.discovery", "MCP discovery"),
        ("architect.logging.setup", "logging setup"),
        # Módulos añadidos en v3-core
        ("architect.core.hooks", "post-edit hooks (v3-M4)"),
        ("architect.core.evaluator", "self-evaluator (F12)"),
        ("architect.logging.levels", "HUMAN log level (v3-M5)"),
        ("architect.logging.human", "HumanFormatter/HumanLog (v3-M5/M6)"),
        ("architect.indexer.tree", "repo indexer (F10)"),
        ("architect.costs", "cost tracker (F14)"),
        ("architect.llm.cache", "LLM cache (F14)"),
    ]

    for module, description in modules:
        try:
            __import__(module)
            _ok(f"{module} ({description})")
        except ImportError as e:
            print(f"  ✗ {module}: {e}", file=sys.stderr)
            return False

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 2: Versión consistente
# ──────────────────────────────────────────────────────────────
def test_version_consistency():
    _separator("Prueba 2: Versión consistente en todos los puntos")

    import architect

    _info(f"Versión esperada: {EXPECTED_VERSION}")

    # __init__.py
    assert architect.__version__ == EXPECTED_VERSION, (
        f"architect.__version__ = {architect.__version__!r}, esperado {EXPECTED_VERSION!r}"
    )
    _ok(f"architect.__version__ = {architect.__version__!r}")

    # pyproject.toml
    toml_path = Path(__file__).parent.parent / "pyproject.toml"
    toml_content = toml_path.read_text()
    assert f'version = "{EXPECTED_VERSION}"' in toml_content, (
        f"pyproject.toml no tiene version = \"{EXPECTED_VERSION}\""
    )
    _ok(f"pyproject.toml version = {EXPECTED_VERSION!r}")

    # CLI --version
    rc, stdout, _ = _run_cli("--version")
    assert rc == 0, f"--version retornó exit code {rc}"
    assert EXPECTED_VERSION in stdout, f"--version no muestra {EXPECTED_VERSION!r}: {stdout!r}"
    _ok(f"architect --version: {stdout.strip()!r}")

    # CLI headers (verificar en código fuente)
    cli_path = Path(__file__).parent.parent / "src" / "architect" / "cli.py"
    cli_content = cli_path.read_text()
    assert f"v{EXPECTED_VERSION}" in cli_content, (
        f"cli.py no tiene v{EXPECTED_VERSION} en headers"
    )
    _ok(f"cli.py headers: v{EXPECTED_VERSION}")

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 3: CLI --help funciona
# ──────────────────────────────────────────────────────────────
def test_cli_help():
    _separator("Prueba 3: CLI --help y subcomandos")

    # architect --help
    rc, stdout, _ = _run_cli("--help")
    assert rc == 0, f"architect --help retornó {rc}"
    assert "architect" in stdout.lower()
    _ok("architect --help funciona")

    # architect run --help
    rc, stdout, _ = _run_cli("run", "--help")
    assert rc == 0, f"architect run --help retornó {rc}"
    assert "PROMPT" in stdout
    assert "--dry-run" in stdout
    assert "--mode" in stdout
    assert "--json" in stdout
    _ok("architect run --help: muestra todas las opciones")

    # architect agents --help
    rc, stdout, _ = _run_cli("agents", "--help")
    assert rc == 0, f"architect agents --help retornó {rc}"
    _ok("architect agents --help funciona")

    # architect validate-config --help
    rc, stdout, _ = _run_cli("validate-config", "--help")
    assert rc == 0, f"architect validate-config --help retornó {rc}"
    _ok("architect validate-config --help funciona")

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 4: Subcomando agents
# ──────────────────────────────────────────────────────────────
def test_agents_command():
    _separator("Prueba 4: Subcomando `architect agents`")

    rc, stdout, stderr = _run_cli("agents")
    assert rc == 0, f"architect agents retornó {rc}\nstderr: {stderr}"
    _info(f"Output:\n{stdout}")

    # Verificar que muestra los 4 agentes por defecto
    for agent in ["plan", "build", "resume", "review"]:
        assert agent in stdout, f"Agente '{agent}' no aparece en la salida"
        _ok(f"Agente '{agent}' listado")

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 5: validate-config con config.example.yaml
# ──────────────────────────────────────────────────────────────
def test_validate_config():
    _separator("Prueba 5: validate-config con config.example.yaml")

    config_path = Path(__file__).parent.parent / "config.example.yaml"
    assert config_path.exists(), f"config.example.yaml no encontrado en {config_path}"

    rc, stdout, stderr = _run_cli("validate-config", "-c", str(config_path))
    _info(f"stdout: {stdout.strip()!r}")
    _info(f"stderr: {stderr.strip()!r}")

    assert rc == 0, f"validate-config retornó {rc}\nstderr: {stderr}"
    assert "válida" in stdout.lower() or "valid" in stdout.lower(), (
        f"Output no indica config válida: {stdout!r}"
    )
    _ok("config.example.yaml es una configuración válida")

    # Verificar que parsea correctamente con el loader
    from architect.config.loader import load_config
    app_config = load_config(config_path=config_path)
    assert app_config.llm.model == "gpt-4o-mini"
    assert app_config.llm.retries == 2
    assert app_config.llm.stream is True
    assert app_config.workspace.allow_delete is False
    _ok(f"Config parseada: model={app_config.llm.model!r}, retries={app_config.llm.retries}")

    return True


# ──────────────────────────────────────────────────────────────
# Prueba 6: Inicialización completa sin LLM
# ──────────────────────────────────────────────────────────────
def test_full_init_without_llm():
    _separator("Prueba 6: Inicialización completa del sistema (sin LLM)")

    from architect.agents.registry import get_agent, DEFAULT_AGENTS
    from architect.config.schema import AppConfig, WorkspaceConfig
    from architect.core import AgentLoop, ContextBuilder, MixedModeRunner, GracefulShutdown
    from architect.core.timeout import StepTimeout
    from architect.execution.engine import ExecutionEngine
    from architect.logging.setup import configure_logging
    from architect.tools import ToolRegistry, register_filesystem_tools

    # Config por defecto
    config = AppConfig()
    _ok("AppConfig() con defaults: OK")

    # Logging
    configure_logging(config.logging, json_output=False, quiet=True)
    _ok("configure_logging(): OK")

    # Tool registry
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)
    tool_names = [t.name for t in registry.list_all()]
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "list_files" in tool_names
    _ok(f"ToolRegistry: {tool_names}")

    # Agentes por defecto
    assert len(DEFAULT_AGENTS) == 4
    _ok(f"DEFAULT_AGENTS: {list(DEFAULT_AGENTS.keys())}")

    # GracefulShutdown
    shutdown = GracefulShutdown()
    assert not shutdown.should_stop
    shutdown.restore_defaults()
    _ok("GracefulShutdown: OK")

    # StepTimeout (no-op con seconds=0)
    with StepTimeout(0):
        pass
    _ok("StepTimeout(0): OK (no-op)")

    # Execution engine
    engine = ExecutionEngine(registry, config, confirm_mode="yolo")
    _ok(f"ExecutionEngine(yolo): OK")

    # ContextBuilder
    ctx = ContextBuilder()
    plan_config = get_agent("plan", {})
    msgs = ctx.build_initial(plan_config, "test prompt")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    _ok(f"ContextBuilder: {len(msgs)} mensajes iniciales")

    _ok("Sistema completo inicializado correctamente (sin LLM)")
    return True


# ──────────────────────────────────────────────────────────────
# Prueba 7: dry-run sin API key
# ──────────────────────────────────────────────────────────────
def test_dry_run_no_api_key():
    _separator("Prueba 7: dry-run (debería fallar con error de LLM, no de config)")

    import os
    # Asegurarse de que no hay API key real
    env_backup = os.environ.pop("LITELLM_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)

    rc, stdout, stderr = _run_cli(
        "run",
        "lee el README.md y dime cuántas líneas tiene",
        "-a", "resume",
        "--dry-run",
        "--mode", "yolo",
        "--quiet",
    )

    # Restaurar env
    if env_backup:
        os.environ["LITELLM_API_KEY"] = env_backup

    _info(f"Exit code: {rc}")
    _info(f"stderr: {stderr[:300]!r}")

    # Debe fallar (sin API key no puede hablar con el LLM)
    # pero el fallo debe ser del LLM (exit 1, 4) — no de config (exit 3)
    assert rc != 3, f"Falló con error de configuración (rc=3), no de LLM: {stderr}"
    assert rc != 0, "Esperaba fallo (sin API key), pero salió con éxito"

    _ok(f"Fallo correcto con exit code {rc} (error de LLM, no de config)")
    return True


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(f"  TEST FASE 8 - Integración Final (v{EXPECTED_VERSION})")
    print("=" * 60)

    results = []
    tests = [
        ("Importaciones de módulos", test_imports),
        ("Versión consistente", test_version_consistency),
        ("CLI --help / subcomandos", test_cli_help),
        ("Subcomando agents", test_agents_command),
        ("validate-config con example", test_validate_config),
        ("Inicialización completa sin LLM", test_full_init_without_llm),
        ("dry-run sin API key", test_dry_run_no_api_key),
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
            print(f"\n  ✗ ASSERTION: {e}", file=sys.stderr)
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
        print("\n  ✅ MVP completo — todas las pruebas pasaron")
        sys.exit(0)
