"""Messages Log — shows orchestrator-worker inbox/outbox messages."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.widget import Widget
from textual.widgets import RichLog


class MessagesLog(Widget):
    """RichLog showing orchestrator-worker messages with direction arrows.

    Messages are color-coded by direction:
    - coordinator->agent: cyan
    - agent->coordinator: yellow
    """

    DEFAULT_CSS = """
    MessagesLog {
        height: 1fr;
    }
    MessagesLog > RichLog {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._seen_count: int = 0

    def compose(self):
        yield RichLog(id="messages-log", auto_scroll=True, markup=True)

    def update_messages(self, messages: list[dict[str, Any]]) -> None:
        """Append only new messages since last call."""
        if not messages:
            return
        new_messages = messages[self._seen_count:]
        if not new_messages:
            return
        self._seen_count = len(messages)

        try:
            log = self.query_one("#messages-log", RichLog)
        except Exception:
            return

        for msg in new_messages:
            direction = msg.get("direction", "")
            agent_id = msg.get("agent_id", "?")
            kind = msg.get("kind", "")
            task_id = msg.get("task_id", "")
            ts_raw = msg.get("timestamp", "")
            payload = msg.get("payload_preview", "")

            # Format timestamp
            epoch = self._to_epoch(ts_raw)
            if epoch:
                time_str = time.strftime("%H:%M:%S", time.localtime(epoch))
            else:
                time_str = "??:??:??"

            line = Text()
            line.append(f"{time_str} ", style="dim")

            if "coordinator" in direction and "agent" in direction.split("\u2192")[-1:]:
                # coordinator -> agent
                line.append(f"\u2192 {agent_id}", style="cyan bold")
            else:
                # agent -> coordinator
                line.append(f"\u2190 {agent_id}", style="yellow bold")

            line.append(f" [{kind}]", style="dim")
            if task_id:
                line.append(f" task:{task_id}", style="green dim")
            if payload:
                line.append(f" {payload[:120]}", style="dim italic")

            log.write(line)

    @staticmethod
    def _to_epoch(ts: Any) -> float:
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, str) and ts:
            try:
                from datetime import datetime
                return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0
        return 0.0
