"""Tab 5: Decisions & Errors pane — decision log and error summary."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.containers import Vertical
from textual.widget import Widget

if TYPE_CHECKING:
    from textual.app import ComposeResult


def _fmt_ts(ts: Any) -> str:
    """Format a timestamp (epoch number or ISO string) as HH:MM:SS."""
    if not ts:
        return "??:??:??"
    if isinstance(ts, (int, float)):
        return time.strftime("%H:%M:%S", time.localtime(ts))
    if isinstance(ts, str):
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%H:%M:%S")
        except Exception:
            return ts[:8]
    return "??:??:??"


class DecisionLog(Widget):
    """Scrollable chronological decision log."""

    DEFAULT_CSS = """
    DecisionLog {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._decisions: list[dict[str, Any]] = []
        self._filter_phase: str = ""

    def render(self) -> Text:
        text = Text()
        text.append("Decision Log", style="bold underline")
        if self._filter_phase:
            text.append(f" [phase={self._filter_phase}]", style="yellow")
        text.append("\n\n")

        decisions = self._decisions
        if self._filter_phase:
            decisions = [d for d in decisions if d.get("phase") == self._filter_phase]

        if not decisions:
            text.append("No decisions recorded yet", style="dim italic")
            return text

        phase_colors = {
            "decomposing": "cyan",
            "scheduling": "blue",
            "executing": "green",
            "verifying": "magenta",
            "adapting": "yellow",
        }

        for d in decisions[-50:]:
            ts = d.get("timestamp", 0)
            t = _fmt_ts(ts)
            phase = d.get("phase", "")
            color = phase_colors.get(phase, "dim")

            text.append(f"[{t}] ", style="dim")
            text.append(f"[{phase.upper():>12s}] ", style=color)
            text.append(f"{d.get('decision', '')}\n", style="bold")

            reasoning = d.get("reasoning", "")
            if reasoning:
                text.append(f"{'':>23s}Reason: {reasoning}\n", style="dim")

        return text

    def update_decisions(self, decisions: list[dict[str, Any]]) -> None:
        self._decisions = decisions
        self.refresh()


class ErrorSummary(Widget):
    """Error counts by phase and recent error details."""

    DEFAULT_CSS = """
    ErrorSummary {
        height: auto;
        min-height: 6;
        max-height: 20;
        border: solid $error;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._errors: list[dict[str, Any]] = []

    def render(self) -> Text:
        text = Text()
        text.append("Error Summary\n", style="bold red underline")
        text.append("\n")

        if not self._errors:
            text.append("No errors", style="green dim")
            return text

        # Count by phase
        by_phase: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        for e in self._errors:
            phase = e.get("phase", "unknown")
            by_phase[phase] = by_phase.get(phase, 0) + 1
            fm = e.get("failure_mode", "")
            if fm:
                by_mode[fm] = by_mode.get(fm, 0) + 1

        text.append("By Phase:\n", style="bold")
        for phase, count in sorted(by_phase.items(), key=lambda x: -x[1]):
            bar = "\u2588" * min(count, 20)
            text.append(f"  {phase:>12s}: {bar} {count}\n", style="dim")

        if by_mode:
            text.append("\nBy Failure Mode:\n", style="bold")
            for mode, count in sorted(by_mode.items(), key=lambda x: -x[1]):
                text.append(f"  {mode:>12s}: {count}\n", style="dim")

        text.append(f"\nRecent Errors ({min(len(self._errors), 10)}):\n", style="bold")
        for e in self._errors[-10:]:
            ts = e.get("timestamp", 0)
            t = _fmt_ts(ts)
            text.append(f"  [{t}] ", style="dim")
            msg = e.get("message", e.get("error", "unknown"))
            text.append(f"{str(msg)[:80]}\n", style="red")

        return text

    def update_errors(self, errors: list[dict[str, Any]]) -> None:
        self._errors = errors
        self.refresh()


class TransitionLog(Widget):
    """Scrollable log of task state transitions."""

    DEFAULT_CSS = """
    TransitionLog {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    _STATE_STYLES: dict[str, str] = {
        "running": "cyan",
        "done": "green",
        "failed": "red",
        "pending": "dim",
        "skipped": "yellow",
        "claiming": "yellow",
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._transitions: list[dict[str, Any]] = []

    def render(self) -> Text:
        text = Text()
        text.append("Transition Log", style="bold underline")
        text.append("\n\n")

        if not self._transitions:
            text.append("No task transitions recorded yet", style="dim italic")
            return text

        for t in self._transitions[-50:]:
            ts = t.get("timestamp", 0)
            t_str = _fmt_ts(ts)
            task_id = t.get("task_id", "?")
            from_state = t.get("from_state", t.get("from", "?"))
            to_state = t.get("to_state", t.get("to", "?"))
            reason = t.get("reason", "")
            agent = t.get("assigned_agent", t.get("agent_id", ""))

            text.append(f"[{t_str}] ", style="dim")
            text.append(f"{task_id}: ", style="bold")
            text.append(f"{from_state}", style="dim")
            text.append(" \u2192 ", style="dim")
            to_style = self._STATE_STYLES.get(str(to_state), "")
            text.append(f"{to_state}", style=to_style)
            if agent:
                text.append(f" (agent: {agent})", style="dim italic")
            if reason:
                text.append(f" — {reason}", style="dim italic")
            text.append("\n")

        return text

    def update_transitions(self, transitions: list[dict[str, Any]]) -> None:
        self._transitions = transitions
        self.refresh()


class DecisionsPane(Widget):
    """Top: DecisionLog, Middle: TransitionLog, Bottom: ErrorSummary."""

    DEFAULT_CSS = """
    DecisionsPane {
        height: 1fr;
    }
    DecisionsPane #decisions-log-container {
        height: 2fr;
    }
    DecisionsPane #decisions-transition-container {
        height: 1fr;
    }
    DecisionsPane #decisions-error-container {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(id="decisions-log-container"):
                yield DecisionLog(id="dec-log")
            with Vertical(id="decisions-transition-container"):
                yield TransitionLog(id="dec-transitions")
            with Vertical(id="decisions-error-container"):
                yield ErrorSummary(id="dec-errors")

    def update_state(self, state: dict[str, Any]) -> None:
        """Push decisions, transitions, and errors to child widgets."""
        try:
            self.query_one("#dec-log", DecisionLog).update_decisions(
                state.get("decisions", [])
            )
        except Exception:
            pass
        try:
            self.query_one("#dec-transitions", TransitionLog).update_transitions(
                state.get("transitions", [])
            )
        except Exception:
            pass
        try:
            self.query_one("#dec-errors", ErrorSummary).update_errors(
                state.get("errors", [])
            )
        except Exception:
            pass
