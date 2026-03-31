"""Adapter registry for built-in backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from attoswarm.adapters.aider import AiderAdapter
from attoswarm.adapters.attocode import AttocodeAdapter
from attoswarm.adapters.claude import ClaudeAdapter
from attoswarm.adapters.codex import CodexAdapter
from attoswarm.adapters.codex_mcp import CodexMcpAdapter
from attoswarm.adapters.opencode import OpencodeAdapter

if TYPE_CHECKING:
    from attoswarm.adapters.base import AgentAdapter, AgentExecutor, ProcessBackend

_ADAPTER_MAP: dict[str, type] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "codex-mcp": CodexMcpAdapter,
    "aider": AiderAdapter,
    "attocode": AttocodeAdapter,
    "opencode": OpencodeAdapter,
}


def get_adapter(backend: str) -> AgentAdapter:
    """Return an adapter for the given backend name.

    This is the original entry point.  All returned adapters satisfy
    the ``AgentAdapter`` protocol (spawn / send_message / read_output /
    terminate / get_status).
    """
    b = backend.lower()
    cls = _ADAPTER_MAP.get(b)
    if cls is None:
        raise ValueError(f"Unsupported backend: {backend}")
    return cls()


def get_backend(backend: str) -> ProcessBackend:
    """Return a ``ProcessBackend`` for the given backend name.

    Since every ``SubprocessAdapter`` subclass now also satisfies the
    ``ProcessBackend`` protocol, this just returns the same adapter
    instance -- but typed as a ``ProcessBackend`` so callers can program
    against the low-level interface.
    """
    b = backend.lower()
    cls = _ADAPTER_MAP.get(b)
    if cls is None:
        raise ValueError(f"Unsupported backend: {backend}")
    return cls()


def get_executor(backend: str) -> AgentExecutor:
    """Return an ``AgentExecutor`` wrapping a ``ProcessBackend``.

    This is the new preferred entry point for code that wants the
    two-layer split (ProcessBackend + AgentExecutor).  The executor
    satisfies the same duck-typed interface as ``AgentAdapter``
    (spawn / send_message / read_output / terminate / get_status).
    """
    from attoswarm.adapters.base import AgentExecutor, SubprocessBackend

    process_backend = SubprocessBackend()
    return AgentExecutor(backend=process_backend, backend_name=backend.lower())
