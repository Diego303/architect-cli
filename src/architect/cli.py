"""
CLI principal de architect usando Click.

Define todos los comandos y opciones disponibles para el usuario.
"""

import sys
from pathlib import Path

import click

from .agents import AgentNotFoundError, DEFAULT_AGENTS, get_agent, list_available_agents
from .config.loader import load_config
from .core import AgentLoop, ContextBuilder, MixedModeRunner
from .execution import ExecutionEngine
from .llm import LLMAdapter
from .logging import configure_logging
from .mcp import MCPDiscovery
from .tools import ToolRegistry, register_filesystem_tools


@click.group()
@click.version_option(version="0.1.0", prog_name="architect")
def main() -> None:
    """architect - Herramienta CLI headless y agentica para orquestar agentes de IA.

    architect te permite ejecutar tareas complejas usando modelos de lenguaje,
    con control explícito, configuración declarativa y sin intervención humana.
    """
    pass


@main.command()
@click.argument("prompt", required=True)
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
@click.option(
    "-a",
    "--agent",
    default=None,
    help="Agente a utilizar (plan, build, resume, review, o custom)",
)
@click.option(
    "-m",
    "--mode",
    type=click.Choice(["confirm-all", "confirm-sensitive", "yolo"]),
    help="Modo de confirmación de acciones",
)
@click.option(
    "-w",
    "--workspace",
    type=click.Path(path_type=Path),
    help="Directorio de trabajo (workspace root)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Simular ejecución sin realizar cambios reales",
)
@click.option(
    "--model",
    help="Modelo LLM a usar (ej: gpt-4o, claude-3-sonnet)",
)
@click.option(
    "--api-base",
    help="URL base de la API del LLM",
)
@click.option(
    "--api-key",
    help="API key (también puede usar env var)",
)
@click.option(
    "--no-stream",
    is_flag=True,
    help="Deshabilitar streaming de respuestas",
)
@click.option(
    "--mcp-config",
    type=click.Path(exists=True, path_type=Path),
    help="Archivo de configuración MCP adicional",
)
@click.option(
    "--disable-mcp",
    is_flag=True,
    help="Deshabilitar conexión a servidores MCP",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Nivel de verbose (-v, -vv, -vvv para más detalle)",
)
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warn", "error"]),
    help="Nivel de logging explícito",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    help="Archivo donde guardar logs estructurados (JSON)",
)
@click.option(
    "--max-steps",
    type=int,
    help="Número máximo de pasos del agente",
)
@click.option(
    "--timeout",
    type=int,
    help="Timeout en segundos para llamadas LLM",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Salida en formato JSON estructurado",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Modo silencioso (solo errores críticos)",
)
def run(prompt: str, **kwargs) -> None:  # type: ignore
    """Ejecuta una tarea usando un agente de IA.

    PROMPT: Descripción de la tarea a realizar

    Ejemplos:

        \b
        # Análisis seguro (solo lectura)
        $ architect run "analiza este proyecto" -a review

        \b
        # Construcción con confirmación
        $ architect run "refactoriza main.py" -a build

        \b
        # Ejecución automática total
        $ architect run "genera scaffolding" --mode yolo

        \b
        # Dry-run para ver qué haría sin ejecutar
        $ architect run "modifica config.yaml" --dry-run
    """
    try:
        # Cargar configuración primero (necesaria para logging)
        config = load_config(
            config_path=kwargs.get("config"),
            cli_args=kwargs,
        )

        # Configurar logging completo
        configure_logging(
            config.logging,
            json_output=kwargs.get("json_output", False),
            quiet=kwargs.get("quiet", False),
        )

        # Determinar agente a usar
        agent_name = kwargs.get("agent")
        use_mixed_mode = agent_name is None  # Sin agente = modo mixto

        # Crear tool registry y registrar tools
        registry = ToolRegistry()
        register_filesystem_tools(registry, config.workspace)

        # Descubrir y registrar tools MCP si está habilitado
        if not kwargs.get("disable_mcp") and config.mcp.servers:
            if not kwargs.get("quiet"):
                click.echo(f"🔌 Descubriendo tools MCP de {len(config.mcp.servers)} servidor(es)...")

            discovery = MCPDiscovery()
            mcp_stats = discovery.discover_and_register(config.mcp.servers, registry)

            if not kwargs.get("quiet"):
                if mcp_stats["servers_success"] > 0:
                    click.echo(
                        f"   ✓ {mcp_stats['tools_registered']} tools MCP registradas "
                        f"desde {mcp_stats['servers_success']} servidor(es)"
                    )
                if mcp_stats["servers_failed"] > 0:
                    click.echo(
                        f"   ⚠️  {mcp_stats['servers_failed']} servidor(es) no disponible(s)",
                        err=True,
                    )
                click.echo()

        # Crear LLM adapter
        llm = LLMAdapter(config.llm)

        # Crear context builder
        ctx = ContextBuilder()

        # CLI overrides para configuración de agentes
        cli_overrides = {
            "mode": kwargs.get("mode"),
            "max_steps": kwargs.get("max_steps"),
        }

        # Ejecutar según modo
        if use_mixed_mode:
            # Modo mixto: plan → build
            try:
                plan_config = get_agent("plan", config.agents, cli_overrides)
                build_config = get_agent("build", config.agents, cli_overrides)
            except AgentNotFoundError as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)

            # Crear execution engines para ambos agentes
            # Plan: siempre en modo confirm-all (readonly)
            plan_engine = ExecutionEngine(registry, config, confirm_mode="confirm-all")

            # Build: según configuración
            build_engine = ExecutionEngine(
                registry, config, confirm_mode=build_config.confirm_mode
            )

            # Configurar dry-run si está habilitado
            if kwargs.get("dry_run"):
                plan_engine.set_dry_run(True)
                build_engine.set_dry_run(True)
                if not kwargs.get("quiet"):
                    click.echo("🔍 Modo DRY-RUN activado (no se ejecutarán cambios reales)\n")

            # Crear mixed mode runner
            runner = MixedModeRunner(llm, build_engine, plan_config, build_config, ctx)

            # Mostrar info inicial si no es quiet
            if not kwargs.get("quiet"):
                click.echo(f"🏗️  architect v0.5.0")
                click.echo(f"📝 Prompt: {prompt}")
                click.echo(f"🤖 Modelo: {config.llm.model}")
                click.echo(f"📁 Workspace: {config.workspace.root}")
                click.echo(f"🔀 Modo: mixto (plan → build)")
                click.echo(f"⚙️  Confirmación: {build_config.confirm_mode}")
                click.echo()

            # Ejecutar flujo plan → build
            state = runner.run(prompt)

        else:
            # Modo single agent
            try:
                agent_config = get_agent(agent_name, config.agents, cli_overrides)
            except AgentNotFoundError as e:
                click.echo(f"❌ Error: {e}", err=True)
                available = list_available_agents(config.agents)
                click.echo(f"\nAgentes disponibles: {', '.join(available)}", err=True)
                sys.exit(1)

            # Crear execution engine
            engine = ExecutionEngine(registry, config, confirm_mode=agent_config.confirm_mode)

            # Configurar dry-run si está habilitado
            if kwargs.get("dry_run"):
                engine.set_dry_run(True)
                if not kwargs.get("quiet"):
                    click.echo("🔍 Modo DRY-RUN activado (no se ejecutarán cambios reales)\n")

            # Crear agent loop
            loop = AgentLoop(llm, engine, agent_config, ctx)

            # Mostrar info inicial si no es quiet
            if not kwargs.get("quiet"):
                click.echo(f"🏗️  architect v0.5.0")
                click.echo(f"📝 Prompt: {prompt}")
                click.echo(f"🤖 Modelo: {config.llm.model}")
                click.echo(f"📁 Workspace: {config.workspace.root}")
                click.echo(f"🎭 Agente: {agent_name}")
                click.echo(f"⚙️  Modo: {agent_config.confirm_mode}")
                click.echo()

            # Ejecutar agent loop
            state = loop.run(prompt)

        # Mostrar resultado
        if kwargs.get("json_output"):
            import json
            output = state.to_output_dict()
            click.echo(json.dumps(output, indent=2))
        else:
            if not kwargs.get("quiet"):
                click.echo()
                click.echo("=" * 70)
                click.echo("RESULTADO")
                click.echo("=" * 70)
                click.echo()

            if state.final_output:
                click.echo(state.final_output)

            if not kwargs.get("quiet"):
                click.echo()
                click.echo(f"Estado: {state.status}")
                click.echo(f"Steps: {state.current_step}")
                click.echo(f"Tool calls: {state.total_tool_calls}")

        # Código de salida según el estado
        exit_code = {"success": 0, "partial": 2, "failed": 1}.get(state.status, 1)
        sys.exit(exit_code)

    except FileNotFoundError as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(3)
    except Exception as e:
        click.echo(f"❌ Error inesperado: {e}", err=True)
        if kwargs.get("verbose", 0) > 1:
            import traceback

            traceback.print_exc()
        sys.exit(1)


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración a validar",
)
def validate_config(config: Path | None) -> None:
    """Valida un archivo de configuración YAML.

    Útil para verificar sintaxis y valores antes de ejecutar.
    """
    try:
        app_config = load_config(config_path=config)
        click.echo("✓ Configuración válida")
        click.echo(f"  Modelo: {app_config.llm.model}")
        click.echo(f"  Agentes definidos: {len(app_config.agents)}")
        click.echo(f"  Servidores MCP: {len(app_config.mcp.servers)}")
    except FileNotFoundError as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(3)
    except Exception as e:
        click.echo(f"❌ Configuración inválida: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
