# architect

Headless, agentic CLI tool for orchestrating AI agents over local files and remote MCP services. Designed to run unattended in CI, cron jobs, and pipelines.

---

## Installation

**Requirements**: Python 3.12+

```bash
# Install from PyPI
pip install architect-ai-cli

# From the repository
git clone https://github.com/Diego303/architect-cli
cd architect-cli
pip install -e .

# Verify installation
architect --version
architect run --help
```

**Optional extras:**

```bash
pip install architect-ai-cli[dev]        # pytest, black, ruff, mypy
pip install architect-ai-cli[telemetry]  # OpenTelemetry (OTLP traces)
pip install architect-ai-cli[health]     # radon (cyclomatic complexity)
```

**Main dependencies**: `litellm`, `click`, `pydantic`, `httpx`, `structlog`, `tenacity`

---

## Quickstart

```bash
# Set API key
export LITELLM_API_KEY="sk-..."

# Analyze a project (read-only, safe)
architect run "summarize what this project does" -a resume

# Review code
architect run "review main.py and find issues" -a review

# Generate a detailed plan (without modifying files)
architect run "plan how to add tests to the project" -a plan

# Modify files — build plans and executes in a single step
architect run "add docstrings to all functions in utils.py"

# Run without confirmations (CI/automation)
architect run "generate a README.md file for this project" --mode yolo

# See what it would do without executing anything
architect run "reorganize the folder structure" --dry-run

# Limit total execution time
architect run "refactor the auth module" --timeout 300
```

---

## Commands

### `architect run` — execute task

```
architect run PROMPT [options]
```

**Argument**:
- `PROMPT` — Task description in natural language

**Main options**:

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | YAML configuration file |
| `-a, --agent NAME` | Agent to use: `plan`, `build`, `resume`, `review`, or custom |
| `-m, --mode MODE` | Confirmation mode: `confirm-all`, `confirm-sensitive`, `yolo` |
| `-w, --workspace PATH` | Working directory (workspace root) |
| `--dry-run` | Simulate execution without real changes |

**LLM options**:

| Option | Description |
|--------|-------------|
| `--model MODEL` | Model to use (`gpt-4o`, `claude-sonnet-4-6`, etc.) |
| `--api-base URL` | API base URL |
| `--api-key KEY` | Direct API key |
| `--no-stream` | Disable streaming |
| `--timeout N` | Maximum total execution time in seconds (global watchdog) |

**Output and reports options**:

| Option | Description |
|--------|-------------|
| `-v / -vv / -vvv` | Technical verbose level (without `-v` only agent steps are shown) |
| `--log-level LEVEL` | Log level: `human` (default), `debug`, `info`, `warn`, `error` |
| `--log-file PATH` | Save structured JSON logs to file |
| `--json` | JSON output format (compatible with `jq`) |
| `--quiet` | Silent mode (only final result to stdout) |
| `--max-steps N` | Maximum agent steps limit |
| `--budget N` | Cost limit in USD (stops the agent if exceeded) |
| `--report FORMAT` | Generate execution report: `json`, `markdown`, `github` |
| `--report-file PATH` | Save report to file (format inferred from extension: `.json`, `.md`, `.html`) |

**Session and CI/CD options**:

| Option | Description |
|--------|-------------|
| `--session ID` | Resume a previously saved session |
| `--confirm-mode MODE` | CI-friendly alias: `yolo`, `confirm-sensitive`, `confirm-all` |
| `--context-git-diff REF` | Inject `git diff REF` as context (e.g., `origin/main`) |
| `--exit-code-on-partial N` | Custom exit code for `partial` status (default: 2) |

**Analysis and evaluation options**:

| Option | Description |
|--------|-------------|
| `--self-eval off\|basic\|full` | Result self-evaluation: `off` (no extra cost), `basic` (one extra call, marks as `partial` if fails), `full` (retries with correction prompt up to `max_retries` times) |
| `--health` | Run code health analysis before/after — shows complexity delta, long functions, and duplicates |

**MCP options**:

| Option | Description |
|--------|-------------|
| `--disable-mcp` | Disable connection to MCP servers |

---

### `architect sessions` — list saved sessions

```bash
architect sessions
```

Shows a table with all saved sessions: ID, status, steps, cost, and task.

---

### `architect resume` — resume session

```bash
architect resume SESSION_ID [options]
```

Resumes an interrupted session. Loads the complete state (messages, modified files, accumulated cost) and continues where it left off. If the ID doesn't exist, exits with code 3.

---

### `architect cleanup` — clean old sessions

```bash
architect cleanup                  # removes sessions > 7 days
architect cleanup --older-than 30  # removes sessions > 30 days
```

---

### `architect loop` — automatic iteration (Ralph Loop)

```
architect loop PROMPT --check CMD [options]
```

Runs an agent in a loop until all checks (shell commands) pass. Each iteration receives a clean context: only the original spec, accumulated diff, errors from the previous iteration, and an auto-generated progress.md.

```bash
# Loop until tests and lint pass
architect loop "implement feature X" \
  --check "pytest tests/" \
  --check "ruff check src/" \
  --max-iterations 10 \
  --max-cost 5.0

# With spec file and isolated worktree
architect loop "refactor the auth module" \
  --spec spec.md \
  --check "pytest" \
  --worktree \
  --model gpt-4o
```

