"""Provider adapter bridge module.

Provides format converters between internal tool/message representations
and provider-specific API formats (Anthropic, OpenAI), plus async TUI
bridge protocols with timeout-based fail-safe defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol, runtime_checkable

from attocode.tools.base import ToolSpec
from attocode.types.messages import DangerLevel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool format conversion
# ---------------------------------------------------------------------------


class ToolFormatConverter:
    """Converts ToolSpec lists between internal and provider-specific formats."""

    @staticmethod
    def to_anthropic(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Convert ToolSpec list to Anthropic ``{name, description, input_schema}``."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]

    @staticmethod
    def to_openai(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Convert ToolSpec list to OpenAI ``{type, function: {name, description, parameters}}``."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @staticmethod
    def from_anthropic(tools: list[dict[str, Any]]) -> list[ToolSpec]:
        """Convert Anthropic tool dicts back to ToolSpec list."""
        return [
            ToolSpec(
                name=e.get("name", ""),
                description=e.get("description", ""),
                parameters=e.get("input_schema", {}),
                danger_level=DangerLevel.SAFE,
            )
            for e in tools
        ]

    @staticmethod
    def from_openai(tools: list[dict[str, Any]]) -> list[ToolSpec]:
        """Convert OpenAI function tool dicts back to ToolSpec list."""
        return [
            ToolSpec(
                name=(f := e.get("function", e)).get("name", ""),
                description=f.get("description", ""),
                parameters=f.get("parameters", {}),
                danger_level=DangerLevel.SAFE,
            )
            for e in tools
        ]


# ---------------------------------------------------------------------------
# Provider adapter
# ---------------------------------------------------------------------------


class ProviderAdapter:
    """Adapts between different provider message/tool formats.

    Wraps a concrete LLM provider and transparently converts tool specs and
    messages to the format the provider expects, then normalises responses.
    """

    def __init__(self, provider: Any, default_model: str = "") -> None:
        self._provider = provider
        self._default_model = default_model
        self._provider_type = self._detect_provider_type()

    def _detect_provider_type(self) -> str:
        """Heuristically detect whether the provider is Anthropic or OpenAI."""
        name = getattr(self._provider, "name", "").lower()
        if "anthropic" in name or "claude" in name:
            return "anthropic"
        if "openai" in name or "gpt" in name:
            return "openai"
        return "anthropic"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolSpec] | None = None,
        model: str = "",
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Call the underlying provider with automatic format conversion."""
        from attocode.types.messages import ChatOptions, Message, Role

        converted = self.convert_messages_to_provider(messages)
        msg_objects = [
            Message(role=Role(m.get("role", "user")), content=m.get("content", ""))
            for m in converted
        ]
        effective_model = model or self._default_model
        options = ChatOptions(model=effective_model or None, max_tokens=max_tokens)
        response = await self._provider.chat(msg_objects, options)
        return self.convert_response_from_provider(response)

    def convert_messages_to_provider(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert internal ``{role, content, tool_calls?, tool_call_id?}`` to provider format."""
        if self._provider_type == "openai":
            return MessageFormatAdapter.to_openai_messages(messages)
        return MessageFormatAdapter.to_anthropic_messages(messages)

    def convert_response_from_provider(self, response: Any) -> dict[str, Any]:
        """Normalise a provider response to ``{content, stop_reason, tool_calls, usage}``."""
        if isinstance(response, dict):
            return response

        result: dict[str, Any] = {
            "content": getattr(response, "content", ""),
            "stop_reason": str(getattr(response, "stop_reason", "end_turn")),
            "tool_calls": None,
            "usage": None,
        }

        raw_calls = getattr(response, "tool_calls", None)
        if raw_calls:
            result["tool_calls"] = [
                {"id": getattr(tc, "id", ""), "name": getattr(tc, "name", ""),
                 "arguments": getattr(tc, "arguments", {})}
                for tc in raw_calls
            ]

        usage = getattr(response, "usage", None)
        if usage:
            result["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
                "cache_read_tokens": getattr(usage, "cache_read_tokens", 0),
                "cost": getattr(usage, "cost", 0.0),
            }
        return result


# ---------------------------------------------------------------------------
# TUI bridge protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ApprovalBridge(Protocol):
    """Async bridge for requesting user approval of tool execution."""

    async def request_approval(
        self, tool_name: str, args: dict[str, Any], danger_level: str = "low",
    ) -> bool: ...


@runtime_checkable
class BudgetExtensionBridge(Protocol):
    """Async bridge for requesting a budget extension from the user."""

    async def request_extension(
        self, current_tokens: int, max_tokens: int, requested: int, reason: str = "",
    ) -> bool: ...


@runtime_checkable
class LearningValidationBridge(Protocol):
    """Async bridge for validating a proposed learning with the user."""

    async def validate_learning(self, learning: dict[str, Any]) -> str: ...


# ---------------------------------------------------------------------------
# TUI bridge factory helpers
# ---------------------------------------------------------------------------


def create_tui_approval_bridge(callback: Any, timeout: float = 60.0) -> ApprovalBridge:
    """Create an approval bridge with timeout and fail-safe default (deny)."""

    class _Impl:
        async def request_approval(
            self, tool_name: str, args: dict[str, Any], danger_level: str = "low",
        ) -> bool:
            try:
                return await asyncio.wait_for(
                    callback(tool_name, args, danger_level), timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Approval timed out after %.1fs for %s", timeout, tool_name)
                return False
            except Exception:
                logger.exception("Approval bridge error for %s", tool_name)
                return False

    return _Impl()


def create_tui_budget_bridge(callback: Any, timeout: float = 60.0) -> BudgetExtensionBridge:
    """Create a budget extension bridge with timeout and fail-safe default (deny)."""

    class _Impl:
        async def request_extension(
            self, current_tokens: int, max_tokens: int, requested: int, reason: str = "",
        ) -> bool:
            try:
                return await asyncio.wait_for(
                    callback(current_tokens, max_tokens, requested, reason), timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Budget extension timed out after %.1fs", timeout)
                return False
            except Exception:
                logger.exception("Budget extension bridge error")
                return False

    return _Impl()


def create_tui_learning_bridge(callback: Any, timeout: float = 60.0) -> LearningValidationBridge:
    """Create a learning validation bridge with timeout and fail-safe default (skip)."""

    class _Impl:
        async def validate_learning(self, learning: dict[str, Any]) -> str:
            try:
                result: str = await asyncio.wait_for(callback(learning), timeout=timeout)
                if result not in ("approve", "reject", "skip"):
                    logger.warning("Invalid validation result %r, defaulting to skip", result)
                    return "skip"
                return result
            except asyncio.TimeoutError:
                logger.warning("Learning validation timed out after %.1fs", timeout)
                return "skip"
            except Exception:
                logger.exception("Learning validation bridge error")
                return "skip"

    return _Impl()


# ---------------------------------------------------------------------------
# Message format adapter
# ---------------------------------------------------------------------------


def _serialize_args(args: Any) -> str:
    """Serialise tool call arguments to a JSON string."""
    if isinstance(args, dict):
        return json.dumps(args)
    return str(args) if args else "{}"


class MessageFormatAdapter:
    """Converts between internal and provider-specific message dict formats."""

    @staticmethod
    def to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert internal messages to Anthropic API format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Tool result -> user message with tool_result block
            if role == "tool" or msg.get("tool_call_id"):
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content,
                    }],
                })
                continue

            # Assistant with tool calls -> content blocks
            if role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in msg["tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "input": tc.get("arguments", {}),
                    })
                result.append({"role": "assistant", "content": blocks})
                continue

            result.append({"role": role, "content": content})
        return result

    @staticmethod
    def to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert internal messages to OpenAI API format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Tool result -> "tool" role message
            if role == "tool" or msg.get("tool_call_id"):
                result.append({
                    "role": "tool",
                    "content": content,
                    "tool_call_id": msg.get("tool_call_id", ""),
                })
                continue

            # Assistant with tool calls
            if role == "assistant" and msg.get("tool_calls"):
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": _serialize_args(tc.get("arguments")),
                            },
                        }
                        for tc in msg["tool_calls"]
                    ],
                }
                result.append(entry)
                continue

            result.append({"role": role, "content": content})
        return result

    @staticmethod
    def parse_tool_call_arguments(raw_args: str | dict[str, Any]) -> dict[str, Any]:
        """Parse tool call arguments from string or dict.

        OpenAI returns arguments as a JSON string; Anthropic returns a dict.
        Normalises both to a dict, returning ``{}`` on parse failure.
        """
        if isinstance(raw_args, dict):
            return raw_args
        if isinstance(raw_args, str):
            text = raw_args.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {"value": parsed}
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool call arguments: %.120s", text)
                return {}
        return {}
