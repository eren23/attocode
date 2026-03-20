"""In-memory query engine over trace and event data.

Provides structured queries across multiple data sources:
- ``swarm.events.jsonl`` (EventBus history)
- ``agents/agent-{id}.trace.jsonl`` (per-agent traces)
- ``tasks/task-{id}.json`` (per-task state)
- ``swarm.state.json`` (run state)

Designed for CLI, TUI, and post-mortem consumption.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TraceEvent:
    """Normalized event from any source."""

    timestamp: float
    source: str  # "event_bus" | "agent_trace" | "task_state"
    event_type: str
    task_id: str = ""
    agent_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class TraceQueryEngine:
    """Query engine over trace data.

    Usage::

        engine = TraceQueryEngine(run_dir=Path("/path/to/run"))
        engine.load()
        events = engine.events_for_task("task-1")
        costs = engine.cost_by_task()
        summary = engine.failure_summary()
    """

    def __init__(self, run_dir: Path | None = None) -> None:
        self._run_dir = run_dir
        self._events: list[TraceEvent] = []
        self._task_data: dict[str, dict[str, Any]] = {}
        self._state_data: dict[str, Any] = {}

    def load(self) -> None:
        """Load all trace data from disk."""
        if not self._run_dir:
            return

        self._load_event_bus()
        self._load_agent_traces()
        self._load_task_data()
        self._load_state()

        # Sort all events by timestamp
        self._events.sort(key=lambda e: e.timestamp)

    def load_from_memory(
        self,
        events: list[dict[str, Any]],
        task_data: dict[str, dict[str, Any]] | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        """Load from in-memory data (for testing/live queries)."""
        for e in events:
            self._events.append(TraceEvent(
                timestamp=e.get("timestamp", 0.0),
                source="memory",
                event_type=e.get("event_type", ""),
                task_id=e.get("task_id", ""),
                agent_id=e.get("agent_id", ""),
                trace_id=e.get("trace_id", ""),
                span_id=e.get("span_id", ""),
                data=e.get("data", {}),
                message=e.get("message", ""),
            ))
        if task_data:
            self._task_data = task_data
        if state:
            self._state_data = state
        self._events.sort(key=lambda e: e.timestamp)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def events_for_task(self, task_id: str) -> list[TraceEvent]:
        """Return all events related to a specific task."""
        return [e for e in self._events if e.task_id == task_id]

    def events_for_trace(self, trace_id: str) -> list[TraceEvent]:
        """Return all events for a specific trace (run)."""
        return [e for e in self._events if e.trace_id == trace_id]

    def events_by_type(self, event_type: str) -> list[TraceEvent]:
        """Return all events of a specific type."""
        return [e for e in self._events if e.event_type == event_type]

    def cost_by_task(self) -> dict[str, float]:
        """Return cost breakdown by task."""
        costs: dict[str, float] = {}
        for tid, data in self._task_data.items():
            cost = data.get("cost_usd", 0.0)
            if cost:
                costs[tid] = cost
        # Also check events for cost deltas
        for e in self._events:
            if e.event_type in ("complete", "cost_delta") and e.task_id:
                cost = e.data.get("cost_usd", 0.0)
                if cost and e.task_id not in costs:
                    costs[e.task_id] = cost
        return costs

    def cost_by_dependency_chain(self) -> dict[str, float]:
        """Return total cost grouped by dependency chains.

        Uses task dep info to group costs by root tasks.
        """
        costs = self.cost_by_task()
        # Build dep chains
        chains: dict[str, list[str]] = {}
        for tid, data in self._task_data.items():
            deps = data.get("deps", [])
            if not deps:
                chains[tid] = [tid]

        # For each task, find its root
        for tid in costs:
            root = self._find_chain_root(tid)
            chains.setdefault(root, []).append(tid)

        # Aggregate costs per chain
        chain_costs: dict[str, float] = {}
        for root, members in chains.items():
            chain_costs[root] = sum(costs.get(m, 0.0) for m in members)
        return chain_costs

    def timing_waterfall(self) -> list[dict[str, Any]]:
        """Return timing entries suitable for waterfall visualization."""
        entries: list[dict[str, Any]] = []
        for e in self._events:
            if e.event_type in ("spawn", "complete", "fail"):
                entries.append({
                    "task_id": e.task_id,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "data": e.data,
                })
        return entries

    def failure_summary(self) -> list[dict[str, Any]]:
        """Return a summary of all failures."""
        failures: list[dict[str, Any]] = []
        for e in self._events:
            if e.event_type in ("fail", "error"):
                failures.append({
                    "task_id": e.task_id,
                    "timestamp": e.timestamp,
                    "message": e.message,
                    "data": e.data,
                })
        return failures

    def budget_timeline(self) -> list[dict[str, Any]]:
        """Return budget events over time."""
        return [
            {
                "timestamp": e.timestamp,
                "message": e.message,
                "data": e.data,
            }
            for e in self._events
            if e.event_type == "budget"
        ]

    def search_events(
        self,
        pattern: str,
        event_types: list[str] | None = None,
    ) -> list[TraceEvent]:
        """Search events by regex pattern in message field."""
        compiled = re.compile(pattern, re.IGNORECASE)
        results: list[TraceEvent] = []
        for e in self._events:
            if event_types and e.event_type not in event_types:
                continue
            if compiled.search(e.message):
                results.append(e)
        return results

    @property
    def all_events(self) -> list[TraceEvent]:
        return list(self._events)

    @property
    def task_data(self) -> dict[str, dict[str, Any]]:
        return dict(self._task_data)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_event_bus(self) -> None:
        """Load events from swarm.events.jsonl."""
        events_path = self._run_dir / "swarm.events.jsonl"  # type: ignore[union-attr]
        if not events_path.exists():
            return
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self._events.append(TraceEvent(
                        timestamp=data.get("timestamp", 0.0),
                        source="event_bus",
                        event_type=data.get("event_type", ""),
                        task_id=data.get("task_id", ""),
                        agent_id=data.get("agent_id", ""),
                        trace_id=data.get("trace_id", ""),
                        span_id=data.get("span_id", ""),
                        data=data.get("data", {}),
                        message=data.get("message", ""),
                    ))
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            logger.debug("Failed to load events: %s", exc)

    def _load_agent_traces(self) -> None:
        """Load per-agent trace JSONL files."""
        agents_dir = self._run_dir / "agents"  # type: ignore[union-attr]
        if not agents_dir.exists():
            return
        for trace_file in agents_dir.glob("*.trace.jsonl"):
            try:
                for line in trace_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        self._events.append(TraceEvent(
                            timestamp=data.get("timestamp", 0.0),
                            source="agent_trace",
                            event_type=data.get("entry_type", ""),
                            task_id=data.get("task_id", ""),
                            agent_id=data.get("agent_id", ""),
                            trace_id=data.get("trace_id", ""),
                            span_id=data.get("span_id", ""),
                            data=data.get("data", {}),
                        ))
                    except json.JSONDecodeError:
                        pass
            except Exception as exc:
                logger.debug("Failed to load trace %s: %s", trace_file, exc)

    def _load_task_data(self) -> None:
        """Load per-task JSON files."""
        tasks_dir = self._run_dir / "tasks"  # type: ignore[union-attr]
        if not tasks_dir.exists():
            return
        for task_file in tasks_dir.glob("task-*.json"):
            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                tid = data.get("task_id", task_file.stem.replace("task-", ""))
                self._task_data[tid] = data
            except Exception as exc:
                logger.debug("Failed to load task %s: %s", task_file, exc)

    def _load_state(self) -> None:
        """Load swarm.state.json."""
        state_path = self._run_dir / "swarm.state.json"  # type: ignore[union-attr]
        if not state_path.exists():
            return
        try:
            self._state_data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed to load state: %s", exc)

    def _find_chain_root(self, task_id: str) -> str:
        """Find the root task in a dependency chain."""
        visited: set[str] = set()
        current = task_id
        while current not in visited:
            visited.add(current)
            data = self._task_data.get(current, {})
            deps = data.get("deps", [])
            if not deps:
                return current
            current = deps[0]
        return current
