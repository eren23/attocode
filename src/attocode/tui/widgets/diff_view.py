"""Diff rendering widgets.

Provides DiffView (unified diff) and SideBySideDiff (two-column)
widgets for displaying file changes in the TUI.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


# ─── Data types ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class DiffLine:
    """A single line in a diff."""

    line_type: str  # "add", "remove", "context", "header"
    content: str
    old_line_no: int | None = None
    new_line_no: int | None = None


@dataclass(slots=True)
class DiffHunk:
    """A contiguous block of diff lines."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)
    header: str = ""


@dataclass(slots=True)
class FileDiff:
    """A complete diff for a single file."""

    file_path: str
    old_content: str
    new_content: str
    hunks: list[DiffHunk] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    is_new: bool = False
    is_deleted: bool = False


# ─── Diff computation ────────────────────────────────────────────────────────

def compute_diff(
    old_content: str,
    new_content: str,
    *,
    file_path: str = "",
    context_lines: int = 3,
) -> FileDiff:
    """Compute a structured diff between two strings.

    Args:
        old_content: Original content.
        new_content: Modified content.
        file_path: File path for display.
        context_lines: Number of context lines around changes.

    Returns:
        A :class:`FileDiff` with hunks and line-level detail.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = FileDiff(
        file_path=file_path,
        old_content=old_content,
        new_content=new_content,
        is_new=not old_content,
        is_deleted=not new_content,
    )

    unified = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=context_lines,
    ))

    if not unified:
        return diff

    current_hunk: DiffHunk | None = None
    old_no = 0
    new_no = 0

    for line in unified:
        if line.startswith("---") or line.startswith("+++"):
            continue

        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            import re
            match = re.match(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)",
                line,
            )
            if match:
                old_start = int(match.group(1))
                old_count = int(match.group(2) or "1")
                new_start = int(match.group(3))
                new_count = int(match.group(4) or "1")
                header = match.group(5).strip()

                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    header=header,
                )
                diff.hunks.append(current_hunk)
                old_no = old_start - 1
                new_no = new_start - 1
            continue

        if current_hunk is None:
            continue

        content = line.rstrip("\n")

        if line.startswith("+"):
            new_no += 1
            diff.additions += 1
            current_hunk.lines.append(DiffLine(
                line_type="add",
                content=content[1:],
                new_line_no=new_no,
            ))
        elif line.startswith("-"):
            old_no += 1
            diff.deletions += 1
            current_hunk.lines.append(DiffLine(
                line_type="remove",
                content=content[1:],
                old_line_no=old_no,
            ))
        else:
            old_no += 1
            new_no += 1
            current_hunk.lines.append(DiffLine(
                line_type="context",
                content=content[1:] if content.startswith(" ") else content,
                old_line_no=old_no,
                new_line_no=new_no,
            ))

    return diff


# ─── Rendering helpers ───────────────────────────────────────────────────────

_STYLE_MAP = {
    "add": "green",
    "remove": "red",
    "context": "dim",
    "header": "bold cyan",
}


def render_diff_line(line: DiffLine, *, show_line_numbers: bool = True) -> Text:
    """Render a diff line as Rich Text."""
    style = _STYLE_MAP.get(line.line_type, "")
    prefix = {"add": "+", "remove": "-", "context": " ", "header": "@"}.get(
        line.line_type, " "
    )

    parts: list[str] = []
    if show_line_numbers:
        old = str(line.old_line_no).rjust(4) if line.old_line_no else "    "
        new = str(line.new_line_no).rjust(4) if line.new_line_no else "    "
        parts.append(f"{old} {new}")

    parts.append(f" {prefix} {line.content}")
    return Text("".join(parts), style=style)


# ─── Widgets ─────────────────────────────────────────────────────────────────

class DiffView(VerticalScroll):
    """Unified diff view widget.

    Displays a file diff in unified format with syntax highlighting
    for additions and deletions.
    """

    DEFAULT_CSS = """
    DiffView {
        height: auto;
        max-height: 40;
        border: round $surface;
        padding: 0 1;
    }
    DiffView .diff-header {
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }
    DiffView .diff-stats {
        color: $text-muted;
    }
    """

    diff: reactive[FileDiff | None] = reactive(None)

    def __init__(
        self,
        file_diff: FileDiff | None = None,
        *,
        show_line_numbers: bool = True,
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self._show_line_numbers = show_line_numbers
        if file_diff:
            self.diff = file_diff

    def compose(self) -> ComposeResult:
        yield Static("", classes="diff-header", id="diff-header")
        yield Static("", classes="diff-stats", id="diff-stats")
        yield Static("", id="diff-content")

    def watch_diff(self, diff: FileDiff | None) -> None:
        if diff is None:
            return
        self._render_diff(diff)

    def _render_diff(self, diff: FileDiff) -> None:
        header = self.query_one("#diff-header", Static)
        stats = self.query_one("#diff-stats", Static)
        content = self.query_one("#diff-content", Static)

        header.update(diff.file_path)
        stats.update(f"+{diff.additions} -{diff.deletions}")

        lines: list[Text] = []
        for hunk in diff.hunks:
            hunk_header = Text(
                f"@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@"
                + (f" {hunk.header}" if hunk.header else ""),
                style="bold cyan",
            )
            lines.append(hunk_header)
            for line in hunk.lines:
                lines.append(render_diff_line(
                    line, show_line_numbers=self._show_line_numbers,
                ))

        text = Text("\n").join(lines) if lines else Text("(no changes)")
        content.update(text)


class CollapsibleDiffView(Vertical):
    """Collapsible wrapper around DiffView.

    Click the header to expand/collapse the diff content.
    """

    DEFAULT_CSS = """
    CollapsibleDiffView {
        height: auto;
        margin: 0 0 1 0;
    }
    CollapsibleDiffView .collapse-header {
        height: 1;
        padding: 0 1;
    }
    CollapsibleDiffView .collapse-header:hover {
        background: $surface;
    }
    """

    collapsed: reactive[bool] = reactive(True)

    def __init__(
        self,
        file_diff: FileDiff,
        *,
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self._file_diff = file_diff

    def compose(self) -> ComposeResult:
        arrow = ">" if self.collapsed else "v"
        stats = f"+{self._file_diff.additions}/-{self._file_diff.deletions}"
        yield Static(
            f" {arrow} {self._file_diff.file_path}  ({stats})",
            classes="collapse-header",
            id="collapse-toggle",
        )
        view = DiffView(self._file_diff, id="inner-diff")
        view.display = not self.collapsed
        yield view

    def on_click(self, event: Any) -> None:
        self.collapsed = not self.collapsed

    def watch_collapsed(self, collapsed: bool) -> None:
        toggle = self.query_one("#collapse-toggle", Static)
        arrow = ">" if collapsed else "v"
        stats = f"+{self._file_diff.additions}/-{self._file_diff.deletions}"
        toggle.update(f" {arrow} {self._file_diff.file_path}  ({stats})")

        try:
            inner = self.query_one("#inner-diff", DiffView)
            inner.display = not collapsed
        except Exception:
            pass


class FileChangeSummary(Static):
    """Summary of all file changes in an iteration/session."""

    DEFAULT_CSS = """
    FileChangeSummary {
        height: auto;
        padding: 1;
        border: round $surface;
    }
    """

    def update_diffs(self, diffs: list[FileDiff]) -> None:
        """Update the summary with a list of file diffs."""
        if not diffs:
            self.update("No file changes")
            return

        total_add = sum(d.additions for d in diffs)
        total_del = sum(d.deletions for d in diffs)

        lines = [
            f"Files changed: {len(diffs)}  "
            f"(+{total_add} -{total_del})",
            "",
        ]
        for diff in diffs:
            indicator = "new" if diff.is_new else "del" if diff.is_deleted else "mod"
            lines.append(
                f"  [{indicator}] {diff.file_path} "
                f"+{diff.additions}/-{diff.deletions}"
            )

        self.update("\n".join(lines))
