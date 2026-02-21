"""Side-by-side diff view widget.

Displays file differences in a two-column layout for easier comparison
of changes, with line numbers and syntax highlighting.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass(slots=True)
class SideBySideLine:
    """A line pair in a side-by-side diff."""

    left_no: int | None = None
    left_text: str = ""
    left_type: str = "context"  # "context", "remove", "empty"
    right_no: int | None = None
    right_text: str = ""
    right_type: str = "context"  # "context", "add", "empty"


class SideBySideDiff(VerticalScroll):
    """Two-column diff view.

    Shows old content on the left and new content on the right,
    aligned by diff hunks for easy visual comparison.
    """

    DEFAULT_CSS = """
    SideBySideDiff {
        height: auto;
        max-height: 30;
        border: round $surface;
        padding: 0 1;
    }
    SideBySideDiff .sbs-header {
        color: $primary;
        text-style: bold;
    }
    SideBySideDiff .sbs-left {
        width: 1fr;
        border-right: solid $surface-darken-1;
    }
    SideBySideDiff .sbs-right {
        width: 1fr;
    }
    SideBySideDiff .sbs-add {
        color: $success;
    }
    SideBySideDiff .sbs-remove {
        color: $error;
    }
    SideBySideDiff .sbs-line-no {
        color: $text-muted;
        width: 5;
    }
    """

    file_path: reactive[str] = reactive("")
    lines: reactive[list[SideBySideLine]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        yield Static("", id="sbs-header", classes="sbs-header")
        yield Static("", id="sbs-content")

    def set_diff(
        self,
        file_path: str,
        old_content: str,
        new_content: str,
    ) -> None:
        """Compute and display a side-by-side diff."""
        self.file_path = file_path
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        differ = difflib.SequenceMatcher(None, old_lines, new_lines)
        result: list[SideBySideLine] = []

        for tag, i1, i2, j1, j2 in differ.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    result.append(SideBySideLine(
                        left_no=i1 + k + 1,
                        left_text=old_lines[i1 + k].rstrip(),
                        left_type="context",
                        right_no=j1 + k + 1,
                        right_text=new_lines[j1 + k].rstrip(),
                        right_type="context",
                    ))
            elif tag == "replace":
                max_len = max(i2 - i1, j2 - j1)
                for k in range(max_len):
                    left_no = i1 + k + 1 if k < (i2 - i1) else None
                    left_text = old_lines[i1 + k].rstrip() if k < (i2 - i1) else ""
                    left_type = "remove" if k < (i2 - i1) else "empty"
                    right_no = j1 + k + 1 if k < (j2 - j1) else None
                    right_text = new_lines[j1 + k].rstrip() if k < (j2 - j1) else ""
                    right_type = "add" if k < (j2 - j1) else "empty"
                    result.append(SideBySideLine(
                        left_no=left_no, left_text=left_text, left_type=left_type,
                        right_no=right_no, right_text=right_text, right_type=right_type,
                    ))
            elif tag == "delete":
                for k in range(i2 - i1):
                    result.append(SideBySideLine(
                        left_no=i1 + k + 1,
                        left_text=old_lines[i1 + k].rstrip(),
                        left_type="remove",
                        right_type="empty",
                    ))
            elif tag == "insert":
                for k in range(j2 - j1):
                    result.append(SideBySideLine(
                        left_type="empty",
                        right_no=j1 + k + 1,
                        right_text=new_lines[j1 + k].rstrip(),
                        right_type="add",
                    ))

        self.lines = result
        self._render()

    def _render(self) -> None:
        """Render the side-by-side diff."""
        header = self.query_one("#sbs-header", Static)
        content = self.query_one("#sbs-content", Static)

        header.update(f"Diff: {self.file_path}")

        if not self.lines:
            content.update("No changes")
            return

        output: list[str] = []
        for line in self.lines:
            left_no = f"{line.left_no:4d}" if line.left_no else "    "
            right_no = f"{line.right_no:4d}" if line.right_no else "    "

            left_prefix = "-" if line.left_type == "remove" else " "
            right_prefix = "+" if line.right_type == "add" else " "

            left_text = line.left_text[:40].ljust(40) if line.left_type != "empty" else " " * 40
            right_text = line.right_text[:40] if line.right_type != "empty" else ""

            output.append(f"{left_no} {left_prefix}{left_text} │ {right_no} {right_prefix}{right_text}")

        content.update("\n".join(output))

    def clear(self) -> None:
        """Clear the diff view."""
        self.file_path = ""
        self.lines = []
        self._render()
