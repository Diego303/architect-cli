"""
Pydantic models for architect configuration.

Defines all configuration schemas using Pydantic v2 for validation,
defaults, and serialization.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = "litellm"
    mode: Literal["proxy", "direct"] = "direct"
    model: str = "gpt-4o"
    api_base: str | None = None
    api_key_env: str = "LITELLM_API_KEY"
    timeout: int = 60
    retries: int = 2
    stream: bool = True
    prompt_caching: bool = Field(
        default=False,
        description=(
            "If True, marks the system prompt with cache_control so the provider "
            "(Anthropic, OpenAI) caches it. Reduces cost 50-90% on repeated calls."
        ),
    )

    model_config = {"extra": "forbid"}


class AgentConfig(BaseModel):
    """Configuration for a specific agent."""

    system_prompt: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    confirm_mode: Literal["confirm-all", "confirm-sensitive", "yolo"] = "confirm-sensitive"
    max_steps: int = 20

    model_config = {"extra": "forbid"}


class HookItemConfig(BaseModel):
    """Configuration for an individual hook (v4-A1).

    A hook is a shell command executed at points in the agent lifecycle.
    It receives context via env vars (ARCHITECT_EVENT, ARCHITECT_TOOL_NAME, etc.) and stdin JSON.

    Protocol:
    - Exit 0 = ALLOW (JSON on stdout for additional context or input modification)
    - Exit 2 = BLOCK (stderr = reason for blocking, only for pre-hooks)
    - Other  = Error (warning logged, does not block)
    """

    name: str = Field(default="", description="Descriptive name of the hook")
    command: str = Field(description="Shell command to execute")
    matcher: str = Field(
        default="*",
        description="Regex/glob of tool name to filter (only for tool hooks). '*' = all.",
    )
    file_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns of files that trigger the hook (e.g.: ['*.py', '*.ts'])",
    )
    timeout: int = Field(default=10, ge=1, le=300, description="Timeout in seconds")
    async_: bool = Field(
        default=False,
        alias="async",
        description="If True, execute in background without blocking",
    )
    enabled: bool = Field(default=True, description="If False, the hook is ignored")

    model_config = {"extra": "forbid", "populate_by_name": True}


# Backward-compat alias for v3-M4 code that references HookConfig
HookConfig = HookItemConfig


class HooksConfig(BaseModel):
    """Hook system configuration (v4-A1).

    Organizes hooks by lifecycle event. Each event has a list of hooks
    that execute in order. The post_edit hooks are an alias for
    post_tool_use for backward compatibility with v3-M4.
    """

    pre_tool_use: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed BEFORE each tool call",
    )
    post_tool_use: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed AFTER each tool call",
    )
    pre_llm_call: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed BEFORE each LLM call",
    )
    post_llm_call: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed AFTER each LLM call",
    )
    session_start: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed at session start",
    )
    session_end: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed at session end",
    )
    on_error: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed when a tool fails",
    )
    agent_complete: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed when the agent declares completion",
    )
    budget_warning: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed when budget percentage is exceeded",
    )
    context_compress: list[HookItemConfig] = Field(
        default_factory=list,
        description="Hooks executed before context compression",
    )
    # Backward compat: post_edit maps to post_tool_use with edit-tool matcher
    post_edit: list[HookItemConfig] = Field(
        default_factory=list,
        description="(Compat v3) Post-edit hooks. Added to post_tool_use with matcher 'write_file|edit_file|apply_patch'.",
    )

    model_config = {"extra": "forbid"}


class LoggingConfig(BaseModel):
    """Logging system configuration."""

    # v3: added "human" as agent traceability level
    level: Literal["debug", "info", "human", "warn", "error"] = "human"
    file: Path | None = None
    verbose: int = 0

    model_config = {"extra": "forbid"}


class WorkspaceConfig(BaseModel):
    """Workspace (working directory) configuration."""

    root: Path = Path(".")
    allow_delete: bool = False

    model_config = {"extra": "forbid"}


class MCPServerConfig(BaseModel):
    """Configuration for an individual MCP server."""

    name: str
    url: str
    token_env: str | None = None
    token: str | None = None

    model_config = {"extra": "forbid"}


class MCPConfig(BaseModel):
    """Global MCP configuration."""

    servers: list[MCPServerConfig] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class IndexerConfig(BaseModel):
    """Repository indexer configuration (F10).

    The indexer builds a lightweight tree of the workspace at startup
    and injects it into the agent's system prompt. This allows the
    agent to know the project structure without reading each file.
    """

    enabled: bool = True
    """If False, the indexer does not run and the agent does not receive the tree."""

    max_file_size: int = Field(
        default=1_000_000,
        description="Maximum file size to index in bytes (default: 1MB)",
    )

    exclude_dirs: list[str] = Field(
        default_factory=list,
        description=(
            "Additional directories to exclude (besides defaults: "
            ".git, node_modules, __pycache__, .venv, etc.)"
        ),
    )

    exclude_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Additional file patterns to exclude (besides defaults: "
            "*.pyc, *.min.js, *.map, etc.)"
        ),
    )

    use_cache: bool = Field(
        default=True,
        description=(
            "If True, caches the index on disk for 5 minutes to "
            "avoid rebuilding it on each call."
        ),
    )

    model_config = {"extra": "forbid"}


class ContextConfig(BaseModel):
    """Context window manager configuration (F11).

    Controls the behavior of the ContextManager, which prevents the LLM
    context from filling up during long tasks. It operates at three levels:
    - Level 1: Truncate very long tool results (always active if enabled)
    - Level 2: Summarize old steps with the LLM itself when there are many steps
    - Level 3: Sliding window with hard limit on total tokens
    """

    max_tool_result_tokens: int = Field(
        default=2000,
        description=(
            "Maximum tokens per tool result before truncating (~4 chars/token). "
            "0 = no truncation."
        ),
    )

    summarize_after_steps: int = Field(
        default=8,
        description=(
            "Number of tool call exchanges (steps with tool calls) before "
            "attempting to compress old messages. 0 = disable summarization."
        ),
    )

    keep_recent_steps: int = Field(
        default=4,
        description="Recent complete steps to preserve during compression.",
    )

    max_context_tokens: int = Field(
        default=80000,
        description=(
            "Hard limit of total estimated context window in tokens (~4 chars/token). "
            "0 = no limit."
        ),
    )

    parallel_tools: bool = Field(
        default=True,
        description=(
            "Execute independent tool calls in parallel using ThreadPoolExecutor. "
            "Only applies when there are >1 tool calls and none require confirmation."
        ),
    )

    model_config = {"extra": "forbid"}


class EvaluationConfig(BaseModel):
    """Self-evaluation configuration (F12).

    Controls whether the agent automatically evaluates its own result
    upon completion. Disabled by default to avoid consuming extra tokens.

    Available modes:
    - ``"off"``   -- No evaluation (default)
    - ``"basic"`` -- Asks the LLM if the task was completed; if not, marks as ``partial``
    - ``"full"``  -- Evaluation + up to ``max_retries`` automatic correction retries
    """

    mode: Literal["off", "basic", "full"] = "off"

    @field_validator("mode", mode="before")
    @classmethod
    def _coerce_yaml_bool(cls, v: object) -> object:
        """YAML 1.1 parses `off` without quotes as False (bool). Convert it to 'off'."""
        if v is False:
            return "off"
        return v

    max_retries: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum number of retries in 'full' mode.",
    )

    confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum confidence threshold to consider the task completed in 'full' mode. "
            "If the LLM evaluates confidence < threshold, it retries."
        ),
    )

    model_config = {"extra": "forbid"}


class CostsConfig(BaseModel):
    """Cost tracking configuration (F14).

    Controls whether LLM call costs are tracked and whether a budget
    limit per execution is applied.
    """

    enabled: bool = Field(
        default=True,
        description="If True, costs of each LLM call are tracked.",
    )

    prices_file: Path | None = Field(
        default=None,
        description=(
            "Path to a JSON file with custom prices that override the defaults. "
            "Same format as default_prices.json."
        ),
    )

    budget_usd: float | None = Field(
        default=None,
        description=(
            "Spending limit in USD per execution. If exceeded, the agent stops "
            "with status 'partial'. None = no limit."
        ),
    )

    warn_at_usd: float | None = Field(
        default=None,
        description=(
            "Warning threshold in USD. When accumulated spending exceeds this value "
            "a log warning is emitted (without stopping execution)."
        ),
    )

    model_config = {"extra": "forbid"}


class LLMCacheConfig(BaseModel):
    """Local LLM response cache configuration (F14).

    The local cache is deterministic: it stores complete responses on disk
    to avoid repeated LLM calls. Useful in development to save tokens.

    WARNING: For development only. Do not use in production (cached responses
    may become stale if the context changes).
    """

    enabled: bool = Field(
        default=False,
        description="If True, enables the local LLM response cache.",
    )

    dir: Path = Field(
        default=Path("~/.architect/cache"),
        description="Directory to store cache entries.",
    )

    ttl_hours: int = Field(
        default=24,
        ge=1,
        le=8760,  # 1 year
        description="Hours of validity for each cache entry. After that it is considered expired.",
    )

    model_config = {"extra": "forbid"}


class CommandsConfig(BaseModel):
    """run_command tool configuration (F13).

    Controls whether the agent can execute system commands and what security
    restrictions are applied. The tool includes four integrated security layers:
    pattern blocking, dynamic classification, timeouts, and cwd sandboxing.
    """

    enabled: bool = Field(
        default=True,
        description="If False, the run_command tool is not registered and the agent cannot execute commands.",
    )

    default_timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Default timeout in seconds for run_command if no explicit timeout is specified.",
    )

    max_output_lines: int = Field(
        default=200,
        ge=10,
        le=5000,
        description="Maximum stdout/stderr lines before truncating to avoid filling the context.",
    )

    blocked_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Additional regex patterns to block (besides built-in: "
            "rm -rf /, sudo, chmod 777, curl|bash, etc.)."
        ),
    )

    safe_commands: list[str] = Field(
        default_factory=list,
        description=(
            "Additional commands considered safe (no confirmation required). "
            "Added to the built-in: ls, cat, git status, etc."
        ),
    )

    allowed_only: bool = Field(
        default=False,
        description=(
            "If True, only commands classified as 'safe' or 'dev' are allowed. "
            "'dangerous' commands are rejected in execute(), not just at confirmation."
        ),
    )

    model_config = {"extra": "forbid"}


class QualityGateConfig(BaseModel):
    """Configuration for an individual quality gate (v4-A2).

    Quality gates are executed when the agent declares completion.
    If a required gate fails, the agent receives feedback and continues.
    """

    name: str = Field(description="Name of the quality gate (e.g.: 'lint', 'tests')")
    command: str = Field(description="Shell command to execute")
    required: bool = Field(
        default=True,
        description="If True, the agent cannot finish without passing it",
    )
    timeout: int = Field(default=60, ge=1, le=600, description="Timeout in seconds")

    model_config = {"extra": "forbid"}


class CodeRuleConfig(BaseModel):
    """Configuration for a code rule (v4-A2).

    Code rules scan content written by the agent
    with regex to detect forbidden patterns.
    """

    pattern: str = Field(description="Regex to search for in written code")
    message: str = Field(description="Message to the LLM when the pattern is detected")
    severity: Literal["warn", "block"] = Field(
        default="warn",
        description="'warn' attaches a warning, 'block' prevents the write",
    )

    model_config = {"extra": "forbid"}


class GuardrailsConfig(BaseModel):
    """Security guardrails configuration (v4-A2).

    Guardrails are DETERMINISTIC rules evaluated BEFORE hooks
    and cannot be disabled by the LLM. They are the base security layer.
    """

    enabled: bool = Field(
        default=False,
        description="If True, enables the guardrails system",
    )
    protected_files: list[str] = Field(
        default_factory=list,
        description="Glob patterns of files protected against writing (e.g.: ['.env', '*.pem', '*.key'])",
    )
    sensitive_files: list[str] = Field(
        default_factory=list,
        description=(
            "Glob patterns of sensitive files -- blocks READING and WRITING "
            "(e.g.: ['.env', '*.pem', 'secrets/*']). "
            "Unlike protected_files (write-only), sensitive_files "
            "also prevents reading the content."
        ),
    )
    blocked_commands: list[str] = Field(
        default_factory=list,
        description="Regex patterns of blocked commands (e.g.: ['rm\\s+-[rf]+\\s+/'])",
    )
    max_files_modified: int | None = Field(
        default=None,
        description="Maximum files the agent can modify. None = no limit.",
    )
    max_lines_changed: int | None = Field(
        default=None,
        description="Maximum lines changed. None = no limit.",
    )
    max_commands_executed: int | None = Field(
        default=None,
        description="Maximum commands the agent can execute. None = no limit.",
    )
    require_test_after_edit: bool = Field(
        default=False,
        description="If True, forces the agent to run tests after editing.",
    )
    quality_gates: list[QualityGateConfig] = Field(
        default_factory=list,
        description="Quality gates executed when the agent declares completion.",
    )
    code_rules: list[CodeRuleConfig] = Field(
        default_factory=list,
        description="Regex rules that scan content written by the agent.",
    )

    model_config = {"extra": "forbid"}

    def model_post_init(self, __context: Any) -> None:
        """Auto-enable guardrails when any rule is configured."""
        if not self.enabled:
            has_rules = (
                bool(self.protected_files)
                or bool(self.sensitive_files)
                or bool(self.blocked_commands)
                or self.max_files_modified is not None
                or self.max_lines_changed is not None
                or self.max_commands_executed is not None
                or self.require_test_after_edit
                or bool(self.quality_gates)
                or bool(self.code_rules)
            )
            if has_rules:
                object.__setattr__(self, "enabled", True)


class MemoryConfig(BaseModel):
    """Procedural memory configuration (v4-A4)."""

    enabled: bool = Field(
        default=False,
        description="If True, enables procedural memory.",
    )
    auto_detect_corrections: bool = Field(
        default=True,
        description="If True, automatically detects corrections in user messages.",
    )

    model_config = {"extra": "forbid"}


class SkillsConfig(BaseModel):
    """Skills ecosystem configuration (v4-A3)."""

    auto_discover: bool = Field(
        default=True,
        description="If True, automatically discovers skills in .architect/skills/",
    )
    inject_by_glob: bool = Field(
        default=True,
        description="If True, injects relevant skills based on active file globs.",
    )

    model_config = {"extra": "forbid"}


class SessionsConfig(BaseModel):
    """Session persistence configuration (v4-B1).

    Controls whether the agent automatically saves the state of each session
    so it can be resumed after an interruption.
    """

    auto_save: bool = Field(
        default=True,
        description="If True, saves state after each step automatically.",
    )
    cleanup_after_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Days after which sessions are automatically cleaned up.",
    )

    model_config = {"extra": "forbid"}


# -- Phase C Config Schemas -----------------------------------------------


class RalphLoopConfig(BaseModel):
    """Native Ralph Loop configuration (v4-C1).

    The Ralph Loop runs agent iterations until all checks pass.
    Each iteration uses an agent with CLEAN context.
    """

    max_iterations: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum number of loop iterations.",
    )
    max_cost: float | None = Field(
        default=None,
        description="Maximum total cost in USD. None = no limit.",
    )
    max_time: int | None = Field(
        default=None,
        ge=1,
        description="Maximum total time in seconds. None = no limit.",
    )
    completion_tag: str = Field(
        default="COMPLETE",
        description="Tag the agent emits when it declares completion.",
    )
    agent: str = Field(
        default="build",
        description="Agent to use in each iteration.",
    )

    model_config = {"extra": "forbid"}


class ParallelRunsConfig(BaseModel):
    """Parallel execution with worktrees configuration (v4-C2).

    Runs multiple agents in parallel, each in a separate git worktree
    for total isolation.
    """

    workers: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of parallel workers.",
    )
    agent: str = Field(
        default="build",
        description="Agent to use in each worker.",
    )
    max_steps: int = Field(
        default=50,
        ge=1,
        description="Maximum steps per worker.",
    )
    budget_per_worker: float | None = Field(
        default=None,
        description="Budget in USD per worker. None = no limit.",
    )
    timeout_per_worker: int | None = Field(
        default=None,
        ge=1,
        description="Timeout in seconds per worker. None = 600s.",
    )

    model_config = {"extra": "forbid"}


class CheckpointsConfig(BaseModel):
    """Checkpoints and rollback configuration (v4-C4).

    Checkpoints are git commits with a special prefix that allow
    restoring the workspace state to a previous point.
    """

    enabled: bool = Field(
        default=False,
        description="If True, enables automatic checkpoints.",
    )
    every_n_steps: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Create a checkpoint every N agent steps.",
    )

    model_config = {"extra": "forbid"}


class AutoReviewConfig(BaseModel):
    """Auto-review writer/reviewer configuration (v4-C5).

    When active, upon completing a task the reviewer agent inspects
    the changes and, if problems are found, the builder performs
    a fix-pass.
    """

    enabled: bool = Field(
        default=False,
        description="If True, enables auto-review after completion.",
    )
    review_model: str | None = Field(
        default=None,
        description="LLM model for the reviewer. None = uses the same as the builder.",
    )
    max_fix_passes: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Maximum fix-passes after review. 0 = report only.",
    )

    model_config = {"extra": "forbid"}


# -- Phase D Config Schemas -----------------------------------------------


class TelemetryConfig(BaseModel):
    """OpenTelemetry configuration (v4-D4).

    When enabled, emits distributed traces for sessions, LLM calls,
    and tool executions. Requires optional dependencies:
    opentelemetry-api, opentelemetry-sdk.
    """

    enabled: bool = Field(
        default=False,
        description="If True, enables OpenTelemetry trace emission.",
    )
    exporter: Literal["otlp", "console", "json-file"] = Field(
        default="console",
        description="Exporter type: otlp (gRPC), console (stderr), json-file.",
    )
    endpoint: str = Field(
        default="http://localhost:4317",
        description="Endpoint for the OTLP exporter.",
    )
    trace_file: str | None = Field(
        default=None,
        description="File path for the json-file exporter.",
    )

    model_config = {"extra": "forbid"}


class HealthConfig(BaseModel):
    """Code Health Delta configuration (v4-D2).

    When enabled, analyzes code health metrics before and after the
    agent session, generating a delta report. Requires optional
    dependency: radon (for cyclomatic complexity).
    """

    enabled: bool = Field(
        default=False,
        description="If True, runs health analysis before/after the session.",
    )
    include_patterns: list[str] = Field(
        default_factory=lambda: ["**/*.py"],
        description="Glob patterns of files to analyze.",
    )
    exclude_dirs: list[str] = Field(
        default_factory=list,
        description="Additional directories to exclude from analysis.",
    )

    model_config = {"extra": "forbid"}


class AppConfig(BaseModel):
    """Complete application configuration.

    This is the root of the configuration tree. It combines all sections
    and is the entry point for validation.
    """

    language: Literal["en", "es"] = "en"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    llm_cache: LLMCacheConfig = Field(default_factory=LLMCacheConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)  # v4-A2
    memory: MemoryConfig = Field(default_factory=MemoryConfig)  # v4-A4
    skills: SkillsConfig = Field(default_factory=SkillsConfig)  # v4-A3
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)  # v4-B1
    ralph: RalphLoopConfig = Field(default_factory=RalphLoopConfig)  # v4-C1
    parallel: ParallelRunsConfig = Field(default_factory=ParallelRunsConfig)  # v4-C2
    checkpoints: CheckpointsConfig = Field(default_factory=CheckpointsConfig)  # v4-C4
    auto_review: AutoReviewConfig = Field(default_factory=AutoReviewConfig)  # v4-C5
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)  # v4-D4
    health: HealthConfig = Field(default_factory=HealthConfig)  # v4-D2

    model_config = {"extra": "forbid"}
