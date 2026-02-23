"""
CLI principal de architect usando Click.

v3: Sin agente explícito → usa 'build' directamente (no más MixedModeRunner por defecto).
    Añadido soporte para PostEditHooks, human logging, banner y separador de resultado.
"""

import json
import subprocess
import sys
import time
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

# v4-A1: Sistema de hooks completo
from .core.hooks import HookConfig, HookEvent, HookExecutor, HooksRegistry
# v4-A2: Guardrails
from .core.guardrails import GuardrailsEngine
# v4-A3: Skills ecosystem
from .skills import ProceduralMemory, SkillInstaller, SkillsLoader
# v4-B1: Sessions
from .features.sessions import SessionManager, generate_session_id
# v4-B2: Reports
from .features.report import ExecutionReport, ReportGenerator, collect_git_diff
# v4-B4: Dry Run Tracker
from .features.dryrun import DryRunTracker

# Códigos de salida
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_CONFIG_ERROR = 3
EXIT_AUTH_ERROR = 4
EXIT_TIMEOUT = 5
EXIT_INTERRUPTED = 130

# Versión actual
_VERSION = "0.17.0"


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
@click.option(
    "--report",
    "report_format",
    type=click.Choice(["json", "markdown", "github"]),
    default=None,
    help="Formato del reporte de ejecución",
)
@click.option(
    "--report-file",
    "report_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Archivo de salida para el reporte",
)
@click.option(
    "--context-git-diff",
    "git_diff_ref",
    default=None,
    help="Inyectar diff de git como contexto (ej: origin/main)",
)
@click.option(
    "--session",
    "session_id",
    default=None,
    help="ID de sesión para resume (reanuda sesión previa)",
)
@click.option(
    "--confirm-mode",
    "confirm_mode",
    type=click.Choice(["yolo", "confirm-sensitive", "confirm-all"]),
    default=None,
    help="Modo de confirmación (alias CI-friendly de --mode)",
)
@click.option(
    "--exit-code-on-partial",
    "exit_code_on_partial",
    type=int,
    default=None,
    help="Exit code si el resultado es parcial (default: 2)",
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
        # Cargar configuración
        config = load_config(
            config_path=kwargs.get("config"),
            cli_args=kwargs,
        )

        # Configurar logging antes de cualquier otra cosa (evita debug spurious)
        configure_logging(
            config.logging,
            json_output=kwargs.get("json_output", False),
            quiet=kwargs.get("quiet", False),
        )

        # Instalar GracefulShutdown para SIGINT + SIGTERM (después del logging)
        shutdown = GracefulShutdown()

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

        # v4-A3: Crear SkillsLoader y cargar contexto del proyecto
        skills_loader: SkillsLoader | None = None
        if config.skills.auto_discover:
            skills_loader = SkillsLoader(str(Path(config.workspace.root).resolve()))
            skills_loader.load_project_context()
            skills_loader.discover_skills()

        # v4-A4: Crear ProceduralMemory si configurado
        memory: ProceduralMemory | None = None
        if config.memory.enabled:
            memory = ProceduralMemory(str(Path(config.workspace.root).resolve()))

        # v4-B1: Crear SessionManager si auto_save está habilitado
        session_manager: SessionManager | None = None
        if config.sessions.auto_save:
            session_manager = SessionManager(str(Path(config.workspace.root).resolve()))

        # v4-B1: Si se proporcionó un session_id, cargar la sesión previa
        resume_session = None
        session_id = kwargs.get("session_id")
        if session_id and session_manager:
            resume_session = session_manager.load(session_id)
            if resume_session is None:
                click.echo(f"Error: Sesión '{session_id}' no encontrada", err=True)
                sys.exit(EXIT_CONFIG_ERROR)
            if not kwargs.get("quiet"):
                click.echo(
                    f"Reanudando sesión {session_id} "
                    f"(step {resume_session.steps_completed}, "
                    f"status={resume_session.status})",
                    err=True,
                )

        # v4-B3: Inyectar git diff como contexto si se pidió
        git_diff_context: str | None = None
        if kwargs.get("git_diff_ref"):
            git_diff_context = _get_git_diff_context(kwargs["git_diff_ref"])
            if git_diff_context and not kwargs.get("quiet"):
                click.echo(
                    f"Contexto de git diff inyectado (vs {kwargs['git_diff_ref']})",
                    err=True,
                )

        # v4-A1: Crear HookExecutor con el sistema de hooks completo
        hook_executor: HookExecutor | None = None
        hooks_registry = _build_hooks_registry(config)
        if hooks_registry.has_hooks():
            hook_executor = HookExecutor(
                registry=hooks_registry,
                workspace_root=str(Path(config.workspace.root).resolve()),
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
            price_loader = PriceLoader(custom_path=config.costs.prices_file)
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
        # --confirm-mode es alias CI-friendly de --mode; --confirm-mode tiene prioridad
        effective_mode = kwargs.get("confirm_mode") or kwargs.get("mode")
        cli_overrides = {
            "mode": effective_mode,
            "max_steps": kwargs.get("max_steps"),
        }

        try:
            agent_config = get_agent(agent_name, config.agents, cli_overrides)
        except AgentNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            available = list_available_agents(config.agents)
            click.echo(f"Agentes disponibles: {', '.join(available)}", err=True)
            sys.exit(EXIT_FAILED)

        # Inyectar MCP tools en allowed_tools del agente para que el LLM las vea.
        # Sin esto, los agentes con allowed_tools explícito (como build) no expondrían
        # las MCP tools al LLM aunque estén registradas en el ToolRegistry.
        if agent_config.allowed_tools:
            mcp_tool_names = [
                t.name for t in registry.list_all()
                if t.name.startswith("mcp_")
            ]
            if mcp_tool_names:
                agent_config.allowed_tools.extend(mcp_tool_names)

        # v4-A2: Crear guardrails engine si configurado
        guardrails_engine: GuardrailsEngine | None = None
        if config.guardrails.enabled:
            guardrails_engine = GuardrailsEngine(
                config=config.guardrails,
                workspace_root=str(Path(config.workspace.root).resolve()),
            )

        # Crear execution engine con hooks (v4-A1) y guardrails (v4-A2)
        engine = ExecutionEngine(
            registry,
            config,
            confirm_mode=agent_config.confirm_mode,
            hook_executor=hook_executor,
            guardrails=guardrails_engine,
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

        # v4-B4: Crear DryRunTracker si --dry-run
        dry_run_tracker: DryRunTracker | None = None
        if kwargs.get("dry_run"):
            dry_run_tracker = DryRunTracker()

        # Crear agent loop (v3-M1: while True + timeout, v4-A1: hooks, v4-A2: guardrails, v4-A3: skills, v4-B1: sessions)
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
            hook_executor=hook_executor,
            guardrails=guardrails_engine,
            skills_loader=skills_loader,
            memory=memory,
            session_manager=session_manager,
            session_id=session_id,
            dry_run_tracker=dry_run_tracker,
        )

        # v4-B1/B3: Enriquecer prompt con contexto adicional
        effective_prompt = prompt
        if resume_session:
            effective_prompt = (
                f"Estás reanudando una sesión interrumpida.\n"
                f"Tarea original: {resume_session.task}\n"
                f"Steps completados: {resume_session.steps_completed}\n"
                f"Archivos modificados: {', '.join(resume_session.files_modified) or 'ninguno'}\n\n"
                f"Continúa la tarea desde donde se quedó."
            )
        if git_diff_context:
            effective_prompt = effective_prompt + "\n\n" + git_diff_context

        # Ejecutar
        state = loop.run(effective_prompt, stream=use_stream, on_stream_chunk=on_stream_chunk)

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

        # v4-B4: Mostrar resumen de dry-run si aplica
        if dry_run_tracker:
            if not kwargs.get("quiet"):
                click.echo("\n" + dry_run_tracker.get_plan_summary(), err=True)

        # v4-B2: Generar reporte si se pidió
        report_format = kwargs.get("report_format")
        if report_format:
            duration = time.time() - state.start_time

            # Recopilar archivos modificados y timeline de los StepResults
            report_files: list[dict] = []
            report_timeline: list[dict] = []
            report_errors: list[str] = []
            seen_paths: set[str] = set()
            for sr in state.steps:
                for tc in sr.tool_calls_made:
                    # Timeline entry (duration = time from tool execution to step completion)
                    tool_duration = round(abs(sr.timestamp - tc.timestamp), 2)
                    report_timeline.append({
                        "step": sr.step_number,
                        "tool": tc.tool_name,
                        "duration": tool_duration,
                    })
                    # Files modified
                    if tc.tool_name in ("write_file", "edit_file", "apply_patch", "delete_file"):
                        path = tc.args.get("path", "")
                        if path and path not in seen_paths:
                            action = "deleted" if tc.tool_name == "delete_file" else "modified"
                            if tc.tool_name == "write_file":
                                action = "created"
                            report_files.append({"path": path, "action": action})
                            seen_paths.add(path)
                    # Errors
                    if not tc.result.success and tc.result.error:
                        report_errors.append(
                            f"Step {sr.step_number}, {tc.tool_name}: {tc.result.error}"
                        )

            exec_report = ExecutionReport(
                task=prompt,
                agent=agent_name,
                model=config.llm.model,
                status=state.status,
                duration_seconds=round(duration, 2),
                steps=state.current_step,
                total_cost=(
                    cost_tracker.total_cost_usd if cost_tracker and cost_tracker.has_data() else 0.0
                ),
                files_modified=report_files,
                errors=report_errors,
                timeline=report_timeline,
                stop_reason=state.stop_reason.value if state.stop_reason else None,
                git_diff=collect_git_diff(str(Path(config.workspace.root).resolve())),
            )

            gen = ReportGenerator(exec_report)
            report_content = {
                "json": gen.to_json,
                "markdown": gen.to_markdown,
                "github": gen.to_github_pr_comment,
            }[report_format]()

            report_file = kwargs.get("report_file")
            if report_file:
                Path(report_file).write_text(report_content, encoding="utf-8")
                if not kwargs.get("quiet"):
                    click.echo(f"Reporte guardado en {report_file}", err=True)
            else:
                click.echo(report_content, err=True)

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

        # v4-B3: --exit-code-on-partial permite personalizar el código de salida
        partial_code = kwargs.get("exit_code_on_partial")
        if partial_code is None:
            partial_code = EXIT_PARTIAL
        exit_code = {
            "success": EXIT_SUCCESS,
            "partial": partial_code,
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


@main.group()
def skill() -> None:
    """Gestionar skills del proyecto."""
    pass


@skill.command("install")
@click.argument("source")
def skill_install(source: str) -> None:
    """Instala una skill desde GitHub. Formato: user/repo/path/to/skill."""
    import os

    installer = SkillInstaller(os.getcwd())
    if installer.install_from_github(source):
        click.echo(f"Skill instalada desde {source}")
    else:
        click.echo("Error instalando skill", err=True)
        raise SystemExit(1)


@skill.command("create")
@click.argument("name")
def skill_create(name: str) -> None:
    """Crea una skill local con template."""
    import os

    installer = SkillInstaller(os.getcwd())
    path = installer.create_local(name)
    click.echo(f"Skill creada en {path}")


@skill.command("list")
def skill_list() -> None:
    """Lista skills disponibles."""
    import os

    installer = SkillInstaller(os.getcwd())
    skills = installer.list_installed()
    if not skills:
        click.echo("  No hay skills instaladas.")
        return
    for s in skills:
        source_label = "local" if s["source"] == "local" else "installed"
        click.echo(f"  {s['name']:20s} ({source_label})")


@skill.command("remove")
@click.argument("name")
def skill_remove(name: str) -> None:
    """Elimina una skill instalada."""
    import os

    installer = SkillInstaller(os.getcwd())
    if installer.uninstall(name):
        click.echo(f"Skill '{name}' eliminada")
    else:
        click.echo(f"Skill '{name}' no encontrada", err=True)


# ── SESSION COMMANDS (v4-B1) ─────────────────────────────────────────────


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
def sessions(config: Path | None) -> None:
    """Lista sesiones guardadas."""
    import os

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()
    mgr = SessionManager(workspace)
    session_list = mgr.list_sessions()

    if not session_list:
        click.echo("No hay sesiones guardadas.")
        return

    click.echo(f"Sesiones guardadas ({len(session_list)}):\n")
    click.echo(f"  {'ID':<24s} {'Estado':<10s} {'Steps':<7s} {'Coste':<10s} Tarea")
    click.echo(f"  {'─'*24} {'─'*10} {'─'*7} {'─'*10} {'─'*30}")
    for s in session_list:
        cost_str = f"${s['cost']:.4f}" if s["cost"] else "-"
        click.echo(
            f"  {s['id']:<24s} {s['status']:<10s} {s['steps']:<7d} {cost_str:<10s} {s['task']}"
        )

    click.echo(f"\nUsa 'architect run \"<tarea>\" --session <ID>' para reanudar.")


@main.command()
@click.argument("session_id")
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
def resume(session_id: str, config: Path | None) -> None:
    """Reanuda una sesión interrumpida.

    SESSION_ID: Identificador de la sesión a reanudar.
    Se puede obtener con 'architect sessions'.
    """
    import os

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()
    mgr = SessionManager(workspace)
    session = mgr.load(session_id)

    if session is None:
        click.echo(f"Error: Sesión '{session_id}' no encontrada.", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    click.echo(f"Reanudando sesión: {session_id}")
    click.echo(f"  Tarea: {session.task}")
    click.echo(f"  Estado: {session.status}")
    click.echo(f"  Steps: {session.steps_completed}")
    click.echo(f"  Coste: ${session.total_cost:.4f}")
    click.echo()

    # Delegar al comando run con el session_id
    # Esto es un shortcut — el usuario puede hacer lo mismo con:
    #   architect run "<tarea>" --session <id>
    from click.testing import CliRunner

    runner = CliRunner()
    args = ["run", session.task, "--session", session_id]
    if config:
        args.extend(["--config", str(config)])
    result = runner.invoke(main, args, standalone_mode=False)
    if isinstance(result, int):
        sys.exit(result)
    if result and hasattr(result, "exit_code"):
        sys.exit(result.exit_code)


@main.command()
@click.option(
    "--older-than",
    "older_than_days",
    default=7,
    type=int,
    help="Eliminar sesiones más antiguas que N días",
)
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
def cleanup(older_than_days: int, config: Path | None) -> None:
    """Limpia sesiones antiguas."""
    import os

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()
    mgr = SessionManager(workspace)
    removed = mgr.cleanup(older_than_days=older_than_days)
    click.echo(f"Sesiones eliminadas: {removed}")


# ── HELPER FUNCTIONS (v4-B3) ────────────────────────────────────────────


def _get_git_diff_context(ref: str) -> str | None:
    """Obtiene el diff de git y lo formatea como contexto para el agente.

    Args:
        ref: Referencia git contra la que comparar (ej: origin/main).

    Returns:
        String con el diff formateado, o None si falla.
    """
    try:
        stat_result = subprocess.run(
            ["git", "diff", ref, "--stat"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        stat = stat_result.stdout

        diff_result = subprocess.run(
            ["git", "diff", ref],
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff = diff_result.stdout

        if not diff.strip():
            return None

        # Truncar si es muy largo
        if len(diff) > 50000:
            diff = diff[:50000] + "\n... (diff truncado)"

        return (
            f"## Cambios en este branch (vs {ref})\n\n"
            f"### Resumen\n```\n{stat}\n```\n\n"
            f"### Diff completo\n```diff\n{diff}\n```"
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _build_hooks_registry(config) -> HooksRegistry:
    """Construye un HooksRegistry a partir de la configuración (v4-A1).

    Mapea las listas de HookItemConfig de la sección hooks del config YAML
    a un HooksRegistry con HookConfig por cada HookEvent.
    También migra post_edit (v3-M4 compat) a post_tool_use con matcher de edit tools.

    Args:
        config: AppConfig con la sección hooks.

    Returns:
        HooksRegistry listo para usar con HookExecutor.
    """
    hooks_dict: dict[HookEvent, list[HookConfig]] = {}

    event_mapping = {
        "pre_tool_use": HookEvent.PRE_TOOL_USE,
        "post_tool_use": HookEvent.POST_TOOL_USE,
        "pre_llm_call": HookEvent.PRE_LLM_CALL,
        "post_llm_call": HookEvent.POST_LLM_CALL,
        "session_start": HookEvent.SESSION_START,
        "session_end": HookEvent.SESSION_END,
        "on_error": HookEvent.ON_ERROR,
        "agent_complete": HookEvent.AGENT_COMPLETE,
        "budget_warning": HookEvent.BUDGET_WARNING,
        "context_compress": HookEvent.CONTEXT_COMPRESS,
    }

    for config_attr, event in event_mapping.items():
        items = getattr(config.hooks, config_attr, [])
        if items:
            hooks_dict[event] = [
                HookConfig(
                    command=h.command,
                    matcher=h.matcher,
                    file_patterns=h.file_patterns,
                    timeout=h.timeout,
                    is_async=h.async_,
                    enabled=h.enabled,
                    name=h.name,
                )
                for h in items
            ]

    # Backward compat: post_edit → post_tool_use con matcher de edit tools
    if config.hooks.post_edit:
        edit_hooks = [
            HookConfig(
                command=h.command,
                matcher="write_file|edit_file|apply_patch",
                file_patterns=h.file_patterns,
                timeout=h.timeout,
                is_async=h.async_,
                enabled=h.enabled,
                name=h.name or "post-edit-compat",
            )
            for h in config.hooks.post_edit
        ]
        existing = hooks_dict.get(HookEvent.POST_TOOL_USE, [])
        hooks_dict[HookEvent.POST_TOOL_USE] = existing + edit_hooks

    return HooksRegistry(hooks=hooks_dict)


if __name__ == "__main__":
    main()
