"""Tests for trace analysis modules (SessionAnalyzer, InefficiencyDetector, TokenAnalyzer)."""

from __future__ import annotations

import pytest

from attocode.tracing.types import TraceEvent, TraceEventKind, TraceSession
from attocode.tracing.analysis.session_analyzer import SessionAnalyzer
from attocode.tracing.analysis.inefficiency_detector import InefficiencyDetector
from attocode.tracing.analysis.token_analyzer import TokenAnalyzer
from attocode.tracing.analysis.views import (
    DetectedIssue,
    SessionSummaryView,
    TimelineEntry,
    TokenFlowPoint,
    TreeNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    kind: TraceEventKind,
    *,
    iteration: int | None = None,
    data: dict | None = None,
    timestamp: float = 1000.0,
    duration_ms: float | None = None,
) -> TraceEvent:
    return TraceEvent(
        kind=kind,
        timestamp=timestamp,
        session_id="test-session",
        iteration=iteration,
        data=data or {},
        duration_ms=duration_ms,
    )


def _session(events: list[TraceEvent], goal: str = "test") -> TraceSession:
    return TraceSession(
        session_id="test-session",
        goal=goal,
        model="claude-test",
        start_time=1000.0,
        end_time=1060.0,
        events=events,
    )


def _llm_response(
    iteration: int,
    *,
    tokens: int = 500,
    cost: float = 0.01,
    input_tokens: int = 200,
    output_tokens: int = 100,
    cache_read: int = 200,
    cache_write: int = 0,
    timestamp: float = 1001.0,
) -> TraceEvent:
    return _event(
        TraceEventKind.LLM_RESPONSE,
        iteration=iteration,
        timestamp=timestamp,
        data={
            "tokens": tokens,
            "cost": cost,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
        },
    )


# ---------------------------------------------------------------------------
# SessionAnalyzer
# ---------------------------------------------------------------------------


class TestSessionAnalyzerSummary:
    def test_basic_metrics(self) -> None:
        events = [
            _event(TraceEventKind.SESSION_START, timestamp=1000.0),
            _event(TraceEventKind.ITERATION_START, iteration=1, timestamp=1001.0),
            _llm_response(1, tokens=1000, cost=0.05, timestamp=1002.0),
            _event(TraceEventKind.TOOL_END, iteration=1, data={"tool": "bash"}, timestamp=1003.0),
            _event(TraceEventKind.ITERATION_END, iteration=1, timestamp=1004.0),
            _event(TraceEventKind.SESSION_END, timestamp=1060.0),
        ]
        session = _session(events)
        summary = SessionAnalyzer(session).summary()

        assert isinstance(summary, SessionSummaryView)
        assert summary.session_id == "test-session"
        assert summary.goal == "test"
        assert summary.model == "claude-test"
        assert summary.iterations == 1
        assert summary.total_tokens == 1000
        assert summary.total_cost == pytest.approx(0.05)
        assert summary.tool_calls == 1
        assert summary.llm_calls == 1
        assert summary.errors == 0

    def test_efficiency_score_range(self) -> None:
        events = [
            _event(TraceEventKind.ITERATION_START, iteration=1),
            _llm_response(1, cache_read=80, input_tokens=20),
            _event(TraceEventKind.TOOL_END, iteration=1, data={"tool": "bash"}),
        ]
        session = _session(events)
        summary = SessionAnalyzer(session).summary()

        assert 0.0 <= summary.efficiency_score <= 100.0

    def test_zero_iterations_no_crash(self) -> None:
        session = _session([])
        summary = SessionAnalyzer(session).summary()
        assert summary.iterations == 0
        assert summary.avg_tokens_per_iteration == 0.0
        assert summary.avg_cost_per_iteration == 0.0


class TestSessionAnalyzerTimeline:
    def test_event_ordering(self) -> None:
        events = [
            _event(TraceEventKind.TOOL_END, timestamp=1003.0, data={"tool": "bash"}),
            _event(TraceEventKind.LLM_RESPONSE, timestamp=1001.0, data={"tokens": 100}),
            _event(TraceEventKind.SESSION_START, timestamp=1000.0),
        ]
        session = _session(events)
        timeline = SessionAnalyzer(session).timeline()

        assert len(timeline) == 3
        # Should be sorted by timestamp
        assert timeline[0].timestamp == 1000.0
        assert timeline[1].timestamp == 1001.0
        assert timeline[2].timestamp == 1003.0

    def test_entry_structure(self) -> None:
        events = [
            _event(TraceEventKind.SESSION_START, timestamp=1000.0, data={"goal": "test"}),
        ]
        session = _session(events)
        timeline = SessionAnalyzer(session).timeline()

        assert len(timeline) == 1
        entry = timeline[0]
        assert isinstance(entry, TimelineEntry)
        assert entry.event_kind == "session_start"
        assert "Session started" in entry.summary


