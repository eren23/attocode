"""Work log for tracking agent progress."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class WorkEntryType(StrEnum):
    """Type of work log entry."""

    ACTION = "action"
    OBSERVATION = "observation"
    DECISION = "decision"
    ERROR = "error"
    MILESTONE = "milestone"


@dataclass
class WorkEntry:
    """A single work log entry."""

    type: WorkEntryType
    description: str
    timestamp: float = field(default_factory=time.monotonic)
    tool: str | None = None
    iteration: int = 0
    metadata: dict = field(default_factory=dict)


class WorkLog:
    """Tracks agent progress through a session.

    Maintains a log of actions, observations, decisions,
    errors, and milestones for summarization.
    """

    def __init__(self, max_entries: int = 200) -> None:
        self._entries: list[WorkEntry] = []
        self._max_entries = max_entries

    def record(
        self,
        entry_type: WorkEntryType,
        description: str,
        tool: str | None = None,
        iteration: int = 0,
    ) -> None:
        """Record a work log entry."""
        entry = WorkEntry(
            type=entry_type,
            description=description,
            tool=tool,
            iteration=iteration,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

    def action(self, description: str, tool: str | None = None, iteration: int = 0) -> None:
        self.record(WorkEntryType.ACTION, description, tool, iteration)

    def observation(self, description: str, iteration: int = 0) -> None:
        self.record(WorkEntryType.OBSERVATION, description, iteration=iteration)

    def decision(self, description: str, iteration: int = 0) -> None:
        self.record(WorkEntryType.DECISION, description, iteration=iteration)

    def error(self, description: str, iteration: int = 0) -> None:
        self.record(WorkEntryType.ERROR, description, iteration=iteration)

    def milestone(self, description: str, iteration: int = 0) -> None:
        self.record(WorkEntryType.MILESTONE, description, iteration=iteration)

    @property
    def entries(self) -> list[WorkEntry]:
        return list(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def get_recent(self, count: int = 10) -> list[WorkEntry]:
        """Get the most recent entries."""
        return self._entries[-count:]

    def get_by_type(self, entry_type: WorkEntryType) -> list[WorkEntry]:
        """Get entries of a specific type."""
        return [e for e in self._entries if e.type == entry_type]

    def get_summary(self, max_entries: int = 20) -> str:
        """Get a text summary of recent work."""
        if not self._entries:
            return "No work recorded."

        recent = self._entries[-max_entries:]
        lines = []
        for entry in recent:
            prefix = {
                WorkEntryType.ACTION: "->",
                WorkEntryType.OBSERVATION: "  ",
                WorkEntryType.DECISION: "**",
                WorkEntryType.ERROR: "!!",
                WorkEntryType.MILESTONE: "##",
            }.get(entry.type, "  ")
            tool_info = f" [{entry.tool}]" if entry.tool else ""
            lines.append(f"{prefix}{tool_info} {entry.description}")

        return "\n".join(lines)

    def get_milestones(self) -> list[WorkEntry]:
        """Get all milestone entries."""
        return self.get_by_type(WorkEntryType.MILESTONE)

    def get_errors(self) -> list[WorkEntry]:
        """Get all error entries."""
        return self.get_by_type(WorkEntryType.ERROR)

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()
