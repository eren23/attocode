"""Tests for OpenRouterProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from attocode.errors import ProviderError
from attocode.providers.openrouter import OpenRouterPreferences, OpenRouterProvider
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
def provider() -> OpenRouterProvider:
    return OpenRouterProvider(api_key="or-test-key")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestOpenRouterProviderInit:
    def test_name(self, provider: OpenRouterProvider) -> None:
        assert provider.name == "openrouter"

    def test_missing_api_key_raises(self) -> None:
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False):
            with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
                OpenRouterProvider(api_key="")

    def test_missing_api_key_no_env(self) -> None:
        env = {k: v for k, v in __import__("os").environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
                OpenRouterProvider()


# ---------------------------------------------------------------------------
# HTTP headers
# ---------------------------------------------------------------------------


class TestOpenRouterHeaders:
    def test_headers_include_x_title(self, provider: OpenRouterProvider) -> None:
        client = provider._ensure_client()
        assert client.headers.get("X-Title") == "attocode"

    def test_headers_include_http_referer(self, provider: OpenRouterProvider) -> None:
        client = provider._ensure_client()
        assert "github.com" in client.headers.get("HTTP-Referer", "")

    def test_headers_include_authorization(self, provider: OpenRouterProvider) -> None:
        client = provider._ensure_client()
        assert client.headers.get("Authorization") == "Bearer or-test-key"

    def test_custom_app_name(self) -> None:
        p = OpenRouterProvider(api_key="or-key", app_name="my-custom-app")
        client = p._ensure_client()
        assert client.headers.get("X-Title") == "my-custom-app"
        assert "my-custom-app" in client.headers.get("HTTP-Referer", "")


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------


class TestFormatMessages:
    def test_user_message(self, provider: OpenRouterProvider) -> None:
        msgs = [Message(role=Role.USER, content="Hello")]
        result = provider._format_messages(msgs)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_system_message(self, provider: OpenRouterProvider) -> None:
        msgs = [Message(role=Role.SYSTEM, content="Be concise.")]
        result = provider._format_messages(msgs)
        assert result == [{"role": "system", "content": "Be concise."}]

    def test_assistant_message_with_tool_calls(self, provider: OpenRouterProvider) -> None:
        tc = ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})
        msgs = [Message(role=Role.ASSISTANT, content="", tool_calls=[tc])]
        result = provider._format_messages(msgs)

        assert len(result) == 1
        formatted = result[0]
        assert formatted["role"] == "assistant"
        assert formatted["content"] is None
        assert len(formatted["tool_calls"]) == 1
        assert formatted["tool_calls"][0]["id"] == "tc_1"
        assert formatted["tool_calls"][0]["function"]["name"] == "bash"
        parsed_args = json.loads(formatted["tool_calls"][0]["function"]["arguments"])
        assert parsed_args == {"command": "ls"}

    def test_tool_message(self, provider: OpenRouterProvider) -> None:
        msgs = [Message(role=Role.TOOL, content="output", tool_call_id="tc_1")]
        result = provider._format_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["content"] == "output"
        assert result[0]["tool_call_id"] == "tc_1"

    def test_tool_message_missing_call_id(self, provider: OpenRouterProvider) -> None:
        msgs = [Message(role=Role.TOOL, content="data")]
        result = provider._format_messages(msgs)
        assert result[0]["tool_call_id"] == ""


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_valid_text_response(self, provider: OpenRouterProvider) -> None:
        data = {
            "choices": [
                {"message": {"content": "Hello!"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
        }
        result = provider._parse_response(data, "anthropic/claude-sonnet-4")
        assert result.content == "Hello!"
        assert result.model == "anthropic/claude-sonnet-4"
        assert result.stop_reason == StopReason.END_TURN
        assert result.usage is not None
        assert result.usage.input_tokens == 8
        assert result.usage.output_tokens == 3

    def test_empty_choices(self, provider: OpenRouterProvider) -> None:
        data: dict = {"choices": []}
        result = provider._parse_response(data, "meta/llama-3-70b")
        assert result.content == ""
        assert result.stop_reason == StopReason.END_TURN

    def test_response_with_tool_calls(self, provider: OpenRouterProvider) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_xyz",
                                "type": "function",
                                "function": {
                                    "name": "glob",
                                    "arguments": '{"pattern": "*.py"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23},
        }
        result = provider._parse_response(data, "openai/gpt-4o")
        assert result.stop_reason == StopReason.TOOL_USE
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "glob"
        assert result.tool_calls[0].arguments == {"pattern": "*.py"}

    def test_max_tokens_stop_reason(self, provider: OpenRouterProvider) -> None:
        data = {
            "choices": [{"message": {"content": "cut off"}, "finish_reason": "length"}],
            "usage": {},
        }
        result = provider._parse_response(data, "model")
        assert result.stop_reason == StopReason.MAX_TOKENS

    def test_malformed_tool_arguments(self, provider: OpenRouterProvider) -> None:
        data = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "type": "function",
                                "function": {"name": "bash", "arguments": "{broken json"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
        }
        result = provider._parse_response(data, "model")
        assert result.tool_calls is not None
        assert result.tool_calls[0].arguments == {}

    def test_null_content_in_message(self, provider: OpenRouterProvider) -> None:
        data = {
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
            "usage": {},
        }
        result = provider._parse_response(data, "model")
        assert result.content == ""

    def test_missing_usage(self, provider: OpenRouterProvider) -> None:
        data = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        }
        result = provider._parse_response(data, "model")
        assert result.usage is not None
        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0
        assert result.usage.total_tokens == 0


# ---------------------------------------------------------------------------
# _format_content (image handling)
# ---------------------------------------------------------------------------


class TestFormatContent:
    def test_plain_string_passthrough(self, provider: OpenRouterProvider) -> None:
        assert provider._format_content("hello") == "hello"

    def test_text_block(self, provider: OpenRouterProvider) -> None:
        blocks = [TextContentBlock(text="hello")]
        result = provider._format_content(blocks)
        assert result == [{"type": "text", "text": "hello"}]

    def test_image_block_base64(self, provider: OpenRouterProvider) -> None:
        source = ImageSource(type=ImageSourceType.BASE64, media_type="image/png", data="iVBORw0KGgo=")
        blocks = [ImageContentBlock(source=source)]
        result = provider._format_content(blocks)
        assert len(result) == 1
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="

    def test_image_block_url(self, provider: OpenRouterProvider) -> None:
        source = ImageSource(type=ImageSourceType.URL, media_type="image/jpeg", data="https://example.com/img.jpg")
        blocks = [ImageContentBlock(source=source)]
        result = provider._format_content(blocks)
        assert len(result) == 1
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"] == "https://example.com/img.jpg"

    def test_mixed_text_and_image(self, provider: OpenRouterProvider) -> None:
        source = ImageSource(type=ImageSourceType.BASE64, media_type="image/jpeg", data="abc123")
        blocks = [
            TextContentBlock(text="Look at this:"),
            ImageContentBlock(source=source),
        ]
        result = provider._format_content(blocks)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "Look at this:"}
        assert result[1]["type"] == "image_url"

    def test_structured_content_in_format_messages(self, provider: OpenRouterProvider) -> None:
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


# ---------------------------------------------------------------------------
# OpenRouterPreferences
# ---------------------------------------------------------------------------


class TestOpenRouterPreferences:
    def test_default_preferences_empty_dict(self) -> None:
        prefs = OpenRouterPreferences()
        assert prefs.to_dict() == {}

    def test_order_serialization(self) -> None:
        prefs = OpenRouterPreferences(order=["anthropic", "openai"])
        d = prefs.to_dict()
        assert d == {"order": ["anthropic", "openai"]}

    def test_only_and_ignore(self) -> None:
        prefs = OpenRouterPreferences(only=["anthropic"], ignore=["openai"])
        d = prefs.to_dict()
        assert d["only"] == ["anthropic"]
        assert d["ignore"] == ["openai"]

    def test_allow_fallbacks_false(self) -> None:
        prefs = OpenRouterPreferences(allow_fallbacks=False)
        d = prefs.to_dict()
        assert d["allow_fallbacks"] is False

    def test_allow_fallbacks_true_omitted(self) -> None:
        prefs = OpenRouterPreferences(allow_fallbacks=True)
        assert "allow_fallbacks" not in prefs.to_dict()

    def test_sort_and_quantizations(self) -> None:
        prefs = OpenRouterPreferences(sort="price", quantizations=["bf16", "fp16"])
        d = prefs.to_dict()
        assert d["sort"] == "price"
        assert d["quantizations"] == ["bf16", "fp16"]

    def test_max_price(self) -> None:
        prefs = OpenRouterPreferences(max_price={"prompt": 5.0, "completion": 15.0})
        d = prefs.to_dict()
        assert d["max_price"] == {"prompt": 5.0, "completion": 15.0}

    def test_data_collection(self) -> None:
        prefs = OpenRouterPreferences(data_collection="deny")
        assert prefs.to_dict()["data_collection"] == "deny"

    def test_require_parameters(self) -> None:
        prefs = OpenRouterPreferences(require_parameters=True)
        assert prefs.to_dict()["require_parameters"] is True

    def test_full_preferences(self) -> None:
        prefs = OpenRouterPreferences(
            order=["anthropic"],
            allow_fallbacks=False,
            sort="throughput",
            data_collection="deny",
        )
        d = prefs.to_dict()
        assert d == {
            "order": ["anthropic"],
            "allow_fallbacks": False,
            "sort": "throughput",
            "data_collection": "deny",
        }


# ---------------------------------------------------------------------------
# Preferences injection into request body
# ---------------------------------------------------------------------------


class TestPreferencesInjection:
    def test_no_preferences_no_provider_key(self, provider: OpenRouterProvider) -> None:
        body: dict = {"model": "test", "messages": []}
        provider._inject_preferences(body)
        assert "provider" not in body

    def test_preferences_injected(self) -> None:
        prefs = OpenRouterPreferences(order=["anthropic"], sort="price")
        p = OpenRouterProvider(api_key="or-test-key", preferences=prefs)
        body: dict = {"model": "test", "messages": []}
        p._inject_preferences(body)
        assert body["provider"] == {"order": ["anthropic"], "sort": "price"}

    def test_empty_preferences_not_injected(self) -> None:
        prefs = OpenRouterPreferences()  # all defaults
        p = OpenRouterProvider(api_key="or-test-key", preferences=prefs)
        body: dict = {"model": "test", "messages": []}
        p._inject_preferences(body)
        assert "provider" not in body
