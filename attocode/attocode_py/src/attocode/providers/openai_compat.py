"""Shared helpers for OpenAI-compatible providers (OpenRouter, OpenAI)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

from attocode.types.messages import (
    Message,
    MessageWithStructuredContent,
    Role,
    ToolDefinition,
)


def describe_request_error(e: httpx.RequestError) -> str:
    """Build a descriptive error message for httpx request errors.

    httpx.ReadTimeout and similar errors often have empty str(e),
    so we fall back to the exception type name and include the
    chained cause when available.
    """
    msg = str(e)
    if not msg:
        msg = type(e).__name__
    if e.__cause__ and str(e.__cause__):
        msg = f"{msg} (caused by {type(e.__cause__).__name__}: {e.__cause__})"
    return msg


def format_openai_content(content: str | list) -> str | list[dict[str, Any]]:
    """Convert structured content blocks to OpenAI-compatible format.

    Handles ImageContentBlock by converting to image_url dicts (base64 data URI
    or direct URL). Text blocks become text dicts. Plain strings pass through.

    If content contains only unknown block types, falls back to str() representation
    to avoid sending raw dataclass instances to httpx.
    """
    if isinstance(content, str):
        return content
    from attocode.types.messages import ImageContentBlock, ImageSourceType, TextContentBlock

    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, TextContentBlock):
            parts.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageContentBlock):
            if block.source.type == ImageSourceType.URL:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": block.source.data},
                })
            else:  # base64
                data_uri = f"data:{block.source.media_type};base64,{block.source.data}"
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                })
    if not parts:
        # Fallback: convert unknown block types to text to avoid sending
        # raw dataclass instances to httpx's JSON encoder.
        for block in content:
            parts.append({"type": "text", "text": str(block)})
    return parts or [{"type": "text", "text": ""}]


def format_openai_messages(
    messages: list[Message | MessageWithStructuredContent],
    format_content_fn: Any = None,
) -> list[dict[str, Any]]:
    """Format messages for OpenAI-compatible APIs.

    Args:
        messages: List of Message or MessageWithStructuredContent instances.
        format_content_fn: Content formatter (defaults to format_openai_content).
    """
    if format_content_fn is None:
        format_content_fn = format_openai_content

    result: list[dict[str, Any]] = []
    for msg in messages:
        content = format_content_fn(msg.content)
        if msg.role == Role.TOOL:
            result.append({
                "role": "tool",
                "content": content,
                "tool_call_id": msg.tool_call_id or "",
            })
        elif msg.role == Role.ASSISTANT and msg.tool_calls:
            tc_list = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
            result.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": tc_list,
            })
        else:
            result.append({"role": str(msg.role), "content": content})
    return result


def format_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    """Format a tool definition for OpenAI-compatible APIs."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
