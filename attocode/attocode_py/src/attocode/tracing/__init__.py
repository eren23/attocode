"""Tracing package -- lifecycle event collection and cache boundary tracking.

This package replaces the original single-file ``tracing.py`` module with a
richer set of types, a buffered JSONL collector, and KV-cache boundary
tracking.

Backward compatibility
~~~~~~~~~~~~~~~~~~~~~~
The :class:`TraceWriter` class is re-exported here so that existing imports
of the form ``from attocode.tracing import TraceWriter`` continue to work
unchanged.

Submodules
~~~~~~~~~~
- :mod:`attocode.tracing.types` -- Event kinds, trace event dataclass, session
  and summary structures.
- :mod:`attocode.tracing.collector` -- :class:`TraceCollector` (buffered JSONL
  writer) and the :class:`TraceWriter` compatibility shim.
- :mod:`attocode.tracing.cache_boundary` -- :class:`CacheBoundaryTracker` for
  monitoring KV-cache hit/miss patterns.
- :mod:`attocode.tracing.analysis` -- Post-hoc analysis: session metrics,
  inefficiency detection, token flow analysis.
"""

from __future__ import annotations

# --- types ----------------------------------------------------------------
from attocode.tracing.types import (
    TraceEvent,
    TraceEventCategory,
    TraceEventKind,
    TraceSession,
    TraceSummary,
    create_trace_event,
    event_type_to_trace_kind,
    get_trace_event_category,
    TRACE_EVENT_CATEGORIES,
)

# --- collector ------------------------------------------------------------
from attocode.tracing.collector import (
    TraceCollector,
    TraceWriter,
    load_trace_session,
)

# --- cache boundary -------------------------------------------------------
from attocode.tracing.cache_boundary import (
    CacheBoundaryTracker,
    CacheHitRecord,
    CacheStats,
)

__all__ = [
    # types
    "TraceEvent",
    "TraceEventCategory",
    "TraceEventKind",
    "TraceSession",
    "TraceSummary",
    "create_trace_event",
    "event_type_to_trace_kind",
    "get_trace_event_category",
    "TRACE_EVENT_CATEGORIES",
    # collector
    "TraceCollector",
    "TraceWriter",
    "load_trace_session",
    # cache boundary
    "CacheBoundaryTracker",
    "CacheHitRecord",
    "CacheStats",
    # analysis (subpackage -- import via attocode.tracing.analysis)
    "analysis",
]
