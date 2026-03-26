"""Research/Evaluation mode — iterative experimentation with numeric metrics.

Inspired by Karpathy's AutoResearch: one metric, one budget, iterate.
"""

from attoswarm.research.accept_policy import (
    AcceptPolicy,
    NeverRegressPolicy,
    StatisticalPolicy,
    ThresholdPolicy,
)
from attoswarm.research.config import ResearchConfig
from attoswarm.research.evaluator import (
    CommandEvaluator,
    CompositeEvaluator,
    EvalResult,
    Evaluator,
    ScriptEvaluator,
    TestPassRateEvaluator,
)
from attoswarm.research.experiment import Experiment, FindingRecord, ResearchState, SteeringNote
from attoswarm.research.experiment_db import ExperimentDB
from attoswarm.research.hypothesis import HypothesisGenerator
from attoswarm.research.research_orchestrator import ResearchOrchestrator
from attoswarm.research.scoreboard import Scoreboard
from attoswarm.research.worktree_manager import WorktreeManager

__all__ = [
    "AcceptPolicy",
    "CommandEvaluator",
    "CompositeEvaluator",
    "EvalResult",
    "Evaluator",
    "Experiment",
    "ExperimentDB",
    "FindingRecord",
    "HypothesisGenerator",
    "NeverRegressPolicy",
    "ResearchConfig",
    "ResearchOrchestrator",
    "ResearchState",
    "Scoreboard",
    "ScriptEvaluator",
    "SteeringNote",
    "StatisticalPolicy",
    "TestPassRateEvaluator",
    "ThresholdPolicy",
    "WorktreeManager",
]
