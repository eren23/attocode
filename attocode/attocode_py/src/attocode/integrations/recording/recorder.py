"""Recording session manager — lifecycle and event handling.

Coordinates frame capture, exploration tracking, and metadata
annotation for visual debug recordings of agent execution.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attocode.integrations.recording.exploration_tracker import (
    ExplorationGraph,
    ExplorationSnapshot,
    tool_to_action,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecordingConfig:
    """Configuration for a recording session."""

    output_dir: str = ".attocode/recordings"
    capture_granularity: str = "tool_call"  # "iteration" | "tool_call" | "event"
    capture_screenshots: bool = True
    max_frames: int = 500
    debounce_ms: float = 200.0


@dataclass(slots=True)
class RecordingFrame:
    """A single captured frame in the recording."""

    frame_id: str
    timestamp: float
    frame_number: int
    event_kind: str
    agent_id: str
    iteration: int
    screenshot_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    exploration_snapshot: ExplorationSnapshot | None = None
    annotations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecordingSession:
    """Completed recording session with all frames and metadata."""

    session_id: str
    start_time: float
    end_time: float
    frames: list[RecordingFrame]
    exploration_graph: ExplorationGraph
    config: RecordingConfig
    output_dir: str
    total_frames: int = 0
    agents: list[str] = field(default_factory=list)


# Event types that trigger frame capture
_CAPTURE_EVENTS = {
    "tool.start", "tool.complete", "tool.error",
    "iteration", "response",
    "subagent.spawn", "subagent.complete",
    "swarm.task.start", "swarm.task.complete",
    "compaction", "compaction.complete",
}

# Event types captured at all granularity levels
_ALWAYS_CAPTURE = {"tool.error", "subagent.spawn", "subagent.complete"}

# Tool names that indicate file access (for exploration tracking)
_FILE_ACCESS_TOOLS = {
    "read_file", "edit_file", "write_file", "grep", "glob",
    "get_repo_map", "get_tree_view", "bash",
}


class RecordingSessionManager:
    """Manages a recording session lifecycle.

    Usage::

        mgr = RecordingSessionManager(config)
        session_dir = mgr.start("session-abc")
        # ... agent runs, events flow through handle_event() ...
        session = mgr.stop()
        gallery_path = mgr.export("html")
    """

    def __init__(
        self,
        config: RecordingConfig | None = None,
        capture_callback: Any = None,
    ) -> None:
        self._config = config or RecordingConfig()
        self._capture_callback = capture_callback  # TUI screenshot bridge
        self._session_id: str = ""
        self._session_dir: Path | None = None
        self._frames: list[RecordingFrame] = []
        self._exploration = ExplorationGraph()
        self._frame_counter: int = 0
        self._last_capture_time: float = 0.0
        self._start_time: float = 0.0
        self._recording: bool = False
        self._agents_seen: set[str] = set()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def frame_count(self) -> int:
        return self._frame_counter

    @property
    def exploration_graph(self) -> ExplorationGraph:
        return self._exploration

    def start(self, session_id: str) -> Path:
        """Start a new recording session.

        Creates the output directory structure and returns its path.
        If already recording, the previous session is auto-stopped first.
        """
        if self._recording:
            self.stop()

        self._session_id = session_id
        self._start_time = time.time()
        self._recording = True
        self._frames = []
        self._exploration = ExplorationGraph()
        self._frame_counter = 0
        self._agents_seen = set()

        base = Path(self._config.output_dir)
        self._session_dir = base / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        (self._session_dir / "frames").mkdir(exist_ok=True)

        logger.info("Recording started: session=%s dir=%s", session_id, self._session_dir)
        return self._session_dir

    def stop(self) -> RecordingSession:
        """Stop the recording and return the completed session.

        Also writes metadata files (recording.json, exploration_graph.json,
        exploration.mermaid) to the session directory.
        """
        end_time = time.time()
        self._recording = False

        session = RecordingSession(
            session_id=self._session_id,
            start_time=self._start_time,
            end_time=end_time,
            frames=list(self._frames),
            exploration_graph=self._exploration,
            config=self._config,
            output_dir=str(self._session_dir) if self._session_dir else "",
            total_frames=self._frame_counter,
            agents=sorted(self._agents_seen),
        )

        # Persist metadata
        if self._session_dir:
            self._write_metadata(session)

        logger.info(
            "Recording stopped: session=%s frames=%d duration=%.1fs",
            self._session_id, self._frame_counter, end_time - self._start_time,
        )
        return session

    def handle_event(self, event: Any) -> None:
        """Process an AgentEvent, updating exploration and capturing frames.

        This is the main hook — wire it into the agent's event pipeline.
        """
        if not self._recording:
            return
        if self._frame_counter >= self._config.max_frames:
            return

        event_type = str(getattr(event, "type", ""))
        agent_id = getattr(event, "agent_id", None) or "main"
        self._agents_seen.add(agent_id)

        # --- Update exploration graph for file-access tool events ---
        if event_type in ("tool.complete", "tool.start"):
            self._track_exploration(event, agent_id)

        # --- Determine whether to capture a frame ---
        if not self._should_capture(event_type):
            return

        # Debounce
        now = time.time()
        if (now - self._last_capture_time) * 1000 < self._config.debounce_ms:
            if event_type not in _ALWAYS_CAPTURE:
                return

        self._last_capture_time = now
        self._frame_counter += 1

        # Capture screenshot (async-safe: schedule if callback is coroutine)
        screenshot_path: str | None = None
        if self._config.capture_screenshots and self._session_dir:
            screenshot_path = self._capture_screenshot(event_type)

        # Build frame
        frame = RecordingFrame(
            frame_id=f"frame-{self._frame_counter:04d}",
            timestamp=now,
            frame_number=self._frame_counter,
            event_kind=event_type,
            agent_id=agent_id,
            iteration=getattr(event, "iteration", 0) or 0,
            screenshot_path=screenshot_path,
            metadata=self._extract_metadata(event),
            exploration_snapshot=self._exploration.get_snapshot(agent_id),
            annotations=self._generate_annotations(event),
        )
        self._frames.append(frame)

        # Write sidecar JSON
        if self._session_dir:
            self._write_frame_sidecar(frame)

    def export(self, format: str = "html") -> Path:
        """Export the recording to the specified format.

        Args:
            format: ``"html"`` for a self-contained gallery,
                    ``"mermaid"`` for exploration diagram only.

        Returns:
            Path to the exported file.
        """
        if not self._session_dir:
            raise RuntimeError("No recording session to export")

        if format == "mermaid":
            path = self._session_dir / "exploration.mermaid"
            path.write_text(self._exploration.to_mermaid(), encoding="utf-8")
            return path

        # HTML gallery
        from attocode.integrations.recording.assembly import assemble_gallery

        return assemble_gallery(
            session_dir=self._session_dir,
            frames=self._frames,
            exploration=self._exploration,
            session_id=self._session_id,
            start_time=self._start_time,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _track_exploration(self, event: Any, agent_id: str) -> None:
        """Update the exploration graph from a tool event."""
        tool_name = getattr(event, "tool", "") or ""
        if tool_name not in _FILE_ACCESS_TOOLS:
            return

        args = getattr(event, "args", None) or {}
        file_path = (
            args.get("file_path")
            or args.get("path")
            or args.get("pattern", "")
        )
        if not file_path:
            return

        action = tool_to_action(tool_name)
        iteration = getattr(event, "iteration", 0) or 0

        node = self._exploration.add_visit(
            file_path=file_path,
            agent_id=agent_id,
            action=action,
            tool_name=tool_name,
            iteration=iteration,
            metadata={"args": args},
        )

        # Mark edits as key findings
        if action == "edit":
            self._exploration.mark_outcome(node.node_id, "key_finding")

    def _should_capture(self, event_type: str) -> bool:
        """Determine if this event type should trigger a frame capture."""
        if event_type in _ALWAYS_CAPTURE:
            return True

        gran = self._config.capture_granularity
        if gran == "event":
            return event_type in _CAPTURE_EVENTS
        elif gran == "tool_call":
            return event_type in (
                "tool.start", "tool.complete", "tool.error",
                "iteration", "subagent.spawn", "subagent.complete",
            )
        elif gran == "iteration":
            return event_type in ("iteration", "subagent.spawn", "subagent.complete")
        return False

    def _capture_screenshot(self, event_type: str) -> str | None:
        """Request a screenshot capture (via bridge or fallback)."""
        if not self._session_dir:
            return None

        filename = f"frame-{self._frame_counter:04d}-{event_type.replace('.', '_')}.svg"
        path = self._session_dir / "frames" / filename

        if self._capture_callback:
            try:
                # The callback may be sync or async — fire-and-forget pattern
                self._capture_callback(str(path))
                return str(path)
            except Exception:
                pass

        # Fallback: write ASCII exploration art as a text file
        ascii_path = path.with_suffix(".txt")
        try:
            ascii_art = self._exploration.to_ascii_dag()
            ascii_path.write_text(ascii_art, encoding="utf-8")
            return str(ascii_path)
        except Exception:
            return None

    def _extract_metadata(self, event: Any) -> dict[str, Any]:
        """Extract relevant metadata from an event."""
        meta: dict[str, Any] = {}
        for attr in ("tool", "args", "result", "error", "tokens", "cost", "duration_ms"):
            val = getattr(event, attr, None)
            if val is not None:
                # Truncate long results to avoid bloating sidecar files
                if attr == "result" and isinstance(val, str) and len(val) > 500:
                    val = val[:500] + "..."
                meta[attr] = val
        return meta

    def _generate_annotations(self, event: Any) -> list[str]:
        """Generate human-readable annotations for a frame."""
        annotations: list[str] = []
        event_type = str(getattr(event, "type", ""))
        tool = getattr(event, "tool", "")

        if event_type == "tool.error":
            error = getattr(event, "error", "unknown")
            annotations.append(f"Tool error: {error}")
        elif event_type == "tool.complete" and tool:
            annotations.append(f"Completed: {tool}")
        elif event_type == "subagent.spawn":
            annotations.append(f"Subagent spawned: {getattr(event, 'agent_id', '?')}")
        elif event_type == "iteration":
            annotations.append(f"Iteration {getattr(event, 'iteration', '?')}")

        return annotations

    def _write_frame_sidecar(self, frame: RecordingFrame) -> None:
        """Write a JSON sidecar file for a frame."""
        if not self._session_dir:
            return
        sidecar_path = (
            self._session_dir / "frames" / f"{frame.frame_id}-{frame.event_kind.replace('.', '_')}.json"
        )
        data = {
            "frame_id": frame.frame_id,
            "timestamp": frame.timestamp,
            "frame_number": frame.frame_number,
            "event_kind": frame.event_kind,
            "agent_id": frame.agent_id,
            "iteration": frame.iteration,
            "screenshot_path": frame.screenshot_path,
            "metadata": frame.metadata,
            "annotations": frame.annotations,
        }
        try:
            sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass  # Non-fatal

    def _write_metadata(self, session: RecordingSession) -> None:
        """Write session-level metadata files."""
        if not self._session_dir:
            return

        # recording.json
        meta = {
            "session_id": session.session_id,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "total_frames": session.total_frames,
            "agents": session.agents,
            "config": {
                "capture_granularity": session.config.capture_granularity,
                "capture_screenshots": session.config.capture_screenshots,
                "max_frames": session.config.max_frames,
            },
        }
        try:
            (self._session_dir / "recording.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8",
            )
        except Exception:
            pass

        # exploration_graph.json
        try:
            (self._session_dir / "exploration_graph.json").write_text(
                json.dumps(self._exploration.to_dict(), indent=2), encoding="utf-8",
            )
        except Exception:
            pass

        # exploration.mermaid
        try:
            (self._session_dir / "exploration.mermaid").write_text(
                self._exploration.to_mermaid(), encoding="utf-8",
            )
        except Exception:
            pass
