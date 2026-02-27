"""Tests for Seatbelt sandbox (macOS sandbox-exec)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.safety.sandbox.seatbelt import (
    SeatbeltOptions,
    SeatbeltResult,
    SeatbeltSandbox,
    _generate_profile,
    _shell_quote,
)


# ---------------------------------------------------------------------------
# _shell_quote
# ---------------------------------------------------------------------------
class TestShellQuote:
    def test_simple_string(self) -> None:
        assert _shell_quote("hello") == "'hello'"

    def test_single_quote_escaped(self) -> None:
        assert _shell_quote("it's") == "'it'\\''s'"

    def test_empty(self) -> None:
        assert _shell_quote("") == "''"

    def test_spaces(self) -> None:
        assert _shell_quote("a b c") == "'a b c'"


# ---------------------------------------------------------------------------
# _generate_profile
# ---------------------------------------------------------------------------
class TestGenerateProfile:
    def test_contains_version(self) -> None:
        profile = _generate_profile(SeatbeltOptions(), "/tmp/work")
        assert "(version 1)" in profile

    def test_deny_default(self) -> None:
        profile = _generate_profile(SeatbeltOptions(), "/tmp/work")
        assert "(deny default)" in profile

    def test_working_dir_writable(self) -> None:
        profile = _generate_profile(SeatbeltOptions(), "/tmp/work")
        assert '(allow file-write* (subpath "/tmp/work"))' in profile

    def test_readable_paths_included(self) -> None:
        opts = SeatbeltOptions(readable_paths=["/usr/local"])
        profile = _generate_profile(opts, "/tmp/work")
        assert "file-read*" in profile

    def test_writable_paths_included(self) -> None:
        opts = SeatbeltOptions(writable_paths=["/tmp/extra"])
        profile = _generate_profile(opts, "/tmp/work")
        assert "file-write*" in profile

    def test_network_allowed(self) -> None:
        opts = SeatbeltOptions(network_allowed=True)
        profile = _generate_profile(opts, "/tmp/work")
        assert "(allow network*)" in profile

    def test_network_denied(self) -> None:
        opts = SeatbeltOptions(network_allowed=False)
        profile = _generate_profile(opts, "/tmp/work")
        assert "(allow network*)" not in profile
        assert "Network access denied" in profile

    def test_dot_resolves_to_working_dir(self) -> None:
        opts = SeatbeltOptions(writable_paths=["."])
        profile = _generate_profile(opts, "/my/project")
        assert "/my/project" in profile

    def test_system_paths_readable(self) -> None:
        profile = _generate_profile(SeatbeltOptions(), "/tmp/work")
        assert '(subpath "/usr")' in profile
        assert '(subpath "/bin")' in profile
        assert '(subpath "/opt/homebrew")' in profile


# ---------------------------------------------------------------------------
# SeatbeltSandbox.is_available
# ---------------------------------------------------------------------------
class TestSeatbeltIsAvailable:
    @patch("attocode.integrations.safety.sandbox.seatbelt.sys")
    def test_not_darwin(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "linux"
        assert SeatbeltSandbox.is_available() is False

    @patch("attocode.integrations.safety.sandbox.seatbelt.os.path.exists", return_value=True)
    @patch("attocode.integrations.safety.sandbox.seatbelt.sys")
    def test_darwin_with_sandbox_exec(self, mock_sys: MagicMock, mock_exists: MagicMock) -> None:
        mock_sys.platform = "darwin"
        assert SeatbeltSandbox.is_available() is True

    @patch("attocode.integrations.safety.sandbox.seatbelt.os.path.exists", return_value=False)
    @patch("attocode.integrations.safety.sandbox.seatbelt.sys")
    def test_darwin_without_sandbox_exec(self, mock_sys: MagicMock, mock_exists: MagicMock) -> None:
        mock_sys.platform = "darwin"
        assert SeatbeltSandbox.is_available() is False


# ---------------------------------------------------------------------------
# SeatbeltSandbox.validate
# ---------------------------------------------------------------------------
class TestSeatbeltValidate:
    @patch.object(SeatbeltSandbox, "is_available", return_value=True)
    def test_allowed_when_available(self, _mock: MagicMock) -> None:
        sb = SeatbeltSandbox()
        result = sb.validate("ls -la")
        assert result.allowed
        assert result.command == "ls -la"

    @patch.object(SeatbeltSandbox, "is_available", return_value=False)
    def test_denied_when_unavailable(self, _mock: MagicMock) -> None:
        sb = SeatbeltSandbox()
        result = sb.validate("ls -la")
        assert not result.allowed
        assert "not available" in result.reason.lower()


# ---------------------------------------------------------------------------
# SeatbeltSandbox.execute
# ---------------------------------------------------------------------------
class TestSeatbeltExecute:
    @pytest.mark.asyncio
    @patch.object(SeatbeltSandbox, "is_available", return_value=False)
    async def test_raises_when_unavailable(self, _mock: MagicMock) -> None:
        sb = SeatbeltSandbox()
        with pytest.raises(RuntimeError, match="not available"):
            await sb.execute("echo hi")

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.seatbelt.os.unlink")
    @patch("attocode.integrations.safety.sandbox.seatbelt.tempfile.NamedTemporaryFile")
    @patch("attocode.integrations.safety.sandbox.seatbelt.asyncio.create_subprocess_shell")
    @patch.object(SeatbeltSandbox, "is_available", return_value=True)
    async def test_successful_execution(
        self,
        _avail: MagicMock,
        mock_subprocess: MagicMock,
        mock_tmpfile: MagicMock,
        mock_unlink: MagicMock,
    ) -> None:
        mock_file = MagicMock()
        mock_file.name = "/tmp/attocode_sandbox_test.sb"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_tmpfile.return_value = mock_file

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello world\n", b"")
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        sb = SeatbeltSandbox()
        output, code = await sb.execute("echo hello world", working_dir="/tmp")
        assert code == 0
        assert "hello world" in output
        mock_unlink.assert_called_once_with("/tmp/attocode_sandbox_test.sb")

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.seatbelt.os.unlink")
    @patch("attocode.integrations.safety.sandbox.seatbelt.tempfile.NamedTemporaryFile")
    @patch("attocode.integrations.safety.sandbox.seatbelt.asyncio.create_subprocess_shell")
    @patch.object(SeatbeltSandbox, "is_available", return_value=True)
    async def test_timeout_kills_process(
        self,
        _avail: MagicMock,
        mock_subprocess: MagicMock,
        mock_tmpfile: MagicMock,
        mock_unlink: MagicMock,
    ) -> None:
        mock_file = MagicMock()
        mock_file.name = "/tmp/test.sb"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_tmpfile.return_value = mock_file

        mock_proc = AsyncMock()
        # First call (inside wait_for) raises TimeoutError;
        # second call (after kill) returns empty
        mock_proc.communicate.side_effect = [
            asyncio.TimeoutError(),
            (b"", b""),
        ]
        mock_proc.kill = MagicMock()
        mock_subprocess.return_value = mock_proc

        sb = SeatbeltSandbox(options=SeatbeltOptions(timeout=1.0))
        output, code = await sb.execute("sleep 100")
        assert code == -1
        assert "timed out" in output.lower()
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.seatbelt.os.unlink")
    @patch("attocode.integrations.safety.sandbox.seatbelt.tempfile.NamedTemporaryFile")
    @patch("attocode.integrations.safety.sandbox.seatbelt.asyncio.create_subprocess_shell")
    @patch.object(SeatbeltSandbox, "is_available", return_value=True)
    async def test_stderr_sandbox_denials_filtered(
        self,
        _avail: MagicMock,
        mock_subprocess: MagicMock,
        mock_tmpfile: MagicMock,
        mock_unlink: MagicMock,
    ) -> None:
        mock_file = MagicMock()
        mock_file.name = "/tmp/test.sb"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_tmpfile.return_value = mock_file

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"output\n",
            b"sandbox deny file-write\nreal error\n",
        )
        mock_proc.returncode = 1
        mock_subprocess.return_value = mock_proc

        sb = SeatbeltSandbox()
        output, code = await sb.execute("some_cmd")
        assert code == 1
        assert "real error" in output

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.seatbelt.os.unlink")
    @patch("attocode.integrations.safety.sandbox.seatbelt.tempfile.NamedTemporaryFile")
    @patch("attocode.integrations.safety.sandbox.seatbelt.asyncio.create_subprocess_shell")
    @patch.object(SeatbeltSandbox, "is_available", return_value=True)
    async def test_output_truncation(
        self,
        _avail: MagicMock,
        mock_subprocess: MagicMock,
        mock_tmpfile: MagicMock,
        mock_unlink: MagicMock,
    ) -> None:
        mock_file = MagicMock()
        mock_file.name = "/tmp/test.sb"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_tmpfile.return_value = mock_file

        huge_output = b"x" * 2_000_000
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (huge_output, b"")
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        sb = SeatbeltSandbox(options=SeatbeltOptions(max_output_bytes=100))
        output, code = await sb.execute("large_output_cmd")
        assert code == 0
        assert "truncated" in output
        assert len(output) < 200

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.seatbelt.os.unlink")
    @patch("attocode.integrations.safety.sandbox.seatbelt.tempfile.NamedTemporaryFile")
    @patch("attocode.integrations.safety.sandbox.seatbelt.asyncio.create_subprocess_shell")
    @patch.object(SeatbeltSandbox, "is_available", return_value=True)
    async def test_env_passed_through(
        self,
        _avail: MagicMock,
        mock_subprocess: MagicMock,
        mock_tmpfile: MagicMock,
        mock_unlink: MagicMock,
    ) -> None:
        mock_file = MagicMock()
        mock_file.name = "/tmp/test.sb"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_tmpfile.return_value = mock_file

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok\n", b"")
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        sb = SeatbeltSandbox()
        await sb.execute("echo hi", env={"MY_VAR": "test"})
        call_kwargs = mock_subprocess.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["TERM"] == "dumb"
        assert env["MY_VAR"] == "test"


# ---------------------------------------------------------------------------
# SeatbeltResult / SeatbeltOptions dataclass basics
# ---------------------------------------------------------------------------
class TestSeatbeltDataclasses:
    def test_result_defaults(self) -> None:
        r = SeatbeltResult(allowed=True)
        assert r.allowed
        assert r.reason == ""
        assert r.command == ""

    def test_options_defaults(self) -> None:
        opts = SeatbeltOptions()
        assert opts.writable_paths == ["."]
        assert opts.readable_paths == ["/"]
        assert opts.network_allowed is False
        assert opts.timeout == 300.0
        assert opts.max_output_bytes == 1_000_000
