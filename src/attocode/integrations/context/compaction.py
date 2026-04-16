"""Message compaction utilities.

Compacts conversation messages to reduce context size while
preserving essential information.

Includes multi-tier compaction with tool-aware decay profiles
(``ToolDecayProfile`` / ``microcompact``) for per-turn clearing
of stale tool results based on tool-specific retention rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from attocode.integrations.utilities.token_estimate import estimate_tokens
from attocode.types.messages import Message, Role

# Length thresholds
COMPACT_PREVIEW_LENGTH = 200
MAX_TOOL_OUTPUT_CHARS = 8000
MAX_PRESERVED_EXPENSIVE_RESULTS = 6


# ---------------------------------------------------------------------------
# Multi-Tier Compaction: Tool-Aware Decay Profiles
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolDecayProfile:
    """Controls how quickly a tool's results are eligible for clearing."""

    tool_name: str
    max_age_turns: int  # Turns before eligible for clearing
    preview_length: int  # Characters to keep when cleared
    priority: int  # Higher = keep longer (0-10)


# Tool-specific decay rates — informed by CC source analysis.
# Edit/write tools have the longest retention because they represent
# decisions the agent made.  Read-only tools decay faster since their
# content can be re-fetched.
TOOL_DECAY_PROFILES: dict[str, ToolDecayProfile] = {
    "read_file": ToolDecayProfile("read_file", max_age_turns=5, preview_length=200, priority=3),
    "bash": ToolDecayProfile("bash", max_age_turns=3, preview_length=100, priority=2),
    "grep": ToolDecayProfile("grep", max_age_turns=3, preview_length=150, priority=2),
    "glob_files": ToolDecayProfile("glob_files", max_age_turns=4, preview_length=100, priority=1),
    "web_fetch": ToolDecayProfile("web_fetch", max_age_turns=2, preview_length=100, priority=1),
    "edit_file": ToolDecayProfile("edit_file", max_age_turns=8, preview_length=300, priority=7),
    "write_file": ToolDecayProfile("write_file", max_age_turns=8, preview_length=300, priority=7),
    "semantic_search": ToolDecayProfile("semantic_search", max_age_turns=6, preview_length=200, priority=5),
    "ast_query": ToolDecayProfile("ast_query", max_age_turns=6, preview_length=200, priority=5),
    "list_files": ToolDecayProfile("list_files", max_age_turns=3, preview_length=100, priority=1),
    "search": ToolDecayProfile("search", max_age_turns=3, preview_length=150, priority=2),
}

# Default profile for unregistered tools
_DEFAULT_PROFILE = ToolDecayProfile("_default", max_age_turns=4, preview_length=150, priority=3)


# ---------------------------------------------------------------------------
# Content Replacement State Tracking (C1)
# ---------------------------------------------------------------------------

# Tools whose results are code-intelligence related
CODE_INTEL_TOOLS: frozenset[str] = frozenset({
    "ast_query", "semantic_search", "search_symbols", "cross_references",
    "dependencies", "impact_analysis", "find_related", "repo_map",
    "file_analysis", "code_evolution", "symbols",
})


@dataclass(slots=True)
class ReplacedContent:
    """Metadata about a replaced/evicted tool result."""

    tool_name: str
    original_token_estimate: int
    turn_number: int
    preview: str
    was_code_intel: bool = False


