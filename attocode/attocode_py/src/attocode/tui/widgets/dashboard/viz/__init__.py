"""Visualization primitives for the trace dashboard.

Lightweight Textual widgets that render common data-visualization patterns
(sparklines, bar charts, tables, trees, badges) using only Unicode characters
and Rich styling.  No external charting libraries required.
"""

from __future__ import annotations

from attocode.tui.widgets.dashboard.viz.ascii_table import ASCIITable
from attocode.tui.widgets.dashboard.viz.bar_chart import BarChart
from attocode.tui.widgets.dashboard.viz.percent_bar import PercentBar
from attocode.tui.widgets.dashboard.viz.severity_badge import SeverityBadge
from attocode.tui.widgets.dashboard.viz.sparkline import SparkLine
from attocode.tui.widgets.dashboard.viz.tree_renderer import TreeRenderer

__all__ = [
    "ASCIITable",
    "BarChart",
    "PercentBar",
    "SeverityBadge",
    "SparkLine",
    "TreeRenderer",
]
