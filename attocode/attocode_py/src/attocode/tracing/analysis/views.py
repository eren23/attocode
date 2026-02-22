"""Data structures for trace analysis views.

These dataclasses represent the computed outputs of various analysis passes
over a :class:`~attocode.tracing.types.TraceSession`.  They are pure data --
no business logic, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SessionSummaryView:
    """Aggregate metrics for an entire trace session."""

    session_id: str
    goal: str
    model: str
    duration_seconds: float
    total_tokens: int
    total_cost: float
    iterations: int
    tool_calls: int
    llm_calls: int
    errors: int
    compactions: int
    efficiency_score: float  # 0-100
    cache_hit_rate: float  # 0.0-1.0
    avg_tokens_per_iteration: float
    avg_cost_per_iteration: float


@dataclass(slots=True)
class TimelineEntry:
    """A single row in the chronological event timeline."""

    timestamp: float
    event_kind: str
    iteration: int | None
    summary: str  # Human-readable one-liner
    duration_ms: float | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TreeNode:
    """A node in the hierarchical (iteration > events) tree view."""

    event_id: str
    kind: str
    label: str
    duration_ms: float | None = None
    children: list[TreeNode] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TokenFlowPoint:
    """Token usage snapshot for a single iteration."""

    iteration: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cumulative_cost: float = 0.0


@dataclass(slots=True)
class DetectedIssue:
    """A single inefficiency or anomaly detected in a trace session."""

    severity: str  # 'critical', 'high', 'medium', 'low'
    category: str
    title: str
    description: str
    iteration: int | None = None
    suggestion: str = ""
