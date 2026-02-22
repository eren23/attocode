"""Dashboard screen — multi-tab trace analysis and monitoring.

Pushed via Ctrl+D from the main chat screen. Uses Textual's Screen
system for clean separation from the chat interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Footer, Static

from attocode.tui.widgets.dashboard.compare_pane import ComparePane
from attocode.tui.widgets.dashboard.live_dashboard import (
    LiveDashboardPane,
    LiveTraceAccumulator,
)
from attocode.tui.widgets.dashboard.session_browser import SessionBrowserPane
from attocode.tui.widgets.dashboard.session_detail import SessionDetailPane
from attocode.tui.widgets.dashboard.swarm_activity_pane import SwarmActivityPane

# Tab definitions: (number key, label, pane widget id)
_TABS = [
    ("1", "Live", "pane-live"),
    ("2", "Sessions", "pane-sessions"),
    ("3", "Detail", "pane-detail"),
    ("4", "Compare", "pane-compare"),
    ("5", "Swarm", "pane-swarm"),
]


class DashboardScreen(Screen):
    """Multi-tab dashboard screen for trace analysis and live monitoring.

    Tabs:
      1. Live — real-time agent metrics (tokens, cache, tools)
      2. Sessions — browse past trace sessions
      3. Detail — deep-dive into a single session (5 sub-views)
      4. Compare — side-by-side session comparison
      5. Swarm — multi-agent orchestration monitoring

    Keyboard shortcuts:
      1-5     — Jump to tab
      Tab     — Next tab
      Shift+Tab — Previous tab
      a-e     — Switch sub-view (in Detail tab)
      Escape  — Go back (detail → sessions → close dashboard)
      r       — Refresh data
    """

    CSS_PATH = [Path(__file__).parent.parent / "styles" / "dashboard.tcss"]

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
        Binding("1", "tab_1", "Live", show=True),
        Binding("2", "tab_2", "Sessions", show=True),
        Binding("3", "tab_3", "Detail", show=False),
        Binding("4", "tab_4", "Compare", show=False),
        Binding("5", "tab_5", "Swarm", show=False),
        Binding("tab", "next_tab", "Next Tab", show=False),
        Binding("shift+tab", "prev_tab", "Prev Tab", show=False),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("s", "sort_sessions", "Sort", show=False),
        # Detail sub-view keys
        Binding("a", "detail_a", "Summary", show=False),
        Binding("b", "detail_b", "Timeline", show=False),
        Binding("c", "detail_c", "Tree", show=False),
        Binding("d", "detail_d", "Tokens", show=False),
        Binding("e", "detail_e", "Issues", show=False),
    ]

    def __init__(
        self,
        agent: Any = None,
        trace_dir: str | Path = "",
        accumulator: LiveTraceAccumulator | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._trace_dir = Path(trace_dir) if trace_dir else Path(".attocode/traces")
        self._accumulator = accumulator or LiveTraceAccumulator()
        self._active_tab_index: int = 0
        self._in_detail: bool = False
        self._refresh_timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dashboard-container"):
            # Tab bar header
            yield Static(self._render_tab_bar(), id="dashboard-tab-bar", classes="dashboard-header-bar")
            # Content switcher with all panes
            with ContentSwitcher(id="dashboard-switcher", initial="pane-live"):
                yield LiveDashboardPane(
                    accumulator=self._accumulator,
                    id="pane-live",
                )
                yield SessionBrowserPane(
                    trace_dir=self._trace_dir,
                    id="pane-sessions",
                )
                yield SessionDetailPane(id="pane-detail")
                yield ComparePane(id="pane-compare")
                yield SwarmActivityPane(id="pane-swarm")
            # Footer with keybinds
            yield Static(
                "[1-5] tabs  [Tab] next  [Esc] back  [r] refresh",
                id="dashboard-footer-bar",
                classes="dashboard-footer-bar",
            )
        yield Footer()

    def on_mount(self) -> None:
        """Start the refresh timer for the live pane."""
        self._refresh_timer = self.set_interval(2.0, self._auto_refresh)

    def on_unmount(self) -> None:
        """Stop refresh timer."""
        if self._refresh_timer:
            self._refresh_timer.stop()

    # ------------------------------------------------------------------
    # Tab bar rendering
    # ------------------------------------------------------------------

    def _render_tab_bar(self) -> str:
        """Render the tab bar as a Rich string."""
        from rich.text import Text
        text = Text()
        text.append(" DASHBOARD ", style="bold reverse")
        text.append("  ")
        for i, (key, label, _) in enumerate(_TABS):
            if i == self._active_tab_index:
                text.append(f" {key}:{label} ", style="bold on blue")
            else:
                text.append(f" {key}:{label} ", style="dim")
            text.append(" ")
        return text  # Static.update() accepts Text objects

    def _update_tab_bar(self) -> None:
        """Refresh the tab bar display."""
        try:
            bar = self.query_one("#dashboard-tab-bar", Static)
            bar.update(self._render_tab_bar())
        except Exception:
            pass

    def _switch_tab(self, index: int) -> None:
        """Switch to the tab at the given index."""
        if 0 <= index < len(_TABS):
            self._active_tab_index = index
            self._in_detail = (index == 2)  # Detail tab
            _, _, pane_id = _TABS[index]
            try:
                switcher = self.query_one("#dashboard-switcher", ContentSwitcher)
                switcher.current = pane_id
                self._update_tab_bar()
                self._update_footer()
            except Exception:
                pass

    def _update_footer(self) -> None:
        """Update footer based on current tab."""
        try:
            footer = self.query_one("#dashboard-footer-bar", Static)
            if self._active_tab_index == 2:  # Detail
                footer.update("[a-e] views  [Esc] back to sessions  [r] refresh")
            elif self._active_tab_index == 1:  # Sessions
                footer.update("[Enter] open  [/] search  [c] mark compare  [Esc] close dashboard")
            else:
                footer.update("[1-5] tabs  [Tab] next  [Esc] close dashboard  [r] refresh")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tab actions
    # ------------------------------------------------------------------

    def action_tab_1(self) -> None:
        self._switch_tab(0)

    def action_tab_2(self) -> None:
        self._switch_tab(1)

    def action_tab_3(self) -> None:
        self._switch_tab(2)

    def action_tab_4(self) -> None:
        self._switch_tab(3)

    def action_tab_5(self) -> None:
        self._switch_tab(4)

    def action_next_tab(self) -> None:
        self._switch_tab((self._active_tab_index + 1) % len(_TABS))

    def action_prev_tab(self) -> None:
        self._switch_tab((self._active_tab_index - 1) % len(_TABS))

    def action_go_back(self) -> None:
        """Handle Escape — context-dependent back navigation."""
        if self._in_detail:
            # Go back to sessions tab
            self._switch_tab(1)
        else:
            # Close dashboard, return to chat
            self.dismiss()

    def action_refresh(self) -> None:
        """Refresh the current pane's data."""
        self._refresh_current_pane()

    def action_sort_sessions(self) -> None:
        """Cycle session sort order (only active on Sessions tab)."""
        if self._active_tab_index == 1:
            try:
                self.query_one("#pane-sessions", SessionBrowserPane).cycle_sort()
            except Exception:
                pass

    # Detail sub-view actions
    def action_detail_a(self) -> None:
        if self._active_tab_index == 2:
            self.query_one("#pane-detail", SessionDetailPane).switch_tab("a")

    def action_detail_b(self) -> None:
        if self._active_tab_index == 2:
            self.query_one("#pane-detail", SessionDetailPane).switch_tab("b")

    def action_detail_c(self) -> None:
        if self._active_tab_index == 2:
            self.query_one("#pane-detail", SessionDetailPane).switch_tab("c")

    def action_detail_d(self) -> None:
        if self._active_tab_index == 2:
            self.query_one("#pane-detail", SessionDetailPane).switch_tab("d")

    def action_detail_e(self) -> None:
        if self._active_tab_index == 2:
            self.query_one("#pane-detail", SessionDetailPane).switch_tab("e")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_session_browser_pane_session_opened(self, event: SessionBrowserPane.SessionOpened) -> None:
        """User selected a session in the browser — open detail view."""
        detail = self.query_one("#pane-detail", SessionDetailPane)
        detail.load_session(event.file_path)
        self._switch_tab(2)  # Switch to Detail tab

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------

    def _auto_refresh(self) -> None:
        """Periodic refresh for the live dashboard pane."""
        if self._active_tab_index == 0:  # Live tab
            self._refresh_current_pane()

    def _refresh_current_pane(self) -> None:
        """Refresh the currently visible pane."""
        try:
            if self._active_tab_index == 0:
                self.query_one("#pane-live", LiveDashboardPane).refresh_data()
            elif self._active_tab_index == 4:
                # Swarm pane refreshes via events
                pass
        except Exception:
            pass
