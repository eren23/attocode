"""Tests for provider adapter bridge module."""

from __future__ import annotations

import asyncio
import json

import pytest

from attocode.adapters import (
    MessageFormatAdapter,
    ToolFormatConverter,
    create_tui_approval_bridge,
    create_tui_budget_bridge,
    create_tui_learning_bridge,
)
from attocode.tools.base import ToolSpec
from attocode.types.messages import DangerLevel


def _make_tool_spec(name: str = "test_tool", desc: str = "A test tool") -> ToolSpec:
    return ToolSpec(
        name=name,
        description=desc,
        parameters={"type": "object", "properties": {"arg1": {"type": "string"}}},
        danger_level=DangerLevel.SAFE,
    )


class TestToolFormatConverterToAnthropic:
    def test_single_tool(self) -> None:
        tools = [_make_tool_spec()]
        result = ToolFormatConverter.to_anthropic(tools)
        assert len(result) == 1
        assert result[0]["name"] == "test_tool"
        assert result[0]["description"] == "A test tool"
        assert "input_schema" in result[0]

    def test_empty_list(self) -> None:
        assert ToolFormatConverter.to_anthropic([]) == []

    def test_multiple_tools(self) -> None:
        tools = [_make_tool_spec("a"), _make_tool_spec("b")]
        result = ToolFormatConverter.to_anthropic(tools)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"


class TestToolFormatConverterToOpenAI:
    def test_single_tool(self) -> None:
        tools = [_make_tool_spec()]
        result = ToolFormatConverter.to_openai(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        func = result[0]["function"]
        assert func["name"] == "test_tool"
        assert func["description"] == "A test tool"
        assert "parameters" in func

    def test_empty_list(self) -> None:
        assert ToolFormatConverter.to_openai([]) == []


class TestToolFormatConverterRoundTrip:
    def test_anthropic_round_trip(self) -> None:
        original = [_make_tool_spec("my_tool", "does stuff")]
        converted = ToolFormatConverter.to_anthropic(original)
        restored = ToolFormatConverter.from_anthropic(converted)
        assert len(restored) == 1
        assert restored[0].name == "my_tool"
        assert restored[0].description == "does stuff"
        assert restored[0].parameters == original[0].parameters

    def test_openai_round_trip(self) -> None:
        original = [_make_tool_spec("my_tool", "does stuff")]
        converted = ToolFormatConverter.to_openai(original)
        restored = ToolFormatConverter.from_openai(converted)
        assert len(restored) == 1
        assert restored[0].name == "my_tool"
        assert restored[0].description == "does stuff"
        assert restored[0].parameters == original[0].parameters


class TestMessageFormatAdapter:
    def test_parse_tool_call_arguments_dict(self) -> None:
        result = MessageFormatAdapter.parse_tool_call_arguments({"key": "value"})
        assert result == {"key": "value"}

    def test_parse_tool_call_arguments_json_string(self) -> None:
        result = MessageFormatAdapter.parse_tool_call_arguments('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_tool_call_arguments_empty_string(self) -> None:
        result = MessageFormatAdapter.parse_tool_call_arguments("")
        assert result == {}

    def test_parse_tool_call_arguments_invalid_json(self) -> None:
        result = MessageFormatAdapter.parse_tool_call_arguments("not json")
        assert result == {}

    def test_parse_tool_call_arguments_non_dict_json(self) -> None:
        result = MessageFormatAdapter.parse_tool_call_arguments("[1, 2, 3]")
        assert result == {"value": [1, 2, 3]}

    def test_to_anthropic_messages_basic(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        result = MessageFormatAdapter.to_anthropic_messages(messages)
        assert result == [{"role": "user", "content": "hello"}]

    def test_to_anthropic_messages_tool_result(self) -> None:
        messages = [{"role": "tool", "content": "result", "tool_call_id": "tc-1"}]
        result = MessageFormatAdapter.to_anthropic_messages(messages)
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "tc-1"

    def test_to_openai_messages_tool_result(self) -> None:
        messages = [{"role": "tool", "content": "result", "tool_call_id": "tc-1"}]
        result = MessageFormatAdapter.to_openai_messages(messages)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc-1"

    def test_to_openai_messages_assistant_tool_calls(self) -> None:
        messages = [{
            "role": "assistant",
            "content": "thinking...",
            "tool_calls": [
                {"id": "tc-1", "name": "bash", "arguments": {"command": "ls"}},
            ],
        }]
        result = MessageFormatAdapter.to_openai_messages(messages)
        assert result[0]["role"] == "assistant"
        assert len(result[0]["tool_calls"]) == 1
        tc = result[0]["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "bash"
        # OpenAI serializes arguments as JSON string
        assert json.loads(tc["function"]["arguments"]) == {"command": "ls"}


class TestTUIBridgeFactories:
    @pytest.mark.asyncio
    async def test_approval_bridge_approved(self) -> None:
        async def callback(tool_name: str, args: dict, danger: str) -> bool:
            return True

        bridge = create_tui_approval_bridge(callback)
        result = await bridge.request_approval("bash", {"cmd": "ls"})
        assert result is True

    @pytest.mark.asyncio
    async def test_approval_bridge_denied(self) -> None:
        async def callback(tool_name: str, args: dict, danger: str) -> bool:
            return False

        bridge = create_tui_approval_bridge(callback)
        result = await bridge.request_approval("bash", {"cmd": "rm -rf /"})
        assert result is False

    @pytest.mark.asyncio
    async def test_approval_bridge_timeout(self) -> None:
        async def callback(tool_name: str, args: dict, danger: str) -> bool:
            await asyncio.sleep(10)
            return True

        bridge = create_tui_approval_bridge(callback, timeout=0.05)
        result = await bridge.request_approval("bash", {})
        assert result is False  # fail-safe default

    @pytest.mark.asyncio
    async def test_budget_bridge_approved(self) -> None:
        async def callback(current: int, max_t: int, requested: int, reason: str) -> bool:
            return True

        bridge = create_tui_budget_bridge(callback)
        result = await bridge.request_extension(500_000, 1_000_000, 200_000)
        assert result is True

    @pytest.mark.asyncio
    async def test_budget_bridge_timeout(self) -> None:
        async def callback(current: int, max_t: int, requested: int, reason: str) -> bool:
            await asyncio.sleep(10)
            return True

        bridge = create_tui_budget_bridge(callback, timeout=0.05)
        result = await bridge.request_extension(0, 0, 0)
        assert result is False  # fail-safe default

    @pytest.mark.asyncio
    async def test_learning_bridge_approve(self) -> None:
        async def callback(learning: dict) -> str:
            return "approve"

        bridge = create_tui_learning_bridge(callback)
        result = await bridge.validate_learning({"rule": "always test"})
        assert result == "approve"

    @pytest.mark.asyncio
    async def test_learning_bridge_invalid_result_defaults_to_skip(self) -> None:
        async def callback(learning: dict) -> str:
            return "invalid_value"

        bridge = create_tui_learning_bridge(callback)
        result = await bridge.validate_learning({})
        assert result == "skip"

    @pytest.mark.asyncio
    async def test_learning_bridge_timeout(self) -> None:
        async def callback(learning: dict) -> str:
            await asyncio.sleep(10)
            return "approve"

        bridge = create_tui_learning_bridge(callback, timeout=0.05)
        result = await bridge.validate_learning({})
        assert result == "skip"  # fail-safe default
