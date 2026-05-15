"""pipeline-cli: Agent closed-loop pipeline with Claude."""

__version__ = "0.4.0"

from .config import Config, load_config
from .engine import QCFEngine
from .models import (
    ActionSuggestion,
    Issue,
    ReviewOutput,
    AuditOutput,
    StageMetrics,
    RoundStageMetric,
    RoundsOverview,
)
from .progress import AgentProgress
from .runner import run_claude

__all__ = [
    "Config", "load_config",
    "QCFEngine",
    "ActionSuggestion",
    "Issue", "ReviewOutput", "AuditOutput",
    "StageMetrics", "RoundStageMetric", "RoundsOverview",
    "AgentProgress",
    "run_claude",
]
