"""
CLI principal de architect usando Click.

v3: Sin agente explícito → usa 'build' directamente (no más MixedModeRunner por defecto).
    Añadido soporte para PostEditHooks, human logging, banner y separador de resultado.
"""

import json
import sys
from pathlib import Path
from typing import Callable

import click

from .agents import AgentNotFoundError, get_agent, list_available_agents
from .config.loader import load_config
from .core import AgentLoop, ContextBuilder, ContextManager, MixedModeRunner, SelfEvaluator
from .core.shutdown import GracefulShutdown
from .costs import CostTracker, PriceLoader
from .execution import ExecutionEngine
from .indexer import IndexCache, RepoIndex, RepoIndexer
from .llm import LLMAdapter, LocalLLMCache
from .logging import configure_logging
from .mcp import MCPDiscovery
from .tools import ToolRegistry, register_all_tools

# Importación opcional de hooks (v3-M4)
try:
    from .core.hooks import PostEditHooks
    _HOOKS_AVAILABLE = True
except ImportError:
    _HOOKS_AVAILABLE = False

# Códigos de salida
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_CONFIG_ERROR = 3
EXIT_AUTH_ERROR = 4
EXIT_TIMEOUT = 5
EXIT_INTERRUPTED = 130

# Versión actual
_VERSION = "0.15.0"


def _print_banner(agent_name: str, model: str, quiet: bool) -> None:
    """Imprime el banner de inicio (v3-M5)."""
    if not quiet:
        width = 50
        label = f" architect · {agent_name} · {model} "
        dashes = "─" * max(0, width - len(label))
        click.echo(f"\n─── {label}{dashes}\n", err=True)


def _print_result_separator(quiet: bool) -> None:
    """Imprime el separador antes del resultado (v3-M5)."""
    if not quiet:
        click.echo(f"\n─── Resultado {'─' * 40}\n", err=True)


