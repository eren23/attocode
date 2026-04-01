"""Tests for lifecycle utilities (generation counter, shutdown, pending tracker)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from attocode.integrations.lifecycle import (
    GenerationCounter,
    GenerationGuardedFuture,
    GracefulShutdown,
    PendingRequestTracker,
)


def test_generation_counter_advance_and_is_current() -> None:
    g = GenerationCounter()
    assert g.current == 0
    first = g.advance()
    assert first == 1
    assert g.is_current(1) is True
    assert g.is_current(0) is False
    g.advance()
    assert g.is_current(1) is False
    assert g.is_current(2) is True


def test_generation_counter_reset() -> None:
    g = GenerationCounter()
    g.advance()
    g.reset()
    assert g.current == 0


@pytest.mark.asyncio
async def test_generation_guarded_future_returns_result_when_stable() -> None:
    g = GenerationCounter()

    async def work() -> int:
        return 42

    gf = GenerationGuardedFuture(g, work())
    assert await gf.wait() == 42


@pytest.mark.asyncio
async def test_generation_guarded_future_discards_when_generation_advances() -> None:
    g = GenerationCounter()

    async def slow_work() -> int:
        await asyncio.sleep(0.05)
        return 99

    gf = GenerationGuardedFuture(g, slow_work())
    g.advance()
    assert await gf.wait() is None


@pytest.mark.asyncio
async def test_graceful_shutdown_shutdown_exit_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.close = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    proc.kill = MagicMock()

    requests: list[tuple[str, Any]] = []

    async def request_fn(method: str, params: Any) -> None:
        requests.append((method, params))

    def notify_fn(method: str, params: Any) -> None:
        requests.append(("notify", method, params))

    gs = GracefulShutdown(
        proc,  # type: ignore[arg-type]
        request_fn,
        notify_fn,
        timeout=5.0,
        name="test-lsp",
    )
    assert gs.is_stopping is False
    await gs.shutdown()
    assert gs.is_stopping is False
    proc.stdin.close.assert_called_once()
    proc.wait.assert_awaited()
    assert ("shutdown", None) in requests
    assert ("notify", "exit", None) in requests


@pytest.mark.asyncio
async def test_graceful_shutdown_kills_on_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.close = MagicMock()
    proc.wait = AsyncMock(side_effect=[TimeoutError(), 0])
    proc.kill = MagicMock()

    async def request_fn(method: str, params: Any) -> None:
        return None

    gs = GracefulShutdown(
        proc,  # type: ignore[arg-type]
        request_fn,
        lambda _m, _p: None,
        timeout=0.01,
        name="stub",
    )
    await gs.shutdown()
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_pending_request_tracker_resolve() -> None:
    t = PendingRequestTracker()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    rid = t.track(fut)

    async def resolver() -> None:
        await asyncio.sleep(0.01)
        t.resolve(rid, {"ok": True})

    result, _ = await asyncio.gather(t.wait(rid), resolver())
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_pending_request_tracker_wait_unknown_raises() -> None:
    t = PendingRequestTracker()
    with pytest.raises(KeyError, match="No tracked request"):
        await t.wait(9999)


@pytest.mark.asyncio
async def test_pending_request_tracker_cancel_all() -> None:
    t = PendingRequestTracker()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    t.track(fut)
    assert t.count >= 1
    t.cancel_all()
    assert fut.cancelled()


@pytest.mark.asyncio
async def test_pending_request_tracker_reject() -> None:
    t = PendingRequestTracker()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    rid = t.track(fut)

    async def failer() -> None:
        await asyncio.sleep(0.01)
        t.reject(rid, ValueError("rpc failed"))

    with pytest.raises(ValueError, match="rpc failed"):
        await asyncio.gather(t.wait(rid), failer())
