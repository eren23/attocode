"""Tests for the async subagent manager."""

import asyncio

import pytest

from attocode.integrations.agents.async_subagent import (
    AsyncSubagentManager,
    AsyncSubagentConfig,
    SubagentHandle,
    SubagentStatus,
)


class TestSubagentDataclasses:
    def test_handle_defaults(self):
        h = SubagentHandle(id="sub-1", agent_type="coder", task="write tests")
        assert h.status == SubagentStatus.PENDING
        assert h.result is None
        assert h.error is None
        assert h.tokens_used == 0

    def test_config_defaults(self):
        cfg = AsyncSubagentConfig()
        assert cfg.max_concurrent == 5
        assert cfg.default_timeout == 300.0
        assert cfg.collect_timeout == 10.0

    def test_status_enum_values(self):
        assert SubagentStatus.PENDING == "pending"
        assert SubagentStatus.RUNNING == "running"
        assert SubagentStatus.COMPLETED == "completed"
        assert SubagentStatus.TIMED_OUT == "timed_out"
        assert SubagentStatus.CANCELLED == "cancelled"


class TestAsyncSubagentManager:
    def test_initialization(self):
        mgr = AsyncSubagentManager(AsyncSubagentConfig(max_concurrent=3))
        assert mgr.config.max_concurrent == 3
        stats = mgr.get_stats()
        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_spawn_and_complete(self):
        mgr = AsyncSubagentManager(AsyncSubagentConfig(max_concurrent=2))

        async def work():
            return "done"

        handle = await mgr.spawn("coder", "fix bug", work)
        assert handle.id == "sub-1"
        assert handle.agent_type == "coder"

        results = await mgr.wait_all(timeout=5.0)
        assert len(results) == 1
        completed = [r for r in results if r.status == SubagentStatus.COMPLETED]
        assert len(completed) == 1
        assert completed[0].result == "done"

    @pytest.mark.asyncio
    async def test_spawn_timeout(self):
        mgr = AsyncSubagentManager(AsyncSubagentConfig(max_concurrent=2))

        async def slow_work():
            await asyncio.sleep(10)

        handle = await mgr.spawn("researcher", "deep analysis", slow_work, timeout=0.1)
        results = await mgr.wait_all(timeout=5.0)
        timed_out = [r for r in results if r.status == SubagentStatus.TIMED_OUT]
        assert len(timed_out) == 1
        assert "Timed out" in timed_out[0].error

    @pytest.mark.asyncio
    async def test_spawn_failure(self):
        mgr = AsyncSubagentManager()

        async def failing_work():
            raise ValueError("test error")

        handle = await mgr.spawn("coder", "bad task", failing_work)
        results = await mgr.wait_all(timeout=5.0)
        failed = [r for r in results if r.status == SubagentStatus.FAILED]
        assert len(failed) == 1
        assert "test error" in failed[0].error

    @pytest.mark.asyncio
    async def test_semaphore_concurrency_limit(self):
        max_conc = 2
        mgr = AsyncSubagentManager(AsyncSubagentConfig(max_concurrent=max_conc))
        concurrency_log: list[int] = []
        active = 0
        lock = asyncio.Lock()

        async def tracked_work():
            nonlocal active
            async with lock:
                active += 1
                concurrency_log.append(active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1

        for i in range(5):
            await mgr.spawn("worker", f"task-{i}", tracked_work)

        await mgr.wait_all(timeout=10.0)
        assert max(concurrency_log) <= max_conc

    @pytest.mark.asyncio
    async def test_cancel_subagent(self):
        mgr = AsyncSubagentManager()

        async def long_work():
            await asyncio.sleep(100)

        handle = await mgr.spawn("coder", "long task", long_work)
        await asyncio.sleep(0.05)
        cancelled = await mgr.cancel(handle.id)
        assert cancelled is True
        await mgr.wait_all(timeout=5.0)
        assert handle.status == SubagentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_get_stats(self):
        mgr = AsyncSubagentManager()

        async def work():
            return 42

        await mgr.spawn("coder", "t1", work)
        await mgr.wait_all(timeout=5.0)
        stats = mgr.get_stats()
        assert stats["total"] == 1
        assert stats.get("completed", 0) == 1

    def test_clear(self):
        mgr = AsyncSubagentManager()
        mgr.clear()
        assert mgr.get_stats()["total"] == 0

    @pytest.mark.asyncio
    async def test_wait_all_empty(self):
        mgr = AsyncSubagentManager()
        results = await mgr.wait_all()
        assert results == []
