"""Tests for bash execution tool."""

from __future__ import annotations

import pytest

from attocode.tools.bash import create_bash_tool, execute_bash


class TestExecuteBash:
    @pytest.mark.asyncio
    async def test_simple_command(self) -> None:
        result = await execute_bash({"command": "echo hello"})
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_exit_code(self) -> None:
        result = await execute_bash({"command": "false"})
        assert "Exit code" in result

    @pytest.mark.asyncio
    async def test_stderr(self) -> None:
        result = await execute_bash({"command": "echo error >&2"})
        assert "STDERR" in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_working_dir(self, tmp_workdir) -> None:
        result = await execute_bash({"command": "pwd"}, working_dir=str(tmp_workdir))
        assert str(tmp_workdir) in result

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        result = await execute_bash({"command": "sleep 10"}, timeout=0.5)
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_combined_stdout_stderr(self) -> None:
        result = await execute_bash({"command": "echo out && echo err >&2"})
        assert "out" in result
        assert "err" in result

    @pytest.mark.asyncio
    async def test_no_output(self) -> None:
        result = await execute_bash({"command": "true"})
        assert "no output" in result.lower()

    @pytest.mark.asyncio
    async def test_multiline_output(self) -> None:
        result = await execute_bash({"command": "printf 'line1\\nline2\\nline3'"})
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result


class TestCreateBashTool:
    def test_tool_spec(self) -> None:
        tool = create_bash_tool()
        assert tool.name == "bash"
        assert tool.spec.danger_level.value == "dangerous"

    @pytest.mark.asyncio
    async def test_execute_via_tool(self) -> None:
        tool = create_bash_tool()
        result = await tool.execute({"command": "echo via_tool"})
        assert "via_tool" in result
