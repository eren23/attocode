"""Sandbox implementations for safe command execution.

Available sandboxes:
- BasicSandbox: Allowlist/blocklist validation (all platforms)
- SeatbeltSandbox: macOS sandbox-exec isolation
- LandlockSandbox: Linux Landlock LSM isolation
- DockerSandbox: Docker container isolation
- OpenShellSandbox: NVIDIA OpenShell policy-governed isolation

Use create_sandbox() to auto-detect the best available sandbox.
Use create_two_phase_sandbox() for two-phase mode (network ON for setup, OFF for agent).
"""

import sys
from enum import StrEnum
from typing import Any

from attocode.errors import ConfigurationError
from attocode.integrations.safety.sandbox.basic import (
    BasicSandbox,
    SandboxOptions,
    SandboxResult,
)

__all__ = [
    "BasicSandbox",
    "SandboxOptions",
    "SandboxResult",
    "SandboxPhase",
    "TwoPhaseContext",
    "create_sandbox",
    "create_two_phase_sandbox",
    "OpenShellSandbox",
    "OpenShellOptions",
    "OpenShellSandboxSession",
]


class SandboxPhase(StrEnum):
    """Phase of a two-phase sandbox lifecycle."""

    SETUP = "setup"  # Network allowed, install deps
    AGENT = "agent"  # Network restricted


# Lazy imports for platform-specific sandboxes
_SeatbeltSandbox: type | None = None
_LandlockSandbox: type | None = None
_DockerSandbox: type | None = None
_OpenShellSandbox: type | None = None


def _load_seatbelt() -> type | None:
    global _SeatbeltSandbox
    if _SeatbeltSandbox is None:
        try:
            from attocode.integrations.safety.sandbox.seatbelt import SeatbeltSandbox
            _SeatbeltSandbox = SeatbeltSandbox
        except ImportError:
            pass
    return _SeatbeltSandbox


def _load_landlock() -> type | None:
    global _LandlockSandbox
    if _LandlockSandbox is None:
        try:
            from attocode.integrations.safety.sandbox.landlock import LandlockSandbox
            _LandlockSandbox = LandlockSandbox
        except ImportError:
            pass
    return _LandlockSandbox


def _load_docker() -> type | None:
    global _DockerSandbox
    if _DockerSandbox is None:
        try:
            from attocode.integrations.safety.sandbox.docker import DockerSandbox
            _DockerSandbox = DockerSandbox
        except ImportError:
            pass
    return _DockerSandbox


def _load_openshell() -> type | None:
    global _OpenShellSandbox
    if _OpenShellSandbox is None:
        try:
            from attocode.integrations.safety.sandbox.openshell import OpenShellSandbox
            _OpenShellSandbox = OpenShellSandbox
        except ImportError:
            pass
    return _OpenShellSandbox


def _apply_network_option(cls: type, network_allowed: bool | None, kwargs: dict[str, Any]) -> Any:
    """Create a sandbox instance, injecting network_allowed into its options."""
    instance = cls(**kwargs)
    if network_allowed is not None and hasattr(instance, "options"):
        opts = instance.options
        if hasattr(opts, "network_allowed"):
            opts.network_allowed = network_allowed
    return instance


