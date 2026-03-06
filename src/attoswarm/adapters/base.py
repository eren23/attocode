"""Agent adapter interfaces and subprocess implementation."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


class AgentAdapter(Protocol):
    async def spawn(self, spec: AgentProcessSpec) -> AgentHandle: ...

    async def send_message(self, handle: AgentHandle, msg: AgentMessage) -> None: ...

    async def read_output(self, handle: AgentHandle, since_seq: int | None = None) -> list[AgentEvent]: ...

    async def terminate(self, handle: AgentHandle, reason: str) -> None: ...

    async def get_status(self, handle: AgentHandle) -> AgentRuntimeStatus: ...


class SubprocessAdapter:
    """Base adapter using stdin/stdout process protocol."""

    def __init__(self, backend: str) -> None:
        self._backend = backend

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

    async def _pump_stream(
        self,
        stream: asyncio.StreamReader | None,
        queue: asyncio.Queue[str],
        *,
        log_file: str | None = None,
        stream_name: str = "stdout",
    ) -> None:
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
