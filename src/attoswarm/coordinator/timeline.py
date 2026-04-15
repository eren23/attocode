"""Visual timeline generator for swarm execution.

Generates ASCII Gantt charts and structured data for HTML/SVG export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.coordinator.trace_query import TraceQueryEngine

logger = logging.getLogger(__name__)

_STATUS_CHARS = {
    "done": "=",
    "running": ">",
    "failed": "X",
    "skipped": "-",
    "pending": ".",
}


@dataclass(slots=True)
class GanttEntry:
    """A single entry in a Gantt chart."""

    task_id: str
    title: str
    start_time: float
    end_time: float
    status: str
    retries: int = 0
    model: str = ""

    @property
    def duration_s(self) -> float:
        return max(self.end_time - self.start_time, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": round(self.duration_s, 2),
            "status": self.status,
            "retries": self.retries,
            "model": self.model,
        }


class TimelineGenerator:
    """Generates timeline visualizations from trace data.

    Usage::

        gen = TimelineGenerator(query_engine)
        print(gen.generate_text_timeline())
        gantt = gen.generate_gantt_data()
        print(gen.generate_critical_path_highlight(critical_path))
    """

    def __init__(self, query_engine: TraceQueryEngine) -> None:
        self._engine = query_engine

    def generate_gantt_data(self) -> list[GanttEntry]:
        """Generate structured Gantt chart data from trace events."""
        task_data = self._engine.task_data
        spawn_times: dict[str, float] = {}
        end_times: dict[str, float] = {}
        statuses: dict[str, str] = {}
        retries: dict[str, int] = {}

        for event in self._engine.all_events:
            tid = event.task_id
            if not tid:
                continue
            if event.event_type == "spawn":
                spawn_times.setdefault(tid, event.timestamp)
            elif event.event_type in ("complete", "fail", "skip"):
                end_times[tid] = event.timestamp
                if event.event_type == "complete":
                    statuses[tid] = "done"
                elif event.event_type == "fail":
                    statuses[tid] = "failed"
                elif event.event_type == "skip":
                    statuses[tid] = "skipped"
            elif event.event_type == "retry":
                retries[tid] = retries.get(tid, 0) + 1

        entries: list[GanttEntry] = []
        for tid in sorted(spawn_times.keys()):
            tdata = task_data.get(tid, {})
            entries.append(GanttEntry(
                task_id=tid,
                title=tdata.get("title", tid),
                start_time=spawn_times[tid],
                end_time=end_times.get(tid, spawn_times[tid]),
                status=statuses.get(tid, "pending"),
                retries=retries.get(tid, 0),
                model=tdata.get("model", ""),
            ))

        return entries

    def generate_text_timeline(self, width: int = 60) -> str:
        """Generate an ASCII Gantt chart.

        Returns a multi-line string like::

            task-1  [============================]  12.3s  done
            task-2      [==============X]            8.1s  failed (1 retry)
            task-3          [===========>]           6.5s  running
        """
        entries = self.generate_gantt_data()
        if not entries:
            return "(no timeline data)"

        # Compute time range
        min_time = min(e.start_time for e in entries)
        max_time = max(e.end_time for e in entries if e.end_time > 0)
        time_range = max(max_time - min_time, 0.1)

        lines: list[str] = []
        max_id_len = max(len(e.task_id) for e in entries)

        for entry in entries:
            # Calculate bar position
            start_pos = int((entry.start_time - min_time) / time_range * width)
            end_pos = int((entry.end_time - min_time) / time_range * width) if entry.end_time > 0 else start_pos + 1
            bar_len = max(end_pos - start_pos, 1)

            # Build bar
            char = _STATUS_CHARS.get(entry.status, "?")
            bar = " " * start_pos + "[" + char * bar_len + "]"
            bar = bar.ljust(width + 2)

            # Duration and status
            duration = f"{entry.duration_s:6.1f}s"
            status = entry.status
            if entry.retries:
                status += f" ({entry.retries} {'retry' if entry.retries == 1 else 'retries'})"

            lines.append(f"{entry.task_id:<{max_id_len}}  {bar}  {duration}  {status}")

        return "\n".join(lines)

    def generate_critical_path_highlight(
        self,
        critical_path: list[str],
    ) -> str:
        """Generate a text timeline highlighting the critical path.

        Critical-path tasks are marked with ``>>`` prefix.
        """
        entries = self.generate_gantt_data()
        if not entries:
            return "(no timeline data)"

        cp_set = set(critical_path)
        min_time = min(e.start_time for e in entries)
        max_time = max(e.end_time for e in entries if e.end_time > 0)
        time_range = max(max_time - min_time, 0.1)
        width = 50

        lines: list[str] = []
        max_id_len = max(len(e.task_id) for e in entries)
        total_cp_time = 0.0

        for entry in entries:
            prefix = ">>" if entry.task_id in cp_set else "  "
            start_pos = int((entry.start_time - min_time) / time_range * width)
            end_pos = int((entry.end_time - min_time) / time_range * width) if entry.end_time > 0 else start_pos + 1
            bar_len = max(end_pos - start_pos, 1)
            char = _STATUS_CHARS.get(entry.status, "?")
            bar = " " * start_pos + "[" + char * bar_len + "]"
            bar = bar.ljust(width + 2)

            if entry.task_id in cp_set:
                total_cp_time += entry.duration_s

            lines.append(f"{prefix} {entry.task_id:<{max_id_len}}  {bar}  {entry.duration_s:6.1f}s")

        lines.append("")
        lines.append(f"Critical path: {' -> '.join(critical_path)}")
        lines.append(f"Critical path time: {total_cp_time:.1f}s")

        return "\n".join(lines)
