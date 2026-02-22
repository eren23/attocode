"""Session browser pane — filterable list of past sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Input, Static

from attocode.tracing.analysis import SessionAnalyzer
from attocode.tracing.collector import load_trace_session


@dataclass(slots=True)
class SessionInfo:
    """Lightweight session metadata for the browser list."""
    session_id: str
    goal: str
    model: str
    duration_seconds: float
    total_tokens: int
    total_cost: float
    iterations: int
    efficiency_score: float
    file_path: str


class SessionCard(Static):
    """A single session row in the browser list."""

    class Selected(Message):
        """Emitted when a session card is clicked/selected."""
        def __init__(self, session_id: str, file_path: str) -> None:
            super().__init__()
            self.session_id = session_id
            self.file_path = file_path

    def __init__(self, info: SessionInfo, **kwargs) -> None:
        super().__init__(**kwargs)
        self.info = info
        self._selected = False

    def on_mount(self) -> None:
        self._render_card()

    def _render_card(self) -> None:
        from rich.text import Text
        info = self.info
        text = Text()
        # Session ID (truncated)
        sid = info.session_id[:20]
        text.append(f"{sid:<22}", style="bold")
        # Goal (truncated)
        goal = (info.goal[:40] + "...") if len(info.goal) > 40 else info.goal
        text.append(f"{goal:<45}", style="dim")
        # Duration
        mins = info.duration_seconds / 60
        text.append(f"{mins:>5.1f}m ", style="cyan")
        # Cost
        text.append(f"${info.total_cost:>7.4f} ", style="green")
        # Efficiency
        eff = info.efficiency_score
        eff_style = "green" if eff >= 70 else ("yellow" if eff >= 40 else "red")
        text.append(f"{eff:>5.1f}%", style=eff_style)
        self.update(text)

    def on_click(self) -> None:
        self.post_message(self.Selected(self.info.session_id, self.info.file_path))

    def select(self) -> None:
        self._selected = True
        self.add_class("selected")

    def deselect(self) -> None:
        self._selected = False
        self.remove_class("selected")


class SessionBrowserPane(Container):
    """Filterable session browser with search and session cards."""

    DEFAULT_CSS = """
    SessionBrowserPane {
        layout: vertical;
        padding: 0;
    }
    SessionBrowserPane .search-bar {
        height: 3;
        dock: top;
        padding: 0 1;
    }
    SessionBrowserPane .session-list {
        height: 1fr;
        overflow-y: auto;
    }
    SessionBrowserPane .session-header {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    SessionBrowserPane SessionCard {
        height: 1;
        padding: 0 1;
    }
    SessionBrowserPane SessionCard:hover {
        background: $primary 15%;
    }
    SessionBrowserPane SessionCard.selected {
        background: $primary 25%;
    }
    SessionBrowserPane .empty-message {
        text-align: center;
        color: $text-muted;
        margin-top: 3;
    }
    """

    class SessionOpened(Message):
        """Emitted when user opens a session for detail view."""
        def __init__(self, session_id: str, file_path: str) -> None:
            super().__init__()
            self.session_id = session_id
            self.file_path = file_path

    # Sort modes: (label, key function, reverse)
    _SORT_MODES: list[tuple[str, str, bool]] = [
        ("Newest first", "duration_seconds", True),  # Default: file mtime order (already sorted)
        ("Cost desc", "total_cost", True),
        ("Efficiency desc", "efficiency_score", True),
        ("Iterations desc", "iterations", True),
    ]

    def __init__(self, trace_dir: str | Path = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._trace_dir = Path(trace_dir) if trace_dir else Path(".attocode/traces")
        self._sessions: list[SessionInfo] = []
        self._selected_index: int = -1
        self._filter_text: str = ""
        self._sort_index: int = 0
        # Sessions marked for comparison
        self.marked_for_compare: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter sessions... (/)", id="session-search", classes="search-bar")
        yield Static("ID                    Goal                                          Time    Cost   Score", classes="session-header")
        with Vertical(id="session-list-container", classes="session-list"):
            yield Static("Loading sessions...", classes="empty-message", id="loading-msg")

    async def on_mount(self) -> None:
        """Load sessions on mount."""
        await self.load_sessions()

    async def load_sessions(self) -> None:
        """Scan trace directory and load session summaries."""
        self._sessions.clear()

        if not self._trace_dir.exists():
            try:
                msg = self.query_one("#loading-msg", Static)
                msg.update("No trace sessions found. Run an agent task to generate traces.")
            except Exception:
                pass
            return

        jsonl_files = sorted(self._trace_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

        if not jsonl_files:
            try:
                msg = self.query_one("#loading-msg", Static)
                msg.update("No trace sessions found. Run an agent task to generate traces.")
            except Exception:
                pass
            return

        # Load in background to avoid blocking
        for path in jsonl_files[:50]:  # Limit to 50 most recent
            try:
                session = load_trace_session(path)
                analyzer = SessionAnalyzer(session)
                summary = analyzer.summary()
                self._sessions.append(SessionInfo(
                    session_id=summary.session_id,
                    goal=summary.goal,
                    model=summary.model,
                    duration_seconds=summary.duration_seconds,
                    total_tokens=summary.total_tokens,
                    total_cost=summary.total_cost,
                    iterations=summary.iterations,
                    efficiency_score=summary.efficiency_score,
                    file_path=str(path),
                ))
            except Exception:
                continue

        self._render_list()

    def _render_list(self) -> None:
        """Re-render the session list with current filter."""
        try:
            container = self.query_one("#session-list-container", Vertical)
        except Exception:
            return

        # Remove existing cards and loading message
        container.remove_children()

        filtered = self._filtered_sessions()
        if not filtered:
            container.mount(Static("No sessions match filter.", classes="empty-message"))
            return

        for info in filtered:
            card = SessionCard(info, classes="session-card")
            container.mount(card)

    def _filtered_sessions(self) -> list[SessionInfo]:
        """Apply text filter and sort to sessions."""
        if self._filter_text:
            ft = self._filter_text.lower()
            result = [
                s for s in self._sessions
                if ft in s.session_id.lower() or ft in s.goal.lower() or ft in s.model.lower()
            ]
        else:
            result = list(self._sessions)

        # Apply sort (index 0 = default file mtime order, no re-sort needed)
        if self._sort_index > 0:
            _, sort_key, reverse = self._SORT_MODES[self._sort_index]
            result.sort(key=lambda s: getattr(s, sort_key, 0), reverse=reverse)

        return result

    def cycle_sort(self) -> None:
        """Cycle through sort modes and re-render."""
        self._sort_index = (self._sort_index + 1) % len(self._SORT_MODES)
        self._render_list()
        label, _, _ = self._SORT_MODES[self._sort_index]
        self.notify(f"Sort: {label}", timeout=2)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "session-search":
            self._filter_text = event.value
            self._render_list()

    def on_session_card_selected(self, event: SessionCard.Selected) -> None:
        """Handle session card selection — open detail view."""
        self.post_message(self.SessionOpened(event.session_id, event.file_path))

    def mark_for_compare(self, session_id: str) -> None:
        """Toggle a session for comparison."""
        if session_id in self.marked_for_compare:
            self.marked_for_compare.remove(session_id)
        else:
            if len(self.marked_for_compare) < 2:
                self.marked_for_compare.append(session_id)