@click.group()
@click.version_option(version=_VERSION, prog_name="architect")
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
    help="Agente a utilizar (build, plan, resume, review, o custom). Default: build",
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
    help="Modelo LLM a usar (ej: gpt-4o, claude-sonnet-4-6)",
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
    type=click.Choice(["debug", "info", "human", "warn", "error"]),
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
    help="Número máximo de pasos del agente (watchdog)",
)
@click.option(
    "--timeout",
    type=int,
    default=None,
    help="Timeout total en segundos (watchdog de tiempo total)",
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
@click.option(
    "--self-eval",
    "self_eval",
    type=click.Choice(["off", "basic", "full"]),
    default=None,
    help="Modo de auto-evaluación: off|basic|full (default: config YAML)",
)
@click.option(
    "--allow-commands",
    "allow_commands",
    is_flag=True,
    default=False,
    help="Habilitar run_command tool (override de commands.enabled en config)",
)
@click.option(
    "--no-commands",
    "no_commands",
    is_flag=True,
    default=False,
    help="Deshabilitar run_command tool completamente",
)
@click.option(
    "--budget",
    type=float,
    default=None,
    help="Límite de gasto en USD por ejecución",
)
@click.option(
    "--show-costs",
    "show_costs",
    is_flag=True,
    default=False,
    help="Mostrar resumen de costes al terminar",
)
@click.option(
    "--cache",
    "use_local_cache",
    is_flag=True,
    default=False,
    help="Activar cache local de LLM para desarrollo",
)
@click.option(
    "--no-cache",
    "disable_cache",
    is_flag=True,
    default=False,
    help="Desactivar cache local de LLM aunque esté habilitado en config",
)
@click.option(
    "--cache-clear",
    "cache_clear",
    is_flag=True,
    default=False,
    help="Limpiar cache local de LLM antes de ejecutar",
)
def run(prompt: str, **kwargs) -> None:  # type: ignore
    """Ejecuta una tarea usando un agente de IA.

    PROMPT: Descripción de la tarea a realizar

    Por defecto usa el agente 'build' (planifica + ejecuta en un solo loop).
    Usa -a para seleccionar un agente diferente.

    Ejemplos:

        \b
        # Tarea general (agente build por defecto)
        $ architect run "añade validación de email a user.py"

        \b
        # Análisis sin modificaciones
        $ architect run "analiza este proyecto" -a review

        \b
        # Planificación solo (sin ejecutar)
        $ architect run "¿cómo refactorizaría main.py?" -a plan

        \b
        # Ejecución automática total sin confirmaciones
        $ architect run "genera scaffolding" --mode yolo

        \b
        # Dry-run para ver qué haría sin ejecutar
        $ architect run "modifica config.yaml" --dry-run

        \b
        # Salida JSON estructurada (para pipes)
        $ architect run "resume el proyecto" --quiet --json | jq .

        \b
        # Con límite de coste y resumen de costes
        $ architect run "refactoriza todo" --budget 0.50 --show-costs
    """
    try:
        # Instalar GracefulShutdown para SIGINT + SIGTERM
        shutdown = GracefulShutdown()

        # Cargar configuración
        config = load_config(
            config_path=kwargs.get("config"),
            cli_args=kwargs,
        )

        # Configurar logging
        configure_logging(
            config.logging,
            json_output=kwargs.get("json_output", False),
            quiet=kwargs.get("quiet", False),
        )

        # v3-M3: Sin agente → usar 'build' directamente (no MixedModeRunner)
        agent_name = kwargs.get("agent") or "build"

        # Modo streaming
        use_stream = (
            not kwargs.get("no_stream", False)
            and not kwargs.get("json_output", False)
            and config.llm.stream
        )

        on_stream_chunk: Callable[[str], None] | None = None
        if use_stream and not kwargs.get("quiet", False):
            def on_stream_chunk(chunk: str) -> None:  # type: ignore[misc]
                sys.stderr.write(chunk)
                sys.stderr.flush()

        # Aplicar CLI overrides para commands
        if kwargs.get("allow_commands"):
            config.commands.enabled = True
        if kwargs.get("no_commands"):
            config.commands.enabled = False

        # Crear tool registry
        registry = ToolRegistry()
        register_all_tools(registry, config.workspace, config.commands)

        # Descubrir tools MCP
        if not kwargs.get("disable_mcp") and config.mcp.servers:
            if not kwargs.get("quiet"):
                click.echo(
                    f"Descubriendo tools MCP de {len(config.mcp.servers)} servidor(es)...",
                    err=True,
                )
            discovery = MCPDiscovery()
            mcp_stats = discovery.discover_and_register(config.mcp.servers, registry)

            if not kwargs.get("quiet") and kwargs.get("verbose", 0) >= 1:
                if mcp_stats["servers_success"] > 0:
                    click.echo(
                        f"  {mcp_stats['tools_registered']} tools MCP registradas",
                        err=True,
                    )
                if mcp_stats["servers_failed"] > 0:
                    click.echo(
                        f"  {mcp_stats['servers_failed']} servidor(es) no disponible(s)",
                        err=True,
                    )

        # Construir índice del repositorio
        repo_index: RepoIndex | None = None
        if config.indexer.enabled:
            workspace_root = Path(config.workspace.root).resolve()
            indexer = RepoIndexer(
                workspace_root=workspace_root,
                max_file_size=config.indexer.max_file_size,
                exclude_dirs=config.indexer.exclude_dirs,
                exclude_patterns=config.indexer.exclude_patterns,
            )
            cache = IndexCache() if config.indexer.use_cache else None
            if cache:
                repo_index = cache.get(workspace_root)
            if repo_index is None:
                repo_index = indexer.build_index()
                if cache:
                    cache.set(workspace_root, repo_index)

        # Crear PostEditHooks (v3-M4)
        post_edit_hooks: "PostEditHooks | None" = None
        if _HOOKS_AVAILABLE and hasattr(config, "hooks") and config.hooks.post_edit:
            post_edit_hooks = PostEditHooks(
                hooks=config.hooks.post_edit,
                workspace_root=Path(config.workspace.root).resolve(),
            )

        # Determinar si usar cache local de LLM
        llm_cache_enabled = config.llm_cache.enabled
        if kwargs.get("use_local_cache"):
            llm_cache_enabled = True
        if kwargs.get("disable_cache"):
            llm_cache_enabled = False

        local_cache: LocalLLMCache | None = None
        if llm_cache_enabled:
            local_cache = LocalLLMCache(
                cache_dir=config.llm_cache.dir,
                ttl_hours=config.llm_cache.ttl_hours,
            )
            if kwargs.get("cache_clear"):
                cleared = local_cache.clear()
                if not kwargs.get("quiet"):
                    click.echo(f"Cache limpiado: {cleared} entradas eliminadas", err=True)

        # Crear cost tracker
        cost_tracker: CostTracker | None = None
        if config.costs.enabled:
            price_loader = PriceLoader(custom_prices_file=config.costs.prices_file)
            budget_usd = kwargs.get("budget") or config.costs.budget_usd
            cost_tracker = CostTracker(
                price_loader=price_loader,
                budget_usd=budget_usd,
                warn_at_usd=config.costs.warn_at_usd,
            )

        # Crear LLM adapter
        llm = LLMAdapter(config.llm, local_cache=local_cache)

        # Crear context manager y context builder
        context_mgr = ContextManager(config.context)
        ctx = ContextBuilder(repo_index=repo_index, context_manager=context_mgr)

        # Resolver agente con overrides CLI
        cli_overrides = {
            "mode": kwargs.get("mode"),
            "max_steps": kwargs.get("max_steps"),
        }

        try:
            agent_config = get_agent(agent_name, config.agents, cli_overrides)
        except AgentNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            available = list_available_agents(config.agents)
            click.echo(f"Agentes disponibles: {', '.join(available)}", err=True)
            sys.exit(EXIT_FAILED)

        # Crear execution engine con hooks (v3-M4)
        engine = ExecutionEngine(
            registry,
            config,
            confirm_mode=agent_config.confirm_mode,
            hooks=post_edit_hooks,
        )

        # Configurar dry-run
        if kwargs.get("dry_run"):
            engine.set_dry_run(True)

        # v3-M5: Banner de inicio
        _print_banner(agent_name, config.llm.model, kwargs.get("quiet", False))

        if not kwargs.get("quiet") and kwargs.get("verbose", 0) >= 1:
            click.echo(f"Workspace: {config.workspace.root}", err=True)
            click.echo(f"Modo: {agent_config.confirm_mode}", err=True)
            click.echo(f"Streaming: {'sí' if use_stream else 'no'}", err=True)
            if kwargs.get("dry_run"):
                click.echo("DRY-RUN activado (no se ejecutarán cambios reales)", err=True)
            click.echo(err=True)

        # Crear agent loop (v3-M1: while True + timeout total)
        loop = AgentLoop(
            llm,
            engine,
            agent_config,
            ctx,
            shutdown=shutdown,
            step_timeout=0,  # Sin SIGALRM por step (el timeout total lo controla `timeout`)
            context_manager=context_mgr,
            cost_tracker=cost_tracker,
            timeout=kwargs.get("timeout"),  # v3: total elapsed time watchdog
        )

        # Ejecutar
        state = loop.run(prompt, stream=use_stream, on_stream_chunk=on_stream_chunk)

        # run_fn para evaluate_full
        def run_fn(correction_prompt: str):  # type: ignore[misc]
            return loop.run(correction_prompt, stream=False)

        # Self-evaluation
        self_eval_mode = kwargs.get("self_eval") or config.evaluation.mode
        if self_eval_mode != "off" and state.status == "success":
            if not kwargs.get("quiet"):
                click.echo("Evaluando resultado...", err=True)

            evaluator = SelfEvaluator(
                llm,
                max_retries=config.evaluation.max_retries,
                confidence_threshold=config.evaluation.confidence_threshold,
            )

            if self_eval_mode == "basic":
                eval_result = evaluator.evaluate_basic(prompt, state)
                passed = (
                    eval_result.completed
                    and eval_result.confidence >= config.evaluation.confidence_threshold
                )
                if not passed:
                    state.status = "partial"
                if not kwargs.get("quiet"):
                    icon = "✓" if passed else "⚠"
                    click.echo(
                        f"{icon} Evaluación: {'completado' if passed else 'incompleto'} "
                        f"({eval_result.confidence:.0%} confianza)",
                        err=True,
                    )
                    for issue in eval_result.issues:
                        click.echo(f"   - {issue}", err=True)
                    if not passed and eval_result.suggestion:
                        click.echo(f"   Sugerencia: {eval_result.suggestion}", err=True)

            elif self_eval_mode == "full":
                state = evaluator.evaluate_full(prompt, state, run_fn)
                if not kwargs.get("quiet"):
                    click.echo(
                        f"Evaluación full completada (estado: {state.status})",
                        err=True,
                    )

        # Mostrar resumen de costes
        show_costs = kwargs.get("show_costs") or kwargs.get("verbose", 0) >= 1
        if show_costs and not kwargs.get("quiet") and cost_tracker and cost_tracker.has_data():
            click.echo(f"\nCoste: {cost_tracker.format_summary_line()}", err=True)

        # v3-M5: Separador de resultado
        _print_result_separator(kwargs.get("quiet", False))

        # Output
        if kwargs.get("json_output"):
            output = state.to_output_dict()
            click.echo(json.dumps(output, indent=2))
        else:
            if use_stream and on_stream_chunk is not None:
                sys.stderr.write("\n")
                sys.stderr.flush()

            if state.final_output:
                click.echo(state.final_output)

            if not kwargs.get("quiet"):
                stop_info = (
                    f" ({state.stop_reason.value})"
                    if state.stop_reason
                    else ""
                )
                click.echo(
                    f"\nEstado: {state.status}{stop_info} | "
                    f"Steps: {state.current_step} | "
                    f"Tool calls: {state.total_tool_calls}",
                    err=True,
                )

        # Código de salida
        if shutdown.should_stop:
            sys.exit(EXIT_INTERRUPTED)

        exit_code = {
            "success": EXIT_SUCCESS,
            "partial": EXIT_PARTIAL,
            "failed": EXIT_FAILED,
        }.get(state.status, EXIT_FAILED)
        sys.exit(exit_code)

    except KeyboardInterrupt:
        click.echo("\nInterrumpido.", err=True)
        sys.exit(EXIT_INTERRUPTED)
    except FileNotFoundError as e:
        click.echo(f"Error de configuración: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception as e:
        error_str = str(e).lower()
        if any(kw in error_str for kw in ("authenticationerror", "auth", "api key", "unauthorized", "401")):
            click.echo(f"Error de autenticación: {e}", err=True)
            sys.exit(EXIT_AUTH_ERROR)
        elif any(kw in error_str for kw in ("timeout", "timed out", "readtimeout")):
            click.echo(f"Timeout: {e}", err=True)
            sys.exit(EXIT_TIMEOUT)
        else:
            click.echo(f"Error inesperado: {e}", err=True)
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
    """Valida un archivo de configuración YAML."""
    try:
        app_config = load_config(config_path=config)
        click.echo("Configuración válida")
        click.echo(f"  Modelo: {app_config.llm.model}")
        click.echo(f"  Agentes definidos: {len(app_config.agents)}")
        click.echo(f"  Servidores MCP: {len(app_config.mcp.servers)}")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception as e:
        click.echo(f"Configuración inválida: {e}", err=True)
        sys.exit(EXIT_FAILED)


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
def agents(config: Path | None) -> None:
    """Lista los agentes disponibles y su configuración."""
    from .agents import DEFAULT_AGENTS, list_available_agents

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    yaml_agents = app_config.agents if app_config else {}

    click.echo("Agentes disponibles:\n")

    click.echo("  Agentes por defecto:")
    default_descriptions = {
        "build":  "Crea y modifica archivos — planifica + ejecuta en un solo loop (confirm-sensitive)",
        "plan":   "Analiza y planifica tareas sin ejecutar (yolo, solo lectura)",
        "resume": "Lee y resume información (yolo, solo lectura)",
        "review": "Revisión de código (yolo, solo lectura)",
    }
    for name, desc in default_descriptions.items():
        marker = " *" if name in yaml_agents else ""
        click.echo(f"    {name:<12} {desc}{marker}")

    custom = {k: v for k, v in yaml_agents.items() if k not in DEFAULT_AGENTS}
    if custom:
        click.echo("\n  Agentes custom (desde config):")
        for name, agent_cfg in custom.items():
            tools = ", ".join(agent_cfg.allowed_tools) if agent_cfg.allowed_tools else "todas"
            click.echo(f"    {name:<12} tools=[{tools}], mode={agent_cfg.confirm_mode}")

    overrides = {k: v for k, v in yaml_agents.items() if k in DEFAULT_AGENTS}
    if overrides:
        click.echo("\n  Defaults con override en config (marcados con *):")
        for name in overrides:
            click.echo(f"    {name}")

    click.echo(f"\n  Uso: architect run \"<tarea>\" -a <nombre-agente>")
    click.echo(f"  Sin -a → usa 'build' por defecto")


if __name__ == "__main__":
    main()
