"""Tests for fresh context protocol and dumb zone detection."""

from __future__ import annotations

import pytest

from attocode.integrations.context.auto_compaction import (
    AutoCompactionManager,
    CompactionStatus,
)
from attocode.types.messages import Message, Role


MAX_TOKENS = 10_000


def _make_messages_for_fill(fill_fraction: float) -> list[Message]:
    """Create messages that fill approximately fill_fraction of MAX_TOKENS."""
    from attocode.integrations.utilities.token_estimate import count_tokens

    target_tokens = int(MAX_TOKENS * fill_fraction)
    msgs: list[Message] = []
    total = 0
    words = "the quick brown fox jumps over the lazy dog and "
    i = 0
    while total < target_tokens:
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        content = words * 40
        msg_tokens = count_tokens(content) + 4
        total += msg_tokens
        msgs.append(Message(role=role, content=content))
        i += 1
    return msgs


class TestDumbZoneDetection:
    """Tests for dumb zone (40-60% context fill) detection."""

    def test_ok_below_dumb_zone(self) -> None:
        """Status is OK below 40% fill."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        msgs = _make_messages_for_fill(0.2)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.OK

    def test_dumb_zone_detected(self) -> None:
        """DUMB_ZONE status at 40-60% fill."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        msgs = _make_messages_for_fill(0.5)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.DUMB_ZONE
        assert "dumb zone" in result.message.lower()

    def test_dumb_zone_tracks_entry(self) -> None:
        """Entering dumb zone sets tracking flag."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        assert not mgr.in_dumb_zone

        msgs = _make_messages_for_fill(0.5)
        mgr.check(msgs)
        assert mgr.in_dumb_zone

    def test_dumb_zone_resets_below_threshold(self) -> None:
        """Dumb zone flag resets when below threshold."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        # Enter dumb zone
        msgs = _make_messages_for_fill(0.5)
        mgr.check(msgs)
        assert mgr.in_dumb_zone

        # Go below threshold
        small_msgs = _make_messages_for_fill(0.1)
        mgr.check(small_msgs)
        assert not mgr.in_dumb_zone

    def test_dumb_zone_disabled(self) -> None:
        """DUMB_ZONE not reported when fresh_context_enabled=False."""
        mgr = AutoCompactionManager(
            max_context_tokens=MAX_TOKENS,
            fresh_context_enabled=False,
        )
        msgs = _make_messages_for_fill(0.5)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.OK

    def test_warning_takes_precedence(self) -> None:
        """WARNING status at 70%+ overrides dumb zone."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        msgs = _make_messages_for_fill(0.75)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.WARNING

    def test_compaction_takes_precedence(self) -> None:
        """NEEDS_COMPACTION at 80%+ overrides everything."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        msgs = _make_messages_for_fill(0.85)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.NEEDS_COMPACTION


class TestFreshContextProtocol:
    """Tests for the fresh context handoff mechanism."""

    def test_should_refresh_at_dumb_zone_end(self) -> None:
        """should_refresh_context returns True at 60%+ fill."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        msgs = _make_messages_for_fill(0.65)
        assert mgr.should_refresh_context(msgs)

    def test_should_not_refresh_at_dumb_zone_start(self) -> None:
        """should_refresh_context returns False at 42% (just entering dumb zone)."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        msgs = _make_messages_for_fill(0.42)
        # At 42%, we're in dumb zone but below dumb_zone_end (60%)
        assert not mgr.should_refresh_context(msgs)

    def test_should_not_refresh_when_disabled(self) -> None:
        """should_refresh_context returns False when disabled."""
        mgr = AutoCompactionManager(
            max_context_tokens=MAX_TOKENS,
            fresh_context_enabled=False,
        )
        msgs = _make_messages_for_fill(0.65)
        assert not mgr.should_refresh_context(msgs)

    def test_handoff_summary_prompt(self) -> None:
        """Handoff summary prompt contains structured sections."""
        mgr = AutoCompactionManager()
        prompt = mgr.create_handoff_summary_prompt()
        assert "Current Task" in prompt
        assert "Completed Work" in prompt
        assert "Pending Work" in prompt
        assert "Key Decisions" in prompt
        assert "Critical Context" in prompt

    def test_record_fresh_context(self) -> None:
        """Recording fresh context increments counter and resets dumb zone."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)
        # Enter dumb zone
        msgs = _make_messages_for_fill(0.5)
        mgr.check(msgs)
        assert mgr.in_dumb_zone
        assert mgr.fresh_context_count == 0

        mgr.record_fresh_context()
        assert not mgr.in_dumb_zone
        assert mgr.fresh_context_count == 1

    def test_fresh_context_count_accumulates(self) -> None:
        """Fresh context count accumulates across multiple refreshes."""
        mgr = AutoCompactionManager()
        mgr.record_fresh_context()
        mgr.record_fresh_context()
        mgr.record_fresh_context()
        assert mgr.fresh_context_count == 3


class TestCompactionStatusOrder:
    """Test that statuses are checked in the correct priority order."""

    def test_status_progression(self) -> None:
        """Statuses progress correctly as fill increases."""
        mgr = AutoCompactionManager(max_context_tokens=MAX_TOKENS)

        # 20% -> OK
        result = mgr.check(_make_messages_for_fill(0.2))
        assert result.status == CompactionStatus.OK

        # 50% -> DUMB_ZONE
        result = mgr.check(_make_messages_for_fill(0.5))
        assert result.status == CompactionStatus.DUMB_ZONE

        # 75% -> WARNING
        result = mgr.check(_make_messages_for_fill(0.75))
        assert result.status == CompactionStatus.WARNING

        # 85% -> NEEDS_COMPACTION
        result = mgr.check(_make_messages_for_fill(0.85))
        assert result.status == CompactionStatus.NEEDS_COMPACTION
