"""Tests for TimelineGenerator."""

from __future__ import annotations

from attoswarm.coordinator.timeline import TimelineGenerator
from attoswarm.coordinator.trace_query import TraceQueryEngine


class TestTimelineGenerator:
    def _build_engine(self) -> TraceQueryEngine:
        engine = TraceQueryEngine()
        engine.load_from_memory(
            events=[
                {"timestamp": 100.0, "event_type": "spawn", "task_id": "t1", "message": "s"},
                {"timestamp": 112.0, "event_type": "complete", "task_id": "t1", "message": "d"},
                {"timestamp": 101.0, "event_type": "spawn", "task_id": "t2", "message": "s"},
                {"timestamp": 108.0, "event_type": "fail", "task_id": "t2", "message": "f"},
                {"timestamp": 113.0, "event_type": "spawn", "task_id": "t3", "message": "s"},
                {"timestamp": 119.0, "event_type": "complete", "task_id": "t3", "message": "d"},
            ],
            task_data={
                "t1": {"task_id": "t1", "title": "Task One"},
                "t2": {"task_id": "t2", "title": "Task Two"},
                "t3": {"task_id": "t3", "title": "Task Three"},
            },
        )
        return engine

    def test_gantt_data(self) -> None:
        gen = TimelineGenerator(self._build_engine())
        entries = gen.generate_gantt_data()
        assert len(entries) == 3
        assert entries[0].task_id == "t1"
        assert entries[0].status == "done"
        assert entries[1].status == "failed"

    def test_text_timeline(self) -> None:
        gen = TimelineGenerator(self._build_engine())
        text = gen.generate_text_timeline()
        assert "t1" in text
        assert "t2" in text
        assert "done" in text
        assert "failed" in text

    def test_critical_path_highlight(self) -> None:
        gen = TimelineGenerator(self._build_engine())
        text = gen.generate_critical_path_highlight(["t1", "t3"])
        assert ">>" in text
        assert "Critical path:" in text

    def test_empty_timeline(self) -> None:
        engine = TraceQueryEngine()
        engine.load_from_memory(events=[])
        gen = TimelineGenerator(engine)
        text = gen.generate_text_timeline()
        assert "no timeline data" in text
