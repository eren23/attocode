"""Tests for basic sandbox."""

from __future__ import annotations

import pytest

from attocode.integrations.safety.sandbox.basic import (
    BasicSandbox,
    SandboxOptions,
)


class TestBasicSandboxValidation:
    def test_allowed_command(self) -> None:
        sb = BasicSandbox()
        result = sb.validate("ls -la")
        assert result.allowed

    def test_blocked_command(self) -> None:
        sb = BasicSandbox()
        result = sb.validate("rm important_file")
        assert not result.allowed
        assert "blocked" in result.reason.lower()

    def test_unknown_blocked(self) -> None:
        sb = BasicSandbox()
        result = sb.validate("obscure_binary --flag")
        assert not result.allowed

    def test_empty_allowed(self) -> None:
        sb = BasicSandbox()
        assert sb.validate("").allowed

    def test_git_allowed(self) -> None:
        sb = BasicSandbox()
        assert sb.validate("git status").allowed

    def test_python_allowed(self) -> None:
        sb = BasicSandbox()
        assert sb.validate("python -c 'print(1)'").allowed

    def test_sudo_blocked(self) -> None:
        sb = BasicSandbox()
        assert not sb.validate("sudo ls").allowed

    def test_custom_allowlist(self) -> None:
        sb = BasicSandbox(options=SandboxOptions(
            allowed_commands=frozenset({"my_tool"}),
            blocked_commands=frozenset(),
        ))
        assert sb.validate("my_tool --flag").allowed
        assert not sb.validate("other_tool").allowed


class TestBasicSandboxExecution:
    @pytest.mark.asyncio
    async def test_execute_allowed(self) -> None:
        sb = BasicSandbox()
        output, code = await sb.execute("echo hello")
        assert code == 0
        assert "hello" in output

    @pytest.mark.asyncio
    async def test_execute_blocked(self) -> None:
        sb = BasicSandbox()
        with pytest.raises(PermissionError):
            await sb.execute("rm /tmp/nonexistent")

    @pytest.mark.asyncio
    async def test_execute_with_working_dir(self) -> None:
        sb = BasicSandbox()
        output, code = await sb.execute("pwd", working_dir="/tmp")
        assert code == 0
        assert "/tmp" in output or "/private/tmp" in output
