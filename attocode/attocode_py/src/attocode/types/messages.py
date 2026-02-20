"""Core message types for LLM communication."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Message role in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class DangerLevel(StrEnum):
    """Tool danger classification."""

    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


class StopReason(StrEnum):
    """Why the LLM stopped generating."""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"


class StreamChunkType(StrEnum):
    """Type of streaming chunk."""

    TEXT = "text"
    TOOL_CALL = "tool_call"
    THINKING = "thinking"
    USAGE = "usage"
    ERROR = "error"
    DONE = "done"


@dataclass
class CacheControl:
    """Cache control for content blocks."""

    type: str = "ephemeral"


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]
    parse_error: str | None = None


@dataclass
class ToolResult:
    """Result of executing a tool call."""

    call_id: str
    result: str | None = None
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class ToolDefinition:
    """Schema definition for a tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    danger_level: DangerLevel = DangerLevel.SAFE

    def to_schema(self) -> dict[str, Any]:
        """Convert to the API schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class TokenUsage:
    """Token consumption metrics."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0


@dataclass
class ImageSource:
    """Source data for an image content block."""

    type: str = "base64"
    media_type: str = "image/png"
    data: str = ""


class ImageSourceType(StrEnum):
    """Image source type."""

    BASE64 = "base64"
    URL = "url"


@dataclass
class TextContentBlock:
    """A text content block."""

    text: str
    type: str = "text"
    cache_control: CacheControl | None = None


@dataclass
class ImageContentBlock:
    """An image content block."""

    source: ImageSource
    type: str = "image"
    cache_control: CacheControl | None = None


ContentBlock = TextContentBlock | ImageContentBlock


@dataclass
class Message:
    """A conversation message."""

    role: Role
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class MessageWithStructuredContent:
    """A message that can contain structured content blocks."""

    role: Role
    content: str | list[ContentBlock]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ChatOptions:
    """Options for an LLM chat request."""

    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop_sequences: list[str] | None = None
    tools: list[ToolDefinition] | None = None
    system: str | None = None
    stream: bool = False


@dataclass
class ChatResponse:
    """Response from an LLM chat request."""

    content: str
    stop_reason: StopReason | None = None
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage | None = None
    thinking: str | None = None
    model: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class StreamChunk:
    """A chunk from a streaming LLM response."""

    type: StreamChunkType
    content: str | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
    error: str | None = None
