"""TUI widgets."""

from attocode.tui.widgets.agents_panel import ActiveAgentInfo, AgentsPanel
from attocode.tui.widgets.input_area import PromptInput
from attocode.tui.widgets.message_log import MessageLog
from attocode.tui.widgets.plan_panel import PlanPanel
from attocode.tui.widgets.status_bar import StatusBar
from attocode.tui.widgets.streaming_buffer import StreamingBuffer
from attocode.tui.widgets.swarm_panel import SwarmPanel
from attocode.tui.widgets.tasks_panel import TasksPanel
from attocode.tui.widgets.thinking_panel import ThinkingPanel
from attocode.tui.widgets.tool_calls import ToolCallInfo, ToolCallsPanel
from attocode.tui.widgets.diff_view import (
    CollapsibleDiffView,
    DiffHunk,
    DiffLine,
    DiffView,
    FileDiff,
    FileChangeSummary,
    compute_diff,
    render_diff_line,
)
from attocode.tui.widgets.debug_panel import DebugPanel, DiagnosticsPanel
from attocode.tui.widgets.command_palette import (
    CommandEntry,
    CommandPaletteScreen,
    CommandRegistry,
    fuzzy_match,
    register_default_commands,
)

__all__ = [
    # existing
    "ActiveAgentInfo",
    "AgentsPanel",
    "MessageLog",
    "PlanPanel",
    "PromptInput",
    "StatusBar",
    "StreamingBuffer",
    "SwarmPanel",
    "TasksPanel",
    "ThinkingPanel",
    "ToolCallInfo",
    "ToolCallsPanel",
    # diff_view
    "CollapsibleDiffView",
    "DiffHunk",
    "DiffLine",
    "DiffView",
    "FileDiff",
    "FileChangeSummary",
    "compute_diff",
    "render_diff_line",
    # debug_panel
    "DebugPanel",
    "DiagnosticsPanel",
    # command_palette
    "CommandEntry",
    "CommandPaletteScreen",
    "CommandRegistry",
    "fuzzy_match",
    "register_default_commands",
]
