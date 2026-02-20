"""Status bar widget."""

from __future__ import annotations

import time

from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static


_SPINNER_FRAMES = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")


class StatusBar(Static):
    """Bottom status bar showing agent state, budget, context info."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    mode: reactive[str] = reactive("ready")
    model_name: reactive[str] = reactive("")
    iteration: reactive[int] = reactive(0)
    context_pct: reactive[float] = reactive(0.0)
    budget_pct: reactive[float] = reactive(0.0)
    cost: reactive[float] = reactive(0.0)
    git_branch: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._start_time: float = 0.0
        self._processing = False
        self._spinner_index = 0
        self._spinner_timer: Timer | None = None

    def render(self) -> Text:
        text = Text()

        # Status icon + mode
        if self.mode == "ready":
            text.append("[*] ", style="green")
            text.append("ready ")
        elif self.mode in ("thinking", "processing"):
            frame = _SPINNER_FRAMES[self._spinner_index]
            text.append(f"{frame} ", style="blue")
            text.append(f"{self.mode} ")
        elif self.mode == "approving":
            text.append("[?] ", style="yellow")
            text.append("awaiting approval ")
        else:
            frame = _SPINNER_FRAMES[self._spinner_index] if self._processing else "[~]"
            text.append(f"{frame} ", style="blue")
            text.append(_truncate(self.mode, 30) + " ")

        # Elapsed time
        if self._processing and self._start_time > 0:
            elapsed = int(time.monotonic() - self._start_time)
            if elapsed >= 3:
                text.append(f"| {elapsed}s ", style="dim")

        # Iteration
        if self.iteration > 0:
            text.append(f"| iter {self.iteration} ", style="dim")

        # Separator
        text.append("\u2502 ", style="dim")

        # Model
        if self.model_name:
            short_model = self.model_name.rsplit("/", 1)[-1][:25]
            text.append(f"{short_model} ", style="dim")

        # Context bar
        ctx = self.context_pct
        filled = int(ctx * 8)
        bar = "=" * filled + "-" * (8 - filled)
        ctx_style = "red" if ctx >= 0.9 else "yellow" if ctx >= 0.7 else "dim"
        text.append("ctx:[", style="dim")
        text.append(bar, style=ctx_style)
        text.append(f"] {ctx:.0%} ", style="dim")

        # Budget
        bud = self.budget_pct
        bud_style = "red" if bud >= 0.8 else "yellow" if bud >= 0.5 else "dim"
        text.append(f"bud:{bud:.0%} ", style=bud_style)

        # Cost
        if self.cost > 0:
            text.append(f"${self.cost:.4f} ", style="dim")

        # Git branch
        if self.git_branch:
            text.append(f"\u23e3 {self.git_branch} ", style="dim")

        # Hint
        text.append("^P:help", style="dim")

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


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "\u2026"
