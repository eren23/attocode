"""Tests for codex JSONL output parsing (cli._unwrap_codex_jsonl & CodexAdapter._parse_stdout_line)."""

from __future__ import annotations

import json

import pytest

from attoswarm.cli import _unwrap_codex_jsonl
from attoswarm.adapters.codex import CodexAdapter
from attoswarm.adapters.stream_parser import parse_backend_stream_line


# ── _unwrap_codex_jsonl ──────────────────────────────────────────────


REALISTIC_JSONL = "\n".join([
    '{"type":"thread.started","thread_id":"thread_abc123"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"[{\\"task_id\\":\\"t1\\",\\"title\\":\\"Setup\\",\\"description\\":\\"init project\\",\\"deps\\":[]},{\\"task_id\\":\\"t2\\",\\"title\\":\\"Implement\\",\\"description\\":\\"build feature\\",\\"deps\\":[\\"t1\\"]}]"}}',
    '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":50}}',
])


def test_extracts_agent_message():
    result = _unwrap_codex_jsonl(REALISTIC_JSONL)
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["task_id"] == "t1"


def test_multiple_messages_returns_last():
    lines = "\n".join([
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"first response"}}',
        '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"second response"}}',
    ])
    assert _unwrap_codex_jsonl(lines) == "second response"


def test_no_matching_events_returns_raw():
    raw = '{"type":"thread.started","thread_id":"abc"}\n{"type":"turn.started"}'
    assert _unwrap_codex_jsonl(raw) == raw


def test_legacy_status_format():
    raw = '{"status":"completed","message":"legacy output"}'
    assert _unwrap_codex_jsonl(raw) == "legacy output"


def test_non_json_lines_skipped():
    lines = "some random text\n{bad json\n" + REALISTIC_JSONL
    result = _unwrap_codex_jsonl(lines)
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 2


def test_empty_input():
    assert _unwrap_codex_jsonl("") == ""


# ── CodexAdapter._parse_stdout_line ──────────────────────────────────


@pytest.fixture
def adapter():
    return CodexAdapter()


def test_item_completed_agent_message(adapter: CodexAdapter):
    line = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "hello world"},
    })
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "log"
    assert result["payload"]["event_kind"] == "agent_message"
    assert result["payload"]["message"] == "hello world"


def test_item_completed_other_type(adapter: CodexAdapter):
    line = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_0", "type": "tool_call", "name": "read_file"},
    })
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "log"
    assert result["payload"]["event_kind"] == "progress"


def test_turn_completed_extracts_tokens(adapter: CodexAdapter):
    line = json.dumps({
        "type": "turn.completed",
        "usage": {"input_tokens": 500, "cached_input_tokens": 100, "output_tokens": 200},
    })
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "log"
    usage = result["payload"]["token_usage"]
    assert usage["total"] == 700
    assert usage["input"] == 500
    assert usage["output"] == 200
    assert usage["cached_input"] == 100


def test_thread_started(adapter: CodexAdapter):
    line = json.dumps({"type": "thread.started", "thread_id": "thread_xyz"})
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "log"
    assert result["payload"]["thread_id"] == "thread_xyz"


def test_turn_started(adapter: CodexAdapter):
    line = json.dumps({"type": "turn.started"})
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "log"
    assert result["payload"]["event_kind"] == "progress"


def test_legacy_completed(adapter: CodexAdapter):
    line = json.dumps({"status": "completed", "message": "done"})
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "task_done"
    assert result["payload"]["message"] == "done"


def test_legacy_error(adapter: CodexAdapter):
    line = json.dumps({"status": "error", "error": "something broke"})
    result = adapter._parse_stdout_line(line)
    assert result["type"] == "task_failed"
    assert result["payload"]["message"] == "something broke"


def test_heartbeat_markers_pass_through(adapter: CodexAdapter):
    """[TASK_DONE] and [TASK_FAILED] markers are handled by base class."""
    done = adapter._parse_stdout_line("[TASK_DONE] finished")
    assert done["type"] == "task_done"

    failed = adapter._parse_stdout_line("[TASK_FAILED] oops")
    assert failed["type"] == "task_failed"


def test_plain_text_falls_through(adapter: CodexAdapter):
    result = adapter._parse_stdout_line("just some plain text")
    assert result["type"] == "log"
    assert result["payload"]["event_kind"] == "progress"


def test_unknown_json_falls_through(adapter: CodexAdapter):
    line = json.dumps({"some": "unknown", "json": "object"})
    result = adapter._parse_stdout_line(line)
    # Base class handles unknown JSON via generic protocol
    assert result["type"] == "log"


def test_parse_backend_stream_line_codex_agent_message():
    line = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "thinking about repo"},
    })
    event = parse_backend_stream_line("codex", line, "t1")
    assert event is not None
    assert event.event_kind == "text"
    assert event.text_preview == "thinking about repo"


def test_parse_backend_stream_line_codex_turn_completed():
    line = json.dumps({
        "type": "turn.completed",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    })
    event = parse_backend_stream_line("codex", line, "t1")
    assert event is not None
    assert event.event_kind == "result"
    assert event.tokens_used == 20
