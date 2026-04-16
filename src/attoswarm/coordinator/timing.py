"""Timing waterfall for swarm execution.

Subscribes to span completions from the trace context and builds a
timing summary, including critical-path analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from attoswarm.coordinator.trace_context import SpanContext, on_span_complete, remove_span_listener

if TYPE_CHECKING:
    from attoswarm.coordinator.aot_graph import AoTGraph

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TimingEntry:
    """A single entry in the timing waterfall."""

    task_id: str
    operation: str
    start_time: float
    end_time: float
    duration_s: float
    parent_span_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": round(self.duration_s, 3),
        }


class TimingWaterfall:
    """Collects span timing data and provides analysis.

    Usage::

        waterfall = TimingWaterfall(trace_id="abc123")
        # ... spans complete via trace context ...
        print(waterfall.summary())
        print(waterfall.critical_path_timing(aot_graph))
    """

    def __init__(self, trace_id: str) -> None:
        self._trace_id = trace_id
        self._entries: list[TimingEntry] = []
        self._phase_spans: dict[str, list[SpanContext]] = {}
        on_span_complete(self._on_span)

    def _on_span(self, span: SpanContext) -> None:
        if span.trace_id != self._trace_id:
            return
        entry = TimingEntry(
            task_id=span.attributes.get("task_id", ""),
            operation=span.operation,
            start_time=span.start_time,
            end_time=span.end_time,
            duration_s=span.duration_s,
            parent_span_id=span.parent_span_id,
        )
        self._entries.append(entry)

        # Group by phase/operation
        phase = span.operation.split(".")[0] if "." in span.operation else span.operation
        self._phase_spans.setdefault(phase, []).append(span)

    def summary(self) -> dict[str, float]:
        """Return total duration per phase/operation."""
        result: dict[str, float] = {}
        for phase, spans in self._phase_spans.items():
            result[phase] = round(sum(s.duration_s for s in spans), 3)
        return result

    def critical_path_timing(self, aot_graph: AoTGraph) -> list[TimingEntry]:
        """Return timing entries for the critical-path tasks."""
        critical_path = aot_graph.get_critical_path()
        if not critical_path:
            return []

        cp_set = set(critical_path)
        cp_entries = [
            e for e in self._entries
            if e.task_id in cp_set and e.operation in ("execute_task", "handle_result")
        ]
        # If no matching entries, return all entries for critical path tasks
        if not cp_entries:
            cp_entries = [e for e in self._entries if e.task_id in cp_set]
        return sorted(cp_entries, key=lambda e: e.start_time)

    @property
    def entries(self) -> list[TimingEntry]:
        return list(self._entries)

    def wall_clock_s(self) -> float:
        """Return the total wall-clock time from first to last span."""
        if not self._entries:
            return 0.0
        start = min(e.start_time for e in self._entries)
        end = max(e.end_time for e in self._entries if e.end_time > 0)
        return round(end - start, 3) if end > start else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "wall_clock_s": self.wall_clock_s(),
            "entry_count": len(self._entries),
        }

    def cleanup(self) -> None:
        """Remove span listener to avoid leaks."""
        remove_span_listener(self._on_span)
