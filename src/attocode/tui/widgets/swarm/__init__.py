"""Swarm dashboard widgets."""

from attocode.tui.widgets.swarm.agent_grid import AgentGrid, AgentsDataTable
from attocode.tui.widgets.swarm.ast_blackboard_pane import ASTBlackboardPane
from attocode.tui.widgets.swarm.control_bar import (
    RetryTaskRequested,
    SkipTaskRequested,
    SwarmCancelRequested,
    SwarmControlBar,
    SwarmPauseRequested,
    SwarmResumeRequested,
)
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView, DependencyTree
from attocode.tui.widgets.swarm.decisions_pane import DecisionsPane
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.event_timeline import EventsLog, EventTimeline
from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap
from attocode.tui.widgets.swarm.files_pane import FilesPane
from attocode.tui.widgets.swarm.messages_log import MessagesLog
from attocode.tui.widgets.swarm.model_health_pane import ModelHealthPane
from attocode.tui.widgets.swarm.overview_pane import OverviewPane
from attocode.tui.widgets.swarm.quality_pane import QualityPane
from attocode.tui.widgets.swarm.task_board import TaskBoard, TasksDataTable
from attocode.tui.widgets.swarm.tasks_pane import TasksPane
from attocode.tui.widgets.swarm.workers_pane import WorkerDetailCard, WorkersPane, WorkerStreamView

__all__ = [
    "AgentGrid",
    "AgentsDataTable",
    "TaskBoard",
    "TasksDataTable",
    "DependencyDAGView",
    "DependencyTree",
    "EventTimeline",
    "EventsLog",
    "DetailInspector",
    "FileActivityMap",
    "MessagesLog",
    # Dashboard tab panes
    "OverviewPane",
    "WorkerDetailCard",
    "WorkerStreamView",
    "WorkersPane",
    "TasksPane",
    "ModelHealthPane",
    "DecisionsPane",
    "FilesPane",
    "QualityPane",
    "ASTBlackboardPane",
    # Control bar
    "SwarmControlBar",
    "SwarmPauseRequested",
    "SwarmResumeRequested",
    "SwarmCancelRequested",
    "SkipTaskRequested",
    "RetryTaskRequested",
]
