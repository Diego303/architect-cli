#!/usr/bin/env python3
"""
Script de prueba para verificar la Fase 5.

Demuestra el sistema completo de logging:
- Logging estructurado con structlog
- Dos pipelines: archivo (JSON) y stderr (humano)
- Niveles de verbose
- Formato JSON para archivos
- Logs legibles para terminal
"""

import sys
import tempfile
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architect.config.schema import LoggingConfig
from architect.logging import configure_logging, get_logger


def test_logging_levels():
    """Prueba diferentes niveles de logging."""
    print("=" * 70)
    print("PRUEBA 1: Niveles de Logging")
    print("=" * 70)
    print()

    for verbose_level, label in [(0, "WARNING"), (1, "INFO"), (2, "DEBUG"), (3, "DEBUG+")]:
        print(f"Verbose level {verbose_level} ({label}):")
        print("-" * 70)

        config = LoggingConfig(
            level="debug",
            verbose=verbose_level,
            file=None,
        )

        configure_logging(config, json_output=False, quiet=False)

        log = get_logger(__name__)

        # Generar logs de diferentes niveles
        log.debug("test.debug", message="Mensaje de debug", level=verbose_level)
        log.info("test.info", message="Mensaje de info", level=verbose_level)
        log.warning("test.warning", message="Mensaje de warning", level=verbose_level)
        log.error("test.error", message="Mensaje de error", level=verbose_level)

        print()


def test_json_logging():
    """Prueba logging a archivo JSON."""
    print("=" * 70)
    print("PRUEBA 2: Logging a Archivo JSON")
    print("=" * 70)
    print()

    # Crear archivo temporal
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as tmp_file:
        log_file = Path(tmp_file.name)

    print(f"Archivo de log: {log_file}")
    print()

    try:
        # Configurar logging con archivo
        config = LoggingConfig(
            level="debug",
            verbose=1,
            file=log_file,
        )

        configure_logging(config, json_output=False, quiet=False)

        log = get_logger("test_module")

        # Generar logs con contexto
        print("Generando logs con contexto...")
        log.info(
            "agent.step.start",
            step=1,
            agent="build",
            prompt="crear archivo test",
        )

        log.info(
            "tool.call",
            tool="write_file",
            args={"path": "test.txt", "content": "hola"},
            step=1,
        )

        log.info(
            "tool.result",
            tool="write_file",
            success=True,
            step=1,
        )

        log.info(
            "agent.step.complete",
            step=1,
            tool_calls=1,
        )

        print()

        # Leer y mostrar el archivo JSON
        print("Contenido del archivo JSON:")
        print("-" * 70)
        with open(log_file) as f:
            for line in f:
                print(line.rstrip())

        print()

    finally:
        # Limpiar
        if log_file.exists():
            log_file.unlink()


def test_quiet_mode():
    """Prueba modo quiet (solo errores)."""
    print("=" * 70)
    print("PRUEBA 3: Modo Quiet")
    print("=" * 70)
    print()

    config = LoggingConfig(
        level="info",
        verbose=1,
        file=None,
    )

    configure_logging(config, json_output=False, quiet=True)

    log = get_logger(__name__)

    print("En modo quiet, solo deberías ver el error:")
    print("-" * 70)

    # Estos no se deberían mostrar
    log.debug("test.debug", message="No deberías ver esto")
    log.info("test.info", message="No deberías ver esto")
    log.warning("test.warning", message="No deberías ver esto")

    # Este sí se debe mostrar
    log.error("test.error", message="✓ Este error SÍ se debe ver en modo quiet")

    print()


def test_structured_context():
    """Prueba logging estructurado con contexto."""
    print("=" * 70)
    print("PRUEBA 4: Logging Estructurado con Contexto")
    print("=" * 70)
    print()

    config = LoggingConfig(
        level="info",
        verbose=1,
        file=None,
    )

    configure_logging(config, json_output=False, quiet=False)

    log = get_logger("architect.core.loop")

    print("Simulando ejecución de agente:")
    print("-" * 70)

    # Simular logs de un agent loop
    log.info(
        "agent.loop.start",
        prompt="refactorizar main.py",
        max_steps=20,
        agent="build",
    )

    for step in range(3):
        log.info(
            "agent.step.start",
            step=step,
        )

        log.info(
            "llm.completion.start",
            step=step,
            messages_count=step * 2 + 2,
            has_tools=True,
        )

        log.info(
            "tool.call",
            step=step,
            tool="read_file" if step == 0 else "write_file",
            args_preview="path=main.py" if step == 0 else "path=main.py, content=...",
        )

        log.info(
            "tool.result",
            step=step,
            success=True,
        )

    log.info(
        "agent.loop.complete",
        status="success",
        total_steps=3,
        total_tool_calls=3,
    )

    print()


def test_dual_pipeline():
    """Prueba los dos pipelines simultáneamente."""
    print("=" * 70)
    print("PRUEBA 5: Dual Pipeline (Archivo JSON + Stderr Humano)")
    print("=" * 70)
    print()

    # Crear archivo temporal
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as tmp_file:
        log_file = Path(tmp_file.name)

    print(f"Archivo JSON: {log_file}")
    print()

    try:
        config = LoggingConfig(
            level="info",
            verbose=1,
            file=log_file,
        )

        configure_logging(config, json_output=False, quiet=False)

        log = get_logger("dual_test")

        print("Generando logs (deberían aparecer en stderr Y en archivo):")
        print("-" * 70)

        log.info("test.message.1", data="Primer mensaje", number=1)
        log.info("test.message.2", data="Segundo mensaje", number=2)
        log.warning("test.warning", data="Un warning", number=3)

        print()
        print("Logs en stderr (arriba) y en archivo JSON (abajo):")
        print("-" * 70)

        with open(log_file) as f:
            for line in f:
                print(line.rstrip())

        print()

    finally:
        if log_file.exists():
            log_file.unlink()


def main():
    """Ejecuta todas las pruebas."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 16 + "PRUEBAS DE FASE 5 - Logging Completo" + " " * 16 + "║")
    print("╚" + "═" * 68 + "╝")
    print()

    try:
        # Prueba 1: Niveles
        test_logging_levels()
        print("─" * 70)
        print()

        # Prueba 2: JSON
        test_json_logging()
        print("─" * 70)
        print()

        # Prueba 3: Quiet
        test_quiet_mode()
        print("─" * 70)
        print()

        # Prueba 4: Contexto estructurado
        test_structured_context()
        print("─" * 70)
        print()

        # Prueba 5: Dual pipeline
        test_dual_pipeline()

    except KeyboardInterrupt:
        print("\n⚠️  Pruebas interrumpidas")

    print("=" * 70)
    print("✓ PRUEBAS COMPLETADAS")
    print("=" * 70)
    print()
    print("Notas:")
    print("- Logs van a stderr (no stdout) para no romper pipes")
    print("- Archivo JSON tiene un log por línea (JSON Lines)")
    print("- Verbose levels: 0=WARNING, 1=INFO, 2=DEBUG, 3+=DEBUG completo")
    print("- En quiet mode solo se muestran errores")
    print()


if __name__ == "__main__":
    main()
