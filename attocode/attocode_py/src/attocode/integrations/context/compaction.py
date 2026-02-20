"""Message compaction utilities.

Compacts conversation messages to reduce context size while
preserving essential information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attocode.types.messages import Message, Role


# Length thresholds
COMPACT_PREVIEW_LENGTH = 200
MAX_TOOL_OUTPUT_CHARS = 8000
MAX_PRESERVED_EXPENSIVE_RESULTS = 6


@dataclass(slots=True)
class CompactionResult:
    """Result of a compaction operation."""

    messages: list[Message]
    tokens_before: int
    tokens_after: int
    messages_removed: int

    @property
    def reduction_ratio(self) -> float:
        """How much was reduced (0.0 = nothing, 1.0 = everything)."""
        if self.tokens_before == 0:
            return 0.0
        return 1.0 - (self.tokens_after / self.tokens_before)


def compact_tool_outputs(
    messages: list[Message | Any],
    *,
    preview_length: int = COMPACT_PREVIEW_LENGTH,
    preserve_recent: int = 4,
) -> int:
    """Compact tool output messages in-place.

    Truncates long tool result content to a short preview,
    preserving the most recent messages.

    Args:
        messages: List of messages to compact (modified in-place).
        preview_length: Maximum length for compacted previews.
        preserve_recent: Number of recent messages to preserve.

    Returns:
        Number of messages compacted.
    """
    compacted = 0
    cutoff = len(messages) - preserve_recent

    for i, msg in enumerate(messages):
        if i >= cutoff:
            break
        if not hasattr(msg, "role") or msg.role != Role.TOOL:
            continue
        content = msg.content or ""
        if len(content) > preview_length:
            messages[i] = Message(
                role=Role.TOOL,
                content=content[:preview_length] + "... (compacted)",
                tool_call_id=getattr(msg, "tool_call_id", None),
            )
            compacted += 1

    return compacted


def truncate_tool_output(content: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Truncate a single tool output to max_chars."""
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return (
        content[:half]
        + f"\n\n... ({len(content) - max_chars} characters truncated) ...\n\n"
        + content[-half:]
    )


def emergency_truncation(
    messages: list[Message | Any],
    *,
    preserve_recent: int = 10,
    work_log_summary: str = "",
) -> list[Message | Any]:
    """Emergency context reduction for budget recovery.

    Keeps the system message and the most recent messages,
    injecting a work log summary to preserve context.

    Args:
        messages: Full message list.
        preserve_recent: Number of recent messages to keep.
        work_log_summary: Optional work log to inject.

    Returns:
        Truncated message list.
    """
    if len(messages) <= preserve_recent + 1:
        return messages

    # Keep system message(s) at the start
    system_msgs = []
    for msg in messages:
        if hasattr(msg, "role") and msg.role == Role.SYSTEM:
            system_msgs.append(msg)
        else:
            break

    # Keep recent messages
    recent = messages[-preserve_recent:]

    result = list(system_msgs)

    # Inject work log summary if available
    if work_log_summary:
        result.append(Message(
            role=Role.USER,
            content=(
                "Previous context was compacted. Here's a summary of work done:\n\n"
                f"{work_log_summary}\n\n"
                "Continue from where you left off."
            ),
        ))

    result.extend(recent)
    return result
