"""OpenCode subprocess adapter.

Spawns ``opencode run`` in headless mode with ``--format json`` to get
structured JSONL output.  Parses ``step_start``, ``text``, and
``step_finish`` events, extracting token usage and cost from the latter.
"""

from __future__ import annotations

import json as _json

from attoswarm.adapters.base import SubprocessAdapter


class OpencodeAdapter(SubprocessAdapter):
    def __init__(self) -> None:
        super().__init__(backend="opencode")

    @staticmethod
    def build_command(model: str = "", prompt: str = "") -> list[str]:
        cmd = ["opencode", "run"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--format", "json"])
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

            # ── step_finish: contains token usage and cost ──
            if event_type == "step_finish":
                part = data.get("part", {})
                token_usage = None
                cost_usd = None

                if isinstance(part, dict):
                    tokens = part.get("tokens")
                    if isinstance(tokens, dict):
                        input_tok = tokens.get("input", 0)
                        output_tok = tokens.get("output", 0)
                        reasoning_tok = tokens.get("reasoning", 0)
                        cache = tokens.get("cache", {})
                        cache_read = cache.get("read", 0) if isinstance(cache, dict) else 0
                        cache_write = cache.get("write", 0) if isinstance(cache, dict) else 0
                        token_usage = {
                            "total": input_tok + output_tok + reasoning_tok,
                            "input": input_tok,
                            "output": output_tok,
                            "reasoning": reasoning_tok,
                            "cached_read": cache_read,
                            "cached_write": cache_write,
                        }

                    raw_cost = part.get("cost")
                    if isinstance(raw_cost, (int, float)):
                        cost_usd = float(raw_cost)

                return {
                    "type": "log",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "step_finish",
                    },
                    "token_usage": token_usage,
                    "cost_usd": cost_usd,
                }

            # ── text: streaming content output ──
            if event_type == "text":
                part = data.get("part", {})
                text = part.get("text", "") if isinstance(part, dict) else ""
                return {
                    "type": "log",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "text",
                        "message": text,
                    },
                }

            # ── step_start: new LLM call beginning ──
            if event_type == "step_start":
                return {
                    "type": "log",
                    "payload": {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": "step_start",
                    },
                }

            # Unrecognised JSON event — delegate to base class
            return super()._parse_stdout_line(line)

        return super()._parse_stdout_line(line)
