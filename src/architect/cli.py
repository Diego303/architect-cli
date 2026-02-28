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
from typing import Any, Callable

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
from .tools.setup import register_dispatch_tool

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
# v4-C1: Ralph Loop
from .features.ralph import RalphConfig, RalphLoop
# v4-C2: Parallel Runs
from .features.parallel import ParallelConfig, ParallelRunner
# v4-C3: Pipelines
from .features.pipelines import PipelineRunner
# v4-C4: Checkpoints
from .features.checkpoints import CheckpointManager
# v4-C5: Auto-Review
from .agents.reviewer import AutoReviewer
# v4-D3: Competitive Eval
from .features.competitive import CompetitiveConfig, CompetitiveEval
# v4-D2: Code Health Delta
from .core.health import CodeHealthAnalyzer
# v4-D4: Telemetry
from .telemetry.otel import create_tracer
# v4-D5: Preset Configs
from .config.presets import AVAILABLE_PRESETS, PresetManager

# Códigos de salida
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_CONFIG_ERROR = 3
EXIT_AUTH_ERROR = 4
EXIT_TIMEOUT = 5
EXIT_INTERRUPTED = 130

# Versión actual
_VERSION = "1.1.0"


_REPORT_EXT_MAP: dict[str, str] = {
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "github",
}


