"""Sandbox implementations for safe command execution.

Available sandboxes:
- BasicSandbox: Allowlist/blocklist validation (all platforms)
- SeatbeltSandbox: macOS sandbox-exec isolation
- LandlockSandbox: Linux Landlock LSM isolation
- DockerSandbox: Docker container isolation

Use create_sandbox() to auto-detect the best available sandbox.
"""

import sys
from typing import Any

from attocode.integrations.safety.sandbox.basic import (
    BasicSandbox,
    SandboxOptions,
    SandboxResult,
)

__all__ = [
    "BasicSandbox",
    "SandboxOptions",
    "SandboxResult",
    "create_sandbox",
]

# Lazy imports for platform-specific sandboxes
_SeatbeltSandbox: type | None = None
_LandlockSandbox: type | None = None
_DockerSandbox: type | None = None


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


def create_sandbox(
    mode: str = "auto",
    **kwargs: Any,
) -> Any:
    """Create the best available sandbox for the current platform.

    Args:
        mode: Sandbox mode - 'auto', 'basic', 'seatbelt', 'landlock', 'docker'.
        **kwargs: Options passed to the sandbox constructor.

    Returns:
        A sandbox instance.
    """
    if mode == "basic":
        return BasicSandbox(**kwargs)

    if mode == "seatbelt":
        cls = _load_seatbelt()
        if cls and cls.is_available():
            return cls(**kwargs)
        raise RuntimeError("Seatbelt sandbox not available")

    if mode == "landlock":
        cls = _load_landlock()
        if cls and cls.is_available():
            return cls(**kwargs)
        raise RuntimeError("Landlock sandbox not available")

    if mode == "docker":
        cls = _load_docker()
        if cls and cls.is_available():
            return cls(**kwargs)
        raise RuntimeError("Docker sandbox not available")

    # Auto-detect
    if sys.platform == "darwin":
        cls = _load_seatbelt()
        if cls and cls.is_available():
            return cls(**kwargs)

    if sys.platform == "linux":
        cls = _load_landlock()
        if cls and cls.is_available():
            return cls(**kwargs)

    cls = _load_docker()
    if cls and cls.is_available():
        return cls(**kwargs)

    # Fall back to basic
    return BasicSandbox(**kwargs)
