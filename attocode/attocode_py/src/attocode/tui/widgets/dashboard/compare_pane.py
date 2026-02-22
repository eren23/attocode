"""Compare pane — side-by-side session comparison."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static

from attocode.tracing.analysis import SessionAnalyzer, SessionSummaryView
from attocode.tracing.collector import load_trace_session
from attocode.tui.widgets.dashboard.viz import ASCIITable, PercentBar


class ComparePane(Container):
    """Side-by-side comparison of two trace sessions."""

    DEFAULT_CSS = """
    ComparePane {
        layout: horizontal;
        padding: 1 2;
    }
    ComparePane .compare-column {
        width: 1fr;
        border: round $surface-lighten-2;
        padding: 0 1;
        margin: 0 1;
        overflow-y: auto;
    }
    ComparePane .compare-header {
        text-style: bold;
        color: $accent;
        text-align: center;
        margin-bottom: 1;
    }
    ComparePane .no-selection {
        text-align: center;
        color: $text-muted;
        margin-top: 3;
        width: 100%;
    }
    ComparePane .metric-row {
        height: 1;
    }
    ComparePane .better {
        color: $success;
    }
    ComparePane .worse {
        color: $error;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_a: SessionSummaryView | None = None
        self._session_b: SessionSummaryView | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "Mark two sessions with [bold]c[/bold] in the Sessions tab, then switch here.",
            classes="no-selection",
            id="compare-empty-msg",
        )

    def load_sessions(self, path_a: str, path_b: str) -> None:
        """Load two sessions and render comparison."""
        try:
            session_a = load_trace_session(path_a)
            session_b = load_trace_session(path_b)
            self._session_a = SessionAnalyzer(session_a).summary()
            self._session_b = SessionAnalyzer(session_b).summary()
            self._render_comparison()
        except Exception as e:
            self.remove_children()
            self.mount(Static(f"Error loading sessions: {e}", classes="no-selection"))

    def _render_comparison(self) -> None:
        """Render the side-by-side comparison."""
        if not self._session_a or not self._session_b:
            return

        self.remove_children()

        a = self._session_a
        b = self._session_b

        # Build comparison rows
        metrics = [
            ("Duration", f"{a.duration_seconds:.1f}s", f"{b.duration_seconds:.1f}s", a.duration_seconds < b.duration_seconds),
            ("Iterations", str(a.iterations), str(b.iterations), a.iterations <= b.iterations),
            ("Total Tokens", f"{a.total_tokens:,}", f"{b.total_tokens:,}", a.total_tokens < b.total_tokens),
            ("Total Cost", f"${a.total_cost:.4f}", f"${b.total_cost:.4f}", a.total_cost < b.total_cost),
            ("Tool Calls", str(a.tool_calls), str(b.tool_calls), True),
            ("LLM Calls", str(a.llm_calls), str(b.llm_calls), a.llm_calls <= b.llm_calls),
            ("Errors", str(a.errors), str(b.errors), a.errors <= b.errors),
            ("Compactions", str(a.compactions), str(b.compactions), a.compactions <= b.compactions),
            ("Efficiency", f"{a.efficiency_score:.1f}%", f"{b.efficiency_score:.1f}%", a.efficiency_score >= b.efficiency_score),
            ("Cache Rate", f"{a.cache_hit_rate:.0%}", f"{b.cache_hit_rate:.0%}", a.cache_hit_rate >= b.cache_hit_rate),
            ("Avg Tok/Iter", f"{a.avg_tokens_per_iteration:,.0f}", f"{b.avg_tokens_per_iteration:,.0f}", a.avg_tokens_per_iteration < b.avg_tokens_per_iteration),
            ("Avg Cost/Iter", f"${a.avg_cost_per_iteration:.6f}", f"${b.avg_cost_per_iteration:.6f}", a.avg_cost_per_iteration < b.avg_cost_per_iteration),
        ]

        # Column A
        col_a = Container(classes="compare-column")
        col_a_header = Static(f"Session A: {a.session_id[:20]}", classes="compare-header")

        # Column B
        col_b = Container(classes="compare-column")
        col_b_header = Static(f"Session B: {b.session_id[:20]}", classes="compare-header")

        with self.app.batch_update():
            self.mount(col_a)
            self.mount(col_b)
            col_a.mount(col_a_header)
            col_b.mount(col_b_header)

            # Goals
            col_a.mount(Static(f"Goal: {a.goal[:60]}", classes="metric-row"))
            col_b.mount(Static(f"Goal: {b.goal[:60]}", classes="metric-row"))
            col_a.mount(Static(f"Model: {a.model}", classes="metric-row"))
            col_b.mount(Static(f"Model: {b.model}", classes="metric-row"))
            col_a.mount(Static("─" * 30))
            col_b.mount(Static("─" * 30))

            for label, val_a, val_b, a_better in metrics:
                from rich.text import Text
                text_a = Text()
                text_a.append(f"{label}: ", style="dim")
                text_a.append(val_a, style="green bold" if a_better else "")
                col_a.mount(Static(text_a, classes="metric-row"))

                text_b = Text()
                text_b.append(f"{label}: ", style="dim")
                text_b.append(val_b, style="green bold" if not a_better else "")
                col_b.mount(Static(text_b, classes="metric-row"))
