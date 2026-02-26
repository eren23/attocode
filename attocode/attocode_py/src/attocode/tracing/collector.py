"""Trace collector -- full lifecycle tracking with buffered JSONL output.

Replaces and extends the original single-file ``tracing.py``.  Provides both
the fine-grained ``record()`` API and convenience methods for common event
patterns (LLM calls, tool execution, budget, compaction, subagents).

Usage::

    collector = TraceCollector(output_dir=".attocode/traces", session_id="abc")
    collector.start_session(goal="Build REST API", model="claude-sonnet-4-20250514")

    collector.record_llm_request(iteration=1, messages_count=5, model="claude-sonnet-4-20250514")
    collector.record_llm_response(iteration=1, tokens=1200, cost=0.003, duration_ms=850)
    collector.record_tool_call(iteration=1, tool_name="bash", args={"command": "ls"},
                               result="file.py", duration_ms=120)

    summary = collector.get_summary()
    collector.end_session(status="complete", summary=summary)
"""

from __future__ import annotations

import atexit
import json
import logging
import time
from pathlib import Path
from typing import IO, Any

from attocode.tracing.types import (
    TraceEvent,
    TraceEventKind,
    TraceSession,
    TraceSummary,
    create_trace_event,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe serialisation helpers (carried over from the original tracing.py)
# ---------------------------------------------------------------------------


def _safe_serialize(obj: Any, max_str_len: int = 500) -> Any:
    """Recursively prepare *obj* for JSON, truncating long strings.

    This is intentionally lenient -- tracing must never crash the agent.
    """
    if isinstance(obj, str):
        return obj[:max_str_len] if len(obj) > max_str_len else obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v, max_str_len) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v, max_str_len) for v in obj]
    if isinstance(obj, (int, float, bool, type(None))):
        return obj
    # Fallback: stringify anything exotic.
    return str(obj)[:max_str_len]


# ---------------------------------------------------------------------------
# TraceCollector
# ---------------------------------------------------------------------------


