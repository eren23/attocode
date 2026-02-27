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
    context_tokens: reactive[int] = reactive(0)
    context_window: reactive[int] = reactive(200_000)
    files_changed: reactive[int] = reactive(0)
    lines_added: reactive[int] = reactive(0)
    lines_removed: reactive[int] = reactive(0)
    project_name: reactive[str] = reactive("")

    # Part 2 additions: cache, compaction, phase
    cache_hit_rate: reactive[float] = reactive(0.0)
    compaction_count: reactive[int] = reactive(0)
    phase: reactive[str] = reactive("")

    # Swarm mode
    swarm_active: reactive[bool] = reactive(False)
    swarm_wave: reactive[str] = reactive("")
    swarm_active_workers: reactive[int] = reactive(0)
    swarm_done: reactive[int] = reactive(0)
    swarm_total: reactive[int] = reactive(0)
    swarm_cost: reactive[float] = reactive(0.0)

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

        # Token ratio (context window usage, not budget)
        text.append(f"{self.context_tokens:,}", style="")
        text.append(f"/{self.context_window:,}", style="dim")
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

        # Phase
        if self.phase:
            phase_style = {
                "exploration": "cyan",
                "planning": "yellow",
                "acting": "green",
                "verifying": "magenta",
            }.get(self.phase, "dim")
            parts.append(Text(self.phase, style=phase_style))

        # Swarm indicator
        if self.swarm_active:
            swarm_text = Text()
            swarm_text.append("SWARM ", style="bold magenta")
            if self.swarm_wave:
                swarm_text.append(f"W{self.swarm_wave}", style="cyan")
                swarm_text.append(" | ", style="dim")
            swarm_text.append(f"{self.swarm_active_workers} active", style="yellow")
            swarm_text.append(" | ", style="dim")
            swarm_text.append(
                f"{self.swarm_done}/{self.swarm_total} done", style="green"
            )
            if self.swarm_cost > 0:
                swarm_text.append(" | ", style="dim")
                swarm_text.append(f"${self.swarm_cost:.2f}", style="dim")
            parts.append(swarm_text)

        # Cache hit rate
        if self.cache_hit_rate > 0:
            cache_style = "cyan" if self.cache_hit_rate > 0.5 else "dim"
            parts.append(Text(f"{self.cache_hit_rate:.0%} cache", style=cache_style))

        # Compaction count
        if self.compaction_count > 0:
            parts.append(Text(f"{self.compaction_count} compactions", style="dim"))

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

    def watch_context_tokens(self) -> None:
        self.refresh()

    def watch_context_window(self) -> None:
        self.refresh()

    def watch_cache_hit_rate(self) -> None:
        self.refresh()

    def watch_compaction_count(self) -> None:
        self.refresh()

    def watch_phase(self) -> None:
        self.refresh()

    def watch_swarm_active(self) -> None:
        self.refresh()

    def watch_swarm_wave(self) -> None:
        self.refresh()

    def watch_swarm_active_workers(self) -> None:
        self.refresh()

    def watch_swarm_done(self) -> None:
        self.refresh()

    def watch_swarm_total(self) -> None:
        self.refresh()

    def watch_swarm_cost(self) -> None:
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
