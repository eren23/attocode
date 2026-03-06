"""Dashboard widgets for the Attocode TUI."""

from __future__ import annotations

from attocode.tui.widgets.dashboard.compare_pane import ComparePane
from attocode.tui.widgets.dashboard.live_dashboard import (
    LiveDashboardPane,
    LiveTraceAccumulator,
)
from attocode.tui.widgets.dashboard.session_browser import (
    SessionBrowserPane,
    SessionCard,
    SessionInfo,
)
from attocode.tui.widgets.dashboard.session_detail import SessionDetailPane
from attocode.tui.widgets.dashboard.swarm_activity_pane import SwarmActivityPane

__all__ = [
    "ComparePane",
    "LiveDashboardPane",
    "LiveTraceAccumulator",
    "SessionBrowserPane",
    "SessionCard",
    "SessionDetailPane",
    "SessionInfo",
    "SwarmActivityPane",
]
