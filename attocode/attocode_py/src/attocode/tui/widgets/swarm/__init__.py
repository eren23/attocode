"""Swarm dashboard widgets."""

from attocode.tui.widgets.swarm.agent_grid import AgentGrid
from attocode.tui.widgets.swarm.task_board import TaskBoard
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView
from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap
from attocode.tui.widgets.swarm.overview_pane import OverviewPane
from attocode.tui.widgets.swarm.workers_pane import WorkerDetailCard, WorkerStreamView, WorkersPane
from attocode.tui.widgets.swarm.tasks_pane import TasksPane
from attocode.tui.widgets.swarm.model_health_pane import ModelHealthPane
from attocode.tui.widgets.swarm.decisions_pane import DecisionsPane
from attocode.tui.widgets.swarm.files_pane import FilesPane
from attocode.tui.widgets.swarm.quality_pane import QualityPane
from attocode.tui.widgets.swarm.ast_blackboard_pane import ASTBlackboardPane

__all__ = [
    "AgentGrid",
    "TaskBoard",
    "DependencyDAGView",
    "EventTimeline",
    "DetailInspector",
    "FileActivityMap",
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
]
