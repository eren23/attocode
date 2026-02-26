"""Tests for the visual debug recording system.

Covers:
- RecordingSessionManager lifecycle (start → handle events → stop)
- Frame capture with debouncing
- Exploration graph tracking from tool events
- Gallery export (assembly.py)
- Edge cases: max_frames limit, non-recording events ignored, graceful fallback
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from attocode.integrations.recording.assembly import assemble_gallery
from attocode.integrations.recording.exploration_tracker import (
    ExplorationGraph,
    tool_to_action,
)
from attocode.integrations.recording.recorder import (
    RecordingConfig,
    RecordingFrame,
    RecordingSession,
    RecordingSessionManager,
)


# ---------------------------------------------------------------------------
# Mock event helper
# ---------------------------------------------------------------------------

@dataclass
class MockEvent:
    """Minimal event object matching the attrs that RecordingSessionManager reads."""

    type: str = ""
    agent_id: str = "main"
    tool: str = ""
    args: dict[str, Any] | None = None
    result: str | None = None
    error: str | None = None
    tokens: int | None = None
    cost: float | None = None
    iteration: int = 0
    duration_ms: float | None = None


def _tool_event(
    tool: str,
    event_type: str = "tool.complete",
    agent_id: str = "main",
    file_path: str = "",
    iteration: int = 1,
) -> MockEvent:
    args: dict[str, Any] = {}
    if file_path:
        args["file_path"] = file_path
    return MockEvent(
        type=event_type,
        agent_id=agent_id,
        tool=tool,
        args=args,
        iteration=iteration,
    )


# ---------------------------------------------------------------------------
# RecordingSessionManager lifecycle
# ---------------------------------------------------------------------------


class TestRecordingSessionManagerLifecycle:
    def test_start_creates_directory(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "recordings"))
        mgr = RecordingSessionManager(cfg)
        session_dir = mgr.start("test-001")

        assert session_dir.exists()
        assert (session_dir / "frames").exists()
        assert mgr.is_recording
        assert mgr.frame_count == 0

    def test_stop_returns_session(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("s1")

        # Feed a few events
        mgr.handle_event(_tool_event("read_file", file_path="src/main.py"))
        mgr.handle_event(_tool_event("edit_file", file_path="src/main.py"))

        session = mgr.stop()
        assert isinstance(session, RecordingSession)
        assert session.session_id == "s1"
        assert session.total_frames == 2
        assert not mgr.is_recording

    def test_stop_writes_metadata_files(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        session_dir = mgr.start("s2")

        mgr.handle_event(_tool_event("read_file", file_path="f.py"))
        mgr.stop()

        assert (session_dir / "recording.json").exists()
        assert (session_dir / "exploration_graph.json").exists()
        assert (session_dir / "exploration.mermaid").exists()

        meta = json.loads((session_dir / "recording.json").read_text())
        assert meta["session_id"] == "s2"
        assert meta["total_frames"] == 1

    def test_events_ignored_when_not_recording(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)

        # Not started yet
        mgr.handle_event(_tool_event("read_file", file_path="f.py"))
        assert mgr.frame_count == 0

        # Start then stop
        mgr.start("s3")
        mgr.stop()

        # After stop
        mgr.handle_event(_tool_event("read_file", file_path="f.py"))
        assert mgr.frame_count == 0

    def test_agents_tracked(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("s4")

        mgr.handle_event(_tool_event("read_file", agent_id="agent-1", file_path="a.py"))
        mgr.handle_event(_tool_event("read_file", agent_id="agent-2", file_path="b.py"))
        mgr.handle_event(_tool_event("read_file", agent_id="agent-1", file_path="c.py"))

        session = mgr.stop()
        assert sorted(session.agents) == ["agent-1", "agent-2"]


# ---------------------------------------------------------------------------
# Frame capture and debouncing
# ---------------------------------------------------------------------------


class TestFrameCapture:
    def test_debounce_suppresses_rapid_events(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            debounce_ms=10_000,  # Very long debounce
        )
        mgr = RecordingSessionManager(cfg)
        mgr.start("debounce-test")

        # First event goes through
        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        assert mgr.frame_count == 1

        # Second event within debounce window is suppressed
        mgr.handle_event(_tool_event("read_file", file_path="b.py"))
        assert mgr.frame_count == 1

        mgr.stop()

    def test_always_capture_events_bypass_debounce(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            debounce_ms=10_000,
        )
        mgr = RecordingSessionManager(cfg)
        mgr.start("always-capture")

        # First event captured normally
        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        assert mgr.frame_count == 1

        # tool.error is in _ALWAYS_CAPTURE — should bypass debounce
        mgr.handle_event(MockEvent(type="tool.error", error="some error"))
        assert mgr.frame_count == 2

        # subagent.spawn is also in _ALWAYS_CAPTURE
        mgr.handle_event(MockEvent(type="subagent.spawn", agent_id="sub-1"))
        assert mgr.frame_count == 3

        mgr.stop()

    def test_max_frames_limit(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            max_frames=3,
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        mgr.start("max-frames")

        for i in range(10):
            mgr.handle_event(_tool_event("read_file", file_path=f"f{i}.py", iteration=i))

        assert mgr.frame_count == 3

        session = mgr.stop()
        assert session.total_frames == 3
        assert len(session.frames) == 3

    def test_frame_sidecar_written(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        session_dir = mgr.start("sidecar-test")

        mgr.handle_event(_tool_event("read_file", file_path="main.py"))

        # Check sidecar file exists
        sidecar_files = list((session_dir / "frames").glob("*.json"))
        assert len(sidecar_files) >= 1

        data = json.loads(sidecar_files[0].read_text())
        assert data["frame_id"] == "frame-0001"
        assert data["event_kind"] == "tool.complete"

        mgr.stop()

    def test_ascii_fallback_screenshot(self, tmp_path: Path) -> None:
        """When no TUI callback, screenshots fall back to ASCII text files."""
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            capture_screenshots=True,
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        session_dir = mgr.start("ascii-fallback")

        # Add a visit so there's content for ASCII DAG
        mgr._exploration.add_visit(file_path="src/main.py", action="read")
        mgr.handle_event(_tool_event("read_file", file_path="src/main.py"))

        # Should have created a .txt fallback
        txt_files = list((session_dir / "frames").glob("*.txt"))
        assert len(txt_files) >= 1

        content = txt_files[0].read_text()
        assert "src/main.py" in content

        mgr.stop()

    def test_capture_callback_used(self, tmp_path: Path) -> None:
        captured_paths: list[str] = []

        def mock_capture(path: str) -> None:
            captured_paths.append(path)
            # Write a fake SVG so the path exists
            Path(path).write_text("<svg></svg>")

        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            capture_screenshots=True,
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg, capture_callback=mock_capture)
        mgr.start("callback-test")

        mgr.handle_event(_tool_event("read_file", file_path="a.py"))

        assert len(captured_paths) == 1
        assert captured_paths[0].endswith(".svg")

        mgr.stop()


# ---------------------------------------------------------------------------
# Exploration graph tracking
# ---------------------------------------------------------------------------


class TestExplorationTracking:
    def test_file_visits_tracked(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("explore-test")

        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        mgr.handle_event(_tool_event("grep", file_path="b.py"))
        mgr.handle_event(_tool_event("edit_file", file_path="a.py"))

        graph = mgr.exploration_graph
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2  # Sequential edges

        # Check actions mapped correctly
        actions = [n.action for n in graph.nodes.values()]
        assert "read" in actions
        assert "search" in actions
        assert "edit" in actions

        mgr.stop()

    def test_edit_marked_as_key_finding(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("key-finding-test")

        mgr.handle_event(_tool_event("edit_file", file_path="module.py"))

        graph = mgr.exploration_graph
        nodes = list(graph.nodes.values())
        assert len(nodes) == 1
        assert nodes[0].outcome == "key_finding"

        mgr.stop()

    def test_non_file_tools_not_tracked(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("no-track-test")

        # "spawn_agent" is not in _FILE_ACCESS_TOOLS
        mgr.handle_event(MockEvent(
            type="tool.complete",
            tool="spawn_agent",
            args={"task": "do stuff"},
        ))

        assert len(mgr.exploration_graph.nodes) == 0
        mgr.stop()

    def test_multi_agent_paths(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("multi-agent")

        mgr.handle_event(_tool_event("read_file", agent_id="a1", file_path="x.py"))
        mgr.handle_event(_tool_event("read_file", agent_id="a2", file_path="y.py"))
        mgr.handle_event(_tool_event("read_file", agent_id="a1", file_path="z.py"))

        graph = mgr.exploration_graph
        assert len(graph.agent_paths) == 2
        assert len(graph.agent_paths["a1"]) == 2
        assert len(graph.agent_paths["a2"]) == 1

        mgr.stop()

    def test_exploration_snapshot_in_frame(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("snapshot-in-frame")

        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        mgr.handle_event(_tool_event("read_file", file_path="b.py"))

        session = mgr.stop()
        # Each frame should have an exploration snapshot
        assert session.frames[0].exploration_snapshot is not None
        assert session.frames[0].exploration_snapshot.depth >= 1


# ---------------------------------------------------------------------------
# tool_to_action
# ---------------------------------------------------------------------------


class TestToolToAction:
    def test_known_tools(self) -> None:
        assert tool_to_action("read_file") == "read"
        assert tool_to_action("edit_file") == "edit"
        assert tool_to_action("write_file") == "edit"
        assert tool_to_action("grep") == "search"
        assert tool_to_action("glob") == "search"
        assert tool_to_action("get_repo_map") == "overview"
        assert tool_to_action("bash") == "search"

    def test_unknown_tool_defaults_to_read(self) -> None:
        assert tool_to_action("some_custom_tool") == "read"


# ---------------------------------------------------------------------------
# ExplorationGraph serialization
# ---------------------------------------------------------------------------


class TestExplorationGraphSerialization:
    def test_roundtrip(self) -> None:
        graph = ExplorationGraph()
        graph.add_visit("a.py", agent_id="main", action="read")
        graph.add_visit("b.py", agent_id="main", action="edit")
        graph.mark_outcome(list(graph.nodes.keys())[1], "key_finding")

        data = graph.to_dict()
        restored = ExplorationGraph.from_dict(data)

        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1
        assert restored.agent_paths["main"] == graph.agent_paths["main"]

    def test_mermaid_export(self) -> None:
        graph = ExplorationGraph()
        graph.add_visit("src/main.py", action="read")
        graph.add_visit("src/utils.py", action="edit")

        mermaid = graph.to_mermaid()
        assert "graph LR" in mermaid
        assert "main.py" in mermaid

    def test_ascii_dag_export(self) -> None:
        graph = ExplorationGraph()
        graph.add_visit("a.py", action="read")
        graph.add_visit("b.py", action="edit")
        graph.mark_outcome(list(graph.nodes.keys())[1], "key_finding")

        ascii_output = graph.to_ascii_dag()
        assert "a.py" in ascii_output
        assert "b.py" in ascii_output
        assert "[KEY]" in ascii_output

    def test_empty_graph(self) -> None:
        graph = ExplorationGraph()
        assert graph.to_ascii_dag() == "(no exploration recorded)"
        assert "graph LR" in graph.to_mermaid()


# ---------------------------------------------------------------------------
# Gallery export (assembly.py)
# ---------------------------------------------------------------------------


class TestGalleryExport:
    def test_assemble_gallery_produces_html(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "session-test"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        graph = ExplorationGraph()
        graph.add_visit("main.py", action="read")
        graph.add_visit("utils.py", action="edit")

        frames = [
            RecordingFrame(
                frame_id="frame-0001",
                timestamp=time.time(),
                frame_number=1,
                event_kind="tool.complete",
                agent_id="main",
                iteration=1,
                metadata={"tool": "read_file"},
                annotations=["Completed: read_file"],
            ),
            RecordingFrame(
                frame_id="frame-0002",
                timestamp=time.time() + 1,
                frame_number=2,
                event_kind="tool.complete",
                agent_id="main",
                iteration=2,
                metadata={"tool": "edit_file"},
                annotations=["Completed: edit_file"],
            ),
        ]

        path = assemble_gallery(
            session_dir=session_dir,
            frames=frames,
            exploration=graph,
            session_id="test-gallery",
            start_time=time.time() - 10,
        )

        assert path.exists()
        assert path.name == "gallery.html"
        content = path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "test-gallery" in content
        assert "frame-0001" in content
        assert "frame-0002" in content
        assert "graph LR" in content  # Mermaid
        assert "read_file" in content

    def test_gallery_with_no_frames(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "empty-session"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        graph = ExplorationGraph()

        path = assemble_gallery(
            session_dir=session_dir,
            frames=[],
            exploration=graph,
            session_id="empty-test",
            start_time=time.time(),
        )

        assert path.exists()
        content = path.read_text()
        assert "No frames captured" in content

    def test_gallery_with_svg_screenshot(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "svg-session"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        # Create a fake SVG screenshot
        svg_path = session_dir / "frames" / "frame-0001-tool_complete.svg"
        svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Hello</text></svg>')

        graph = ExplorationGraph()

        frames = [
            RecordingFrame(
                frame_id="frame-0001",
                timestamp=time.time(),
                frame_number=1,
                event_kind="tool.complete",
                agent_id="main",
                iteration=1,
                screenshot_path=str(svg_path),
                annotations=["Test frame"],
            ),
        ]

        path = assemble_gallery(
            session_dir=session_dir,
            frames=frames,
            exploration=graph,
            session_id="svg-test",
            start_time=time.time(),
        )

        content = path.read_text()
        # Should contain base64-encoded SVG
        assert "data:image/svg+xml;base64," in content

    def test_gallery_with_ascii_fallback(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "ascii-session"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        txt_path = session_dir / "frames" / "frame-0001-tool_complete.txt"
        txt_path.write_text("    src/main.py (read)\n    |\n  └─> src/utils.py (edit)")

        graph = ExplorationGraph()

        frames = [
            RecordingFrame(
                frame_id="frame-0001",
                timestamp=time.time(),
                frame_number=1,
                event_kind="tool.complete",
                agent_id="main",
                iteration=1,
                screenshot_path=str(txt_path),
                annotations=["ASCII fallback"],
            ),
        ]

        path = assemble_gallery(
            session_dir=session_dir,
            frames=frames,
            exploration=graph,
            session_id="ascii-test",
            start_time=time.time(),
        )

        content = path.read_text()
        assert "frame-ascii" in content
        assert "src/main.py" in content

    def test_export_via_manager(self, tmp_path: Path) -> None:
        """Full end-to-end: RecordingSessionManager → export('html') → gallery.html."""
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        session_dir = mgr.start("e2e-test")

        mgr.handle_event(_tool_event("read_file", file_path="src/app.py"))
        mgr.handle_event(_tool_event("edit_file", file_path="src/app.py"))
        mgr.handle_event(_tool_event("grep", file_path="src/utils.py"))

        mgr.stop()

        gallery_path = mgr.export("html")
        assert gallery_path.exists()
        assert gallery_path.name == "gallery.html"

        content = gallery_path.read_text()
        assert "e2e-test" in content
        assert "frame-0001" in content

    def test_export_mermaid_format(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        mgr.start("mermaid-test")

        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        mgr.stop()

        mermaid_path = mgr.export("mermaid")
        assert mermaid_path.exists()
        content = mermaid_path.read_text()
        assert "graph LR" in content


# ---------------------------------------------------------------------------
# Granularity settings
# ---------------------------------------------------------------------------


class TestCaptureGranularity:
    def test_iteration_granularity(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            capture_granularity="iteration",
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        mgr.start("gran-iteration")

        # Iteration events captured
        mgr.handle_event(MockEvent(type="iteration", iteration=1))
        assert mgr.frame_count == 1

        # tool.complete NOT captured at iteration granularity
        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        assert mgr.frame_count == 1

        # But always-capture events still get through
        mgr.handle_event(MockEvent(type="subagent.spawn", agent_id="sub"))
        assert mgr.frame_count == 2

        mgr.stop()

    def test_event_granularity(self, tmp_path: Path) -> None:
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            capture_granularity="event",
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        mgr.start("gran-event")

        # Both tool and iteration events captured
        mgr.handle_event(MockEvent(type="iteration", iteration=1))
        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        mgr.handle_event(MockEvent(type="response"))

        assert mgr.frame_count == 3
        mgr.stop()


# ---------------------------------------------------------------------------
# Real AgentEvent integration tests
# ---------------------------------------------------------------------------


class TestRealAgentEvents:
    """Verify the recorder works with actual AgentEvent objects (not mocks)."""

    def test_recorder_with_real_agent_events(self, tmp_path: Path) -> None:
        from attocode.types.events import AgentEvent, EventType

        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("real-events")

        mgr.handle_event(AgentEvent(
            type=EventType.TOOL_COMPLETE,
            tool="read_file",
            args={"file_path": "src/main.py"},
            iteration=1,
            agent_id="main",
        ))
        mgr.handle_event(AgentEvent(
            type=EventType.TOOL_ERROR,
            tool="edit_file",
            error="Permission denied",
            args={"file_path": "src/main.py"},
            iteration=2,
        ))

        session = mgr.stop()
        assert session.total_frames == 2
        # Verify exploration tracked the file visit
        assert len(mgr.exploration_graph.nodes) >= 1

    def test_export_without_session_raises(self) -> None:
        mgr = RecordingSessionManager()
        with pytest.raises(RuntimeError, match="No recording session"):
            mgr.export("html")


# ---------------------------------------------------------------------------
# XSS safety tests
# ---------------------------------------------------------------------------


class TestGalleryXSSSafety:
    def test_gallery_escapes_dangerous_content(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "xss-session"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        graph = ExplorationGraph()

        frames = [
            RecordingFrame(
                frame_id="frame-0001",
                timestamp=time.time(),
                frame_number=1,
                event_kind="tool.complete",
                agent_id='<script>alert("xss")</script>',
                iteration=1,
                metadata={"tool": '<img onerror=alert(1) src=x>'},
                annotations=["<b>bold</b>"],
            ),
        ]

        path = assemble_gallery(
            session_dir=session_dir,
            frames=frames,
            exploration=graph,
            session_id="xss-test",
            start_time=time.time(),
        )

        content = path.read_text()
        # The agent_id XSS payload must be escaped in the rendered output —
        # no raw <script> or <b> tags from user-supplied data
        assert '<script>alert("xss")</script>' not in content
        assert "<img onerror=" not in content
        assert "<b>bold</b>" not in content
        # Escaped versions should be present
        assert "&lt;script&gt;" in content
        assert "&lt;b&gt;" in content

    def test_frame_id_xss_in_onclick(self, tmp_path: Path) -> None:
        """Frame IDs with quotes/JS should be escaped in onclick handlers."""
        session_dir = tmp_path / "onclick-xss"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        graph = ExplorationGraph()

        frames = [
            RecordingFrame(
                frame_id="frame');alert('xss",
                timestamp=time.time(),
                frame_number=1,
                event_kind="tool.complete",
                agent_id="main",
                iteration=1,
            ),
        ]

        path = assemble_gallery(
            session_dir=session_dir,
            frames=frames,
            exploration=graph,
            session_id="onclick-test",
            start_time=time.time(),
        )

        content = path.read_text()
        # The raw malicious frame_id must NOT appear unescaped
        assert "frame');alert('xss" not in content


# ---------------------------------------------------------------------------
# End-to-end smoke test
# ---------------------------------------------------------------------------


class TestRecordingE2ESmoke:
    def test_recording_e2e_smoke(self, tmp_path: Path) -> None:
        """Full lifecycle: config -> manager -> events -> stop -> export -> gallery.html."""
        from attocode.types.events import AgentEvent, EventType

        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)
        mgr.start("smoke-test")

        # Simulate a realistic event sequence
        for i, (tool, path_str) in enumerate([
            ("read_file", "src/main.py"),
            ("grep", "src/utils.py"),
            ("read_file", "src/utils.py"),
            ("edit_file", "src/utils.py"),
            ("read_file", "tests/test_utils.py"),
        ]):
            mgr.handle_event(AgentEvent(
                type=EventType.TOOL_COMPLETE,
                tool=tool,
                args={"file_path": path_str},
                iteration=i + 1,
            ))

        session = mgr.stop()
        gallery = mgr.export("html")

        assert gallery.exists()
        content = gallery.read_text()
        assert "smoke-test" in content
        assert session.total_frames == 5
        assert len(session.exploration_graph.nodes) == 5
        # Verify mermaid graph is in the HTML
        assert "graph LR" in content


# ---------------------------------------------------------------------------
# Audit fix tests (post-implementation)
# ---------------------------------------------------------------------------


class TestCaptureScreenshotsDisabled:
    def test_no_screenshot_files_when_disabled(self, tmp_path: Path) -> None:
        """capture_screenshots=False should produce no screenshot files but still capture frames."""
        cfg = RecordingConfig(
            output_dir=str(tmp_path / "rec"),
            capture_screenshots=False,
            debounce_ms=0,
        )
        mgr = RecordingSessionManager(cfg)
        session_dir = mgr.start("no-screenshots")

        mgr.handle_event(_tool_event("read_file", file_path="a.py"))
        mgr.handle_event(_tool_event("edit_file", file_path="b.py"))

        session = mgr.stop()
        assert session.total_frames == 2

        # No screenshot files (svg or txt) should exist
        svg_files = list((session_dir / "frames").glob("*.svg"))
        txt_files = list((session_dir / "frames").glob("*.txt"))
        assert len(svg_files) == 0
        assert len(txt_files) == 0

        # All frames should have screenshot_path=None
        for frame in session.frames:
            assert frame.screenshot_path is None


class TestDoubleStart:
    def test_start_called_twice_stops_previous(self, tmp_path: Path) -> None:
        """Calling start() twice should auto-stop the first session."""
        cfg = RecordingConfig(output_dir=str(tmp_path / "rec"), debounce_ms=0)
        mgr = RecordingSessionManager(cfg)

        session_dir_1 = mgr.start("session-1")
        mgr.handle_event(_tool_event("read_file", file_path="a.py"))

        # Second start should auto-stop first
        session_dir_2 = mgr.start("session-2")
        mgr.handle_event(_tool_event("edit_file", file_path="b.py"))

        assert session_dir_1 != session_dir_2
        assert mgr.is_recording

        # First session's metadata should have been written
        assert (session_dir_1 / "recording.json").exists()
        meta = json.loads((session_dir_1 / "recording.json").read_text())
        assert meta["session_id"] == "session-1"
        assert meta["total_frames"] == 1

        # Second session should work normally
        session = mgr.stop()
        assert session.session_id == "session-2"
        assert session.total_frames == 1


class TestStopWithoutStart:
    def test_stop_without_start_graceful(self) -> None:
        """stop() without start() should return a degraded session, not crash."""
        mgr = RecordingSessionManager()
        session = mgr.stop()

        assert isinstance(session, RecordingSession)
        assert session.session_id == ""
        assert session.total_frames == 0
        assert session.output_dir == ""
        assert not mgr.is_recording


class TestKindClassSanitization:
    def test_special_chars_stripped(self, tmp_path: Path) -> None:
        """event_kind with special chars should produce a safe CSS class."""
        session_dir = tmp_path / "sanitize-session"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        graph = ExplorationGraph()

        frames = [
            RecordingFrame(
                frame_id="frame-0001",
                timestamp=time.time(),
                frame_number=1,
                event_kind='tool; onclick=alert(1)',
                agent_id="main",
                iteration=1,
            ),
            RecordingFrame(
                frame_id="frame-0002",
                timestamp=time.time(),
                frame_number=2,
                event_kind='tool<img src=x>',
                agent_id="main",
                iteration=2,
            ),
        ]

        path = assemble_gallery(
            session_dir=session_dir,
            frames=frames,
            exploration=graph,
            session_id="sanitize-test",
            start_time=time.time(),
        )

        content = path.read_text()
        # The CSS class should NOT contain semicolons, spaces, angle brackets, or parens
        # The malicious event_kind is sanitized in the class attr but html-escaped in the display
        assert 'class="frame-card tool; onclick=alert(1)"' not in content
        assert 'class="frame-card toolonclickalert1"' in content
        assert 'class="frame-card toolimgsrcx"' in content
        # The event_kind display text is html-escaped, not raw
        assert "tool&lt;img src=x&gt;" in content


class TestPathTraversal:
    def test_traversal_blocked(self, tmp_path: Path) -> None:
        """_load_screenshot should reject paths that escape session_dir."""
        from attocode.integrations.recording.assembly import _load_screenshot

        session_dir = tmp_path / "session"
        session_dir.mkdir()

        # Create a file outside session_dir
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret data")

        result = _load_screenshot("../secret.txt", session_dir)
        assert "invalid path" in result
        assert "secret data" not in result

    def test_absolute_path_outside_blocked(self, tmp_path: Path) -> None:
        """Absolute paths outside session_dir should be rejected."""
        from attocode.integrations.recording.assembly import _load_screenshot

        session_dir = tmp_path / "session"
        session_dir.mkdir()

        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("outside data")

        result = _load_screenshot(str(outside_file), session_dir)
        assert "invalid path" in result

    def test_valid_path_inside_still_works(self, tmp_path: Path) -> None:
        """Valid paths within session_dir should still load correctly."""
        from attocode.integrations.recording.assembly import _load_screenshot

        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / "frames").mkdir()

        valid_file = session_dir / "frames" / "test.txt"
        valid_file.write_text("valid content")

        result = _load_screenshot(str(valid_file), session_dir)
        assert "valid content" in result


class TestBuilderWithRecording:
    def test_with_recording_stores_config(self) -> None:
        """AgentBuilder.with_recording() should store the recording config."""
        from attocode.agent.builder import AgentBuilder

        cfg = RecordingConfig(output_dir="/tmp/test-rec", max_frames=100)
        builder = AgentBuilder().with_recording(cfg)

        assert builder._recording_config is cfg

    def test_with_recording_default_config(self) -> None:
        """with_recording(None) should create a default RecordingConfig."""
        from attocode.agent.builder import AgentBuilder

        builder = AgentBuilder().with_recording()

        assert builder._recording_config is not None
        assert isinstance(builder._recording_config, RecordingConfig)

    def test_with_recording_disabled(self) -> None:
        """with_recording(enabled=False) should not store config."""
        from attocode.agent.builder import AgentBuilder

        builder = AgentBuilder().with_recording(enabled=False)

        assert not hasattr(builder, "_recording_config") or builder._recording_config is None
