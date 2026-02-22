"""Tests for visualization widgets (SparkLine, BarChart, PercentBar, ASCIITable, SeverityBadge)."""

from __future__ import annotations

import pytest

from rich.text import Text

from attocode.tui.widgets.dashboard.viz.sparkline import SparkLine
from attocode.tui.widgets.dashboard.viz.bar_chart import BarChart
from attocode.tui.widgets.dashboard.viz.percent_bar import PercentBar
from attocode.tui.widgets.dashboard.viz.ascii_table import ASCIITable
from attocode.tui.widgets.dashboard.viz.severity_badge import SeverityBadge


# ---------------------------------------------------------------------------
# SparkLine
# ---------------------------------------------------------------------------


class TestSparkLine:
    def test_empty_data(self) -> None:
        spark = SparkLine(data=[])
        result = spark.render()
        assert isinstance(result, Text)
        assert str(result) == ""

    def test_single_point(self) -> None:
        spark = SparkLine(data=[5.0])
        result = spark.render()
        assert len(str(result)) == 1

    def test_all_same_values(self) -> None:
        spark = SparkLine(data=[3.0, 3.0, 3.0, 3.0])
        result = spark.render()
        rendered = str(result)
        # All same → all mapped to same block char
        assert len(set(rendered)) == 1
        assert len(rendered) == 4

    def test_normal_range(self) -> None:
        spark = SparkLine(data=[1.0, 5.0, 3.0, 8.0, 2.0])
        result = spark.render()
        rendered = str(result)
        assert len(rendered) == 5
        # All chars should be Unicode block elements
        for ch in rendered:
            assert ord(ch) >= 0x2581  # lowest block element

    def test_respects_max_width(self) -> None:
        spark = SparkLine(data=list(range(100)), max_width=20)
        result = spark.render()
        assert len(str(result)) <= 20


# ---------------------------------------------------------------------------
# BarChart
# ---------------------------------------------------------------------------


class TestBarChart:
    def test_empty_items(self) -> None:
        chart = BarChart(items=[])
        result = chart.render()
        assert "(no data)" in str(result)

    def test_single_item(self) -> None:
        chart = BarChart(items=[("Python", 42.0)])
        result = chart.render()
        rendered = str(result)
        assert "Python" in rendered
        assert "42" in rendered

    def test_label_alignment(self) -> None:
        chart = BarChart(items=[("Go", 10.0), ("Python", 45.0)])
        result = chart.render()
        rendered = str(result)
        assert "Go" in rendered
        assert "Python" in rendered

    def test_bar_proportions(self) -> None:
        chart = BarChart(items=[("A", 100.0), ("B", 50.0)], bar_width=20)
        result = chart.render()
        rendered = str(result)
        lines = rendered.split("\n")
        assert len(lines) == 2

    def test_zero_max_value(self) -> None:
        chart = BarChart(items=[("A", 0.0), ("B", 0.0)])
        result = chart.render()
        # Should not crash
        assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# PercentBar
# ---------------------------------------------------------------------------


class TestPercentBar:
    def test_zero_percent(self) -> None:
        bar = PercentBar(value=0.0)
        result = bar.render()
        rendered = str(result)
        assert "0%" in rendered

    def test_fifty_percent(self) -> None:
        bar = PercentBar(value=0.5)
        result = bar.render()
        rendered = str(result)
        assert "50%" in rendered

    def test_hundred_percent(self) -> None:
        bar = PercentBar(value=1.0)
        result = bar.render()
        rendered = str(result)
        assert "100%" in rendered

    def test_over_hundred_clamped(self) -> None:
        bar = PercentBar(value=1.5)
        result = bar.render()
        rendered = str(result)
        # Should clamp to 100%
        assert "100%" in rendered

    def test_negative_clamped(self) -> None:
        bar = PercentBar(value=-0.5)
        result = bar.render()
        rendered = str(result)
        assert "0%" in rendered

    def test_threshold_colors_green(self) -> None:
        bar = PercentBar(value=0.3)
        result = bar.render()
        # Green range (< 0.60) — check the span has "green" style
        spans = result._spans
        green_found = any("green" in str(s.style) for s in spans)
        assert green_found

    def test_threshold_colors_yellow(self) -> None:
        bar = PercentBar(value=0.7)
        result = bar.render()
        spans = result._spans
        yellow_found = any("yellow" in str(s.style) for s in spans)
        assert yellow_found

    def test_threshold_colors_red(self) -> None:
        bar = PercentBar(value=0.95)
        result = bar.render()
        spans = result._spans
        red_found = any("red" in str(s.style) for s in spans)
        assert red_found

    def test_with_label(self) -> None:
        bar = PercentBar(value=0.5, label="Budget")
        result = bar.render()
        assert "Budget" in str(result)


