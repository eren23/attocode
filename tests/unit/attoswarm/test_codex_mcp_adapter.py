"""Tests for CodexMcpAdapter JSON-RPC parsing and thread management."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

from attoswarm.adapters.codex_mcp import CodexMcpAdapter
from attoswarm.adapters.base import AgentHandle, AgentMessage, AgentProcessSpec


def _adapter() -> CodexMcpAdapter:
    return CodexMcpAdapter(model="gpt-5.3-codex")


class TestBuildCommand:
    def test_returns_mcp_server_command(self) -> None:
        cmd = CodexMcpAdapter.build_command()
        assert cmd == ["codex", "mcp-server"]


class TestBuildToolCall:
    def test_first_message_uses_codex_tool(self) -> None:
        adapter = _adapter()
        rpc = adapter._build_tool_call("codex", {"prompt": "hello", "model": "gpt-5.3-codex"})
        assert rpc["jsonrpc"] == "2.0"
        assert rpc["method"] == "tools/call"
        assert rpc["params"]["name"] == "codex"
        assert rpc["params"]["arguments"]["prompt"] == "hello"

    def test_reply_uses_codex_reply_tool(self) -> None:
        adapter = _adapter()
        rpc = adapter._build_tool_call("codex-reply", {"prompt": "next", "threadId": "t-1"})
        assert rpc["params"]["name"] == "codex-reply"
        assert rpc["params"]["arguments"]["threadId"] == "t-1"

    def test_rpc_ids_increment(self) -> None:
        adapter = _adapter()
        r1 = adapter._build_tool_call("codex", {"prompt": "a"})
        r2 = adapter._build_tool_call("codex", {"prompt": "b"})
        assert r1["id"] < r2["id"]


class TestParseStdoutLine:
    def test_rpc_result_completed(self) -> None:
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "completed", "message": "Done", "threadId": "t-42"},
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_done"
        assert parsed["payload"]["event_kind"] == "task_done"
        assert parsed["payload"]["message"] == "Done"
        assert parsed["payload"]["thread_id"] == "t-42"

    def test_rpc_result_progress(self) -> None:
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "in_progress", "message": "Working..."},
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "log"
        assert parsed["payload"]["event_kind"] == "progress"

    def test_rpc_result_error_status(self) -> None:
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "error", "message": "OOM"},
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_failed"
        assert parsed["payload"]["event_kind"] == "task_failed"

    def test_rpc_result_failed_status(self) -> None:
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "failed", "message": "crash"},
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_failed"

    def test_rpc_error(self) -> None:
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_failed"
        assert "Invalid request" in parsed["payload"]["message"]

    def test_rpc_error_string(self) -> None:
        """Non-dict error value should not crash (Fix 5)."""
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": "something went wrong",
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_failed"
        assert "something went wrong" in parsed["payload"]["message"]

    def test_rpc_error_integer(self) -> None:
        """Integer error value should not crash (Fix 5)."""
        adapter = _adapter()
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": 42,
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_failed"
        assert "42" in parsed["payload"]["message"]

    def test_rpc_result_content_array(self) -> None:
        adapter = _adapter()
        inner = json.dumps({"status": "completed", "message": "merged", "threadId": "t-99"})
        rpc_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": [{"type": "text", "text": inner}],
        })
        parsed = adapter._parse_stdout_line(rpc_response)
        assert parsed["type"] == "task_done"
        assert parsed["payload"]["message"] == "merged"
        assert parsed["payload"]["thread_id"] == "t-99"

    def test_plain_text_falls_through(self) -> None:
        adapter = _adapter()
        parsed = adapter._parse_stdout_line("some plain log line")
        assert parsed["type"] == "log"
        assert parsed["payload"]["backend"] == "codex-mcp"

    def test_non_json_rpc_json_falls_through(self) -> None:
        adapter = _adapter()
        parsed = adapter._parse_stdout_line('{"event":"task_done","message":"ok"}')
        # Should be handled by parent class JSON line protocol
        assert parsed["type"] == "task_done"


class TestThreadManagement:
    def test_store_and_get_thread_id(self) -> None:
        adapter = _adapter()
        assert adapter.get_thread_id("agent-1") is None
        adapter.store_thread_id("agent-1", "t-100")
        assert adapter.get_thread_id("agent-1") == "t-100"

    def test_separate_agents_separate_threads(self) -> None:
        adapter = _adapter()
        adapter.store_thread_id("agent-1", "t-1")
        adapter.store_thread_id("agent-2", "t-2")
        assert adapter.get_thread_id("agent-1") == "t-1"
        assert adapter.get_thread_id("agent-2") == "t-2"

    def test_new_task_on_same_worker_clears_old_thread(self) -> None:
        adapter = _adapter()
        adapter.store_thread_id("agent-1", "thread-old")
        adapter._thread_task_ids["agent-1"] = "task-old"

        writes: list[bytes] = []

        class _FakeStdin:
            def write(self, data: bytes) -> None:
                writes.append(data)

            async def drain(self) -> None:
                return None

        @dataclass
        class _FakeProcess:
            stdin: _FakeStdin = field(default_factory=_FakeStdin)

        spec = AgentProcessSpec(agent_id="agent-1", backend="codex-mcp", binary="codex", args=[])
        handle = AgentHandle(spec=spec, process=_FakeProcess())  # type: ignore[arg-type]
        msg = AgentMessage(message_id="m1", task_id="task-new", kind="task_assign", content="do new task")

        asyncio.new_event_loop().run_until_complete(adapter.send_message(handle, msg))

        payload = json.loads(writes[0].decode("utf-8").strip())
        assert payload["params"]["name"] == "codex"
        assert adapter.get_thread_id("agent-1") is None
        assert adapter._thread_task_ids["agent-1"] == "task-new"


class TestCodexAdapterDefaultModel:
    def test_codex_adapter_default_model(self) -> None:
        from attoswarm.adapters.codex import CodexAdapter

        cmd = CodexAdapter.build_command()
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "gpt-5.3-codex"


class TestSpawnHandshake:
    """MCP initialize handshake is sent on spawn (Fix 3)."""

    def test_spawn_sends_initialize_and_notification(self) -> None:
        adapter = _adapter()
        written: list[bytes] = []

        mock_stdin = MagicMock()
        mock_stdin.write = lambda data: written.append(data)
        mock_stdin.drain = AsyncMock()

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin

        # Mock super().spawn() to return a handle with our mock process
        fake_spec = MagicMock()
        fake_handle = MagicMock()
        fake_handle.process = mock_process

        async def _run() -> None:
            # Patch super().spawn
            original_spawn = type(adapter).__mro__[1].spawn  # SubprocessAdapter.spawn

            async def fake_spawn(self_inner: object, spec: object) -> object:
                return fake_handle

            type(adapter).__mro__[1].spawn = fake_spawn
            try:
                result = await adapter.spawn(fake_spec)
            finally:
                type(adapter).__mro__[1].spawn = original_spawn

            assert result is fake_handle
            # Two writes: initialize RPC + initialized notification
            assert len(written) == 2
            init_rpc = json.loads(written[0].decode("utf-8").strip())
            assert init_rpc["method"] == "initialize"
            assert init_rpc["params"]["protocolVersion"] == "2024-11-05"
            assert init_rpc["params"]["clientInfo"]["name"] == "attoswarm"

            notif = json.loads(written[1].decode("utf-8").strip())
            assert notif["method"] == "notifications/initialized"
            assert "id" not in notif  # notifications have no id

        asyncio.new_event_loop().run_until_complete(_run())


class TestHarvesterThreadWiring:
    """Thread ID wiring from output_harvester (Fix 4b)."""

    def test_thread_id_stored_via_harvester_path(self) -> None:
        """Simulate the harvester calling store_thread_id when payload has thread_id."""
        adapter = _adapter()
        assert adapter.get_thread_id("agent-1") is None

        # Simulate what the harvester does
        payload = {"thread_id": "t-500", "message": "Done"}
        if payload.get("thread_id"):
            if hasattr(adapter, "store_thread_id"):
                adapter.store_thread_id("agent-1", payload["thread_id"])

        assert adapter.get_thread_id("agent-1") == "t-500"


class TestRegistryCodexMcp:
    def test_registry_returns_codex_mcp(self) -> None:
        from attoswarm.adapters.registry import get_adapter

        adapter = get_adapter("codex-mcp")
        assert isinstance(adapter, CodexMcpAdapter)

    def test_registry_returns_codex(self) -> None:
        from attoswarm.adapters.codex import CodexAdapter
        from attoswarm.adapters.registry import get_adapter

        adapter = get_adapter("codex")
        assert isinstance(adapter, CodexAdapter)
