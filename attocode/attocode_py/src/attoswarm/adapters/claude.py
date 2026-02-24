"""Claude Code subprocess adapter."""

from __future__ import annotations

from attoswarm.adapters.base import SubprocessAdapter


class ClaudeAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="claude")
