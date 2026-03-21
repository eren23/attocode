"""Tests for TraceQueryEngine."""

from __future__ import annotations

from attoswarm.coordinator.trace_query import TraceQueryEngine


class TestTraceQueryEngine:
    def _build_engine(self) -> TraceQueryEngine:
        engine = TraceQueryEngine()
        engine.load_from_memory(
            events=[
                {"timestamp": 1.0, "event_type": "spawn", "task_id": "t1", "message": "Spawning t1"},
                {"timestamp": 2.0, "event_type": "complete", "task_id": "t1",
                 "message": "t1 done", "data": {"cost_usd": 0.5}},
                {"timestamp": 1.5, "event_type": "spawn", "task_id": "t2", "message": "Spawning t2"},
                {"timestamp": 3.0, "event_type": "fail", "task_id": "t2",
                 "message": "t2 failed: rate limit", "data": {"cost_usd": 0.3}},
                {"timestamp": 2.5, "event_type": "budget", "task_id": "",
                 "message": "Budget 80%", "data": {}},
            ],
            task_data={
                "t1": {"task_id": "t1", "cost_usd": 0.5, "deps": [], "files_modified": ["a.py"]},
                "t2": {"task_id": "t2", "cost_usd": 0.3, "deps": ["t1"], "files_modified": []},
            },
        )
        return engine

    def test_events_for_task(self) -> None:
        engine = self._build_engine()
        events = engine.events_for_task("t1")
        assert len(events) == 2

    def test_events_by_type(self) -> None:
        engine = self._build_engine()
        spawns = engine.events_by_type("spawn")
        assert len(spawns) == 2

    def test_cost_by_task(self) -> None:
        engine = self._build_engine()
        costs = engine.cost_by_task()
        assert costs["t1"] == 0.5
        assert costs["t2"] == 0.3

    def test_failure_summary(self) -> None:
        engine = self._build_engine()
        failures = engine.failure_summary()
        assert len(failures) == 1
        assert failures[0]["task_id"] == "t2"

    def test_budget_timeline(self) -> None:
        engine = self._build_engine()
        timeline = engine.budget_timeline()
        assert len(timeline) == 1

    def test_search_events(self) -> None:
        engine = self._build_engine()
        results = engine.search_events("rate limit")
        assert len(results) == 1
        assert results[0].task_id == "t2"

    def test_search_events_with_type_filter(self) -> None:
        engine = self._build_engine()
        results = engine.search_events("Spawning", event_types=["spawn"])
        assert len(results) == 2

    def test_timing_waterfall(self) -> None:
        engine = self._build_engine()
        waterfall = engine.timing_waterfall()
        assert len(waterfall) >= 3  # 2 spawns + 1 complete + 1 fail
