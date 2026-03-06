"""Tests for hook manager."""

from __future__ import annotations

import pytest

from attocode.integrations.utilities.hooks import HookDefinition, HookManager


class TestHookManager:
    def test_from_config(self) -> None:
        config = {
            "hooks": [
                {"event": "tool.before", "command": "echo start"},
                {"event": "run.after", "command": "echo done", "timeout": 60},
            ]
        }
        hm = HookManager.from_config(config)
        assert len(hm.hooks) == 2

    def test_from_empty_config(self) -> None:
        hm = HookManager.from_config({})
        assert len(hm.hooks) == 0

    def test_get_hooks(self) -> None:
        hm = HookManager(hooks=[
            HookDefinition(event="tool.before", command="echo 1"),
            HookDefinition(event="tool.after", command="echo 2"),
            HookDefinition(event="tool.before", command="echo 3"),
        ])
        matching = hm.get_hooks("tool.before")
        assert len(matching) == 2

    def test_disabled_hooks_skipped(self) -> None:
        hm = HookManager(hooks=[
            HookDefinition(event="run.after", command="echo 1", enabled=False),
        ])
        assert len(hm.get_hooks("run.after")) == 0

    @pytest.mark.asyncio
    async def test_run_hooks(self) -> None:
        hm = HookManager(hooks=[
            HookDefinition(event="test", command="echo hello"),
        ])
        results = await hm.run_hooks("test")
        assert len(results) == 1
        assert results[0].success
        assert "hello" in results[0].output

    @pytest.mark.asyncio
    async def test_no_matching_hooks(self) -> None:
        hm = HookManager(hooks=[
            HookDefinition(event="other", command="echo x"),
        ])
        results = await hm.run_hooks("test")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_failing_hook(self) -> None:
        hm = HookManager(hooks=[
            HookDefinition(event="test", command="exit 1"),
        ])
        results = await hm.run_hooks("test")
        assert len(results) == 1
        assert not results[0].success
        assert results[0].exit_code == 1

    @pytest.mark.asyncio
    async def test_timeout_hook(self) -> None:
        hm = HookManager(hooks=[
            HookDefinition(event="test", command="sleep 10", timeout=0.1),
        ])
        results = await hm.run_hooks("test")
        assert len(results) == 1
        assert not results[0].success
        assert "timed out" in results[0].error.lower()
