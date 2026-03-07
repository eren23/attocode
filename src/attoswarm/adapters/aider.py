"""Aider subprocess adapter."""

from __future__ import annotations

import re

from attoswarm.adapters.base import SubprocessAdapter


class AiderAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="aider")

    @staticmethod
    def build_command(model: str = "", prompt: str = "") -> list[str]:
        cmd = ["aider", "--yes-always", "--no-auto-commits"]
        if model:
            cmd.extend(["--model", model])
        if prompt:
            cmd.extend(["--message", prompt])
        return cmd

    def _parse_stdout_line(self, line: str) -> dict:
        result = super()._parse_stdout_line(line)
        if "Tokens:" in line and "Cost:" in line:
            tok_m = re.search(r"Tokens:\s*([\d,]+)", line)
            cost_m = re.search(r"Cost:\s*\$([0-9.]+)", line)
            if tok_m:
                result["token_usage"] = {"total": int(tok_m.group(1).replace(",", ""))}
            if cost_m:
                result["cost_usd"] = float(cost_m.group(1))
        return result
