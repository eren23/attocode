"""Tests for cancellation system."""

from __future__ import annotations

import asyncio

import pytest

from attocode.integrations.budget.cancellation import (
    CancellationToken,
    CancellationTokenSource,
)


class TestCancellationToken:
    def test_not_cancelled_initially(self) -> None:
        token = CancellationToken()
        assert not token.is_cancelled

    def test_cancel(self) -> None:
        token = CancellationToken()
        token.cancel("user requested")
        assert token.is_cancelled
        assert token.reason == "user requested"

    def test_check_raises_when_cancelled(self) -> None:
        token = CancellationToken()
        token.cancel()
        with pytest.raises(asyncio.CancelledError):
            token.check()

    def test_check_ok_when_not_cancelled(self) -> None:
        token = CancellationToken()
        token.check()  # Should not raise

    @pytest.mark.asyncio
    async def test_wait(self) -> None:
        token = CancellationToken()

        async def cancel_later():
            await asyncio.sleep(0.01)
            token.cancel("timeout")

        asyncio.create_task(cancel_later())
        await asyncio.wait_for(token.wait(), timeout=1.0)
        assert token.is_cancelled


class TestCancellationTokenSource:
    def test_create(self) -> None:
        source = CancellationTokenSource()
        assert not source.token.is_cancelled

    def test_cancel_source(self) -> None:
        source = CancellationTokenSource()
        source.cancel("done")
        assert source.token.is_cancelled
        assert source.token.reason == "done"

    def test_linked_cancellation(self) -> None:
        parent = CancellationTokenSource()
        child = parent.create_linked()
        parent.cancel("parent done")
        assert child.token.is_cancelled
        assert child.token.reason == "parent done"

    def test_child_independent_cancel(self) -> None:
        parent = CancellationTokenSource()
        child = parent.create_linked()
        child.cancel("child done")
        assert child.token.is_cancelled
        assert not parent.token.is_cancelled

    def test_already_cancelled_parent(self) -> None:
        parent = CancellationTokenSource()
        parent.cancel("already")
        child = parent.create_linked()
        assert child.token.is_cancelled

    def test_dispose(self) -> None:
        parent = CancellationTokenSource()
        child = parent.create_linked()
        parent.dispose()
        # After dispose, cancelling parent won't affect child
        parent.cancel("late")
        assert not child.token.is_cancelled
