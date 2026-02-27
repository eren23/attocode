"""Tab 7: Quality Gates pane — quality stats, scores, wave reviews."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Static


class QualitySummaryBar(Widget):
    """Aggregate quality stats: rejections, retries, hollows, avg score."""

    DEFAULT_CSS = """
    QualitySummaryBar {
        height: auto;
        min-height: 3;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._stats: dict[str, Any] = {}
        self._quality_results: dict[str, dict[str, Any]] = {}

    def render(self) -> Text:
        text = Text()
        text.append("Quality Summary\n", style="bold underline")

        s = self._stats
        rej = s.get("total_rejections", 0)
        ret = s.get("total_retries", 0)
        hollow = s.get("hollow_streak", 0)
        total_h = s.get("total_hollows", 0)
        dispatches = s.get("total_dispatches", 0)

        text.append(f"  Rejections: {rej}  ", style="red dim" if rej > 0 else "dim")
        text.append(f"Retries: {ret}  ", style="yellow dim" if ret > 0 else "dim")
        text.append(f"Hollows: {total_h} (streak: {hollow})  ", style="red dim" if hollow > 0 else "dim")
        text.append(f"Dispatches: {dispatches}\n", style="dim")

        # Average quality score
        scores = [
            r.get("score", 0) for r in self._quality_results.values()
            if r.get("score") is not None
        ]
        if scores:
            avg = sum(scores) / len(scores)
            avg_style = "green" if avg >= 3.5 else "yellow" if avg >= 2.5 else "red"
            text.append(f"  Avg Score: {avg:.1f}/5 ({len(scores)} evaluated)\n", style=avg_style)

        return text

    def update_stats(
        self,
        stats: dict[str, Any],
        quality_results: dict[str, dict[str, Any]],
    ) -> None:
        self._stats = stats
        self._quality_results = quality_results
        self.refresh()


class QualityScoreTable(Widget):
    """DataTable showing per-task quality scores."""

    DEFAULT_CSS = """
    QualityScoreTable {
        height: 1fr;
        border: solid $accent;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._results: dict[str, dict[str, Any]] = {}
        self._table_initialized = False

    def compose(self):
        yield DataTable(id="quality-scores-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#quality-scores-table", DataTable)
        table.add_columns("Task ID", "Score", "Passed", "Feedback")
        self._table_initialized = True

    def update_results(self, results: dict[str, dict[str, Any]]) -> None:
        self._results = results
        if not self._table_initialized:
            return

        try:
            table = self.query_one("#quality-scores-table", DataTable)
            table.clear()

            for tid, r in sorted(results.items()):
                score = r.get("score", "?")
                passed = r.get("passed", False)
                feedback = r.get("feedback", "")[:60]

                score_style = "green" if passed else "red"
                table.add_row(
                    tid[:16],
                    Text(str(score), style=score_style),
                    Text("Yes" if passed else "No", style=score_style),
                    feedback,
                    key=tid,
                )
        except Exception:
            pass


class WaveReviewLog(Widget):
    """Wave review assessments and hollow detection events."""

    DEFAULT_CSS = """
    WaveReviewLog {
        height: auto;
        min-height: 4;
        max-height: 15;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._reviews: list[dict[str, Any]] = []

    def render(self) -> Text:
        text = Text()
        text.append("Wave Reviews\n", style="bold underline")

        if not self._reviews:
            text.append("No wave reviews yet", style="dim italic")
            return text

        for r in self._reviews[-20:]:
            ts = r.get("timestamp", 0)
            t = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "??:??:??"
            wave = r.get("wave", "?")
            fixups = r.get("fixup_count", 0)

            text.append(f"[{t}] ", style="dim")
            text.append(f"Wave {wave}: ", style="bold")
            text.append(f"{r.get('assessment', '')}", style="dim")
            if fixups > 0:
                text.append(f" ({fixups} fix-ups)", style="yellow")
            text.append("\n")

        return text

    def update_reviews(self, reviews: list[dict[str, Any]]) -> None:
        self._reviews = reviews
        self.refresh()


class QualityPane(Widget):
    """Quality gates dashboard: summary + scores + wave reviews."""

    DEFAULT_CSS = """
    QualityPane {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield QualitySummaryBar(id="quality-summary")
            yield QualityScoreTable(id="quality-scores")
            yield WaveReviewLog(id="quality-waves")

    def update_state(self, state: dict[str, Any]) -> None:
        """Push quality data to child widgets."""
        quality_stats = state.get("quality_stats", {})
        quality_results = state.get("quality_results", {})
        wave_reviews = state.get("wave_reviews", [])

        try:
            self.query_one("#quality-summary", QualitySummaryBar).update_stats(
                quality_stats, quality_results
            )
        except Exception:
            pass
        try:
            self.query_one("#quality-scores", QualityScoreTable).update_results(
                quality_results
            )
        except Exception:
            pass
        try:
            self.query_one("#quality-waves", WaveReviewLog).update_reviews(
                wave_reviews
            )
        except Exception:
            pass
