"""Private client stream capture and observations; receipt times are not server timings."""
from __future__ import annotations

import json
import math
import os
import re
import selectors
import signal
import subprocess
import time

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens

QUOTA = re.compile(r"(?:usage|rate) limit (?:reached|exceeded)|out of (?:usage|credits)|quota exceeded", re.I)
READ_TOOLS = {"Read", "Grep", "Glob", "readToolCall", "grepToolCall", "globToolCall", "read_file", "search"}


def private_file(path, mode="w"):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, mode)


def capture(argv, root, directory, timeout, env, *, kill_grace=10):
    """Drain both pipes without blocking on lines, including partial UTF-8 and descendants."""
    directory.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    process = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, bufsize=0)
    pending = b""
    stderr_tail = ""
    exhausted = timed_out = killed = False
    termination = None

    def stop(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    def event(line, now, stream):
        try:
            value = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(value, dict):
            stream.write(json.dumps({"received_seconds": now - start, "event": value}) + "\n")
            stream.flush()

    try:
        with selectors.DefaultSelector() as selector, private_file(directory / "trace.jsonl", "wb") as stdout, \
                private_file(directory / "stderr.log", "wb") as stderr, private_file(directory / "events.jsonl") as events:
            for pipe, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if termination is None and now - start >= timeout:
                    timed_out = True
                    termination = now
                    stop(signal.SIGTERM)
                if termination is not None and now - termination >= kill_grace and not killed:
                    stop(signal.SIGKILL)
                    killed = True
                if killed and now - termination >= kill_grace + 1:
                    break
                for key, _ in selector.select(timeout=.05):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    received = time.monotonic()
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stderr":
                        stderr.write(chunk)
                        stderr_tail = (stderr_tail + chunk.decode("utf-8", errors="replace"))[-6000:]
                        exhausted |= bool(QUOTA.search(stderr_tail))
                    else:
                        stdout.write(chunk)
                        stdout.flush()
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            event(line, received, events)
                if exhausted and termination is None:
                    termination = time.monotonic()
                    stop(signal.SIGTERM)
            if pending:
                event(pending, time.monotonic(), events)
        process.wait(timeout=1)
    finally:
        # Clean up MCP descendants even when a client exits without closing them.
        stop(signal.SIGKILL)
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    return {"seconds": time.monotonic() - start, "exit_code": process.returncode,
            "timed_out": timed_out, "quota_exhausted": exhausted, "stderr_tail": stderr_tail[-1500:]}


def parse_events(client, stdout, answer_path=None):
    """Accept raw CLI JSONL or timestamped capture records, deduplicating by call ID."""
    calls, outputs, models, usage, answer, denials = {}, {}, set(), {}, {}, []
    first_event = None
    terminal_error = False
    records = []
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        wrapped = isinstance(row.get("event"), dict) and "received_seconds" in row
        event, received = (row["event"], row["received_seconds"]) if wrapped else (row, None)
        if not isinstance(received, (int, float)) or not math.isfinite(received) or received < 0:
            received = None
        records.append((event, received))

    def call(identity, name, arguments, index, received, started):
        key = identity or f"unidentified-{index}-{name}"
        row = calls.setdefault(key, {"id": identity, "name": name, "arguments": arguments,
                                     "event_index": index, "started_seconds": None, "completed_seconds": None})
        row.update(name=name, arguments=arguments)
        if started and row["started_seconds"] is None:
            row["started_seconds"] = received
        if not started and row["completed_seconds"] is None:
            row["completed_seconds"] = received
        return key

    def output(identity, content, index, received, error=False):
        key = identity or f"unidentified-output-{index}"
        outputs.setdefault(key, {"id": identity, "content": content, "event_index": index,
                                 "received_seconds": received, "is_error": bool(error)})
        if identity in calls and calls[identity]["completed_seconds"] is None:
            calls[identity]["completed_seconds"] = received

    for index, (event, received) in enumerate(records):
        if first_event is None:
            first_event = received
        message = event.get("message") or {}
        if isinstance(message, dict):
            if message.get("model"):
                models.add(message["model"])
            for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    call(block.get("id"), block["name"], block.get("input", {}), index, received, True)
                elif block.get("type") == "tool_result":
                    output(block.get("tool_use_id"), block.get("content"), index, received, block.get("is_error"))
        if event.get("type") == "result":
            answer = event.get("structured_output") or answer
            usage = event.get("usage") or usage
            models.update((event.get("modelUsage") or {}).keys())
            denials.extend(event.get("permission_denials", []))
            terminal_error |= bool(event.get("is_error"))
            if not answer and isinstance(event.get("result"), str):
                try:
                    answer = json.loads(event["result"].strip().removeprefix("```json").removesuffix("```").strip())
                except ValueError:
                    pass
        item = event.get("item") or {}
        if event.get("type") in {"item.started", "item.completed"}:
            started = event["type"] == "item.started"
            if item.get("type") == "mcp_tool_call":
                name = "mcp__" + item.get("server", "") + "__" + item.get("tool", "")
                call(item.get("id"), name, item.get("arguments", {}), index, received, started)
                if not started:
                    output(item.get("id"), item.get("result"), index, received, item.get("error"))
            elif item.get("type") == "command_execution":
                call(item.get("id"), "shell", {"command": item.get("command")}, index, received, started)
                if not started:
                    output(item.get("id"), item.get("aggregated_output"), index, received, bool(item.get("exit_code")))
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
        if event.get("type") == "turn.failed":
            terminal_error = True
        if event.get("type") == "tool_call" and event.get("subtype") in {"started", "completed"}:
            started = event["subtype"] == "started"
            for kind, value in (event.get("tool_call") or {}).items():
                if not isinstance(value, dict):
                    continue
                call(event.get("call_id"), value.get("name", kind), value.get("arguments", value.get("args", {})),
                     index, received, started)
                if not started and "result" in value:
                    output(event.get("call_id"), value["result"], index, received,
                           isinstance(value["result"], dict) and bool(value["result"].get("error")))
        if event.get("model"):
            models.add(event["model"])
    if answer_path and answer_path.exists():
        try:
            answer = json.loads(answer_path.read_text())
        except ValueError:
            pass
    for row in calls.values():
        a, b = row["started_seconds"], row["completed_seconds"]
        row["observed_seconds"] = b - a if a is not None and b is not None and b >= a else None
    present = [row for row in outputs.values() if row["content"] is not None]
    complete = bool(calls) and all(row["id"] and row["id"] in outputs and outputs[row["id"]]["content"] is not None
                                   for row in calls.values())
    return {"output": answer if isinstance(answer, dict) else {}, "tool_calls": list(calls.values()),
            "tool_results": list(outputs.values()), "resolved_models": sorted(models), "usage": usage,
            "permission_denials": denials, "terminal_error": terminal_error,
            "first_event_seconds": first_event, "event_count": len(records),
            "tool_result_tokens": sum(count_tokens(json.dumps(row["content"])) for row in present) if complete else None,
            "observed_tool_result_tokens": sum(count_tokens(json.dumps(row["content"])) for row in present) if present else None,
            "mcp_used": any(c["name"].startswith("mcp__") for c in calls.values())}


def observations(parsed):
    calls, outputs = parsed["tool_calls"], {r["id"]: r for r in parsed["tool_results"] if r["id"]}
    mcp = [r for r in calls if r["name"].startswith("mcp__")]
    intel = [r for r in mcp if r["name"].startswith(("mcp__intelligence__", "mcp__attocode-code-intel__"))]
    completed = [outputs[r["id"]]["event_index"] for r in mcp if r["id"] in outputs]
    first_result = min(completed) if completed else None
    reads = [r for r in calls if r["name"] in READ_TOOLS]
    shells = [r for r in calls if r["name"] in {"shell", "Bash", "shellToolCall"}]
    observed = [outputs[r["id"]] for r in mcp if r["id"] in outputs and outputs[r["id"]]["content"] is not None]
    return {"intelligence_calls": len(intel), "inspect_symbol_calls": sum(r["name"].endswith("__inspect_symbol") for r in intel),
            "mcp_calls": len(mcp), "discovery_calls": sum(r["name"] == "ToolSearch" for r in calls),
            "native_read_search_calls": len(reads), "native_shell_calls": len(shells),
            "follow_up_read_search_calls": sum(r["event_index"] > first_result for r in reads) if first_result is not None else None,
            "follow_up_shell_calls": sum(r["event_index"] > first_result for r in shells) if first_result is not None else None,
            "mcp_result_tokens": sum(count_tokens(json.dumps(r["content"])) for r in observed) if mcp and len(observed) == len(mcp) else None,
            "mcp_results_observed": len(observed), "first_event_seconds": parsed["first_event_seconds"],
            "tool_intervals_observed": sum(r["observed_seconds"] is not None for r in calls),
            "tool_intervals_missing": sum(r["observed_seconds"] is None for r in calls),
            "follow_up_interpretation": "Follow-up calls are not necessarily redundant; verify requested evidence in the trace."}
