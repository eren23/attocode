"""Shared result record for standalone intelligence evaluations."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvalResult:
    """Result of an evaluation."""

    metric_value: float
    raw_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    constraint_checks: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    seed: int | None = None
    error: str = ""
    success: bool = True
