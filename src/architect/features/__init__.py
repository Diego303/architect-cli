"""
Features avanzadas de architect — módulos post-core.

Fase B: Sessions, Reports, CI/CD flags, Dry Run.
Fase C: Ralph Loop, Parallel Runs, Pipelines, Checkpoints.
Fase D: Competitive Eval.
"""

from .checkpoints import Checkpoint, CheckpointManager
from .competitive import CompetitiveConfig, CompetitiveEval, CompetitiveResult
from .dryrun import DryRunTracker
from .parallel import ParallelConfig, ParallelRunner, WorkerResult
from .pipelines import PipelineConfig, PipelineRunner, PipelineStep, PipelineStepResult
from .ralph import LoopIteration, RalphConfig, RalphLoop, RalphLoopResult
from .report import ExecutionReport, ReportGenerator
from .sessions import SessionManager, SessionState

__all__ = [
    # Phase B
    "DryRunTracker",
    "ExecutionReport",
    "ReportGenerator",
    "SessionManager",
    "SessionState",
    # Phase C
    "Checkpoint",
    "CheckpointManager",
    "LoopIteration",
    "ParallelConfig",
    "ParallelRunner",
    "PipelineConfig",
    "PipelineRunner",
    "PipelineStep",
    "PipelineStepResult",
    "RalphConfig",
    "RalphLoop",
    "RalphLoopResult",
    "WorkerResult",
    # Phase D
    "CompetitiveConfig",
    "CompetitiveEval",
    "CompetitiveResult",
]
