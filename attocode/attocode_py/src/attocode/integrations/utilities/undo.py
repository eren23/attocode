"""Undo system for file operations.

Tracks file changes (before/after content snapshots) and provides
undo capability for reversing file modifications.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FileChange:
    """Record of a file change."""

    path: str
    before_content: str | None  # None if file didn't exist
    after_content: str | None  # None if file was deleted
    tool_name: str
    timestamp: float
    iteration: int = 0
    description: str = ""
    undone: bool = False

    @property
    def was_created(self) -> bool:
        """True if the file was created (didn't exist before)."""
        return self.before_content is None and self.after_content is not None

    @property
    def was_deleted(self) -> bool:
        """True if the file was deleted."""
        return self.before_content is not None and self.after_content is None

    @property
    def was_modified(self) -> bool:
        """True if the file was modified (existed before and after)."""
        return self.before_content is not None and self.after_content is not None

    @property
    def change_type(self) -> str:
        if self.was_created:
            return "created"
        if self.was_deleted:
            return "deleted"
        return "modified"


@dataclass
class FileChangeTracker:
    """Tracks file changes for undo capability.

    Records before/after snapshots of file content whenever
    file operations (write, edit) are performed.
    """

    changes: list[FileChange] = field(default_factory=list)
    max_history: int = 100
    _current_turn: int = 0

    def set_turn(self, turn: int) -> None:
        """Set the current turn/iteration number."""
        self._current_turn = turn

    def track_change(
        self,
        path: str,
        before_content: str | None,
        after_content: str | None,
        tool_name: str,
        description: str = "",
    ) -> FileChange:
        """Record a file change.

        Args:
            path: The file path.
            before_content: Content before the change (None if file didn't exist).
            after_content: Content after the change (None if file was deleted).
            tool_name: Name of the tool that made the change.
            description: Optional description of the change.

        Returns:
            The recorded FileChange.
        """
        change = FileChange(
            path=str(Path(path).resolve()),
            before_content=before_content,
            after_content=after_content,
            tool_name=tool_name,
            timestamp=time.time(),
            iteration=self._current_turn,
            description=description,
        )
        self.changes.append(change)

        # Trim history if needed
        if len(self.changes) > self.max_history:
            self.changes = self.changes[-self.max_history:]

        return change

    def track_file_before_write(self, path: str) -> str | None:
        """Capture file content before a write operation.

        Call this before performing a file write/edit. Returns the
        current content (or None if file doesn't exist).

        Args:
            path: The file path.

        Returns:
            Current file content, or None if file doesn't exist.
        """
        resolved = Path(path).resolve()
        if resolved.exists() and resolved.is_file():
            try:
                return resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        return None

    def undo_last_change(self) -> str:
        """Undo the most recent file change.

        Returns:
            Status message.
        """
        # Find the most recent non-undone change
        for change in reversed(self.changes):
            if not change.undone:
                return self._undo_change(change)
        return "No changes to undo."

    def undo_current_turn(self) -> str:
        """Undo all changes from the current turn/iteration.

        Returns:
            Status message.
        """
        turn_changes = [
            c for c in self.changes
            if c.iteration == self._current_turn and not c.undone
        ]
        if not turn_changes:
            return f"No changes in turn {self._current_turn} to undo."

        results = []
        for change in reversed(turn_changes):
            result = self._undo_change(change)
            results.append(result)

        return f"Undid {len(results)} changes from turn {self._current_turn}:\n" + "\n".join(results)

    def undo_file(self, path: str) -> str:
        """Undo the most recent change to a specific file.

        Args:
            path: The file path.

        Returns:
            Status message.
        """
        resolved = str(Path(path).resolve())
        for change in reversed(self.changes):
            if change.path == resolved and not change.undone:
                return self._undo_change(change)
        return f"No undoable changes found for {path}"

    def _undo_change(self, change: FileChange) -> str:
        """Actually undo a specific change.

        Args:
            change: The change to undo.

        Returns:
            Status message.
        """
        path = Path(change.path)
        try:
            if change.was_created:
                # File was created → delete it
                if path.exists():
                    path.unlink()
                change.undone = True
                return f"Undid creation of {change.path}"
            elif change.was_deleted:
                # File was deleted → restore it
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(change.before_content or "", encoding="utf-8")
                change.undone = True
                return f"Restored deleted file {change.path}"
            else:
                # File was modified → restore previous content
                path.write_text(change.before_content or "", encoding="utf-8")
                change.undone = True
                return f"Reverted {change.path} to previous content"
        except OSError as e:
            return f"Failed to undo {change.path}: {e}"

    def get_file_history(self, path: str) -> list[FileChange]:
        """Get the change history for a specific file.

        Args:
            path: The file path.

        Returns:
            List of changes for that file, newest first.
        """
        resolved = str(Path(path).resolve())
        return [
            c for c in reversed(self.changes)
            if c.path == resolved
        ]

    def get_session_changes(self) -> list[FileChange]:
        """Get all changes in the current session.

        Returns:
            All changes, newest first.
        """
        return list(reversed(self.changes))

    def get_pending_changes(self) -> list[FileChange]:
        """Get changes that haven't been undone.

        Returns:
            Non-undone changes, newest first.
        """
        return [c for c in reversed(self.changes) if not c.undone]

    def format_history(self, max_entries: int = 20) -> str:
        """Format the change history as a readable string.

        Args:
            max_entries: Maximum entries to show.

        Returns:
            Formatted history string.
        """
        changes = self.get_session_changes()[:max_entries]
        if not changes:
            return "No file changes recorded."

        lines = [f"File change history ({len(self.changes)} total):"]
        for i, change in enumerate(changes):
            status = "[undone]" if change.undone else ""
            lines.append(
                f"  {i + 1}. [{change.change_type}] {change.path} "
                f"(turn {change.iteration}, {change.tool_name}) {status}"
            )
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all change history."""
        self.changes.clear()
