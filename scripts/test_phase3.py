#!/usr/bin/env python3
"""
Script de prueba para verificar la Fase 3.

Demuestra el funcionamiento del sistema de agentes especializados
y el modo mixto plan→build.

IMPORTANTE: Este script requiere una API key válida configurada.
"""

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architect.agents import DEFAULT_AGENTS, get_agent, list_available_agents
from architect.config.schema import AgentConfig, AppConfig, LLMConfig, WorkspaceConfig
from architect.core import AgentLoop, ContextBuilder, MixedModeRunner
from architect.execution import ExecutionEngine
from architect.llm import LLMAdapter
from architect.logging import configure_logging_basic
from architect.tools import ToolRegistry, register_filesystem_tools


def test_agents_registry():
    """Prueba el registro de agentes."""
    print("=" * 70)
    print("PRUEBA 1: Registry de Agentes")
    print("=" * 70)
    print()

    print(f"Agentes por defecto: {len(DEFAULT_AGENTS)}")
    for name, config in DEFAULT_AGENTS.items():
        print(f"  - {name}:")
        print(f"      allowed_tools: {', '.join(config.allowed_tools[:3])}...")
        print(f"      confirm_mode: {config.confirm_mode}")
        print(f"      max_steps: {config.max_steps}")
    print()

    # Probar list_available_agents
    available = list_available_agents({})
    print(f"✓ Agentes disponibles: {', '.join(available)}")
    print()

    # Probar get_agent
    review_agent = get_agent("review", {})
    print(f"✓ Agente 'review' obtenido:")
    print(f"  confirm_mode: {review_agent.confirm_mode}")
    print(f"  allowed_tools: {review_agent.allowed_tools}")
    print()


def test_single_agent_mode():
    """Prueba ejecución con un solo agente (review)."""
    print("=" * 70)
    print("PRUEBA 2: Modo Single Agent (review)")
    print("=" * 70)
    print()

    configure_logging_basic()

    config = AppConfig(
        llm=LLMConfig(
            model="gpt-4o-mini",
            api_key_env="LITELLM_API_KEY",
        ),
        workspace=WorkspaceConfig(
            root=Path.cwd(),
            allow_delete=False,
        ),
    )

    # Obtener agente review
    agent_config = get_agent("review", {})

    print(f"✓ Agente 'review' configurado")
    print(f"  System prompt (primeras líneas):")
    lines = agent_config.system_prompt.split("\n")[:3]
    for line in lines:
        print(f"    {line}")
    print()

    # Setup completo
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)

    try:
        llm = LLMAdapter(config.llm)
    except Exception as e:
        print(f"❌ Error al crear LLMAdapter: {e}")
        print("   Configura LITELLM_API_KEY para ejecutar esta prueba")
        return

    engine = ExecutionEngine(registry, config, confirm_mode=agent_config.confirm_mode)
    ctx = ContextBuilder()
    loop = AgentLoop(llm, engine, agent_config, ctx)

    prompt = "Revisa el archivo README.md y dame feedback sobre su estructura"

    print(f"Ejecutando: {prompt}")
    print()

    try:
        state = loop.run(prompt)
        print()
        print("Resultado:")
        print("-" * 70)
        print(state.final_output)
        print()
        print(f"Estado: {state.status}")
        print(f"Steps: {state.current_step}")
        print()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


def test_mixed_mode():
    """Prueba modo mixto plan→build."""
    print("=" * 70)
    print("PRUEBA 3: Modo Mixto (plan → build)")
    print("=" * 70)
    print()

    configure_logging_basic()

    config = AppConfig(
        llm=LLMConfig(
            model="gpt-4o-mini",
            api_key_env="LITELLM_API_KEY",
        ),
        workspace=WorkspaceConfig(
            root=Path.cwd(),
            allow_delete=False,
        ),
    )

    # Obtener agentes plan y build
    plan_config = get_agent("plan", {})
    build_config = get_agent("build", {})

    print(f"✓ Agentes configurados:")
    print(f"  - plan: {plan_config.max_steps} steps, {plan_config.confirm_mode}")
    print(f"  - build: {build_config.max_steps} steps, {build_config.confirm_mode}")
    print()

    # Setup
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)

    try:
        llm = LLMAdapter(config.llm)
    except Exception as e:
        print(f"❌ Error al crear LLMAdapter: {e}")
        print("   Configura LITELLM_API_KEY para ejecutar esta prueba")
        return

    plan_engine = ExecutionEngine(registry, config, confirm_mode="confirm-all")
    build_engine = ExecutionEngine(registry, config, confirm_mode="yolo")

    # Habilitar dry-run para no modificar archivos reales
    build_engine.set_dry_run(True)
    print("🔍 Dry-run habilitado (no se modificarán archivos)")
    print()

    runner = MixedModeRunner(llm, build_engine, plan_config, build_config, ContextBuilder())

    prompt = "Crea un archivo test_phase3.txt con un resumen de esta fase"

    print(f"Ejecutando: {prompt}")
    print()

    try:
        state = runner.run(prompt)
        print()
        print("Resultado Final:")
        print("-" * 70)
        print(state.final_output)
        print()
        print(f"Estado: {state.status}")
        print(f"Steps: {state.current_step}")
        print()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


def main():
    """Ejecuta todas las pruebas."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "PRUEBAS DE FASE 3 - Sistema de Agentes" + " " * 14 + "║")
    print("╚" + "═" * 68 + "╝")
    print()

    # Prueba 1: Registry
    test_agents_registry()

    print()
    print("─" * 70)
    print()

    # Prueba 2: Single agent (requiere API key)
    try:
        test_single_agent_mode()
    except KeyboardInterrupt:
        print("\n⚠️  Prueba interrumpida")

    print()
    print("─" * 70)
    print()

    # Prueba 3: Mixed mode (requiere API key)
    try:
        test_mixed_mode()
    except KeyboardInterrupt:
        print("\n⚠️  Prueba interrumpida")

    print()
    print("=" * 70)
    print("✓ PRUEBAS COMPLETADAS")
    print("=" * 70)


if __name__ == "__main__":
    main()
