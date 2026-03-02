"""
Main CLI for architect using Click.

v3: No explicit agent -> uses 'build' directly (no more MixedModeRunner by default).
    Added support for PostEditHooks, human logging, banner and result separator.
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
from .i18n import set_language as _set_language
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

# v4-A1: Complete hooks system
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
from .features.pipelines import PipelineRunner, PipelineValidationError
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

# Exit codes
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_CONFIG_ERROR = 3
EXIT_AUTH_ERROR = 4
EXIT_TIMEOUT = 5
EXIT_INTERRUPTED = 130

# Current version
_VERSION = "1.1.0"


_REPORT_EXT_MAP: dict[str, str] = {
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "github",
}


def _write_report_file(report_file: str, content: str) -> str | None:
    """Write the report to the specified file, creating directories if needed.

    Strategy:
    1. Create parent directories and try to write to the original path.
    2. If that fails, try writing just the filename in the current directory.
    3. If both fail, return an error message.

    Returns:
        Path where the file was saved, or None if writing failed.
    """
    target = Path(report_file)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)
    except OSError:
        pass

    # Fallback: write to current directory
    fallback = Path(target.name)
    try:
        fallback.write_text(content, encoding="utf-8")
        click.echo(
            f"Could not create '{target.parent}'. "
            f"Report saved to '{fallback}' (current directory).",
            err=True,
        )
        return str(fallback)
    except OSError as e:
        click.echo(f"Could not save report: {e}", err=True)
        return None


def _infer_report_format(report_file: str) -> str:
    """Infer the report format from the file extension.

    Returns:
        'json', 'markdown' or 'github'. Default: 'markdown'.
    """
    ext = Path(report_file).suffix.lower()
    return _REPORT_EXT_MAP.get(ext, "markdown")


def _print_banner(agent_name: str, model: str, quiet: bool) -> None:
    """Print the startup banner (v3-M5)."""
    if not quiet:
        width = 50
        label = f" architect · {agent_name} · {model} "
        dashes = "─" * max(0, width - len(label))
        click.echo(f"\n─── {label}{dashes}\n", err=True)


def _print_result_separator(quiet: bool) -> None:
    """Print the separator before the result (v3-M5)."""
    if not quiet:
        click.echo(f"\n─── Result {'─' * 40}\n", err=True)


@click.group()
@click.version_option(version=_VERSION, prog_name="architect")
def main() -> None:
    """architect - Headless agentic CLI tool for orchestrating AI agents.

    architect lets you run complex tasks using language models,
    with explicit control, declarative configuration, and no human intervention.
    """
    pass


@main.command()
@click.argument("prompt", required=True)
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
@click.option(
    "-a",
    "--agent",
    default=None,
    help="Agent to use (build, plan, resume, review, or custom). Default: build",
)
@click.option(
    "-m",
    "--mode",
    type=click.Choice(["confirm-all", "confirm-sensitive", "yolo"]),
    help="Action confirmation mode",
)
@click.option(
    "-w",
    "--workspace",
    type=click.Path(path_type=Path),
    help="Working directory (workspace root)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Simulate execution without making real changes",
)
@click.option(
    "--model",
    help="LLM model to use (e.g.: gpt-4o, claude-sonnet-4-6)",
)
@click.option(
    "--api-base",
    help="LLM API base URL",
)
@click.option(
    "--api-key",
    help="API key (can also use env var)",
)
@click.option(
    "--no-stream",
    is_flag=True,
    help="Disable response streaming",
)
@click.option(
    "--mcp-config",
    type=click.Path(exists=True, path_type=Path),
    help="Additional MCP configuration file",
)
@click.option(
    "--disable-mcp",
    is_flag=True,
    help="Disable connection to MCP servers",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Verbosity level (-v, -vv, -vvv for more detail)",
)
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "human", "warn", "error"]),
    help="Explicit logging level",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    help="File to save structured logs (JSON)",
)
@click.option(
    "--max-steps",
    type=int,
    help="Maximum number of agent steps (watchdog)",
)
@click.option(
    "--timeout",
    type=int,
    default=None,
    help="Total timeout in seconds (total time watchdog)",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Output in structured JSON format",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Quiet mode (critical errors only)",
)
@click.option(
    "--self-eval",
    "self_eval",
    type=click.Choice(["off", "basic", "full"]),
    default=None,
    help="Self-evaluation mode: off|basic|full (default: YAML config)",
)
@click.option(
    "--allow-commands",
    "allow_commands",
    is_flag=True,
    default=False,
    help="Enable run_command tool (overrides commands.enabled in config)",
)
@click.option(
    "--no-commands",
    "no_commands",
    is_flag=True,
    default=False,
    help="Disable run_command tool completely",
)
@click.option(
    "--budget",
    type=float,
    default=None,
    help="Spending limit in USD per execution",
)
@click.option(
    "--show-costs",
    "show_costs",
    is_flag=True,
    default=False,
    help="Show cost summary when finished",
)
@click.option(
    "--cache",
    "use_local_cache",
    is_flag=True,
    default=False,
    help="Enable local LLM cache for development",
)
@click.option(
    "--no-cache",
    "disable_cache",
    is_flag=True,
    default=False,
    help="Disable local LLM cache even if enabled in config",
)
@click.option(
    "--cache-clear",
    "cache_clear",
    is_flag=True,
    default=False,
    help="Clear local LLM cache before execution",
)
@click.option(
    "--report",
    "report_format",
    type=click.Choice(["json", "markdown", "github"]),
    default=None,
    help="Execution report format",
)
@click.option(
    "--report-file",
    "report_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file for the report",
)
@click.option(
    "--context-git-diff",
    "git_diff_ref",
    default=None,
    help="Inject git diff as context (e.g.: origin/main)",
)
@click.option(
    "--session",
    "session_id",
    default=None,
    help="Session ID for resume (resumes a previous session)",
)
@click.option(
    "--confirm-mode",
    "confirm_mode",
    type=click.Choice(["yolo", "confirm-sensitive", "confirm-all"]),
    default=None,
    help="Confirmation mode (CI-friendly alias for --mode)",
)
@click.option(
    "--exit-code-on-partial",
    "exit_code_on_partial",
    type=int,
    default=None,
    help="Exit code if result is partial (default: 2)",
)
@click.option(
    "--health",
    "health_check",
    is_flag=True,
    default=False,
    help="Run code health analysis before/after (v4-D2)",
)
def run(prompt: str, **kwargs) -> None:  # type: ignore
    """Run a task using an AI agent.

    PROMPT: Description of the task to perform

    By default uses the 'build' agent (plans + executes in a single loop).
    Use -a to select a different agent.

    Examples:

        \b
        # General task (build agent by default)
        $ architect run "add email validation to user.py"

        \b
        # Analysis without modifications
        $ architect run "analyze this project" -a review

        \b
        # Planning only (without executing)
        $ architect run "how would I refactor main.py?" -a plan

        \b
        # Full automatic execution without confirmations
        $ architect run "generate scaffolding" --mode yolo

        \b
        # Dry-run to see what it would do without executing
        $ architect run "modify config.yaml" --dry-run

        \b
        # Structured JSON output (for pipes)
        $ architect run "summarize the project" --quiet --json | jq .

        \b
        # With cost limit and cost summary
        $ architect run "refactor everything" --budget 0.50 --show-costs
    """
    try:
        # Load configuration
        config = load_config(
            config_path=kwargs.get("config"),
            cli_args=kwargs,
        )
        _set_language(config.language)

        # Configure logging before anything else (avoids spurious debug)
        configure_logging(
            config.logging,
            json_output=kwargs.get("json_output", False),
            quiet=kwargs.get("quiet", False),
        )

        # Install GracefulShutdown for SIGINT + SIGTERM (after logging)
        shutdown = GracefulShutdown()

        # v3-M3: No agent -> use 'build' directly (no MixedModeRunner)
        agent_name = kwargs.get("agent") or "build"

        # Streaming mode
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

        # Apply CLI overrides for commands
        if kwargs.get("allow_commands"):
            config.commands.enabled = True
        if kwargs.get("no_commands"):
            config.commands.enabled = False

        # Create tool registry
        registry = ToolRegistry()
        register_all_tools(registry, config.workspace, config.commands)

        # Discover MCP tools
        if not kwargs.get("disable_mcp") and config.mcp.servers:
            if not kwargs.get("quiet"):
                click.echo(
                    f"Discovering MCP tools from {len(config.mcp.servers)} server(s)...",
                    err=True,
                )
            discovery = MCPDiscovery()
            mcp_stats = discovery.discover_and_register(config.mcp.servers, registry)

            if not kwargs.get("quiet") and kwargs.get("verbose", 0) >= 1:
                if mcp_stats["servers_success"] > 0:
                    click.echo(
                        f"  {mcp_stats['tools_registered']} MCP tools registered",
                        err=True,
                    )
                if mcp_stats["servers_failed"] > 0:
                    click.echo(
                        f"  {mcp_stats['servers_failed']} server(s) unavailable",
                        err=True,
                    )

        # Build repository index
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

        # v4-A3: Create SkillsLoader and load project context
        skills_loader: SkillsLoader | None = None
        if config.skills.auto_discover:
            skills_loader = SkillsLoader(str(Path(config.workspace.root).resolve()))
            skills_loader.load_project_context()
            skills_loader.discover_skills()

        # v4-A4: Create ProceduralMemory if configured
        memory: ProceduralMemory | None = None
        if config.memory.enabled:
            memory = ProceduralMemory(str(Path(config.workspace.root).resolve()))

        # v4-B1: Create SessionManager if auto_save is enabled
        session_manager: SessionManager | None = None
        if config.sessions.auto_save:
            session_manager = SessionManager(str(Path(config.workspace.root).resolve()))

        # v4-B1: If a session_id was provided, load the previous session
        resume_session = None
        session_id = kwargs.get("session_id")
        if session_id and session_manager:
            resume_session = session_manager.load(session_id)
            if resume_session is None:
                click.echo(f"Error: Session '{session_id}' not found", err=True)
                sys.exit(EXIT_CONFIG_ERROR)
            if not kwargs.get("quiet"):
                click.echo(
                    f"Resuming session {session_id} "
                    f"(step {resume_session.steps_completed}, "
                    f"status={resume_session.status})",
                    err=True,
                )

        # v4-B3: Inject git diff as context if requested
        git_diff_context: str | None = None
        if kwargs.get("git_diff_ref"):
            git_diff_context = _get_git_diff_context(kwargs["git_diff_ref"])
            if git_diff_context and not kwargs.get("quiet"):
                click.echo(
                    f"Git diff context injected (vs {kwargs['git_diff_ref']})",
                    err=True,
                )

        # v4-A1: Create HookExecutor with the complete hooks system
        hook_executor: HookExecutor | None = None
        hooks_registry = _build_hooks_registry(config)
        if hooks_registry.has_hooks():
            hook_executor = HookExecutor(
                registry=hooks_registry,
                workspace_root=str(Path(config.workspace.root).resolve()),
            )

        # Determine whether to use local LLM cache
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
                    click.echo(f"Cache cleared: {cleared} entries removed", err=True)

        # Create cost tracker
        cost_tracker: CostTracker | None = None
        if config.costs.enabled:
            price_loader = PriceLoader(custom_path=config.costs.prices_file)
            budget_usd = kwargs.get("budget") or config.costs.budget_usd
            cost_tracker = CostTracker(
                price_loader=price_loader,
                budget_usd=budget_usd,
                warn_at_usd=config.costs.warn_at_usd,
            )

        # Create LLM adapter
        llm = LLMAdapter(config.llm, local_cache=local_cache)

        # Create context manager and context builder
        context_mgr = ContextManager(config.context)
        ctx = ContextBuilder(repo_index=repo_index, context_manager=context_mgr)

        # Resolve agent with CLI overrides
        # --confirm-mode is a CI-friendly alias for --mode; --confirm-mode takes priority
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
            click.echo(f"Available agents: {', '.join(available)}", err=True)
            sys.exit(EXIT_FAILED)

        # Inject MCP tools into the agent's allowed_tools so the LLM can see them.
        # Without this, agents with explicit allowed_tools (like build) would not expose
        # MCP tools to the LLM even though they are registered in the ToolRegistry.
        if agent_config.allowed_tools:
            mcp_tool_names = [
                t.name for t in registry.list_all()
                if t.name.startswith("mcp_")
            ]
            if mcp_tool_names:
                agent_config.allowed_tools.extend(mcp_tool_names)

        # v4-A2: Create guardrails engine if configured
        guardrails_engine: GuardrailsEngine | None = None
        if config.guardrails.enabled:
            guardrails_engine = GuardrailsEngine(
                config=config.guardrails,
                workspace_root=str(Path(config.workspace.root).resolve()),
            )

        # Create execution engine with hooks (v4-A1) and guardrails (v4-A2)
        engine = ExecutionEngine(
            registry,
            config,
            confirm_mode=agent_config.confirm_mode,
            hook_executor=hook_executor,
            guardrails=guardrails_engine,
        )

        # Configure dry-run
        if kwargs.get("dry_run"):
            engine.set_dry_run(True)

        # v3-M5: Startup banner
        _print_banner(agent_name, config.llm.model, kwargs.get("quiet", False))

        if not kwargs.get("quiet") and kwargs.get("verbose", 0) >= 1:
            click.echo(f"Workspace: {config.workspace.root}", err=True)
            click.echo(f"Mode: {agent_config.confirm_mode}", err=True)
            click.echo(f"Streaming: {'yes' if use_stream else 'no'}", err=True)
            if kwargs.get("dry_run"):
                click.echo("DRY-RUN enabled (no real changes will be made)", err=True)
            click.echo(err=True)

        # v4-B4: Create DryRunTracker if --dry-run
        dry_run_tracker: DryRunTracker | None = None
        if kwargs.get("dry_run"):
            dry_run_tracker = DryRunTracker()

        # v4-D4: Create telemetry tracer
        tracer = create_tracer(
            enabled=config.telemetry.enabled,
            exporter=config.telemetry.exporter,
            endpoint=config.telemetry.endpoint,
            trace_file=config.telemetry.trace_file,
        )

        # Create agent loop (v3-M1: while True + timeout, v4-A1: hooks, v4-A2: guardrails, v4-A3: skills, v4-B1: sessions)
        loop = AgentLoop(
            llm,
            engine,
            agent_config,
            ctx,
            shutdown=shutdown,
            step_timeout=0,  # No SIGALRM per step (total timeout is controlled by `timeout`)
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

        # v4-D1: Register dispatch_subagent tool with agent_factory
        def _subagent_factory(agent: str = "build", max_steps: int = 15, allowed_tools: list[str] | None = None, **kw: Any) -> AgentLoop:
            """Create a fresh AgentLoop for sub-agents."""
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

        # v4-B1/B3: Enrich prompt with additional context
        effective_prompt = prompt
        if resume_session:
            effective_prompt = (
                f"You are resuming an interrupted session.\n"
                f"Original task: {resume_session.task}\n"
                f"Steps completed: {resume_session.steps_completed}\n"
                f"Files modified: {', '.join(resume_session.files_modified) or 'none'}\n\n"
                f"Continue the task from where it left off."
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
                click.echo("Health: 'before' snapshot captured", err=True)

        # Execute (with telemetry tracing v4-D4)
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

        # run_fn for evaluate_full
        def run_fn(correction_prompt: str):  # type: ignore[misc]
            return loop.run(correction_prompt, stream=False)

        # Self-evaluation
        self_eval_mode = kwargs.get("self_eval") or config.evaluation.mode
        if self_eval_mode != "off" and state.status == "success":
            if not kwargs.get("quiet"):
                click.echo("Evaluating result...", err=True)

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
                        f"{icon} Evaluation: {'completed' if passed else 'incomplete'} "
                        f"({eval_result.confidence:.0%} confidence)",
                        err=True,
                    )
                    for issue in eval_result.issues:
                        click.echo(f"   - {issue}", err=True)
                    if not passed and eval_result.suggestion:
                        click.echo(f"   Suggestion: {eval_result.suggestion}", err=True)

            elif self_eval_mode == "full":
                state = evaluator.evaluate_full(prompt, state, run_fn)
                if not kwargs.get("quiet"):
                    click.echo(
                        f"Full evaluation completed (status: {state.status})",
                        err=True,
                    )

        # v4-B4: Show dry-run summary if applicable
        if dry_run_tracker:
            if not kwargs.get("quiet"):
                click.echo("\n" + dry_run_tracker.get_plan_summary(), err=True)

        # v4-B2: Generate report if requested
        report_format = kwargs.get("report_format")
        if not report_format and kwargs.get("report_file"):
            report_format = _infer_report_format(kwargs["report_file"])
        if report_format:
            duration = time.time() - state.start_time

            # Collect modified files and timeline from StepResults
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
                saved_path = _write_report_file(report_file, report_content)
                if saved_path and not kwargs.get("quiet"):
                    click.echo(f"Report saved to {saved_path}", err=True)
            else:
                click.echo(report_content, err=True)

        # Show cost summary
        show_costs = kwargs.get("show_costs") or kwargs.get("verbose", 0) >= 1
        if show_costs and not kwargs.get("quiet") and cost_tracker and cost_tracker.has_data():
            click.echo(f"\nCost: {cost_tracker.format_summary_line()}", err=True)

        # v3-M5: Result separator
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
                    f"\nStatus: {state.status}{stop_info} | "
                    f"Steps: {state.current_step} | "
                    f"Tool calls: {state.total_tool_calls}",
                    err=True,
                )

        # v4-D4: Shutdown tracer (flush pending spans)
        tracer.shutdown()

        # Exit code
        if shutdown.should_stop:
            sys.exit(EXIT_INTERRUPTED)

        # v4-B3: --exit-code-on-partial allows customizing the exit code
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
        click.echo("\nInterrupted.", err=True)
        sys.exit(EXIT_INTERRUPTED)
    except FileNotFoundError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception as e:
        error_str = str(e).lower()
        if any(kw in error_str for kw in ("authenticationerror", "auth", "api key", "unauthorized", "401")):
            click.echo(f"Authentication error: {e}", err=True)
            sys.exit(EXIT_AUTH_ERROR)
        elif any(kw in error_str for kw in ("timeout", "timed out", "readtimeout")):
            click.echo(f"Timeout: {e}", err=True)
            sys.exit(EXIT_TIMEOUT)
        else:
            click.echo(f"Unexpected error: {e}", err=True)
            if kwargs.get("verbose", 0) > 1:
                import traceback
                traceback.print_exc()
            sys.exit(EXIT_FAILED)


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the configuration file to validate",
)
def validate_config(config: Path | None) -> None:
    """Validate a YAML configuration file."""
    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
        click.echo("Valid configuration")
        click.echo(f"  Model: {app_config.llm.model}")
        click.echo(f"  Agents defined: {len(app_config.agents)}")
        click.echo(f"  MCP servers: {len(app_config.mcp.servers)}")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception as e:
        click.echo(f"Invalid configuration: {e}", err=True)
        sys.exit(EXIT_FAILED)


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
def agents(config: Path | None) -> None:
    """List available agents and their configuration."""
    from .agents import DEFAULT_AGENTS, list_available_agents

    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
    except Exception:
        app_config = None

    yaml_agents = app_config.agents if app_config else {}

    click.echo("Available agents:\n")

    click.echo("  Default agents:")
    default_descriptions = {
        "build":  "Creates and modifies files — plans + executes in a single loop (confirm-sensitive)",
        "plan":   "Analyzes and plans tasks without executing (yolo, read-only)",
        "resume": "Reads and summarizes information (yolo, read-only)",
        "review": "Code review (yolo, read-only)",
    }
    for name, desc in default_descriptions.items():
        marker = " *" if name in yaml_agents else ""
        click.echo(f"    {name:<12} {desc}{marker}")

    custom = {k: v for k, v in yaml_agents.items() if k not in DEFAULT_AGENTS}
    if custom:
        click.echo("\n  Custom agents (from config):")
        for name, agent_cfg in custom.items():
            tools = ", ".join(agent_cfg.allowed_tools) if agent_cfg.allowed_tools else "all"
            click.echo(f"    {name:<12} tools=[{tools}], mode={agent_cfg.confirm_mode}")

    overrides = {k: v for k, v in yaml_agents.items() if k in DEFAULT_AGENTS}
    if overrides:
        click.echo("\n  Defaults with config override (marked with *):")
        for name in overrides:
            click.echo(f"    {name}")

    click.echo(f"\n  Usage: architect run \"<task>\" -a <agent-name>")
    click.echo(f"  Without -a -> uses 'build' by default")


@main.group()
def skill() -> None:
    """Manage project skills."""
    pass


@skill.command("install")
@click.argument("source")
def skill_install(source: str) -> None:
    """Install a skill from GitHub. Format: user/repo/path/to/skill."""
    import os

    installer = SkillInstaller(os.getcwd())
    if installer.install_from_github(source):
        click.echo(f"Skill installed from {source}")
    else:
        click.echo("Error installing skill", err=True)
        raise SystemExit(1)


@skill.command("create")
@click.argument("name")
def skill_create(name: str) -> None:
    """Create a local skill with template."""
    import os

    installer = SkillInstaller(os.getcwd())
    path = installer.create_local(name)
    click.echo(f"Skill created at {path}")


@skill.command("list")
def skill_list() -> None:
    """List available skills."""
    import os

    installer = SkillInstaller(os.getcwd())
    skills = installer.list_installed()
    if not skills:
        click.echo("  No skills installed.")
        return
    for s in skills:
        source_label = "local" if s["source"] == "local" else "installed"
        click.echo(f"  {s['name']:20s} ({source_label})")


@skill.command("remove")
@click.argument("name")
def skill_remove(name: str) -> None:
    """Remove an installed skill."""
    import os

    installer = SkillInstaller(os.getcwd())
    if installer.uninstall(name):
        click.echo(f"Skill '{name}' removed")
    else:
        click.echo(f"Skill '{name}' not found", err=True)


# ── SESSION COMMANDS (v4-B1) ─────────────────────────────────────────────


@main.command()
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
def sessions(config: Path | None) -> None:
    """List saved sessions."""
    import os

    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()
    mgr = SessionManager(workspace)
    session_list = mgr.list_sessions()

    if not session_list:
        click.echo("No saved sessions.")
        return

    click.echo(f"Saved sessions ({len(session_list)}):\n")
    click.echo(f"  {'ID':<24s} {'Status':<10s} {'Steps':<7s} {'Cost':<10s} Task")
    click.echo(f"  {'─'*24} {'─'*10} {'─'*7} {'─'*10} {'─'*30}")
    for s in session_list:
        cost_str = f"${s['cost']:.4f}" if s["cost"] else "-"
        click.echo(
            f"  {s['id']:<24s} {s['status']:<10s} {s['steps']:<7d} {cost_str:<10s} {s['task']}"
        )

    click.echo(f"\nUse 'architect run \"<task>\" --session <ID>' to resume.")


@main.command()
@click.argument("session_id")
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
def resume(session_id: str, config: Path | None) -> None:
    """Resume an interrupted session.

    SESSION_ID: Identifier of the session to resume.
    Can be obtained with 'architect sessions'.
    """
    import os

    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()
    mgr = SessionManager(workspace)
    session = mgr.load(session_id)

    if session is None:
        click.echo(f"Error: Session '{session_id}' not found.", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    click.echo(f"Resuming session: {session_id}")
    click.echo(f"  Task: {session.task}")
    click.echo(f"  Status: {session.status}")
    click.echo(f"  Steps: {session.steps_completed}")
    click.echo(f"  Cost: ${session.total_cost:.4f}")
    click.echo()

    # Delegate to the run command with the session_id
    # This is a shortcut -- the user can do the same with:
    #   architect run "<task>" --session <id>
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
    help="Delete sessions older than N days",
)
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
def cleanup(older_than_days: int, config: Path | None) -> None:
    """Clean up old sessions."""
    import os

    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()
    mgr = SessionManager(workspace)
    removed = mgr.cleanup(older_than_days=older_than_days)
    click.echo(f"Sessions removed: {removed}")


# ── PHASE C COMMANDS (v4-C1..C5) ───────────────────────────────────────


@main.command("loop")
@click.argument("task")
@click.option(
    "--check",
    "checks",
    multiple=True,
    required=True,
    help="Verification command (repeatable with multiple --check)",
)
@click.option(
    "--spec",
    "spec_file",
    type=click.Path(exists=True),
    help="Detailed specification file",
)
@click.option(
    "--max-iterations",
    default=25,
    type=int,
    help="Maximum number of iterations (default: 25)",
)
@click.option("--max-cost", type=float, help="Maximum total cost in USD")
@click.option("--max-time", type=int, help="Maximum total time in seconds")
@click.option(
    "--completion-tag",
    default="COMPLETE",
    help="Tag the agent emits when done (default: COMPLETE)",
)
@click.option("--agent", default="build", help="Agent to use in each iteration")
@click.option("--model", default=None, help="LLM model to use")
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
@click.option("--worktree", is_flag=True, help="Use isolated git worktree")
@click.option("--report", "report_format", type=click.Choice(["json", "markdown", "github"]), default=None, help="Report format")
@click.option("--report-file", "report_file", type=click.Path(), default=None, help="Output file for the report")
@click.option("--quiet", is_flag=True, help="Quiet mode")
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
    """Run a Ralph Loop: iterate until checks pass.

    Each iteration uses an agent with CLEAN context. It only receives:
    the original task, accumulated diff, errors from the previous iteration,
    and accumulated progress.

    Examples:

        \b
        # Loop with test as check
        $ architect loop "implement login" --check "pytest tests/"

        \b
        # Loop with multiple checks
        $ architect loop "refactor auth" \\
            --check "ruff check src/" \\
            --check "pytest tests/ -q" \\
            --max-iterations 10

        \b
        # With spec file and budget
        $ architect loop "implement spec" --spec spec.md \\
            --check "pytest" --max-cost 1.0

        \b
        # In isolated worktree (does not modify working tree)
        $ architect loop "migrate DB" --check "pytest" --worktree
    """
    import os

    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
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
        """Create a fresh AgentLoop for each iteration.

        Accepts workspace_root to support isolated worktrees.
        When workspace_root is passed, the agent's tools operate
        in that directory instead of the original workspace.
        """
        iter_agent = kwargs.get("agent", agent)
        iter_model = kwargs.get("model", model)
        iter_workspace_root = kwargs.get("workspace_root")

        if not app_config:
            click.echo("Error: Configuration not available.", err=True)
            sys.exit(EXIT_CONFIG_ERROR)

        # If workspace_root was provided (worktree), use it instead of the original
        iter_workspace_config = app_config.workspace
        iter_app_config = app_config
        if iter_workspace_root and str(iter_workspace_root) != workspace:
            iter_workspace_config = app_config.workspace.model_copy(
                update={"root": Path(iter_workspace_root)}
            )
            iter_app_config = app_config.model_copy(
                update={"workspace": iter_workspace_config}
            )

        # Create fresh components for each iteration
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

        # Guardrails for loop iterations (v4-A2)
        iter_guardrails: GuardrailsEngine | None = None
        if iter_app_config.guardrails.enabled:
            ws_root = str(Path(iter_workspace_config.root).resolve())
            iter_guardrails = GuardrailsEngine(
                config=iter_app_config.guardrails,
                workspace_root=ws_root,
            )

        # v4-A1: Hooks for loop iterations
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
            f"max {max_iterations} iterations{wt_label}",
            err=True,
        )

    ralph = RalphLoop(ralph_config, agent_factory, workspace_root=workspace)
    result = ralph.run()

    # Summary
    if not quiet:
        click.echo(f"\n--- Ralph Loop {'Completed' if result.success else 'Finished'} ---", err=True)
        click.echo(f"Iterations: {result.total_iterations}", err=True)
        click.echo(f"Total cost: ${result.total_cost:.4f}", err=True)
        click.echo(f"Duration: {result.total_duration:.1f}s", err=True)
        click.echo(f"Reason: {result.stop_reason}", err=True)
        if result.worktree_path:
            click.echo(f"Worktree: {result.worktree_path}", err=True)
            click.echo(
                "  Inspect the changes and use 'git merge architect/ralph-loop' to integrate.",
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

    # v4-B2: Generate report if requested
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
            saved_path = _write_report_file(report_file, report_content)
            if saved_path and not quiet:
                click.echo(f"Report saved to {saved_path}", err=True)
        else:
            click.echo(report_content)

    sys.exit(EXIT_SUCCESS if result.success else EXIT_FAILED)


@main.command("parallel")
@click.argument("task", required=False)
@click.option("--task", "tasks", multiple=True, help="Task (repeatable for fan-out)")
@click.option("--workers", default=3, type=int, help="Number of workers (default: 3)")
@click.option("--models", help="Comma-separated models (e.g.: gpt-4o,claude-sonnet-4)")
@click.option("--agent", default="build", help="Agent to use")
@click.option("--budget-per-worker", type=float, help="Budget in USD per worker")
@click.option("--timeout-per-worker", type=int, help="Timeout in seconds per worker")
@click.option("-c", "--config", "config_path", type=click.Path(exists=True), default=None, help="Path to the YAML configuration file")
@click.option("--api-base", default=None, help="LLM API base URL")
@click.option("--quiet", is_flag=True, help="Quiet mode")
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
    """Run multiple agents in parallel with worktrees.

    Each worker runs in an isolated git worktree. Worktrees
    are preserved after execution for inspection.

    Examples:

        \b
        # Same task, 3 different models
        $ architect parallel "implement auth" \\
            --models gpt-4o,claude-sonnet-4,deepseek-chat

        \b
        # Fan-out with different tasks
        $ architect parallel \\
            --task "implement login" \\
            --task "implement registration" \\
            --task "implement logout" \\
            --workers 3
    """
    import os

    task_list = list(tasks) if tasks else ([task] if task else [])
    if not task_list:
        click.echo("Error: Specify a task as argument or with --task", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    model_list = models.split(",") if models else None
    workspace = os.getcwd()

    # Resolve config_path to absolute so it works from worktrees
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
            f"{len(task_list)} task(s)"
            + (f", models: {models}" if models else ""),
            err=True,
        )

    runner = ParallelRunner(config, workspace)
    results = runner.run()

    if not quiet:
        click.echo("\n--- Parallel Run Results ---", err=True)
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
            f"\nWorktrees preserved. Use 'architect parallel-cleanup' to clean up.",
            err=True,
        )

    any_success = any(r.status == "success" for r in results)
    sys.exit(EXIT_SUCCESS if any_success else EXIT_FAILED)


@main.command("parallel-cleanup")
def parallel_cleanup_cmd() -> None:
    """Clean up worktrees and branches from parallel executions."""
    import os

    workspace = os.getcwd()
    runner = ParallelRunner(
        ParallelConfig(tasks=[""]),
        workspace,
    )
    removed = runner.cleanup()
    click.echo(f"Worktrees cleaned up: {removed}")


@main.command("pipeline")
@click.argument("pipeline_file", type=click.Path(exists=True))
@click.option(
    "--var",
    "variables",
    multiple=True,
    help="Pipeline variable (format: name=value, repeatable)",
)
@click.option("--from-step", help="Start from a specific step")
@click.option("--dry-run", is_flag=True, help="Show plan without executing")
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to the YAML configuration file",
)
@click.option("--report", "report_format", type=click.Choice(["json", "markdown", "github"]), default=None, help="Report format")
@click.option("--report-file", "report_file", type=click.Path(), default=None, help="Output file for the report")
@click.option("--quiet", is_flag=True, help="Quiet mode")
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
    """Run a multi-step YAML workflow.

    The YAML file defines a sequence of steps, each with its own
    agent, prompt, and configuration.

    Examples:

        \b
        # Run complete pipeline
        $ architect pipeline workflow.yaml --var task="add auth"

        \b
        # Continue from a specific step
        $ architect pipeline workflow.yaml --from-step test

        \b
        # Dry-run to see the plan
        $ architect pipeline workflow.yaml --dry-run
    """
    import os

    try:
        app_config = load_config(config_path=config)
        _set_language(app_config.language)
    except Exception:
        app_config = None

    workspace = str(Path(app_config.workspace.root).resolve()) if app_config else os.getcwd()

    configure_logging(
        app_config.logging if app_config else None,
        quiet=quiet,
    )

    # Parse variables
    vars_dict: dict[str, str] = {}
    for v in variables:
        if "=" in v:
            key, val = v.split("=", 1)
            vars_dict[key.strip()] = val.strip()

    def agent_factory(**kwargs):
        """Create a fresh AgentLoop for each pipeline step."""
        iter_agent = kwargs.get("agent", "build")
        iter_model = kwargs.get("model")

        if not app_config:
            click.echo("Error: Configuration not available.", err=True)
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

        # Guardrails for pipeline steps (v4-A2)
        pipe_guardrails: GuardrailsEngine | None = None
        if app_config.guardrails.enabled:
            pipe_guardrails = GuardrailsEngine(
                config=app_config.guardrails,
                workspace_root=workspace,
            )

        # v4-A1: Hooks for pipeline steps
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

    try:
        runner = PipelineRunner.from_yaml(
            pipeline_file, vars_dict, agent_factory, workspace_root=workspace,
        )
    except PipelineValidationError as e:
        click.echo(f"Validation error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

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

    # v4-B2: Generate report if requested
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
            saved_path = _write_report_file(report_file, report_content)
            if saved_path and not quiet:
                click.echo(f"Report saved to {saved_path}", err=True)
        else:
            click.echo(report_content)

    sys.exit(EXIT_SUCCESS if all_ok else EXIT_FAILED)


@main.command("rollback")
@click.option("--to-step", type=int, help="Rollback to the checkpoint at this step")
@click.option("--to-commit", help="Rollback to a specific commit")
def rollback_cmd(to_step: int | None, to_commit: str | None) -> None:
    """Undo changes up to a checkpoint.

    Checkpoints are automatically created by architect during
    execution. Use 'architect history' to see available ones.

    Examples:

        \b
        # Rollback to step 3
        $ architect rollback --to-step 3

        \b
        # Rollback to a specific commit
        $ architect rollback --to-commit abc1234
    """
    import os

    if to_step is None and to_commit is None:
        click.echo("Error: Specify --to-step or --to-commit", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    mgr = CheckpointManager(os.getcwd())

    if mgr.rollback(step=to_step, commit=to_commit):
        target = f"step {to_step}" if to_step is not None else to_commit
        click.echo(f"Rollback successful to {target}")
    else:
        click.echo("Error: Could not perform rollback.", err=True)
        sys.exit(EXIT_FAILED)


@main.command("history")
def history_cmd() -> None:
    """Show architect checkpoint history.

    Lists all git commits with the 'architect:checkpoint' prefix
    created during agent executions.
    """
    import os
    from datetime import datetime

    mgr = CheckpointManager(os.getcwd())
    checkpoints = mgr.list_checkpoints()

    if not checkpoints:
        click.echo("No checkpoints recorded.")
        return

    click.echo(f"Checkpoints ({len(checkpoints)}):\n")
    click.echo(f"  {'Step':<6s} {'Hash':<9s} {'Date':<20s} Message")
    click.echo(f"  {'─'*6} {'─'*9} {'─'*20} {'─'*30}")
    for cp in checkpoints:
        date_str = datetime.fromtimestamp(cp.timestamp).strftime("%Y-%m-%d %H:%M:%S") if cp.timestamp else "-"
        click.echo(
            f"  {cp.step:<6d} {cp.short_hash():<9s} {date_str:<20s} {cp.message or '-'}"
        )

    click.echo(f"\nUse 'architect rollback --to-step N' to restore.")


# ── v4-D3: COMPETITIVE EVAL ────────────────────────────────────────────


@main.command("eval")
@click.argument("task")
@click.option(
    "--models", required=True,
    help="Comma-separated models (e.g.: gpt-4o,claude-sonnet-4-20250514,gemini-2.0-flash)",
)
@click.option("--check", "checks", multiple=True, help="Verification command (repeatable)")
@click.option("--agent", default="build", help="Agent to use for each model")
@click.option("--max-steps", default=50, type=int, help="Maximum steps per model")
@click.option("--budget-per-model", type=float, help="Budget in USD per model")
@click.option("--timeout-per-model", type=int, help="Timeout in seconds per model")
@click.option(
    "--report-file", type=click.Path(),
    help="File to save the markdown report",
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
    """Competitive evaluation: run the same task with multiple models.

    Compares the results of different LLM models executing the same task
    in isolated git worktrees. Generates a report with ranking and metrics.

    Example:

        architect eval "Implement JWT auth" --models gpt-4o,claude-sonnet-4-20250514 --check "pytest tests/"
    """
    import os

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if len(model_list) < 2:
        click.echo("Error: At least 2 models are required for comparison.", err=True)
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

    click.echo(f"Competitive evaluation: {len(model_list)} models")
    click.echo(f"  Models: {', '.join(model_list)}")
    click.echo(f"  Task: {task[:80]}...")
    if checks:
        click.echo(f"  Checks: {', '.join(checks)}")
    click.echo()

    evaluator = CompetitiveEval(config, os.getcwd())
    results = evaluator.run()

    # Generate and display report
    report = evaluator.generate_report(results)

    if report_file:
        saved_path = _write_report_file(report_file, report)
        if saved_path:
            click.echo(f"\nReport saved to: {saved_path}")
    else:
        click.echo(report)

    # Exit code: 0 if at least one model succeeded
    any_success = any(r.status == "success" for r in results)
    sys.exit(EXIT_SUCCESS if any_success else EXIT_FAILED)


# ── v4-D5: PRESET CONFIGS ─────────────────────────────────────────────


@main.command("init")
@click.option(
    "--preset",
    type=click.Choice(sorted(AVAILABLE_PRESETS)),
    required=True,
    help="Configuration preset to apply",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing files")
@click.option("--list-presets", "show_list", is_flag=True, help="List available presets")
def init_cmd(preset: str | None, overwrite: bool, show_list: bool) -> None:
    """Initialize architect configuration in the project.

    Creates .architect.md and config.yaml files with predefined
    configurations based on the tech stack or security profile.

    Example:

        architect init --preset python
    """
    import os

    manager = PresetManager(os.getcwd())

    if show_list:
        presets = manager.list_presets()
        click.echo("Available presets:\n")
        for p in presets:
            click.echo(f"  {p['name']:<15s} {p['description']}")
        return

    if not preset:
        click.echo("Error: Specify a preset with --preset", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        files = manager.apply_preset(preset, overwrite=overwrite)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)

    if files:
        click.echo(f"Preset '{preset}' applied. Files created:")
        for f in files:
            click.echo(f"  + {f}")
    else:
        click.echo(f"Preset '{preset}': all files already exist (use --overwrite to replace).")

    click.echo(f"\n.architect/ directory created.")
    click.echo(f"Edit .architect.md to customize the agent instructions.")


# ── HELPER FUNCTIONS (v4-B3) ────────────────────────────────────────────


def _get_git_diff_context(ref: str) -> str | None:
    """Get the git diff and format it as context for the agent.

    Args:
        ref: Git reference to compare against (e.g.: origin/main).

    Returns:
        String with the formatted diff, or None if it fails.
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

        # Truncate if too long
        if len(diff) > 50000:
            diff = diff[:50000] + "\n... (diff truncated)"

        return (
            f"## Changes in this branch (vs {ref})\n\n"
            f"### Summary\n```\n{stat}\n```\n\n"
            f"### Full diff\n```diff\n{diff}\n```"
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _build_hooks_registry(config) -> HooksRegistry:
    """Build a HooksRegistry from the configuration (v4-A1).

    Maps the HookItemConfig lists from the hooks section of the YAML config
    to a HooksRegistry with HookConfig for each HookEvent.
    Also migrates post_edit (v3-M4 compat) to post_tool_use with edit tools matcher.

    Args:
        config: AppConfig with the hooks section.

    Returns:
        HooksRegistry ready to use with HookExecutor.
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

    # Backward compat: post_edit -> post_tool_use with edit tools matcher
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
