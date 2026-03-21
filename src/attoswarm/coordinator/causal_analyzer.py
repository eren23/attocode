"""Causal chain analyzer for failure root-cause analysis.

Wraps ``FailureAnalyzer.trace_root_cause()`` with memoization and
blast-radius computation.  Automatically builds causal chains on
every failure for post-mortem analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.coordinator.aot_graph import AoTGraph
    from attoswarm.coordinator.failure_analyzer import FailureAnalyzer, FailureAttribution

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CausalChain:
    """A causal chain from a failed task to its root cause."""

    task_id: str
    root_cause_id: str
    chain: list[str]  # task_id path from leaf to root
    cause: str
    confidence: float
    blast_radius: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "root_cause_id": self.root_cause_id,
            "chain": self.chain,
            "cause": self.cause,
            "confidence": round(self.confidence, 3),
            "blast_radius": self.blast_radius,
        }


@dataclass(slots=True)
class RootCause:
    """A unique root cause found in the run."""

    task_id: str
    cause: str
    confidence: float
    affected_tasks: list[str] = field(default_factory=list)
    wasted_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "cause": self.cause,
            "confidence": round(self.confidence, 3),
            "affected_tasks": self.affected_tasks,
            "wasted_cost": round(self.wasted_cost, 4),
        }


@dataclass(slots=True)
class BlastRadius:
    """Blast radius of a task failure."""

    task_id: str
    directly_blocked: list[str] = field(default_factory=list)
    transitively_blocked: list[str] = field(default_factory=list)
    wasted_cost: float = 0.0

    @property
    def total_blocked(self) -> int:
        return len(self.directly_blocked) + len(self.transitively_blocked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "directly_blocked": self.directly_blocked,
            "transitively_blocked": self.transitively_blocked,
            "total_blocked": self.total_blocked,
            "wasted_cost": round(self.wasted_cost, 4),
        }


class CausalChainAnalyzer:
    """Reconstructs causal chains and computes blast radii.

    Usage::

        analyzer = CausalChainAnalyzer(aot_graph, failure_analyzer)
        chain = analyzer.analyze_failure(task_id, failure_attr)
        root_causes = analyzer.get_root_causes()
        blast = analyzer.get_blast_radius(task_id)
    """

    def __init__(
        self,
        aot_graph: AoTGraph,
        failure_analyzer: FailureAnalyzer,
    ) -> None:
        self._graph = aot_graph
        self._analyzer = failure_analyzer
        self._failure_cache: dict[str, FailureAttribution] = {}
        self._chains: dict[str, CausalChain] = {}
        self._task_costs: dict[str, float] = {}

    def record_task_cost(self, task_id: str, cost: float) -> None:
        """Record the cost spent on a task (for wasted cost computation)."""
        self._task_costs[task_id] = self._task_costs.get(task_id, 0.0) + cost

    def analyze_failure(
        self,
        task_id: str,
        failure_attr: FailureAttribution | None = None,
    ) -> CausalChain:
        """Trace the causal chain for a failure.

        Uses memoized ``trace_root_cause()`` and computes blast radius.
        """
        # Check cache
        if task_id in self._chains:
            return self._chains[task_id]

        # Trace root cause
        root_attr = self._analyzer.trace_root_cause(
            task_id, self._graph, self._failure_cache,
        )

        # Cache the attribution
        if failure_attr:
            self._failure_cache[task_id] = failure_attr

        # Compute blast radius
        blast_data = self._graph.get_blast_radius(task_id)

        # Calculate wasted cost on blocked tasks
        blocked_ids = set(blast_data.get("directly_blocked", []) + blast_data.get("transitively_blocked", []))
        wasted = sum(self._task_costs.get(tid, 0.0) for tid in blocked_ids)

        chain = CausalChain(
            task_id=task_id,
            root_cause_id=root_attr.root_task_id or task_id,
            chain=root_attr.chain or [task_id],
            cause=root_attr.cause,
            confidence=root_attr.confidence,
            blast_radius={
                "directly_blocked": blast_data.get("directly_blocked", []),
                "transitively_blocked": blast_data.get("transitively_blocked", []),
                "total_blocked": blast_data.get("total_blocked", 0),
                "wasted_cost": round(wasted, 4),
            },
        )
        self._chains[task_id] = chain
        return chain

    def get_root_causes(self) -> list[RootCause]:
        """Return all unique root causes found in the run."""
        root_map: dict[str, RootCause] = {}

        for chain in self._chains.values():
            root_id = chain.root_cause_id
            if root_id not in root_map:
                root_map[root_id] = RootCause(
                    task_id=root_id,
                    cause=chain.cause,
                    confidence=chain.confidence,
                )
            root = root_map[root_id]
            if chain.task_id not in root.affected_tasks:
                root.affected_tasks.append(chain.task_id)

        # Compute wasted cost per root cause
        for root in root_map.values():
            root.wasted_cost = sum(
                self._task_costs.get(tid, 0.0)
                for tid in root.affected_tasks
                if tid != root.task_id
            )

        return sorted(root_map.values(), key=lambda r: len(r.affected_tasks), reverse=True)

    def get_blast_radius(self, task_id: str) -> BlastRadius:
        """Compute the blast radius of a specific task failure."""
        blast_data = self._graph.get_blast_radius(task_id)
        blocked_ids = set(
            blast_data.get("directly_blocked", [])
            + blast_data.get("transitively_blocked", [])
        )
        wasted = sum(self._task_costs.get(tid, 0.0) for tid in blocked_ids)

        return BlastRadius(
            task_id=task_id,
            directly_blocked=blast_data.get("directly_blocked", []),
            transitively_blocked=blast_data.get("transitively_blocked", []),
            wasted_cost=wasted,
        )

    @property
    def chains(self) -> dict[str, CausalChain]:
        return dict(self._chains)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chains": {tid: c.to_dict() for tid, c in self._chains.items()},
            "root_causes": [r.to_dict() for r in self.get_root_causes()],
        }
