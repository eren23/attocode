"""Experiment data models for research campaigns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Experiment:
    """A single experiment in a research campaign."""

    experiment_id: str
    iteration: int
    hypothesis: str
    parent_experiment_id: str = ""
    related_experiment_ids: list[str] = field(default_factory=list)
    strategy: str = "explore"
    status: str = "queued"  # queued|running|candidate|validated|held|killed|accepted|rejected|invalid|error
    branch: str = ""
    worktree_path: str = ""
    commit_hash: str = ""
    diff: str = ""
    metric_value: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    baseline_value: float | None = None
    accepted: bool = False
    reject_reason: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    files_modified: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    raw_output: str = ""
    error: str = ""
    steering_notes: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "iteration": self.iteration,
            "hypothesis": self.hypothesis,
            "parent_experiment_id": self.parent_experiment_id,
            "related_experiment_ids": self.related_experiment_ids,
            "strategy": self.strategy,
            "status": self.status,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "commit_hash": self.commit_hash,
            "diff": self.diff[:4000],
            "metric_value": self.metric_value,
            "metrics": self.metrics,
            "baseline_value": self.baseline_value,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "duration_s": self.duration_s,
            "files_modified": self.files_modified,
            "artifacts": self.artifacts,
            "raw_output": self.raw_output[:4000],
            "error": self.error,
            "steering_notes": self.steering_notes,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class FindingRecord:
    """A structured finding derived from one or more experiments."""

    finding_id: str
    experiment_id: str
    claim: str
    evidence: str = ""
    confidence: float = 0.5
    scope: str = "experiment"
    composeability: str = "unknown"
    status: str = "proposed"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "experiment_id": self.experiment_id,
            "claim": self.claim,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "scope": self.scope,
            "composeability": self.composeability,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class SteeringNote:
    """Human guidance that can bias future hypothesis generation."""

    note_id: str
    run_id: str
    content: str
    scope: str = "global"
    target: str = ""
    active: bool = True
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "run_id": self.run_id,
            "content": self.content,
            "scope": self.scope,
            "target": self.target,
            "active": self.active,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class ResearchState:
    """Overall state of a research campaign."""

    run_id: str = ""
    goal: str = ""
    metric_name: str = "score"
    metric_direction: str = "maximize"
    baseline_value: float | None = None
    best_value: float | None = None
    best_experiment_id: str = ""
    best_branch: str = ""
    total_experiments: int = 0
    accepted_count: int = 0
    candidate_count: int = 0
    held_count: int = 0
    killed_count: int = 0
    rejected_count: int = 0
    invalid_count: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    wall_seconds: float = 0.0
    active_experiments: int = 0
    status: str = "running"  # running|completed|budget_exceeded|error
    error: str = ""

    def is_improvement(self, candidate: float, baseline: float) -> bool:
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
            "best_branch": self.best_branch,
            "total_experiments": self.total_experiments,
            "accepted_count": self.accepted_count,
            "candidate_count": self.candidate_count,
            "held_count": self.held_count,
            "killed_count": self.killed_count,
            "rejected_count": self.rejected_count,
            "invalid_count": self.invalid_count,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
            "wall_seconds": round(self.wall_seconds, 1),
            "active_experiments": self.active_experiments,
            "status": self.status,
        }
