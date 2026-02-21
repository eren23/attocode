"""History manager for message history management.

Tracks conversation message history with search, filtering, and
summarization support. Provides efficient access to recent messages
and topic-based retrieval.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HistoryEntry:
    """A single history entry."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens_estimate: int = 0


@dataclass(slots=True)
class HistorySearchResult:
    """Result of a history search."""

    entries: list[HistoryEntry]
    total_matches: int
    query: str


class HistoryManager:
    """Manages conversation message history.

    Features:
    - Ring buffer for recent messages (O(1) append)
    - Token-based windowing for context assembly
    - Keyword search across history
    - Summary generation for compacted history
    """

    def __init__(
        self,
        max_entries: int = 10_000,
        max_tokens: int = 200_000,
    ) -> None:
        self._max_entries = max_entries
        self._max_tokens = max_tokens
        self._entries: deque[HistoryEntry] = deque(maxlen=max_entries)
        self._total_tokens = 0
        self._summaries: list[str] = []

    def add(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> HistoryEntry:
        """Add a message to history."""
        tokens = len(content) // 4  # rough estimate
        entry = HistoryEntry(
            role=role,
            content=content,
            timestamp=time.monotonic(),
            metadata=metadata or {},
            tokens_estimate=tokens,
        )
        self._entries.append(entry)
        self._total_tokens += tokens
        return entry

    def get_recent(self, count: int = 10) -> list[HistoryEntry]:
        """Get the most recent N entries."""
        entries = list(self._entries)
        return entries[-count:] if count < len(entries) else entries

    def get_window(self, max_tokens: int | None = None) -> list[HistoryEntry]:
        """Get entries that fit within a token budget.

        Returns recent entries working backwards until budget is exhausted.
        """
        budget = max_tokens or self._max_tokens
        result: list[HistoryEntry] = []
        used = 0

        for entry in reversed(self._entries):
            if used + entry.tokens_estimate > budget:
                break
            result.append(entry)
            used += entry.tokens_estimate

        result.reverse()
        return result

    def search(self, query: str, max_results: int = 20) -> HistorySearchResult:
        """Search history by keyword."""
        query_lower = query.lower()
        matches: list[HistoryEntry] = []

        for entry in reversed(self._entries):
            if query_lower in entry.content.lower():
                matches.append(entry)
                if len(matches) >= max_results:
                    break

        return HistorySearchResult(
            entries=matches,
            total_matches=len(matches),
            query=query,
        )

    def filter_by_role(self, role: str) -> list[HistoryEntry]:
        """Get all entries with a specific role."""
        return [e for e in self._entries if e.role == role]

    def add_summary(self, summary: str) -> None:
        """Add a compaction summary."""
        self._summaries.append(summary)

    def get_summaries(self) -> list[str]:
        """Get all compaction summaries."""
        return list(self._summaries)

    def compact(self, keep_recent: int = 10) -> str:
        """Compact history, keeping only recent entries.

        Returns a summary of the removed entries.
        """
        if len(self._entries) <= keep_recent:
            return ""

        removed = list(self._entries)[:-keep_recent]
        kept = list(self._entries)[-keep_recent:]

        summary_parts = [f"[History summary: {len(removed)} messages compacted]"]
        roles = {}
        for entry in removed:
            roles[entry.role] = roles.get(entry.role, 0) + 1
        for role, count in roles.items():
            summary_parts.append(f"  {role}: {count} messages")

        summary = "\n".join(summary_parts)
        self._summaries.append(summary)

        self._entries.clear()
        for entry in kept:
            self._entries.append(entry)

        self._total_tokens = sum(e.tokens_estimate for e in self._entries)
        return summary

    def clear(self) -> None:
        """Clear all history."""
        self._entries.clear()
        self._summaries.clear()
        self._total_tokens = 0

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    def get_stats(self) -> dict[str, Any]:
        """Get history statistics."""
        return {
            "entries": len(self._entries),
            "total_tokens": self._total_tokens,
            "summaries": len(self._summaries),
            "max_entries": self._max_entries,
        }
