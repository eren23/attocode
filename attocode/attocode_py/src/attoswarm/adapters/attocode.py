"""Attocode subprocess adapter."""

from __future__ import annotations

from attoswarm.adapters.base import SubprocessAdapter


class AttocodeAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="attocode")