class ContentReplacementState:
    """Tracks tool results that have been evicted from context.

    Enables selective re-injection of high-value results (especially
    code-intelligence results) after compaction.
    """

    def __init__(self) -> None:
        self._replaced: dict[str, ReplacedContent] = {}

    def record_replacement(
        self,
        message_id: str,
        tool_name: str,
        original_content: str,
        turn_number: int,
        preview: str = "",
    ) -> None:
        """Record that a tool result was evicted."""
        if not preview:
            preview = original_content[:200].strip()
        est_tokens = estimate_tokens(original_content)
        self._replaced[message_id] = ReplacedContent(
            tool_name=tool_name,
            original_token_estimate=est_tokens,
            turn_number=turn_number,
            preview=preview,
            was_code_intel=tool_name in CODE_INTEL_TOOLS,
        )

    def get_evicted_code_intel(self) -> list[tuple[str, ReplacedContent]]:
        """Return evicted code-intel results, sorted by token estimate (largest first)."""
        return sorted(
            [(mid, rc) for mid, rc in self._replaced.items() if rc.was_code_intel],
            key=lambda x: x[1].original_token_estimate,
            reverse=True,
        )

    def get_restorable(self, token_budget: int) -> list[str]:
        """Return message_ids of evicted results that fit in budget.

        Prioritizes code-intel results, then by size (largest first).
        """
        # Sort: code-intel first, then by token estimate descending
        sorted_items = sorted(
            self._replaced.items(),
            key=lambda x: (not x[1].was_code_intel, -x[1].original_token_estimate),
        )

        result: list[str] = []
        remaining = token_budget
        for mid, rc in sorted_items:
            if rc.original_token_estimate <= remaining:
                result.append(mid)
                remaining -= rc.original_token_estimate
            if remaining <= 0:
                break
        return result

    def remove(self, message_id: str) -> None:
        """Remove a replacement record (e.g., after restoration)."""
        self._replaced.pop(message_id, None)

    def clear(self) -> None:
        """Clear all replacement records."""
        self._replaced.clear()

    @property
    def total_evicted_tokens(self) -> int:
        """Total estimated tokens that have been evicted."""
        return sum(rc.original_token_estimate for rc in self._replaced.values())

    @property
    def evicted_count(self) -> int:
        return len(self._replaced)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for debugging/persistence."""
        return {
            "count": self.evicted_count,
            "total_tokens": self.total_evicted_tokens,
            "code_intel_count": sum(
                1 for rc in self._replaced.values() if rc.was_code_intel
            ),
            "items": {
                mid: {
                    "tool": rc.tool_name,
                    "tokens": rc.original_token_estimate,
                    "turn": rc.turn_number,
                    "code_intel": rc.was_code_intel,
                    "preview": rc.preview[:100],
                }
                for mid, rc in self._replaced.items()
            },
        }


# ---------------------------------------------------------------------------
# Compaction Result
# ---------------------------------------------------------------------------


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
    replacement_state: ContentReplacementState | None = None,
) -> int:
    """Compact tool output messages in-place.

    Truncates long tool result content to a short preview,
    preserving the most recent messages.

    Args:
        messages: List of messages to compact (modified in-place).
        preview_length: Maximum length for compacted previews.
        preserve_recent: Number of recent messages to preserve.
        replacement_state: Optional state tracker for evicted content.
            When provided, records metadata about each compacted message
            so high-value results can be selectively re-injected later.

    Returns:
        Number of messages compacted.
    """
    compacted = 0
    cutoff = len(messages) - preserve_recent

    # Build tool_call_id -> tool_name lookup when tracking replacements
    id_to_name: dict[str, str] = {}
    if replacement_state is not None:
        id_to_name = _build_tool_call_id_to_name(messages)

    for i, msg in enumerate(messages):
        if i >= cutoff:
            break
        if not hasattr(msg, "role") or msg.role != Role.TOOL:
            continue
        content = msg.content or ""
        if len(content) > preview_length:
            # Record eviction before replacing content
            if replacement_state is not None:
                tool_call_id = getattr(msg, "tool_call_id", None)
                msg_id = tool_call_id or f"turn-{i}"
                tool_name = (
                    id_to_name.get(tool_call_id, "")
                    if tool_call_id
                    else ""
                ) or getattr(msg, "name", None) or "unknown"
                replacement_state.record_replacement(
                    message_id=msg_id,
                    tool_name=tool_name,
                    original_content=content,
                    turn_number=i,
                )

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


def _build_tool_call_id_to_name(messages: list[Message | Any]) -> dict[str, str]:
    """Build a mapping from tool_call_id to tool name.

    Scans assistant messages for ``tool_calls`` and records each
    call's ``id`` -> ``name`` pair.
    """
    mapping: dict[str, str] = {}
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                tc_id = getattr(tc, "id", None)
                tc_name = getattr(tc, "name", None)
                if tc_id and tc_name:
                    mapping[tc_id] = tc_name
    return mapping


def _estimate_turn(index: int, messages: list[Message | Any]) -> int:
    """Estimate which turn a message belongs to.

    Turns are delimited by assistant messages: each assistant message
    increments the turn counter.  This gives a rough age without
    requiring a ``turn`` field on ``Message``.
    """
    turn = 0
    for i in range(index):
        m = messages[i]
        if hasattr(m, "role") and m.role == Role.ASSISTANT:
            turn += 1
    return turn


def microcompact(
    messages: list[Message | Any],
    current_turn: int,
    profiles: dict[str, ToolDecayProfile] | None = None,
    replacement_state: ContentReplacementState | None = None,
) -> int:
    """Per-turn tool result clearing based on tool-specific decay profiles.

    Iterates through messages and clears tool results that have exceeded
    their ``max_age_turns``.  Low-priority tools are cleared first.
    Modifies *messages* in-place (replacing stale ``Role.TOOL`` messages
    with short preview placeholders).

    The tool name is resolved by matching the tool result's
    ``tool_call_id`` back to the originating ``ToolCall`` on the
    preceding assistant message.

    Args:
        messages: Message list to compact (modified in-place).
        current_turn: Current iteration / turn number.
        profiles: Tool decay profiles.  Defaults to ``TOOL_DECAY_PROFILES``.
        replacement_state: Optional state tracker for evicted content.
            When provided, records metadata about each cleared message
            so high-value results can be selectively re-injected later.

    Returns:
        Number of tool results cleared.
    """
    if profiles is None:
        profiles = TOOL_DECAY_PROFILES

    # Build tool_call_id -> tool_name lookup from assistant messages
    id_to_name = _build_tool_call_id_to_name(messages)

    cleared = 0

    # Build list of (message_index, tool_name, priority, age) for eligible results
    candidates: list[tuple[int, str, int, int]] = []

    for i, msg in enumerate(messages):
        # Only process tool result messages
        if not hasattr(msg, "role") or msg.role != Role.TOOL:
            continue

        # Resolve tool name via tool_call_id
        tool_call_id = getattr(msg, "tool_call_id", None)
        tool_name = id_to_name.get(tool_call_id, "") if tool_call_id else ""
        if not tool_name:
            # Fallback: check ``name`` attribute (some adapters populate it)
            tool_name = getattr(msg, "name", None) or ""
        if not tool_name:
            continue

        profile = profiles.get(tool_name, _DEFAULT_PROFILE)
        turn = _estimate_turn(i, messages)
        age = current_turn - turn

        if age >= profile.max_age_turns:
            candidates.append((i, tool_name, profile.priority, age))

    # Sort by priority (ascending) so low-priority items are cleared first,
    # then by age (descending) so the oldest within the same priority go first.
    candidates.sort(key=lambda x: (x[2], -x[3]))

    for idx, tool_name, _priority, age in candidates:
        msg = messages[idx]
        content = msg.content or ""
        profile = profiles.get(tool_name, _DEFAULT_PROFILE)
        preview = content[: profile.preview_length].strip()

        # Record eviction before replacing content
        if replacement_state is not None:
            tool_call_id = getattr(msg, "tool_call_id", None)
            msg_id = tool_call_id or f"turn-{idx}"
            origin_turn = current_turn - age
            replacement_state.record_replacement(
                message_id=msg_id,
                tool_name=tool_name,
                original_content=content,
                turn_number=origin_turn,
                preview=preview,
            )

        # Replace with a cleared marker that retains a short preview
        origin_turn = current_turn - age
        cleared_content = (
            f"[Cleared: {tool_name} result from turn {origin_turn}. "
            f"Preview: {preview}]"
        )
        # Replace the message in-place (Message uses slots — reassign content)
        messages[idx] = Message(
            role=Role.TOOL,
            content=cleared_content,
            tool_call_id=getattr(msg, "tool_call_id", None),
            name=getattr(msg, "name", None),
        )
        cleared += 1

    return cleared


def adjust_slice_for_tool_pairs(
    messages: list[Message | Any],
    slice_start: int,
) -> int:
    """Walk backwards from *slice_start* to include the full tool-call group.

    If ``messages[slice_start]`` is a ``Role.TOOL`` message, the corresponding
    ``assistant`` message (with matching ``tool_calls``) must also be included
    so the pair is not orphaned.  This walks backwards until a non-TOOL message
    is found and includes it if it is an ``assistant`` message with tool_calls.

    Returns the adjusted (possibly earlier) slice start index.
    """
    if slice_start >= len(messages):
        return slice_start

    # If the message at slice_start is not a TOOL message, no adjustment needed
    if not (hasattr(messages[slice_start], "role") and messages[slice_start].role == Role.TOOL):
        return slice_start

    idx = slice_start
    # Walk backwards past consecutive TOOL messages
    while idx > 0 and hasattr(messages[idx], "role") and messages[idx].role == Role.TOOL:
        idx -= 1

    # If we landed on an assistant message with tool_calls, include it
    if idx >= 0:
        msg = messages[idx]
        if (
            hasattr(msg, "role")
            and msg.role == Role.ASSISTANT
            and getattr(msg, "tool_calls", None)
        ):
            return idx

    # The TOOL messages at slice_start didn't have a matching assistant in range;
    # skip past them to avoid sending orphans
    skip = slice_start
    while skip < len(messages) and hasattr(messages[skip], "role") and messages[skip].role == Role.TOOL:
        skip += 1
    return skip


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

    # Keep recent messages, adjusting boundary to keep tool pairs intact
    raw_start = max(0, len(messages) - preserve_recent)
    adj_start = adjust_slice_for_tool_pairs(messages, raw_start)
    recent = messages[adj_start:]

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
