"""Persistent memory across sessions.

Stores and retrieves key-value memories that persist across agent
sessions. Used for learning preferences, project patterns, and
accumulated knowledge.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MemoryEntry:
    """A single memory entry."""

    key: str
    value: str
    category: str = "general"
    importance: float = 0.5  # 0.0 to 1.0
    created_at: float = 0.0
    updated_at: float = 0.0
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        return cls(
            key=data["key"],
            value=data["value"],
            category=data.get("category", "general"),
            importance=data.get("importance", 0.5),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
        )


class PersistentMemory:
    """Key-value memory store with file-based persistence.

    Memories are stored as a JSON file and loaded on init.
    Changes are written through immediately.

    Args:
        storage_path: Path to the JSON file for persistence.
        max_entries: Maximum number of memories to keep.
    """

    def __init__(
        self,
        storage_path: Path | str,
        *,
        max_entries: int = 500,
    ) -> None:
        self._path = Path(storage_path)
        self._max_entries = max_entries
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    @property
    def count(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> MemoryEntry | None:
        """Get a memory entry by key. Increments access count."""
        entry = self._entries.get(key)
        if entry:
            entry.access_count += 1
            self._save()
        return entry

    def set(
        self,
        key: str,
        value: str,
        *,
        category: str = "general",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Set or update a memory entry."""
        existing = self._entries.get(key)
        if existing:
            existing.value = value
            existing.category = category
            existing.importance = importance
            existing.updated_at = time.time()
            if metadata:
                existing.metadata.update(metadata)
            entry = existing
        else:
            entry = MemoryEntry(
                key=key,
                value=value,
                category=category,
                importance=importance,
                metadata=metadata or {},
            )
            self._entries[key] = entry

        self._evict_if_needed()
        self._save()
        return entry

    def delete(self, key: str) -> bool:
        """Delete a memory entry. Returns True if it existed."""
        if key in self._entries:
            del self._entries[key]
            self._save()
            return True
        return False

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        min_importance: float = 0.0,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Search memories by keyword in key and value.

        Args:
            query: Search string (case-insensitive).
            category: Optional category filter.
            min_importance: Minimum importance threshold.
            limit: Maximum results to return.

        Returns:
            Matching entries sorted by importance (descending).
        """
        query_lower = query.lower()
        results: list[MemoryEntry] = []

        for entry in self._entries.values():
            if entry.importance < min_importance:
                continue
            if category and entry.category != category:
                continue
            if query_lower in entry.key.lower() or query_lower in entry.value.lower():
                results.append(entry)

        results.sort(key=lambda e: e.importance, reverse=True)
        return results[:limit]

    def list_categories(self) -> list[str]:
        """List all unique categories."""
        return sorted({e.category for e in self._entries.values()})

    def get_by_category(
        self,
        category: str,
        *,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """Get all memories in a category."""
        entries = [e for e in self._entries.values() if e.category == category]
        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries[:limit]

    def clear(self) -> None:
        """Clear all memories."""
        self._entries.clear()
        self._save()

    def _evict_if_needed(self) -> None:
        """Evict lowest-importance entries if over max_entries."""
        if len(self._entries) <= self._max_entries:
            return
        sorted_entries = sorted(
            self._entries.values(),
            key=lambda e: (e.importance, e.access_count, e.updated_at),
        )
        to_remove = len(self._entries) - self._max_entries
        for entry in sorted_entries[:to_remove]:
            del self._entries[entry.key]

    def _load(self) -> None:
        """Load entries from the JSON file."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "entries" in data:
                for entry_data in data["entries"]:
                    entry = MemoryEntry.from_dict(entry_data)
                    self._entries[entry.key] = entry
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    def _save(self) -> None:
        """Save entries to the JSON file."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            self._path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass
