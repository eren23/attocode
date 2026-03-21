"""Codex MCP server adapter for multi-turn orchestration.

Spawns a ``codex mcp-server`` process and communicates via JSON-RPC
over stdio.  The first message for an agent uses the ``codex`` tool
call (which returns a ``threadId``); subsequent messages use
``codex-reply`` with the stored thread ID.
"""

from __future__ import annotations

import json as _json
from typing import Any

from attoswarm.adapters.base import AgentHandle, AgentMessage, AgentProcessSpec, SubprocessAdapter


class CodexMcpAdapter(SubprocessAdapter):
    """Codex adapter using MCP server for multi-turn orchestration."""

    def __init__(self, model: str = "gpt-5.3-codex") -> None:
        super().__init__(backend="codex-mcp")
        self._model = model
        self._thread_ids: dict[str, str] = {}  # agent_id -> threadId
        self._thread_task_ids: dict[str, str] = {}  # agent_id -> task_id owning threadId
        self._rpc_id = 0

    @staticmethod
    def build_command(model: str = "", prompt: str = "") -> list[str]:
        return ["codex", "mcp-server"]

    async def spawn(self, spec: AgentProcessSpec) -> AgentHandle:
        handle = await super().spawn(spec)
        # MCP spec requires initialize handshake before any tools/call
        init_rpc = {
            "jsonrpc": "2.0",
            "id": self._next_rpc_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "attoswarm", "version": "0.1.0"},
            },
        }
        if handle.process.stdin:
            handle.process.stdin.write((_json.dumps(init_rpc) + "\n").encode("utf-8"))
            await handle.process.stdin.drain()
        # Send initialized notification (required by MCP spec)
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        if handle.process.stdin:
            handle.process.stdin.write((_json.dumps(notif) + "\n").encode("utf-8"))
            await handle.process.stdin.drain()
        return handle

    def _next_rpc_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    async def send_message(self, handle: AgentHandle, msg: AgentMessage) -> None:
        if handle.process.stdin is None:
            return

        agent_id = handle.spec.agent_id
        task_id = msg.task_id or ""
        previous_task_id = self._thread_task_ids.get(agent_id, "")
        if task_id and previous_task_id and previous_task_id != task_id:
            # New task on the same worker: force a fresh Codex thread so
            # previous task context cannot bleed into the new assignment.
            self._thread_ids.pop(agent_id, None)

        if task_id:
            self._thread_task_ids[agent_id] = task_id

        thread_id = self._thread_ids.get(agent_id)

        if thread_id is None:
            # First message: use codex tool call
            rpc = self._build_tool_call(
                "codex",
                {
                    "prompt": msg.content,
                    "approval-policy": "full-auto",
                    "sandbox": "workspace-write",
                    "model": self._model,
                },
            )
        else:
            # Follow-up: use codex-reply with threadId
            rpc = self._build_tool_call(
                "codex-reply",
                {
                    "prompt": msg.content,
                    "threadId": thread_id,
                },
            )

        payload = _json.dumps(rpc) + "\n"
        handle.process.stdin.write(payload.encode("utf-8"))
        await handle.process.stdin.drain()

    def _build_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": self._next_rpc_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

    def _parse_stdout_line(self, line: str) -> dict:
        stripped = line.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            return super()._parse_stdout_line(line)

        try:
            data = _json.loads(stripped)
        except _json.JSONDecodeError:
            return super()._parse_stdout_line(line)

        if not isinstance(data, dict):
            return super()._parse_stdout_line(line)

        # JSON-RPC response
        if "result" in data:
            return self._handle_rpc_result(data, line)

        # JSON-RPC error
        if "error" in data:
            err = data["error"]
            error_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return {
                "type": "task_failed",
                "payload": {
                    "line": line,
                    "backend": self._backend,
                    "event_kind": "task_failed",
                    "message": error_msg,
                },
            }

        return super()._parse_stdout_line(line)

    def _handle_rpc_result(self, data: dict, line: str) -> dict:
        result = data.get("result", {})

        # Extract threadId from first codex tool response
        thread_id = None
        message_text = ""

        if isinstance(result, dict):
            thread_id = result.get("threadId")
            message_text = result.get("message", "")
            status = result.get("status", "")
        elif isinstance(result, list):
            # MCP tool results come as content array
            for item in result:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    if text:
                        try:
                            inner = _json.loads(text)
                            if isinstance(inner, dict):
                                thread_id = thread_id or inner.get("threadId")
                                message_text = inner.get("message", message_text)
                                status = inner.get("status", "")
                        except _json.JSONDecodeError:
                            message_text = text
            if not message_text:
                status = ""
        else:
            message_text = str(result)
            status = ""

        payload = {
            "line": line,
            "backend": self._backend,
            "event_kind": "task_done" if status == "completed" else "progress",
            "message": message_text,
        }

        if thread_id:
            payload["thread_id"] = thread_id

        ev_type = "task_done" if status == "completed" else "log"
        if status == "error" or status == "failed":
            ev_type = "task_failed"
            payload["event_kind"] = "task_failed"

        return {"type": ev_type, "payload": payload}

    def store_thread_id(self, agent_id: str, thread_id: str) -> None:
        """Explicitly associate an agent with a Codex thread."""
        self._thread_ids[agent_id] = thread_id

    def get_thread_id(self, agent_id: str) -> str | None:
        """Return the stored threadId for an agent, if any."""
        return self._thread_ids.get(agent_id)