| Option | Description |
|--------|-------------|
| `--check CMD` | Verification command (repeatable, required) |
| `--spec PATH` | Specification file (used instead of prompt) |
| `--max-iterations N` | Maximum iterations (default: 25) |
| `--max-cost N` | Cost limit in USD |
| `--max-time N` | Time limit in seconds |
| `--completion-tag TAG` | Tag the agent emits when done (default: `COMPLETE`) |
| `--agent NAME` | Agent to use (default: `build`) |
| `--model MODEL` | LLM model |
| `--worktree` | Run in an isolated git worktree |
| `--quiet` | Only final result |

---

### `architect pipeline` — run YAML workflow

```
architect pipeline FILE [options]
```

Runs a multi-step workflow defined in YAML. Each step can have its own agent, model, checks, conditions, and variables. The YAML is validated before execution — unknown fields, missing `prompt`, and invalid step formats are rejected with clear error messages.

```bash
# Run pipeline
architect pipeline ci/pipeline.yaml --var project=myapp --var env=staging

# Preview plan without executing
architect pipeline ci/pipeline.yaml --dry-run

# Resume from a step
architect pipeline ci/pipeline.yaml --from-step deploy
```

| Option | Description |
|--------|-------------|
| `--var KEY=VALUE` | Pipeline variable (repeatable) |
| `--from-step NAME` | Resume from a specific step |
| `--dry-run` | Show plan without executing |
| `-c, --config PATH` | YAML configuration file |
| `--quiet` | Only final result |

**Pipeline YAML format**:

```yaml
name: my-pipeline
steps:
  - name: analyze
    agent: plan
    prompt: "Analyze project {{project}} in {{env}} environment"
    output_var: analysis

  - name: implement
    agent: build
    prompt: "Implement: {{analysis}}"
    model: gpt-4o
    checks:
      - "pytest tests/"
      - "ruff check src/"
    checkpoint: true

  - name: deploy
    agent: build
    prompt: "Deploy to {{env}}"
    condition: "env == 'production'"
```

---

### `architect parallel` — parallel execution

```
architect parallel --task CMD [options]
```

Runs multiple tasks in parallel, each in an isolated git worktree.

```bash
# Three tasks in parallel
architect parallel \
  --task "add tests to auth.py" \
  --task "add tests to users.py" \
  --task "add tests to billing.py" \
  --workers 3

# With different models per worker
architect parallel \
  --task "optimize queries" \
  --task "improve logging" \
  --models gpt-4o,claude-sonnet-4-6
```

| Option | Description |
|--------|-------------|
| `--task CMD` | Task to execute (repeatable) |
| `--workers N` | Number of parallel workers (default: 3) |
| `--models LIST` | Comma-separated models (round-robin across workers) |
| `--agent NAME` | Agent to use (default: `build`) |
| `--budget-per-worker N` | Cost limit per worker |
| `--timeout-per-worker N` | Time limit per worker |
| `--config PATH` | YAML configuration file for workers |
| `--api-base URL` | LLM API base URL for workers |
| `--quiet` | Only final result |

```bash
# With custom config and API
architect parallel \
  --task "optimize queries" \
  --config ci/architect.yaml \
  --api-base http://proxy.internal:8000

# Clean up worktrees after execution
architect parallel-cleanup
```

---

### `architect eval` — competitive multi-model evaluation

```
architect eval PROMPT [options]
```

Runs the same task with multiple models in parallel and generates a comparative ranking. Each model runs in an isolated git worktree with the same validation checks.

```bash
# Compare three models
architect eval "implement JWT authentication" \
  --models gpt-4o,claude-sonnet-4-6,gemini-2.0-flash \
  --check "pytest tests/test_auth.py -q" \
  --check "ruff check src/" \
  --budget-per-model 1.0 \
  --report-file eval_report.md

# With timeout and custom agent
architect eval "refactor utils.py" \
  --models gpt-4o,claude-sonnet-4-6 \
  --check "pytest" \
  --timeout-per-model 300 \
  --agent build \
  --max-steps 30
```

| Option | Description |
|--------|-------------|
| `--models LIST` | Comma-separated models (required) |
| `--check CMD` | Verification command (repeatable, required) |
| `--agent NAME` | Agent to use (default: `build`) |
| `--max-steps N` | Maximum steps per model (default: 50) |
| `--budget-per-model N` | Cost limit per model in USD |
| `--timeout-per-model N` | Time limit per model in seconds |
| `--report-file PATH` | Save report to file |
| `--config PATH` | YAML configuration file |
| `--api-base URL` | LLM API base URL |

**Scoring system** (100 points):
- Checks passed: 40 pts (proportional)
- Status: 30 pts (success=30, partial=15, timeout=5, failed=0)
- Efficiency: 20 pts (fewer steps = higher score)
- Cost: 10 pts (lower cost = higher score)

---

### `architect init` — initialize project with presets

```
architect init [options]
```

Generates initial configuration (`.architect.md` + `config.yaml`) from predefined presets.

```bash
# View available presets
architect init --list-presets

# Initialize Python project
architect init --preset python

# Maximum security mode (overwrite if exists)
architect init --preset paranoid --overwrite
```

| Option | Description |
|--------|-------------|
| `--preset NAME` | Preset to apply: `python`, `node-react`, `ci`, `paranoid`, `yolo` |
| `--list-presets` | Show available presets |
| `--overwrite` | Overwrite existing files |

