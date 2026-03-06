"""Tests for TUI dialogs."""

from __future__ import annotations

from attocode.tui.dialogs.approval import ApprovalResult


class TestApprovalResult:
    def test_approved(self) -> None:
        result = ApprovalResult(approved=True)
        assert result.approved is True
        assert result.always_allow is False
        assert result.deny_reason is None

    def test_always_allow(self) -> None:
        result = ApprovalResult(approved=True, always_allow=True)
        assert result.approved is True
        assert result.always_allow is True

    def test_denied(self) -> None:
        result = ApprovalResult(approved=False)
        assert result.approved is False

    def test_denied_with_reason(self) -> None:
        result = ApprovalResult(approved=False, deny_reason="Too dangerous")
        assert result.deny_reason == "Too dangerous"
