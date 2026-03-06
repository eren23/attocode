"""Message log widget using RichLog."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.widgets import RichLog


class MessageLog(RichLog):
    """Displays conversation messages in a scrollable log.

    Uses Textual's RichLog for efficient append-only rendering
    with built-in scrolling.
    """

    DEFAULT_CSS = """
    MessageLog {
        height: 1fr;
        min-height: 5;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self._max_messages = 500

    def add_user_message(self, text: str, *, images: list[str] | None = None) -> None:
        """Add a user message, with optional image attachment indicators."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" You ", style="bold on #45475a")
        styled.append(" ")
        styled.append(text)
        if images:
            for img in images:
                name = Path(img).name
                styled.append(f"\n  \U0001f4ce {name}", style="dim italic")
        self.write(styled)

    def add_assistant_message(self, text: str) -> None:
        """Add an assistant message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" Agent ", style="bold #1e1e2e on #89b4fa")
        styled.append(" ")
        styled.append(text)
        self.write(styled)

    def add_system_message(self, text: str) -> None:
        """Add a system/info message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" sys ", style="italic #6c7086 on #313244")
        styled.append(" ")
        styled.append(text, style="dim italic")
        self.write(styled)

    def add_error_message(self, text: str) -> None:
        """Add an error message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" ERR ", style="bold #1e1e2e on #f38ba8")
        styled.append(" ")
        styled.append(text, style="red")
        self.write(styled)

    def add_tool_message(self, name: str, status: str = "started") -> None:
        """Add a tool status message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        if status == "started":
            icon, color = "\u26a1", "yellow"
        elif status == "completed":
            icon, color = "\u2713", "green"
        else:
            icon, color = "\u2717", "red"
        styled.append(f"{icon} {name}", style=color)
        self.write(styled)

    # --- Swarm message methods ---

    _FAILURE_HINTS: dict[str, str] = {
        "timeout": "Consider increasing worker_timeout",
        "rate-limit": "Auto-retry with backoff",
        "rate_limit": "Auto-retry with backoff",
        "hollow": "Empty output, retrying",
        "quality": "Output didn't pass quality gate",
        "cascade": "Parent task failed",
    }

    def add_swarm_phase(self, phase: str, detail: str = "") -> None:
        """Add a swarm phase transition message (orange badge)."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" SWARM ", style="bold #1e1e2e on #fab387")
        styled.append(" ")
        styled.append(phase, style="bold")
        if detail:
            styled.append(f" \u2014 {detail}", style="dim")
        self.write(styled)

    def add_swarm_dispatch(self, desc: str, worker: str = "", model: str = "") -> None:
        """Add a swarm task dispatch message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append("\u25b6 ", style="cyan")
        if worker:
            styled.append(f"{worker} ", style="bold cyan")
        if model:
            styled.append(f"({model}) ", style="dim")
        styled.append(desc)
        self.write(styled)

    def add_swarm_complete(
        self, desc: str, quality_score: int | float | None = None, files: list[str] | None = None
    ) -> None:
        """Add a swarm task completion message (green checkmark, quality badge)."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append("\u2713 ", style="green bold")
        styled.append(desc)
        if quality_score is not None:
            score_style = "green" if quality_score >= 4 else ("yellow" if quality_score >= 3 else "red")
            styled.append(f" [{quality_score}/5]", style=score_style)
        if files:
            if len(files) <= 2:
                styled.append(f" [{len(files)} files: {', '.join(files)}]", style="dim")
            else:
                shown = ", ".join(files[:2])
                styled.append(f" [{len(files)} files: {shown}, +{len(files) - 2}]", style="dim")
        self.write(styled)

    def add_swarm_failure(self, desc: str, error: str = "", failure_mode: str = "") -> None:
        """Add a swarm task failure message (red X badge)."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append("\u2717 ", style="red bold")
        styled.append(desc, style="red")
        if failure_mode:
            styled.append(f" [{failure_mode}]", style="red dim")
        if error:
            styled.append(f" \u2014 {error[:80]}", style="dim")
        hint = self._FAILURE_HINTS.get(failure_mode, "")
        if hint:
            styled.append(f" ({hint})", style="yellow dim")
        self.write(styled)

    def add_swarm_wave(
        self, wave: int, total: int, completed: int = 0, failed: int = 0
    ) -> None:
        """Add a swarm wave completion summary."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" WAVE ", style="bold #1e1e2e on #89b4fa")
        styled.append(f" {wave}/{total}", style="bold")
        styled.append(f" \u2014 {completed} done", style="green")
        if failed:
            styled.append(f", {failed} failed", style="red")
        self.write(styled)

    def add_swarm_quality_reject(
        self, task_desc: str, score: int | float | None = None, feedback: str = ""
    ) -> None:
        """Add a swarm quality rejection message (yellow warning)."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append("\u26a0 ", style="yellow bold")
        styled.append("Quality rejected: ", style="yellow")
        styled.append(task_desc[:50])
        if score is not None:
            styled.append(f" [{score}/5]", style="red")
        if feedback:
            styled.append(f" \u2014 {feedback[:60]}", style="dim")
        self.write(styled)
