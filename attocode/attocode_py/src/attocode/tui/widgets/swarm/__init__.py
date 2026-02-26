"""Swarm dashboard widgets."""

from attocode.tui.widgets.swarm.agent_grid import AgentGrid
from attocode.tui.widgets.swarm.task_board import TaskBoard
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView
from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap

__all__ = [
    "AgentGrid",
    "TaskBoard",
    "DependencyDAGView",
    "EventTimeline",
    "DetailInspector",
    "FileActivityMap",
]
