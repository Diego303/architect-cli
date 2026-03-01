"""
English language strings (canonical) for architect-cli.

All keys used in i18n are defined here. The Spanish translation (es.py)
must have the same keys.
"""

STRINGS: dict[str, str] = {
    # ── Human Formatter: LLM ────────────────────────────────────────────
    "human.llm_call": "\n🔄 Step {step} → LLM call ({messages} messages)",
    "human.llm_response_tools": "   ✓ LLM responded with {count} tool call{s}",
    "human.llm_response_text": "   ✓ LLM responded with final text",
    "human.agent_complete": (
        "\n✅ Agent complete ({steps} steps)\n"
        "   Reason: LLM decided it was done{cost_line}"
    ),
    "human.cost_line": "\n   Cost: {cost}",
    # ── Human Formatter: Tools ──────────────────────────────────────────
    "human.tool_call": "\n   🔧 {tool} → {summary}",
    "human.tool_call_mcp": "\n   🌐 {tool} → {summary}  (MCP: {server})",
    "human.tool_ok": "      ✓ OK",
    "human.tool_error": "      ✗ ERROR: {error}",
    "human.hook_complete": "      🔍 Hook {hook}: {icon}",
    "human.hooks_executed": "      🔍 hooks executed",
    # ── Human Formatter: Safety nets ────────────────────────────────────
    "human.user_interrupt": "\n⚠️  Interrupted by user",
    "human.max_steps": (
        "\n⚠️  Step limit reached ({step}/{max_steps})\n"
        "    Asking the agent to summarize..."
    ),
    "human.budget_exceeded": (
        "\n⚠️  Budget exceeded (${spent}/{budget})\n"
        "    Asking the agent to summarize..."
    ),
    "human.timeout": "\n⚠️  Timeout reached\n    Asking the agent to summarize...",
    "human.context_full": "\n⚠️  Context full\n    Asking the agent to summarize...",
    # ── Human Formatter: LLM errors ─────────────────────────────────────
    "human.llm_error": "\n❌ LLM error: {error}",
    "human.step_timeout": "\n⚠️  Step timeout ({seconds}s)\n    Asking the agent to summarize...",
    # ── Human Formatter: Agent lifecycle ─────────────────────────────────
    "human.closing": "\n🔄 Closing ({reason}, {steps} steps completed)",
    "human.loop_complete_success": "  ({steps} steps, {tool_calls} tool calls){cost_line}",
    "human.loop_complete_stopped": "\n⚡ Stopped ({status}{reason_str}, {steps} steps){cost_line}",
    # ── Human Formatter: Pipeline ───────────────────────────────────────
    "human.pipeline_step_skipped": "\n   ⏭️  Step '{step}' skipped (condition not met)",
    "human.pipeline_step_done": "\n   {icon} Step '{step}' → {status} ({cost_str}, {dur_str})",
    # ── Human Formatter: Ralph Loop ─────────────────────────────────────
    "human.ralph_checks": "   🧪 Checks: {passed}/{total} passed{check_icon}",
    "human.ralph_iteration_done": "   {icon} Iteration {iteration} → {status} ({cost_str}, {dur_str})",
    "human.ralph_complete": "\n{icon} Ralph complete — {total_iterations} iterations, {status} ({cost_str})",
    # ── Human Formatter: Auto-Reviewer ──────────────────────────────────
    "human.reviewer_start_label": " Auto-Review ({diff_lines} diff lines) ",
    "human.reviewer_complete": "   {icon} Review complete: {status}, {issues} issues, score {score}",
    "human.reviewer_status_approved": "approved",
    "human.reviewer_status_rejected": "not approved",
    # ── Human Formatter: Parallel Runs ──────────────────────────────────
    "human.parallel_worker_done": "   {icon} Worker {worker} ({model}) → {status} ({cost_str}, {dur_str})",
    "human.parallel_worker_error": "   ✗ Worker {worker} → error: {error}",
    "human.parallel_complete": (
        "\n⚡ Parallel complete — {total_workers} workers: "
        "{succeeded} success, {failed} failed ({cost_str})"
    ),
    # ── Human Formatter: Competitive Eval ───────────────────────────────
    "human.competitive_ranking_empty": "\n🏁 Final ranking: (no results)",
    "human.competitive_ranking": "\n🏁 Final ranking: {ranking}",
    # ── Human Formatter: Context ────────────────────────────────────────
    "human.context_compressing": "   📦 Compressing context — {exchanges} exchanges",
    "human.context_window_enforced": "   📦 Context window: removed {removed} old messages",
    # ── Human Formatter: _summarize_args ────────────────────────────────
    "human.summary_lines": "{path} ({lines} lines)",
    "human.summary_edit": "{path} ({old}→{new} lines)",
    "human.summary_search": "\"{pattern}\" in {path}",
    "human.summary_no_args": "(no args)",
    # ── Agent Prompts ───────────────────────────────────────────────────
    "prompt.build": (
        "You are a software development agent. You work methodically and verify your work.\n\n"
        "## Your workflow\n\n"
        "1. ANALYZE: Read the relevant files and understand the context before acting\n"
        "2. PLAN: Think about the necessary steps and their correct order\n"
        "3. EXECUTE: Make changes step by step\n"
        "4. VERIFY: After each change, check that it works\n"
        "5. FIX: If something fails, analyze the error and fix it\n\n"
        "## Editing tools — Hierarchy\n\n"
        "| Situation | Tool |\n"
        "|-----------|------|\n"
        "| Modify a single contiguous block | `edit_file` (str_replace) ← **PREFER** |\n"
        "| Changes in multiple sections | `apply_patch` (unified diff) |\n"
        "| New file or complete rewrite | `write_file` |\n\n"
        "## Search tools\n\n"
        "Before opening files, use these tools to find what's relevant:\n\n"
        "| Need | Tool |\n"
        "|------|------|\n"
        "| Search definitions, imports, code | `search_code` (regex) |\n"
        "| Search exact literal text | `grep` |\n"
        "| Locate files by name | `find_files` |\n"
        "| Explore a directory | `list_files` |\n\n"
        "## Command execution\n\n"
        "Use `run_command` to verify and execute:\n\n"
        "| Situation | Example |\n"
        "|-----------|--------|\n"
        "| Run tests | `run_command(command=\"pytest tests/ -v\")` |\n"
        "| Check types | `run_command(command=\"mypy src/\")` |\n"
        "| Linting | `run_command(command=\"ruff check .\")` |\n\n"
        "## Rules\n\n"
        "- Always read a file before editing it\n"
        "- Use `search_code` or `grep` to find relevant code instead of guessing\n"
        "- If a command or test fails, analyze the error and try to fix it\n"
        "- Do NOT ask for confirmation or ask questions — act with available information\n"
        "- When you have completed the task, explain what you did and which files you changed\n"
        "- Make the minimum changes necessary to complete the task"
    ),
    "prompt.plan": (
        "You are an analysis and planning agent. Your job is to understand a task\n"
        "and produce a detailed plan WITHOUT executing changes.\n\n"
        "## Your process\n\n"
        "1. Read the relevant files to understand the context\n"
        "2. Analyze what changes are necessary\n"
        "3. Produce a structured plan with:\n"
        "   - Which files to create/modify/delete\n"
        "   - What specific changes in each file\n"
        "   - In what order to make them\n"
        "   - Possible risks or dependencies\n\n"
        "## Exploration tools\n\n"
        "| Situation | Tool |\n"
        "|-----------|------|\n"
        "| Search definitions, imports, code | `search_code` (regex) |\n"
        "| Search exact literal text | `grep` |\n"
        "| Locate files by name | `find_files` |\n"
        "| List a directory | `list_files` |\n"
        "| Read content | `read_file` |\n\n"
        "## Rules\n\n"
        "- Do NOT modify any file\n"
        "- Use search tools to investigate before planning\n"
        "- Be specific: don't say \"modify auth.py\", say \"in auth.py, add token\n"
        "  validation in the validate() function around line ~45\"\n"
        "- If something is ambiguous, indicate the options and recommend one"
    ),
    "prompt.resume": (
        "You are an analysis and summary agent. Your job is to read information\n"
        "and produce a clear and concise summary. You do not modify files.\n\n"
        "Be direct. Don't repeat what the user already knows. Focus on what matters."
    ),
    "prompt.review": (
        "You are a code review agent. Your job is to inspect code\n"
        "and provide constructive, actionable feedback.\n\n"
        "## What to look for\n\n"
        "- Bugs and logic errors\n"
        "- Security issues\n"
        "- Simplification opportunities\n"
        "- Code smells and SOLID violations\n"
        "- Missing tests\n\n"
        "## Rules\n\n"
        "- Do NOT modify any file\n"
        "- Be specific: indicate file, line and the exact problem\n"
        "- Prioritize: first bugs/security, then improvements, then style"
    ),
    "prompt.review_system": (
        "You are a senior code reviewer. Your job is to review code changes "
        "made by another agent and find problems.\n\n"
        "Look specifically for:\n"
        "1. Logic bugs and uncovered edge cases\n"
        "2. Security issues (SQL injection, XSS, hardcoded secrets, etc.)\n"
        "3. Violations of project conventions (if there is .architect.md, follow it)\n"
        "4. Simplification or improvement opportunities\n"
        "5. Missing or insufficient tests\n\n"
        "Be specific: indicate file, line, and what exact change you would make.\n"
        "If you find no significant problems, say \"No issues found.\""
    ),
    # ── Close Instructions ──────────────────────────────────────────────
    "close.max_steps": (
        "You have reached the maximum allowed step limit. "
        "Respond with a summary of what you completed, what remains pending "
        "and suggestions for continuing in another session."
    ),
    "close.budget_exceeded": (
        "The maximum cost budget has been reached. "
        "Briefly summarize what you completed and what remains to be done."
    ),
    "close.context_full": (
        "The conversation context is full. "
        "Briefly summarize what you completed and what remains to be done."
    ),
    "close.agent_stopped": (
        "The agent stopped ({reason}). Steps completed: {steps}."
    ),
    "close.timeout": (
        "The allocated time for this execution has run out. "
        "Briefly summarize what you completed and what remains to be done."
    ),
    # ── Evaluator ───────────────────────────────────────────────────────
    "eval.system_prompt": (
        "You are an AI agent result evaluator. "
        "Your job is to verify whether a task was completed correctly.\n\n"
        "IMPORTANT: Respond ONLY with valid JSON with this exact structure:\n"
        '{"completed": true_or_false, "confidence": number_between_0_and_1, '
        '"issues": ["list", "of", "problems"], "suggestion": "improvement_suggestion"}\n\n'
        "- completed: true if the task was completed fully and correctly\n"
        "- confidence: your confidence level (1.0 = completely sure)\n"
        "- issues: empty list [] if everything is fine; list of problems otherwise\n"
        "- suggestion: what the agent should do to improve (empty if completed=true)\n\n"
        "Do not include explanations or text outside the JSON."
    ),
    "eval.user_prompt": (
        "**Original user task:**\n{original_prompt}\n\n"
        "**Agent result:**\n{output_preview}\n\n"
        "**Actions executed:**\n{steps_summary}\n\n"
        "Was the task completed correctly?"
    ),
    "eval.no_output": "(no output)",
    "eval.error": "Error evaluating: {error}",
    "eval.error_suggestion": "Verify the result manually.",
    "eval.parse_failed": "Could not parse LLM evaluation.",
    "eval.parse_failed_suggestion": "Review the result manually.",
    "eval.no_steps": "(no steps executed)",
    "eval.step_line": "  Step {step}: {tools} [{status}]",
    "eval.step_no_tools": "  Step {step}: (reasoning without tool calls)",
    "eval.status_ok": "OK",
    "eval.status_errors": "some errors",
    "eval.correction_prompt": (
        "The previous task was not completed correctly.\n\n"
        "**Original task:**\n{original_prompt}\n\n"
        "**Problems detected:**\n{issues_text}\n\n"
        "**Suggestion:**\n{suggestion_text}\n\n"
        "Please fix these problems and complete the task correctly."
    ),
    "eval.correction_default_issues": "  - Incomplete or incorrect result.",
    "eval.correction_default_suggestion": "Review the result and complete the task.",
    # ── Context Manager ─────────────────────────────────────────────────
    "context.chars_omitted": "[... {n} characters omitted ...]",
    "context.lines_omitted": "[... {n} lines omitted ...]",
    "context.summary_prompt": (
        "Summarize concisely the following agent actions. "
        "Keep important details (files modified, key decisions). "
        "Omit repetitive details:\n\n{content}"
    ),
    "context.summary_header": "[Summary of previous steps]",
    "context.mechanical_summary": "[Mechanical summary — LLM unavailable]\n{content}",
    "context.agent_called_tools": "Agent called tools: {tools}",
    "context.agent_responded": "Agent responded: {content}",
    "context.tool_result": "Result of {name}: {content}",
    "context.no_messages": "(no messages)",
    # ── Guardrails ──────────────────────────────────────────────────────
    "guardrail.sensitive_blocked": (
        "Sensitive file blocked by guardrail: {file} (pattern: {pattern})"
    ),
    "guardrail.protected_blocked": (
        "Protected file blocked by guardrail: {file} (pattern: {pattern})"
    ),
    "guardrail.command_blocked": (
        "Command blocked by guardrail: matches '{pattern}'"
    ),
    "guardrail.command_write_blocked": (
        "Command blocked: attempts to write to protected file "
        "'{target}' (pattern: {pattern})"
    ),
    "guardrail.command_read_blocked": (
        "Command blocked: attempts to read sensitive file "
        "'{target}' (pattern: {pattern})"
    ),
    "guardrail.commands_limit": (
        "Command limit reached ({limit}). "
        "The guardrail prevents executing more commands."
    ),
    "guardrail.files_limit": (
        "File modification limit reached ({limit}). "
        "The guardrail prevents modifying more files."
    ),
    "guardrail.lines_limit": (
        "Line modification limit reached ({limit}). "
        "The guardrail prevents further edits."
    ),
    "guardrail.code_rule": (
        "Code rule violation in {file}: pattern '{pattern}' — {message}"
    ),
    "guardrail.test_required": (
        "Tests required: {edits} edits since last test. "
        "Run tests before making more changes."
    ),
    # ── Dispatch Sub-agent ──────────────────────────────────────────────
    "dispatch.description": (
        "Delegates a sub-task to a specialized agent with its own independent "
        "context. Useful for investigating, exploring code or running tests "
        "without polluting your main context. The sub-agent will return a "
        "summary of its work.\n\n"
        "Available types:\n"
        "- explore: Read-only/search (read files, search code)\n"
        "- test: Read + test execution (pytest, etc.)\n"
        "- review: Read + code analysis\n\n"
        "The sub-agent has a maximum of 15 steps and returns a summary "
        "of at most 1000 characters."
    ),
    "dispatch.task_description": (
        "Description of the sub-task to execute. Be specific about what "
        "you want the sub-agent to investigate, test or review."
    ),
    "dispatch.type_description": (
        "Sub-agent type: "
        "'explore' (read-only/search, for investigating), "
        "'test' (read + test execution), "
        "'review' (read + code analysis)"
    ),
    "dispatch.files_description": (
        "Files the sub-agent should read for context. "
        "Example: ['src/main.py', 'tests/test_main.py']"
    ),
    "dispatch.invalid_type": (
        "Invalid sub-agent type: '{agent_type}'. "
        "Valid types: {valid_types}"
    ),
    "dispatch.no_result": "No result from sub-agent.",
    "dispatch.summary_truncated": "\n... (summary truncated)",
    "dispatch.error": "Error executing sub-agent: {error}",
    "dispatch.subtask_header": "## Sub-task ({agent_type})\n\n{task}",
    "dispatch.relevant_files_header": (
        "\n## Relevant Files\n\n"
        "Read these files for context:\n{file_list}"
    ),
    "dispatch.instructions_explore": (
        "\n## Instructions\n\n"
        "Investigate and answer the question using the available "
        "read and search tools. Do NOT modify any file. "
        "Respond with a concise and useful summary."
    ),
    "dispatch.instructions_test": (
        "\n## Instructions\n\n"
        "Run the relevant tests and report the results. "
        "Do NOT modify code. Only read files and run tests. "
        "Respond with a summary of which tests passed/failed."
    ),
    "dispatch.instructions_review": (
        "\n## Instructions\n\n"
        "Review the code in the relevant files. Look for bugs, "
        "design issues and improvement opportunities. "
        "Do NOT modify any file. Respond with a summary "
        "of your findings."
    ),
    # ── Ralph Loop ──────────────────────────────────────────────────────
    "ralph.spec_header": "## Task Specification\n\n{spec}",
    "ralph.task_header": "## Task\n\n{task}",
    "ralph.iteration_instructions": (
        "## Iteration Instructions\n\n"
        "This is **iteration {iteration}/{max_iterations}** "
        "of an automatic correction loop.\n\n"
        "When you have completed the ENTIRE task and are confident that "
        "everything works correctly, include the word "
        "`{completion_tag}` in your final response.\n\n"
        "**Checks your code must pass:**\n{checks_list}"
    ),
    "ralph.previous_diff": (
        "\n## Changes from Previous Iterations\n\n"
        "```diff\n{diff}\n```"
    ),
    "ralph.previous_errors_header": "\n## Errors from Previous Iteration\n",
    "ralph.execution_error_header": "\n## Execution Error\n\n```\n{error}\n```",
    "ralph.accumulated_progress": "\n## Accumulated Progress\n\n{content}",
    "ralph.progress_title": "# Ralph Loop — Progress\n\n",
    "ralph.progress_auto": "> Auto-generated. Do not edit manually.\n\n",
    "ralph.progress_iteration": "### Iteration {iteration}\n",
    "ralph.progress_status": "- Status: {status}\n",
    "ralph.progress_steps": "- Steps: {steps}\n",
    "ralph.progress_cost": "- Cost: ${cost:.4f}\n",
    "ralph.progress_duration": "- Duration: {duration:.1f}s\n",
    "ralph.progress_error": "- Error: {error}\n",
    "ralph.diff_truncated": "\n... (diff truncated)",
    # ── Reviewer ────────────────────────────────────────────────────────
    "reviewer.no_changes": "No changes to review.",
    "reviewer.diff_truncated": "\n... (diff truncated)",
    "reviewer.prompt": (
        "## Original Task\n{task}\n\n"
        "## Changes to Review\n```diff\n{diff}\n```\n\n"
        "Review these changes. List each issue found with format:\n"
        "- **[file:line]** Problem description. Fix suggestion.\n\n"
        "If there are no issues, respond exactly: 'No issues found.'"
    ),
    "reviewer.error": "Error in auto-review: {error}",
    "reviewer.fix_prompt": (
        "A reviewer found these problems in your code:\n\n"
        "{review_text}\n\n"
        "Fix these problems. Make sure each issue "
        "mentioned is resolved."
    ),
    # ── Reports: Health Delta ───────────────────────────────────────────
    "health.title": "## Code Health Delta\n",
    "health.radon_notice": (
        "> *radon not available — cyclomatic complexity not measured. "
        "Install with `pip install radon`.*\n"
    ),
    "health.col_metric": "Metric",
    "health.col_before": "Before",
    "health.col_after": "After",
    "health.col_delta": "Delta",
    "health.avg_complexity": "Avg complexity",
    "health.max_complexity": "Max complexity",
    "health.avg_lines": "Lines/function (avg)",
    "health.long_functions": "Long functions (>50 lines)",
    "health.complex_functions": "Complex functions (>10)",
    "health.duplicate_blocks": "Duplicate blocks",
    "health.files_analyzed": "**Files analyzed**: {count}",
    "health.functions_summary": (
        "**Functions**: {total} "
        "(+{new} new, -{removed} removed)"
    ),
    # ── Reports: Competitive Eval ───────────────────────────────────────
    "competitive.report_title": "# Competitive Eval Report\n",
    "competitive.task_label": "**Task**: {task}\n",
    "competitive.models_label": "**Models**: {count}\n",
    "competitive.checks_label": "**Checks**: {checks}\n",
    "competitive.results_header": "\n## Results\n",
    "competitive.col_model": "Model",
    "competitive.col_status": "Status",
    "competitive.col_steps": "Steps",
    "competitive.col_cost": "Cost",
    "competitive.col_time": "Time",
    "competitive.col_checks": "Checks",
    "competitive.col_files": "Files",
    "competitive.ranking_header": "\n## Ranking\n",
    "competitive.check_details_header": "\n## Check Details\n",
    "competitive.no_checks_run": "No checks were run.\n",
    "competitive.worktrees_header": "\n## Worktrees\n",
    "competitive.worktrees_desc": "To inspect each model's results:\n",
    # ── Reports: Dryrun ─────────────────────────────────────────────────
    "dryrun.plan_label": "Plan",
    "dryrun.tool_label": "Tool",
    "dryrun.args_label": "Args",
    # ── Pipelines ───────────────────────────────────────────────────────
    "pipeline.validation_error": (
        "Pipeline '{path}' has validation errors:\n{errors}"
    ),
    "pipeline.missing_prompt": "missing 'prompt' or it is empty",
    "pipeline.missing_prompt_hint": (
        "missing 'prompt' (the field 'task' is not valid, use 'prompt')"
    ),
    "pipeline.unknown_field": "unknown field '{field}'",
    "pipeline.unknown_field_hint": (
        "unknown field '{field}' (did you mean 'prompt'?)"
    ),
    "pipeline.invalid_step": "step must be a dict/object, not {type}",
    "pipeline.no_steps": "pipeline must have at least one step",
}
