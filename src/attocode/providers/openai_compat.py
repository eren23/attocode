"""Shared helpers for OpenAI-compatible providers (OpenRouter, OpenAI)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

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


def sanitize_tool_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure tool results immediately follow their assistant tool_calls.

    Strict OpenAI-compatible APIs (e.g. MiniMax) require:
    1. Every ``role="tool"`` message references a ``tool_call_id`` from a
       preceding ``assistant`` message's ``tool_calls`` array.
    2. Tool result messages appear **immediately** after the assistant message
       (no interleaved user/system messages).

    This function:
    - Drops orphaned tool results (no matching tool_call).
    - Relocates interleaved non-tool messages so tool results sit right after
      the assistant.
    """
    # Pass 1: collect all valid tool_call IDs and group tool results
    # with their assistant message.
    known_tc_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tc_id = tc.get("id")
                if tc_id:
                    known_tc_ids.add(tc_id)

    # Pass 2: build result with correct ordering.
    # When we see an assistant message with tool_calls, collect its
    # tool results and any interleaved messages, then emit in order:
    # assistant → tool results → interleaved messages.
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")

        if role == "assistant" and msg.get("tool_calls"):
            # Collect the IDs this assistant expects
            expected_ids = {
                tc.get("id") for tc in msg["tool_calls"] if tc.get("id")
            }
            result.append(msg)
            i += 1

            # Scan ahead: gather tool results and interleaved messages
            tool_results: list[dict[str, Any]] = []
            deferred: list[dict[str, Any]] = []
            while i < len(messages):
                nxt = messages[i]
                nxt_role = nxt.get("role")
                if nxt_role == "tool":
                    tc_id = nxt.get("tool_call_id", "")
                    if tc_id in expected_ids:
                        tool_results.append(nxt)
                        expected_ids.discard(tc_id)
                        i += 1
                        continue
                    elif tc_id in known_tc_ids:
                        # Belongs to a different assistant — stop scanning
                        break
                    else:
                        # Orphan — drop it
                        logger.warning(
                            "Dropping orphaned tool result (tool_call_id=%s)",
                            tc_id,
                        )
                        i += 1
                        continue
                elif nxt_role == "assistant":
                    # Next turn — stop
                    break
                else:
                    # Interleaved user/system message — defer until after results
                    deferred.append(nxt)
                    i += 1
                    if not expected_ids:
                        break  # All results collected

            result.extend(tool_results)
            result.extend(deferred)

        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id and tc_id in known_tc_ids:
                result.append(msg)
            else:
                logger.warning(
                    "Dropping orphaned tool result (tool_call_id=%s)",
                    tc_id,
                )
            i += 1
        else:
            result.append(msg)
            i += 1

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
