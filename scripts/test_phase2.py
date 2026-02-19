#!/usr/bin/env python3
"""
Script de prueba para verificar la Fase 2.

Demuestra el funcionamiento del agent loop completo,
integrando LLM, tools y execution engine.

IMPORTANTE: Este script requiere una API key válida configurada
en la variable de entorno especificada (default: LITELLM_API_KEY).
"""

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architect.config.schema import AgentConfig, AppConfig, LLMConfig, WorkspaceConfig
from architect.core import AgentLoop, ContextBuilder
from architect.execution import ExecutionEngine
from architect.llm import LLMAdapter
from architect.logging import configure_logging_basic
from architect.tools import ToolRegistry, register_filesystem_tools


def main() -> None:
    """Prueba del agent loop completo (requiere API key)."""

    # Configurar logging
    configure_logging_basic()

    print("=" * 70)
    print("PRUEBA DE FASE 2 - LLM Adapter + Agent Loop")
    print("=" * 70)
    print()

    # Crear configuración
    config = AppConfig(
        llm=LLMConfig(
            model="gpt-4o-mini",  # Modelo más económico para testing
            api_key_env="LITELLM_API_KEY",
        ),
        workspace=WorkspaceConfig(
            root=Path.cwd(),
            allow_delete=False,
        ),
    )

    # Crear agente de prueba simple
    test_agent = AgentConfig(
        system_prompt=(
            "Eres un asistente útil que puede leer y listar archivos. "
            "Responde de forma concisa y clara."
        ),
        allowed_tools=["read_file", "list_files"],
        confirm_mode="yolo",  # Sin confirmación para testing
        max_steps=5,
    )

    print(f"✓ Configuración creada:")
    print(f"  Modelo: {config.llm.model}")
    print(f"  Workspace: {config.workspace.root}")
    print(f"  Agente: {test_agent.max_steps} pasos max, modo {test_agent.confirm_mode}")
    print()

    # Crear registry y registrar tools
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)
    print(f"✓ Tools registradas: {', '.join(t.name for t in registry.list_all())}")
    print()

    # Crear LLM adapter
    try:
        llm = LLMAdapter(config.llm)
        print(f"✓ LLMAdapter creado: {llm}")
        print()
    except Exception as e:
        print(f"❌ Error al crear LLMAdapter: {e}")
        print()
        print("NOTA: Este script requiere una API key válida.")
        print(f"Configura la variable de entorno {config.llm.api_key_env}")
        return

    # Crear execution engine
    engine = ExecutionEngine(registry, config, confirm_mode=test_agent.confirm_mode)
    print(f"✓ ExecutionEngine creado: {engine}")
    print()

    # Crear context builder
    ctx = ContextBuilder()
    print(f"✓ ContextBuilder creado")
    print()

    # Crear agent loop
    loop = AgentLoop(llm, engine, test_agent, ctx)
    print(f"✓ AgentLoop creado")
    print()

    # Ejecutar una tarea simple
    print("=" * 70)
    print("EJECUTANDO TAREA")
    print("=" * 70)
    print()

    prompt = "Lista los archivos .md en el directorio actual y muéstrame el contenido del README.md"
    print(f"Prompt: {prompt}")
    print()

    try:
        state = loop.run(prompt)

        print()
        print("=" * 70)
        print("RESULTADO")
        print("=" * 70)
        print()
        print(f"Estado: {state.status}")
        print(f"Steps ejecutados: {state.current_step}")
        print(f"Tool calls totales: {state.total_tool_calls}")
        print()
        print("Output final:")
        print("-" * 70)
        print(state.final_output)
        print()

        # Mostrar detalles de steps
        if state.steps:
            print("=" * 70)
            print("DETALLES DE STEPS")
            print("=" * 70)
            print()
            for step in state.steps:
                print(f"Step {step.step_number}:")
                print(f"  Tool calls: {len(step.tool_calls_made)}")
                for tc in step.tool_calls_made:
                    print(f"    - {tc.tool_name}: success={tc.result.success}")
                print()

    except Exception as e:
        print(f"❌ Error durante la ejecución: {e}")
        import traceback

        traceback.print_exc()

    print("=" * 70)
    print("✓ PRUEBA COMPLETADA")
    print("=" * 70)


if __name__ == "__main__":
    main()
