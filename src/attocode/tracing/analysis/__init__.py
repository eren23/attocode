"""Trace analysis library.

Provides structured analysis of JSONL trace files produced by the agent's
:class:`~attocode.tracing.collector.TraceCollector`.

Analysers
~~~~~~~~~
- :class:`SessionAnalyzer` -- summary metrics, timeline, tree, and token flow.
- :class:`InefficiencyDetector` -- detects 11 categories of performance issues.
- :class:`TokenAnalyzer` -- detailed token usage breakdowns and cost tracking.

View dataclasses
~~~~~~~~~~~~~~~~
- :class:`SessionSummaryView` -- aggregate session metrics.
- :class:`TimelineEntry` -- chronological event row.
- :class:`TreeNode` -- hierarchical event node.
- :class:`TokenFlowPoint` -- per-iteration token snapshot.
- :class:`DetectedIssue` -- a single detected inefficiency.
"""

from __future__ import annotations

from attocode.tracing.analysis.inefficiency_detector import InefficiencyDetector
from attocode.tracing.analysis.session_analyzer import SessionAnalyzer
from attocode.tracing.analysis.token_analyzer import TokenAnalyzer
from attocode.tracing.analysis.views import (
    DetectedIssue,
    SessionSummaryView,
    TimelineEntry,
    TokenFlowPoint,
    TreeNode,
)

__all__ = [
    # Analysers
    "SessionAnalyzer",
    "InefficiencyDetector",
    "TokenAnalyzer",
    # Views
    "SessionSummaryView",
    "TimelineEntry",
    "TreeNode",
    "TokenFlowPoint",
    "DetectedIssue",
]
