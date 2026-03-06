"""Aider subprocess adapter."""

from __future__ import annotations

from attoswarm.adapters.base import SubprocessAdapter


class AiderAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="aider")
