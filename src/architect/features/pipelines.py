"""
Pipeline Mode — Multi-step YAML workflow execution.

v4-C3: Allows defining workflows as sequences of steps in YAML.
Each step runs an agent with its own prompt, model, and configuration.
Steps can pass data between each other using {{name}} variables.
"""

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import structlog
import yaml

from architect.logging.levels import HUMAN

logger = structlog.get_logger()
_hlog = logging.getLogger("architect.pipeline")

__all__ = [
    "PipelineConfig",
    "PipelineRunner",
    "PipelineStep",
    "PipelineStepResult",
    "PipelineValidationError",
]


class PipelineValidationError(ValueError):
    """Pipeline YAML validation error."""


# Valid fields in each pipeline step.
_VALID_STEP_FIELDS = frozenset({
    "name", "agent", "prompt", "model", "checkpoint",
    "condition", "output_var", "checks", "timeout",
})

# Type alias for agent factory.
AgentFactory = Callable[..., Any]


@dataclass
class PipelineStep:
    """Definition of a pipeline step."""

    name: str
    agent: str = "build"
    prompt: str = ""
    model: str | None = None
    checkpoint: bool = False
    condition: str | None = None
    output_var: str | None = None
    checks: list[str] = field(default_factory=list)
    timeout: int | None = None


@dataclass
class PipelineConfig:
    """Complete configuration of a pipeline."""

    name: str
    steps: list[PipelineStep]
    variables: dict[str, str] = field(default_factory=dict)


@dataclass
class PipelineStepResult:
    """Result of a pipeline step."""

    step_name: str
    status: str  # "success" | "partial" | "failed" | "skipped"
    cost: float = 0.0
    duration: float = 0.0
    checks_passed: bool = True
    error: str | None = None


