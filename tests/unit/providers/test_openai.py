"""Tests for OpenAIProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from attocode.errors import ProviderError
from attocode.providers.openai import OpenAIProvider
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    ImageContentBlock,
    ImageSource,
    ImageSourceType,
    Message,
    MessageWithStructuredContent,
    Role,
    StopReason,
    TextContentBlock,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="sk-test-key")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestOpenAIProviderInit:
    def test_name(self, provider: OpenAIProvider) -> None:
        assert provider.name == "openai"

    def test_missing_api_key_raises(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
                OpenAIProvider(api_key="")

    def test_missing_api_key_no_env(self) -> None:
        env = {k: v for k, v in __import__("os").environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
                OpenAIProvider()


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------


class TestFormatMessages:
    def test_user_message(self, provider: OpenAIProvider) -> None:
        msgs = [Message(role=Role.USER, content="Hello")]
        result = provider._format_messages(msgs)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_system_message(self, provider: OpenAIProvider) -> None:
        msgs = [Message(role=Role.SYSTEM, content="You are helpful.")]
        result = provider._format_messages(msgs)
        assert result == [{"role": "system", "content": "You are helpful."}]

    def test_assistant_message_plain(self, provider: OpenAIProvider) -> None:
        msgs = [Message(role=Role.ASSISTANT, content="Sure!")]
        result = provider._format_messages(msgs)
        assert result == [{"role": "assistant", "content": "Sure!"}]

    def test_assistant_message_with_tool_calls(self, provider: OpenAIProvider) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "/tmp/x"})
        msgs = [Message(role=Role.ASSISTANT, content="", tool_calls=[tc])]
        result = provider._format_messages(msgs)

        assert len(result) == 1
        formatted = result[0]
        assert formatted["role"] == "assistant"
        assert formatted["content"] is None  # empty content becomes None
        assert len(formatted["tool_calls"]) == 1
        assert formatted["tool_calls"][0]["id"] == "tc_1"
        assert formatted["tool_calls"][0]["type"] == "function"
        assert formatted["tool_calls"][0]["function"]["name"] == "read_file"
        assert json.loads(formatted["tool_calls"][0]["function"]["arguments"]) == {"path": "/tmp/x"}

    def test_tool_message(self, provider: OpenAIProvider) -> None:
        msgs = [Message(role=Role.TOOL, content="file contents", tool_call_id="tc_1")]
        result = provider._format_messages(msgs)

        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["content"] == "file contents"
        assert result[0]["tool_call_id"] == "tc_1"

    def test_tool_message_no_call_id(self, provider: OpenAIProvider) -> None:
        msgs = [Message(role=Role.TOOL, content="result")]
        result = provider._format_messages(msgs)
        assert result[0]["tool_call_id"] == ""

    def test_mixed_conversation(self, provider: OpenAIProvider) -> None:
        msgs = [
            Message(role=Role.SYSTEM, content="Be helpful."),
            Message(role=Role.USER, content="Read a file."),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="tc_1", name="read_file", arguments={"path": "x"})],
            ),
            Message(role=Role.TOOL, content="contents", tool_call_id="tc_1"),
            Message(role=Role.ASSISTANT, content="Here is the file."),
        ]
        result = provider._format_messages(msgs)
        assert len(result) == 5
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert "tool_calls" in result[2]
        assert result[3]["role"] == "tool"
        assert result[4]["role"] == "assistant"


# ---------------------------------------------------------------------------
# _format_tool
# ---------------------------------------------------------------------------


class TestFormatTool:
    def test_format_tool_basic(self, provider: OpenAIProvider) -> None:
        tool = ToolDefinition(
            name="read_file",
            description="Read a file from disk",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        result = provider._format_tool(tool)

        assert result["type"] == "function"
        assert result["function"]["name"] == "read_file"
        assert result["function"]["description"] == "Read a file from disk"
        assert result["function"]["parameters"]["type"] == "object"
        assert "path" in result["function"]["parameters"]["properties"]

    def test_format_tool_empty_parameters(self, provider: OpenAIProvider) -> None:
        tool = ToolDefinition(
            name="list_files",
            description="List files",
            parameters={"type": "object", "properties": {}},
        )
        result = provider._format_tool(tool)
        assert result["function"]["parameters"] == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_valid_text_response(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [
                {
                    "message": {"content": "Hello there!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        result = provider._parse_response(data, "gpt-4o")

        assert result.content == "Hello there!"
        assert result.model == "gpt-4o"
        assert result.stop_reason == StopReason.END_TURN
        assert result.usage is not None
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5
        assert result.usage.total_tokens == 15
        assert result.tool_calls is None

    def test_empty_choices(self, provider: OpenAIProvider) -> None:
        data: dict = {"choices": []}
        result = provider._parse_response(data, "gpt-4o")

        assert result.content == ""
        assert result.model == "gpt-4o"
        assert result.stop_reason == StopReason.END_TURN

    def test_response_with_tool_calls(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/test.txt"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }
        result = provider._parse_response(data, "gpt-4o")

        assert result.content == ""
        assert result.stop_reason == StopReason.TOOL_USE
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_abc"
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].arguments == {"path": "/tmp/test.txt"}

    def test_response_with_multiple_tool_calls(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                            },
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": "grep", "arguments": '{"pattern": "TODO"}'},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        result = provider._parse_response(data, "gpt-4o")

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[1].name == "grep"

    def test_response_with_malformed_arguments(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "type": "function",
                                "function": {"name": "bash", "arguments": "not valid json{"},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
        }
        result = provider._parse_response(data, "gpt-4o")

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].arguments == {}  # falls back to empty dict

    def test_response_max_tokens_stop_reason(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [{"message": {"content": "partial..."}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 100, "total_tokens": 110},
        }
        result = provider._parse_response(data, "gpt-4o")
        assert result.stop_reason == StopReason.MAX_TOKENS

    def test_response_missing_usage(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
        }
        result = provider._parse_response(data, "gpt-4o")

        assert result.usage is not None
        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0

    def test_response_null_content(self, provider: OpenAIProvider) -> None:
        data = {
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
            "usage": {},
        }
        result = provider._parse_response(data, "gpt-4o")
        assert result.content == ""


# ---------------------------------------------------------------------------
# _format_content (image handling)
# ---------------------------------------------------------------------------


class TestFormatContent:
    def test_plain_string_passthrough(self, provider: OpenAIProvider) -> None:
        assert provider._format_content("hello") == "hello"

    def test_text_block(self, provider: OpenAIProvider) -> None:
        blocks = [TextContentBlock(text="hello")]
        result = provider._format_content(blocks)
        assert result == [{"type": "text", "text": "hello"}]

    def test_image_block_base64(self, provider: OpenAIProvider) -> None:
        source = ImageSource(type=ImageSourceType.BASE64, media_type="image/png", data="iVBORw0KGgo=")
        blocks = [ImageContentBlock(source=source)]
        result = provider._format_content(blocks)
        assert len(result) == 1
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="

    def test_image_block_url(self, provider: OpenAIProvider) -> None:
        source = ImageSource(type=ImageSourceType.URL, media_type="image/jpeg", data="https://example.com/img.jpg")
        blocks = [ImageContentBlock(source=source)]
        result = provider._format_content(blocks)
        assert len(result) == 1
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"] == "https://example.com/img.jpg"

    def test_mixed_text_and_image(self, provider: OpenAIProvider) -> None:
        source = ImageSource(type=ImageSourceType.BASE64, media_type="image/jpeg", data="abc123")
        blocks = [
            TextContentBlock(text="What is this?"),
            ImageContentBlock(source=source),
        ]
        result = provider._format_content(blocks)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "What is this?"}
        assert result[1]["type"] == "image_url"

    def test_structured_content_in_format_messages(self, provider: OpenAIProvider) -> None:
        source = ImageSource(type=ImageSourceType.BASE64, media_type="image/png", data="data==")
        msg = MessageWithStructuredContent(
            role=Role.USER,
            content=[TextContentBlock(text="Describe"), ImageContentBlock(source=source)],
        )
        result = provider._format_messages([msg])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
