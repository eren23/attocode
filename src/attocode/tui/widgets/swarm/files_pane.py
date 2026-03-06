"""Tab 6: Files & Artifacts pane — file activity, artifacts, and conflicts."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Static

from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap


class ArtifactInventoryView(Widget):
    """Summary of artifact inventory with file list."""

    DEFAULT_CSS = """
    ArtifactInventoryView {
        height: auto;
        min-height: 4;
        max-height: 12;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._inventory: dict[str, Any] | None = None

    def render(self) -> Text:
        text = Text()
        text.append("Artifact Inventory\n", style="bold underline")

        if not self._inventory:
            text.append("No artifacts collected yet", style="dim italic")
            return text

        total_files = self._inventory.get("total_files", 0)
        total_bytes = self._inventory.get("total_bytes", 0)

        text.append(f"  Files: {total_files}  |  ", style="dim")
        if total_bytes > 1_000_000:
            text.append(f"Size: {total_bytes / 1_000_000:.1f}MB\n", style="dim")
        elif total_bytes > 1_000:
            text.append(f"Size: {total_bytes / 1_000:.1f}KB\n", style="dim")
        else:
            text.append(f"Size: {total_bytes}B\n", style="dim")

        return text

    def update_inventory(self, inventory: dict[str, Any] | None) -> None:
        self._inventory = inventory
        self.refresh()


class FileConflictsView(Widget):
    """Files touched by multiple tasks — conflict detection."""

    DEFAULT_CSS = """
    FileConflictsView {
        height: auto;
        min-height: 3;
        max-height: 15;
        border: solid $warning;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._conflicts: list[dict[str, Any]] = []

    def render(self) -> Text:
        text = Text()
        text.append("File Conflicts\n", style="bold underline")

        if not self._conflicts:
            text.append("No conflicts detected", style="green dim")
            return text

        for c in self._conflicts[:20]:
            file_path = c.get("file", "?")
            tasks = c.get("tasks", [])
            text.append(f"  {file_path}\n", style="yellow")
            for t in tasks[:5]:
                text.append(f"    - {t}\n", style="dim")

        return text

    def detect_conflicts(self, tasks: dict[str, dict[str, Any]]) -> None:
        """Detect files touched by multiple tasks."""
        file_to_tasks: dict[str, list[str]] = {}
        for tid, t in tasks.items():
            for f in t.get("target_files", []) or []:
                file_to_tasks.setdefault(f, []).append(tid)

        self._conflicts = [
            {"file": f, "tasks": tids}
            for f, tids in file_to_tasks.items()
            if len(tids) > 1
        ]
        self.refresh()


class FilesPane(Widget):
    """File activity map + artifact inventory + conflict view."""

    DEFAULT_CSS = """
    FilesPane {
        height: 1fr;
    }
    FilesPane #files-activity {
        height: 2fr;
    }
    FilesPane #files-bottom {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield FileActivityMap(id="files-activity-map")
            with Vertical(id="files-bottom"):
                yield ArtifactInventoryView(id="files-artifacts")
                yield FileConflictsView(id="files-conflicts")

    def update_state(self, state: dict[str, Any]) -> None:
        """Push state to child widgets."""
        tasks = state.get("tasks", {})

        # Build file→activity mapping from tasks dict for FileActivityMap.
        # FileActivityMap expects {file_path: [{"agent_id": ..., "action": ...}]}
        file_activity: dict[str, list[dict[str, Any]]] = {}
        if isinstance(tasks, dict):
            for tid, t in tasks.items():
                agent_id = t.get("assigned_model") or tid
                for f in t.get("target_files", []) or []:
                    file_activity.setdefault(f, []).append(
                        {"agent_id": agent_id, "action": "write"}
                    )
                for f in t.get("read_files", []) or []:
                    if f not in file_activity or not any(
                        a.get("agent_id") == agent_id for a in file_activity.get(f, [])
                    ):
                        file_activity.setdefault(f, []).append(
                            {"agent_id": agent_id, "action": "read"}
                        )
                # Actual files modified from worker results
                for f in t.get("files_modified", []) or []:
                    file_activity.setdefault(f, []).append(
                        {"agent_id": agent_id, "action": "modified"}
                    )

        try:
            self.query_one("#files-activity-map", FileActivityMap).update_activity(
                file_activity
            )
        except Exception:
            pass
        try:
            self.query_one("#files-artifacts", ArtifactInventoryView).update_inventory(
                state.get("artifact_inventory")
            )
        except Exception:
            pass
        try:
            self.query_one("#files-conflicts", FileConflictsView).detect_conflicts(tasks)
        except Exception:
            pass
