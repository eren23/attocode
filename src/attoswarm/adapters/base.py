"""Agent adapter interfaces and subprocess implementation.

Provides two abstraction layers:

1. **ProcessBackend** (low-level) -- spawning processes, writing stdin,
   reading stdout lines, killing processes.  ``SubprocessBackend`` is the
   default implementation.

2. **AgentExecutor** (high-level) -- agent lifecycle on top of a
   ``ProcessBackend``.  Translates between ``AgentMessage``/``AgentEvent``
   and raw process I/O.

The original ``SubprocessAdapter`` remains as the unified class that
satisfies both the ``AgentAdapter`` protocol *and* the ``ProcessBackend``
protocol for full backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _pump_stream(
    stream: asyncio.StreamReader | None,
    queue: asyncio.Queue[str],
    *,
    log_file: str | None = None,
    stream_name: str = "stdout",
) -> None:
    """Pump lines from a stream into a queue, optionally tee'ing to a log file."""
    if stream is None:
        return
    log_path = Path(log_file) if log_file else None
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        if log_path:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"[{stream_name}] {text}")
            except OSError:
                pass
        await queue.put(text)


@dataclass(slots=True)
class AgentProcessSpec:
    agent_id: str
    backend: str
    binary: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = "."
    role: str = "worker"
    model: str = ""
    write_access: bool = False
    log_file: str | None = None


@dataclass(slots=True)
class AgentMessage:
    message_id: str
    task_id: str | None
    kind: str
    content: str
    attachments: list[str] = field(default_factory=list)
    deadline_ts: str | None = None


@dataclass(slots=True)
class AgentEvent:
    seq: int
    timestamp: str
    type: str
    task_id: str | None
    payload: dict
    token_usage: dict[str, int] | None = None
    cost_usd: float | None = None


@dataclass(slots=True)
class AgentRuntimeStatus:
    pid: int | None
    state: str
    last_heartbeat_ts: str
    exit_code: int | None = None
    stderr_tail: str = ""


@dataclass(slots=True)
class AgentHandle:
    spec: AgentProcessSpec
    process: asyncio.subprocess.Process
    stdout_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    stderr_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    seq: int = 1
    last_heartbeat_ts: str = field(default_factory=now_iso)
    stderr_tail: str = ""


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class ProcessBackend(Protocol):
    """Low-level process management protocol.

    Abstracts how agent processes are spawned and communicated with,
    independent of the agent message protocol.
    """

    async def spawn_process(self, spec: AgentProcessSpec) -> AgentHandle:
        """Launch a new agent process."""
        ...

    async def send_stdin(self, handle: AgentHandle, data: str) -> None:
        """Write data to the agent's stdin."""
        ...

    async def read_stdout_lines(self, handle: AgentHandle) -> list[str]:
        """Read available lines from the agent's stdout."""
        ...

    async def read_stderr_lines(self, handle: AgentHandle) -> list[str]:
        """Read available lines from the agent's stderr."""
        ...

    async def kill(self, handle: AgentHandle, reason: str) -> None:
        """Terminate the agent process."""
        ...

    async def get_process_status(self, handle: AgentHandle) -> AgentRuntimeStatus:
        """Get the current process status."""
        ...


class AgentAdapter(Protocol):
    """High-level agent lifecycle protocol (original interface).

    Kept for backward compatibility.  New code should prefer
    ``AgentExecutor`` wrapping a ``ProcessBackend``.
    """

    async def spawn(self, spec: AgentProcessSpec) -> AgentHandle: ...

    async def send_message(self, handle: AgentHandle, msg: AgentMessage) -> None: ...

    async def read_output(self, handle: AgentHandle, since_seq: int | None = None) -> list[AgentEvent]: ...

    async def terminate(self, handle: AgentHandle, reason: str) -> None: ...

    async def get_status(self, handle: AgentHandle) -> AgentRuntimeStatus: ...


# ---------------------------------------------------------------------------
# SubprocessBackend -- low-level process ops extracted from SubprocessAdapter
# ---------------------------------------------------------------------------


