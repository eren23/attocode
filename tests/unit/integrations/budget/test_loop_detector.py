"""Tests for loop detector."""

from __future__ import annotations

from attocode.integrations.budget.loop_detector import LoopDetection, LoopDetector


class TestLoopDetection:
    def test_no_loop(self) -> None:
        d = LoopDetection.no_loop()
        assert not d.is_loop

    def test_detected(self) -> None:
        d = LoopDetection.detected("read_file", 3)
        assert d.is_loop
        assert d.tool_name == "read_file"
        assert d.count == 3
        assert "read_file" in d.message


class TestLoopDetector:
    def test_no_loop_with_variety(self) -> None:
        ld = LoopDetector(threshold=3)
        assert not ld.record("read_file", {"path": "a.py"}).is_loop
        assert not ld.record("write_file", {"path": "b.py"}).is_loop
        assert not ld.record("bash", {"command": "ls"}).is_loop

    def test_detects_loop(self) -> None:
        ld = LoopDetector(threshold=3)
        args = {"path": "/same/file.py"}
        ld.record("read_file", args)
        ld.record("read_file", args)
        result = ld.record("read_file", args)
        assert result.is_loop
        assert result.count == 3

    def test_different_args_not_loop(self) -> None:
        ld = LoopDetector(threshold=3)
        ld.record("read_file", {"path": "a.py"})
        ld.record("read_file", {"path": "b.py"})
        result = ld.record("read_file", {"path": "c.py"})
        assert not result.is_loop

    def test_window_forgets_old(self) -> None:
        ld = LoopDetector(threshold=3)
        ld._window_size = 5
        args = {"path": "x.py"}
        ld.record("read_file", args)
        ld.record("read_file", args)
        # Fill window with other calls
        for i in range(5):
            ld.record("other", {"i": i})
        # Old calls should be evicted
        result = ld.record("read_file", args)
        assert not result.is_loop

    def test_reset(self) -> None:
        ld = LoopDetector(threshold=2)
        ld.record("read_file", {"path": "a"})
        ld.record("read_file", {"path": "a"})
        ld.reset()
        result = ld.record("read_file", {"path": "a"})
        assert not result.is_loop

    def test_total_calls(self) -> None:
        ld = LoopDetector()
        ld.record("a", {})
        ld.record("b", {})
        ld.record("c", {})
        assert ld.total_calls == 3

    def test_most_common(self) -> None:
        ld = LoopDetector()
        ld.record("a", {"x": 1})
        ld.record("a", {"x": 1})
        ld.record("b", {"y": 2})
        common = ld.get_most_common(1)
        assert len(common) == 1
        assert common[0][1] == 2
