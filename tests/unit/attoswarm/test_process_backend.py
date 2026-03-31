"""Tests for ProcessBackend, SubprocessBackend, and AgentExecutor.

Uses mocks exclusively -- no real subprocesses are spawned.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attoswarm.adapters.base import (
    AgentEvent,
    AgentExecutor,
    AgentHandle,
    AgentMessage,
    AgentProcessSpec,
    AgentRuntimeStatus,
    ProcessBackend,
    SubprocessBackend,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(agent_id: str = "a1") -> AgentProcessSpec:
    return AgentProcessSpec(
        agent_id=agent_id,
        backend="test",
        binary="/usr/bin/true",
        args=[],
    )


def _make_handle(spec: AgentProcessSpec | None = None) -> AgentHandle:
    """Create a handle with a mock process."""
    spec = spec or _make_spec()
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.returncode = None
    proc.pid = 42
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return AgentHandle(spec=spec, process=proc)


def _mock_backend() -> MagicMock:
    """Return a MagicMock satisfying the ProcessBackend protocol."""
    backend = MagicMock()
    backend.spawn_process = AsyncMock()
    backend.send_stdin = AsyncMock()
    backend.read_stdout_lines = AsyncMock(return_value=[])
    backend.read_stderr_lines = AsyncMock(return_value=[])
    backend.kill = AsyncMock()
    backend.get_process_status = AsyncMock()
    return backend


# ---------------------------------------------------------------------------
# Test 5a: AgentExecutor.send_message formats JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_executor_send_message_formats_json():
    """send_message should serialise the message as a single JSON line to stdin."""
    backend = _mock_backend()
    executor = AgentExecutor(backend, backend_name="test")
    handle = _make_handle()

    msg = AgentMessage(
        message_id="m1",
        task_id="t1",
        kind="task_assign",
        content="Do the thing",
    )

    await executor.send_message(handle, msg)

    # The backend should have received exactly one send_stdin call
    backend.send_stdin.assert_awaited_once()
    args = backend.send_stdin.call_args
    raw_data: str = args[0][1]  # second positional arg is the data string

    # Should end with newline
    assert raw_data.endswith("\n")

    # Should be valid JSON
    parsed = json.loads(raw_data.strip())
    assert parsed["message_id"] == "m1"
    assert parsed["task_id"] == "t1"
    assert parsed["kind"] == "task_assign"
    assert parsed["content"] == "Do the thing"


# ---------------------------------------------------------------------------
# Test 5b: AgentExecutor.read_output parses events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_executor_read_output_parses_events():
    """read_output should turn JSON stdout lines into AgentEvent objects."""
    backend = _mock_backend()

    json_line = json.dumps({
        "event": "task_done",
        "message": "done!",
        "artifacts": ["a.py"],
        "task_id": "t1",
        "token_usage": {"total": 100},
        "cost_usd": 0.05,
    })

    backend.read_stdout_lines = AsyncMock(return_value=[json_line])
    backend.read_stderr_lines = AsyncMock(return_value=[])

    executor = AgentExecutor(backend, backend_name="test")
    handle = _make_handle()

    events = await executor.read_output(handle)

    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, AgentEvent)
    assert ev.type == "task_done"
    assert ev.payload["message"] == "done!"
    assert ev.payload["artifacts"] == ["a.py"]
    assert ev.token_usage == {"total": 100}
    assert ev.cost_usd == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_agent_executor_read_output_parses_plain_lines():
    """read_output should handle plain text lines as 'log' events."""
    backend = _mock_backend()
    backend.read_stdout_lines = AsyncMock(return_value=["hello world"])
    backend.read_stderr_lines = AsyncMock(return_value=[])

    executor = AgentExecutor(backend, backend_name="test")
    handle = _make_handle()

    events = await executor.read_output(handle)

    assert len(events) == 1
    assert events[0].type == "log"
    assert events[0].payload["line"] == "hello world"


@pytest.mark.asyncio
async def test_agent_executor_read_output_parses_stderr():
    """read_output should produce stderr events for stderr lines."""
    backend = _mock_backend()
    backend.read_stdout_lines = AsyncMock(return_value=[])
    backend.read_stderr_lines = AsyncMock(return_value=["an error"])

    executor = AgentExecutor(backend, backend_name="test")
    handle = _make_handle()

    events = await executor.read_output(handle)

    assert len(events) == 1
    assert events[0].type == "stderr"
    assert events[0].payload["line"] == "an error"


# ---------------------------------------------------------------------------
# Test 5c: AgentExecutor.terminate delegates to backend.kill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_executor_terminate_calls_kill():
    """terminate() should delegate to backend.kill with the reason."""
    backend = _mock_backend()
    executor = AgentExecutor(backend, backend_name="test")
    handle = _make_handle()

    await executor.terminate(handle, "test shutdown")

    backend.kill.assert_awaited_once_with(handle, "test shutdown")


# ---------------------------------------------------------------------------
# Test 5d: SubprocessBackend satisfies ProcessBackend protocol
# ---------------------------------------------------------------------------


def test_subprocess_backend_satisfies_protocol():
    """SubprocessBackend should implement all methods required by ProcessBackend."""
    sb = SubprocessBackend()
    # ProcessBackend is a Protocol (not @runtime_checkable), so we verify
    # structural conformance by checking every required method exists and
    # is callable.
    required_methods = [
        "spawn_process",
        "send_stdin",
        "read_stdout_lines",
        "read_stderr_lines",
        "kill",
        "get_process_status",
    ]
    for method_name in required_methods:
        attr = getattr(sb, method_name, None)
        assert attr is not None, f"Missing method: {method_name}"
        assert callable(attr), f"{method_name} is not callable"

    # Verify that SubprocessBackend can be used where ProcessBackend is expected
    # by constructing an AgentExecutor (which takes a ProcessBackend parameter)
    executor = AgentExecutor(sb, backend_name="test")
    assert executor._backend is sb