def _infer_report_format(report_file: str) -> str:
    """Infiere el formato de reporte a partir de la extensión del archivo.

    Returns:
        'json', 'markdown' o 'github'. Default: 'markdown'.
    """
    ext = Path(report_file).suffix.lower()
    return _REPORT_EXT_MAP.get(ext, "markdown")


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
@click.option(
    "--health",
    "health_check",
    is_flag=True,
    default=False,
    help="Ejecutar análisis de salud del código antes/después (v4-D2)",
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

        # v4-D4: Crear tracer de telemetría
        tracer = create_tracer(
            enabled=config.telemetry.enabled,
            exporter=config.telemetry.exporter,
            endpoint=config.telemetry.endpoint,
            trace_file=config.telemetry.trace_file,
        )

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

        # v4-D1: Registrar dispatch_subagent tool con agent_factory
        def _subagent_factory(agent: str = "build", max_steps: int = 15, allowed_tools: list[str] | None = None, **kw: Any) -> AgentLoop:
            """Crea un AgentLoop fresco para sub-agentes."""
            from .agents import get_agent as _get_agent
            sub_agent_config = _get_agent(agent, config.agents, {"max_steps": max_steps})
            if allowed_tools:
                sub_agent_config.allowed_tools = list(allowed_tools)
            sub_engine = ExecutionEngine(
                registry, config,
                confirm_mode="yolo",
                guardrails=guardrails_engine,
            )
            sub_ctx = ContextBuilder(repo_index=repo_index, context_manager=ContextManager(config.context))
            return AgentLoop(
                llm, sub_engine, sub_agent_config, sub_ctx,
                shutdown=shutdown, step_timeout=0,
                context_manager=ContextManager(config.context),
                cost_tracker=cost_tracker,
            )

        register_dispatch_tool(registry, config.workspace, _subagent_factory)

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

        # v4-D2: Health analysis — before snapshot
        health_analyzer: CodeHealthAnalyzer | None = None
        if kwargs.get("health_check") or config.health.enabled:
            health_analyzer = CodeHealthAnalyzer(
                workspace_root=str(Path(config.workspace.root).resolve()),
                include_patterns=config.health.include_patterns,
                exclude_dirs=config.health.exclude_dirs or None,
            )
            health_analyzer.take_before_snapshot()
            if not kwargs.get("quiet"):
                click.echo("Health: snapshot 'antes' capturado", err=True)

        # Ejecutar (con tracing de telemetría v4-D4)
        with tracer.start_session(
            task=effective_prompt[:200],
            agent=agent_name,
            model=config.llm.model,
            session_id=session_id or "",
        ):
            state = loop.run(effective_prompt, stream=use_stream, on_stream_chunk=on_stream_chunk)

        # v4-D2: Health analysis — after snapshot + delta
        if health_analyzer:
            health_analyzer.take_after_snapshot()
            delta = health_analyzer.compute_delta()
            if delta and not kwargs.get("quiet"):
                click.echo("\n" + delta.to_report(), err=True)

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
        if not report_format and kwargs.get("report_file"):
            report_format = _infer_report_format(kwargs["report_file"])
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

        # v4-D4: Shutdown tracer (flush pending spans)
        tracer.shutdown()

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


# ── PHASE C COMMANDS (v4-C1..C5) ───────────────────────────────────────


@main.command("loop")
@click.argument("task")
@click.option(
    "--check",
    "checks",
    multiple=True,
    required=True,
    help="Comando de verificación (repetible con múltiples --check)",
)
@click.option(
    "--spec",
    "spec_file",
    type=click.Path(exists=True),
    help="Archivo de especificación detallada",
)
@click.option(
    "--max-iterations",
    default=25,
    type=int,
    help="Número máximo de iteraciones (default: 25)",
)
@click.option("--max-cost", type=float, help="Coste máximo total en USD")
@click.option("--max-time", type=int, help="Tiempo máximo total en segundos")
@click.option(
    "--completion-tag",
    default="COMPLETE",
    help="Tag que el agente emite al terminar (default: COMPLETE)",
)
@click.option("--agent", default="build", help="Agente a usar en cada iteración")
@click.option("--model", default=None, help="Modelo LLM a usar")
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
@click.option("--worktree", is_flag=True, help="Usar git worktree aislado")
@click.option("--report", "report_format", type=click.Choice(["json", "markdown", "github"]), default=None, help="Formato del reporte")
@click.option("--report-file", "report_file", type=click.Path(), default=None, help="Archivo de salida para el reporte")
@click.option("--quiet", is_flag=True, help="Modo silencioso")
def loop_cmd(
    task: str,
    checks: tuple[str, ...],
    spec_file: str | None,
    max_iterations: int,
    max_cost: float | None,
    max_time: int | None,
    completion_tag: str,
    agent: str,
    model: str | None,
    config: Path | None,
    worktree: bool,
    report_format: str | None,
    report_file: str | None,
    quiet: bool,
) -> None:
    """Ejecuta un Ralph Loop: iterar hasta que los checks pasen.

    Cada iteración usa un agente con contexto LIMPIO. Solo recibe:
    la tarea original, diff acumulado, errores de la iteración anterior,
    y progreso acumulado.

    Ejemplos:

        \b
        # Loop con test como check
        $ architect loop "implementa login" --check "pytest tests/"

        \b
        # Loop con múltiples checks
        $ architect loop "refactoriza auth" \\
            --check "ruff check src/" \\
            --check "pytest tests/ -q" \\
            --max-iterations 10

        \b
        # Con spec file y presupuesto
        $ architect loop "implementa spec" --spec spec.md \\
            --check "pytest" --max-cost 1.0

        \b
        # En worktree aislado (no modifica working tree)
        $ architect loop "migra DB" --check "pytest" --worktree
    """
    import os

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()

    configure_logging(
        app_config.logging if app_config else None,
        quiet=quiet,
    )

    ralph_config = RalphConfig(
        task=task,
        checks=list(checks),
        spec_file=spec_file,
        completion_tag=completion_tag,
        max_iterations=max_iterations,
        max_cost=max_cost,
        max_time=max_time,
        agent=agent,
        model=model,
        use_worktree=worktree,
    )

    def agent_factory(**kwargs):
        """Crea un AgentLoop fresco para cada iteración.

        Acepta workspace_root para soportar worktrees aislados.
        Cuando se pasa workspace_root, las tools del agente operan
        en ese directorio en lugar del workspace original.
        """
        iter_agent = kwargs.get("agent", agent)
        iter_model = kwargs.get("model", model)
        iter_workspace_root = kwargs.get("workspace_root")

        if not app_config:
            click.echo("Error: Configuración no disponible.", err=True)
            sys.exit(EXIT_CONFIG_ERROR)

        # Si se proporcionó workspace_root (worktree), usar ese en lugar del original
        iter_workspace_config = app_config.workspace
        iter_app_config = app_config
        if iter_workspace_root and str(iter_workspace_root) != workspace:
            iter_workspace_config = app_config.workspace.model_copy(
                update={"root": Path(iter_workspace_root)}
            )
            iter_app_config = app_config.model_copy(
                update={"workspace": iter_workspace_config}
            )

        # Crear componentes frescos para cada iteración
        registry = ToolRegistry()
        register_all_tools(registry, iter_workspace_config, app_config.commands)

        llm_config = app_config.llm
        if iter_model:
            # Override model for this iteration
            llm_config = app_config.llm.model_copy(update={"model": iter_model})

        llm = LLMAdapter(llm_config)
        context_mgr = ContextManager(app_config.context)
        ctx = ContextBuilder(context_manager=context_mgr)

        cost_tracker_iter: CostTracker | None = None
        if app_config.costs.enabled:
            price_loader = PriceLoader()
            cost_tracker_iter = CostTracker(price_loader=price_loader)

        try:
            agent_config = get_agent(iter_agent, app_config.agents, {"mode": "yolo"})
        except AgentNotFoundError:
            agent_config = get_agent("build", app_config.agents, {"mode": "yolo"})

        # Guardrails para iteraciones del loop (v4-A2)
        iter_guardrails: GuardrailsEngine | None = None
        if iter_app_config.guardrails.enabled:
            ws_root = str(Path(iter_workspace_config.root).resolve())
            iter_guardrails = GuardrailsEngine(
                config=iter_app_config.guardrails,
                workspace_root=ws_root,
            )

        # v4-A1: Hooks para iteraciones del loop
        iter_hook_executor: HookExecutor | None = None
        if iter_app_config.hooks:
            iter_hooks_registry = _build_hooks_registry(iter_app_config)
            if iter_hooks_registry.has_hooks():
                ws_root = str(Path(iter_workspace_config.root).resolve())
                iter_hook_executor = HookExecutor(
                    registry=iter_hooks_registry,
                    workspace_root=ws_root,
                )

        engine = ExecutionEngine(
            registry, iter_app_config, confirm_mode="yolo",
            hook_executor=iter_hook_executor,
            guardrails=iter_guardrails,
        )

        return AgentLoop(
            llm, engine, agent_config, ctx,
            context_manager=context_mgr,
            cost_tracker=cost_tracker_iter,
            hook_executor=iter_hook_executor,
            guardrails=iter_guardrails,
        )

    if not quiet:
        wt_label = " [worktree]" if worktree else ""
        click.echo(
            f"\nRalph Loop: {len(checks)} check(s), "
            f"max {max_iterations} iteraciones{wt_label}",
            err=True,
        )

    ralph = RalphLoop(ralph_config, agent_factory, workspace_root=workspace)
    result = ralph.run()

    # Resumen
    if not quiet:
        click.echo(f"\n--- Ralph Loop {'Completado' if result.success else 'Finalizado'} ---", err=True)
        click.echo(f"Iteraciones: {result.total_iterations}", err=True)
        click.echo(f"Coste total: ${result.total_cost:.4f}", err=True)
        click.echo(f"Duración: {result.total_duration:.1f}s", err=True)
        click.echo(f"Razón: {result.stop_reason}", err=True)
        if result.worktree_path:
            click.echo(f"Worktree: {result.worktree_path}", err=True)
            click.echo(
                "  Inspecciona los cambios y usa 'git merge architect/ralph-loop' para integrar.",
                err=True,
            )

        for it in result.iterations:
            status = "PASS" if it.all_checks_passed else "FAIL"
            tag = " [TAG]" if it.completion_tag_found else ""
            click.echo(
                f"  Iter {it.iteration}: [{status}]{tag} "
                f"steps={it.steps_taken} cost=${it.cost:.4f}",
                err=True,
            )

    # v4-B2: Generar reporte si se pidió
    if not report_format and report_file:
        report_format = _infer_report_format(report_file)
    if report_format:
        exec_report = ExecutionReport(
            task=task,
            agent=agent,
            model=model or (app_config.llm.model if app_config else "unknown"),
            status="success" if result.success else "failed",
            duration_seconds=round(result.total_duration, 2),
            steps=sum(it.steps_taken for it in result.iterations),
            total_cost=result.total_cost,
            files_modified=[],
            errors=[],
            timeline=[],
            stop_reason=result.stop_reason,
            git_diff=collect_git_diff(workspace),
        )
        gen = ReportGenerator(exec_report)
        report_content = {
            "json": gen.to_json,
            "markdown": gen.to_markdown,
            "github": gen.to_github_pr_comment,
        }[report_format]()

        if report_file:
            Path(report_file).write_text(report_content, encoding="utf-8")
            if not quiet:
                click.echo(f"Reporte guardado en {report_file}", err=True)
        else:
            click.echo(report_content)

    sys.exit(EXIT_SUCCESS if result.success else EXIT_FAILED)


@main.command("parallel")
@click.argument("task", required=False)
@click.option("--task", "tasks", multiple=True, help="Tarea (repetible para fan-out)")
@click.option("--workers", default=3, type=int, help="Número de workers (default: 3)")
@click.option("--models", help="Modelos separados por coma (ej: gpt-4o,claude-sonnet-4)")
@click.option("--agent", default="build", help="Agente a usar")
@click.option("--budget-per-worker", type=float, help="Presupuesto USD por worker")
@click.option("--timeout-per-worker", type=int, help="Timeout segundos por worker")
@click.option("-c", "--config", "config_path", type=click.Path(exists=True), default=None, help="Path al archivo de configuración YAML")
@click.option("--api-base", default=None, help="URL base de la API del LLM")
@click.option("--quiet", is_flag=True, help="Modo silencioso")
def parallel_cmd(
    task: str | None,
    tasks: tuple[str, ...],
    workers: int,
    models: str | None,
    agent: str,
    budget_per_worker: float | None,
    timeout_per_worker: int | None,
    config_path: str | None,
    api_base: str | None,
    quiet: bool,
) -> None:
    """Ejecuta múltiples agentes en paralelo con worktrees.

    Cada worker se ejecuta en un git worktree aislado. Los worktrees
    se conservan después de la ejecución para inspección.

    Ejemplos:

        \b
        # Misma tarea, 3 modelos diferentes
        $ architect parallel "implementa auth" \\
            --models gpt-4o,claude-sonnet-4,deepseek-chat

        \b
        # Fan-out con diferentes tareas
        $ architect parallel \\
            --task "implementa login" \\
            --task "implementa registro" \\
            --task "implementa logout" \\
            --workers 3
    """
    import os

    task_list = list(tasks) if tasks else ([task] if task else [])
    if not task_list:
        click.echo("Error: Especifica una tarea como argumento o con --task", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    model_list = models.split(",") if models else None
    workspace = os.getcwd()

    # Resolver config_path a absoluto para que funcione desde worktrees
    resolved_config = str(Path(config_path).resolve()) if config_path else None

    config = ParallelConfig(
        tasks=task_list,
        workers=workers,
        models=model_list,
        agent=agent,
        budget_per_worker=budget_per_worker,
        timeout_per_worker=timeout_per_worker,
        config_path=resolved_config,
        api_base=api_base,
    )

    if not quiet:
        click.echo(
            f"\nParallel Run: {workers} workers, "
            f"{len(task_list)} tarea(s)"
            + (f", modelos: {models}" if models else ""),
            err=True,
        )

    runner = ParallelRunner(config, workspace)
    results = runner.run()

    if not quiet:
        click.echo("\n--- Resultados Parallel Run ---", err=True)
        for r in results:
            click.echo(
                f"  Worker {r.worker_id}: [{r.status}] "
                f"branch={r.branch} model={r.model} "
                f"steps={r.steps} cost=${r.cost:.4f} "
                f"duration={r.duration:.1f}s",
                err=True,
            )
            if r.files_modified:
                click.echo(f"    files: {', '.join(r.files_modified[:5])}", err=True)

        click.echo(
            f"\nWorktrees conservados. Usa 'architect parallel-cleanup' para limpiar.",
            err=True,
        )

    any_success = any(r.status == "success" for r in results)
    sys.exit(EXIT_SUCCESS if any_success else EXIT_FAILED)


@main.command("parallel-cleanup")
def parallel_cleanup_cmd() -> None:
    """Limpia worktrees y branches de ejecuciones paralelas."""
    import os

    workspace = os.getcwd()
    runner = ParallelRunner(
        ParallelConfig(tasks=[""]),
        workspace,
    )
    removed = runner.cleanup()
    click.echo(f"Worktrees limpiados: {removed}")


@main.command("pipeline")
@click.argument("pipeline_file", type=click.Path(exists=True))
@click.option(
    "--var",
    "variables",
    multiple=True,
    help="Variable del pipeline (formato: nombre=valor, repetible)",
)
@click.option("--from-step", help="Empezar desde un paso específico")
@click.option("--dry-run", is_flag=True, help="Mostrar plan sin ejecutar")
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path al archivo de configuración YAML",
)
@click.option("--report", "report_format", type=click.Choice(["json", "markdown", "github"]), default=None, help="Formato del reporte")
@click.option("--report-file", "report_file", type=click.Path(), default=None, help="Archivo de salida para el reporte")
@click.option("--quiet", is_flag=True, help="Modo silencioso")
def pipeline_cmd(
    pipeline_file: str,
    variables: tuple[str, ...],
    from_step: str | None,
    dry_run: bool,
    config: Path | None,
    report_format: str | None,
    report_file: str | None,
    quiet: bool,
) -> None:
    """Ejecuta un workflow YAML multi-step.

    El archivo YAML define una secuencia de pasos, cada uno con su
    agente, prompt, y configuración.

    Ejemplos:

        \b
        # Ejecutar pipeline completo
        $ architect pipeline workflow.yaml --var task="añade auth"

        \b
        # Continuar desde un paso específico
        $ architect pipeline workflow.yaml --from-step test

        \b
        # Dry-run para ver el plan
        $ architect pipeline workflow.yaml --dry-run
    """
    import os

    try:
        app_config = load_config(config_path=config)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()

    configure_logging(
        app_config.logging if app_config else None,
        quiet=quiet,
    )

    # Parsear variables
    vars_dict: dict[str, str] = {}
    for v in variables:
        if "=" in v:
            key, val = v.split("=", 1)
            vars_dict[key.strip()] = val.strip()

    def agent_factory(**kwargs):
        """Crea un AgentLoop fresco para cada step del pipeline."""
        iter_agent = kwargs.get("agent", "build")
        iter_model = kwargs.get("model")

        if not app_config:
            click.echo("Error: Configuración no disponible.", err=True)
            sys.exit(EXIT_CONFIG_ERROR)

        registry = ToolRegistry()
        register_all_tools(registry, app_config.workspace, app_config.commands)

        llm_config = app_config.llm
        if iter_model:
            llm_config = app_config.llm.model_copy(update={"model": iter_model})

        llm = LLMAdapter(llm_config)
        context_mgr = ContextManager(app_config.context)
        ctx = ContextBuilder(context_manager=context_mgr)

        cost_tracker_iter: CostTracker | None = None
        if app_config.costs.enabled:
            price_loader = PriceLoader()
            cost_tracker_iter = CostTracker(price_loader=price_loader)

        try:
            agent_config = get_agent(iter_agent, app_config.agents, {"mode": "yolo"})
        except AgentNotFoundError:
            agent_config = get_agent("build", app_config.agents, {"mode": "yolo"})

        # Guardrails para steps del pipeline (v4-A2)
        pipe_guardrails: GuardrailsEngine | None = None
        if app_config.guardrails.enabled:
            pipe_guardrails = GuardrailsEngine(
                config=app_config.guardrails,
                workspace_root=workspace,
            )

        # v4-A1: Hooks para steps del pipeline
        pipe_hook_executor: HookExecutor | None = None
        if app_config.hooks:
            pipe_hooks_registry = _build_hooks_registry(app_config)
            if pipe_hooks_registry.has_hooks():
                pipe_hook_executor = HookExecutor(
                    registry=pipe_hooks_registry,
                    workspace_root=workspace,
                )

        engine = ExecutionEngine(
            registry, app_config, confirm_mode="yolo",
            hook_executor=pipe_hook_executor,
            guardrails=pipe_guardrails,
        )

        return AgentLoop(
            llm, engine, agent_config, ctx,
            context_manager=context_mgr,
            cost_tracker=cost_tracker_iter,
            hook_executor=pipe_hook_executor,
            guardrails=pipe_guardrails,
        )

    runner = PipelineRunner.from_yaml(
        pipeline_file, vars_dict, agent_factory, workspace_root=workspace,
    )

    if dry_run and not quiet:
        click.echo(runner.get_plan_summary(), err=True)
        sys.exit(EXIT_SUCCESS)

    if not quiet:
        click.echo(
            f"\nPipeline: {runner.config.name} "
            f"({len(runner.config.steps)} steps)",
            err=True,
        )

    results = runner.run(from_step=from_step, dry_run=dry_run)

    if not quiet:
        click.echo("\n--- Pipeline Results ---", err=True)
        for r in results:
            status_icon = {"success": "PASS", "failed": "FAIL", "skipped": "SKIP"}.get(
                r.status, r.status
            )
            click.echo(
                f"  [{status_icon}] {r.step_name} "
                f"(${r.cost:.4f}, {r.duration:.1f}s)",
                err=True,
            )
            if r.error:
                click.echo(f"    Error: {r.error[:100]}", err=True)

    all_ok = all(r.status in ("success", "skipped", "dry_run") for r in results)

    # v4-B2: Generar reporte si se pidió
    if not report_format and report_file:
        report_format = _infer_report_format(report_file)
    if report_format:
        total_cost = sum(r.cost for r in results)
        total_duration = sum(r.duration for r in results)
        pipeline_errors = [f"{r.step_name}: {r.error}" for r in results if r.error]
        exec_report = ExecutionReport(
            task=f"Pipeline: {pipeline_file}",
            agent="pipeline",
            model=app_config.llm.model if app_config else "unknown",
            status="success" if all_ok else "failed",
            duration_seconds=round(total_duration, 2),
            steps=len(results),
            total_cost=total_cost,
            files_modified=[],
            errors=pipeline_errors,
            timeline=[
                {"step": i, "tool": r.step_name, "duration": round(r.duration, 2)}
                for i, r in enumerate(results)
            ],
            stop_reason=None,
            git_diff=collect_git_diff(workspace),
        )
        gen = ReportGenerator(exec_report)
        report_content = {
            "json": gen.to_json,
            "markdown": gen.to_markdown,
            "github": gen.to_github_pr_comment,
        }[report_format]()

        if report_file:
            Path(report_file).write_text(report_content, encoding="utf-8")
            if not quiet:
                click.echo(f"Reporte guardado en {report_file}", err=True)
        else:
            click.echo(report_content)

    sys.exit(EXIT_SUCCESS if all_ok else EXIT_FAILED)


@main.command("rollback")
@click.option("--to-step", type=int, help="Rollback al checkpoint de este step")
@click.option("--to-commit", help="Rollback a un commit específico")
def rollback_cmd(to_step: int | None, to_commit: str | None) -> None:
    """Deshace cambios hasta un checkpoint.

    Los checkpoints son creados automáticamente por architect durante
    la ejecución. Usa 'architect history' para ver los disponibles.

    Ejemplos:

        \b
        # Rollback al paso 3
        $ architect rollback --to-step 3

        \b
        # Rollback a un commit específico
        $ architect rollback --to-commit abc1234
    """
    import os

    if to_step is None and to_commit is None:
        click.echo("Error: Especifica --to-step o --to-commit", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    mgr = CheckpointManager(os.getcwd())

    if mgr.rollback(step=to_step, commit=to_commit):
        target = f"step {to_step}" if to_step is not None else to_commit
        click.echo(f"Rollback exitoso a {target}")
    else:
        click.echo("Error: No se pudo hacer rollback.", err=True)
        sys.exit(EXIT_FAILED)


@main.command("history")
def history_cmd() -> None:
    """Muestra historial de checkpoints de architect.

    Lista todos los git commits con prefijo 'architect:checkpoint'
    creados durante ejecuciones del agente.
    """
    import os
    from datetime import datetime

    mgr = CheckpointManager(os.getcwd())
    checkpoints = mgr.list_checkpoints()

    if not checkpoints:
        click.echo("No hay checkpoints registrados.")
        return

    click.echo(f"Checkpoints ({len(checkpoints)}):\n")
    click.echo(f"  {'Step':<6s} {'Hash':<9s} {'Fecha':<20s} Mensaje")
    click.echo(f"  {'─'*6} {'─'*9} {'─'*20} {'─'*30}")
    for cp in checkpoints:
        date_str = datetime.fromtimestamp(cp.timestamp).strftime("%Y-%m-%d %H:%M:%S") if cp.timestamp else "-"
        click.echo(
            f"  {cp.step:<6d} {cp.short_hash():<9s} {date_str:<20s} {cp.message or '-'}"
        )

    click.echo(f"\nUsa 'architect rollback --to-step N' para restaurar.")


# ── v4-D3: COMPETITIVE EVAL ────────────────────────────────────────────


@main.command("eval")
@click.argument("task")
@click.option(
    "--models", required=True,
    help="Modelos separados por coma (ej: gpt-4o,claude-sonnet-4-20250514,gemini-2.0-flash)",
)
@click.option("--check", "checks", multiple=True, help="Comando de verificación (repetible)")
@click.option("--agent", default="build", help="Agente a usar en cada modelo")
@click.option("--max-steps", default=50, type=int, help="Máximo de pasos por modelo")
@click.option("--budget-per-model", type=float, help="Presupuesto USD por modelo")
@click.option("--timeout-per-model", type=int, help="Timeout en segundos por modelo")
@click.option(
    "--report-file", type=click.Path(),
    help="Archivo donde guardar el reporte markdown",
)
def eval_cmd(
    task: str,
    models: str,
    checks: tuple[str, ...],
    agent: str,
    max_steps: int,
    budget_per_model: float | None,
    timeout_per_model: int | None,
    report_file: str | None,
) -> None:
    """Evaluación competitiva: ejecuta la misma tarea con múltiples modelos.

    Compara el resultado de diferentes modelos LLM ejecutando la misma tarea
    en worktrees git aislados. Genera un reporte con ranking y métricas.

    Ejemplo:

        architect eval "Implementa auth JWT" --models gpt-4o,claude-sonnet-4-20250514 --check "pytest tests/"
    """
    import os

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if len(model_list) < 2:
        click.echo("Error: Se necesitan al menos 2 modelos para comparar.", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    config = CompetitiveConfig(
        task=task,
        models=model_list,
        checks=list(checks),
        agent=agent,
        max_steps=max_steps,
        budget_per_model=budget_per_model,
        timeout_per_model=timeout_per_model,
    )

    click.echo(f"Evaluación competitiva: {len(model_list)} modelos")
    click.echo(f"  Modelos: {', '.join(model_list)}")
    click.echo(f"  Tarea: {task[:80]}...")
    if checks:
        click.echo(f"  Checks: {', '.join(checks)}")
    click.echo()

    evaluator = CompetitiveEval(config, os.getcwd())
    results = evaluator.run()

    # Generar y mostrar reporte
    report = evaluator.generate_report(results)

    if report_file:
        Path(report_file).write_text(report, encoding="utf-8")
        click.echo(f"\nReporte guardado en: {report_file}")
    else:
        click.echo(report)

    # Exit code: 0 si al menos un modelo tuvo éxito
    any_success = any(r.status == "success" for r in results)
    sys.exit(EXIT_SUCCESS if any_success else EXIT_FAILED)


# ── v4-D5: PRESET CONFIGS ─────────────────────────────────────────────


@main.command("init")
@click.option(
    "--preset",
    type=click.Choice(sorted(AVAILABLE_PRESETS)),
    required=True,
    help="Preset de configuración a aplicar",
)
@click.option("--overwrite", is_flag=True, help="Sobrescribir archivos existentes")
@click.option("--list-presets", "show_list", is_flag=True, help="Listar presets disponibles")
def init_cmd(preset: str | None, overwrite: bool, show_list: bool) -> None:
    """Inicializa la configuración de architect en el proyecto.

    Crea archivos .architect.md y config.yaml con configuraciones
    predefinidas según el stack tecnológico o perfil de seguridad.

    Ejemplo:

        architect init --preset python
    """
    import os

    manager = PresetManager(os.getcwd())

    if show_list:
        presets = manager.list_presets()
        click.echo("Presets disponibles:\n")
        for p in presets:
            click.echo(f"  {p['name']:<15s} {p['description']}")
        return

    if not preset:
        click.echo("Error: Especifica un preset con --preset", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        files = manager.apply_preset(preset, overwrite=overwrite)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    if files:
        click.echo(f"Preset '{preset}' aplicado. Archivos creados:")
        for f in files:
            click.echo(f"  + {f}")
    else:
        click.echo(f"Preset '{preset}': todos los archivos ya existen (usa --overwrite para reemplazar).")

    click.echo(f"\nDirectorio .architect/ creado.")
    click.echo(f"Edita .architect.md para personalizar las instrucciones del agente.")


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
