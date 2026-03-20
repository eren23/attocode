"""Post-hoc decomposition quality metrics.

Scores the decomposition based on execution outcomes:
- Granularity score: duration distribution analysis
- Dependency accuracy: predicted vs actual file access
- File scope accuracy: target_files vs files_modified
- Parallel efficiency: actual vs theoretical parallelism
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DecomposeScorecard:
    """Decomposition quality scorecard."""

    granularity_score: float = 0.0     # 0-1: 1 = good distribution
    dependency_accuracy: float = 0.0   # 0-1: 1 = all deps correct
    file_scope_accuracy: float = 0.0   # 0-1: 1 = predicted == actual
    parallel_efficiency: float = 0.0   # 0-1: 1 = perfect parallelism
    overall_score: float = 0.0        # weighted average

    def to_dict(self) -> dict[str, Any]:
        return {
            "granularity_score": round(self.granularity_score, 3),
            "dependency_accuracy": round(self.dependency_accuracy, 3),
            "file_scope_accuracy": round(self.file_scope_accuracy, 3),
            "parallel_efficiency": round(self.parallel_efficiency, 3),
            "overall_score": round(self.overall_score, 3),
        }


class DecomposeMetrics:
    """Computes decomposition quality from execution outcomes.

    Usage::

        metrics = DecomposeMetrics()
        scorecard = metrics.score(
            task_data=task_data,
            wall_clock_s=120.0,
            max_concurrency=4,
        )
    """

    def score(
        self,
        task_data: dict[str, dict[str, Any]],
        wall_clock_s: float = 0.0,
        max_concurrency: int = 4,
    ) -> DecomposeScorecard:
        """Compute all decomposition quality metrics.

        Args:
            task_data: Dict of task_id -> task state dict (from trace query or persist).
            wall_clock_s: Total execution wall-clock time.
            max_concurrency: Maximum concurrent workers.
        """
        scorecard = DecomposeScorecard()

        scorecard.granularity_score = self._score_granularity(task_data)
        scorecard.dependency_accuracy = self._score_dependency_accuracy(task_data)
        scorecard.file_scope_accuracy = self._score_file_scope(task_data)
        scorecard.parallel_efficiency = self._score_parallel_efficiency(
            task_data, wall_clock_s, max_concurrency,
        )

        # Weighted average
        scorecard.overall_score = (
            scorecard.granularity_score * 0.25
            + scorecard.dependency_accuracy * 0.25
            + scorecard.file_scope_accuracy * 0.25
            + scorecard.parallel_efficiency * 0.25
        )

        return scorecard

    def _score_granularity(self, task_data: dict[str, dict[str, Any]]) -> float:
        """Score based on task duration distribution.

        Ideal: tasks take 30-300s. Timeouts = too big. <10s = too small.
        """
        if not task_data:
            return 0.5

        durations: list[float] = []
        for data in task_data.values():
            # Try to extract duration from attempt history
            history = data.get("attempt_history", [])
            if history:
                for attempt in history:
                    d = attempt.get("duration_s", 0.0)
                    if d > 0:
                        durations.append(d)
            else:
                # Fall back to tokens as proxy
                tokens = data.get("tokens_used", 0)
                if tokens > 0:
                    durations.append(tokens / 1000.0)  # rough proxy

        if not durations:
            return 0.5

        # Score: penalize extremes
        good = sum(1 for d in durations if 10.0 <= d <= 300.0)
        too_small = sum(1 for d in durations if d < 10.0)
        too_big = sum(1 for d in durations if d > 300.0)

        total = len(durations)
        score = good / total

        # Extra penalty for timeouts (very bad signal)
        timeout_penalty = too_big * 0.15
        too_small_penalty = too_small * 0.05

        return max(0.0, min(1.0, score - timeout_penalty - too_small_penalty))

    def _score_dependency_accuracy(self, task_data: dict[str, dict[str, Any]]) -> float:
        """Compare predicted deps with actual file access patterns.

        If task A writes file X and task B (no dep on A) also touches X,
        that's a missed dependency.
        """
        if not task_data:
            return 0.5

        # Build actual file writers
        file_writers: dict[str, list[str]] = {}
        for tid, data in task_data.items():
            for f in data.get("files_modified", []):
                file_writers.setdefault(f, []).append(tid)

        # Check for missing deps
        total_checks = 0
        correct = 0
        for tid, data in task_data.items():
            deps = set(data.get("deps", []))
            for f in data.get("files_modified", []):
                writers = file_writers.get(f, [])
                for writer in writers:
                    if writer != tid:
                        total_checks += 1
                        if writer in deps or tid in task_data.get(writer, {}).get("deps", []):
                            correct += 1

        if total_checks == 0:
            return 1.0  # No cross-file access = perfect
        return correct / total_checks

    def _score_file_scope(self, task_data: dict[str, dict[str, Any]]) -> float:
        """Compare target_files (predicted) vs files_modified (actual)."""
        if not task_data:
            return 0.5

        total_tasks = 0
        scope_scores: list[float] = []

        for data in task_data.values():
            target = set(data.get("target_files", []))
            modified = set(data.get("files_modified", []))

            if not target and not modified:
                continue

            total_tasks += 1

            if not target:
                scope_scores.append(0.0)
                continue
            if not modified:
                scope_scores.append(0.5)  # Can't tell if task was skipped
                continue

            # Jaccard similarity
            intersection = target & modified
            union = target | modified
            score = len(intersection) / len(union) if union else 0.0
            scope_scores.append(score)

        if not scope_scores:
            return 0.5
        return sum(scope_scores) / len(scope_scores)

    def _score_parallel_efficiency(
        self,
        task_data: dict[str, dict[str, Any]],
        wall_clock_s: float,
        max_concurrency: int,
    ) -> float:
        """Compute parallel efficiency: sum(durations) / (wall_clock * max_concurrency).

        1.0 = perfect utilization, 0.0 = fully sequential.
        """
        if not task_data or wall_clock_s <= 0 or max_concurrency <= 0:
            return 0.5

        total_task_time = 0.0
        for data in task_data.values():
            history = data.get("attempt_history", [])
            if history:
                for attempt in history:
                    d = attempt.get("duration_s", 0.0)
                    if d > 0:
                        total_task_time += d

        if total_task_time <= 0:
            return 0.5

        theoretical_min = total_task_time / max_concurrency
        # Efficiency = how close wall clock is to theoretical minimum
        if wall_clock_s <= 0:
            return 0.5
        efficiency = theoretical_min / wall_clock_s
        return min(1.0, max(0.0, efficiency))