# ---------------------------------------------------------------------------
# ASCIITable
# ---------------------------------------------------------------------------


class TestASCIITable:
    def test_empty_headers(self) -> None:
        table = ASCIITable(headers=[], rows=[])
        result = table.render()
        assert "(no data)" in str(result)

    def test_single_row(self) -> None:
        table = ASCIITable(
            headers=["Name", "Value"],
            rows=[("Tokens", "1,234")],
        )
        result = table.render()
        rendered = str(result)
        assert "Name" in rendered
        assert "Value" in rendered
        assert "Tokens" in rendered
        assert "1,234" in rendered

    def test_column_alignment(self) -> None:
        table = ASCIITable(
            headers=["A", "B"],
            rows=[("short", "x"), ("a very long value", "y")],
        )
        result = table.render()
        rendered = str(result)
        lines = rendered.split("\n")
        # Header + separator + 2 data rows = 4 lines
        assert len(lines) == 4

    def test_separator_present(self) -> None:
        table = ASCIITable(
            headers=["Col1", "Col2"],
            rows=[("a", "b")],
        )
        result = table.render()
        rendered = str(result)
        assert "-+-" in rendered

    def test_missing_cells(self) -> None:
        table = ASCIITable(
            headers=["A", "B", "C"],
            rows=[("x",)],  # Fewer cells than headers
        )
        result = table.render()
        # Should not crash — missing cells are empty
        assert "x" in str(result)

    def test_content_height(self) -> None:
        table = ASCIITable(
            headers=["A"],
            rows=[("1",), ("2",), ("3",)],
        )
        height = table.get_content_height(None, None, 80)
        # header + separator + 3 rows = 5
        assert height == 5


# ---------------------------------------------------------------------------
# SeverityBadge
# ---------------------------------------------------------------------------


class TestSeverityBadge:
    def test_critical(self) -> None:
        badge = SeverityBadge(severity="critical")
        result = badge.render()
        assert "CRITICAL" in str(result)

    def test_high(self) -> None:
        badge = SeverityBadge(severity="high")
        result = badge.render()
        assert "HIGH" in str(result)

    def test_medium(self) -> None:
        badge = SeverityBadge(severity="medium")
        result = badge.render()
        assert "MEDIUM" in str(result)

    def test_low(self) -> None:
        badge = SeverityBadge(severity="low")
        result = badge.render()
        assert "LOW" in str(result)

    def test_unknown_severity(self) -> None:
        badge = SeverityBadge(severity="unknown")
        result = badge.render()
        assert "UNKNOWN" in str(result)
        # Should use "dim" fallback style
        spans = result._spans
        dim_found = any("dim" in str(s.style) for s in spans)
        assert dim_found

    def test_case_insensitive(self) -> None:
        badge = SeverityBadge(severity="HIGH")
        assert badge.severity == "high"

    def test_bracket_formatting(self) -> None:
        badge = SeverityBadge(severity="low")
        rendered = str(badge.render())
        assert rendered.startswith("[")
        assert rendered.endswith("]")
