"""Live dashboard pane — real-time agent monitoring."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from attocode.tui.widgets.dashboard.viz import SparkLine, BarChart, PercentBar


class LiveTraceAccumulator:
    """Accumulates real-time agent events for dashboard display.

    Maintains rolling windows of:
    - Per-iteration token counts (last 50)
    - Cache hit rates (last 20 LLM calls)
    - Tool frequency counter
    - Cumulative cost tracker
    """

    def __init__(self) -> None:
        self.token_history: list[float] = []
        self.cache_rates: list[float] = []
        self.tool_counts: dict[str, int] = {}
        self.total_cost: float = 0.0
        self.total_tokens: int = 0
        self.iteration: int = 0
        self.errors: int = 0
        self.tool_calls: int = 0
        self.budget_warnings: int = 0
        self.last_budget_pct: float = 0.0

    def record_llm(self, tokens: int, cost: float, cache_read: int = 0, input_tokens: int = 0) -> None:
        """Record an LLM completion event."""
        self.token_history.append(float(tokens))
        if len(self.token_history) > 50:
            self.token_history = self.token_history[-50:]
        self.total_tokens += tokens
        self.total_cost += cost
        # Cache rate
        denom = input_tokens + cache_read
        if denom > 0:
            self.cache_rates.append(cache_read / denom)
            if len(self.cache_rates) > 20:
                self.cache_rates = self.cache_rates[-20:]

    def record_tool(self, name: str, error: bool = False) -> None:
        """Record a tool completion event."""
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1
        self.tool_calls += 1
        if error:
            self.errors += 1

    def record_iteration(self, iteration: int) -> None:
        """Record iteration update."""
        self.iteration = iteration

    @property
    def avg_cache_rate(self) -> float:
        if not self.cache_rates:
            return 0.0
        return sum(self.cache_rates) / len(self.cache_rates)

    @property
    def top_tools(self) -> list[tuple[str, int]]:
        """Return top 8 tools by frequency."""
        return sorted(self.tool_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    @property
    def error_rate(self) -> float:
        if self.tool_calls == 0:
            return 0.0
        return self.errors / self.tool_calls


class LiveDashboardPane(Container):
    """Real-time agent monitoring pane with 2x2 grid of metric boxes."""

    DEFAULT_CSS = """
    LiveDashboardPane {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
        padding: 1 2;
        overflow-y: auto;
    }
    LiveDashboardPane .metric-box {
        border: round $primary;
        padding: 0 1;
        height: auto;
        min-height: 5;
    }
    LiveDashboardPane .metric-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    """

    def __init__(self, accumulator: LiveTraceAccumulator | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._acc = accumulator or LiveTraceAccumulator()

    def compose(self) -> ComposeResult:
        # Token usage box
        with Container(classes="metric-box", id="token-box"):
            yield Static("Token Usage", classes="metric-title")
            yield SparkLine(id="live-token-spark")
            yield Static("", id="token-stats")

        # Cache efficiency box
        with Container(classes="metric-box", id="cache-box"):
            yield Static("Cache Efficiency", classes="metric-title")
            yield PercentBar(id="live-cache-bar")
            yield Static("", id="cache-stats")

        # Tool frequency box
        with Container(classes="metric-box", id="tool-box"):
            yield Static("Tool Frequency", classes="metric-title")
            yield BarChart(id="live-tool-chart")

        # Session stats box
        with Container(classes="metric-box", id="stats-box"):
            yield Static("Session Stats", classes="metric-title")
            yield Static("", id="session-stats")

    def refresh_data(self) -> None:
        """Update all widgets with latest accumulator data."""
        acc = self._acc

        # Token sparkline
        try:
            spark = self.query_one("#live-token-spark", SparkLine)
            spark.data = acc.token_history
        except Exception:
            pass

        # Token stats text
        try:
            stats = self.query_one("#token-stats", Static)
            stats.update(
                f"Total: {acc.total_tokens:,} tokens  |  "
                f"Cost: ${acc.total_cost:.4f}"
            )
        except Exception:
            pass

        # Cache bar
        try:
            cache_bar = self.query_one("#live-cache-bar", PercentBar)
            cache_bar.value = acc.avg_cache_rate
        except Exception:
            pass

        # Cache stats
        try:
            cache_stats = self.query_one("#cache-stats", Static)
            rate = acc.avg_cache_rate
            cache_stats.update(f"Avg cache hit rate: {rate:.0%}")
        except Exception:
            pass

        # Tool chart
        try:
            tool_chart = self.query_one("#live-tool-chart", BarChart)
            top = acc.top_tools
            if top:
                tool_chart.items = [(name, float(count)) for name, count in top]
        except Exception:
            pass

        # Session stats
        try:
            stats_widget = self.query_one("#session-stats", Static)
            error_pct = f"{acc.error_rate:.0%}" if acc.tool_calls > 0 else "N/A"
            budget_str = (
                f"Budget warnings: {acc.budget_warnings} (last: {acc.last_budget_pct:.0%})"
                if acc.budget_warnings > 0
                else "Budget warnings: 0"
            )
            stats_widget.update(
                f"Iteration: {acc.iteration}\n"
                f"Tool calls: {acc.tool_calls}\n"
                f"Errors: {acc.errors} ({error_pct})\n"
                f"LLM calls: {len(acc.token_history)}\n"
                f"{budget_str}"
            )
        except Exception:
            pass

    @property
    def accumulator(self) -> LiveTraceAccumulator:
        return self._acc
