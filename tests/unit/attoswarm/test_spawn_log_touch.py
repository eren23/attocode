"""Test that SubprocessAdapter.spawn() creates the log file eagerly."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from attoswarm.adapters.base import AgentProcessSpec, SubprocessAdapter


def test_spawn_creates_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "agent-test.log"
    spec = AgentProcessSpec(
        agent_id="test-1",
        backend="claude",
        binary="true",  # /usr/bin/true — exits immediately
        args=[],
        log_file=str(log_file),
    )

    adapter = SubprocessAdapter("claude")

    async def _run() -> None:
        handle = await adapter.spawn(spec)
        # Log file should exist before the process produces any output
        assert log_file.exists()
        assert log_file.stat().st_size == 0
        await adapter.terminate(handle, "test done")

    asyncio.run(_run())


def test_spawn_works_without_log_file() -> None:
    """When log_file is None, spawn should still work (no touch)."""
    spec = AgentProcessSpec(
        agent_id="test-2",
        backend="claude",
        binary="true",
        args=[],
        log_file=None,
    )
    adapter = SubprocessAdapter("claude")

    async def _run() -> None:
        handle = await adapter.spawn(spec)
        await adapter.terminate(handle, "test done")

    asyncio.run(_run())
