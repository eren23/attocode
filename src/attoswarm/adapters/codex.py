"""Codex CLI subprocess adapter."""

from __future__ import annotations

import json as _json

from attoswarm.adapters.base import SubprocessAdapter


class CodexAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="codex")

    @staticmethod
    def build_command(model: str = "gpt-5.3-codex", prompt: str = "") -> list[str]:
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
            except _json.JSONDecodeError:
                return super()._parse_stdout_line(line)

            if not isinstance(data, dict):
                return super()._parse_stdout_line(line)

            event_type = data.get("type", "")

            # ── Current codex JSONL format ──
            if event_type == "item.completed":
                item = data.get("item", {})
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    return {
                        "type": "log",
                        "payload": {
                            "line": line,
                            "backend": self._backend,
                            "event_kind": "agent_message",
                            "message": item.get("text", ""),
                        },
                    }
                return {
                    "type": "log",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "progress",
                    },
                }

            if event_type == "turn.completed":
                usage = data.get("usage", {})
                payload: dict = {
                    "line": line,
                    "backend": self._backend,
                    "event_kind": "progress",
                }
                if isinstance(usage, dict):
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cached = usage.get("cached_input_tokens", 0)
                    payload["token_usage"] = {
                        "total": input_tokens + output_tokens,
                        "input": input_tokens,
                        "output": output_tokens,
                        "cached_input": cached,
                    }
                return {"type": "log", "payload": payload}

            if event_type == "thread.started":
                return {
                    "type": "log",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "progress",
                        "thread_id": data.get("thread_id", ""),
                    },
                }

            if event_type == "turn.started":
                return {
                    "type": "log",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "progress",
                    },
                }

            # ── Legacy format (backward compat) ──
            status = data.get("status")
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
            if status == "error":
                return {
                    "type": "task_failed",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "task_failed",
                        "message": data.get("error", ""),
                    },
                }

            # Unrecognized JSON — delegate to base class generic JSON protocol
            return super()._parse_stdout_line(line)

        return super()._parse_stdout_line(line)
