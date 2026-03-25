"""Tests for OpenShell sandbox."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.safety.sandbox.openshell import (
    OpenShellOptions,
    OpenShellResult,
    OpenShellSandbox,
    OpenShellSandboxSession,
)


# ---------------------------------------------------------------------------
# OpenShellOptions defaults
# ---------------------------------------------------------------------------
class TestOpenShellOptions:
    def test_defaults(self) -> None:
        opts = OpenShellOptions()
        assert opts.gateway_url == ""
        assert opts.agent_type == "claude"
        assert opts.network_allowed is False
        assert opts.timeout == 600.0
        assert opts.max_output_bytes == 1_000_000
        assert opts.include_workdir is True
        assert opts.writable_paths == ["/sandbox", "/tmp"]
        assert opts.readable_paths == ["/usr", "/lib", "/etc"]

    def test_custom_options(self) -> None:
        opts = OpenShellOptions(
            gateway_url="remote:50051",
            agent_type="opencode",
            network_allowed=True,
            timeout=120.0,
        )
        assert opts.gateway_url == "remote:50051"
        assert opts.agent_type == "opencode"
        assert opts.network_allowed is True
        assert opts.timeout == 120.0


# ---------------------------------------------------------------------------
# OpenShellSandbox.is_available
# ---------------------------------------------------------------------------
class TestOpenShellIsAvailable:
    @patch("attocode.integrations.safety.sandbox.openshell.shutil.which", return_value="/usr/bin/openshell")
    def test_binary_found(self, _mock: MagicMock) -> None:
        assert OpenShellSandbox.is_available() is True

    @patch("attocode.integrations.safety.sandbox.openshell.shutil.which", return_value=None)
    def test_binary_not_found(self, _mock: MagicMock) -> None:
        assert OpenShellSandbox.is_available() is False


# ---------------------------------------------------------------------------
# OpenShellSandbox.validate
# ---------------------------------------------------------------------------
class TestOpenShellValidate:
    @patch.object(OpenShellSandbox, "is_available", return_value=True)
    def test_allowed_when_available(self, _mock: MagicMock) -> None:
        sb = OpenShellSandbox()
        result = sb.validate("rm -rf /")
        assert result.allowed
        assert result.command == "rm -rf /"

    @patch.object(OpenShellSandbox, "is_available", return_value=False)
    def test_denied_when_unavailable(self, _mock: MagicMock) -> None:
        sb = OpenShellSandbox()
        result = sb.validate("echo hi")
        assert not result.allowed
        assert "not available" in result.reason.lower()


# ---------------------------------------------------------------------------
# OpenShellSandbox._build_default_policy
# ---------------------------------------------------------------------------
class TestOpenShellBuildDefaultPolicy:
    def test_network_off(self) -> None:
        sb = OpenShellSandbox(options=OpenShellOptions(network_allowed=False))
        policy = sb._build_default_policy()
        assert policy["network_policies"] == {}

    def test_network_on(self) -> None:
        sb = OpenShellSandbox(options=OpenShellOptions(network_allowed=True))
        policy = sb._build_default_policy()
        assert "default_allow" in policy["network_policies"]

    def test_filesystem_paths(self) -> None:
        sb = OpenShellSandbox(options=OpenShellOptions(
            readable_paths=["/opt"],
            writable_paths=["/workspace"],
        ))
        policy = sb._build_default_policy()
        assert policy["filesystem_policy"]["read_only"] == ["/opt"]
        assert policy["filesystem_policy"]["read_write"] == ["/workspace"]

    def test_landlock_best_effort(self) -> None:
        sb = OpenShellSandbox()
        policy = sb._build_default_policy()
        assert policy["landlock"]["compatibility"] == "best_effort"

    def test_version_field(self) -> None:
        sb = OpenShellSandbox()
        policy = sb._build_default_policy()
        assert policy["version"] == 1

    def test_process_runs_as_sandbox(self) -> None:
        sb = OpenShellSandbox()
        policy = sb._build_default_policy()
        assert policy["process"]["run_as_user"] == "sandbox"


# ---------------------------------------------------------------------------
# OpenShellSandbox.execute — subprocess mocking
# ---------------------------------------------------------------------------
class TestOpenShellExecute:
    @pytest.mark.asyncio
    @patch.object(OpenShellSandbox, "is_available", return_value=False)
    async def test_raises_when_unavailable(self, _mock: MagicMock) -> None:
        from attocode.errors import ConfigurationError

        sb = OpenShellSandbox()
        with pytest.raises(ConfigurationError, match="not available"):
            await sb.execute("echo hi")


# ---------------------------------------------------------------------------
# OpenShellSandboxSession
# ---------------------------------------------------------------------------
class TestOpenShellSession:
    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    async def test_exec_command(self, mock_exec: MagicMock) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello\n", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        session = OpenShellSandboxSession(
            sandbox_name="test-sandbox",
            working_dir="/tmp",
            options=OpenShellOptions(),
        )
        output, code = await session.exec_command("echo hello")
        assert code == 0
        assert "hello" in output

        args = mock_exec.call_args[0]
        assert "openshell" in args
        assert "sandbox" in args
        assert "exec" in args
        assert "test-sandbox" in args

    @pytest.mark.asyncio
    async def test_exec_destroyed_raises(self) -> None:
        session = OpenShellSandboxSession(
            sandbox_name="dead",
            working_dir="/tmp",
            options=OpenShellOptions(),
            _destroyed=True,
        )
        with pytest.raises(RuntimeError, match="already destroyed"):
            await session.exec_command("echo hi")

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    async def test_destroy_idempotent(self, mock_exec: MagicMock) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_exec.return_value = mock_proc

        session = OpenShellSandboxSession(
            sandbox_name="test",
            working_dir="/tmp",
            options=OpenShellOptions(),
        )
        await session.destroy()
        await session.destroy()  # second call is a no-op
        assert mock_exec.call_count == 1

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    async def test_inject_credentials(self, mock_exec: MagicMock) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_exec.return_value = mock_proc

        session = OpenShellSandboxSession(
            sandbox_name="test",
            working_dir="/tmp",
            options=OpenShellOptions(),
        )
        await session.inject_credentials({"API_KEY": "secret123", "TOKEN": "xyz"})
        assert mock_exec.call_count == 2  # one per credential

    @pytest.mark.asyncio
    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    async def test_timeout_handling(self, mock_exec: MagicMock) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = [asyncio.TimeoutError(), (b"", b"")]
        mock_proc.kill = MagicMock()
        mock_exec.return_value = mock_proc

        session = OpenShellSandboxSession(
            sandbox_name="test",
            working_dir="/tmp",
            options=OpenShellOptions(timeout=1.0),
        )
        output, code = await session.exec_command("sleep 999")
        assert code == -1
        assert "timed out" in output.lower()


# ---------------------------------------------------------------------------
# OpenShellResult dataclass
# ---------------------------------------------------------------------------
class TestOpenShellResult:
    def test_defaults(self) -> None:
        r = OpenShellResult(allowed=True)
        assert r.allowed
        assert r.reason == ""
        assert r.command == ""


# ---------------------------------------------------------------------------
# Sandbox factory integration
# ---------------------------------------------------------------------------
class TestOpenShellInSandboxFactory:
    @patch("attocode.integrations.safety.sandbox._load_openshell")
    def test_create_sandbox_openshell_mode(self, mock_load: MagicMock) -> None:
        mock_cls = MagicMock()
        mock_cls.is_available.return_value = True
        mock_load.return_value = mock_cls

        from attocode.integrations.safety.sandbox import create_sandbox
        create_sandbox(mode="openshell")
        mock_cls.is_available.assert_called()

    def test_create_sandbox_openshell_unavailable(self) -> None:
        from attocode.errors import ConfigurationError
        from attocode.integrations.safety.sandbox import create_sandbox

        with patch("attocode.integrations.safety.sandbox._load_openshell") as mock_load:
            mock_cls = MagicMock()
            mock_cls.is_available.return_value = False
            mock_load.return_value = mock_cls

            with pytest.raises(ConfigurationError, match="not available"):
                create_sandbox(mode="openshell")

    def test_parse_sandbox_name_json(self) -> None:
        name = OpenShellSandbox._parse_sandbox_name('{"name": "my-sandbox"}')
        assert name == "my-sandbox"

    def test_parse_sandbox_name_text(self) -> None:
        name = OpenShellSandbox._parse_sandbox_name("Creating sandbox...\nmy-sandbox-123")
        assert name == "my-sandbox-123"

    def test_parse_sandbox_name_empty(self) -> None:
        name = OpenShellSandbox._parse_sandbox_name("")
        assert name == "openshell-sandbox"


# ---------------------------------------------------------------------------
# Two-phase policy helpers
# ---------------------------------------------------------------------------
class TestOpenShellPolicyHelpers:
    def test_restricted_network_policy_empty(self) -> None:
        sb = OpenShellSandbox()
        assert sb.build_restricted_network_policy() == {}

    def test_setup_network_policy_has_pypi(self) -> None:
        sb = OpenShellSandbox()
        policy = sb.build_setup_network_policy()
        assert "pypi" in policy
        assert "github" in policy
        assert "npm" in policy


# ---------------------------------------------------------------------------
# Session update_network_policy
# ---------------------------------------------------------------------------
class TestSessionUpdateNetworkPolicy:
    def test_update_network_policy_destroyed(self):
        session = OpenShellSandboxSession(
            sandbox_name="test-sb",
            working_dir="/sandbox",
            options=OpenShellOptions(),
        )
        session._destroyed = True
        with pytest.raises(RuntimeError, match="already destroyed"):
            asyncio.get_event_loop().run_until_complete(
                session.update_network_policy({"allow": ["*.example.com"]})
            )

    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    def test_update_network_policy_get_fails(self, mock_exec):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_exec.return_value = proc

        session = OpenShellSandboxSession(
            sandbox_name="test-sb",
            working_dir="/sandbox",
            options=OpenShellOptions(),
        )
        # Should not raise, just log warning
        asyncio.get_event_loop().run_until_complete(
            session.update_network_policy({"allow": ["*.example.com"]})
        )

    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    def test_update_network_policy_no_yaml(self, mock_exec):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"network_policies: {}", b""))
        mock_exec.return_value = proc

        session = OpenShellSandboxSession(
            sandbox_name="test-sb",
            working_dir="/sandbox",
            options=OpenShellOptions(),
        )
        # Mock yaml not available
        import sys
        yaml_mod = sys.modules.get("yaml")
        sys.modules["yaml"] = None  # type: ignore
        try:
            asyncio.get_event_loop().run_until_complete(
                session.update_network_policy({"allow": ["*.example.com"]})
            )
        except (ImportError, TypeError):
            pass  # Expected when yaml is None
        finally:
            if yaml_mod is not None:
                sys.modules["yaml"] = yaml_mod
            else:
                sys.modules.pop("yaml", None)


# ---------------------------------------------------------------------------
# Session output truncation
# ---------------------------------------------------------------------------
class TestSessionOutputTruncation:
    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    def test_output_truncated_at_max_bytes(self, mock_exec):
        opts = OpenShellOptions(max_output_bytes=100)
        big_output = "x" * 200

        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(big_output.encode(), b""))
        mock_exec.return_value = proc

        session = OpenShellSandboxSession(
            sandbox_name="test-sb",
            working_dir="/sandbox",
            options=opts,
        )
        output, code = asyncio.get_event_loop().run_until_complete(
            session.exec_command("echo lots")
        )
        assert len(output) < 200
        assert "truncated" in output


# ---------------------------------------------------------------------------
# Session destroy idempotency
# ---------------------------------------------------------------------------
class TestSessionDestroyIdempotent:
    @patch("attocode.integrations.safety.sandbox.openshell.asyncio.create_subprocess_exec")
    def test_double_destroy(self, mock_exec):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = proc

        session = OpenShellSandboxSession(
            sandbox_name="test-sb",
            working_dir="/sandbox",
            options=OpenShellOptions(),
        )
        asyncio.get_event_loop().run_until_complete(session.destroy())
        assert session._destroyed
        # Second destroy should be a no-op
        asyncio.get_event_loop().run_until_complete(session.destroy())
        # exec should have been called only once (first destroy)
        assert mock_exec.call_count == 1


# ---------------------------------------------------------------------------
# Session credential injection
# ---------------------------------------------------------------------------
class TestSessionCredentialInjection:
    def test_inject_credentials_destroyed(self):
        session = OpenShellSandboxSession(
            sandbox_name="test-sb",
            working_dir="/sandbox",
            options=OpenShellOptions(),
        )
        session._destroyed = True
        with pytest.raises(RuntimeError, match="already destroyed"):
            asyncio.get_event_loop().run_until_complete(
                session.inject_credentials({"API_KEY": "secret"})
            )
