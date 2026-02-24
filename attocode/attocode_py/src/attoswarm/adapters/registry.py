"""Adapter registry for built-in backends."""

from __future__ import annotations

from attoswarm.adapters.aider import AiderAdapter
from attoswarm.adapters.attocode import AttocodeAdapter
from attoswarm.adapters.base import AgentAdapter
from attoswarm.adapters.claude import ClaudeAdapter
from attoswarm.adapters.codex import CodexAdapter


def get_adapter(backend: str) -> AgentAdapter:
    b = backend.lower()
    if b == "claude":
        return ClaudeAdapter()
    if b == "codex":
        return CodexAdapter()
    if b == "aider":
        return AiderAdapter()
    if b == "attocode":
        return AttocodeAdapter()
    raise ValueError(f"Unsupported backend: {backend}")