**Available presets**:

| Preset | Description |
|--------|-------------|
| `python` | Standard Python project — pytest, ruff, mypy, black, PEP 8, type hints |
| `node-react` | Node.js/React project — TypeScript strict, ESLint, Prettier, Jest/Vitest |
| `ci` | Headless CI/CD mode — yolo, no streaming, autonomous |
| `paranoid` | Maximum security — confirm-all, strict guardrails, code rules, max 20 steps |
| `yolo` | No restrictions — yolo, 100 steps, no guardrails |

---

### `architect agents` — list agents

```bash
architect agents                   # default agents
architect agents -c config.yaml   # includes custom from YAML
```

Lists all available agents with their confirmation mode.

---

### `architect validate-config` — validate configuration

```bash
architect validate-config -c config.yaml
```

Validates the syntax and values of the configuration file before execution.

---

## Agents

An agent defines the **role**, **available tools**, and **confirmation level**.

The default agent is **`build`** (used automatically if `-a` is not specified): it analyzes the project, creates an internal plan, and executes it in a single step, without needing a prior `plan` agent.

| Agent | Description | Tools | Confirmation | Steps |
|-------|-------------|-------|-------------|-------|
| `build` | Plans and executes modifications | all (editing, search, read, `run_command`, `dispatch_subagent`) | `confirm-sensitive` | 50 |
| `plan` | Analyzes and generates a detailed plan | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 20 |
| `resume` | Reads and summarizes information | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 15 |
| `review` | Code review and improvements | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | `yolo` | 20 |

**Custom agents** in `config.yaml`:

```yaml
agents:
  deploy:
    system_prompt: |
      You are a deployment agent...
    allowed_tools:
      - read_file
      - list_files
      - run_command
    confirm_mode: confirm-all
    max_steps: 10
```

---

## Confirmation Modes

| Mode | Behavior |
|------|----------|
| `confirm-all` | Every action requires interactive confirmation |
| `confirm-sensitive` | Only actions that modify the system (write, delete) |
| `yolo` | No confirmations — neither tools nor commands (for CI/scripts). Safety is guaranteed by the destructive commands blocklist |

> In environments without TTY (`--mode confirm-sensitive` in CI), the system raises a clear error. Use `--mode yolo` or `--dry-run` in pipelines.

---

## Configuration

Copy `config.example.yaml` as a starting point:

```bash
cp config.example.yaml config.yaml
```

Minimal structure:

```yaml
llm:
  model: gpt-4o-mini          # or claude-sonnet-4-6, ollama/llama3, etc.
  api_key_env: LITELLM_API_KEY
  timeout: 60
  retries: 2
  stream: true

workspace:
  root: .
  allow_delete: false

logging:
  level: human                 # human (default), debug, info, warn, error
  verbose: 0
```

### Environment Variables

| Variable | Config equivalent | Description |
|----------|-------------------|-------------|
| `LITELLM_API_KEY` | `llm.api_key_env` | LLM provider API key |
| `ARCHITECT_MODEL` | `llm.model` | LLM model |
| `ARCHITECT_API_BASE` | `llm.api_base` | API base URL |
| `ARCHITECT_LOG_LEVEL` | `logging.level` | Logging level |
| `ARCHITECT_WORKSPACE` | `workspace.root` | Working directory |

---

## Output and Exit Codes

