"""Visual Debug Recorder — captures agent execution for replay and analysis."""

from attocode.integrations.recording.assembly import assemble_gallery
from attocode.integrations.recording.exploration_tracker import (
    ExplorationEdge,
    ExplorationGraph,
    ExplorationNode,
    ExplorationSnapshot,
    tool_to_action,
)
from attocode.integrations.recording.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    SessionGraph,
)
from attocode.integrations.recording.playback import (
    PlaybackEngine,
    PlaybackState,
)
from attocode.integrations.recording.recorder import (
    RecordingConfig,
    RecordingFrame,
    RecordingSession,
    RecordingSessionManager,
)

__all__ = [
    # assembly
    "assemble_gallery",
    # exploration_tracker
    "ExplorationEdge",
    "ExplorationGraph",
    "ExplorationNode",
    "ExplorationSnapshot",
    "tool_to_action",
    # graph_types (unified)
    "EdgeKind",
    "GraphEdge",
    "GraphNode",
    "NodeKind",
    "SessionGraph",
    # playback
    "PlaybackEngine",
    "PlaybackState",
    # recorder
    "RecordingConfig",
    "RecordingFrame",
    "RecordingSession",
    "RecordingSessionManager",
]
