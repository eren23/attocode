"""Tests for Landlock sandbox (Linux LSM)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.safety.sandbox.landlock import (
    ALL_ACCESS,
    LANDLOCK_ACCESS_FS_READ_DIR,
    LANDLOCK_ACCESS_FS_READ_FILE,
    LANDLOCK_ACCESS_FS_WRITE_FILE,
    LandlockOptions,
    LandlockResult,
    LandlockSandbox,
    READ_ACCESS,
    WRITE_ACCESS,
    _SYS_LANDLOCK_ADD_RULE,
    _SYS_LANDLOCK_CREATE_RULESET,
    _SYS_LANDLOCK_RESTRICT_SELF,
    _build_landlock_helper,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestLandlockConstants:
    def test_syscall_numbers(self) -> None:
        assert _SYS_LANDLOCK_CREATE_RULESET == 444
        assert _SYS_LANDLOCK_ADD_RULE == 445
        assert _SYS_LANDLOCK_RESTRICT_SELF == 446

    def test_read_access_flags(self) -> None:
        assert READ_ACCESS & LANDLOCK_ACCESS_FS_READ_FILE
        assert READ_ACCESS & LANDLOCK_ACCESS_FS_READ_DIR

    def test_write_access_flags(self) -> None:
        assert WRITE_ACCESS & LANDLOCK_ACCESS_FS_WRITE_FILE

    def test_all_access_includes_read_and_write(self) -> None:
        assert ALL_ACCESS == READ_ACCESS | WRITE_ACCESS


# ---------------------------------------------------------------------------
# LandlockSandbox.is_available
# ---------------------------------------------------------------------------
class TestLandlockIsAvailable:
    @patch("attocode.integrations.safety.sandbox.landlock.sys")
    def test_not_linux(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "darwin"
        assert LandlockSandbox.is_available() is False

    @patch("attocode.integrations.safety.sandbox.landlock.ctypes")
    @patch("attocode.integrations.safety.sandbox.landlock.os")
    @patch("attocode.integrations.safety.sandbox.landlock.sys")
    def test_linux_old_kernel(
        self, mock_sys: MagicMock, mock_os: MagicMock, mock_ctypes: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        uname = MagicMock()
        uname.release = "4.19.0"
        mock_os.uname.return_value = uname
        assert LandlockSandbox.is_available() is False

    @patch("attocode.integrations.safety.sandbox.landlock.ctypes")
    @patch("attocode.integrations.safety.sandbox.landlock.os")
    @patch("attocode.integrations.safety.sandbox.landlock.sys")
    def test_linux_5_13_with_syscall(
        self, mock_sys: MagicMock, mock_os: MagicMock, mock_ctypes: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        uname = MagicMock()
        uname.release = "5.13.0-generic"
        mock_os.uname.return_value = uname

        mock_libc = MagicMock()
        mock_libc.syscall = MagicMock()
        mock_ctypes.CDLL.return_value = mock_libc
        mock_ctypes.util.find_library.return_value = "libc.so.6"

        assert LandlockSandbox.is_available() is True

    @patch("attocode.integrations.safety.sandbox.landlock.ctypes")
    @patch("attocode.integrations.safety.sandbox.landlock.os")
    @patch("attocode.integrations.safety.sandbox.landlock.sys")
    def test_linux_6_x_supported(
        self, mock_sys: MagicMock, mock_os: MagicMock, mock_ctypes: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        uname = MagicMock()
        uname.release = "6.5.0-arch1"
        mock_os.uname.return_value = uname

        mock_libc = MagicMock()
        mock_libc.syscall = MagicMock()
        mock_ctypes.CDLL.return_value = mock_libc
        mock_ctypes.util.find_library.return_value = "libc.so.6"

        assert LandlockSandbox.is_available() is True

    @patch("attocode.integrations.safety.sandbox.landlock.ctypes")
    @patch("attocode.integrations.safety.sandbox.landlock.os")
    @patch("attocode.integrations.safety.sandbox.landlock.sys")
    def test_linux_no_libc(
        self, mock_sys: MagicMock, mock_os: MagicMock, mock_ctypes: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        uname = MagicMock()
        uname.release = "5.15.0"
        mock_os.uname.return_value = uname
        mock_ctypes.CDLL.side_effect = OSError("no libc")
        mock_ctypes.util.find_library.return_value = None

        assert LandlockSandbox.is_available() is False

    @patch("attocode.integrations.safety.sandbox.landlock.os")
    @patch("attocode.integrations.safety.sandbox.landlock.sys")
    def test_bad_kernel_version_string(
        self, mock_sys: MagicMock, mock_os: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        uname = MagicMock()
        uname.release = "not-a-version"
        mock_os.uname.return_value = uname
        assert LandlockSandbox.is_available() is False


# ---------------------------------------------------------------------------
# LandlockSandbox.validate
# ---------------------------------------------------------------------------
class TestLandlockValidate:
    @patch.object(LandlockSandbox, "is_available", return_value=True)
    def test_allowed_when_available(self, _mock: MagicMock) -> None:
        sb = LandlockSandbox()
        result = sb.validate("ls -la")
        assert result.allowed

    @patch.object(LandlockSandbox, "is_available", return_value=False)
    def test_denied_when_unavailable(self, _mock: MagicMock) -> None:
        sb = LandlockSandbox()
        result = sb.validate("ls")
        assert not result.allowed
        assert "not available" in result.reason.lower()


# ---------------------------------------------------------------------------
# _build_landlock_helper
# ---------------------------------------------------------------------------
class TestBuildLandlockHelper:
    def test_contains_syscall_numbers(self) -> None:
        script = _build_landlock_helper(["/usr"], ["/tmp"], "echo hi")
        assert "SYS_CREATE = 444" in script
        assert "SYS_ADD = 445" in script
        assert "SYS_RESTRICT = 446" in script

    def test_contains_prctl(self) -> None:
        script = _build_landlock_helper([], ["/tmp"], "true")
        assert "PR_SET_NO_NEW_PRIVS" in script
        assert "prctl" in script

    def test_contains_command(self) -> None:
        script = _build_landlock_helper([], ["/tmp"], "echo hello world")
        assert "echo hello world" in script

    def test_contains_paths(self) -> None:
        script = _build_landlock_helper(
            ["/usr", "/lib"], ["/home/user"], "cmd"
        )
        assert '"/usr"' in script
        assert '"/lib"' in script
        assert '"/home/user"' in script

    def test_struct_pack_for_ruleset(self) -> None:
        script = _build_landlock_helper([], ["/tmp"], "true")
        assert "struct.pack" in script

    def test_os_open_o_path(self) -> None:
        script = _build_landlock_helper(["/usr"], ["/tmp"], "true")
        assert "os.O_PATH" in script
        assert "os.O_CLOEXEC" in script

    def test_is_valid_python(self) -> None:
        """The generated script should be valid Python syntax."""
        script = _build_landlock_helper(
            ["/usr", "/lib"], ["/tmp", "/home"], "echo test"
        )
        compile(script, "<landlock_helper>", "exec")

    def test_subprocess_run_at_end(self) -> None:
        script = _build_landlock_helper([], ["/tmp"], "echo done")
        assert "subprocess.run" in script
        assert "sys.exit(result.returncode)" in script


# ---------------------------------------------------------------------------
# LandlockSandbox.execute
# ---------------------------------------------------------------------------
class TestLandlockExecute:
    @pytest.mark.asyncio
    @patch.object(LandlockSandbox, "is_available", return_value=False)
    async def test_raises_when_unavailable(self, _mock: MagicMock) -> None:
        sb = LandlockSandbox()
        with pytest.raises(RuntimeError, match="not available"):
            await sb.execute("echo hi")

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.landlock.asyncio.create_subprocess_exec")
    @patch.object(LandlockSandbox, "is_available", return_value=True)
    async def test_basic_execution(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello\n", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = LandlockSandbox()
        output, code = await sb.execute("echo hello", working_dir="/tmp")
        assert code == 0
        assert "hello" in output

        # Should invoke python -c <helper_script>
        args = mock_exec.call_args[0]
        assert "-c" in args

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.landlock.asyncio.create_subprocess_exec")
    @patch.object(LandlockSandbox, "is_available", return_value=True)
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

        sb = LandlockSandbox(options=LandlockOptions(timeout=0.5))
        output, code = await sb.execute("sleep 999")
        assert code == -1
        assert "timed out" in output.lower()
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.landlock.asyncio.create_subprocess_exec")
    @patch.object(LandlockSandbox, "is_available", return_value=True)
    async def test_stderr_merged(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"out\n", b"err\n")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        sb = LandlockSandbox()
        output, code = await sb.execute("fail", working_dir="/tmp")
        assert code == 1
        assert "out" in output
        assert "err" in output

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.landlock.asyncio.create_subprocess_exec")
    @patch.object(LandlockSandbox, "is_available", return_value=True)
    async def test_output_truncation(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"x" * 2_000_000, b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = LandlockSandbox(options=LandlockOptions(max_output_bytes=50))
        output, code = await sb.execute("big", working_dir="/tmp")
        assert "truncated" in output

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.landlock.asyncio.create_subprocess_exec")
    @patch.object(LandlockSandbox, "is_available", return_value=True)
    async def test_env_passed(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = LandlockSandbox()
        await sb.execute("env", working_dir="/tmp", env={"MY_KEY": "val"})

        call_kwargs = mock_exec.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["TERM"] == "dumb"
        assert env["MY_KEY"] == "val"

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.landlock.asyncio.create_subprocess_exec")
    @patch.object(LandlockSandbox, "is_available", return_value=True)
    async def test_working_dir_in_writable(
        self, _avail: MagicMock, mock_exec: MagicMock
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        sb = LandlockSandbox()
        await sb.execute("ls", working_dir="/home/user/proj")

        # The helper script should include the working dir in writable paths
        args = mock_exec.call_args[0]
        helper_script = args[2]  # python -c <script>
        assert "/home/user/proj" in helper_script


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------
class TestLandlockDataclasses:
    def test_result_defaults(self) -> None:
        r = LandlockResult(allowed=True)
        assert r.allowed
        assert r.reason == ""

    def test_options_defaults(self) -> None:
        opts = LandlockOptions()
        assert opts.writable_paths == ["."]
        assert opts.readable_paths == ["/"]
        assert opts.network_allowed is True
        assert opts.timeout == 300.0
        assert opts.max_output_bytes == 1_000_000
