"""NVIDIA OpenShell sandbox for policy-governed agent isolation.

Uses NVIDIA OpenShell to provide containerized sandbox environments
with declarative YAML policies governing filesystem, network, process,
and inference layers. Supports persistent sessions for long-running
agent workers.

Requires the ``openshell`` CLI binary on PATH and a running OpenShell
gateway (local K3s cluster in Docker).

See: https://github.com/NVIDIA/OpenShell
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any

from attocode.errors import ConfigurationError

# OpenShellResult is the canonical generic SandboxResult; the alias preserves
# the historical module-local name without duplicating the dataclass.
from attocode.integrations.safety.sandbox.basic import SandboxResult as OpenShellResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OpenShellOptions:
    """Configuration for the OpenShell sandbox."""

    # Gateway connection
    gateway_url: str = ""  # empty = local default

    # Policy configuration
    policy: dict[str, Any] | None = None  # Inline policy dict
    policy_path: str = ""  # Path to YAML policy file

    # Sandbox image
    image: str = ""  # empty = default image

    # Filesystem
    writable_paths: list[str] = field(default_factory=lambda: ["/sandbox", "/tmp"])
    readable_paths: list[str] = field(default_factory=lambda: ["/usr", "/lib", "/etc"])
    include_workdir: bool = True

    # Network
    network_allowed: bool = False

    # Process
    agent_type: str = "claude"  # claude, opencode, codex, custom

    # Resource limits
    timeout: float = 600.0
    max_output_bytes: int = 1_000_000

    # Credentials (injected as env vars, never on disk)
    credential_env: dict[str, str] = field(default_factory=dict)


@dataclass
class OpenShellSandboxSession:
    """A persistent OpenShell sandbox session for long-running agent work.

    Unlike ephemeral sandboxes, a session maintains state across multiple
    command executions. This maps to an OpenShell K3s pod that persists
    until explicitly destroyed.
    """

    sandbox_name: str
    working_dir: str
    options: OpenShellOptions
    _gateway_args: list[str] = field(default_factory=list, repr=False)
    _destroyed: bool = False

    async def exec_command(
        self,
        command: str,
        *,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, int]:
        """Execute a command inside the sandbox session.

        Uses asyncio.create_subprocess_exec with argument list
        (no shell injection risk).

        Args:
            command: Shell command to execute.
            env: Extra environment variables for this command.
            timeout: Override timeout (seconds).

        Returns:
            Tuple of (output, exit_code).
        """
        if self._destroyed:
            raise RuntimeError(f"Sandbox session '{self.sandbox_name}' already destroyed")

        args = ["openshell", "sandbox", "exec", self.sandbox_name]
        args.extend(self._gateway_args)

        if env:
            for key, value in env.items():
                args.extend(["--env", f"{key}={value}"])

        args.extend(["--", "sh", "-c", command])

        effective_timeout = timeout or self.options.timeout
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"Command timed out after {effective_timeout}s", -1

        output = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        if err:
            output = f"{output}\n{err}" if output else err

        if len(output) > self.options.max_output_bytes:
            output = output[: self.options.max_output_bytes] + "\n... (truncated)"

        return output, proc.returncode or 0

    async def inject_credentials(self, credentials: dict[str, str]) -> None:
        """Inject credentials as environment variables into the sandbox.

        Uses OpenShell's credential provider mechanism so secrets are
        never written to the sandbox filesystem.
        """
        if self._destroyed:
            raise RuntimeError(f"Sandbox session '{self.sandbox_name}' already destroyed")

        for key, value in credentials.items():
            args = [
                "openshell", "provider", "set",
                self.sandbox_name,
                "--env", f"{key}={value}",
            ]
            args.extend(self._gateway_args)

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

    async def update_network_policy(self, network_policies: dict[str, Any]) -> None:
        """Hot-reload network policies on a running sandbox.

        OpenShell supports dynamic updates to network policies without
        restarting the sandbox. This is used for the two-phase pattern:
        full network during setup, restricted during agent work.
        """
        if self._destroyed:
            raise RuntimeError(f"Sandbox session '{self.sandbox_name}' already destroyed")

        # Get current full policy
        get_args = [
            "openshell", "policy", "get", self.sandbox_name, "--full",
        ]
        get_args.extend(self._gateway_args)

        proc = await asyncio.create_subprocess_exec(
            *get_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Failed to get current policy for %s", self.sandbox_name)
            return

        # Write updated policy to temp file and apply
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not available, cannot update network policy")
            return

        try:
            current_policy = yaml.safe_load(stdout.decode(errors="replace"))
        except Exception:
            logger.warning("Failed to parse current policy for %s", self.sandbox_name)
            return

        if current_policy is None:
            current_policy = {}
        current_policy["network_policies"] = network_policies

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as tmp:
            yaml.dump(current_policy, tmp, default_flow_style=False)
            tmp_path = tmp.name

        try:
            set_args = [
                "openshell", "policy", "set", self.sandbox_name,
                "--policy", tmp_path, "--wait",
            ]
            set_args.extend(self._gateway_args)

            proc = await asyncio.create_subprocess_exec(
                *set_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(
                    "Failed to update network policy for %s: %s",
                    self.sandbox_name,
                    stderr.decode(errors="replace"),
                )
        finally:
            os.unlink(tmp_path)

    async def destroy(self) -> None:
        """Destroy the sandbox session and release resources."""
        if self._destroyed:
            return

        args = ["openshell", "sandbox", "destroy", self.sandbox_name, "--force"]
        args.extend(self._gateway_args)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        self._destroyed = True
        logger.info("Destroyed OpenShell sandbox: %s", self.sandbox_name)


@dataclass
class OpenShellSandbox:
    """NVIDIA OpenShell sandbox with declarative YAML policy enforcement.

    Provides kernel-level isolation via Landlock LSM, network policy
    enforcement via an HTTPS proxy, and process restrictions via seccomp.
    All policies are declared in YAML and enforced out-of-process.

    All subprocess calls use ``asyncio.create_subprocess_exec`` with
    argument lists (never shell=True) to prevent command injection.

    Usage::

        sandbox = OpenShellSandbox()
        result = sandbox.validate("python script.py")
        output, exit_code = await sandbox.execute("python script.py")

    For persistent sessions (swarm workers)::

        session = await sandbox.create_session(
            name="worker-1", working_dir="/path/to/repo"
        )
        output, code = await session.exec_command("python script.py")
        await session.destroy()
    """

    options: OpenShellOptions = field(default_factory=OpenShellOptions)

    @staticmethod
    def is_available() -> bool:
        """Check if the OpenShell CLI is available on PATH."""
        return shutil.which("openshell") is not None

    def validate(self, command: str) -> OpenShellResult:
        """Validate a command (always allowed -- OpenShell handles isolation).

        Unlike BasicSandbox, OpenShell enforces security at the kernel
        level so all commands are permitted at the validation stage.
        """
        if not self.is_available():
            return OpenShellResult(
                allowed=False,
                reason="OpenShell CLI not available (install: pip install openshell)",
                command=command,
            )
        return OpenShellResult(allowed=True, command=command)

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, int]:
        """Execute a command in an ephemeral OpenShell sandbox.

        Creates a temporary sandbox, runs the command, and destroys
        the sandbox. For multiple commands, use create_session() instead.

        Args:
            command: The command to execute.
            working_dir: Working directory mounted into the sandbox.
            env: Extra environment variables.

        Returns:
            Tuple of (output, exit_code).
        """
        if not self.is_available():
            raise ConfigurationError("OpenShell CLI not available")

        session = await self.create_session(
            name="",  # auto-generated
            working_dir=working_dir or os.getcwd(),
        )
        try:
            return await session.exec_command(command, env=env)
        finally:
            await session.destroy()

    async def create_session(
        self,
        *,
        name: str = "",
        working_dir: str = "",
    ) -> OpenShellSandboxSession:
        """Create a persistent sandbox session.

        Args:
            name: Sandbox name (auto-generated if empty).
            working_dir: Directory to mount as the workspace.

        Returns:
            An OpenShellSandboxSession for executing commands.
        """
        if not self.is_available():
            raise ConfigurationError("OpenShell CLI not available")

        gateway_args: list[str] = []
        if self.options.gateway_url:
            gateway_args.extend(["--gateway", self.options.gateway_url])

        # Build the sandbox creation command
        create_args = ["openshell", "sandbox", "create"]
        create_args.extend(gateway_args)

        if name:
            create_args.extend(["--name", name])

        create_args.append("--keep")  # Persist across commands

        if working_dir:
            create_args.extend(["--workdir", working_dir])

        if self.options.image:
            create_args.extend(["--from", self.options.image])

        # Apply policy
        policy_path = self._resolve_policy_path()
        if policy_path:
            create_args.extend(["--policy", policy_path])

        # Agent type
        create_args.extend(["--", self.options.agent_type])

        logger.info("Creating OpenShell sandbox: %s", " ".join(create_args))

        proc = await asyncio.create_subprocess_exec(
            *create_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise ConfigurationError(
                f"Failed to create OpenShell sandbox: {err_msg}"
            )

        # Parse sandbox name from output
        output_text = stdout.decode(errors="replace").strip()
        sandbox_name = name or self._parse_sandbox_name(output_text)

        session = OpenShellSandboxSession(
            sandbox_name=sandbox_name,
            working_dir=working_dir,
            options=self.options,
            _gateway_args=gateway_args,
        )

        # Inject credentials if configured
        all_creds = dict(self.options.credential_env)
        if all_creds:
            await session.inject_credentials(all_creds)

        logger.info("OpenShell sandbox ready: %s", sandbox_name)
        return session

    def _resolve_policy_path(self) -> str:
        """Resolve the policy to a YAML file path.

        If an inline policy dict is provided, writes it to a temp file.
        If a policy_path is set, uses it directly.
        Otherwise builds a default policy from options.
        """
        if self.options.policy_path:
            return self.options.policy_path

        policy = self.options.policy or self._build_default_policy()

        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not available, using OpenShell defaults")
            return ""

        # Write inline policy to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="openshell-policy-",
        ) as tmp:
            yaml.dump(policy, tmp, default_flow_style=False)
            return tmp.name

    def _build_default_policy(self) -> dict[str, Any]:
        """Build a default YAML policy from OpenShellOptions."""
        policy: dict[str, Any] = {
            "version": 1,
            "filesystem_policy": {
                "read_only": list(self.options.readable_paths),
                "read_write": list(self.options.writable_paths),
                "include_workdir": self.options.include_workdir,
            },
            "landlock": {
                "compatibility": "best_effort",
            },
            "process": {
                "run_as_user": "sandbox",
                "run_as_group": "sandbox",
            },
        }

        if self.options.network_allowed:
            policy["network_policies"] = {
                "default_allow": {
                    "name": "default-allow",
                    "endpoints": [
                        {"host": "*", "port": 443},
                        {"host": "*", "port": 80},
                    ],
                    "binaries": [{"path": "*"}],
                },
            }
        else:
            policy["network_policies"] = {}

        return policy

    @staticmethod
    def _parse_sandbox_name(output: str) -> str:
        """Extract sandbox name from openshell create output."""
        # Try JSON output first
        try:
            data = json.loads(output)
            if isinstance(data, dict):
                return data.get("name", "") or data.get("sandbox_name", "")
        except (json.JSONDecodeError, ValueError):
            pass

        # Fall back to parsing text output (last non-empty line is often the name)
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line and not line.startswith(("[", "{", "Creating", "Starting")):
                return line

        return "openshell-sandbox"

    def build_restricted_network_policy(self) -> dict[str, Any]:
        """Build a restricted network policy for the agent phase.

        Used in the two-phase pattern: after setup (full network),
        transition to agent phase with minimal network access.
        """
        return {}  # Empty = deny all outbound

    def build_setup_network_policy(self) -> dict[str, Any]:
        """Build a permissive network policy for the setup phase.

        Allows access to package registries and common development
        endpoints needed during dependency installation.
        """
        return {
            "pypi": {
                "name": "pypi",
                "endpoints": [
                    {"host": "pypi.org", "port": 443},
                    {"host": "files.pythonhosted.org", "port": 443},
                ],
                "binaries": [
                    {"path": "/usr/bin/pip"},
                    {"path": "/usr/local/bin/uv"},
                    {"path": "/usr/local/bin/pip"},
                ],
            },
            "npm": {
                "name": "npm",
                "endpoints": [
                    {"host": "registry.npmjs.org", "port": 443},
                ],
                "binaries": [
                    {"path": "/usr/bin/npm"},
                    {"path": "/usr/local/bin/npm"},
                ],
            },
            "github": {
                "name": "github",
                "endpoints": [
                    {"host": "github.com", "port": 443},
                    {"host": "api.github.com", "port": 443},
                ],
                "binaries": [
                    {"path": "/usr/bin/git"},
                    {"path": "/usr/bin/gh"},
                ],
            },
        }
