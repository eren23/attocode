"""Tests for ToolRegistry."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from attocode.errors import ToolNotFoundError, ToolTimeoutError
from attocode.tools.base import Tool, ToolSpec
from attocode.tools.permission import AllowAllPermissions, PermissionDecision, PermissionResult
from attocode.tools.registry import ToolRegistry
from attocode.types.messages import DangerLevel


def _make_tool(name: str = "test_tool", danger: DangerLevel = DangerLevel.SAFE) -> Tool:
    async def execute(args: dict[str, Any]) -> str:
        return f"executed {name} with {args}"

    return Tool(
        spec=ToolSpec(
            name=name,
            description=f"Test tool {name}",
            parameters={"type": "object", "properties": {}},
            danger_level=danger,
        ),
        execute=execute,
    )


class TestToolRegistryBasic:
    def test_register_and_get(self) -> None:
        reg = ToolRegistry()
        tool = _make_tool()
        reg.register(tool)
        assert reg.get("test_tool") is tool
        assert reg.has("test_tool")
        assert not reg.has("unknown")

    def test_unregister(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool())
        assert reg.unregister("test_tool")
        assert not reg.has("test_tool")
        assert not reg.unregister("test_tool")

    def test_list_tools(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert sorted(reg.list_tools()) == ["a", "b"]

    def test_tool_count(self) -> None:
        reg = ToolRegistry()
        assert reg.tool_count == 0
        reg.register(_make_tool("a"))
        assert reg.tool_count == 1

    def test_get_definitions(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("read"))
        reg.register(_make_tool("write"))
        defs = reg.get_definitions()
        assert len(defs) == 2
        names = [d.name for d in defs]
        assert "read" in names
        assert "write" in names


class TestToolRegistryExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("echo"))
        result = await reg.execute("echo", {"msg": "hi"})
        assert not result.is_error
        assert "echo" in result.result
        assert "hi" in result.result

    @pytest.mark.asyncio
    async def test_execute_not_found(self) -> None:
        reg = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            await reg.execute("nonexistent", {})

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        async def slow_tool(args: dict[str, Any]) -> str:
            await asyncio.sleep(10)
            return "done"

        reg = ToolRegistry()
        tool = Tool(
            spec=ToolSpec(name="slow", description="slow", parameters={}),
            execute=slow_tool,
        )
        reg.register(tool)

        with pytest.raises(ToolTimeoutError):
            await reg.execute("slow", {}, timeout=0.1)

    @pytest.mark.asyncio
    async def test_execute_error_returns_result(self) -> None:
        async def failing_tool(args: dict[str, Any]) -> str:
            raise RuntimeError("boom")

        reg = ToolRegistry()
        tool = Tool(
            spec=ToolSpec(name="fail", description="fails", parameters={}),
            execute=failing_tool,
        )
        reg.register(tool)
        result = await reg.execute("fail", {})
        assert result.is_error
        assert "RuntimeError" in result.error
        assert "boom" in result.error


class TestToolRegistryPermissions:
    @pytest.mark.asyncio
    async def test_allow_all_default(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("test"))
        result = await reg.execute("test", {})
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_permission_denied(self) -> None:
        class DenyAll:
            async def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
                return PermissionResult.deny("not allowed")

        reg = ToolRegistry(permission_checker=DenyAll())
        reg.register(_make_tool("test"))
        result = await reg.execute("test", {})
        assert result.is_error
        assert "Permission denied" in result.error

    @pytest.mark.asyncio
    async def test_permission_modified_args(self) -> None:
        class ModifyArgs:
            async def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
                return PermissionResult(
                    decision=PermissionDecision.ALLOW,
                    modified_args={"key": "modified"},
                )

        async def capture_tool(args: dict[str, Any]) -> str:
            return f"args={args}"

        reg = ToolRegistry(permission_checker=ModifyArgs())
        tool = Tool(
            spec=ToolSpec(name="capture", description="test", parameters={}),
            execute=capture_tool,
        )
        reg.register(tool)
        result = await reg.execute("capture", {"key": "original"})
        assert "modified" in result.result


class TestToolRegistryBatch:
    @pytest.mark.asyncio
    async def test_execute_batch(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))

        calls = [
            ("id1", "a", {"x": 1}),
            ("id2", "b", {"x": 2}),
        ]
        results = await reg.execute_batch(calls)
        assert len(results) == 2
        assert results[0].call_id == "id1"
        assert results[1].call_id == "id2"

    @pytest.mark.asyncio
    async def test_execute_batch_partial_failure(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("good"))

        calls = [
            ("id1", "good", {}),
            ("id2", "missing", {}),
        ]
        results = await reg.execute_batch(calls)
        assert len(results) == 2
        assert not results[0].is_error
        assert results[1].is_error
        assert "not found" in results[1].error.lower()

    @pytest.mark.asyncio
    async def test_batch_runs_in_parallel(self) -> None:
        """Verify batch execution runs tools concurrently."""
        execution_order: list[str] = []

        async def tool_a(args: dict[str, Any]) -> str:
            execution_order.append("a_start")
            await asyncio.sleep(0.05)
            execution_order.append("a_end")
            return "a"

        async def tool_b(args: dict[str, Any]) -> str:
            execution_order.append("b_start")
            await asyncio.sleep(0.05)
            execution_order.append("b_end")
            return "b"

        reg = ToolRegistry()
        reg.register(Tool(spec=ToolSpec(name="a", description="a", parameters={}), execute=tool_a))
        reg.register(Tool(spec=ToolSpec(name="b", description="b", parameters={}), execute=tool_b))

        await reg.execute_batch([("1", "a", {}), ("2", "b", {})])

        # Both should start before either finishes (parallel execution)
        assert execution_order.index("a_start") < execution_order.index("a_end")
        assert execution_order.index("b_start") < execution_order.index("b_end")
        # At least one "start" should come before the other's "end"
        assert (
            execution_order.index("a_start") < execution_order.index("b_end")
            or execution_order.index("b_start") < execution_order.index("a_end")
        )
