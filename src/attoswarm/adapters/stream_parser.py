"""Stream-JSON parser for Claude CLI ``--output-format stream-json`` output.

Parses newline-delimited JSON events emitted by the Claude CLI in real time,
extracting structured tool-call data, text previews, cost/token usage, and
session metadata.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentActivityEvent:
    """A single structured event parsed from a Claude stream-json line."""

    timestamp: float
    task_id: str
    event_kind: str  # "tool_call" | "text" | "result" | "error"
    tool_name: str = ""
    tool_input_summary: str = ""  # first 200 chars of input
    text_preview: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0


def _summarize_input(tool_input: object) -> str:
    """Return a short summary of a tool_use input dict."""
    if isinstance(tool_input, str):
        return tool_input[:200]
    if isinstance(tool_input, dict):
        text = json.dumps(tool_input, ensure_ascii=False, default=str)
        return text[:200]
    return str(tool_input)[:200]


def parse_stream_json_line(line: str, task_id: str) -> AgentActivityEvent | None:
    """Parse a single stream-json line into an ``AgentActivityEvent``.

    Returns ``None`` for lines that are empty, not valid JSON, or contain
    event types we don't recognise (lenient — never crashes).
    """
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    event_type = data.get("type", "")
    now = time.time()

    # ── assistant events: contain content blocks ──────────────────────
    if event_type == "assistant":
        message = data.get("message", data)
        content_blocks = message.get("content", [])
        if not isinstance(content_blocks, list):
            return None

        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "tool_use":
                return AgentActivityEvent(
                    timestamp=now,
                    task_id=task_id,
                    event_kind="tool_call",
                    tool_name=block.get("name", ""),
                    tool_input_summary=_summarize_input(block.get("input", "")),
                )

            if block_type == "text":
                text = str(block.get("text", ""))
                if text.strip():
                    return AgentActivityEvent(
                        timestamp=now,
                        task_id=task_id,
                        event_kind="text",
                        text_preview=text[:200],
                    )

        return None

    # ── content_block_start: streaming tool_use start ─────────────────
    if event_type == "content_block_start":
        cb = data.get("content_block", {})
        if isinstance(cb, dict) and cb.get("type") == "tool_use":
            return AgentActivityEvent(
                timestamp=now,
                task_id=task_id,
                event_kind="tool_call",
                tool_name=cb.get("name", ""),
            )
        return None

    # ── result events: final cost/token summary ───────────────────────
    if event_type == "result":
        # data["result"] may be a text string (the final output) or a nested dict
        result_field = data.get("result", data)
        meta = result_field if isinstance(result_field, dict) else data
        usage = meta.get("usage", {}) or {}
        cost = meta.get("cost_usd", 0.0) or meta.get("cost", 0.0) or 0.0
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
        return AgentActivityEvent(
            timestamp=now,
            task_id=task_id,
            event_kind="result",
            tokens_used=input_tokens + output_tokens,
            cost_usd=float(cost),
        )

    # ── error events ──────────────────────────────────────────────────
    if event_type == "error":
        error_data = data.get("error", {})
        msg = error_data.get("message", str(error_data)) if isinstance(error_data, dict) else str(error_data)
        return AgentActivityEvent(
            timestamp=now,
            task_id=task_id,
            event_kind="error",
            text_preview=str(msg)[:200],
        )

    # Unknown event type — silently skip
    return None
