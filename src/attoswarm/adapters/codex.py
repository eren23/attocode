"""Codex CLI subprocess adapter."""

from __future__ import annotations

import json as _json

from attoswarm.adapters.base import SubprocessAdapter


class CodexAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="codex")

    @staticmethod
    def build_command(model: str = "o3", prompt: str = "") -> list[str]:
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write"]
        if model:
            cmd.extend(["--model", model])
        if prompt:
            cmd.append(prompt)
        return cmd

    def _parse_stdout_line(self, line: str) -> dict:
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = _json.loads(stripped)
                if isinstance(data, dict) and "status" in data:
                    status = data["status"]
                    if status == "completed":
                        return {
                            "type": "task_done",
                            "payload": {
                                "line": line,
                                "backend": self._backend,
                                "event_kind": "task_done",
                                "message": data.get("message", ""),
                            },
                        }
                    elif status == "error":
                        return {
                            "type": "task_failed",
                            "payload": {
                                "line": line,
                                "backend": self._backend,
                                "event_kind": "task_failed",
                                "message": data.get("error", ""),
                            },
                        }
            except _json.JSONDecodeError:
                pass
        return super()._parse_stdout_line(line)