class SubprocessBackend:
    """Low-level subprocess management implementing ``ProcessBackend``.

    Handles spawning, stdin/stdout I/O, stream pumping, and process
    termination without any knowledge of the agent message protocol.
    """

    async def spawn_process(self, spec: AgentProcessSpec) -> AgentHandle:
        """Launch a new agent process."""
        # Create the log file eagerly so it exists even if the agent
        # produces no output.  An empty file = "spawned but silent"
        # vs missing file = "never spawned".
        if spec.log_file:
            log_path = Path(spec.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch(exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            spec.binary,
            *spec.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=spec.cwd,
            env=spec.env if spec.env else None,
        )
        handle = AgentHandle(spec=spec, process=process)
        asyncio.create_task(
            self._pump_stream(
                process.stdout,
                handle.stdout_queue,
                log_file=spec.log_file,
                stream_name="stdout",
            )
        )
        asyncio.create_task(
            self._pump_stream(
                process.stderr,
                handle.stderr_queue,
                log_file=spec.log_file,
                stream_name="stderr",
            )
        )
        return handle

    async def send_stdin(self, handle: AgentHandle, data: str) -> None:
        """Write *data* to the agent's stdin."""
        if handle.process.stdin is None:
            return
        handle.process.stdin.write(data.encode("utf-8"))
        await handle.process.stdin.drain()

    async def read_stdout_lines(self, handle: AgentHandle) -> list[str]:
        """Drain all available lines from the agent's stdout queue."""
        lines: list[str] = []
        while not handle.stdout_queue.empty():
            line = await handle.stdout_queue.get()
            lines.append(line.rstrip("\n"))
        return lines

    async def read_stderr_lines(self, handle: AgentHandle) -> list[str]:
        """Drain all available lines from the agent's stderr queue."""
        lines: list[str] = []
        while not handle.stderr_queue.empty():
            line = await handle.stderr_queue.get()
            lines.append(line.rstrip("\n"))
        return lines

    async def kill(self, handle: AgentHandle, reason: str) -> None:
        """Terminate the agent process."""
        _ = reason
        if handle.process.returncode is not None:
            return
        handle.process.terminate()
        try:
            await asyncio.wait_for(handle.process.wait(), timeout=5)
        except TimeoutError:
            handle.process.kill()
            await handle.process.wait()

    async def get_process_status(self, handle: AgentHandle) -> AgentRuntimeStatus:
        """Get the current process status."""
        return AgentRuntimeStatus(
            pid=handle.process.pid,
            state="running" if handle.process.returncode is None else "exited",
            last_heartbeat_ts=handle.last_heartbeat_ts,
            exit_code=handle.process.returncode,
        )

    async def _pump_stream(
        self,
        stream: asyncio.StreamReader | None,
        queue: asyncio.Queue[str],
        *,
        log_file: str | None = None,
        stream_name: str = "stdout",
    ) -> None:
        await _pump_stream(stream, queue, log_file=log_file, stream_name=stream_name)


# ---------------------------------------------------------------------------
# AgentExecutor -- high-level agent lifecycle on top of a ProcessBackend
# ---------------------------------------------------------------------------


class AgentExecutor:
    """High-level agent lifecycle management on top of a ``ProcessBackend``.

    Translates between the agent message protocol (``AgentMessage``,
    ``AgentEvent``) and the low-level process I/O (stdin/stdout lines).

    The *protocol_parser* parameter is an optional object with a
    ``parse_line(line, handle) -> AgentEvent | None`` method.  When
    omitted, the executor uses the built-in ``_parse_stdout_line`` /
    ``_parse_stderr_line`` methods which can be overridden by subclasses.
    """

    def __init__(
        self,
        backend: ProcessBackend,
        backend_name: str = "",
        protocol_parser: Any = None,
    ) -> None:
        self._backend = backend
        self._backend_name = backend_name
        self._parser = protocol_parser

    # -- AgentAdapter-compatible interface ----------------------------------

    async def spawn(self, spec: AgentProcessSpec) -> AgentHandle:
        """Launch a new agent."""
        return await self._backend.spawn_process(spec)

    async def send_message(self, handle: AgentHandle, msg: AgentMessage) -> None:
        """Send a message to the agent via stdin."""
        payload = json.dumps({
            "message_id": msg.message_id,
            "task_id": msg.task_id,
            "kind": msg.kind,
            "content": msg.content,
        })
        await self._backend.send_stdin(handle, payload + "\n")

    async def read_output(
        self, handle: AgentHandle, since_seq: int | None = None,
    ) -> list[AgentEvent]:
        """Read and parse output events from the agent."""
        events: list[AgentEvent] = []

        # Stdout -> agent events
        stdout_lines = await self._backend.read_stdout_lines(handle)
        for line in stdout_lines:
            handle.last_heartbeat_ts = now_iso()
            event = self._parse_event(line, handle, stream="stdout")
            if event and (since_seq is None or event.seq > since_seq):
                events.append(event)

        # Stderr -> stderr events
        stderr_lines = await self._backend.read_stderr_lines(handle)
        for line in stderr_lines:
            event = self._parse_event(line, handle, stream="stderr")
            if event and (since_seq is None or event.seq > since_seq):
                events.append(event)

        return events

    async def terminate(self, handle: AgentHandle, reason: str) -> None:
        """Terminate the agent."""
        await self._backend.kill(handle, reason)

    async def get_status(self, handle: AgentHandle) -> AgentRuntimeStatus:
        """Get agent status."""
        return await self._backend.get_process_status(handle)

    # -- Event parsing ------------------------------------------------------

    def _parse_event(
        self, line: str, handle: AgentHandle, *, stream: str = "stdout",
    ) -> AgentEvent | None:
        """Parse a stdout/stderr line into an ``AgentEvent``."""
        if self._parser:
            return self._parser.parse_line(line, handle)

        if stream == "stderr":
            return self._parse_stderr_line(line, handle)

        return self._parse_stdout_line_to_event(line, handle)

    def _parse_stdout_line_to_event(
        self, line: str, handle: AgentHandle,
    ) -> AgentEvent | None:
        """Convert a stdout line to an AgentEvent using JSON parsing."""
        parsed = self._parse_stdout_line(line)
        ev_type = parsed["type"]
        payload = parsed["payload"]
        token_usage = parsed.get("token_usage")
        cost_usd = parsed.get("cost_usd")
        seq = handle.seq
        handle.seq += 1
        return AgentEvent(
            seq=seq,
            timestamp=now_iso(),
            type=ev_type,
            task_id=None,
            payload=payload,
            token_usage=token_usage,
            cost_usd=cost_usd,
        )

    def _parse_stderr_line(
        self, line: str, handle: AgentHandle,
    ) -> AgentEvent:
        """Convert a stderr line to an AgentEvent."""
        line_clean = line.rstrip("\n")
        if line_clean:
            combined = (handle.stderr_tail + "\n" + line_clean).strip()
            handle.stderr_tail = combined[-4000:]
        seq = handle.seq
        handle.seq += 1
        return AgentEvent(
            seq=seq,
            timestamp=now_iso(),
            type="stderr",
            task_id=None,
            payload={"line": line_clean, "backend": self._backend_name},
        )

    def _parse_stdout_line(self, line: str) -> dict:
        """Parse a single stdout line into a dict with type/payload/etc.

        Override in subclasses for backend-specific protocols.
        This is the same logic as ``SubprocessAdapter._parse_stdout_line``.
        """
        backend = self._backend_name
        payload: dict[str, Any] = {"line": line, "backend": backend, "event_kind": "progress"}
        if "[TASK_DONE]" in line:
            payload["event_kind"] = "task_done"
            return {"type": "task_done", "payload": payload}
        if "[TASK_FAILED]" in line:
            payload["event_kind"] = "task_failed"
            return {"type": "task_failed", "payload": payload}
        if "[HEARTBEAT]" in line:
            payload["event_kind"] = "heartbeat"
            return {"type": "heartbeat", "payload": payload}

        if line.startswith("[DEBUG:"):
            bracket_end = line.find("]", 7)
            if bracket_end != -1:
                marker = line[7:bracket_end]
                detail = line[bracket_end + 1:].strip()
                payload["event_kind"] = "debug"
                payload["debug_marker"] = marker
                payload["debug_detail"] = detail
                return {"type": "debug", "payload": payload}

        # Optional JSON line protocol from worker wrappers
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict):
                    event = str(data.get("event", "log"))
                    norm = "log"
                    if event in {"task_done", "task_failed", "heartbeat", "progress"}:
                        norm = event
                    payload = {
                        "line": line,
                        "backend": backend,
                        "event_kind": event,
                        "message": data.get("message", ""),
                        "artifacts": data.get("artifacts", []),
                        "task_id": data.get("task_id"),
                    }
                    token_usage = data.get("token_usage")
                    cost_usd = data.get("cost_usd")
                    return {
                        "type": norm,
                        "payload": payload,
                        "token_usage": token_usage if isinstance(token_usage, dict) else None,
                        "cost_usd": float(cost_usd) if isinstance(cost_usd, (int, float)) else None,
                    }
            except json.JSONDecodeError:
                pass

        usage = self._extract_usage_from_line(line)
        if usage:
            return {"type": "log", "payload": payload, **usage}

        return {"type": "log", "payload": payload}

    @staticmethod
    def _extract_usage_from_line(line: str) -> dict | None:
        """Best-effort parser for ad-hoc usage lines."""
        tok_match = re.search(r"(?:tokens|total_tokens)\s*[:=]\s*(\d+)", line, re.IGNORECASE)
        cost_match = re.search(r"(?:cost|usd)\s*[:=]\s*([0-9]*\.?[0-9]+)", line, re.IGNORECASE)
        if not tok_match and not cost_match:
            return None
        token_usage = None
        cost_usd = None
        if tok_match:
            total = int(tok_match.group(1))
            token_usage = {"total": total}
        if cost_match:
            cost_usd = float(cost_match.group(1))
        return {"token_usage": token_usage, "cost_usd": cost_usd}