class PipelineRunner:
    """Executes multi-step YAML workflows.

    Each step is executed sequentially with a fresh agent.
    Steps can pass data between each other using {{name}} variables
    defined with output_var.
    """

    def __init__(
        self,
        config: PipelineConfig,
        agent_factory: AgentFactory,
        workspace_root: str | None = None,
    ):
        """Initialize the pipeline runner.

        Args:
            config: Pipeline configuration.
            agent_factory: Callable that creates an AgentLoop. Receives kwargs: agent, model.
            workspace_root: Root directory of the workspace. None = cwd.
        """
        self.config = config
        self.agent_factory = agent_factory
        self.workspace_root = workspace_root or str(Path.cwd())
        self.variables: dict[str, str] = dict(config.variables)
        self.results: list[PipelineStepResult] = []
        self.log = logger.bind(component="pipeline_runner", pipeline=config.name)

    def run(self, from_step: str | None = None, dry_run: bool = False) -> list[PipelineStepResult]:
        """Execute the pipeline step by step.

        Args:
            from_step: Name of the step to start from. None = beginning.
            dry_run: If True, shows the plan without executing.

        Returns:
            List of PipelineStepResult for each executed step.
        """
        steps = self.config.steps
        start_index = 0

        # Find starting step if specified
        if from_step:
            for i, step in enumerate(steps):
                if step.name == from_step:
                    start_index = i
                    break
            else:
                self.log.error("pipeline.step_not_found", step=from_step)
                return []

        self.log.info(
            "pipeline.start",
            name=self.config.name,
            total_steps=len(steps),
            from_step=from_step,
        )

        for i in range(start_index, len(steps)):
            step = steps[i]

            self.log.info(
                "pipeline.step_start",
                step=step.name,
                index=i + 1,
                total=len(steps),
            )
            _hlog.log(HUMAN, {
                "event": "pipeline.step_start",
                "step": step.name,
                "agent": step.agent,
                "index": i + 1,
                "total": len(steps),
            })

            # Evaluate condition
            if step.condition and not self._eval_condition(step.condition):
                self.log.info(
                    "pipeline.step_skipped",
                    step=step.name,
                    reason="condition_not_met",
                )
                _hlog.log(HUMAN, {
                    "event": "pipeline.step_skipped",
                    "step": step.name,
                })
                self.results.append(PipelineStepResult(
                    step_name=step.name,
                    status="skipped",
                ))
                continue

            # Resolve variables in the prompt
            prompt = self._resolve_vars(step.prompt)

            if dry_run:
                self.log.info(
                    "pipeline.step_dry_run",
                    step=step.name,
                    agent=step.agent,
                    prompt_preview=prompt[:100],
                )
                self.results.append(PipelineStepResult(
                    step_name=step.name,
                    status="dry_run",
                ))
                continue

            # Execute agent
            step_result = self._execute_step(step, prompt)
            self.results.append(step_result)

            # Run step checks
            if step.checks:
                check_results = self._run_checks(step.checks)
                failed = [c for c in check_results if not c["passed"]]
                step_result.checks_passed = len(failed) == 0
                if failed:
                    self.log.info(
                        "pipeline.step_checks_failed",
                        step=step.name,
                        failed=[c["name"] for c in failed],
                    )

            self.log.info(
                "pipeline.step_done",
                step=step.name,
                status=step_result.status,
                cost=step_result.cost,
            )
            _hlog.log(HUMAN, {
                "event": "pipeline.step_done",
                "step": step.name,
                "status": step_result.status,
                "cost": step_result.cost,
                "duration": step_result.duration,
            })

            # Checkpoint if requested
            if step.checkpoint:
                self._create_checkpoint(step.name)

        self.log.info(
            "pipeline.complete",
            name=self.config.name,
            steps_executed=len(self.results),
        )
        return self.results

    def _execute_step(self, step: PipelineStep, prompt: str) -> PipelineStepResult:
        """Execute an individual pipeline step.

        Args:
            step: Step definition.
            prompt: Resolved prompt (variables already substituted).

        Returns:
            PipelineStepResult with metrics.
        """
        import time

        start = time.time()
        try:
            agent = self.agent_factory(
                agent=step.agent,
                model=step.model,
            )
            result = agent.run(prompt)
            duration = time.time() - start

            # Extract metrics from the result
            status = getattr(result, "status", "unknown")
            cost = 0.0
            if hasattr(result, "cost_tracker") and result.cost_tracker:
                cost = result.cost_tracker.total_cost_usd
            final_response = getattr(result, "final_output", "") or ""

            # Save output to variable if specified
            if step.output_var:
                self.variables[step.output_var] = final_response

            return PipelineStepResult(
                step_name=step.name,
                status=status,
                cost=cost,
                duration=duration,
            )

        except Exception as e:
            self.log.error(
                "pipeline.step_error",
                step=step.name,
                error=str(e),
            )
            return PipelineStepResult(
                step_name=step.name,
                status="failed",
                duration=time.time() - start,
                error=str(e),
            )

    def _resolve_vars(self, template: str) -> str:
        """Resolve {{variable}} placeholders in the template.

        Args:
            template: String with possible {{variable}} placeholders to resolve.

        Returns:
            Template with variables replaced.
        """
        def replacer(match: re.Match[str]) -> str:
            var_name = match.group(1).strip()
            return self.variables.get(var_name, match.group(0))

        return re.sub(r"\{\{(.+?)\}\}", replacer, template)

    def _eval_condition(self, condition: str) -> bool:
        """Evaluate a simple condition.

        Resolves variables and evaluates truthy/falsy values.

        Args:
            condition: Expression with possible {{variables}}.

        Returns:
            True if the condition is met.
        """
        resolved = self._resolve_vars(condition)
        if resolved.lower() in ("true", "yes", "1"):
            return True
        if resolved.lower() in ("false", "no", "0", ""):
            return False
        return bool(resolved.strip())

    def _run_checks(self, checks: list[str]) -> list[dict[str, Any]]:
        """Run verification commands.

        Args:
            checks: List of shell commands to execute.

        Returns:
            List of {name, passed, output}.
        """
        results: list[dict[str, Any]] = []
        for cmd in checks:
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=self.workspace_root,
                )
                results.append({
                    "name": cmd,
                    "passed": proc.returncode == 0,
                    "output": (proc.stdout + proc.stderr)[-500:],
                })
            except subprocess.TimeoutExpired:
                results.append({
                    "name": cmd,
                    "passed": False,
                    "output": "Timeout",
                })
        return results

    def _create_checkpoint(self, step_name: str) -> None:
        """Create a git checkpoint after a step.

        Args:
            step_name: Step name for the commit message.
        """
        try:
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True,
                cwd=self.workspace_root,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 f"architect:checkpoint:{step_name}",
                 "--allow-empty"],
                capture_output=True,
                cwd=self.workspace_root,
            )
            self.log.info("pipeline.checkpoint_created", step=step_name)
        except Exception as e:
            self.log.warning("pipeline.checkpoint_error", step=step_name, error=str(e))

    def get_plan_summary(self) -> str:
        """Generate a summary of the pipeline plan (for dry-run).

        Returns:
            Summary in markdown format.
        """
        lines = [
            f"# Pipeline: {self.config.name}\n",
            f"Steps: {len(self.config.steps)}\n",
        ]
        if self.config.variables:
            lines.append(f"Variables: {', '.join(self.config.variables.keys())}\n")
        lines.append("")

        for i, step in enumerate(self.config.steps, 1):
            prompt_preview = self._resolve_vars(step.prompt)[:80]
            condition_str = f" (if: {step.condition})" if step.condition else ""
            checkpoint_str = " [checkpoint]" if step.checkpoint else ""
            lines.append(
                f"{i}. **{step.name}** ({step.agent}){condition_str}{checkpoint_str}\n"
                f"   {prompt_preview}..."
            )

        return "\n".join(lines)

    @staticmethod
    def _validate_steps(steps_data: list[Any], path: str) -> list["PipelineStep"]:
        """Validate and parse pipeline steps from YAML.

        Validations:
        - At least 1 step defined.
        - Each step must have a non-empty 'prompt'.
        - Unknown fields raise an error (e.g., 'task' instead of 'prompt').
        - Each step must have a 'name'.

        Args:
            steps_data: Raw list of steps from YAML.
            path: File path (for error messages).

        Returns:
            List of validated PipelineStep objects.

        Raises:
            PipelineValidationError: If any validation fails.
        """
        if not steps_data:
            raise PipelineValidationError(
                f"Pipeline '{path}' has no steps defined."
            )

        errors: list[str] = []
        steps: list[PipelineStep] = []

        for i, s in enumerate(steps_data):
            step_label = s.get("name", f"step-{i + 1}") if isinstance(s, dict) else f"step-{i + 1}"

            if not isinstance(s, dict):
                errors.append(f"  {step_label}: must be a YAML object, not {type(s).__name__}")
                continue

            # Detect unknown fields
            unknown = set(s.keys()) - _VALID_STEP_FIELDS
            for field_name in sorted(unknown):
                hint = ""
                if field_name == "task":
                    hint = " (did you mean 'prompt'?)"
                errors.append(f"  {step_label}: unknown field '{field_name}'{hint}")

            # Validate that prompt is required and non-empty
            prompt = s.get("prompt")
            if not prompt or not str(prompt).strip():
                if "task" in s:
                    errors.append(
                        f"  {step_label}: missing 'prompt' (the 'task' field is not valid, use 'prompt')"
                    )
                else:
                    errors.append(f"  {step_label}: missing 'prompt' or it is empty")
                continue

            # Parse valid step
            checks = s.get("checks", [])
            if isinstance(checks, str):
                checks = [checks]
            steps.append(PipelineStep(
                name=s.get("name", f"step-{i + 1}"),
                agent=s.get("agent", "build"),
                prompt=str(prompt),
                model=s.get("model"),
                checkpoint=s.get("checkpoint", False),
                condition=s.get("condition"),
                output_var=s.get("output_var"),
                checks=checks,
                timeout=s.get("timeout"),
            ))

        if errors:
            error_list = "\n".join(errors)
            raise PipelineValidationError(
                f"Pipeline '{path}' has validation errors:\n{error_list}"
            )

        return steps

    @classmethod
    def from_yaml(
        cls,
        path: str,
        variables: dict[str, str],
        agent_factory: AgentFactory,
        workspace_root: str | None = None,
    ) -> "PipelineRunner":
        """Load pipeline from a YAML file.

        Args:
            path: Path to the YAML file.
            variables: Initial variables (from CLI --var).
            agent_factory: Callable that creates AgentLoops.
            workspace_root: Root directory of the workspace.

        Returns:
            Configured PipelineRunner.

        Raises:
            FileNotFoundError: If the file does not exist.
            yaml.YAMLError: If the YAML is invalid.
            PipelineValidationError: If the YAML content is not valid.
        """
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Pipeline file not found: {path}")

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not data or not isinstance(data, dict):
            raise PipelineValidationError(f"Invalid pipeline YAML: {path}")

        steps_data = data.get("steps", [])
        steps = cls._validate_steps(steps_data, path)

        # Merge YAML variables and CLI variables (CLI takes priority)
        yaml_vars = data.get("variables", {}) or {}
        merged_vars = {**yaml_vars, **variables}

        config = PipelineConfig(
            name=data.get("name", yaml_path.stem),
            steps=steps,
            variables=merged_vars,
        )

        return cls(config, agent_factory, workspace_root)
