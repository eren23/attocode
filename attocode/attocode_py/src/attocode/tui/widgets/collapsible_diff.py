"""Collapsible diff view widget.

Shows file diffs in a collapsible/expandable format, allowing users
to focus on specific files while keeping an overview of all changes.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass(slots=True)
class CollapsibleFile:
    """A file entry in the collapsible diff."""

    path: str
    change_type: str  # "created", "modified", "deleted"
    additions: int = 0
    deletions: int = 0
    diff_text: str = ""
    expanded: bool = False


class CollapsibleDiffView(VerticalScroll):
    """Collapsible multi-file diff view.

    Shows a compact list of changed files that can be expanded
    individually to see the full diff for each file.
    """

    DEFAULT_CSS = """
    CollapsibleDiffView {
        height: auto;
        max-height: 30;
        border: round $surface;
        padding: 0 1;
    }
    CollapsibleDiffView .cdv-header {
        color: $primary;
        text-style: bold;
    }
    CollapsibleDiffView .cdv-file {
        margin: 0;
    }
    CollapsibleDiffView .cdv-file-header {
        text-style: bold;
    }
    CollapsibleDiffView .cdv-add {
        color: $success;
    }
    CollapsibleDiffView .cdv-remove {
        color: $error;
    }
    CollapsibleDiffView .cdv-stats {
        color: $text-muted;
    }
    """

    files: reactive[list[CollapsibleFile]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        yield Static("Changes", classes="cdv-header")
        yield Static("", id="cdv-summary", classes="cdv-stats")
        yield Static("", id="cdv-content")

    def add_file_diff(
        self,
        path: str,
        old_content: str,
        new_content: str,
        change_type: str = "modified",
    ) -> None:
        """Add a file diff."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path}", tofile=f"b/{path}",
            lineterm="",
        )
        diff_text = "\n".join(diff)

        additions = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))

        current = list(self.files)
        # Update or add
        existing = next((f for f in current if f.path == path), None)
        if existing:
            existing.diff_text = diff_text
            existing.additions = additions
            existing.deletions = deletions
            existing.change_type = change_type
        else:
            current.append(CollapsibleFile(
                path=path,
                change_type=change_type,
                additions=additions,
                deletions=deletions,
                diff_text=diff_text,
            ))

        self.files = current
        self._render()

    def toggle_file(self, path: str) -> None:
        """Toggle expansion of a file diff."""
        current = list(self.files)
        for f in current:
            if f.path == path:
                f.expanded = not f.expanded
                break
        self.files = current
        self._render()

    def expand_all(self) -> None:
        """Expand all file diffs."""
        current = list(self.files)
        for f in current:
            f.expanded = True
        self.files = current
        self._render()

    def collapse_all(self) -> None:
        """Collapse all file diffs."""
        current = list(self.files)
        for f in current:
            f.expanded = False
        self.files = current
        self._render()

    def _render(self) -> None:
        """Render the collapsible diff view."""
        summary = self.query_one("#cdv-summary", Static)
        content = self.query_one("#cdv-content", Static)

        if not self.files:
            summary.update("No changes")
            content.update("")
            return

        total_add = sum(f.additions for f in self.files)
        total_del = sum(f.deletions for f in self.files)
        summary.update(f"{len(self.files)} files changed (+{total_add}/-{total_del})")

        lines: list[str] = []
        icons = {"created": "+", "modified": "~", "deleted": "-"}

        for f in self.files:
            icon = icons.get(f.change_type, "?")
            expand_icon = "▼" if f.expanded else "▶"
            lines.append(
                f"  {expand_icon} {icon} {f.path} "
                f"(+{f.additions}/-{f.deletions})"
            )

            if f.expanded and f.diff_text:
                for diff_line in f.diff_text.split("\n")[:50]:  # Limit displayed lines
                    lines.append(f"    {diff_line}")
                if f.diff_text.count("\n") > 50:
                    lines.append(f"    ... ({f.diff_text.count(chr(10)) - 50} more lines)")
                lines.append("")

        content.update("\n".join(lines))

    def clear(self) -> None:
        """Clear all file diffs."""
        self.files = []
        self._render()
