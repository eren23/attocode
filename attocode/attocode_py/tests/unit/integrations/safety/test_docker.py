"""Tests for Docker sandbox."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.safety.sandbox.docker import (
    DockerOptions,
    DockerResult,
    DockerSandbox,
)


# ---------------------------------------------------------------------------
# DockerSandbox.is_available
# ---------------------------------------------------------------------------
class TestDockerIsAvailable:
    @patch("attocode.integrations.safety.sandbox.docker.shutil.which", return_value="/usr/bin/docker")
    def test_docker_found(self, _mock: MagicMock) -> None:
        assert DockerSandbox.is_available() is True

    @patch("attocode.integrations.safety.sandbox.docker.shutil.which", return_value=None)
    def test_docker_not_found(self, _mock: MagicMock) -> None:
        assert DockerSandbox.is_available() is False


# ---------------------------------------------------------------------------
# DockerSandbox.validate
# ---------------------------------------------------------------------------
class TestDockerValidate:
    @patch.object(DockerSandbox, "is_available", return_value=True)
    def test_allowed_when_available(self, _mock: MagicMock) -> None:
        sb = DockerSandbox()
        result = sb.validate("rm -rf /")
        assert result.allowed
        assert result.command == "rm -rf /"

    @patch.object(DockerSandbox, "is_available", return_value=False)
    def test_denied_when_unavailable(self, _mock: MagicMock) -> None:
        sb = DockerSandbox()
        result = sb.validate("echo hi")
        assert not result.allowed
        assert "not available" in result.reason.lower()


# ---------------------------------------------------------------------------
# DockerSandbox.execute — docker args construction
# ---------------------------------------------------------------------------
class TestDockerExecute:
    @pytest.mark.asyncio
    @patch.object(DockerSandbox, "is_available", return_value=False)
    async def test_raises_when_unavailable(self, _mock: MagicMock) -> None:
        sb = DockerSandbox()
        with pytest.raises(RuntimeError, match="not available"):
            await sb.execute("echo hi")

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_basic_execution(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello\n", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox()
        output, code = await sb.execute("echo hello", working_dir="/tmp/proj")
        assert code == 0
        assert "hello" in output

        # Verify docker args
        args = mock_exec.call_args[0]
        assert args[0] == "docker"
        assert "run" in args
        assert "--rm" in args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_memory_limit(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox(options=DockerOptions(max_memory_mb=256))
        await sb.execute("true", working_dir="/tmp")

        args = mock_exec.call_args[0]
        assert "--memory=256m" in args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_network_disabled(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox(options=DockerOptions(network_allowed=False))
        await sb.execute("true", working_dir="/tmp")

        args = mock_exec.call_args[0]
        assert "--network=none" in args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_network_enabled(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox(options=DockerOptions(network_allowed=True))
        await sb.execute("true", working_dir="/tmp")

        args = mock_exec.call_args[0]
        assert "--network=none" not in args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_custom_image(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox(options=DockerOptions(image="node:20-slim"))
        await sb.execute("node -v", working_dir="/tmp")

        args = mock_exec.call_args[0]
        assert "node:20-slim" in args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_working_dir_mounted(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox()
        await sb.execute("ls", working_dir="/home/user/project")

        args = mock_exec.call_args[0]
        assert "-v" in args
        mount_idx = [i for i, a in enumerate(args) if a == "-v"]
        # At least one mount should reference working dir
        mounts = [args[i + 1] for i in mount_idx]
        assert any("/home/user/project:/workspace" in m for m in mounts)

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_env_vars_passed(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox()
        await sb.execute("env", working_dir="/tmp", env={"FOO": "bar"})

        args = mock_exec.call_args[0]
        assert "-e" in args
        env_idx = [i for i, a in enumerate(args) if a == "-e"]
        env_args = [args[i + 1] for i in env_idx]
        assert "TERM=dumb" in env_args
        assert "FOO=bar" in env_args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_timeout_kills_process(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        # First call (inside wait_for) raises; second (after kill) returns empty
        mock_proc.communicate.side_effect = [
            asyncio.TimeoutError(),
            (b"", b""),
        ]
        mock_proc.kill = MagicMock()
        mock_exec.return_value = mock_proc

        sb = DockerSandbox(options=DockerOptions(timeout=1.0))
        output, code = await sb.execute("sleep 999", working_dir="/tmp")
        assert code == -1
        assert "timed out" in output.lower()
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_stderr_merged(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"stdout\n", b"stderr\n")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        sb = DockerSandbox()
        output, code = await sb.execute("failing_cmd", working_dir="/tmp")
        assert code == 1
        assert "stdout" in output
        assert "stderr" in output

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_output_truncation(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"x" * 2_000_000, b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox(options=DockerOptions(max_output_bytes=100))
        output, code = await sb.execute("big", working_dir="/tmp")
        assert code == 0
        assert "truncated" in output
        assert len(output) < 200

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.docker.asyncio.create_subprocess_exec")
    @patch.object(DockerSandbox, "is_available", return_value=True)
    async def test_command_passed_via_sh(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = DockerSandbox()
        await sb.execute("echo hello && pwd", working_dir="/tmp")

        args = mock_exec.call_args[0]
        assert "/bin/sh" in args
        assert "-c" in args
        assert "echo hello && pwd" in args


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------
class TestDockerDataclasses:
    def test_result_defaults(self) -> None:
        r = DockerResult(allowed=True)
        assert r.allowed
        assert r.reason == ""

    def test_options_defaults(self) -> None:
        opts = DockerOptions()
        assert opts.image == "python:3.12-slim"
        assert opts.max_memory_mb == 512
        assert opts.max_cpu_seconds == 30
        assert opts.network_allowed is False
        assert opts.timeout == 300.0