class TraceCollector:
    """Buffered JSONL trace collector with crash-safe flushing.

    Parameters:
        output_dir: Directory where ``{session_id}.jsonl`` files are written.
        session_id: Unique identifier for this trace session.  If empty a
            timestamp-based ID is generated.
        buffer_size: Number of events buffered in memory before auto-flush.
        flush_on_crash: When ``True``, registers an ``atexit`` handler that
            flushes remaining events on interpreter shutdown.
    """

    def __init__(
        self,
        output_dir: str | Path = ".attocode/traces",
        session_id: str = "",
        *,
        buffer_size: int = 100,
        flush_on_crash: bool = True,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._session_id = session_id or f"trace-{int(time.time())}"
        self._buffer_size = max(1, buffer_size)
        self._flush_on_crash = flush_on_crash

        # Session state
        self._session: TraceSession | None = None
        self._file: IO[str] | None = None
        self._buffer: list[TraceEvent] = []
        self._event_count: int = 0
        self._start_time: float = 0.0
        self._active: bool = False

        # Statistics accumulators (updated on record, not on flush)
        self._total_tokens: int = 0
        self._total_cost: float = 0.0
        self._iteration_count: int = 0
        self._tool_count: int = 0
        self._llm_count: int = 0
        self._error_count: int = 0
        self._compaction_count: int = 0

        # Atexit guard
        self._atexit_registered: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        """The session ID for this collector."""
        return self._session_id

    @property
    def event_count(self) -> int:
        """Total number of events recorded (flushed + buffered)."""
        return self._event_count

    @property
    def is_active(self) -> bool:
        """Whether a tracing session is currently in progress."""
        return self._active

    @property
    def output_path(self) -> Path:
        """Path to the JSONL trace file."""
        return self._output_dir / f"{self._session_id}.jsonl"

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(
        self,
        goal: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Begin a new tracing session.

        Creates the output directory, opens the JSONL file for appending,
        and writes the initial ``session_start`` event.

        Args:
            goal: The user goal or prompt being traced.
            model: The LLM model identifier.
            metadata: Arbitrary session-level metadata.

        Returns:
            The path to the trace file.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_path
        self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115
        self._start_time = time.time()
        self._active = True

        self._session = TraceSession(
            session_id=self._session_id,
            goal=goal,
            model=model,
            start_time=self._start_time,
            metadata=metadata or {},
        )

        # Register atexit handler once.
        if self._flush_on_crash and not self._atexit_registered:
            atexit.register(self._atexit_flush)
            self._atexit_registered = True

        # Record the opening event.
        self.record(
            TraceEventKind.SESSION_START,
            goal=goal,
            model=model,
            **(metadata or {}),
        )

        return path

    def end_session(
        self,
        status: str = "complete",
        summary: TraceSummary | None = None,
    ) -> None:
        """End the current tracing session.

        Writes a ``session_end`` event, flushes the buffer, and closes the
        file handle.

        Args:
            status: Terminal status of the session (e.g. "complete", "error",
                "budget_exhausted").
            summary: Optional pre-computed summary; if ``None`` one is
                generated automatically.
        """
        if not self._active:
            return

        if summary is None:
            summary = self.get_summary()

        end_time = time.time()
        self.record(
            TraceEventKind.SESSION_END,
            status=status,
            duration_seconds=round(end_time - self._start_time, 3),
            summary=summary.to_dict(),
        )

        if self._session is not None:
            self._session.end_time = end_time

        self.flush()
        self._close_file()
        self._active = False

    # ------------------------------------------------------------------
    # Generic recording
    # ------------------------------------------------------------------

    def record(self, kind: TraceEventKind, **data: Any) -> TraceEvent:
        """Record an arbitrary trace event.

        The event is buffered and periodically flushed to disk.  Callers
        may also pass ``iteration``, ``parent_event_id``, ``duration_ms``,
        and ``event_id`` as keyword arguments -- they are extracted and
        placed on the :class:`TraceEvent` directly rather than into *data*.

        Args:
            kind: The trace event kind.
            **data: Arbitrary payload merged into ``TraceEvent.data``.

        Returns:
            The created :class:`TraceEvent`.
        """
        # Extract TraceEvent-level keys from the data dict.
        iteration = data.pop("iteration", None)
        parent_event_id = data.pop("parent_event_id", None)
        duration_ms = data.pop("duration_ms", None)
        event_id = data.pop("event_id", None)

        event = create_trace_event(
            kind,
            session_id=self._session_id,
            iteration=iteration,
            data=_safe_serialize(data) if data else {},
            parent_event_id=parent_event_id,
            duration_ms=duration_ms,
            event_id=event_id,
        )

        self._buffer.append(event)
        self._event_count += 1

        if self._session is not None:
            self._session.events.append(event)

        self._auto_flush()
        return event

    # ------------------------------------------------------------------
    # Specialised recording helpers
    # ------------------------------------------------------------------

    def _increment_counters(
        self,
        kind: str,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Update summary counters for a given event kind.

        Internal API surface for callers (e.g. :class:`TraceWriter`) that
        route events through the generic ``record()`` path and still need
        accurate ``get_summary()`` results.

        Args:
            kind: Event kind string (e.g. "llm", "tool", "error",
                "iteration", "compaction").
            tokens: Token count to accumulate (LLM events only).
            cost: Monetary cost to accumulate (LLM events only).
        """
        if kind == "llm":
            self._llm_count += 1
            self._total_tokens += tokens
            self._total_cost += cost
        elif kind == "iteration":
            self._iteration_count += 1
        elif kind == "tool":
            self._tool_count += 1
        elif kind == "tool_error":
            self._tool_count += 1
            self._error_count += 1
        elif kind == "error":
            self._error_count += 1
        elif kind == "compaction":
            self._compaction_count += 1

    def record_llm_request(
        self,
        iteration: int,
        messages_count: int,
        model: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record an outbound LLM API request.

        Args:
            iteration: Current agent iteration number.
            messages_count: Number of messages in the request payload.
            model: Model identifier.
            extra: Optional additional data.
        """
        self._llm_count += 1
        payload: dict[str, Any] = {
            "iteration": iteration,
            "messages_count": messages_count,
            "model": model,
        }
        if extra:
            payload.update(extra)
        return self.record(TraceEventKind.LLM_REQUEST, **payload)

    def record_llm_response(
        self,
        iteration: int,
        tokens: int,
        cost: float,
        duration_ms: float,
        *,
        model: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record an LLM API response.

        Args:
            iteration: Current agent iteration number.
            tokens: Total tokens consumed.
            cost: Monetary cost of the call.
            duration_ms: Wall-clock time of the call in milliseconds.
            model: Model identifier (optional echo-back).
            input_tokens: Breakdown -- input tokens.
            output_tokens: Breakdown -- output tokens.
            cache_read_tokens: Tokens served from KV cache.
            cache_write_tokens: Tokens written to KV cache.
            extra: Optional additional data.
        """
        self._total_tokens += tokens
        self._total_cost += cost
        payload: dict[str, Any] = {
            "iteration": iteration,
            "tokens": tokens,
            "cost": cost,
            "duration_ms": duration_ms,
        }
        if model:
            payload["model"] = model
        if input_tokens is not None:
            payload["input_tokens"] = input_tokens
        if output_tokens is not None:
            payload["output_tokens"] = output_tokens
        if cache_read_tokens is not None:
            payload["cache_read_tokens"] = cache_read_tokens
        if cache_write_tokens is not None:
            payload["cache_write_tokens"] = cache_write_tokens
        if extra:
            payload.update(extra)
        return self.record(TraceEventKind.LLM_RESPONSE, **payload)

    def record_tool_call(
        self,
        iteration: int,
        tool_name: str,
        args: dict[str, Any] | None,
        result: str | None,
        duration_ms: float,
        error: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record a tool invocation (start + result in one event).

        If *error* is supplied the event kind is ``tool_error``; otherwise
        ``tool_end``.

        Args:
            iteration: Current agent iteration.
            tool_name: Name of the invoked tool.
            args: Tool input arguments.
            result: Tool output (truncated in serialisation).
            duration_ms: Execution time in milliseconds.
            error: Error message if the tool failed.
            extra: Optional additional data.
        """
        self._tool_count += 1
        kind = TraceEventKind.TOOL_ERROR if error else TraceEventKind.TOOL_END
        if error:
            self._error_count += 1

        payload: dict[str, Any] = {
            "iteration": iteration,
            "tool": tool_name,
            "duration_ms": duration_ms,
        }
        if args is not None:
            payload["args"] = args
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        if extra:
            payload.update(extra)
        return self.record(kind, **payload)

    def record_budget_check(
        self,
        status: str,
        usage_fraction: float,
        message: str = "",
        *,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record a budget check result.

        Args:
            status: Budget status string (e.g. "ok", "warning", "exhausted").
            usage_fraction: Fraction of budget consumed, 0.0 -- 1.0.
            message: Human-readable description.
            extra: Optional additional data.
        """
        kind_map: dict[str, TraceEventKind] = {
            "warning": TraceEventKind.BUDGET_WARNING,
            "exhausted": TraceEventKind.BUDGET_EXHAUSTED,
        }
        kind = kind_map.get(status, TraceEventKind.BUDGET_CHECK)
        payload: dict[str, Any] = {
            "status": status,
            "usage_fraction": round(usage_fraction, 4),
        }
        if message:
            payload["message"] = message
        if extra:
            payload.update(extra)
        return self.record(kind, **payload)

    def record_compaction(
        self,
        messages_before: int,
        messages_after: int,
        tokens_saved: int,
        *,
        duration_ms: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record a context compaction event.

        Args:
            messages_before: Message count before compaction.
            messages_after: Message count after compaction.
            tokens_saved: Estimated token reduction.
            duration_ms: Time taken for compaction.
            extra: Optional additional data.
        """
        self._compaction_count += 1
        payload: dict[str, Any] = {
            "messages_before": messages_before,
            "messages_after": messages_after,
            "tokens_saved": tokens_saved,
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if extra:
            payload.update(extra)
        return self.record(TraceEventKind.COMPACTION_END, **payload)

    def record_subagent(
        self,
        agent_id: str,
        event_type: str,
        **data: Any,
    ) -> TraceEvent:
        """Record a subagent lifecycle event.

        Args:
            agent_id: Unique identifier of the subagent.
            event_type: One of "spawn", "complete", "error", "timeout".
            **data: Additional payload data.
        """
        kind_map: dict[str, TraceEventKind] = {
            "spawn": TraceEventKind.SUBAGENT_SPAWN,
            "complete": TraceEventKind.SUBAGENT_COMPLETE,
            "error": TraceEventKind.SUBAGENT_ERROR,
            "timeout": TraceEventKind.SUBAGENT_TIMEOUT,
        }
        kind = kind_map.get(event_type, TraceEventKind.SUBAGENT_SPAWN)
        payload: dict[str, Any] = {"agent_id": agent_id, "event_type": event_type}
        payload.update(data)
        return self.record(kind, **payload)

    def record_error(
        self,
        error: str | Exception,
        context: str = "",
        *,
        iteration: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record an error event.

        Args:
            error: Error message or exception.
            context: Human-readable description of what was happening.
            iteration: Current iteration, if applicable.
            extra: Optional additional data.
        """
        self._error_count += 1
        error_str = str(error)
        error_type = type(error).__name__ if isinstance(error, Exception) else "str"
        payload: dict[str, Any] = {
            "error": error_str,
            "error_type": error_type,
        }
        if context:
            payload["context"] = context
        if iteration is not None:
            payload["iteration"] = iteration
        if extra:
            payload.update(extra)
        return self.record(TraceEventKind.ERROR, **payload)

    def record_iteration_start(
        self,
        iteration: int,
        *,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record the start of an agent iteration.

        Args:
            iteration: Iteration number.
            extra: Optional additional data.
        """
        self._iteration_count += 1
        payload: dict[str, Any] = {"iteration": iteration}
        if extra:
            payload.update(extra)
        return self.record(TraceEventKind.ITERATION_START, **payload)

    def record_iteration_end(
        self,
        iteration: int,
        duration_ms: float,
        *,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record the end of an agent iteration.

        Args:
            iteration: Iteration number.
            duration_ms: Iteration wall-clock time in milliseconds.
            extra: Optional additional data.
        """
        payload: dict[str, Any] = {
            "iteration": iteration,
            "duration_ms": duration_ms,
        }
        if extra:
            payload.update(extra)
        return self.record(TraceEventKind.ITERATION_END, **payload)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> TraceSummary:
        """Compute aggregate statistics from accumulated counters.

        This is O(1) -- counters are updated incrementally during recording.

        Returns:
            A :class:`TraceSummary` snapshot.
        """
        duration = time.time() - self._start_time if self._start_time else 0.0
        return TraceSummary(
            session_id=self._session_id,
            total_events=self._event_count,
            total_tokens=self._total_tokens,
            total_cost=round(self._total_cost, 6),
            duration_seconds=round(duration, 3),
            iterations=self._iteration_count,
            tool_calls=self._tool_count,
            llm_calls=self._llm_count,
            errors=self._error_count,
            compactions=self._compaction_count,
        )

    # ------------------------------------------------------------------
    # Flushing
    # ------------------------------------------------------------------

    def flush(self) -> int:
        """Write all buffered events to disk.

        Returns:
            The number of events flushed.
        """
        if not self._buffer:
            return 0

        flushed = 0
        for event in self._buffer:
            self._write_event(event)
            flushed += 1

        self._buffer.clear()
        return flushed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_event(self, event: TraceEvent) -> None:
        """Serialise and write a single event as one JSONL line."""
        if self._file is None:
            return
        try:
            line = json.dumps(event.to_dict(), default=str)
            self._file.write(line + "\n")
            self._file.flush()
        except Exception:
            # Tracing must never crash the agent.
            logger.debug("Failed to write trace event", exc_info=True)

    def _auto_flush(self) -> None:
        """Flush the buffer when it reaches the configured capacity."""
        if len(self._buffer) >= self._buffer_size:
            self.flush()

    def _close_file(self) -> None:
        """Close the underlying file handle."""
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                logger.debug("Failed to close trace file", exc_info=True)
            finally:
                self._file = None

    def _atexit_flush(self) -> None:
        """Atexit handler: best-effort flush of remaining events."""
        try:
            if self._active:
                self.flush()
                self._close_file()
                self._active = False
        except Exception:
            pass  # Swallow -- interpreter is shutting down.

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> TraceCollector:
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._active:
            status = "error" if _exc[0] is not None else "complete"
            self.end_session(status=status)


# ---------------------------------------------------------------------------
# TraceWriter compatibility shim
# ---------------------------------------------------------------------------


class TraceWriter:
    """Backward-compatible wrapper around :class:`TraceCollector`.

    Provides the same public API as the original ``tracing.py`` module so
    that existing callers (e.g. ``cli.py``) continue to work without changes.

    Usage::

        writer = TraceWriter(session_id="abc123")
        path = writer.start()
        agent.on_event(writer.record)
        writer.close()
    """

    def __init__(
        self,
        session_id: str = "",
        trace_dir: str | Path | None = None,
    ) -> None:
        output_dir = Path(trace_dir) if trace_dir else Path(".attocode") / "traces"
        self._collector = TraceCollector(
            output_dir=output_dir,
            session_id=session_id,
            buffer_size=1,  # Immediate flush for backward compat.
            flush_on_crash=True,
        )

    def start(self) -> Path:
        """Open the trace file for writing. Returns the file path."""
        return self._collector.start_session()

    def record(self, event: Any) -> None:
        """Record an :class:`AgentEvent` (the old event handler callback).

        Translates the legacy ``AgentEvent`` into a ``TraceEvent`` and
        records it via the underlying collector.
        """
        if not self._collector.is_active:
            return

        from attocode.tracing.types import event_type_to_trace_kind

        kind = event_type_to_trace_kind(str(event.type))
        data: dict[str, Any] = {}

        if event.tool:
            data["tool"] = event.tool
        if event.args:
            data["args"] = _safe_serialize(event.args)
        if event.result:
            data["result"] = event.result[:500]
        if event.error:
            data["error"] = event.error
        if event.tokens is not None:
            data["tokens"] = event.tokens
        if event.cost is not None:
            data["cost"] = event.cost
        if event.metadata:
            data["metadata"] = _safe_serialize(event.metadata)
        if event.iteration is not None:
            data["iteration"] = event.iteration

        # Increment summary counters via the internal API so that events
        # routed through the generic record() path (via TraceWriter.record
        # callback) produce accurate get_summary() results.
        evt_str = str(event.type)
        if evt_str in ("llm.complete", "llm.stream.end"):
            self._collector._increment_counters(
                "llm",
                tokens=event.tokens or 0,
                cost=event.cost or 0.0,
            )
        elif evt_str == "iteration":
            self._collector._increment_counters("iteration")
        elif evt_str in ("tool.complete", "tool.error"):
            kind = "tool_error" if evt_str == "tool.error" else "tool"
            self._collector._increment_counters(kind)
        elif evt_str in ("llm.error", "error"):
            self._collector._increment_counters("error")
        elif evt_str == "compaction.complete":
            self._collector._increment_counters("compaction")

        self._collector.record(kind, **data)

    def close(self) -> None:
        """Close the trace file."""
        if self._collector.is_active:
            self._collector.end_session(status="complete")

    @property
    def session_id(self) -> str:
        return self._collector.session_id

    @property
    def event_count(self) -> int:
        return self._collector.event_count

    @property
    def is_active(self) -> bool:
        return self._collector.is_active


# ---------------------------------------------------------------------------
# Module-level loader
# ---------------------------------------------------------------------------


def load_trace_session(path: str | Path) -> TraceSession:
    """Load a trace session from a JSONL file.

    Reads every line, parses the JSON, and reconstructs :class:`TraceEvent`
    objects.  The session metadata (goal, model, times) is inferred from the
    ``session_start`` and ``session_end`` events.

    Args:
        path: Path to the ``.jsonl`` trace file.

    Returns:
        A populated :class:`TraceSession`.
    """
    path = Path(path)
    events: list[TraceEvent] = []
    session_id = path.stem
    goal = ""
    model = ""
    start_time = 0.0
    end_time: float | None = None
    metadata: dict[str, Any] = {}

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Older format from the original TraceWriter doesn't have "kind".
            if "kind" in raw:
                event = TraceEvent.from_dict(raw)
                events.append(event)

                if event.kind == TraceEventKind.SESSION_START:
                    goal = event.data.get("goal", "")
                    model = event.data.get("model", "")
                    start_time = event.timestamp
                    metadata = {
                        k: v
                        for k, v in event.data.items()
                        if k not in ("goal", "model")
                    }
                elif event.kind == TraceEventKind.SESSION_END:
                    end_time = event.timestamp
            else:
                # Legacy format: interpret as best we can.
                evt_type = raw.get("type", "custom")
                ts = raw.get("timestamp", 0.0)
                if evt_type == "trace.start":
                    session_id = raw.get("session_id", session_id)
                    start_time = ts
                elif evt_type == "trace.end":
                    end_time = ts
                else:
                    from attocode.tracing.types import event_type_to_trace_kind

                    kind = event_type_to_trace_kind(evt_type)
                    evt = TraceEvent(
                        kind=kind,
                        timestamp=ts,
                        session_id=session_id,
                        data={
                            k: v
                            for k, v in raw.items()
                            if k not in ("type", "timestamp", "elapsed_ms")
                        },
                    )
                    events.append(evt)

    return TraceSession(
        session_id=session_id,
        goal=goal,
        model=model,
        start_time=start_time,
        end_time=end_time,
        events=events,
        metadata=metadata,
    )
