"""Tests for LiveTraceAccumulator."""

from __future__ import annotations

import pytest

from attocode.tui.widgets.dashboard.live_dashboard import LiveTraceAccumulator


class TestRecordLLM:
    def test_updates_totals(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_llm(1000, 0.05)
        assert acc.total_tokens == 1000
        assert acc.total_cost == pytest.approx(0.05)
        assert len(acc.token_history) == 1
        assert acc.token_history[0] == 1000.0

    def test_accumulates_multiple_calls(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_llm(500, 0.01)
        acc.record_llm(300, 0.02)
        assert acc.total_tokens == 800
        assert acc.total_cost == pytest.approx(0.03)
        assert len(acc.token_history) == 2

    def test_rolling_window_capped_at_50(self) -> None:
        acc = LiveTraceAccumulator()
        for i in range(60):
            acc.record_llm(100 + i, 0.001)
        assert len(acc.token_history) == 50
        # Should contain the last 50 entries (110..159)
        assert acc.token_history[0] == 110.0
        assert acc.token_history[-1] == 159.0


class TestRecordTool:
    def test_counts_tool_frequency(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_tool("read_file")
        acc.record_tool("read_file")
        acc.record_tool("bash")
        assert acc.tool_counts["read_file"] == 2
        assert acc.tool_counts["bash"] == 1
        assert acc.tool_calls == 3

    def test_error_counting(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_tool("bash", error=False)
        acc.record_tool("bash", error=True)
        acc.record_tool("read_file", error=True)
        assert acc.errors == 2
        assert acc.tool_calls == 3


class TestCacheRate:
    def test_calculation(self) -> None:
        acc = LiveTraceAccumulator()
        # 80 cache_read out of 100 total (80+20)
        acc.record_llm(500, 0.01, cache_read=80, input_tokens=20)
        assert acc.avg_cache_rate == pytest.approx(0.8)

    def test_zero_denominator(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_llm(500, 0.01, cache_read=0, input_tokens=0)
        assert acc.avg_cache_rate == 0.0

    def test_rolling_window_capped_at_20(self) -> None:
        acc = LiveTraceAccumulator()
        for _ in range(25):
            acc.record_llm(100, 0.001, cache_read=50, input_tokens=50)
        assert len(acc.cache_rates) == 20

    def test_average_across_calls(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_llm(100, 0.01, cache_read=80, input_tokens=20)  # 0.8
        acc.record_llm(100, 0.01, cache_read=20, input_tokens=80)  # 0.2
        assert acc.avg_cache_rate == pytest.approx(0.5)


class TestTopTools:
    def test_sorted_by_frequency(self) -> None:
        acc = LiveTraceAccumulator()
        for _ in range(5):
            acc.record_tool("bash")
        for _ in range(3):
            acc.record_tool("read_file")
        acc.record_tool("glob")
        top = acc.top_tools
        assert top[0] == ("bash", 5)
        assert top[1] == ("read_file", 3)
        assert top[2] == ("glob", 1)

    def test_limited_to_8(self) -> None:
        acc = LiveTraceAccumulator()
        for i in range(12):
            acc.record_tool(f"tool_{i}")
        assert len(acc.top_tools) == 8


class TestErrorRate:
    def test_no_calls(self) -> None:
        acc = LiveTraceAccumulator()
        assert acc.error_rate == 0.0

    def test_with_errors(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_tool("bash", error=False)
        acc.record_tool("bash", error=True)
        assert acc.error_rate == pytest.approx(0.5)


class TestEmptyAccumulatorDefaults:
    def test_zero_state(self) -> None:
        acc = LiveTraceAccumulator()
        assert acc.total_tokens == 0
        assert acc.total_cost == 0.0
        assert acc.iteration == 0
        assert acc.errors == 0
        assert acc.tool_calls == 0
        assert acc.budget_warnings == 0
        assert acc.last_budget_pct == 0.0
        assert acc.token_history == []
        assert acc.cache_rates == []
        assert acc.tool_counts == {}
        assert acc.avg_cache_rate == 0.0
        assert acc.top_tools == []
        assert acc.error_rate == 0.0


class TestRecordIteration:
    def test_updates_iteration(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_iteration(5)
        assert acc.iteration == 5
        acc.record_iteration(10)
        assert acc.iteration == 10
