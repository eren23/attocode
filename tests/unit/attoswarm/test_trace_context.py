"""Tests for distributed tracing context."""

from __future__ import annotations

import asyncio

import pytest

from attoswarm.coordinator.trace_context import (
    SpanContext,
    TraceContext,
    current_span,
    start_span,
    start_span_sync,
    traced,
)


class TestSpanContext:
    def test_span_id_generated(self) -> None:
        span = SpanContext(trace_id="test")
        assert len(span.span_id) == 12

    def test_duration_while_running(self) -> None:
        span = SpanContext(trace_id="test")
        assert span.duration_s >= 0

    def test_finish_sets_end_time(self) -> None:
        span = SpanContext(trace_id="test")
        assert span.end_time == 0.0
        span.finish()
        assert span.end_time > 0

    def test_set_attribute(self) -> None:
        span = SpanContext(trace_id="test")
        span.set_attribute("key", "value")
        assert span.attributes["key"] == "value"

    def test_to_dict(self) -> None:
        span = SpanContext(trace_id="t1", operation="op1")
        span.finish()
        d = span.to_dict()
        assert d["trace_id"] == "t1"
        assert d["operation"] == "op1"
        assert "duration_s" in d


class TestStartSpan:
    @pytest.mark.asyncio
    async def test_span_context_propagation(self) -> None:
        async with start_span("outer", trace_id="run1") as outer:
            assert current_span() is outer
            assert outer.trace_id == "run1"
            async with start_span("inner") as inner:
                assert current_span() is inner
                assert inner.parent_span_id == outer.span_id
                assert inner.trace_id == "run1"
            assert current_span() is outer
        assert current_span() is None

    @pytest.mark.asyncio
    async def test_span_finishes_on_exit(self) -> None:
        async with start_span("test", trace_id="r") as span:
            pass
        assert span.end_time > 0

    def test_sync_span(self) -> None:
        with start_span_sync("sync_op", trace_id="s1") as span:
            assert current_span() is span
            assert span.operation == "sync_op"
        assert span.end_time > 0


class TestTraced:
    @pytest.mark.asyncio
    async def test_traced_decorator(self) -> None:
        @traced("my_op")
        async def my_func(x: int) -> int:
            span = current_span()
            assert span is not None
            assert span.operation == "my_op"
            return x * 2

        result = await my_func(5)
        assert result == 10


class TestTraceContext:
    @pytest.mark.asyncio
    async def test_completed_spans_collected(self) -> None:
        ctx = TraceContext(trace_id="run1")
        async with start_span("op1", trace_id="run1"):
            async with start_span("op2"):
                pass
        spans = ctx.completed_spans
        assert len(spans) == 2
        assert spans[0].operation == "op2"  # inner completes first
        assert spans[1].operation == "op1"
        ctx.cleanup()

    @pytest.mark.asyncio
    async def test_ignores_other_traces(self) -> None:
        ctx = TraceContext(trace_id="run1")
        async with start_span("other", trace_id="run2"):
            pass
        assert len(ctx.completed_spans) == 0
        ctx.cleanup()
