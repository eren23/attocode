"""Detailed file change tracking with before/after content.

Records all file operations (create, modify, delete, rename) with
full content snapshots for undo support and audit trails.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ChangeType(StrEnum):
    """Type of file change."""

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


@dataclass(slots=True)
class TrackedChange:
    """A single tracked file change with before/after snapshots."""

    change_id: str
    file_path: str
    change_type: ChangeType
    timestamp: float
    before_content: str | None = None
    after_content: str | None = None
    before_path: str | None = None  # For renames
    tool_name: str = ""
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def lines_added(self) -> int:
        if not self.after_content:
            return 0
        if not self.before_content:
            return self.after_content.count("\n") + 1
        before_lines = set(self.before_content.splitlines())
        after_lines = self.after_content.splitlines()
        return sum(1 for line in after_lines if line not in before_lines)

    @property
    def lines_removed(self) -> int:
        if not self.before_content:
            return 0
        if not self.after_content:
            return self.before_content.count("\n") + 1
        after_lines = set(self.after_content.splitlines())
        before_lines = self.before_content.splitlines()
        return sum(1 for line in before_lines if line not in after_lines)


@dataclass(slots=True)
class ChangeStats:
    """Statistics about tracked changes."""

    total_changes: int = 0
    creates: int = 0
    modifies: int = 0
    deletes: int = 0
    renames: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    files_touched: int = 0


class DetailedFileChangeTracker:
    """Track file changes with full before/after content.

    Records every file operation with content snapshots so changes
    can be reviewed, undone, or audited.

    Args:
        max_history: Maximum number of changes to keep.
        snapshot_max_size: Max bytes to snapshot per file (0 = unlimited).
    """

    def __init__(
        self,
        *,
        max_history: int = 1000,
        snapshot_max_size: int = 500_000,
    ) -> None:
        self._max_history = max_history
        self._snapshot_max_size = snapshot_max_size
        self._changes: list[TrackedChange] = []
        self._change_counter = 0
        self._files_touched: set[str] = set()

    @property
    def changes(self) -> list[TrackedChange]:
        return list(self._changes)

    @property
    def change_count(self) -> int:
        return len(self._changes)

    def record_create(
        self,
        file_path: str,
        content: str,
        *,
        tool_name: str = "",
        iteration: int = 0,
    ) -> TrackedChange:
        """Record a file creation."""
        return self._record(
            file_path=file_path,
            change_type=ChangeType.CREATE,
            after_content=content,
            tool_name=tool_name,
            iteration=iteration,
        )

    def record_modify(
        self,
        file_path: str,
        before_content: str,
        after_content: str,
        *,
        tool_name: str = "",
        iteration: int = 0,
    ) -> TrackedChange:
        """Record a file modification."""
        return self._record(
            file_path=file_path,
            change_type=ChangeType.MODIFY,
            before_content=before_content,
            after_content=after_content,
            tool_name=tool_name,
            iteration=iteration,
        )

    def record_delete(
        self,
        file_path: str,
        content: str,
        *,
        tool_name: str = "",
        iteration: int = 0,
    ) -> TrackedChange:
        """Record a file deletion."""
        return self._record(
            file_path=file_path,
            change_type=ChangeType.DELETE,
            before_content=content,
            tool_name=tool_name,
            iteration=iteration,
        )

    def record_rename(
        self,
        old_path: str,
        new_path: str,
        *,
        tool_name: str = "",
        iteration: int = 0,
    ) -> TrackedChange:
        """Record a file rename."""
        return self._record(
            file_path=new_path,
            change_type=ChangeType.RENAME,
            before_path=old_path,
            tool_name=tool_name,
            iteration=iteration,
        )

    def record_auto(
        self,
        file_path: str,
        content: str,
        *,
        tool_name: str = "",
        iteration: int = 0,
    ) -> TrackedChange:
        """Auto-detect change type by checking if file exists.

        Reads the current file content from disk to determine
        whether this is a create or modify operation.
        """
        path = Path(file_path)
        if path.exists():
            try:
                before = path.read_text(encoding="utf-8", errors="replace")
                return self.record_modify(
                    file_path, before, content,
                    tool_name=tool_name, iteration=iteration,
                )
            except OSError:
                pass
        return self.record_create(
            file_path, content, tool_name=tool_name, iteration=iteration,
        )

    def get_changes_for_file(self, file_path: str) -> list[TrackedChange]:
        """Get all changes for a specific file."""
        return [c for c in self._changes if c.file_path == file_path]

    def get_changes_since(self, timestamp: float) -> list[TrackedChange]:
        """Get all changes since a timestamp."""
        return [c for c in self._changes if c.timestamp >= timestamp]

    def get_changes_for_iteration(self, iteration: int) -> list[TrackedChange]:
        """Get all changes in a specific iteration."""
        return [c for c in self._changes if c.iteration == iteration]

    def get_last_change(self, file_path: str) -> TrackedChange | None:
        """Get the most recent change for a file."""
        for change in reversed(self._changes):
            if change.file_path == file_path:
                return change
        return None

    def get_stats(self) -> ChangeStats:
        """Get aggregate statistics."""
        stats = ChangeStats(
            total_changes=len(self._changes),
            files_touched=len(self._files_touched),
        )
        for change in self._changes:
            match change.change_type:
                case ChangeType.CREATE:
                    stats.creates += 1
                case ChangeType.MODIFY:
                    stats.modifies += 1
                case ChangeType.DELETE:
                    stats.deletes += 1
                case ChangeType.RENAME:
                    stats.renames += 1
            stats.total_lines_added += change.lines_added
            stats.total_lines_removed += change.lines_removed
        return stats

    def get_summary(self) -> str:
        """Get a human-readable summary of changes."""
        stats = self.get_stats()
        parts = [f"{stats.total_changes} changes across {stats.files_touched} files"]
        if stats.creates:
            parts.append(f"{stats.creates} created")
        if stats.modifies:
            parts.append(f"{stats.modifies} modified")
        if stats.deletes:
            parts.append(f"{stats.deletes} deleted")
        if stats.renames:
            parts.append(f"{stats.renames} renamed")
        parts.append(f"+{stats.total_lines_added}/-{stats.total_lines_removed} lines")
        return ", ".join(parts)

    def clear(self) -> None:
        """Clear all tracked changes."""
        self._changes.clear()
        self._files_touched.clear()

    def _record(
        self,
        *,
        file_path: str,
        change_type: ChangeType,
        before_content: str | None = None,
        after_content: str | None = None,
        before_path: str | None = None,
        tool_name: str = "",
        iteration: int = 0,
    ) -> TrackedChange:
        self._change_counter += 1

        # Truncate large snapshots
        if self._snapshot_max_size > 0:
            if before_content and len(before_content) > self._snapshot_max_size:
                before_content = before_content[: self._snapshot_max_size] + "\n[truncated]"
            if after_content and len(after_content) > self._snapshot_max_size:
                after_content = after_content[: self._snapshot_max_size] + "\n[truncated]"

        change = TrackedChange(
            change_id=f"chg-{self._change_counter}",
            file_path=file_path,
            change_type=change_type,
            timestamp=time.monotonic(),
            before_content=before_content,
            after_content=after_content,
            before_path=before_path,
            tool_name=tool_name,
            iteration=iteration,
        )

        self._changes.append(change)
        self._files_touched.add(file_path)
        if before_path:
            self._files_touched.add(before_path)

        # Evict oldest if over limit
        if len(self._changes) > self._max_history:
            self._changes = self._changes[-self._max_history :]

        return change
