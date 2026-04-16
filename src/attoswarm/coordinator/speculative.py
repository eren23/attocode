"""Speculative execution for pre-warming almost-ready tasks.

When all dependencies of a task are currently ``running`` (not yet done),
the task can be speculatively started with "provisional" status.  If a
dependency fails, the speculative task is cancelled.

This is opt-in via ``AdaptiveConfig.speculative_enabled``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.coordinator.aot_graph import AoTGraph
    from attoswarm.coordinator.budget_gate import BudgetGate
    from attoswarm.coordinator.health_monitor import HealthMonitor

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SpeculativeCandidate:
    """A task eligible for speculative execution."""

    task_id: str
    running_deps: list[str]
    confidence: float  # min health score of models used by running deps
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "running_deps": self.running_deps,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
        }


class SpeculativeExecutor:
    """Identifies and manages speculative task execution.

    Usage::

        executor = SpeculativeExecutor(
            aot_graph=graph,
            health_monitor=monitor,
            budget_gate=gate,
            confidence_threshold=0.8,
        )
        candidates = executor.get_candidates()
        for c in candidates:
            dispatch_speculative(c.task_id)

        # On dependency failure:
        to_cancel = executor.on_dep_failed("dep-task-1")
    """

    def __init__(
        self,
        aot_graph: AoTGraph,
        health_monitor: HealthMonitor | None = None,
        budget_gate: BudgetGate | None = None,
        confidence_threshold: float = 0.8,
    ) -> None:
        self._graph = aot_graph
        self._health = health_monitor
        self._budget_gate = budget_gate
        self._confidence_threshold = confidence_threshold
        self._speculative_tasks: set[str] = set()

    def get_candidates(
        self,
        running_models: dict[str, str] | None = None,
    ) -> list[SpeculativeCandidate]:
        """Find tasks whose deps are all currently running.

        Args:
            running_models: Mapping of task_id -> model for currently running tasks.
                Used to check model health for confidence scoring.

        Returns:
            List of candidates meeting all criteria.
        """
        candidates: list[SpeculativeCandidate] = []
        almost_ready = self._get_almost_ready()

        for task_id, running_deps in almost_ready.items():
            # Skip if already running or speculative
            if task_id in self._speculative_tasks:
                continue

            # Check model health confidence
            confidence = self._compute_confidence(running_deps, running_models or {})
            if confidence < self._confidence_threshold:
                continue

            # Check AST conflicts with running tasks
            node = self._graph.get_node(task_id)
            if node and self._has_conflicts_with_running(node.target_files):
                continue

            # Check budget
            if self._budget_gate:
                decision = self._budget_gate.can_dispatch(task_id)
                if not decision.allowed:
                    continue

            candidates.append(SpeculativeCandidate(
                task_id=task_id,
                running_deps=running_deps,
                confidence=confidence,
                reason="all deps running, health ok",
            ))

        return candidates

    def mark_speculative(self, task_id: str) -> None:
        """Mark a task as speculatively running."""
        self._speculative_tasks.add(task_id)

    def on_dep_failed(self, failed_task_id: str) -> list[str]:
        """When a dependency fails, return speculative tasks that should be cancelled."""
        to_cancel: list[str] = []
        for spec_id in list(self._speculative_tasks):
            node = self._graph.get_node(spec_id)
            if node and failed_task_id in node.depends_on:
                to_cancel.append(spec_id)
                self._speculative_tasks.discard(spec_id)
        return to_cancel

    def on_dep_completed(self, task_id: str) -> None:
        """When all deps of a speculative task complete, promote to normal."""
        for spec_id in list(self._speculative_tasks):
            node = self._graph.get_node(spec_id)
            if not node:
                continue
            all_done = all(
                (self._graph.get_node(d) and self._graph.get_node(d).status == "done")  # type: ignore[union-attr]
                for d in node.depends_on
            )
            if all_done:
                self._speculative_tasks.discard(spec_id)
                logger.debug("Speculative task %s promoted to normal (all deps done)", spec_id)

    @property
    def speculative_tasks(self) -> set[str]:
        return set(self._speculative_tasks)

    def _get_almost_ready(self) -> dict[str, list[str]]:
        """Return tasks whose deps are all currently running."""
        result: dict[str, list[str]] = {}
        for node in self._graph.nodes.values():
            if node.status != "pending":
                continue
            if not node.depends_on:
                continue
            running_deps: list[str] = []
            all_running_or_done = True
            has_running = False
            for dep_id in node.depends_on:
                dep = self._graph.get_node(dep_id)
                if dep is None:
                    all_running_or_done = False
                    break
                if dep.status == "running":
                    running_deps.append(dep_id)
                    has_running = True
                elif dep.status == "done":
                    pass  # already completed — fine
                else:
                    all_running_or_done = False
                    break
            if all_running_or_done and has_running:
                result[node.task_id] = running_deps
        return result

    def _compute_confidence(
        self,
        running_deps: list[str],
        running_models: dict[str, str],
    ) -> float:
        """Compute confidence based on model health of running deps."""
        if not self._health or not running_deps:
            return 1.0  # No health data — assume confident

        scores: list[float] = []
        for dep_id in running_deps:
            model = running_models.get(dep_id, "")
            if model:
                health = self._health.get_health(model)
                scores.append(health.health_score if health else 1.0)
            else:
                scores.append(1.0)

        return min(scores) if scores else 1.0

    def _has_conflicts_with_running(self, target_files: list[str]) -> bool:
        """Check if target files overlap with any running task's target files."""
        if not target_files:
            return False
        target_set = set(target_files)
        for node in self._graph.nodes.values():
            if node.status == "running" and node.target_files:
                if target_set & set(node.target_files):
                    return True
        return False
