"""Canonical attoswarm modal/screen namespace."""

from attocode.tui.screens.add_task_screen import AddTaskScreen
from attocode.tui.screens.completion_screen import CompletionScreen
from attocode.tui.screens.confirm_stop_screen import ConfirmStopScreen
from attocode.tui.screens.edit_task_screen import EditTaskScreen
from attocode.tui.screens.focus_screen import FocusScreen
from attocode.tui.screens.graph_screen import GraphScreen
from attocode.tui.screens.timeline_screen import TimelineScreen

__all__ = [
    "AddTaskScreen",
    "CompletionScreen",
    "ConfirmStopScreen",
    "EditTaskScreen",
    "FocusScreen",
    "GraphScreen",
    "TimelineScreen",
]