**stdout/stderr separation**:
- LLM streaming → **stderr** (doesn't break pipes)
- Logs and progress → **stderr**
- Agent's final result → **stdout**
- `--json` output → **stdout**

```bash
# Parse result with jq
architect run "summarize the project" --quiet --json | jq .status

# Capture result, view logs
architect run "analyze main.py" -v 2>logs.txt

# Result only (no logs)
architect run "generate README" --quiet --mode yolo
```

**Exit codes**:

| Code | Meaning |
|------|---------|
| `0` | Success (`success`) |
| `1` | Agent failure (`failed`) |
| `2` | Partial — did something but didn't complete (`partial`) |
| `3` | Configuration error |
| `4` | LLM authentication error |
| `5` | Timeout |
| `130` | Interrupted (Ctrl+C) |

---

## JSON Format (`--json`)

```bash
architect run "analyze the project" -a review --quiet --json
```

```json
{
  "status": "success",
  "stop_reason": null,
  "output": "The project consists of...",
  "steps": 3,
  "tools_used": [
    {"name": "list_files", "success": true},
    {"name": "read_file", "path": "src/main.py", "success": true}
  ],
  "duration_seconds": 8.5,
  "model": "gpt-4o-mini",
  "costs": {"total_usd": 0.0023, "prompt_tokens": 4200, "completion_tokens": 380}
}
```

**`stop_reason`**: indicates why the agent stopped. `null` = terminated naturally. Other values: `max_steps`, `timeout`, `budget_exceeded`, `context_full`, `user_interrupt`, `llm_error`.

When a watchdog triggers (`max_steps`, `timeout`, etc.), the agent receives a shutdown instruction and makes one last LLM call to summarize what was completed and what remains pending before terminating.

---

## Logging

By default, architect displays agent steps in a human-readable format with icons:

```
🔄 Step 1 → LLM call (6 messages)
   ✓ LLM responded with 2 tool calls

   🔧 read_file → src/main.py
      ✓ OK

   🔧 edit_file → src/main.py (3→5 lines)
      ✓ OK
      🔍 Hook ruff: ✓

🔄 Step 2 → LLM call (10 messages)
   ✓ LLM responded with final text

✅ Agent completed (2 steps)
   Reason: LLM decided it was done
   Cost: $0.0042
```

MCP tools are visually distinguished: `🌐 mcp_github_search → query (MCP: github)`

```bash
# Human-readable steps only (default — HUMAN level)
architect run "..."

# HUMAN level + technical logs per step
architect run "..." -v

# Full detail (args, LLM responses)
architect run "..." -vv

# Everything (HTTP, payloads)
architect run "..." -vvv

# No logs (result only)
architect run "..." --quiet

# Logs to JSON file + console
architect run "..." -v --log-file logs/session.jsonl

# Analyze logs afterwards
cat logs/session.jsonl | jq 'select(.event == "tool.call")'
```

**Independent logging pipelines**:
- **HUMAN** (stderr, default): steps, tool calls, hooks — readable format with icons, no technical noise
- **Technical** (stderr, with `-v`): LLM debug, tokens, retries — excludes HUMAN messages
- **JSON file** (file, with `--log-file`): all structured events

See [`docs/logging.md`](docs/logging.md) for logging architecture details.

---

## Lifecycle Hooks

Complete hook system that runs at 10 points in the agent lifecycle. Allows intercepting, blocking, or modifying operations.

```yaml
hooks:
  pre_tool_use:
    - command: "python scripts/validate_tool.py"
      matcher: "write_file|edit_file"
      timeout: 5

  post_tool_use:
    - command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
      timeout: 15
    - command: "mypy {file} --ignore-missing-imports"
      file_patterns: ["*.py"]
      timeout: 30

  session_start:
    - command: "echo 'Session started'"
      async: true

  agent_complete:
    - command: "python scripts/post_run.py"
```

**Available events**: `pre_tool_use`, `post_tool_use`, `pre_llm_call`, `post_llm_call`, `session_start`, `session_end`, `on_error`, `budget_warning`, `context_compress`, `agent_complete`

**Exit code protocol**:
- `0` = ALLOW (continue; if stdout contains JSON with `updatedInput`, the input is modified)
- `2` = BLOCK (abort the operation)
- Other = error (warning in logs, execution continues)

**Injected environment variables**: `ARCHITECT_EVENT`, `ARCHITECT_TOOL`, `ARCHITECT_WORKSPACE`, `ARCHITECT_FILE` (if applicable)

**Backward compatible**: the `post_edit` section still works and maps to `post_tool_use` with editing tools matcher.

---

## Guardrails

Deterministic security layer evaluated **before** hooks. Cannot be disabled by the LLM.

```yaml
guardrails:
  # Write-only protection: blocks write/edit/delete, allows read
  protected_files:
    - "config/production.yaml"
    - ".git/**"

  # Full protection: blocks ALL access including read (v1.1.0)
  sensitive_files:
    - ".env"
    - ".env.*"
    - "*.pem"
    - "*.key"
    - "secrets/**"

  blocked_commands:
    - "rm -rf /"
    - "DROP TABLE"
  max_files_per_session: 20
  max_lines_changed: 5000
  code_rules:
    - pattern: "TODO|FIXME"
      severity: warn
      message: "Code with pending TODOs"
    - pattern: "eval\\("
      severity: block
      message: "eval() not allowed"
  quality_gates:
    - name: tests
      command: "pytest --tb=short -q"
      required: true
    - name: lint
      command: "ruff check src/"
      required: false
```

**`protected_files` vs `sensitive_files`**: `protected_files` blocks write/edit/delete operations but allows the agent to read the file. `sensitive_files` blocks **all** access including reads — the agent cannot see the file contents. Use `sensitive_files` for secrets (`.env`, private keys) to prevent them from being sent to the LLM provider.

**Shell command detection**: `sensitive_files` also blocks shell reads (`cat`, `head`, `tail`, `less`) and shell redirects (`>`, `>>`, `| tee`) targeting sensitive files.

**Quality gates**: executed when the agent declares completion. If a `required` gate fails, the agent receives feedback and keeps working until it passes.

---

## Skills and .architect.md

The agent automatically loads project context from `.architect.md`, `AGENTS.md`, or `CLAUDE.md` in the workspace root and injects its content into the system prompt.

**Specialized skills** are discovered in `.architect/skills/` and `.architect/installed-skills/`:

```
.architect/
├── skills/
│   └── django/
│       └── SKILL.md        # YAML frontmatter + content
└── installed-skills/
    └── react-patterns/
        └── SKILL.md
```

Each `SKILL.md` can have a YAML frontmatter with `globs` to activate only when relevant files are in play:

```yaml
---
name: django
description: Django patterns for the project
globs: ["*.py", "*/models.py", "*/views.py"]
---
# Django Instructions
Use class-based views whenever possible...
```

```bash
# Skill management
architect skill list
architect skill create my-skill
architect skill install github-user/repo/path/to/skill
architect skill remove my-skill
```

---

## Procedural Memory

The agent detects user corrections and persists them across sessions in `.architect/memory.md`.

```yaml
memory:
  enabled: true
  auto_detect_corrections: true
```

When the user corrects the agent (e.g., "don't use print, use logging"), the pattern is saved and injected in future sessions as additional context in the system prompt.

The `.architect/memory.md` file is manually editable and follows the format:
```
- [2026-02-22] correction: Don't use print(), use logging
- [2026-02-22] pattern: Always run tests after editing
```

---

## Cost Control

```yaml
costs:
  budget_usd: 2.0         # Stops the agent if it exceeds $2
  warn_at_usd: 1.5        # Warns in logs when reaching $1.5
```

```bash
# Budget limit via CLI
architect run "..." --budget 1.0
```

Accumulated cost appears in the `--json` output under `costs` and with `--show-costs` at the end of execution (works with both streaming and non-streaming modes). When the budget is exceeded, the agent receives a shutdown instruction and produces one last summary before terminating (`stop_reason: "budget_exceeded"`).

---

## MCP (Model Context Protocol)

Connect architect to remote tools via HTTP:

```yaml
mcp:
  servers:
    - name: github
      url: http://localhost:3001
      token_env: GITHUB_TOKEN

    - name: database
      url: https://mcp.example.com/db
      token_env: DB_TOKEN
```

MCP tools are automatically discovered at startup and injected into the active agent's `allowed_tools` (no need to list them in the agent config). They are indistinguishable from local tools for the LLM. If a server is unavailable, the agent continues without those tools.

```bash
# With MCP
architect run "open a PR with the changes" --mode yolo

# Without MCP
architect run "analyze the project" --disable-mcp
```

---

## Sessions and Resume

The agent automatically saves its state after each step. If an execution is interrupted (Ctrl+C, timeout, error), you can resume it:

```bash
# Run a long task
architect run "refactor the entire auth module" --budget 5.0
# → Interrupted by timeout or Ctrl+C

# View saved sessions
architect sessions
# ID                     Status       Steps  Cost    Task
# 20260223-143022-a1b2   interrupted  12     $1.23   refactor the entire auth module

# Resume where it left off
architect resume 20260223-143022-a1b2

# Clean up old sessions
architect cleanup --older-than 7
```

Sessions are saved in `.architect/sessions/` as JSON files. Long messages (>50) are automatically truncated to the last 30 to keep the size manageable.

---

## Execution Reports

Generate detailed reports of what the agent did, in three formats:

```bash
# JSON report (ideal for CI/CD)
architect run "add tests" --mode yolo --report json

# Markdown report (for documentation)
architect run "refactor utils" --mode yolo --report markdown --report-file report.md

# GitHub PR comment (with collapsible sections)
architect run "review the changes" --mode yolo --report github --report-file pr-comment.md
```

The report includes: summary (task, agent, model, status, duration, steps, cost), modified files with added/removed lines, executed quality gates, errors found, timeline of each step, and git diff.

---

## Ralph Loop (Automatic Iteration)

The Ralph Loop runs an agent iteratively until all checks pass. Each iteration uses a **clean context** — the agent receives only:

1. The original spec (file or prompt)
2. The accumulated diff from all previous iterations
3. Check errors from the previous iteration
4. An auto-generated `progress.md` with history

```bash
# Iterate until tests and lint pass
architect loop "implement JWT authentication" \
  --check "pytest tests/test_auth.py" \
  --check "ruff check src/auth/" \
  --max-iterations 5 \
  --max-cost 3.0

# With detailed spec file
architect loop "implement per spec" \
  --spec requirements/auth-spec.md \
  --check "pytest" \
  --worktree
```

**Safety nets**: The loop stops if iterations (`max_iterations`), cost (`max_cost`), or time (`max_time`) are exhausted. The result indicates the stop reason.

**Worktree**: With `--worktree`, the loop runs in an isolated git worktree. If all checks pass, the result includes the worktree path for inspection or merge.

---

## Pipeline Mode (Multi-Step Workflows)

Pipelines define sequential workflows where each step can have its own agent, model, checks, and configuration.

**Features**:
- **Variables**: `{{name}}` in prompts, substituted from `--var` or from `output_var` of previous steps
- **Conditions**: `condition` evaluates an expression; the step is skipped if false
- **Output variables**: `output_var` captures a step's output as a variable for subsequent steps
- **Checks**: post-step shell commands that verify the result
- **Checkpoints**: `checkpoint: true` creates an automatic git commit upon step completion
- **Resume**: `--from-step` allows resuming a pipeline from a specific step
- **Dry-run**: `--dry-run` shows the plan without executing agents

```yaml
# pipeline.yaml
name: feature-pipeline
steps:
  - name: plan
    agent: plan
    prompt: "Plan how to implement {{feature}}"
    output_var: plan_output

  - name: implement
    agent: build
    prompt: "Execute this plan: {{plan_output}}"
    model: gpt-4o
    checks:
      - "pytest tests/ -q"
    checkpoint: true

  - name: review
    agent: review
    prompt: "Review the implementation of {{feature}}"
    condition: "run_review == 'true'"
```

```bash
architect pipeline pipeline.yaml \
  --var feature="user auth" \
  --var run_review=true
```

---

## Parallel Execution

Run multiple tasks in parallel, each in an isolated git worktree with `ProcessPoolExecutor`.

```bash
architect parallel \
  --task "add unit tests to auth.py" \
  --task "add unit tests to users.py" \
  --task "add unit tests to billing.py" \
  --workers 3 \
  --budget-per-worker 2.0
```

Each worker:
- Runs in an independent git worktree (total isolation)
- Can use a different model (with `--models` they are assigned round-robin)
- Has its own budget and timeout
- The result includes modified files, cost, duration, and worktree path

```bash
# Clean up worktrees afterwards
architect parallel-cleanup
```

---

## Checkpoints and Rollback

Checkpoints are git commits with a special prefix (`architect:checkpoint`) that allow restoring the workspace to a previous point. They are created automatically in pipelines (with `checkpoint: true`) and can be used in the Ralph Loop.

```bash
# Checkpoints are created automatically in pipelines with checkpoint: true
# To view created checkpoints:
git log --oneline --grep="architect:checkpoint"
```

The `CheckpointManager` allows:
- **Creating** checkpoints (stage all + commit with prefix)
- **Listing** existing checkpoints by parsing `git log`
- **Rolling back** to a specific checkpoint (by step or commit hash)
- **Verifying** if there are changes since a checkpoint

---

## Auto-Review

After a build execution, a reviewer with **clean context** can inspect the changes. The reviewer receives only the diff and the original task — without the builder's history — and has exclusive access to read-only tools.

```yaml
# Enable auto-review in config
auto_review:
  enabled: true
  model: gpt-4o
```

The reviewer looks for:
- Bugs and logic errors
- Security issues
- Project convention violations
- Performance or readability improvements
- Missing tests

If issues are found, it generates a correction prompt that can feed the builder for a fix-pass.

---

## Code Health Delta

Automatic code quality metrics analysis before and after an execution. Shows a delta of cyclomatic complexity, long functions, duplicates, and more.

```bash
# Enable with flag
architect run "refactor the auth module" --health

# Or enable permanently in config
```

```yaml
health:
  enabled: true
  include_patterns: ["**/*.py"]
  exclude_dirs: [".git", "venv", "__pycache__"]
```

**Analyzed metrics**:
- Cyclomatic complexity (requires `radon` installed, falls back to AST if not)
- Lines per function
- New/removed functions
- Duplicate code blocks (6-line sliding window, MD5 hash)
- Long functions (>50 lines)
- Complex functions (>10 complexity)

The report is displayed on stderr at the end of execution as a markdown table with improvement/degradation indicators.

---

## Competitive Evaluation

Competitive evaluation runs the same task with multiple models and generates a ranking based on quality, efficiency, and cost.

```bash
architect eval "implement JWT authentication" \
  --models gpt-4o,claude-sonnet-4-6 \
  --check "pytest tests/" \
  --check "ruff check src/" \
  --budget-per-model 1.0
```

Each model runs in an isolated git worktree (reuses `ParallelRunner` infrastructure). After execution, checks are run in each worktree and a comparative ranking is generated.

**Generated report**: table with status, steps, cost, time, passed checks, and composite score. Worktrees remain for manual inspection.

---

## Sub-Agents (Dispatch)

The main agent can delegate specialized sub-tasks via the `dispatch_subagent` tool. Each sub-agent runs with a fresh `AgentLoop` with isolated context and limited tools.

**Sub-agent types**:

| Type | Available tools | Use case |
|------|----------------|----------|
| `explore` | `read_file`, `list_files`, `search_code`, `grep`, `find_files` | Investigate code, search patterns |
| `test` | Explore + `run_command` | Run tests, verify behavior |
| `review` | Explore (read-only) | Review code, quality analysis |

Each sub-agent has a maximum of 15 steps and its summary is truncated to 1000 characters to avoid polluting the main agent's context.

---

## OpenTelemetry Traces

Optional traceability with OpenTelemetry for monitoring sessions, LLM calls, and tool execution.

```yaml
telemetry:
  enabled: true
  exporter: otlp          # otlp | console | json-file
  endpoint: http://localhost:4317
  trace_file: .architect/traces.json  # for json-file
```

**Supported exporters**:
- **otlp**: Sends spans via gRPC (compatible with Jaeger, Grafana Tempo, etc.)
- **console**: Prints spans to stderr (debugging)
- **json-file**: Writes spans to a JSON file

**Semantic attributes** (GenAI Semantic Conventions):
- `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cost`
- `architect.task`, `architect.agent`, `architect.session_id`, `architect.tool_name`

**Optional dependencies**: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`. If not installed, a transparent `NoopTracer` with no performance impact is used.

---

## Configuration Presets

Presets generate `.architect.md` and `config.yaml` with predefined configurations based on project type.

```bash
# View available presets
architect init --list-presets

# Initialize for Python project
architect init --preset python
# → Creates .architect.md (conventions) + config.yaml (hooks: ruff, mypy)

# Paranoid mode (maximum security)
architect init --preset paranoid
# → confirm-all, max 20 steps, strict code rules, quality gates
```

Generated files are editable — they serve as a starting point. Use `--overwrite` to replace existing files.

---

## CI/CD Usage

### Basic Example — GitHub Actions

```yaml
- name: Refactor code
  run: |
    architect run "update obsolete imports in src/" \
      --mode yolo \
      --quiet \
      --json \
      --budget 3.0 \
      -c ci/architect.yaml \
    | tee result.json

- name: Verify result
  run: |
    STATUS=$(cat result.json | jq -r .status)
    if [ "$STATUS" != "success" ]; then
      echo "architect failed with status: $STATUS ($(cat result.json | jq -r .stop_reason))"
      exit 1
    fi
```

### Advanced Example — with reports, dry-run, and git diff

```yaml
- name: Dry run first (see what it would do)
  run: |
    architect run "add docstrings to all functions" \
      --dry-run \
      --confirm-mode yolo \
      --json

- name: Execute with PR context
  run: |
    architect run "review and improve this PR's changes" \
      --confirm-mode yolo \
      --context-git-diff origin/main \
      --report github \
      --report-file pr-report.md \
      --budget 5.0 \
      --timeout 600 \
      --exit-code-on-partial 0

- name: Comment on PR
  if: always()
  run: gh pr comment $PR_NUMBER --body-file pr-report.md
```

### CI Config

```yaml
# ci/architect.yaml
llm:
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  retries: 3
  timeout: 120

workspace:
  root: .

logging:
  level: human
  verbose: 0

hooks:
  post_edit:
    - name: lint
      command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
```

---

## Security

- **Path traversal**: all file operations are confined to `workspace.root`. Attempts to access `../../etc/passwd` are blocked.
- **delete_file** requires explicit `workspace.allow_delete: true` in config.
- **run_command**: destructive commands blocklist (`rm -rf /`, `sudo`, `dd`, `mkfs`, `curl|bash`, etc.) always active, regardless of confirmation mode. Dynamic classification (safe/dev/dangerous) for confirmation policies in `confirm-sensitive` and `confirm-all` modes. Working directory is always confined to the workspace.
- **MCP tools** are marked as sensitive by default (require confirmation in `confirm-sensitive`).
- **API keys** are never logged, only the environment variable name.

---

## Supported LLM Providers

Any provider supported by [LiteLLM](https://docs.litellm.ai/docs/providers):

```bash
# OpenAI
LITELLM_API_KEY=sk-... architect run "..." --model gpt-4o

# Anthropic
LITELLM_API_KEY=sk-ant-... architect run "..." --model claude-sonnet-4-6

# Google Gemini
LITELLM_API_KEY=... architect run "..." --model gemini/gemini-2.0-flash

# Ollama (local, no API key)
architect run "..." --model ollama/llama3 --api-base http://localhost:11434

# LiteLLM Proxy (for teams)
architect run "..." --api-base http://proxy.internal:8000
```

---

## Architecture

```
architect run PROMPT
    │
    ├── load_config()          YAML + env vars + CLI flags
    ├── configure_logging()    3 pipelines: HUMAN + technical + JSON file
    ├── ToolRegistry           local tools (fs, editing, search, run_command) + remote MCP
    ├── RepoIndexer            workspace tree → injected into system prompt
    ├── LLMAdapter             LiteLLM with selective retries + prompt caching
    ├── ContextManager         pruning: compress + enforce_window + is_critically_full
    ├── HookExecutor           10 lifecycle events, exit code protocol
    ├── GuardrailsEngine       deterministic security (before hooks)
    ├── SkillsLoader           .architect.md + skills by glob
    ├── ProceduralMemory       user corrections across sessions
    ├── CostTracker            accumulated cost + budget watchdog
    ├── SessionManager         session persistence (save/load/resume)
    ├── DryRunTracker          action recording without execution (--dry-run)
    ├── CheckpointManager      git commits with rollback (architect:checkpoint)
    ├── ArchitectTracer        OpenTelemetry spans (session/llm/tool) or NoopTracer
    ├── CodeHealthAnalyzer     quality metrics before/after (--health)
    │
    ├── RalphLoop              automatic iteration until checks pass
    │       └── agent_factory() → fresh AgentLoop per iteration (clean context)
    ├── PipelineRunner         multi-step YAML workflows with variables/conditions
    │       └── agent_factory() → fresh AgentLoop per step
    ├── ParallelRunner         parallel execution in isolated git worktrees
    │       └── ProcessPoolExecutor → workers with `architect run` in worktrees
    ├── CompetitiveEval        comparative multi-model evaluation over ParallelRunner
    ├── AutoReviewer           post-build review with clean context (diff + task only)
    ├── PresetManager          .architect.md + config.yaml generation from presets
    ├── DispatchSubagentTool   sub-task delegation (explore/test/review)
    │
    └── AgentLoop (while True — the LLM decides when to stop)
            │
            ├── _check_safety_nets()   max_steps / budget / timeout / context_full
            │       └── if triggered → _graceful_close(): last LLM call without tools
            │                         agent summarizes what was done and what remains
            ├── context_manager.manage()     compress + enforce_window if needed
            ├── hooks: pre_llm_call          → intercept before LLM
            ├── llm.completion()             → streaming chunks to stderr
            ├── hooks: post_llm_call         → intercept after LLM
            ├── if no tool_calls             → LLM_DONE, natural end
            ├── guardrails.check()           → deterministic security (before hooks)
            ├── hooks: pre_tool_use          → ALLOW / BLOCK / MODIFY
            ├── engine.execute_tool_calls()  → parallel if possible → confirm → execute
            ├── hooks: post_tool_use         → lint/test → feedback to LLM if fails
            └── repeat
```

**Stop reasons** (`stop_reason` in JSON output):

| Reason | Description |
|--------|-------------|
| `null` / `llm_done` | The LLM decided it was done (natural termination) |
| `max_steps` | Watchdog: step limit reached |
| `budget_exceeded` | Watchdog: cost limit exceeded |
| `context_full` | Watchdog: context window full (>95%) |
| `timeout` | Watchdog: total time exceeded |
| `user_interrupt` | User pressed Ctrl+C / SIGTERM (immediate cut) |
| `llm_error` | Unrecoverable LLM error |

**Design decisions**:
- Sync-first (predictable, debuggable; the main loop is ~300 lines without magic)
- No LangChain/LangGraph (the loop is direct and controlled)
- Pydantic v2 as the source of truth for schemas and validation
- Tool errors returned to the LLM as results (don't break the loop)
- Clean stdout for pipes, everything else to stderr
- Watchdogs request graceful shutdown — the agent never terminates mid-sentence

---

## Version History

| Version | Features |
|---------|----------|
| v0.9.0 | **Incremental editing**: `edit_file` (exact str-replace) and `apply_patch` (unified diff) |
| v0.10.0 | **Indexer + search**: repo tree in system prompt, `search_code`, `grep`, `find_files` |
| v0.11.0 | **Context management**: tool result truncation, step compression with LLM, hard limit, parallel tool calls |
| v0.12.0 | **Self-evaluation**: `--self-eval basic/full` evaluates and retries automatically |
| v0.13.0 | **`run_command`**: command execution (tests, linters) with 4 security layers |
| v0.14.0 | **Cost tracking**: `CostTracker`, `--budget`, prompt caching, `LocalLLMCache` |
| v0.15.0 | **v3-core** — core redesign: `while True` loop, safety nets with graceful shutdown, `PostEditHooks`, HUMAN log level, `StopReason`, `ContextManager.manage()` |
| v0.15.2 | **Human logging with icons** — visual format aligned with v3 plan: 🔄🔧🌐✅⚡❌📦🔍, MCP distinction, new events (`llm_response`), cost in completion |
| v0.15.3 | **Fix structlog pipeline** — human logging works without `--log-file`; `wrap_for_formatter` always active |
| v0.16.0 | **v4 Phase A** — lifecycle hooks (10 events, exit code protocol), deterministic guardrails, skills ecosystem (.architect.md), procedural memory |
| v0.16.1 | **QA Phase A** — 228 verifications, 5 bugs fixed (ToolResult import, CostTracker.total, YAML off, schema shadowing), 24 aligned scripts |
| v0.16.2 | **QA2** — `--show-costs` works with streaming, `--mode yolo` never asks for confirmation (not even for `dangerous`), `--timeout` is session watchdog (doesn't override `llm.timeout`), MCP tools auto-injected into `allowed_tools`, defensive `get_schemas` |
| v0.17.0 | **v4 Phase B** — persistent sessions with resume, multi-format reports (JSON/Markdown/GitHub PR), 10 native CI/CD flags (`--dry-run`, `--report`, `--session`, `--context-git-diff`, `--confirm-mode`, `--exit-code-on-partial`), dry-run/preview mode, 3 new commands (`sessions`, `resume`, `cleanup`) |
| v0.18.0 | **v4 Phase C** — Ralph Loop (automatic iteration with checks), Pipeline Mode (multi-step YAML workflows with variables, conditions, checkpoints), parallel execution in git worktrees, checkpoints with rollback, post-build auto-review with clean context, 4 new commands (`loop`, `pipeline`, `parallel`, `parallel-cleanup`) |
| v0.19.0 | **v4 Phase D** — Competitive multi-model evaluation (`architect eval`), preset initialization (`architect init` with 5 presets), code health analysis (`--health` with complexity/duplicates delta), delegated sub-agents (`dispatch_subagent` with explore/test/review types), OpenTelemetry traceability (session/llm/tool spans), 7 QA bugfixes (code_rules pre-execution, dispatch wiring, telemetry wiring, health wiring, parallel config propagation) |
| **v1.0.0** | **Stable release** — First public version. Culmination of Plan V4 (Phases A+B+C+D) on v3 core. 15 CLI commands, 11+ tools, 4 agents, hooks + guardrails + skills + memory, sessions + reports + CI/CD, Ralph Loop + pipelines + parallel + checkpoints + auto-review, sub-agents + health + eval + telemetry + presets. 687 tests, 31 E2E checks. |
| v1.0.1 | **Bugfixes** — Test fixes and general stability corrections after initial release. |
| **v1.1.0** | **`sensitive_files` guardrail** — New `sensitive_files` field blocks both read and write access to secret files (`.env`, `*.pem`, `*.key`). Shell read detection (`cat`, `head`, `tail`). `protected_files` remains write-only (backward compatible). **Report improvements** — `--report-file` now works without `--report` (format inferred from extension), and automatically creates parent directories with fallback. **Pipeline YAML validation** — Strict validation before execution: unknown fields rejected (with hints), `prompt` required, `PipelineValidationError` with all errors collected. **HUMAN logging** — Visual traceability for all high-level features: pipeline steps, ralph iterations with check results, auto-review status, parallel worker progress, competitive eval ranking with medals. 14 new HUMAN events across 5 modules, 14 formatter cases, 11 HumanLog helpers. 795 tests. |

---

## License

[MIT](LICENSE)
