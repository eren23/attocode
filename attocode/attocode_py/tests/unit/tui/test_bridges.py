"""Tests for TUI bridges."""

from __future__ import annotations

import asyncio

import pytest

from attocode.tui.bridges.approval_bridge import (
    ApprovalBridge,
    BudgetBridge,
    _first_arg,
)
from attocode.tui.dialogs.approval import ApprovalResult


class TestApprovalBridge:
    def test_initial_state(self) -> None:
        bridge = ApprovalBridge()
        assert not bridge.has_pending()

    @pytest.mark.asyncio
    async def test_request_and_resolve(self) -> None:
        bridge = ApprovalBridge()
        requests: list[tuple] = []

        def handler(name, args, level, ctx):
            requests.append((name, args, level, ctx))

        bridge.set_handler(handler)

        # Start request in background
        async def do_request():
            return await bridge.request_approval("bash", {"command": "ls"})

        task = asyncio.create_task(do_request())

        # Give the task a moment to start
        await asyncio.sleep(0.01)

        assert bridge.has_pending()
        assert len(requests) == 1
        assert requests[0][0] == "bash"

        # Resolve
        bridge.resolve(ApprovalResult(approved=True))
        result = await task

        assert result.approved is True
        assert not bridge.has_pending()

    @pytest.mark.asyncio
    async def test_timeout_returns_denied(self) -> None:
        bridge = ApprovalBridge()
        bridge.set_handler(lambda *_: None)

        result = await bridge.request_approval(
            "bash", {"command": "ls"}, timeout=0.05
        )
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_always_allow_pattern(self) -> None:
        bridge = ApprovalBridge()
        resolved = False

        def handler(name, args, level, ctx):
            nonlocal resolved
            resolved = True

        bridge.set_handler(handler)

        # First request - resolve with always_allow
        task = asyncio.create_task(
            bridge.request_approval(
                "bash", {"command": "npm test"}, danger_level="low"
            )
        )
        await asyncio.sleep(0.01)
        bridge.resolve(ApprovalResult(approved=True, always_allow=True))
        await task

        # Second request - should auto-approve
        resolved = False
        result = await bridge.request_approval(
            "bash", {"command": "npm test"}, danger_level="low"
        )
        assert result.approved is True
        assert not resolved  # Handler should NOT have been called

    def test_clear_always_allowed(self) -> None:
        bridge = ApprovalBridge()
        bridge._always_allowed.add("bash:npm test")
        bridge.clear_always_allowed()
        assert len(bridge._always_allowed) == 0


class TestBudgetBridge:
    def test_initial_state(self) -> None:
        bridge = BudgetBridge()
        assert not bridge.has_pending()

    @pytest.mark.asyncio
    async def test_request_and_resolve(self) -> None:
        bridge = BudgetBridge()
        bridge.set_handler(lambda *_: None)

        task = asyncio.create_task(
            bridge.request_extension(100000, 0.9, 50000, "Need more")
        )
        await asyncio.sleep(0.01)

        assert bridge.has_pending()
        bridge.resolve(True)
        result = await task

        assert result is True

    @pytest.mark.asyncio
    async def test_denied(self) -> None:
        bridge = BudgetBridge()
        bridge.set_handler(lambda *_: None)

        task = asyncio.create_task(
            bridge.request_extension(100000, 0.9, 50000)
        )
        await asyncio.sleep(0.01)
        bridge.resolve(False)
        result = await task

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        bridge = BudgetBridge()
        bridge.set_handler(lambda *_: None)

        result = await bridge.request_extension(
            100000, 0.9, 50000, timeout=0.05
        )
        assert result is False


class TestFirstArg:
    def test_empty(self) -> None:
        assert _first_arg({}) == ""

    def test_simple(self) -> None:
        assert _first_arg({"command": "ls -la"}) == "ls -la"

    def test_truncates_long(self) -> None:
        result = _first_arg({"path": "x" * 100})
        assert len(result) <= 50
