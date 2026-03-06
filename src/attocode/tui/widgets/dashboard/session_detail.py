"""Session detail pane — multi-tabbed session analysis view."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import ContentSwitcher, Static

from attocode.tracing.analysis import (
    InefficiencyDetector,
    SessionAnalyzer,
    TokenAnalyzer,
)
from attocode.tracing.analysis.views import (
    DetectedIssue,
    SessionSummaryView,
    TimelineEntry,
    TokenFlowPoint,
    TreeNode,
)
from attocode.tracing.collector import load_trace_session
from attocode.tracing.types import TraceSession
from attocode.tui.widgets.dashboard.viz import (
    ASCIITable,
    BarChart,
    PercentBar,
    SeverityBadge,
    SparkLine,
    TreeRenderer,
)


_SUB_TABS = [
    ("a", "Summary"),
    ("b", "Timeline"),
    ("c", "Tree"),
    ("d", "Tokens"),
    ("e", "Issues"),
]


class SessionDetailPane(Container):
    """Detail view for a single trace session with 5 sub-views.

    Sub-views:
      a) Summary — metrics grid, efficiency score
      b) Timeline — chronological event log
      c) Tree — hierarchical call tree
      d) Tokens — token flow, cost breakdown
      e) Issues — detected inefficiencies
    """

    DEFAULT_CSS = """
    SessionDetailPane {
        layout: vertical;
    }
    SessionDetailPane .sub-tab-bar {
        height: 1;
        dock: top;
        background: $surface;
        padding: 0 1;
    }
    SessionDetailPane .detail-content {
        height: 1fr;
        overflow-y: auto;
        padding: 1;
    }
    SessionDetailPane .section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    SessionDetailPane .back-hint {
        color: $text-muted;
        height: 1;
        dock: top;
    }
    """

    class BackRequested(Message):
        """User pressed Escape to go back to session browser."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session: TraceSession | None = None
        self._analyzer: SessionAnalyzer | None = None
        self._active_tab: str = "a"

    def compose(self) -> ComposeResult:
        yield Static("ESC: back to sessions  |  a-e: switch sub-view", classes="back-hint")
        # Sub-tab bar
        yield Static(self._render_tab_bar(), id="sub-tab-bar", classes="sub-tab-bar")
        # Content area with switcher
        with ContentSwitcher(id="detail-switcher", initial="summary-view"):
            with Vertical(id="summary-view", classes="detail-content"):
                yield Static(
                    "Select a session from the Sessions tab to view details.",
                    id="detail-empty-msg",
                )
            yield Vertical(id="timeline-view", classes="detail-content")
            yield Vertical(id="tree-view", classes="detail-content")
            yield Vertical(id="tokens-view", classes="detail-content")
            yield Vertical(id="issues-view", classes="detail-content")

    def _render_tab_bar(self) -> str:
        """Render the sub-tab bar text."""
        from rich.text import Text

        text = Text()
        for key, label in _SUB_TABS:
            if key == self._active_tab:
                text.append(f" [{key}:{label}] ", style="bold reverse")
            else:
                text.append(f"  {key}:{label}  ", style="dim")
        return str(text)  # Return plain string for Static; we use Rich below

    def _update_tab_bar(self) -> None:
        """Update the sub-tab bar display."""
        try:
            from rich.text import Text

            bar = self.query_one("#sub-tab-bar", Static)
            text = Text()
            for key, label in _SUB_TABS:
                if key == self._active_tab:
                    text.append(f" [{key}:{label}] ", style="bold reverse")
                else:
                    text.append(f"  {key}:{label}  ", style="dim")
            bar.update(text)
        except Exception:
            pass

    def load_session(self, file_path: str) -> None:
        """Load a trace session and populate all sub-views."""
        try:
            self._session = load_trace_session(file_path)
            self._analyzer = SessionAnalyzer(self._session)
            self._populate_summary()
            self._populate_timeline()
            self._populate_tree()
            self._populate_tokens()
            self._populate_issues()
        except Exception as e:
            try:
                container = self.query_one("#summary-view", Vertical)
                container.remove_children()
                container.mount(Static(f"Error loading session: {e}"))
            except Exception:
                pass

    def switch_tab(self, key: str) -> None:
        """Switch to a sub-view by letter key."""
        tab_map = {
            "a": "summary-view",
            "b": "timeline-view",
            "c": "tree-view",
            "d": "tokens-view",
            "e": "issues-view",
        }
        view_id = tab_map.get(key)
        if view_id:
            self._active_tab = key
            try:
                switcher = self.query_one("#detail-switcher", ContentSwitcher)
                switcher.current = view_id
                self._update_tab_bar()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Sub-view population
    # ------------------------------------------------------------------

    def _populate_summary(self) -> None:
        """Populate the summary sub-view with metrics grid."""
        if not self._analyzer:
            return
        try:
            container = self.query_one("#summary-view", Vertical)
            container.remove_children()
        except Exception:
            return

        summary = self._analyzer.summary()

        container.mount(Static("Session Summary", classes="section-title"))

        # Efficiency score with color
        from rich.text import Text

        eff_text = Text()
        eff_text.append("Efficiency Score: ", style="bold")
        eff = summary.efficiency_score
        eff_style = "green bold" if eff >= 70 else ("yellow bold" if eff >= 40 else "red bold")
        eff_text.append(f"{eff:.1f}%", style=eff_style)
        container.mount(Static(eff_text))

        # Efficiency bar
        bar = PercentBar(value=eff / 100.0)
        container.mount(bar)
        container.mount(Static(""))

        # Metrics table
        table = ASCIITable(
            headers=["Metric", "Value"],
            rows=[
                ("Session ID", summary.session_id[:30]),
                ("Goal", (summary.goal[:60] if summary.goal else "N/A")),
                ("Model", summary.model),
                ("Duration", f"{summary.duration_seconds:.1f}s ({summary.duration_seconds / 60:.1f}m)"),
                ("Iterations", str(summary.iterations)),
                ("Total Tokens", f"{summary.total_tokens:,}"),
                ("Total Cost", f"${summary.total_cost:.4f}"),
                ("LLM Calls", str(summary.llm_calls)),
                ("Tool Calls", str(summary.tool_calls)),
                ("Errors", str(summary.errors)),
                ("Compactions", str(summary.compactions)),
                ("Cache Hit Rate", f"{summary.cache_hit_rate:.0%}"),
                ("Avg Tokens/Iter", f"{summary.avg_tokens_per_iteration:,.0f}"),
                ("Avg Cost/Iter", f"${summary.avg_cost_per_iteration:.6f}"),
            ],
        )
        container.mount(table)

    def _populate_timeline(self) -> None:
        """Populate the timeline sub-view with chronological events."""
        if not self._analyzer:
            return
        try:
            container = self.query_one("#timeline-view", Vertical)
            container.remove_children()
        except Exception:
            return

        timeline = self._analyzer.timeline()
        container.mount(Static("Event Timeline", classes="section-title"))
        container.mount(Static(f"{len(timeline)} events"))
        container.mount(Static(""))

        # Render as table
        import time as _time

        rows: list[tuple[str, ...]] = []
        for entry in timeline[:200]:  # Limit to 200 entries
            ts = (
                _time.strftime("%H:%M:%S", _time.localtime(entry.timestamp))
                if entry.timestamp > 0
                else "?"
            )
            it = str(entry.iteration) if entry.iteration is not None else "-"
            dur = f"{entry.duration_ms:.0f}ms" if entry.duration_ms else "-"
            rows.append((ts, it, entry.event_kind[:20], dur, entry.summary[:50]))

        table = ASCIITable(
            headers=["Time", "Iter", "Kind", "Duration", "Summary"],
            rows=rows,
        )
        container.mount(table)

    def _populate_tree(self) -> None:
        """Populate the tree sub-view with hierarchical event tree."""
        if not self._analyzer:
            return
        try:
            container = self.query_one("#tree-view", Vertical)
            container.remove_children()
        except Exception:
            return

        tree_nodes = self._analyzer.tree()
        container.mount(Static("Iteration Tree", classes="section-title"))

        if not tree_nodes:
            container.mount(Static("No iteration data available."))
            return

        # TreeRenderer accepts a single TreeNode root; wrap the list in a
        # synthetic root node so every iteration appears as a child.
        synthetic_root = TreeNode(
            event_id="root",
            kind="iteration",
            label="Session",
            children=tree_nodes[:50],  # Limit
        )
        renderer = TreeRenderer(root=synthetic_root)
        container.mount(renderer)

    def _populate_tokens(self) -> None:
        """Populate the tokens sub-view with token flow data."""
        if not self._analyzer:
            return
        try:
            container = self.query_one("#tokens-view", Vertical)
            container.remove_children()
        except Exception:
            return

        flow = self._analyzer.token_flow()
        container.mount(Static("Token Flow", classes="section-title"))

        if not flow:
            container.mount(Static("No token data available."))
            return

        # Token sparkline
        total_tokens = [float(p.total_tokens) for p in flow]
        spark = SparkLine(data=total_tokens)
        container.mount(Static("Tokens per iteration:"))
        container.mount(spark)
        container.mount(Static(""))

        # Cost sparkline
        costs = [p.cumulative_cost for p in flow]
        if costs and costs[-1] > 0:
            cost_spark = SparkLine(data=[c * 10000 for c in costs])  # Scale for visibility
            container.mount(Static("Cumulative cost trend:"))
            container.mount(cost_spark)
            container.mount(Static(""))

        # Breakdown table with per-iteration cost
        rows: list[tuple[str, ...]] = []
        prev_cost = 0.0
        for p in flow[:100]:  # Limit
            iter_cost = p.cumulative_cost - prev_cost
            rows.append((
                str(p.iteration),
                f"{p.input_tokens:,}",
                f"{p.output_tokens:,}",
                f"{p.cache_read_tokens:,}",
                f"{p.cache_write_tokens:,}",
                f"{p.total_tokens:,}",
                f"${iter_cost:.4f}",
                f"${p.cumulative_cost:.4f}",
            ))
            prev_cost = p.cumulative_cost

        table = ASCIITable(
            headers=["Iter", "Input", "Output", "Cache Read", "Cache Write", "Total", "Iter Cost", "Cum. Cost"],
            rows=rows,
        )
        container.mount(table)

    def _populate_issues(self) -> None:
        """Populate the issues sub-view with detected inefficiencies."""
        if not self._session:
            return
        try:
            container = self.query_one("#issues-view", Vertical)
            container.remove_children()
        except Exception:
            return

        detector = InefficiencyDetector(self._session)
        issues = detector.detect_all()

        container.mount(Static("Detected Issues", classes="section-title"))

        if not issues:
            container.mount(Static("No issues detected. Session looks healthy!"))
            return

        container.mount(Static(f"{len(issues)} issue(s) found\n"))

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues.sort(key=lambda i: severity_order.get(i.severity, 4))

        for issue in issues:
            from rich.text import Text

            # Severity badge line
            badge_text = Text()
            sev_style_map = {
                "critical": "red bold",
                "high": "red",
                "medium": "yellow",
                "low": "cyan",
            }
            style = sev_style_map.get(issue.severity, "dim")
            badge_text.append(f"[{issue.severity.upper()}]", style=style)
            badge_text.append(f" {issue.title}", style="bold")
            container.mount(Static(badge_text))

            # Description
            container.mount(Static(f"  {issue.description}"))

            # Iteration reference
            if issue.iteration is not None:
                container.mount(Static(f"  Iteration: {issue.iteration}"))

            # Suggestion
            if issue.suggestion:
                sug = Text()
                sug.append("  Suggestion: ", style="green")
                sug.append(issue.suggestion)
                container.mount(Static(sug))

            container.mount(Static(""))  # Spacer
