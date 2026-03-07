"""Claude Code subprocess adapter."""

from __future__ import annotations

import re

from attoswarm.adapters.base import SubprocessAdapter


class ClaudeAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="claude")

    @staticmethod
    def build_command(model: str = "", prompt: str = "") -> list[str]:
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if model:
            cmd.extend(["--model", model])
        if prompt:
            cmd.append(prompt)
        return cmd

    def _parse_stdout_line(self, line: str) -> dict:
        result = super()._parse_stdout_line(line)
        # Claude outputs cost info like "Cost: $0.05 | Tokens: 1234"
        if "Cost:" in line and "Tokens:" in line:
            cost_m = re.search(r"Cost:\s*\$([0-9.]+)", line)
            tok_m = re.search(r"Tokens:\s*(\d+)", line)
            if cost_m:
                result["cost_usd"] = float(cost_m.group(1))
            if tok_m:
                result["token_usage"] = {"total": int(tok_m.group(1))}
        return result
