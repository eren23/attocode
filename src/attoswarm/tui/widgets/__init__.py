"""Canonical swarm widget namespace for attoswarm UI."""

from attocode.tui.widgets.swarm.agent_grid import AgentCard, AgentGrid, AgentsDataTable
from attocode.tui.widgets.swarm.agent_trace_stream import AgentTraceStream
from attocode.tui.widgets.swarm.budget_projection_widget import BudgetProjectionWidget
from attocode.tui.widgets.swarm.conflict_panel import ConflictPanel
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView, DependencyTree
from attocode.tui.widgets.swarm.decisions_pane import DecisionsPane
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.event_timeline import (
    EventsLog,
    EventTimeline,
    _AGENT_COLORS,
    _agent_color,
    _agent_color_cache,
)
from attocode.tui.widgets.swarm.failure_chain_widget import FailureChainWidget
from attocode.tui.widgets.swarm.messages_log import MessagesLog
from attocode.tui.widgets.swarm.overview_pane import OverviewPane
from attocode.tui.widgets.swarm.task_board import TaskBoard, TaskCard, TasksDataTable

__all__ = [
    "AgentCard",
    "AgentGrid",
    "AgentsDataTable",
    "AgentTraceStream",
    "BudgetProjectionWidget",
    "ConflictPanel",
    "DependencyDAGView",
    "DependencyTree",
    "DecisionsPane",
    "DetailInspector",
    "EventsLog",
    "EventTimeline",
    "FailureChainWidget",
    "MessagesLog",
    "OverviewPane",
    "TaskBoard",
    "TaskCard",
    "TasksDataTable",
    "_AGENT_COLORS",
    "_agent_color",
    "_agent_color_cache",
]