def create_sandbox(
    mode: str = "auto",
    *,
    network_allowed: bool | None = None,
    **kwargs: Any,
) -> Any:
    """Create the best available sandbox for the current platform.

    Args:
        mode: Sandbox mode - 'auto', 'basic', 'seatbelt', 'landlock', 'docker', 'openshell'.
        network_allowed: Override the default network_allowed setting on the
            sandbox options. When *None* (default), the sandbox's own default
            is used.
        **kwargs: Options passed to the sandbox constructor.

    Returns:
        A sandbox instance.
    """
    if mode == "basic":
        return _apply_network_option(BasicSandbox, network_allowed, kwargs)

    if mode == "seatbelt":
        cls = _load_seatbelt()
        if cls and cls.is_available():
            return _apply_network_option(cls, network_allowed, kwargs)
        raise ConfigurationError("Seatbelt sandbox not available")

    if mode == "landlock":
        cls = _load_landlock()
        if cls and cls.is_available():
            return _apply_network_option(cls, network_allowed, kwargs)
        raise ConfigurationError("Landlock sandbox not available")

    if mode == "docker":
        cls = _load_docker()
        if cls and cls.is_available():
            return _apply_network_option(cls, network_allowed, kwargs)
        raise ConfigurationError("Docker sandbox not available")

    if mode == "openshell":
        cls = _load_openshell()
        if cls and cls.is_available():
            return _apply_network_option(cls, network_allowed, kwargs)
        raise ConfigurationError("OpenShell sandbox not available (install: pip install openshell)")

    # Auto-detect
    if sys.platform == "darwin":
        cls = _load_seatbelt()
        if cls and cls.is_available():
            return _apply_network_option(cls, network_allowed, kwargs)

    if sys.platform == "linux":
        cls = _load_landlock()
        if cls and cls.is_available():
            return _apply_network_option(cls, network_allowed, kwargs)

    # OpenShell provides stronger isolation than basic but may not always be available
    cls = _load_openshell()
    if cls and cls.is_available():
        return _apply_network_option(cls, network_allowed, kwargs)

    cls = _load_docker()
    if cls and cls.is_available():
        return _apply_network_option(cls, network_allowed, kwargs)

    # Fall back to basic
    return _apply_network_option(BasicSandbox, network_allowed, kwargs)


class TwoPhaseContext:
    """Two-phase sandbox: network ON during setup, OFF during agent work.

    Inspired by OpenAI Codex CLI's approach: allow network access for
    dependency installation (setup phase), then restrict network access
    when the agent begins its work (agent phase).

    Usage::

        ctx = TwoPhaseContext(sandbox_mode="auto")
        setup_sb = ctx.get_sandbox()          # network_allowed=True
        await setup_sb.execute("pip install requests")

        ctx.transition_to_agent()
        agent_sb = ctx.get_sandbox()           # network_allowed=False
        await agent_sb.execute("python myscript.py")
    """

    def __init__(self, sandbox_mode: str = "auto", **sandbox_kwargs: Any) -> None:
        self._mode = sandbox_mode
        self._kwargs = sandbox_kwargs
        self._phase = SandboxPhase.SETUP
        self._setup_sandbox: Any | None = None
        self._agent_sandbox: Any | None = None

    @property
    def phase(self) -> SandboxPhase:
        """Current sandbox phase."""
        return self._phase

    def transition_to_agent(self) -> None:
        """Switch from setup phase (network ON) to agent phase (network OFF).

        Raises:
            RuntimeError: If already in agent phase.
        """
        if self._phase == SandboxPhase.AGENT:
            raise RuntimeError("Already in agent phase")
        self._phase = SandboxPhase.AGENT

    def get_sandbox(self) -> Any:
        """Return the sandbox instance for the current phase.

        During setup: creates a sandbox with ``network_allowed=True``.
        During agent: creates a sandbox with ``network_allowed=False``.

        Sandbox instances are lazily created and cached per phase.
        """
        if self._phase == SandboxPhase.SETUP:
            if self._setup_sandbox is None:
                self._setup_sandbox = create_sandbox(
                    self._mode, network_allowed=True, **self._kwargs,
                )
            return self._setup_sandbox
        else:
            if self._agent_sandbox is None:
                self._agent_sandbox = create_sandbox(
                    self._mode, network_allowed=False, **self._kwargs,
                )
            return self._agent_sandbox


def create_two_phase_sandbox(
    mode: str = "auto",
    **kwargs: Any,
) -> TwoPhaseContext:
    """Create a two-phase sandbox context.

    Returns a :class:`TwoPhaseContext` that starts in the *setup* phase
    (network allowed) and can transition to the *agent* phase (network
    restricted) via :meth:`TwoPhaseContext.transition_to_agent`.

    Args:
        mode: Sandbox mode - 'auto', 'basic', 'seatbelt', 'landlock', 'docker', 'openshell'.
        **kwargs: Extra options forwarded to the underlying sandbox constructor.

    Returns:
        A TwoPhaseContext instance.
    """
    return TwoPhaseContext(sandbox_mode=mode, **kwargs)
