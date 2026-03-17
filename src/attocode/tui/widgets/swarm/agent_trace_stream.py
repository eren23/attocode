"""Per-agent trace stream widget for swarm TUI.

Displays a live stream of trace entries (tool calls, LLM requests,
file writes, etc.) with color-coded entry types and cost tracking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.widgets import RichLog


_ENTRY_TYPE_STYLES: dict[str, str] = {
    "tool_call": "cyan",
    "llm_request": "blue",
    "llm_response": "green",
    "cost_delta": "yellow",
    "reasoning": "dim",
    "file_write": "magenta",
    "error": "red bold",
}


class AgentTraceStream(RichLog):
    """RichLog-based widget showing per-agent trace entries."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self._trace_path: Path | None = None
        self._last_offset: int = 0
        self._total_cost: float = 0.0

    def set_trace_path(self, path: str | Path) -> None:
        """Set the path to the agent's .trace.jsonl file."""
        self._trace_path = Path(path)
        self._last_offset = 0
        self._total_cost = 0.0
        self.clear()

    def poll_new_entries(self) -> None:
        """Read new entries from the trace file since last poll."""
        if not self._trace_path or not self._trace_path.exists():
            return

        try:
            size = self._trace_path.stat().st_size
            if size <= self._last_offset:
                return

            with self._trace_path.open("rb") as f:
                f.seek(self._last_offset)
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._render_entry(entry)
                self._last_offset = f.tell()
        except Exception:
            pass

    def _render_entry(self, entry: dict[str, Any]) -> None:
        """Render a single trace entry."""
        entry_type = entry.get("entry_type", "")
        style = _ENTRY_TYPE_STYLES.get(entry_type, "white")
        data = entry.get("data", {})

        text = Text()

        # Timestamp (last 8 chars of ISO or epoch)
        ts = entry.get("timestamp", "")
        if isinstance(ts, (int, float)):
            import time
            ts_str = time.strftime("%H:%M:%S", time.localtime(ts))
        else:
            ts_str = str(ts)[-8:]
        text.append(f"[{ts_str}] ", style="dim")

        # Entry type badge
        text.append(f"{entry_type:<12} ", style=style)

        # Entry-specific content
        if entry_type == "tool_call":
            tool = data.get("tool", "")
            text.append(f"{tool}", style="bold")
        elif entry_type == "llm_request":
            tokens = data.get("input_tokens", 0)
            text.append(f"tokens={tokens}", style="dim")
        elif entry_type == "llm_response":
            tokens = data.get("output_tokens", 0)
            text.append(f"tokens={tokens}", style="dim")
        elif entry_type == "cost_delta":
            cost = data.get("cost_usd", 0.0)
            self._total_cost += cost
            text.append(f"${cost:.4f} (total: ${self._total_cost:.4f})", style="yellow")
        elif entry_type == "file_write":
            path = data.get("path", "")
            text.append(f"{path}", style="magenta")
        elif entry_type == "error":
            msg = data.get("message", str(data))[:80]
            text.append(f"{msg}", style="red")
        else:
            # Generic fallback
            preview = str(data)[:60]
            text.append(preview, style="dim")

        self.write(text)
