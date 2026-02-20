"""Swarm status panel widget.

Displays live swarm orchestration status: phase, wave progress,
worker activity, queue stats, and budget usage.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static

from attocode.integrations.swarm.types import (
    SwarmPhase,
    SwarmStatus,
    SwarmWorkerStatus,
)


def progress_bar(fraction: float, width: int = 12) -> str:
    """Render a text progress bar like [████░░░░░░░░]."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"


def format_tokens(n: int) -> str:
    """Format token count with k/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def format_elapsed(ms: float) -> str:
    """Format elapsed milliseconds as human-readable duration."""
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m{secs:02d}s"


_PHASE_INFO: dict[SwarmPhase, tuple[str, str]] = {
    SwarmPhase.IDLE: ("Idle", "dim"),
    SwarmPhase.DECOMPOSING: ("Decomposing", "yellow"),
    SwarmPhase.SCHEDULING: ("Scheduling", "yellow"),
    SwarmPhase.PLANNING: ("Planning", "cyan"),
    SwarmPhase.EXECUTING: ("Executing", "bold green"),
    SwarmPhase.VERIFYING: ("Verifying", "cyan"),
    SwarmPhase.SYNTHESIZING: ("Synthesizing", "magenta"),
    SwarmPhase.COMPLETED: ("Completed", "bold green"),
    SwarmPhase.FAILED: ("Failed", "bold red"),
}


def phase_info(phase: SwarmPhase) -> tuple[str, str]:
    """Return (display_text, style) for a swarm phase."""
    return _PHASE_INFO.get(phase, (phase.value.title(), "dim"))


class SwarmPanel(Static):
    """Displays live swarm status: phase, workers, queue, budget."""

    DEFAULT_CSS = """
    SwarmPanel {
        height: auto;
        max-height: 12;
        border: round $primary-darken-2;
        padding: 0 1;
        display: none;
    }

    SwarmPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status: SwarmStatus | None = None

    def update_status(self, status: SwarmStatus | None) -> None:
        """Update the displayed swarm status."""
        self._status = status
        self.set_class(status is not None, "visible")
        self.refresh()

    def render(self) -> Text:
        if self._status is None:
            return Text("")

        s = self._status
        text = Text()

        # Header: SWARM — Phase
        phase_text, phase_style = phase_info(s.phase)
        text.append("SWARM", style="bold")
        text.append(" \u2014 ", style="dim")
        text.append(phase_text, style=phase_style)
        text.append("\n")

        # Wave progress
        if s.total_waves > 0:
            wave_frac = s.current_wave / s.total_waves
            text.append(f"  Wave {s.current_wave}/{s.total_waves}  ")
            text.append(progress_bar(wave_frac), style="cyan")
            text.append(f" {wave_frac * 100:.0f}%\n")

        # Queue stats
        q = s.queue
        text.append("  Queue: ", style="dim")
        text.append(f"Ready: {q.ready}  ", style="yellow")
        text.append(f"Running: {q.running}  ", style="green")
        text.append(f"Done: {q.completed}  ")
        text.append(f"Failed: {q.failed}", style="red" if q.failed > 0 else "dim")
        text.append("\n")

        # Workers
        workers = s.active_workers
        if workers:
            text.append(f"  Workers ({len(workers)} active):\n", style="dim")
            now_ms = time.monotonic() * 1000
            for w in workers[:4]:  # Show at most 4
                elapsed = now_ms - (w.started_at * 1000) if w.started_at else w.elapsed_ms
                model_short = w.model.split("/")[-1] if "/" in w.model else w.model
                text.append("   \u25cf ", style="green")
                text.append(f"{w.worker_name:<12}", style="bold")
                text.append(f"({model_short})  ", style="dim")
                desc = w.task_description[:40]
                text.append(desc)
                text.append(f"  [{format_elapsed(elapsed)}]", style="dim")
                text.append("\n")
            if len(workers) > 4:
                text.append(f"   ... and {len(workers) - 4} more\n", style="dim")

        # Budget
        b = s.budget
        if b.tokens_total > 0:
            tok_frac = b.tokens_used / b.tokens_total
            text.append("  Budget: ")
            text.append(f"{format_tokens(b.tokens_used)}/{format_tokens(b.tokens_total)} tokens ")
            text.append(progress_bar(tok_frac, 10), style="cyan")
            text.append(f" {tok_frac * 100:.0f}%")
            if b.cost_total > 0:
                text.append(f"  ${b.cost_used:.2f}/${b.cost_total:.2f}")
            text.append("\n")

        return text
