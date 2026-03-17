"""Experiment data model and research state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Experiment:
    """A single experiment in a research run."""

    experiment_id: str
    iteration: int
    hypothesis: str
    diff: str = ""
    metric_value: float | None = None
    baseline_value: float | None = None
    accepted: bool = False
    reject_reason: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    files_modified: list[str] = field(default_factory=list)
    error: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "iteration": self.iteration,
            "hypothesis": self.hypothesis,
            "diff": self.diff[:2000],  # cap for storage
            "metric_value": self.metric_value,
            "baseline_value": self.baseline_value,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "duration_s": self.duration_s,
            "files_modified": self.files_modified,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class ResearchState:
    """Overall state of a research run."""

    run_id: str = ""
    goal: str = ""
    metric_name: str = "score"
    metric_direction: str = "maximize"
    baseline_value: float | None = None
    best_value: float | None = None
    best_experiment_id: str = ""
    total_experiments: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    wall_seconds: float = 0.0
    status: str = "running"  # running|completed|budget_exceeded|error

    def is_improvement(self, candidate: float, baseline: float) -> bool:
        """Check if candidate is an improvement over baseline."""
        if self.metric_direction == "minimize":
            return candidate < baseline
        return candidate > baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "metric_name": self.metric_name,
            "metric_direction": self.metric_direction,
            "baseline_value": self.baseline_value,
            "best_value": self.best_value,
            "best_experiment_id": self.best_experiment_id,
            "total_experiments": self.total_experiments,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
            "wall_seconds": round(self.wall_seconds, 1),
            "status": self.status,
        }
