"""TUI widgets."""

from attocode.tui.widgets.agents_panel import ActiveAgentInfo, AgentsPanel
from attocode.tui.widgets.input_area import PromptInput
from attocode.tui.widgets.mascot import GhostExpression, render_ghost, render_startup_banner
from attocode.tui.widgets.message_log import MessageLog
from attocode.tui.widgets.plan_panel import PlanPanel
from attocode.tui.widgets.status_bar import StatusBar
from attocode.tui.widgets.streaming_buffer import StreamingBuffer
from attocode.tui.widgets.welcome_banner import WelcomeBanner
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
from attocode.tui.widgets.debug_panel import DebugPanel
from attocode.tui.widgets.transparency_panel import TransparencyPanel
from attocode.tui.widgets.error_detail_panel import ErrorDetail, ErrorDetailPanel
from attocode.tui.widgets.file_change_summary import FileChangeSummary as FileChangeSummaryWidget
from attocode.tui.widgets.diagnostics_panel import DiagnosticItem, DiagnosticsPanel
from attocode.tui.widgets.side_by_side_diff import SideBySideDiff, SideBySideLine
from attocode.tui.widgets.collapsible_diff import CollapsibleDiffView as CollapsibleDiffWidget
from attocode.tui.widgets.command_palette import (
    CommandEntry,
    CommandPaletteScreen,
    CommandRegistry,
    fuzzy_match,
    register_default_commands,
)
from attocode.tui.widgets.token_sparkline import TokenSparkline
from attocode.tui.widgets.metrics_table import MetricsScreen

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
    # transparency_panel
    "TransparencyPanel",
    # error_detail_panel
    "ErrorDetail",
    "ErrorDetailPanel",
    # file_change_summary (widget)
    "FileChangeSummaryWidget",
    # diagnostics_panel
    "DiagnosticItem",
    "DiagnosticsPanel",
    # side_by_side_diff
    "SideBySideDiff",
    "SideBySideLine",
    # collapsible_diff (widget)
    "CollapsibleDiffWidget",
    # command_palette
    "CommandEntry",
    "CommandPaletteScreen",
    "CommandRegistry",
    "fuzzy_match",
    "register_default_commands",
    # mascot
    "GhostExpression",
    "render_ghost",
    "render_startup_banner",
    # welcome_banner
    "WelcomeBanner",
    # token_sparkline
    "TokenSparkline",
    # metrics_table
    "MetricsScreen",
]
