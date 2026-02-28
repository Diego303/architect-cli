"""
Pipeline Mode — Ejecución de workflows YAML multi-step.

v4-C3: Permite definir workflows como secuencias de pasos en YAML.
Cada paso ejecuta un agente con su propio prompt, modelo, y configuración.
Los pasos pueden pasar datos entre sí mediante variables {{nombre}}.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import structlog
import yaml

logger = structlog.get_logger()

__all__ = [
    "PipelineConfig",
    "PipelineRunner",
    "PipelineStep",
    "PipelineStepResult",
    "PipelineValidationError",
]


class PipelineValidationError(ValueError):
    """Error de validación del YAML de pipeline."""


# Campos válidos en cada step del pipeline.
_VALID_STEP_FIELDS = frozenset({
    "name", "agent", "prompt", "model", "checkpoint",
    "condition", "output_var", "checks", "timeout",
})

# Type alias for agent factory.
AgentFactory = Callable[..., Any]


@dataclass
class PipelineStep:
    """Definición de un paso del pipeline."""

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
    """Configuración completa de un pipeline."""

    name: str
    steps: list[PipelineStep]
    variables: dict[str, str] = field(default_factory=dict)


@dataclass
class PipelineStepResult:
    """Resultado de un paso del pipeline."""

    step_name: str
    status: str  # "success" | "partial" | "failed" | "skipped"
    cost: float = 0.0
    duration: float = 0.0
    checks_passed: bool = True
    error: str | None = None


class PipelineRunner:
    """Ejecuta workflows YAML multi-step.

    Cada step se ejecuta secuencialmente con un agente fresco.
    Los steps pueden pasar datos entre sí mediante variables {{nombre}}
    definidas con output_var.
    """

    def __init__(
        self,
        config: PipelineConfig,
        agent_factory: AgentFactory,
        workspace_root: str | None = None,
    ):
        """Inicializa el runner del pipeline.

        Args:
            config: Configuración del pipeline.
            agent_factory: Callable que crea un AgentLoop. Recibe kwargs: agent, model.
            workspace_root: Directorio raíz del workspace. None = cwd.
        """
        self.config = config
        self.agent_factory = agent_factory
        self.workspace_root = workspace_root or str(Path.cwd())
        self.variables: dict[str, str] = dict(config.variables)
        self.results: list[PipelineStepResult] = []
        self.log = logger.bind(component="pipeline_runner", pipeline=config.name)

    def run(self, from_step: str | None = None, dry_run: bool = False) -> list[PipelineStepResult]:
        """Ejecuta el pipeline paso a paso.

        Args:
            from_step: Nombre del paso desde el que empezar. None = inicio.
            dry_run: Si True, muestra el plan sin ejecutar.

        Returns:
            Lista de PipelineStepResult para cada paso ejecutado.
        """
        steps = self.config.steps
        start_index = 0

        # Encontrar paso de inicio si se especificó
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

            # Evaluar condición
            if step.condition and not self._eval_condition(step.condition):
                self.log.info(
                    "pipeline.step_skipped",
                    step=step.name,
                    reason="condition_not_met",
                )
                self.results.append(PipelineStepResult(
                    step_name=step.name,
                    status="skipped",
                ))
                continue

            # Resolver variables en el prompt
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

            # Ejecutar agente
            step_result = self._execute_step(step, prompt)
            self.results.append(step_result)

            # Ejecutar checks del paso
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

            # Checkpoint si se pidió
            if step.checkpoint:
                self._create_checkpoint(step.name)

        self.log.info(
            "pipeline.complete",
            name=self.config.name,
            steps_executed=len(self.results),
        )
        return self.results

    def _execute_step(self, step: PipelineStep, prompt: str) -> PipelineStepResult:
        """Ejecuta un paso individual del pipeline.

        Args:
            step: Definición del paso.
            prompt: Prompt resuelto (variables ya sustituidas).

        Returns:
            PipelineStepResult con métricas.
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

            # Extraer métricas del resultado
            status = getattr(result, "status", "unknown")
            cost = 0.0
            if hasattr(result, "cost_tracker") and result.cost_tracker:
                cost = result.cost_tracker.total_cost_usd
            final_response = getattr(result, "final_output", "") or ""

            # Guardar output en variable si se especificó
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
        """Resuelve {{variable}} en el template.

        Args:
            template: String con posibles {{variable}} a resolver.

        Returns:
            Template con variables reemplazadas.
        """
        def replacer(match: re.Match[str]) -> str:
            var_name = match.group(1).strip()
            return self.variables.get(var_name, match.group(0))

        return re.sub(r"\{\{(.+?)\}\}", replacer, template)

    def _eval_condition(self, condition: str) -> bool:
        """Evalúa condición simple.

        Resuelve variables y evalúa valores truthy/falsy.

        Args:
            condition: Expresión con posibles {{variables}}.

        Returns:
            True si la condición se cumple.
        """
        resolved = self._resolve_vars(condition)
        if resolved.lower() in ("true", "yes", "1"):
            return True
        if resolved.lower() in ("false", "no", "0", ""):
            return False
        return bool(resolved.strip())

    def _run_checks(self, checks: list[str]) -> list[dict[str, Any]]:
        """Ejecuta comandos de verificación.

        Args:
            checks: Lista de comandos shell a ejecutar.

        Returns:
            Lista de {name, passed, output}.
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
        """Crea un checkpoint git después de un paso.

        Args:
            step_name: Nombre del paso para el mensaje de commit.
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
        """Genera un resumen del plan del pipeline (para dry-run).

        Returns:
            Resumen en formato markdown.
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
        """Valida y parsea los steps del pipeline YAML.

        Validaciones:
        - Al menos 1 step definido.
        - Cada step debe tener 'prompt' no vacío.
        - Campos desconocidos generan error (ej: 'task' en vez de 'prompt').
        - Cada step debe tener 'name'.

        Args:
            steps_data: Lista cruda de steps del YAML.
            path: Path del archivo (para mensajes de error).

        Returns:
            Lista de PipelineStep validados.

        Raises:
            PipelineValidationError: Si alguna validación falla.
        """
        if not steps_data:
            raise PipelineValidationError(
                f"Pipeline '{path}' no tiene steps definidos."
            )

        errors: list[str] = []
        steps: list[PipelineStep] = []

        for i, s in enumerate(steps_data):
            step_label = s.get("name", f"step-{i + 1}") if isinstance(s, dict) else f"step-{i + 1}"

            if not isinstance(s, dict):
                errors.append(f"  {step_label}: debe ser un objeto YAML, no {type(s).__name__}")
                continue

            # Detectar campos desconocidos
            unknown = set(s.keys()) - _VALID_STEP_FIELDS
            for field_name in sorted(unknown):
                hint = ""
                if field_name == "task":
                    hint = " (¿quisiste decir 'prompt'?)"
                errors.append(f"  {step_label}: campo desconocido '{field_name}'{hint}")

            # Validar prompt requerido y no vacío
            prompt = s.get("prompt")
            if not prompt or not str(prompt).strip():
                if "task" in s:
                    errors.append(
                        f"  {step_label}: falta 'prompt' (el campo 'task' no es válido, usa 'prompt')"
                    )
                else:
                    errors.append(f"  {step_label}: falta 'prompt' o está vacío")
                continue

            # Parsear step válido
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
                f"Pipeline '{path}' tiene errores de validación:\n{error_list}"
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
        """Carga pipeline desde archivo YAML.

        Args:
            path: Path al archivo YAML.
            variables: Variables iniciales (desde CLI --var).
            agent_factory: Callable que crea AgentLoops.
            workspace_root: Directorio raíz del workspace.

        Returns:
            PipelineRunner configurado.

        Raises:
            FileNotFoundError: Si el archivo no existe.
            yaml.YAMLError: Si el YAML es inválido.
            PipelineValidationError: Si el contenido del YAML no es válido.
        """
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Pipeline file not found: {path}")

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not data or not isinstance(data, dict):
            raise PipelineValidationError(f"Invalid pipeline YAML: {path}")

        steps_data = data.get("steps", [])
        steps = cls._validate_steps(steps_data, path)

        # Mergear variables del YAML y las de CLI (CLI tiene prioridad)
        yaml_vars = data.get("variables", {}) or {}
        merged_vars = {**yaml_vars, **variables}

        config = PipelineConfig(
            name=data.get("name", yaml_path.stem),
            steps=steps,
            variables=merged_vars,
        )

        return cls(config, agent_factory, workspace_root)
