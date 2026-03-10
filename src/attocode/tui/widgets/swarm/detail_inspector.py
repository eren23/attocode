"""Detail Inspector — full info panel for a selected agent or task."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class DetailInspector(Static):
    """Shows detailed information for a selected agent or task.

    Set ``inspect_data`` to a dict with keys like:
    - kind: "agent" | "task"
    - agent_id / task_id
    - status
    - ... any other metadata
    """

    can_focus = True

    class SkipTaskRequested(Message):
        """User requested to skip a task via detail inspector."""
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    class RetryTaskRequested(Message):
        """User requested to retry a task via detail inspector."""
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    class EditTaskRequested(Message):
        """User requested to edit a task description."""
        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    DEFAULT_CSS = """
    DetailInspector {
        height: auto;
        min-height: 6;
        max-height: 20;
        border: solid $surface-lighten-1;
        padding: 1;
        overflow-y: auto;
    }
    """

    inspect_data: reactive[dict[str, Any]] = reactive(dict)

    def watch_inspect_data(self, data: dict[str, Any]) -> None:
        self._rebuild(data)

    def inspect(self, data: dict[str, Any]) -> None:
        """External API to set inspection target."""
        self.inspect_data = data
        self.focus()

    def on_key(self, event: Any) -> None:
        """Handle action keys for the currently inspected item."""
        data = self.inspect_data
        if not data or data.get("kind") != "task":
            return
        task_id = data.get("task_id", "")
        status = data.get("status", "")
        if not task_id:
            return

        if event.key == "r" and status in ("failed", "skipped"):
            self.post_message(self.RetryTaskRequested(task_id))
            event.stop()
        elif event.key == "s" and status in ("pending", "running", "failed", "skipped"):
            self.post_message(self.SkipTaskRequested(task_id))
            event.stop()
        elif event.key == "e" and status == "pending":
            self.post_message(self.EditTaskRequested(task_id))
            event.stop()

    def _rebuild(self, data: dict[str, Any]) -> None:
        if not data:
            self.update(Text("Select an agent or task to inspect", style="dim italic"))
            return

        text = Text()
        kind = data.get("kind", "unknown")

        if kind == "agent":
            self._render_agent(text, data)
        elif kind == "task":
            self._render_task(text, data)
        else:
            # Generic key-value display
            for key, value in data.items():
                if key == "kind":
                    continue
                text.append(f"  {key}: ", style="bold")
                text.append(f"{value}\n")

        self.update(text)

    @staticmethod
    def _render_agent(text: Text, data: dict[str, Any]) -> None:
        text.append("Agent: ", style="bold")
        text.append(data.get("agent_id", "?"), style="cyan bold")
        text.append("\n")

        status = data.get("status", "?")
        status_style = {"running": "cyan", "exited": "red", "idle": "dim"}.get(status, "")
        text.append("  Status: ")
        text.append(f"{status}\n", style=status_style)

        text.append(f"  Task: {data.get('task_id', 'none')}\n")
        task_title = data.get("task_title", "")
        if task_title:
            text.append(f"  Doing: {task_title}\n")

        # Backend / Model
        backend = data.get("backend", "")
        model = data.get("model", "")
        if backend or model:
            text.append(f"  Backend: {backend}\n")
            if model and model != backend:
                text.append(f"  Model: {model}\n")
        else:
            text.append(f"  Model: {data.get('model', '?')}\n")

        # Role info
        role_type = data.get("role_type", "")
        if role_type:
            text.append(f"  Role: {role_type}\n")
        execution_mode = data.get("execution_mode", "")
        if execution_mode:
            text.append(f"  Execution: {execution_mode}\n")

        text.append(f"  Tokens: {data.get('tokens_used', 0):,}\n")
        text.append(f"  Elapsed: {data.get('elapsed', '?')}\n")

        # Restart info
        restart_count = data.get("restart_count", 0)
        if restart_count:
            text.append(f"  Restarts: {restart_count}\n", style="yellow")

        # Exit code
        exit_code = data.get("exit_code")
        if exit_code is not None:
            style = "red" if exit_code != 0 else "green"
            text.append(f"  Exit code: {exit_code}\n", style=style)

        # Working directory
        cwd = data.get("cwd", "")
        if cwd:
            text.append(f"  CWD: {cwd}\n", style="dim")

        # Result
        result = data.get("result", "")
        if result:
            text.append(f"  Result: {result[:200]}\n", style="dim italic")

        # Files modified
        files = data.get("files_modified", [])
        if files:
            text.append("\n  Files modified:\n")
            for f in files[:10]:
                text.append(f"    \u2022 {f}\n", style="dim")

        # Stderr tail
        stderr = data.get("stderr_tail", "")
        if stderr:
            text.append("\n  Stderr (last 800 chars):\n", style="red dim")
            text.append(f"    {stderr[-800:]}\n", style="red dim")

    @staticmethod
    def _render_task(text: Text, data: dict[str, Any]) -> None:
        text.append("Task: ", style="bold")
        text.append(data.get("task_id", "?"), style="green bold")
        text.append("\n")
        text.append(f"  Title: {data.get('title', '?')}\n")

        status = data.get("status", "?")
        status_style = {
            "running": "cyan",
            "done": "green",
            "failed": "red",
            "pending": "dim",
            "skipped": "yellow dim",
        }.get(status, "")
        text.append("  Status: ")
        text.append(f"{status}\n", style=status_style)

        blocked = data.get("blocked_reason", "")
        if blocked:
            text.append("  Blocked: ", style="red bold")
            text.append(f"{blocked}\n", style="red")

        # Agent activity (what the agent is currently doing)
        agent_activity = data.get("agent_activity", "")
        if agent_activity:
            text.append("  Activity: ", style="cyan bold")
            text.append(f"{agent_activity}\n", style="cyan italic")

        task_kind = data.get("task_kind", "")
        if task_kind:
            text.append(f"  Kind: {task_kind}\n")

        role_hint = data.get("role_hint", "")
        if role_hint:
            text.append(f"  Role hint: {role_hint}\n")

        agent_id = data.get("agent_id", "") or data.get("assigned_agent", "")
        if agent_id:
            text.append(f"  Agent: {agent_id}\n")
        model = data.get("model", "")
        if model:
            text.append(f"  Model: {model}\n")
        duration = data.get("duration", "")
        if duration:
            text.append(f"  Duration: {duration}\n")

        # Cost & tokens
        tokens = data.get("tokens_used", 0)
        cost = data.get("cost_usd", 0.0)
        if tokens or cost:
            text.append("  Tokens: ", style="bold")
            text.append(f"{tokens:,}", style="yellow")
            if cost:
                text.append(f" (${cost:.4f})", style="yellow")
            text.append("\n")

        # Attempts
        attempts = data.get("attempts", 0) or data.get("attempt_count", 0)
        if attempts:
            style = "yellow" if attempts > 1 else ""
            text.append(f"  Attempts: {attempts}\n", style=style)

        # Attempt history
        attempt_history = data.get("attempt_history", [])
        if attempt_history:
            text.append("\n  Attempt History:\n", style="yellow bold")
            for ah in attempt_history[-5:]:  # Show last 5
                attempt_num = ah.get("attempt", "?")
                error = ah.get("error", "")[:100]
                dur = ah.get("duration_s", 0)
                _ts = ah.get("timestamp", "")
                text.append(f"    #{attempt_num}", style="yellow")
                if dur:
                    text.append(f" ({dur:.1f}s)", style="dim")
                if error:
                    text.append(f" - {error}", style="red dim")
                text.append("\n")

        deps = data.get("deps", [])
        if deps:
            text.append(f"  Depends on: {', '.join(str(d) for d in deps)}\n")

        targets = data.get("target_files", [])
        if targets:
            text.append("\n  Target files:\n")
            for f in targets[:10]:
                text.append(f"    \u2022 {f}\n", style="dim")

        files_modified = data.get("files_modified", [])
        if files_modified:
            text.append("\n  Files modified:\n")
            for f in files_modified[:10]:
                text.append(f"    \u2022 {f}\n", style="green dim")

        # Prompt preview
        prompt = data.get("prompt_preview", "")
        if prompt:
            text.append("\n  Prompt (preview):\n", style="blue bold")
            text.append(f"  {prompt[:300]}\n", style="blue dim")

        desc = data.get("description", "") or data.get("result_summary", "")
        if desc and not prompt:
            text.append(f"\n  Description:\n  {desc[:300]}\n", style="dim italic")

        # Stderr if available
        stderr = data.get("stderr", "") or data.get("stderr_tail", "")
        if stderr:
            text.append("\n  Stderr:\n", style="red dim")
            text.append(f"    {stderr[-500:]}\n", style="red dim")

        # Action hints
        if status in ("failed", "skipped"):
            text.append("\n  Actions: ", style="bold")
            text.append("[r] Retry", style="cyan bold")
            text.append("  ", style="dim")
            text.append("[s] Skip", style="yellow bold")
            text.append("\n")
        elif status == "pending":
            text.append("\n  Actions: ", style="bold")
            text.append("[s] Skip", style="yellow bold")
            text.append("  ", style="dim")
            text.append("[e] Edit", style="blue bold")
            text.append("\n")
        elif status == "running":
            text.append("\n  Actions: ", style="bold")
            text.append("[s] Skip/Cancel", style="yellow bold")
            text.append("\n")
