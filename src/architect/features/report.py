"""
Execution Report — Generates execution reports in multiple formats.

Supports JSON (for CI/CD parsing), Markdown (human-readable), and a format
optimized for GitHub PR comments.
"""

import json
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ExecutionReport:
    """Complete data of an execution report.

    Collected by the AgentLoop during execution and passed
    to the ReportGenerator for formatting.
    """

    task: str
    agent: str
    model: str
    status: str
    duration_seconds: float
    steps: int
    total_cost: float
    files_modified: list[dict[str, Any]] = field(default_factory=list)
    quality_gates: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    git_diff: str | None = None
    timeline: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None


class ReportGenerator:
    """Generates reports in multiple formats from an ExecutionReport."""

    def __init__(self, report: ExecutionReport):
        """Initialize the generator.

        Args:
            report: ExecutionReport with the execution data.
        """
        self.report = report

    def to_json(self) -> str:
        """Report in JSON format (for CI/CD parsing).

        Returns:
            Indented JSON string.
        """
        return json.dumps(asdict(self.report), indent=2, default=str, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Human-readable Markdown report.

        Returns:
            String with the report formatted in Markdown.
        """
        r = self.report
        status_icon = {
            "success": "OK",
            "partial": "WARN",
            "failed": "FAIL",
        }.get(r.status, "?")

        lines = [
            "# Execution Report",
            "",
            "## Summary",
            "| Field | Value |",
            "|-------|-------|",
            f"| Task | {r.task} |",
            f"| Agent | {r.agent} ({r.model}) |",
            f"| Status | {status_icon} {r.status} |",
            f"| Duration | {r.duration_seconds:.1f}s |",
            f"| Steps | {r.steps} |",
            f"| Cost | ${r.total_cost:.4f} |",
        ]
        if r.stop_reason:
            lines.append(f"| Stop Reason | {r.stop_reason} |")
        lines.append("")

        # Files modified
        if r.files_modified:
            lines.append("## Files Modified")
            lines.append("| File | Action | Lines |")
            lines.append("|------|--------|-------|")
            for f in r.files_modified:
                added = f.get("lines_added", 0)
                removed = f.get("lines_removed", 0)
                lines.append(
                    f"| `{f['path']}` | {f.get('action', 'modified')} | "
                    f"+{added} -{removed} |"
                )
            lines.append("")

        # Quality gates
        if r.quality_gates:
            lines.append("## Quality Gates")
            for g in r.quality_gates:
                icon = "PASS" if g["passed"] else "FAIL"
                detail = ""
                if not g["passed"] and g.get("output"):
                    detail = f": {g['output'][:100]}"
                lines.append(f"- [{icon}] **{g['name']}**{detail}")
            lines.append("")

        # Errors
        if r.errors:
            lines.append("## Errors")
            for err in r.errors:
                lines.append(f"- {err}")
            lines.append("")

        # Timeline
        if r.timeline:
            lines.append("## Timeline")
            for t in r.timeline:
                cost_str = f", ${t.get('cost', 0):.4f}" if t.get("cost") else ""
                lines.append(
                    f"- **Step {t['step']}**: {t['tool']} "
                    f"({t.get('duration', 0):.1f}s{cost_str})"
                )
            lines.append("")

        return "\n".join(lines)

    def to_github_pr_comment(self) -> str:
        """Format optimized for GitHub PR comments.

        Returns:
            String with the comment formatted for GitHub.
        """
        r = self.report
        status = "OK" if r.status == "success" else "WARN"

        comment = f"## {status} architect: {r.task}\n\n"
        comment += (
            f"**{r.steps} steps** | "
            f"**{r.duration_seconds:.0f}s** | "
            f"**${r.total_cost:.3f}**\n\n"
        )

        if r.files_modified:
            comment += "<details><summary>Files modified</summary>\n\n"
            for f in r.files_modified:
                comment += f"- `{f['path']}` ({f.get('action', 'modified')})\n"
            comment += "\n</details>\n\n"

        if r.quality_gates:
            for g in r.quality_gates:
                icon = "PASS" if g["passed"] else "FAIL"
                comment += f"[{icon}] {g['name']}  "
            comment += "\n"

        if r.errors:
            comment += "\n<details><summary>Errors</summary>\n\n"
            for err in r.errors:
                comment += f"- {err}\n"
            comment += "\n</details>\n"

        return comment


def collect_git_diff(workspace_root: str | None = None) -> str | None:
    """Collect the git diff from the current workspace.

    Args:
        workspace_root: Workspace directory. None = cwd.

    Returns:
        String with the diff, or None if there are no changes or not a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=workspace_root,
        )
        if result.returncode == 0 and result.stdout.strip():
            diff = result.stdout
            if len(diff) > 50000:
                diff = diff[:50000] + "\n... (diff truncated)"
            return diff
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None
