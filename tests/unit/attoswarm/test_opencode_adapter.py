"""Tests for OpencodeAdapter JSONL parsing, command building, and registry."""

from __future__ import annotations

import json

from attoswarm.adapters.base import SubprocessAdapter
from attoswarm.adapters.opencode import OpencodeAdapter


def _adapter() -> OpencodeAdapter:
    return OpencodeAdapter()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestOpencodeAdapterInit:
    def test_backend_is_opencode(self) -> None:
        assert _adapter()._backend == "opencode"

    def test_is_subprocess_adapter(self) -> None:
        assert isinstance(_adapter(), SubprocessAdapter)


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_minimal_command(self) -> None:
        cmd = OpencodeAdapter.build_command()
        assert cmd == ["opencode", "run", "--format", "json"]

    def test_with_model(self) -> None:
        cmd = OpencodeAdapter.build_command(model="gpt-4o")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "gpt-4o"
        assert "--format" in cmd

    def test_with_prompt(self) -> None:
        cmd = OpencodeAdapter.build_command(prompt="do stuff")
        assert cmd[-1] == "do stuff"
        assert "--format" in cmd

    def test_with_model_and_prompt(self) -> None:
        cmd = OpencodeAdapter.build_command(model="o3", prompt="hello")
        assert cmd == ["opencode", "run", "--model", "o3", "--format", "json", "hello"]

    def test_empty_model_omits_flag(self) -> None:
        cmd = OpencodeAdapter.build_command(model="")
        assert "--model" not in cmd

    def test_empty_prompt_omits_arg(self) -> None:
        cmd = OpencodeAdapter.build_command(prompt="")
        assert cmd[-1] == "json"


# ---------------------------------------------------------------------------
# _parse_stdout_line — step_finish events
# ---------------------------------------------------------------------------


class TestParseStdoutLineStepFinish:
    def test_extracts_token_usage(self) -> None:
        adapter = _adapter()
        line = json.dumps({
            "type": "step_finish",
            "part": {
                "tokens": {
                    "input": 100,
                    "output": 50,
                    "reasoning": 10,
                    "cache": {"read": 20, "write": 5},
                },
                "cost": 0.03,
            },
        })
        parsed = adapter._parse_stdout_line(line)
        assert parsed["type"] == "log"
        assert parsed["payload"]["event_kind"] == "step_finish"
        assert parsed["payload"]["backend"] == "opencode"
        assert parsed["token_usage"]["total"] == 160
        assert parsed["token_usage"]["input"] == 100
        assert parsed["token_usage"]["output"] == 50
        assert parsed["token_usage"]["reasoning"] == 10
        assert parsed["token_usage"]["cached_read"] == 20
        assert parsed["token_usage"]["cached_write"] == 5
        assert parsed["cost_usd"] == 0.03

    def test_missing_tokens_key(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "step_finish", "part": {}})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["token_usage"] is None
        assert parsed["cost_usd"] is None

    def test_missing_cache(self) -> None:
        adapter = _adapter()
        line = json.dumps({
            "type": "step_finish",
            "part": {"tokens": {"input": 50, "output": 25, "reasoning": 0}},
        })
        parsed = adapter._parse_stdout_line(line)
        assert parsed["token_usage"]["cached_read"] == 0
        assert parsed["token_usage"]["cached_write"] == 0
        assert parsed["token_usage"]["total"] == 75

    def test_cache_not_dict(self) -> None:
        adapter = _adapter()
        line = json.dumps({
            "type": "step_finish",
            "part": {"tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": "invalid"}},
        })
        parsed = adapter._parse_stdout_line(line)
        assert parsed["token_usage"]["cached_read"] == 0
        assert parsed["token_usage"]["cached_write"] == 0

    def test_cost_integer(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "step_finish", "part": {"cost": 1}})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["cost_usd"] == 1.0
        assert isinstance(parsed["cost_usd"], float)

    def test_cost_not_number(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "step_finish", "part": {"cost": "expensive"}})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["cost_usd"] is None

    def test_part_not_dict(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "step_finish", "part": "string"})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["token_usage"] is None
        assert parsed["cost_usd"] is None

    def test_no_part(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "step_finish"})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["token_usage"] is None
        assert parsed["cost_usd"] is None


# ---------------------------------------------------------------------------
# _parse_stdout_line — text events
# ---------------------------------------------------------------------------


class TestParseStdoutLineText:
    def test_extracts_message(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "text", "part": {"text": "Hello world"}})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["type"] == "log"
        assert parsed["payload"]["event_kind"] == "text"
        assert parsed["payload"]["message"] == "Hello world"

    def test_empty_text(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "text", "part": {"text": ""}})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["payload"]["message"] == ""

    def test_part_not_dict(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "text", "part": "raw"})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["payload"]["message"] == ""

    def test_missing_part(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "text"})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["payload"]["message"] == ""


# ---------------------------------------------------------------------------
# _parse_stdout_line — step_start events
# ---------------------------------------------------------------------------


class TestParseStdoutLineStepStart:
    def test_step_start_event(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "step_start", "part": {}})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["type"] == "log"
        assert parsed["payload"]["event_kind"] == "step_start"
        assert parsed["payload"]["backend"] == "opencode"


# ---------------------------------------------------------------------------
# _parse_stdout_line — delegation to super()
# ---------------------------------------------------------------------------


class TestParseStdoutLineDelegation:
    def test_plain_text_delegates(self) -> None:
        adapter = _adapter()
        parsed = adapter._parse_stdout_line("some plain log line")
        assert parsed["type"] == "log"
        assert parsed["payload"]["backend"] == "opencode"

    def test_invalid_json_delegates(self) -> None:
        adapter = _adapter()
        parsed = adapter._parse_stdout_line("{not valid json}")
        assert parsed["type"] == "log"  # no crash

    def test_non_dict_json_delegates(self) -> None:
        adapter = _adapter()
        parsed = adapter._parse_stdout_line("[1, 2, 3]")
        assert parsed["type"] == "log"

    def test_unrecognized_event_delegates(self) -> None:
        adapter = _adapter()
        line = json.dumps({"type": "unknown_event", "data": "x"})
        parsed = adapter._parse_stdout_line(line)
        assert parsed["type"] == "log"

    def test_whitespace_around_json(self) -> None:
        adapter = _adapter()
        line = '  {"type":"step_start","part":{}}  '
        parsed = adapter._parse_stdout_line(line)
        assert parsed["payload"]["event_kind"] == "step_start"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistryOpencode:
    def test_returns_opencode_adapter(self) -> None:
        from attoswarm.adapters.registry import get_adapter

        adapter = get_adapter("opencode")
        assert isinstance(adapter, OpencodeAdapter)

    def test_case_insensitive(self) -> None:
        from attoswarm.adapters.registry import get_adapter

        adapter = get_adapter("OpenCode")
        assert isinstance(adapter, OpencodeAdapter)
