"""Status bar widget — 2-line Claude Code–style layout."""

from __future__ import annotations

import time

from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static


_SPINNER_FRAMES = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")

_BAR_WIDTH = 20


class StatusBar(Static):
    """Bottom status bar showing agent state, budget, context info.

    Renders two lines:
      Line 1: model | progress bar | tokens | git branch +files (duration) | project
      Line 2: ● mode · file stats · iteration · cost                        ^P help
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 2;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    # Existing reactives
    mode: reactive[str] = reactive("ready")
    model_name: reactive[str] = reactive("")
    iteration: reactive[int] = reactive(0)
    context_pct: reactive[float] = reactive(0.0)
    budget_pct: reactive[float] = reactive(0.0)
    cost: reactive[float] = reactive(0.0)
    git_branch: reactive[str] = reactive("")

    # New reactives
    total_tokens: reactive[int] = reactive(0)
    max_tokens: reactive[int] = reactive(200_000)
    files_changed: reactive[int] = reactive(0)
    lines_added: reactive[int] = reactive(0)
    lines_removed: reactive[int] = reactive(0)
    project_name: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._start_time: float = 0.0
        self._processing = False
        self._spinner_index = 0
        self._spinner_timer: Timer | None = None

    def render(self) -> Text:
        text = Text()
        text.append_text(self._render_line1())
        text.append("\n")
        text.append_text(self._render_line2())
        return text

    def _render_line1(self) -> Text:
        """Metrics-dense top line: model | progress | tokens | branch | project."""
        text = Text()

        # Model name (bold, truncated)
        if self.model_name:
            short_model = self.model_name.rsplit("/", 1)[-1][:25]
            text.append(f" {short_model}", style="bold")
            text.append(" \u2502 ", style="dim")

        # Progress bar (20 chars, colored by threshold)
        fraction = max(self.context_pct, self.budget_pct)
        bar = _render_progress_bar(fraction, _BAR_WIDTH)
        style = _usage_style(fraction)
        text.append(bar, style=style)
        text.append(f" {fraction:.0%}", style=style)
        text.append(" \u2502 ", style="dim")

        # Token ratio
        text.append(f"{self.total_tokens:,}", style="")
        text.append(f"/{self.max_tokens:,}", style="dim")
        text.append(" \u2502 ", style="dim")

        # Git branch + file count
        if self.git_branch:
            text.append(f"\u23e3 {_truncate(self.git_branch, 20)}", style="dim")
            if self.files_changed > 0:
                text.append(f" +{self.files_changed}", style="green")
        else:
            text.append("\u23e3 -", style="dim")

        # Duration (only when processing and >= 3s)
        if self._processing and self._start_time > 0:
            elapsed = int(time.monotonic() - self._start_time)
            if elapsed >= 3:
                text.append(f" ({_format_duration(elapsed)})", style="dim")

        # Project name
        if self.project_name:
            text.append(" \u2502 ", style="dim")
            text.append(self.project_name, style="dim")

        return text

    def _render_line2(self) -> Text:
        """Status + contextual bottom line."""
        text = Text()
        parts: list[Text] = []

        # Activity indicator + mode
        indicator = Text()
        if self.mode == "ready":
            indicator.append(" \u25cf ", style="green")
            indicator.append("ready", style="dim")
        elif self.mode in ("thinking", "processing", "streaming"):
            frame = _SPINNER_FRAMES[self._spinner_index]
            indicator.append(f" {frame} ", style="blue")
            indicator.append(self.mode, style="dim")
        elif self.mode == "approving":
            indicator.append(" ? ", style="yellow bold")
            indicator.append("approval", style="dim")
        else:
            frame = _SPINNER_FRAMES[self._spinner_index] if self._processing else "\u25cf"
            style = "blue" if self._processing else "dim"
            indicator.append(f" {frame} ", style=style)
            indicator.append(_truncate(self.mode, 20), style="dim")
        parts.append(indicator)

        # File stats (only when files changed)
        if self.files_changed > 0:
            ftext = Text()
            ftext.append(f"{self.files_changed} file{'s' if self.files_changed != 1 else ''}", style="dim")
            if self.lines_added > 0:
                ftext.append(f" +{self.lines_added}", style="green")
            if self.lines_removed > 0:
                ftext.append(f" -{self.lines_removed}", style="red")
            parts.append(ftext)

        # Iteration
        if self.iteration > 0:
            parts.append(Text(f"iter #{self.iteration}", style="dim"))

        # Cost
        if self.cost > 0:
            parts.append(Text(f"${self.cost:.4f}", style="dim"))

        # Join parts with dot separator
        for i, part in enumerate(parts):
            text.append_text(part)
            if i < len(parts) - 1:
                text.append(" \u00b7 ", style="dim")

        # Right-aligned help hint (pad to fill)
        hint = "^P help"
        # We can't truly right-align in Rich Text easily, so add spacing
        current_len = len(text.plain)
        try:
            width = self.size.width - 2  # account for padding
        except Exception:
            width = 80
        padding = max(1, width - current_len - len(hint))
        text.append(" " * padding)
        text.append(hint, style="dim")

        return text

    def start_processing(self) -> None:
        """Mark the start of processing."""
        self._processing = True
        self._start_time = time.monotonic()
        self.mode = "thinking"
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._spin)

    def stop_processing(self) -> None:
        """Mark the end of processing."""
        self._processing = False
        self.mode = "ready"
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _spin(self) -> None:
        """Advance spinner frame."""
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        self.refresh()

    # Watchers
    def watch_mode(self) -> None:
        self.refresh()

    def watch_iteration(self) -> None:
        self.refresh()

    def watch_context_pct(self) -> None:
        self.refresh()

    def watch_budget_pct(self) -> None:
        self.refresh()

    def watch_cost(self) -> None:
        self.refresh()

    def watch_total_tokens(self) -> None:
        self.refresh()

    def watch_files_changed(self) -> None:
        self.refresh()

    def watch_lines_added(self) -> None:
        self.refresh()

    def watch_lines_removed(self) -> None:
        self.refresh()

    def watch_project_name(self) -> None:
        self.refresh()


def _render_progress_bar(fraction: float, width: int = 20) -> str:
    """Render a progress bar using block characters."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(fraction * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _usage_style(fraction: float) -> str:
    """Return a Rich style string based on usage fraction."""
    if fraction >= 0.85:
        return "red"
    if fraction >= 0.70:
        return "yellow"
    if fraction >= 0.50:
        return "#89b4fa"
    return "dim"


def _format_duration(seconds: int) -> str:
    """Format seconds into compact duration string."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        mins, secs = divmod(seconds, 60)
        return f"{mins}m{secs:02d}s"
    hours, remainder = divmod(seconds, 3600)
    mins = remainder // 60
    return f"{hours}h{mins:02d}m"


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "\u2026"