class TestSessionAnalyzerTokenFlow:
    def test_cumulative_cost(self) -> None:
        events = [
            _llm_response(1, cost=0.01, timestamp=1001.0),
            _llm_response(2, cost=0.02, timestamp=1002.0),
            _llm_response(3, cost=0.03, timestamp=1003.0),
        ]
        session = _session(events)
        flow = SessionAnalyzer(session).token_flow()

        assert len(flow) == 3
        assert flow[0].cumulative_cost == pytest.approx(0.01)
        assert flow[1].cumulative_cost == pytest.approx(0.03)
        assert flow[2].cumulative_cost == pytest.approx(0.06)

    def test_sorted_by_iteration(self) -> None:
        events = [
            _llm_response(3, timestamp=1003.0),
            _llm_response(1, timestamp=1001.0),
            _llm_response(2, timestamp=1002.0),
        ]
        session = _session(events)
        flow = SessionAnalyzer(session).token_flow()

        assert [p.iteration for p in flow] == [1, 2, 3]


class TestSessionAnalyzerTree:
    def test_groups_by_iteration(self) -> None:
        events = [
            _event(TraceEventKind.ITERATION_START, iteration=1, timestamp=1000.0),
            _event(TraceEventKind.LLM_RESPONSE, iteration=1, timestamp=1001.0, data={"tokens": 100}),
            _event(TraceEventKind.TOOL_END, iteration=1, timestamp=1002.0, data={"tool": "bash"}),
            _event(TraceEventKind.ITERATION_START, iteration=2, timestamp=1003.0),
            _event(TraceEventKind.LLM_RESPONSE, iteration=2, timestamp=1004.0, data={"tokens": 200}),
        ]
        session = _session(events)
        tree = SessionAnalyzer(session).tree()

        assert len(tree) == 2
        assert tree[0].kind == "iteration"
        assert tree[0].label == "Iteration 1"
        assert len(tree[0].children) == 3  # iter_start, llm, tool
        assert tree[1].label == "Iteration 2"


# ---------------------------------------------------------------------------
# InefficiencyDetector
# ---------------------------------------------------------------------------


class TestInefficiencyDetectorExcessiveIterations:
    def test_detects_spinning(self) -> None:
        # 20 iterations without any tool calls
        events = []
        for i in range(1, 21):
            events.append(_event(TraceEventKind.ITERATION_START, iteration=i))
            events.append(_event(TraceEventKind.LLM_RESPONSE, iteration=i, data={"tokens": 100}))
            events.append(_event(TraceEventKind.ITERATION_END, iteration=i))

        session = _session(events)
        detector = InefficiencyDetector(session)
        issues = detector._detect_excessive_iterations()

        assert len(issues) >= 1
        assert issues[0].category == "spinning"
        assert issues[0].severity == "high"

    def test_no_false_positive_with_tools(self) -> None:
        events = []
        for i in range(1, 21):
            events.append(_event(TraceEventKind.ITERATION_START, iteration=i))
            events.append(_event(TraceEventKind.TOOL_END, iteration=i, data={"tool": "bash"}))
            events.append(_event(TraceEventKind.ITERATION_END, iteration=i))

        session = _session(events)
        detector = InefficiencyDetector(session)
        issues = detector._detect_excessive_iterations()
        assert len(issues) == 0


