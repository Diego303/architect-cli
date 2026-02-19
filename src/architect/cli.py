"""
CLI principal de architect usando Click.

Define todos los comandos y opciones disponibles para el usuario.
"""

import json
import sys
from pathlib import Path
from typing import Callable

import click

from .agents import AgentNotFoundError, get_agent, list_available_agents
from .config.loader import load_config
from .core import AgentLoop, ContextBuilder, MixedModeRunner
from .core.shutdown import GracefulShutdown
from .execution import ExecutionEngine
from .llm import LLMAdapter
from .logging import configure_logging
from .mcp import MCPDiscovery
from .tools import ToolRegistry, register_filesystem_tools

# Códigos de salida (según Plan_Implementacion.md §6.3)
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_CONFIG_ERROR = 3
EXIT_AUTH_ERROR = 4
EXIT_TIMEOUT = 5
EXIT_INTERRUPTED = 130


@click.group()
@click.version_option(version="0.8.0", prog_name="architect")
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

        \b
        # Salida JSON estructurada (para pipes)
        $ architect run "resume el proyecto" --quiet --json | jq .
    """
    try:
        # Instalar GracefulShutdown para SIGINT + SIGTERM antes de cualquier otra cosa
        shutdown = GracefulShutdown()
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

        # Determinar si usar streaming
        # Streaming activo por defecto, desactivado con --no-stream, --json o --quiet
        use_stream = (
            not kwargs.get("no_stream", False)
            and not kwargs.get("json_output", False)
            and config.llm.stream
        )

        # Callback de streaming: escribe a stderr para no romper pipes
        # Se desactiva con --quiet o --json
        on_stream_chunk: Callable[[str], None] | None = None
        if use_stream and not kwargs.get("quiet", False):
            def on_stream_chunk(chunk: str) -> None:  # type: ignore[misc]
                sys.stderr.write(chunk)
                sys.stderr.flush()

        # Determinar agente a usar
        agent_name = kwargs.get("agent")
        use_mixed_mode = agent_name is None  # Sin agente = modo mixto

        # Crear tool registry y registrar tools
        registry = ToolRegistry()
        register_filesystem_tools(registry, config.workspace)

        # Descubrir y registrar tools MCP si está habilitado
        if not kwargs.get("disable_mcp") and config.mcp.servers:
            if not kwargs.get("quiet"):
                click.echo(
                    f"🔌 Descubriendo tools MCP de {len(config.mcp.servers)} servidor(es)...",
                    err=True,
                )

            discovery = MCPDiscovery()
            mcp_stats = discovery.discover_and_register(config.mcp.servers, registry)

            if not kwargs.get("quiet"):
                if mcp_stats["servers_success"] > 0:
                    click.echo(
                        f"   ✓ {mcp_stats['tools_registered']} tools MCP registradas "
                        f"desde {mcp_stats['servers_success']} servidor(es)",
                        err=True,
                    )
                if mcp_stats["servers_failed"] > 0:
                    click.echo(
                        f"   ⚠️  {mcp_stats['servers_failed']} servidor(es) no disponible(s)",
                        err=True,
                    )
                click.echo(err=True)

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
                sys.exit(EXIT_FAILED)

            # Crear execution engines para ambos agentes
            plan_engine = ExecutionEngine(registry, config, confirm_mode="confirm-all")
            build_engine = ExecutionEngine(
                registry, config, confirm_mode=build_config.confirm_mode
            )

            # Configurar dry-run si está habilitado
            if kwargs.get("dry_run"):
                plan_engine.set_dry_run(True)
                build_engine.set_dry_run(True)
                if not kwargs.get("quiet"):
                    click.echo(
                        "🔍 Modo DRY-RUN activado (no se ejecutarán cambios reales)\n",
                        err=True,
                    )

            # Crear mixed mode runner (con shutdown y timeout)
            runner = MixedModeRunner(
                llm, build_engine, plan_config, build_config, ctx,
                shutdown=shutdown,
                step_timeout=kwargs.get("timeout") or 0,
            )

            # Mostrar info inicial si no es quiet
            if not kwargs.get("quiet"):
                click.echo(f"🏗️  architect v0.8.0", err=True)
                click.echo(f"📝 Prompt: {prompt}", err=True)
                click.echo(f"🤖 Modelo: {config.llm.model}", err=True)
                click.echo(f"📁 Workspace: {config.workspace.root}", err=True)
                click.echo(f"🔀 Modo: mixto (plan → build)", err=True)
                click.echo(f"⚙️  Confirmación: {build_config.confirm_mode}", err=True)
                click.echo(f"📡 Streaming: {'sí' if use_stream else 'no'}", err=True)
                click.echo(err=True)

            # Ejecutar flujo plan → build (con streaming en fase build)
            state = runner.run(prompt, stream=use_stream, on_stream_chunk=on_stream_chunk)

        else:
            # Modo single agent
            try:
                agent_config = get_agent(agent_name, config.agents, cli_overrides)
            except AgentNotFoundError as e:
                click.echo(f"❌ Error: {e}", err=True)
                available = list_available_agents(config.agents)
                click.echo(f"\nAgentes disponibles: {', '.join(available)}", err=True)
                sys.exit(EXIT_FAILED)

            # Crear execution engine
            engine = ExecutionEngine(registry, config, confirm_mode=agent_config.confirm_mode)

            # Configurar dry-run si está habilitado
            if kwargs.get("dry_run"):
                engine.set_dry_run(True)
                if not kwargs.get("quiet"):
                    click.echo(
                        "🔍 Modo DRY-RUN activado (no se ejecutarán cambios reales)\n",
                        err=True,
                    )

            # Crear agent loop (con shutdown y timeout)
            loop = AgentLoop(
                llm, engine, agent_config, ctx,
                shutdown=shutdown,
                step_timeout=kwargs.get("timeout") or 0,
            )

            # Mostrar info inicial si no es quiet
            if not kwargs.get("quiet"):
                click.echo(f"🏗️  architect v0.8.0", err=True)
                click.echo(f"📝 Prompt: {prompt}", err=True)
                click.echo(f"🤖 Modelo: {config.llm.model}", err=True)
                click.echo(f"📁 Workspace: {config.workspace.root}", err=True)
                click.echo(f"🎭 Agente: {agent_name}", err=True)
                click.echo(f"⚙️  Modo: {agent_config.confirm_mode}", err=True)
                click.echo(f"📡 Streaming: {'sí' if use_stream else 'no'}", err=True)
                click.echo(err=True)

            # Ejecutar agent loop (con streaming si está activo)
            state = loop.run(prompt, stream=use_stream, on_stream_chunk=on_stream_chunk)

        # Mostrar resultado
        if kwargs.get("json_output"):
            output = state.to_output_dict()
            # JSON va a stdout (compatible con pipes)
            click.echo(json.dumps(output, indent=2))
        else:
            # Si hubo streaming, añadir newline final
            if use_stream and on_stream_chunk is not None:
                sys.stderr.write("\n")
                sys.stderr.flush()

            if not kwargs.get("quiet"):
                click.echo(err=True)
                click.echo("=" * 70, err=True)
                click.echo("RESULTADO", err=True)
                click.echo("=" * 70, err=True)
                click.echo(err=True)

            # El resultado final siempre va a stdout
            if state.final_output:
                click.echo(state.final_output)

            if not kwargs.get("quiet"):
                click.echo(err=True)
                click.echo(f"Estado: {state.status}", err=True)
                click.echo(f"Steps: {state.current_step}", err=True)
                click.echo(f"Tool calls: {state.total_tool_calls}", err=True)

        # Código de salida: si hubo shutdown → 130, si no → según status
        if shutdown.should_stop:
            sys.exit(EXIT_INTERRUPTED)

        exit_code = {
            "success": EXIT_SUCCESS,
            "partial": EXIT_PARTIAL,
            "failed": EXIT_FAILED,
        }.get(state.status, EXIT_FAILED)
        sys.exit(exit_code)

    except KeyboardInterrupt:
        # Fallback si GracefulShutdown no captura (ej: durante la carga de config)
        click.echo("\n⚠️  Interrumpido.", err=True)
        sys.exit(EXIT_INTERRUPTED)
    except FileNotFoundError as e:
        click.echo(f"❌ Error de configuración: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception as e:
        # Detectar errores de autenticación LLM
        error_str = str(e).lower()
        if any(kw in error_str for kw in ("authenticationerror", "auth", "api key", "unauthorized", "401")):
            click.echo(f"❌ Error de autenticación: {e}", err=True)
            sys.exit(EXIT_AUTH_ERROR)
        # Detectar timeouts
        elif any(kw in error_str for kw in ("timeout", "timed out", "readtimeout")):
            click.echo(f"❌ Timeout: {e}", err=True)
            sys.exit(EXIT_TIMEOUT)
        else:
            click.echo(f"❌ Error inesperado: {e}", err=True)
            if kwargs.get("verbose", 0) > 1:
                import traceback
                traceback.print_exc()
            sys.exit(EXIT_FAILED)


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
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception as e:
        click.echo(f"❌ Configuración inválida: {e}", err=True)
        sys.exit(EXIT_FAILED)


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
def agents(config: Path | None) -> None:
    """Lista los agentes disponibles y su configuración.

    Muestra los agentes por defecto y los definidos en el archivo de
    configuración. Útil para saber qué agentes se pueden usar con -a.
    """
    from .agents import DEFAULT_AGENTS, list_available_agents, resolve_agents_from_yaml

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    yaml_agents = app_config.agents if app_config else {}

    click.echo("Agentes disponibles:\n")

    # Agentes por defecto
    click.echo("  Agentes por defecto:")
    default_descriptions = {
        "plan":   "Analiza y planifica tareas (solo lectura, confirm-all)",
        "build":  "Crea y modifica archivos (confirm-sensitive)",
        "resume": "Lee y resume información (solo lectura, yolo)",
        "review": "Revisión de código (solo lectura, yolo)",
    }
    for name, desc in default_descriptions.items():
        marker = " *" if name in yaml_agents else ""
        click.echo(f"    {name:<12} {desc}{marker}")

    # Agentes custom desde YAML
    custom = {k: v for k, v in yaml_agents.items() if k not in DEFAULT_AGENTS}
    if custom:
        click.echo("\n  Agentes custom (desde config):")
        for name, agent_cfg in custom.items():
            tools = ", ".join(agent_cfg.allowed_tools) if agent_cfg.allowed_tools else "todas"
            click.echo(f"    {name:<12} tools=[{tools}], mode={agent_cfg.confirm_mode}")

    # Overrides en YAML de defaults
    overrides = {k: v for k, v in yaml_agents.items() if k in DEFAULT_AGENTS}
    if overrides:
        click.echo("\n  Defaults con override en config (marcados con *):")
        for name in overrides:
            click.echo(f"    {name}")

    click.echo(f"\n  Uso: architect run \"<tarea>\" -a <nombre-agente>")


if __name__ == "__main__":
    main()
