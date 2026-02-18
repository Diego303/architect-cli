#!/usr/bin/env python3
"""
Script de prueba para verificar la Fase 1.

Demuestra el funcionamiento del sistema de tools, registry,
execution engine y políticas de confirmación.
"""

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architect.config.schema import AppConfig, WorkspaceConfig
from architect.execution import ExecutionEngine
from architect.logging import configure_logging_basic
from architect.tools import ToolRegistry, register_filesystem_tools


def main() -> None:
    """Prueba básica del sistema de tools y execution engine."""

    # Configurar logging
    configure_logging_basic()

    print("=" * 70)
    print("PRUEBA DE FASE 1 - Tools y Execution Engine")
    print("=" * 70)
    print()

    # Crear configuración básica
    config = AppConfig(
        workspace=WorkspaceConfig(
            root=Path.cwd(),
            allow_delete=False,
        )
    )

    # Crear registry y registrar tools
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)

    print(f"✓ ToolRegistry creado: {registry}")
    print(f"  Tools registradas: {', '.join(t.name for t in registry.list_all())}")
    print()

    # Crear execution engine en modo yolo (sin confirmación)
    engine = ExecutionEngine(registry, config, confirm_mode="yolo")
    print(f"✓ ExecutionEngine creado: {engine}")
    print()

    # Prueba 1: Listar archivos
    print("PRUEBA 1: Listar archivos del directorio actual")
    print("-" * 70)
    result = engine.execute_tool_call("list_files", {"path": ".", "pattern": "*.md"})
    print(f"Success: {result.success}")
    print(f"Output:\n{result.output}")
    print()

    # Prueba 2: Leer un archivo (README.md)
    print("PRUEBA 2: Leer README.md")
    print("-" * 70)
    result = engine.execute_tool_call("read_file", {"path": "README.md"})
    print(f"Success: {result.success}")
    if result.success:
        # Mostrar solo las primeras líneas
        lines = result.output.split("\n")[:10]
        print(f"Output (primeras 10 líneas):\n{chr(10).join(lines)}")
        print(f"... (total: {len(result.output)} caracteres)")
    else:
        print(f"Error: {result.error}")
    print()

    # Prueba 3: Dry-run de escritura
    print("PRUEBA 3: Dry-run de write_file")
    print("-" * 70)
    engine.set_dry_run(True)
    result = engine.execute_tool_call(
        "write_file",
        {"path": "test_output.txt", "content": "Este es un test\n", "mode": "overwrite"},
    )
    print(f"Success: {result.success}")
    print(f"Output: {result.output}")
    print()

    # Prueba 4: Intentar path traversal (debe fallar)
    print("PRUEBA 4: Intentar path traversal (debe fallar)")
    print("-" * 70)
    engine.set_dry_run(False)
    result = engine.execute_tool_call("read_file", {"path": "../../etc/passwd"})
    print(f"Success: {result.success}")
    print(f"Error: {result.error}")
    print()

    # Prueba 5: Intentar delete sin permisos (debe fallar)
    print("PRUEBA 5: Intentar delete sin allow_delete (debe fallar)")
    print("-" * 70)
    result = engine.execute_tool_call("delete_file", {"path": "test_output.txt"})
    print(f"Success: {result.success}")
    print(f"Error: {result.error}")
    print()

    # Prueba 6: Obtener schemas para LLM
    print("PRUEBA 6: Generar schemas para LLM")
    print("-" * 70)
    schemas = registry.get_schemas(["read_file", "list_files"])
    print(f"Schemas generados: {len(schemas)} tools")
    for schema in schemas:
        tool_name = schema["function"]["name"]
        tool_desc = schema["function"]["description"][:60] + "..."
        print(f"  - {tool_name}: {tool_desc}")
    print()

    print("=" * 70)
    print("✓ TODAS LAS PRUEBAS COMPLETADAS")
    print("=" * 70)


if __name__ == "__main__":
    main()