class TestInefficiencyDetectorRepeatedToolCalls:
    def test_detects_doom_loop(self) -> None:
        events = []
        for _ in range(4):
            events.append(_event(
                TraceEventKind.TOOL_END,
                iteration=1,
                data={"tool": "read_file", "args": {"path": "/foo.py"}},
            ))

        session = _session(events)
        detector = InefficiencyDetector(session)
        issues = detector._detect_repeated_tool_calls()

        assert len(issues) >= 1
        assert issues[0].category == "doom_loop"
        assert "read_file" in issues[0].title

    def test_no_issue_under_threshold(self) -> None:
        events = [
            _event(TraceEventKind.TOOL_END, data={"tool": "bash", "args": {"cmd": "ls"}}),
            _event(TraceEventKind.TOOL_END, data={"tool": "bash", "args": {"cmd": "ls"}}),
        ]
        session = _session(events)
        detector = InefficiencyDetector(session)
        issues = detector._detect_repeated_tool_calls()
        assert len(issues) == 0


class TestInefficiencyDetectorTokenSpike:
    def test_detects_spike(self) -> None:
        events = [
            _llm_response(1, tokens=100, timestamp=1001.0),
            _llm_response(2, tokens=100, timestamp=1002.0),
            _llm_response(3, tokens=100, timestamp=1003.0),
            _llm_response(4, tokens=500, timestamp=1004.0),  # 5x average
        ]
        session = _session(events)
        detector = InefficiencyDetector(session)
        issues = detector._detect_token_spikes()

        assert len(issues) >= 1
        assert issues[0].category == "token_spike"

    def test_no_spike_with_uniform_data(self) -> None:
        events = [
            _llm_response(i, tokens=100, timestamp=1000.0 + i)
            for i in range(1, 6)
        ]
        session = _session(events)
        detector = InefficiencyDetector(session)
        issues = detector._detect_token_spikes()
        assert len(issues) == 0


class TestInefficiencyDetectorDetectAll:
    def test_returns_list(self) -> None:
        session = _session([])
        detector = InefficiencyDetector(session)
        issues = detector.detect_all()
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# TokenAnalyzer
# ---------------------------------------------------------------------------


class TestTokenAnalyzer:
    def test_cache_efficiency(self) -> None:
        events = [
            _llm_response(1, input_tokens=100, cache_read=400),
            _llm_response(2, input_tokens=200, cache_read=300),
        ]
        session = _session(events)
        analyzer = TokenAnalyzer(session)

        # total_input = 300, total_cache_read = 700, denom = 1000
        assert analyzer.cache_efficiency() == pytest.approx(0.7)

    def test_cache_efficiency_no_data(self) -> None:
        session = _session([])
        analyzer = TokenAnalyzer(session)
        assert analyzer.cache_efficiency() == 0.0

    def test_token_breakdown(self) -> None:
        events = [
            _llm_response(1, input_tokens=100, output_tokens=50, cache_read=200, cache_write=10),
            _llm_response(2, input_tokens=150, output_tokens=75, cache_read=300, cache_write=20),
        ]
        session = _session(events)
        analyzer = TokenAnalyzer(session)
        breakdown = analyzer.token_breakdown()

        assert breakdown["input"] == 250
        assert breakdown["output"] == 125
        assert breakdown["cache_read"] == 500
        assert breakdown["cache_write"] == 30

    def test_total_cost(self) -> None:
        events = [
            _llm_response(1, cost=0.05),
            _llm_response(2, cost=0.03),
        ]
        session = _session(events)
        analyzer = TokenAnalyzer(session)
        assert analyzer.total_cost() == pytest.approx(0.08)

    def test_cost_by_iteration(self) -> None:
        events = [
            _llm_response(1, cost=0.05, timestamp=1001.0),
            _llm_response(1, cost=0.02, timestamp=1002.0),
            _llm_response(2, cost=0.03, timestamp=1003.0),
        ]
        session = _session(events)
        analyzer = TokenAnalyzer(session)
        by_iter = analyzer.cost_by_iteration()

        assert by_iter[1] == pytest.approx(0.07)
        assert by_iter[2] == pytest.approx(0.03)

    def test_token_flow_points(self) -> None:
        events = [
            _llm_response(1, tokens=500, input_tokens=200, output_tokens=100,
                          cache_read=150, cache_write=50, cost=0.01),
        ]
        session = _session(events)
        analyzer = TokenAnalyzer(session)
        flow = analyzer.token_flow()

        assert len(flow) == 1
        pt = flow[0]
        assert pt.iteration == 1
        assert pt.input_tokens == 200
        assert pt.output_tokens == 100
        assert pt.cache_read_tokens == 150
        assert pt.cache_write_tokens == 50
        assert pt.total_tokens == 500
        assert pt.cumulative_cost == pytest.approx(0.01)
