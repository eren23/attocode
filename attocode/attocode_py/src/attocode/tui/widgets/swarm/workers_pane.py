"""Tab 2: Workers pane — deep agent monitoring with detail cards and stream view."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class WorkerDetailCard(Widget):
    """Detailed card for a single worker."""

    DEFAULT_CSS = """
    WorkerDetailCard {
        height: auto;
        min-height: 4;
        border: solid $accent;
        padding: 0 1;
        margin-bottom: 1;
    }
    WorkerDetailCard.selected {
        border: double $warning;
    }
    """

    class Clicked(Message):
        """Posted when the card is clicked."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, worker: dict[str, Any], index: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._worker = worker
        self._index = index

    def render(self) -> Text:
        w = self._worker
        text = Text()

        # Agent ID + model
        text.append(w.get("worker_name", "worker"), style="bold")
        text.append(f" ({w.get('model', '?')})\n", style="dim")

        # Current task
        task_id = w.get("task_id", "")
        if task_id:
            text.append(f"  Task: {task_id[:20]}\n", style="cyan")
            desc = w.get("task_description", "")
            if desc:
                text.append(f"  {desc[:50]}\n", style="dim")

        # Duration
        started = w.get("started_at", 0)
        if started:
            elapsed = int(time.time() - started)
            text.append(f"  Running: {elapsed}s\n", style="dim")

        return text

    def update_worker(self, worker: dict[str, Any]) -> None:
        self._worker = worker
        self.refresh()

    def on_click(self) -> None:
        self.post_message(self.Clicked(self._index))


class WorkerStreamView(Widget):
    """Shows filtered timeline events for the selected worker."""

    DEFAULT_CSS = """
    WorkerStreamView {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._events: list[dict[str, Any]] = []
        self._task_id: str = ""

    def render(self) -> Text:
        text = Text()
        if not self._task_id:
            text.append("Select a worker to view its event stream", style="dim italic")
            return text

        text.append(f"Events for task: {self._task_id}\n", style="bold underline")
        text.append("\n")

        for evt in self._events[-40:]:
            ts = evt.get("timestamp", 0)
            t = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "??:??:??"
            etype = evt.get("type", "unknown")

            # Color-code event types
            style_map = {
                "swarm.task.dispatched": "cyan",
                "swarm.task.completed": "green",
                "swarm.task.failed": "red",
                "swarm.task.attempt": "yellow",
                "swarm.quality.result": "magenta",
                "swarm.quality.rejected": "red bold",
                "swarm.model.failover": "yellow bold",
                "swarm.hollow_detected": "red dim",
            }
            evt_style = style_map.get(etype, "cyan")

            text.append(f"[{t}] ", style="dim")
            text.append(f"{etype}", style=evt_style)

            # Show extra detail for certain events
            if etype == "swarm.task.attempt":
                model = evt.get("model", "")
                duration = evt.get("duration_ms", 0)
                success = evt.get("success", False)
                tools = evt.get("tool_calls", 0)
                text.append(f" {model}", style="dim")
                if duration:
                    text.append(f" {duration}ms", style="dim")
                if tools:
                    text.append(f" {tools}tc", style="dim")
                text.append(
                    " \u2713" if success else " \u2717",
                    style="green" if success else "red",
                )
            elif etype == "swarm.quality.result":
                score = evt.get("score", "?")
                passed = evt.get("passed", False)
                text.append(f" score={score}", style="dim")
                text.append(
                    " PASS" if passed else " FAIL",
                    style="green" if passed else "red",
                )
            elif etype == "swarm.model.failover":
                text.append(
                    f" {evt.get('from_model', '?')}\u2192{evt.get('to_model', '?')}",
                    style="yellow",
                )
            elif etype in ("swarm.task.completed", "swarm.task.failed"):
                # Show enriched data from worker results
                files_mod = evt.get("files_modified") or []
                session_id = evt.get("session_id", "")
                num_turns = evt.get("num_turns", 0)
                cost = evt.get("cost_used", 0.0)
                if files_mod:
                    text.append(f" {len(files_mod)} files", style="dim")
                if session_id:
                    text.append(f" sess:{session_id[:8]}", style="dim")
                if num_turns:
                    text.append(f" {num_turns}t", style="dim")
                if cost:
                    text.append(f" ${cost:.3f}", style="magenta dim")

            text.append("\n")

        if not self._events:
            text.append("No events yet", style="dim italic")

        return text

    def filter_for_task(self, task_id: str, all_events: list[dict[str, Any]]) -> None:
        """Filter events for the given task."""
        self._task_id = task_id
        self._events = [
            e for e in all_events
            if e.get("task_id") == task_id
        ]
        self.refresh()


class WorkersPane(Widget):
    """Left: WorkerDetailList, Right: WorkerStreamView."""

    DEFAULT_CSS = """
    WorkersPane {
        height: 1fr;
    }
    WorkersPane #workers-left {
        width: 1fr;
        overflow-y: auto;
    }
    WorkersPane #workers-right {
        width: 2fr;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workers: list[dict[str, Any]] = []
        self._last_state: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield VerticalScroll(id="workers-left")
            yield WorkerStreamView(id="workers-stream")

    def update_state(self, state: dict[str, Any]) -> None:
        """Update worker list from state."""
        workers = state.get("status", {}).get("active_workers", [])
        self._workers = workers
        self._last_state = state

        try:
            left = self.query_one("#workers-left", VerticalScroll)
            # Clear existing cards
            for card in left.query(WorkerDetailCard):
                card.remove()
            # Add new cards
            for i, w in enumerate(workers):
                card = WorkerDetailCard(w, index=i, id=f"wcard-{i}")
                if i == self.selected_index:
                    card.add_class("selected")
                left.mount(card)
        except Exception:
            pass

        # Update stream for selected worker
        self._update_stream_for_selected(state)

    def watch_selected_index(self, old_index: int, new_index: int) -> None:
        """Update selection highlight when selected_index changes."""
        # Remove old selection
        try:
            old_card = self.query_one(f"#wcard-{old_index}", WorkerDetailCard)
            old_card.remove_class("selected")
        except Exception:
            pass
        # Add new selection
        try:
            new_card = self.query_one(f"#wcard-{new_index}", WorkerDetailCard)
            new_card.add_class("selected")
        except Exception:
            pass
        # Update stream view
        if hasattr(self, "_last_state"):
            self._update_stream_for_selected(self._last_state)

    def on_worker_detail_card_clicked(self, event: WorkerDetailCard.Clicked) -> None:
        """Handle card click to select worker."""
        self.select_worker(event.index)

    def select_worker(self, index: int) -> None:
        """Select a worker by index."""
        if 0 <= index < len(self._workers):
            self.selected_index = index

    def filter_for_task(self, task_id: str) -> None:
        """Filter the stream view for a specific task (called externally)."""
        try:
            stream = self.query_one("#workers-stream", WorkerStreamView)
            stream.filter_for_task(task_id, self._last_state.get("timeline", []))
        except Exception:
            pass

    def _update_stream_for_selected(self, state: dict[str, Any]) -> None:
        """Update the stream view for the currently selected worker."""
        workers = self._workers
        if workers and 0 <= self.selected_index < len(workers):
            selected = workers[self.selected_index]
            task_id = selected.get("task_id", "")
            try:
                stream = self.query_one("#workers-stream", WorkerStreamView)
                stream.filter_for_task(task_id, state.get("timeline", []))
            except Exception:
                pass
