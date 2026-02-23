"""
Features avanzadas de architect — módulos post-core.

Fase B: Sessions, Reports, CI/CD flags, Dry Run.
"""

from .dryrun import DryRunTracker
from .report import ExecutionReport, ReportGenerator
from .sessions import SessionManager, SessionState

__all__ = [
    "DryRunTracker",
    "ExecutionReport",
    "ReportGenerator",
    "SessionManager",
    "SessionState",
]
