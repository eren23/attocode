"""Attocode subprocess adapter."""

from __future__ import annotations

from attoswarm.adapters.base import SubprocessAdapter


class AttocodeAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="attocode")

    @staticmethod
    def build_command(model: str = "", prompt: str = "") -> list[str]:
        cmd = ["attocode", "--non-interactive"]
        if model:
            cmd.extend(["--model", model])
        if prompt:
            cmd.append(prompt)
        return cmd
