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
    from attoswarm.adapters.base import AgentAdapter


def get_adapter(backend: str) -> AgentAdapter:
    b = backend.lower()
    if b == "claude":
        return ClaudeAdapter()
    if b == "codex":
        return CodexAdapter()
    if b == "codex-mcp":
        return CodexMcpAdapter()
    if b == "aider":
        return AiderAdapter()
    if b == "attocode":
        return AttocodeAdapter()
    if b == "opencode":
        return OpencodeAdapter()
    raise ValueError(f"Unsupported backend: {backend}")
