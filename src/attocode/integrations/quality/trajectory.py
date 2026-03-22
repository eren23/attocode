"""Trajectory analysis for agent self-improvement.

Records thought-action-observation triples and detects
behavioral patterns: repetitive loops, productive exploration,
regression, and spinning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TrajectoryPattern(StrEnum):
    """Detected behavioral patterns."""
    PRODUCTIVE = "productive"
    REPETITIVE_LOOP = "repetitive_loop"
    REGRESSION = "regression"
    SPINNING = "spinning"
    EXPLORING = "exploring"
    STUCK = "stuck"


@dataclass(slots=True)
class TrajectoryTriple:
    """A single thought-action-observation triple."""
    iteration: int
    timestamp: float
    reasoning: str
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    success: bool = True
    tokens_used: int = 0


@dataclass(slots=True)
class PatternDetection:
    """Result of pattern analysis."""
    pattern: TrajectoryPattern
    confidence: float  # 0.0-1.0
    message: str = ""
    affected_iterations: list[int] = field(default_factory=list)


class TrajectoryTracker:
    """Records and analyzes agent execution trajectories.

    Tracks thought-action-observation triples across iterations
    and provides pattern detection for self-improvement.
    """

    def __init__(self, *, max_history: int = 200) -> None:
        self._triples: list[TrajectoryTriple] = []
        self._max_history = max_history
        self._patterns: list[PatternDetection] = []

    @property
    def triples(self) -> list[TrajectoryTriple]:
        return list(self._triples)

    @property
    def patterns(self) -> list[PatternDetection]:
        return list(self._patterns)

    def record(
        self,
        iteration: int,
        reasoning: str,
        *,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        result_summary: str = "",
        success: bool = True,
        tokens_used: int = 0,
    ) -> TrajectoryTriple:
        """Record a trajectory triple."""
        triple = TrajectoryTriple(
            iteration=iteration,
            timestamp=time.monotonic(),
            reasoning=reasoning,
            tool_name=tool_name,
            tool_args=tool_args or {},
            result_summary=result_summary,
            success=success,
            tokens_used=tokens_used,
        )
        self._triples.append(triple)
        if len(self._triples) > self._max_history:
            self._triples = self._triples[-self._max_history:]
        return triple

    def analyze(self, *, window: int = 10) -> list[PatternDetection]:
        """Analyze recent trajectory for patterns."""
        self._patterns.clear()
        if len(self._triples) < 3:
            return []

        recent = self._triples[-window:]

        self._detect_repetitive_loops(recent)
        self._detect_spinning(recent)
        self._detect_regression(recent)
        self._detect_productive(recent)

        return list(self._patterns)

    def detect_spinning(self, *, window: int = 6) -> bool:
        """Quick check: is the agent spinning (same actions, no progress)?"""
        if len(self._triples) < window:
            return False
        recent = self._triples[-window:]
        tool_names = [t.tool_name for t in recent if t.tool_name]
        if len(tool_names) < 3:
            return False
        unique_tools = set(tool_names)
        # Spinning: very few unique tools with many calls
        if len(unique_tools) <= 2 and len(tool_names) >= window - 1:
            failures = sum(1 for t in recent if not t.success)
            if failures >= len(recent) // 2:
                return True
        # Same tool+args repeated
        signatures = [(t.tool_name, str(sorted(t.tool_args.items()))) for t in recent if t.tool_name]
        unique_sigs = set(signatures)
        if len(unique_sigs) <= 2 and len(signatures) >= 4:
            return True
        return False

    def get_summary(self, *, last_n: int = 10) -> dict[str, Any]:
        """Get a summary of recent trajectory for /trace command."""
        recent = self._triples[-last_n:] if self._triples else []
        total_tokens = sum(t.tokens_used for t in recent)
        success_rate = (
            sum(1 for t in recent if t.success) / len(recent)
            if recent else 0.0
        )
        tool_counts: dict[str, int] = {}
        for t in recent:
            if t.tool_name:
                tool_counts[t.tool_name] = tool_counts.get(t.tool_name, 0) + 1

        patterns = self.analyze()

        return {
            "total_triples": len(self._triples),
            "recent_count": len(recent),
            "total_tokens": total_tokens,
            "success_rate": success_rate,
            "tool_distribution": tool_counts,
            "patterns": [
                {"pattern": p.pattern.value, "confidence": p.confidence, "message": p.message}
                for p in patterns
            ],
            "is_spinning": self.detect_spinning(),
        }

    def _detect_repetitive_loops(self, recent: list[TrajectoryTriple]) -> None:
        """Detect repetitive tool call patterns."""
        if len(recent) < 4:
            return
        tool_sequence = [t.tool_name for t in recent if t.tool_name]
        if len(tool_sequence) < 4:
            return
        # Check for repeating subsequences of length 2-3
        for pattern_len in (2, 3):
            for i in range(len(tool_sequence) - pattern_len * 2 + 1):
                pattern = tool_sequence[i:i + pattern_len]
                next_pattern = tool_sequence[i + pattern_len:i + pattern_len * 2]
                if pattern == next_pattern:
                    self._patterns.append(PatternDetection(
                        pattern=TrajectoryPattern.REPETITIVE_LOOP,
                        confidence=0.8,
                        message=f"Repeating tool sequence: {' → '.join(pattern)}",
                        affected_iterations=[t.iteration for t in recent[i:i + pattern_len * 2]],
                    ))
                    return

    def _detect_spinning(self, recent: list[TrajectoryTriple]) -> None:
        """Detect spinning (same actions, no progress)."""
        if self.detect_spinning(window=len(recent)):
            self._patterns.append(PatternDetection(
                pattern=TrajectoryPattern.SPINNING,
                confidence=0.9,
                message="Agent appears to be spinning — repeating same actions without progress",
                affected_iterations=[t.iteration for t in recent],
            ))

    def _detect_regression(self, recent: list[TrajectoryTriple]) -> None:
        """Detect regression: success rate dropping over time."""
        if len(recent) < 6:
            return
        mid = len(recent) // 2
        first_half = recent[:mid]
        second_half = recent[mid:]
        first_success = sum(1 for t in first_half if t.success) / len(first_half) if first_half else 1.0
        second_success = sum(1 for t in second_half if t.success) / len(second_half) if second_half else 1.0
        if first_success > 0.7 and second_success < 0.4:
            self._patterns.append(PatternDetection(
                pattern=TrajectoryPattern.REGRESSION,
                confidence=0.7,
                message=f"Success rate dropped from {first_success:.0%} to {second_success:.0%}",
                affected_iterations=[t.iteration for t in second_half],
            ))

    def _detect_productive(self, recent: list[TrajectoryTriple]) -> None:
        """Detect productive exploration."""
        if not recent:
            return
        success_rate = sum(1 for t in recent if t.success) / len(recent)
        unique_tools = len({t.tool_name for t in recent if t.tool_name})
        if success_rate >= 0.7 and unique_tools >= 3:
            self._patterns.append(PatternDetection(
                pattern=TrajectoryPattern.PRODUCTIVE,
                confidence=success_rate,
                message=f"Productive: {success_rate:.0%} success, {unique_tools} diverse tools",
            ))

    def clear(self) -> None:
        """Clear all recorded triples and patterns."""
        self._triples.clear()
        self._patterns.clear()
