"""Auto-compaction manager.

Monitors context size and triggers compaction when thresholds
are exceeded. Uses a two-stage protocol: first asks the LLM
to summarize, then replaces messages with the summary.

Features:
- Threshold-based triggers (warning + compaction)
- Warning and approval modes
- Configurable compaction strategies
- Work log integration for context preservation
- Statistics tracking
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from attocode.integrations.context.compaction import adjust_slice_for_tool_pairs
from attocode.integrations.utilities.token_estimate import count_tokens
from attocode.types.messages import Message, Role

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Post-compaction file restoration constants
# ---------------------------------------------------------------------------
POST_COMPACT_MAX_FILES = 5
POST_COMPACT_TOKEN_BUDGET = 50_000


class CompactionStatus(StrEnum):
    """Status of compaction check."""

    OK = "ok"
    DUMB_ZONE = "dumb_zone"  # 40-60% fill — quality degradation likely
    WARNING = "warning"
    NEEDS_COMPACTION = "needs_compaction"
    NEEDS_APPROVAL = "needs_approval"
    COMPACTED = "compacted"


class CompactionStrategy(StrEnum):
    """Strategy for how compaction is performed."""

    SUMMARIZE = "summarize"  # LLM summarizes then replaces
    TRUNCATE = "truncate"  # Keep recent, drop old
    SELECTIVE = "selective"  # Keep important, drop routine
    REVERSIBLE = "reversible"  # Summarize with retrieval references


@dataclass(slots=True)
class CompactionCheckResult:
    """Result of checking if compaction is needed."""

    status: CompactionStatus
    usage_fraction: float
    message: str = ""
    estimated_tokens: int = 0
    messages_count: int = 0


@dataclass(slots=True)
class CompactionStats:
    """Statistics for compaction operations."""

    total_compactions: int = 0
    total_messages_removed: int = 0
    total_tokens_saved: int = 0
    last_compaction_time: float = 0.0
    average_compression_ratio: float = 0.0

    def record(self, messages_before: int, messages_after: int, tokens_saved: int) -> None:
        self.total_compactions += 1
        self.total_messages_removed += messages_before - messages_after
        self.total_tokens_saved += tokens_saved
        self.last_compaction_time = time.monotonic()
        if self.total_compactions > 0 and messages_before > 0:
            ratio = messages_after / messages_before
            # Running average
            self.average_compression_ratio = (
                (self.average_compression_ratio * (self.total_compactions - 1) + ratio)
                / self.total_compactions
            )


@dataclass
class AutoCompactionManager:
    """Manages automatic context compaction.

    Monitors the total token count of messages and triggers
    compaction when usage exceeds configurable thresholds.

    Two-stage protocol:
    1. At warning threshold: inject a summary prompt
    2. On next iteration: replace messages with compacted version

    Supports multiple strategies and approval modes.
    """

    max_context_tokens: int = 200_000
    warning_threshold: float = 0.7
    compaction_threshold: float = 0.8
    dumb_zone_start: float = 0.4  # Quality begins degrading here
    dumb_zone_end: float = 0.6  # Significant degradation by here
    fresh_context_enabled: bool = True  # Enable fresh context protocol
    strategy: CompactionStrategy = CompactionStrategy.SUMMARIZE
    require_approval: bool = False
    min_messages_to_keep: int = 4  # Always keep at least this many recent messages
    _compaction_pending: bool = field(default=False, repr=False)
    _compacted_messages: list[Message] | None = field(default=None, repr=False)
    _stats: CompactionStats = field(default_factory=CompactionStats, repr=False)
    _last_check_tokens: int = field(default=0, repr=False)
    _dumb_zone_entered: bool = field(default=False, repr=False)
    _dumb_zone_enter_time: float = field(default=0.0, repr=False)
    _fresh_context_count: int = field(default=0, repr=False)

    @property
    def stats(self) -> CompactionStats:
        return self._stats

    def check(self, messages: list[Message | Any]) -> CompactionCheckResult:
        """Check if compaction is needed.

        Detects three zones:
        - OK: < 40% fill — peak quality
        - DUMB_ZONE: 40-60% fill — quality begins degrading
        - WARNING: 60-80% fill — approaching limit
        - NEEDS_COMPACTION: > 80% fill — compaction required

        Args:
            messages: Current conversation messages.

        Returns:
            CompactionCheckResult with status and usage info.
        """
        total_tokens = self._estimate_tokens(messages)
        self._last_check_tokens = total_tokens
        fraction = total_tokens / self.max_context_tokens if self.max_context_tokens > 0 else 0.0

        if fraction >= self.compaction_threshold:
            if self.require_approval:
                return CompactionCheckResult(
                    status=CompactionStatus.NEEDS_APPROVAL,
                    usage_fraction=fraction,
                    message=f"Context at {fraction:.0%} — approval needed for compaction",
                    estimated_tokens=total_tokens,
                    messages_count=len(messages),
                )
            return CompactionCheckResult(
                status=CompactionStatus.NEEDS_COMPACTION,
                usage_fraction=fraction,
                message=f"Context at {fraction:.0%} — compaction needed",
                estimated_tokens=total_tokens,
                messages_count=len(messages),
            )

        if fraction >= self.warning_threshold:
            return CompactionCheckResult(
                status=CompactionStatus.WARNING,
                usage_fraction=fraction,
                message=f"Context at {fraction:.0%} — approaching limit",
                estimated_tokens=total_tokens,
                messages_count=len(messages),
            )

        # Dumb zone detection: quality degrades between 40-60% fill
        if self.fresh_context_enabled and fraction >= self.dumb_zone_start:
            if not self._dumb_zone_entered:
                self._dumb_zone_entered = True
                self._dumb_zone_enter_time = time.monotonic()
            return CompactionCheckResult(
                status=CompactionStatus.DUMB_ZONE,
                usage_fraction=fraction,
                message=(
                    f"Context at {fraction:.0%} — entering dumb zone. "
                    "Quality may degrade. Consider fresh context refresh."
                ),
                estimated_tokens=total_tokens,
                messages_count=len(messages),
            )

        # Reset dumb zone tracking if we're below threshold
        self._dumb_zone_entered = False

        return CompactionCheckResult(
            status=CompactionStatus.OK,
            usage_fraction=fraction,
            estimated_tokens=total_tokens,
            messages_count=len(messages),
        )

    def create_summary_prompt(self, *, include_work_log: bool = True) -> str:
        """Create a prompt asking the LLM to summarize progress."""
        base = (
            "Before continuing, please provide a concise summary of:\n"
            "1. What task you're working on\n"
            "2. What you've accomplished so far\n"
            "3. What remains to be done\n"
            "4. Any important context or decisions made\n"
            "5. Key file paths and changes made\n\n"
            "Keep the summary brief but comprehensive. "
            "Include specific file names and function names."
        )
        if include_work_log:
            base += (
                "\n\nAlso include a brief work log of major actions "
                "(e.g., 'Created foo.py with class Bar', 'Fixed bug in baz()')."
            )
        return base

    def compact(
        self,
        messages: list[Message | Any],
        summary: str,
        *,
        extra_context: list[str] | None = None,
        preserve_recent: int | None = None,
    ) -> list[Message | Any]:
        """Replace messages with a compacted version.

        Keeps system messages, injects the summary, and optionally
        preserves the most recent messages.

        Args:
            messages: Current messages.
            summary: LLM-generated summary of progress.
            extra_context: Additional context strings to inject.
            preserve_recent: Number of recent non-system messages to keep.

        Returns:
            New compacted message list.
        """
        messages_before = len(messages)
        tokens_before = self._estimate_tokens(messages)

        # Keep system messages
        result: list[Message | Any] = []
        non_system: list[Message | Any] = []
        for msg in messages:
            if hasattr(msg, "role") and msg.role == Role.SYSTEM:
                result.append(msg)
            else:
                non_system.append(msg)

        # Add summary as user + assistant exchange
        result.append(Message(
            role=Role.USER,
            content=(
                "The conversation context has been compacted. "
                "Here is a summary of the work so far:"
            ),
        ))
        result.append(Message(
            role=Role.ASSISTANT,
            content=summary,
        ))

        # Add extra context
        if extra_context:
            context_text = "\n\n".join(extra_context)
            result.append(Message(
                role=Role.USER,
                content=f"Additional context:\n\n{context_text}\n\nPlease continue.",
            ))

        # Preserve recent messages, adjusting boundary to keep tool pairs intact
        keep = preserve_recent or self.min_messages_to_keep
        if keep > 0 and non_system:
            raw_start = max(0, len(non_system) - keep)
            adj_start = adjust_slice_for_tool_pairs(non_system, raw_start)
            recent = non_system[adj_start:]
            result.extend(recent)

        messages_after = len(result)
        tokens_after = self._estimate_tokens(result)
        self._stats.record(messages_before, messages_after, tokens_before - tokens_after)

        return result

    def emergency_compact(
        self,
        messages: list[Message | Any],
    ) -> list[Message | Any]:
        """Emergency compaction — truncate without LLM summary.

        Used when budget is too tight for an LLM summarization call.
        Keeps system messages and the most recent messages.
        """
        system_msgs = [m for m in messages if hasattr(m, "role") and m.role == Role.SYSTEM]
        non_system = [m for m in messages if not (hasattr(m, "role") and m.role == Role.SYSTEM)]

        # Keep only the last few messages, adjusting to keep tool pairs intact
        keep = max(self.min_messages_to_keep, 6)
        if len(non_system) > keep:
            raw_start = len(non_system) - keep
            adj_start = adjust_slice_for_tool_pairs(non_system, raw_start)
            recent = non_system[adj_start:]
        else:
            recent = non_system

        result = list(system_msgs)
        result.append(Message(
            role=Role.USER,
            content="[Context was emergency-truncated to save budget. Previous work has been removed.]",
        ))
        result.extend(recent)

        self._stats.record(len(messages), len(result), 0)
        return result

    async def restore_critical_files(
        self,
        compacted_messages: list[Message | Any],
        codebase_context: Any = None,
    ) -> list[Message | Any]:
        """Re-inject the most important files after compaction.

        Uses PageRank-boosted importance scores from *codebase_context*
        (a :class:`CodebaseContextManager`) if available.  Files are
        appended as ``Role.USER`` messages so the LLM retains awareness
        of key code after the context has been compressed.

        Args:
            compacted_messages: Message list produced by :meth:`compact`
                or :meth:`emergency_compact`.
            codebase_context: A :class:`CodebaseContextManager` instance
                (or ``None`` to skip restoration).

        Returns:
            The *compacted_messages* list, possibly extended with
            restored file content messages.
        """
        if not codebase_context:
            return compacted_messages

        try:
            top_files = codebase_context.get_top_files_by_importance(
                max_files=POST_COMPACT_MAX_FILES,
                max_tokens=POST_COMPACT_TOKEN_BUDGET,
            )
        except (AttributeError, TypeError, Exception):
            logger.debug("restore_critical_files: codebase_context lacks get_top_files_by_importance")
            return compacted_messages

        if not top_files:
            return compacted_messages

        # Resolve relative paths against the codebase root
        root_dir = getattr(codebase_context, "root_dir", None)

        tokens_used = 0
        for file_path, score in top_files:
            try:
                # The file_path may be relative (from get_top_files_by_importance)
                resolved = Path(file_path)
                if not resolved.is_absolute() and root_dir:
                    resolved = Path(root_dir) / file_path
                content = resolved.read_text(encoding="utf-8", errors="replace")
                est_tokens = count_tokens(content)
                if tokens_used + est_tokens > POST_COMPACT_TOKEN_BUDGET:
                    # Trim content to stay within budget
                    remaining = POST_COMPACT_TOKEN_BUDGET - tokens_used
                    if remaining <= 0:
                        break
                    # Rough trim: ~4 chars per token
                    content = content[: remaining * 4]
                    est_tokens = remaining
                tokens_used += est_tokens
                restore_msg = Message(
                    role=Role.USER,
                    content=(
                        f"[Post-compaction context restore: {file_path} "
                        f"(importance: {score:.2f})]\n{content}"
                    ),
                )
                compacted_messages.append(restore_msg)
            except (OSError, UnicodeDecodeError):
                continue

        return compacted_messages

    def create_handoff_summary_prompt(self) -> str:
        """Create a prompt for generating a fresh context handoff summary.

        Used when refreshing context at the dumb zone boundary.
        More structured than compaction summary — designed to
        transfer maximum information to a fresh context.
        """
        return (
            "Context is being refreshed for optimal quality. "
            "Please provide a structured handoff summary:\n\n"
            "## Current Task\n"
            "What is the current goal and where are we in achieving it?\n\n"
            "## Completed Work\n"
            "List specific files created/modified with brief descriptions.\n\n"
            "## Pending Work\n"
            "What remains to be done? List specific next steps.\n\n"
            "## Key Decisions\n"
            "Important architectural or design decisions made.\n\n"
            "## Critical Context\n"
            "Any information that would be lost without this summary "
            "(error patterns found, API quirks discovered, etc.).\n\n"
            "Be specific — include file paths, function names, and exact values."
        )

    def should_refresh_context(self, messages: list[Message | Any]) -> bool:
        """Check if a fresh context refresh is recommended.

        Returns True when the context is in the dumb zone and
        the fresh context protocol is enabled.
        """
        if not self.fresh_context_enabled:
            return False
        check = self.check(messages)
        return check.status == CompactionStatus.DUMB_ZONE and check.usage_fraction >= self.dumb_zone_end

    @property
    def in_dumb_zone(self) -> bool:
        """Whether we're currently in the dumb zone."""
        return self._dumb_zone_entered

    @property
    def fresh_context_count(self) -> int:
        """Number of fresh context refreshes performed."""
        return self._fresh_context_count

    def record_fresh_context(self) -> None:
        """Record that a fresh context refresh was performed."""
        self._fresh_context_count += 1
        self._dumb_zone_entered = False

    @property
    def compaction_pending(self) -> bool:
        return self._compaction_pending

    @compaction_pending.setter
    def compaction_pending(self, value: bool) -> None:
        self._compaction_pending = value

    @property
    def last_check_tokens(self) -> int:
        return self._last_check_tokens

    def _estimate_tokens(self, messages: list[Message | Any]) -> int:
        """Estimate total tokens in the message list."""
        total = 0
        for msg in messages:
            content = getattr(msg, "content", None)
            if content and isinstance(content, str):
                total += count_tokens(content)
            total += 4  # per-message overhead
        return total
