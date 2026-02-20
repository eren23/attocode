"""Tool registry for managing and executing tools."""

from __future__ import annotations

import asyncio
from typing import Any

from attocode.errors import ToolNotFoundError, ToolTimeoutError
from attocode.tools.base import Tool
from attocode.tools.permission import AllowAllPermissions, PermissionChecker
from attocode.types.messages import ToolDefinition, ToolResult


class ToolRegistry:
    """Registry for tool management and execution."""

    def __init__(
        self,
        *,
        permission_checker: PermissionChecker | None = None,
        default_timeout: float = 60.0,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._permission_checker = permission_checker or AllowAllPermissions()
        self._default_timeout = default_timeout

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_definitions(self) -> list[ToolDefinition]:
        return [tool.to_definition() for tool in self._tools.values()]

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(tool_name)

        perm = await self._permission_checker.check(tool_name, args)
        if not perm.allowed:
            return ToolResult(call_id="", error=f"Permission denied: {perm.reason}")

        effective_args = perm.modified_args or args
        effective_timeout = timeout or self._default_timeout

        try:
            result = await asyncio.wait_for(
                tool.execute(effective_args),
                timeout=effective_timeout,
            )
            return ToolResult(call_id="", result=result)
        except asyncio.TimeoutError:
            raise ToolTimeoutError(tool_name, effective_timeout)
        except Exception as e:
            return ToolResult(call_id="", error=f"{type(e).__name__}: {e}")

    async def execute_batch(
        self,
        calls: list[tuple[str, str, dict[str, Any]]],
        *,
        timeout: float | None = None,
    ) -> list[ToolResult]:
        async def _execute_one(call_id: str, tool_name: str, args: dict[str, Any]) -> ToolResult:
            try:
                result = await self.execute(tool_name, args, timeout=timeout)
                return ToolResult(call_id=call_id, result=result.result, error=result.error)
            except ToolNotFoundError:
                return ToolResult(call_id=call_id, error=f"Tool not found: {tool_name}")
            except Exception as e:
                return ToolResult(call_id=call_id, error=f"{type(e).__name__}: {e}")

        tasks = [_execute_one(cid, tn, a) for cid, tn, a in calls]
        return list(await asyncio.gather(*tasks))
