"""Distributed tracing context for swarm orchestration.

Provides span-based tracing using ``contextvars`` for async propagation.
Each span captures an operation with timing, parent chain, and attributes.

Usage::

    async with start_span("decompose_goal") as span:
        span.set_attribute("task_count", 5)
        ...  # traced code

    @traced("handle_result")
    async def _handle_result(self, result):
        ...
"""

from __future__ import annotations

import contextvars
import functools
import logging
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

logger = logging.getLogger(__name__)

# Context variable for async span propagation
_current_span: contextvars.ContextVar[SpanContext | None] = contextvars.ContextVar(
    "_current_span", default=None,
)

# Global list of completed span listeners
_span_listeners: list[Callable[[SpanContext], Any]] = []


def _new_span_id() -> str:
    """Generate a 12-character span ID."""
    return uuid.uuid4().hex[:12]


@dataclass
class SpanContext:
    """A single trace span capturing an operation with timing."""

    trace_id: str
    span_id: str = field(default_factory=_new_span_id)
    parent_span_id: str = ""
    operation: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        if self.end_time > 0:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def finish(self) -> None:
        if self.end_time == 0.0:
            self.end_time = time.time()
            for listener in _span_listeners:
                try:
                    listener(self)
                except Exception as exc:
                    logger.debug("Span listener error: %s", exc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": self.duration_s,
            "attributes": self.attributes,
        }


def current_span() -> SpanContext | None:
    """Return the active span in the current async context, or None."""
    return _current_span.get()


def on_span_complete(listener: Callable[[SpanContext], Any]) -> None:
    """Register a callback invoked when any span finishes."""
    _span_listeners.append(listener)


def remove_span_listener(listener: Callable[[SpanContext], Any]) -> None:
    """Remove a previously registered span listener."""
    _span_listeners[:] = [l for l in _span_listeners if l is not listener]


@contextmanager
def start_span_sync(
    operation: str,
    trace_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[SpanContext]:
    """Synchronous context manager for creating a child span."""
    parent = _current_span.get()
    span = SpanContext(
        trace_id=trace_id or (parent.trace_id if parent else ""),
        parent_span_id=parent.span_id if parent else "",
        operation=operation,
        attributes=dict(attributes) if attributes else {},
    )
    token = _current_span.set(span)
    try:
        yield span
    finally:
        span.finish()
        _current_span.reset(token)


@asynccontextmanager
async def start_span(
    operation: str,
    trace_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[SpanContext]:
    """Async context manager for creating a child span.

    Automatically inherits ``trace_id`` and ``parent_span_id`` from the
    current context if available.
    """
    parent = _current_span.get()
    span = SpanContext(
        trace_id=trace_id or (parent.trace_id if parent else ""),
        parent_span_id=parent.span_id if parent else "",
        operation=operation,
        attributes=dict(attributes) if attributes else {},
    )
    token = _current_span.set(span)
    try:
        yield span
    finally:
        span.finish()
        _current_span.reset(token)


def traced(operation: str) -> Callable[..., Any]:
    """Decorator that wraps an async function in a trace span.

    Usage::

        @traced("handle_result")
        async def _handle_result(self, result):
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async with start_span(operation) as _span:
                return await fn(*args, **kwargs)

        return wrapper

    return decorator


class TraceContext:
    """Per-run trace context manager.

    Holds the ``trace_id`` (= run_id) and provides span creation helpers.
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._completed_spans: list[SpanContext] = []
        on_span_complete(self._on_span_complete)

    def _on_span_complete(self, span: SpanContext) -> None:
        if span.trace_id == self.trace_id:
            self._completed_spans.append(span)

    @property
    def completed_spans(self) -> list[SpanContext]:
        return list(self._completed_spans)

    def new_span(
        self,
        operation: str,
        attributes: dict[str, Any] | None = None,
    ) -> SpanContext:
        """Create a new span (caller must call ``finish()`` manually)."""
        parent = _current_span.get()
        return SpanContext(
            trace_id=self.trace_id,
            parent_span_id=parent.span_id if parent else "",
            operation=operation,
            attributes=dict(attributes) if attributes else {},
        )

    def cleanup(self) -> None:
        """Remove the span listener to avoid leaks."""
        remove_span_listener(self._on_span_complete)
