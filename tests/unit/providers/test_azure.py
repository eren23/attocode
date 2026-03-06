"""Tests for AzureOpenAIProvider."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from attocode.errors import ProviderError
from attocode.providers.azure import AzureConfig, AzureOpenAIProvider, _format_message, _parse_response
from attocode.types.messages import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


# ---------------------------------------------------------------------------
# AzureConfig
# ---------------------------------------------------------------------------


class TestAzureConfig:
    def test_from_env(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://my-resource.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "az-key-123",
            "AZURE_OPENAI_API_VERSION": "2024-08-01",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-deploy",
        }
        with patch.dict("os.environ", env, clear=False):
            config = AzureConfig.from_env()

        assert config.endpoint == "https://my-resource.openai.azure.com"
        assert config.api_key == "az-key-123"
        assert config.api_version == "2024-08-01"
        assert config.deployment == "gpt-4o-deploy"

    def test_from_env_defaults(self) -> None:
        env_clean = {
            k: v
            for k, v in __import__("os").environ.items()
            if not k.startswith("AZURE_OPENAI_")
        }
        with patch.dict("os.environ", env_clean, clear=True):
            config = AzureConfig.from_env()

        assert config.endpoint == ""
        assert config.api_key == ""
        assert config.api_version == "2024-06-01"
        assert config.deployment == ""

    def test_from_env_partial(self) -> None:
        env = {"AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com"}
        base = {k: v for k, v in __import__("os").environ.items() if not k.startswith("AZURE_OPENAI_")}
        base.update(env)
        with patch.dict("os.environ", base, clear=True):
            config = AzureConfig.from_env()

        assert config.endpoint == "https://example.openai.azure.com"
        assert config.api_key == ""


# ---------------------------------------------------------------------------
# AzureOpenAIProvider init
# ---------------------------------------------------------------------------


class TestAzureProviderInit:
    def test_name(self) -> None:
        config = AzureConfig(endpoint="https://x.openai.azure.com", api_key="key")
        provider = AzureOpenAIProvider(config=config)
        assert provider.name == "azure"

    def test_missing_endpoint_raises(self) -> None:
        config = AzureConfig(endpoint="", api_key="key")
        with pytest.raises(ProviderError, match="endpoint"):
            AzureOpenAIProvider(config=config)

    def test_missing_api_key_raises(self) -> None:
        config = AzureConfig(endpoint="https://x.openai.azure.com", api_key="")
        with pytest.raises(ProviderError, match="API key"):
            AzureOpenAIProvider(config=config)


# ---------------------------------------------------------------------------
# _format_message (module-level function)
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_user_message(self) -> None:
        msg = Message(role=Role.USER, content="Hello")
        result = _format_message(msg)
        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_system_message(self) -> None:
        msg = Message(role=Role.SYSTEM, content="System prompt")
        result = _format_message(msg)
        assert result["role"] == "system"
        assert result["content"] == "System prompt"

    def test_assistant_message(self) -> None:
        msg = Message(role=Role.ASSISTANT, content="Sure, I can help.")
        result = _format_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] == "Sure, I can help."

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "/tmp/x"})
        msg = Message(role=Role.ASSISTANT, content="Let me read that.", tool_calls=[tc])
        result = _format_message(msg)

        assert result["role"] == "assistant"
        assert result["content"] == "Let me read that."
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "tc_1"
        assert result["tool_calls"][0]["type"] == "function"
        assert result["tool_calls"][0]["function"]["name"] == "read_file"
        parsed_args = json.loads(result["tool_calls"][0]["function"]["arguments"])
        assert parsed_args == {"path": "/tmp/x"}

    def test_tool_message(self) -> None:
        msg = Message(role=Role.TOOL, content="file contents", tool_call_id="tc_1")
        result = _format_message(msg)
        assert result["role"] == "tool"
        assert result["content"] == "file contents"
        assert result["tool_call_id"] == "tc_1"

    def test_empty_content_not_included(self) -> None:
        msg = Message(role=Role.ASSISTANT, content="")
        result = _format_message(msg)
        assert result["role"] == "assistant"
        # Empty string is falsy, so content key should not be present
        assert "content" not in result


# ---------------------------------------------------------------------------
# _parse_response (module-level function)
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_valid_text_response(self) -> None:
        data = {
            "choices": [
                {"message": {"content": "Hello!"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "gpt-4o",
        }
        result = _parse_response(data)

        assert result.content == "Hello!"
        assert result.model == "gpt-4o"
        assert result.usage is not None
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5

    def test_tool_calls_finish_reason(self) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command": "ls"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "model": "gpt-4o",
        }
        result = _parse_response(data)

        assert result.stop_reason == StopReason.TOOL_USE
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "bash"
        assert result.tool_calls[0].arguments == {"command": "ls"}

    def test_max_tokens_finish_reason(self) -> None:
        data = {
            "choices": [
                {"message": {"content": "partial"}, "finish_reason": "length"}
            ],
            "usage": {},
            "model": "gpt-4o",
        }
        result = _parse_response(data)
        assert result.stop_reason == StopReason.MAX_TOKENS

    def test_stop_finish_reason(self) -> None:
        data = {
            "choices": [
                {"message": {"content": "done"}, "finish_reason": "stop"}
            ],
            "usage": {},
            "model": "gpt-4o",
        }
        result = _parse_response(data)
        # "stop" finish_reason maps to the default StopReason.END_TURN
        assert result.stop_reason == StopReason.END_TURN
        assert result.content == "done"

    def test_malformed_tool_arguments(self) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "function": {"name": "bash", "arguments": "not json"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
            "model": "gpt-4o",
        }
        result = _parse_response(data)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].arguments == {"raw": "not json"}

    def test_empty_choices(self) -> None:
        data = {"choices": [{}], "usage": {}, "model": "gpt-4o"}
        result = _parse_response(data)
        # Empty content string is converted to None via `content or None`
        assert result.content is None
        assert result.tool_calls == []

    def test_missing_usage(self) -> None:
        data = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "model": "gpt-4o",
        }
        result = _parse_response(data)
        assert result.usage is not None
        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0

    def test_multiple_tool_calls(self) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                            },
                            {
                                "id": "call_2",
                                "function": {"name": "grep", "arguments": '{"pattern": "def"}'},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "gpt-4o",
        }
        result = _parse_response(data)
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[1].name == "grep"