# ---------------------------------------------------------------------------
# SubprocessAdapter -- the original unified class, kept for backward compat
# ---------------------------------------------------------------------------


class SubprocessAdapter:
    """Base adapter using stdin/stdout process protocol.

    Implements both the ``AgentAdapter`` and ``ProcessBackend`` protocols.
    Existing subclasses (``ClaudeAdapter``, ``CodexAdapter``, etc.) extend
    this class directly and override ``_parse_stdout_line`` for
    backend-specific event parsing.
    """

    def __init__(self, backend: str) -> None:
        self._backend = backend

    # -- AgentAdapter interface (unchanged) ---------------------------------

    async def spawn(self, spec: AgentProcessSpec) -> AgentHandle:
        # Create the log file eagerly so it exists even if the agent
        # produces no output.  An empty file = "spawned but silent"
        # vs missing file = "never spawned".
        if spec.log_file:
            log_path = Path(spec.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch(exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            spec.binary,
            *spec.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=spec.cwd,
            env=spec.env if spec.env else None,
        )
        handle = AgentHandle(spec=spec, process=process)
        asyncio.create_task(
            self._pump_stream(
                process.stdout,
                handle.stdout_queue,
                log_file=spec.log_file,
                stream_name="stdout",
            )
        )
        asyncio.create_task(
            self._pump_stream(
                process.stderr,
                handle.stderr_queue,
                log_file=spec.log_file,
                stream_name="stderr",
            )
        )
        return handle

    async def send_message(self, handle: AgentHandle, msg: AgentMessage) -> None:
        if handle.process.stdin is None:
            return
        payload = msg.content.strip() + "\n"
        handle.process.stdin.write(payload.encode("utf-8"))
        await handle.process.stdin.drain()

    async def read_output(self, handle: AgentHandle, since_seq: int | None = None) -> list[AgentEvent]:
        _ = since_seq
        events: list[AgentEvent] = []
        while not handle.stdout_queue.empty():
            line = await handle.stdout_queue.get()
            line = line.rstrip("\n")
            handle.last_heartbeat_ts = now_iso()
            parsed = self._parse_stdout_line(line)
            ev_type = parsed["type"]
            payload = parsed["payload"]
            token_usage = parsed.get("token_usage")
            cost_usd = parsed.get("cost_usd")
            events.append(
                AgentEvent(
                    seq=handle.seq,
                    timestamp=now_iso(),
                    type=ev_type,
                    task_id=None,
                    payload=payload,
                    token_usage=token_usage,
                    cost_usd=cost_usd,
                )
            )
            handle.seq += 1
        while not handle.stderr_queue.empty():
            line = await handle.stderr_queue.get()
            line_clean = line.rstrip("\n")
            if line_clean:
                combined = (handle.stderr_tail + "\n" + line_clean).strip()
                handle.stderr_tail = combined[-4000:]
            events.append(
                AgentEvent(
                    seq=handle.seq,
                    timestamp=now_iso(),
                    type="stderr",
                    task_id=None,
                    payload={"line": line_clean, "backend": self._backend},
                )
            )
            handle.seq += 1
        return events

    async def terminate(self, handle: AgentHandle, reason: str) -> None:
        _ = reason
        if handle.process.returncode is not None:
            return
        handle.process.terminate()
        try:
            await asyncio.wait_for(handle.process.wait(), timeout=5)
        except TimeoutError:
            handle.process.kill()
            await handle.process.wait()

    async def get_status(self, handle: AgentHandle) -> AgentRuntimeStatus:
        return AgentRuntimeStatus(
            pid=handle.process.pid,
            state="running" if handle.process.returncode is None else "exited",
            last_heartbeat_ts=handle.last_heartbeat_ts,
            exit_code=handle.process.returncode,
        )

    # -- ProcessBackend interface (aliases + thin wrappers) -----------------

    async def spawn_process(self, spec: AgentProcessSpec) -> AgentHandle:
        """``ProcessBackend.spawn_process`` -- delegates to ``spawn``."""
        return await self.spawn(spec)

    async def send_stdin(self, handle: AgentHandle, data: str) -> None:
        """``ProcessBackend.send_stdin`` -- write raw data to stdin."""
        if handle.process.stdin is None:
            return
        handle.process.stdin.write(data.encode("utf-8"))
        await handle.process.stdin.drain()

    async def read_stdout_lines(self, handle: AgentHandle) -> list[str]:
        """``ProcessBackend.read_stdout_lines`` -- drain stdout queue."""
        lines: list[str] = []
        while not handle.stdout_queue.empty():
            line = await handle.stdout_queue.get()
            lines.append(line.rstrip("\n"))
        return lines

    async def read_stderr_lines(self, handle: AgentHandle) -> list[str]:
        """``ProcessBackend.read_stderr_lines`` -- drain stderr queue."""
        lines: list[str] = []
        while not handle.stderr_queue.empty():
            line = await handle.stderr_queue.get()
            lines.append(line.rstrip("\n"))
        return lines

    async def kill(self, handle: AgentHandle, reason: str) -> None:
        """``ProcessBackend.kill`` -- delegates to ``terminate``."""
        await self.terminate(handle, reason)

    async def get_process_status(self, handle: AgentHandle) -> AgentRuntimeStatus:
        """``ProcessBackend.get_process_status`` -- delegates to ``get_status``."""
        return await self.get_status(handle)

    # -- Parsing (overridden by backend subclasses) -------------------------

    def _parse_stdout_line(self, line: str) -> dict:
        payload = {"line": line, "backend": self._backend, "event_kind": "progress"}
        if "[TASK_DONE]" in line:
            payload["event_kind"] = "task_done"
            return {"type": "task_done", "payload": payload}
        if "[TASK_FAILED]" in line:
            payload["event_kind"] = "task_failed"
            return {"type": "task_failed", "payload": payload}
        if "[HEARTBEAT]" in line:
            payload["event_kind"] = "heartbeat"
            return {"type": "heartbeat", "payload": payload}

        if line.startswith("[DEBUG:"):
            bracket_end = line.find("]", 7)
            if bracket_end != -1:
                marker = line[7:bracket_end]
                detail = line[bracket_end + 1:].strip()
                payload["event_kind"] = "debug"
                payload["debug_marker"] = marker
                payload["debug_detail"] = detail
                return {"type": "debug", "payload": payload}

        # Optional JSON line protocol from worker wrappers:
        # {"event":"task_done","message":"...","token_usage":{"total":123},"cost_usd":0.01}
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict):
                    event = str(data.get("event", "log"))
                    norm = "log"
                    if event in {"task_done", "task_failed", "heartbeat", "progress"}:
                        norm = event
                    payload = {
                        "line": line,
                        "backend": self._backend,
                        "event_kind": event,
                        "message": data.get("message", ""),
                        "artifacts": data.get("artifacts", []),
                        "task_id": data.get("task_id"),
                    }
                    token_usage = data.get("token_usage")
                    cost_usd = data.get("cost_usd")
                    return {
                        "type": norm,
                        "payload": payload,
                        "token_usage": token_usage if isinstance(token_usage, dict) else None,
                        "cost_usd": float(cost_usd) if isinstance(cost_usd, (int, float)) else None,
                    }
            except json.JSONDecodeError:
                pass

        usage = self._extract_usage_from_line(line)
        if usage:
            return {"type": "log", "payload": payload, **usage}

        return {"type": "log", "payload": payload}

    def _extract_usage_from_line(self, line: str) -> dict | None:
        # Best-effort parser for ad-hoc usage lines.
        # Examples: "tokens=1234 cost=0.12", "total_tokens: 500"
        tok_match = re.search(r"(?:tokens|total_tokens)\s*[:=]\s*(\d+)", line, re.IGNORECASE)
        cost_match = re.search(r"(?:cost|usd)\s*[:=]\s*([0-9]*\.?[0-9]+)", line, re.IGNORECASE)
        if not tok_match and not cost_match:
            return None
        token_usage = None
        cost_usd = None
        if tok_match:
            total = int(tok_match.group(1))
            token_usage = {"total": total}
        if cost_match:
            cost_usd = float(cost_match.group(1))
        return {"token_usage": token_usage, "cost_usd": cost_usd}

    # -- Internal -----------------------------------------------------------

    async def _pump_stream(
        self,
        stream: asyncio.StreamReader | None,
        queue: asyncio.Queue[str],
        *,
        log_file: str | None = None,
        stream_name: str = "stdout",
    ) -> None:
        await _pump_stream(stream, queue, log_file=log_file, stream_name=stream_name)
