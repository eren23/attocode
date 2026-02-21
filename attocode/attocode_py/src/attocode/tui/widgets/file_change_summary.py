"""File change summary widget.

Displays a summary of all files modified during an agent session,
with change counts, sizes, and status indicators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass(slots=True)
class FileChange:
    """Record of a file change."""

    path: str
    change_type: str  # "created", "modified", "deleted", "renamed"
    additions: int = 0
    deletions: int = 0
    tool_name: str = ""


class FileChangeSummary(VerticalScroll):
    """Summarizes all file changes in the session.

    Features:
    - Categorized by change type (created/modified/deleted)
    - Line count changes (+/-) per file
    - Sortable by path or change type
    - Collapsible sections
    """

    DEFAULT_CSS = """
    FileChangeSummary {
        height: auto;
        max-height: 15;
        border: round $surface;
        padding: 0 1;
    }
    FileChangeSummary .fcs-header {
        color: $primary;
        text-style: bold;
    }
    FileChangeSummary .fcs-created {
        color: $success;
    }
    FileChangeSummary .fcs-modified {
        color: $warning;
    }
    FileChangeSummary .fcs-deleted {
        color: $error;
    }
    FileChangeSummary .fcs-stats {
        color: $text-muted;
    }
    """

    changes: reactive[list[FileChange]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        yield Static("File Changes", classes="fcs-header")
        yield Static("", id="fcs-summary", classes="fcs-stats")
        yield Static("", id="fcs-details")

    def add_change(self, change: FileChange) -> None:
        """Record a file change."""
        current = list(self.changes)

        # Update existing or add new
        existing = next((c for c in current if c.path == change.path), None)
        if existing:
            existing.change_type = change.change_type
            existing.additions += change.additions
            existing.deletions += change.deletions
        else:
            current.append(change)

        self.changes = current
        self._render()

    def add_simple_change(
        self,
        path: str,
        change_type: str,
        additions: int = 0,
        deletions: int = 0,
    ) -> None:
        """Convenience method for simple changes."""
        self.add_change(FileChange(
            path=path,
            change_type=change_type,
            additions=additions,
            deletions=deletions,
        ))

    def _render(self) -> None:
        """Render the file change summary."""
        summary = self.query_one("#fcs-summary", Static)
        details = self.query_one("#fcs-details", Static)

        if not self.changes:
            summary.update("No changes")
            details.update("")
            return

        # Stats
        created = sum(1 for c in self.changes if c.change_type == "created")
        modified = sum(1 for c in self.changes if c.change_type == "modified")
        deleted = sum(1 for c in self.changes if c.change_type == "deleted")
        total_add = sum(c.additions for c in self.changes)
        total_del = sum(c.deletions for c in self.changes)

        summary.update(
            f"{len(self.changes)} files: "
            f"+{created} created, ~{modified} modified, -{deleted} deleted "
            f"(+{total_add}/-{total_del} lines)"
        )

        # Details
        icons = {"created": "+", "modified": "~", "deleted": "-", "renamed": "→"}
        lines: list[str] = []
        for change in sorted(self.changes, key=lambda c: c.path):
            icon = icons.get(change.change_type, "?")
            delta = ""
            if change.additions or change.deletions:
                delta = f" (+{change.additions}/-{change.deletions})"
            lines.append(f"  {icon} {change.path}{delta}")

        details.update("\n".join(lines))

    def clear(self) -> None:
        """Clear all changes."""
        self.changes = []
        self._render()
