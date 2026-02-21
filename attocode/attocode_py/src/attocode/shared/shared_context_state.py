"""Shared context state for cross-worker coordination.

Central failure tracker and reference pool shared across swarm workers.
Tracks failures, pools compaction references, and provides shared KV-cache prefix.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from attocode.tricks.failure_evidence import Failure, FailureTracker
from attocode.tricks.reversible_compaction import Reference


@dataclass(slots=True)
class SharedContextConfig:
    """Configuration for shared context state."""

    max_references: int = 200
    max_failures_per_worker: int = 50
    kv_cache_prefix: str | None = None


@dataclass
class SharedContextState:
    """Cross-worker failure tracking and reference pool.

    Thread-safe shared state enabling swarm workers to:
    - Report and access failure history from all workers
    - Pool compaction references for knowledge sharing
    - Use a shared KV-cache prefix for alignment
    """

    config: SharedContextConfig = field(default_factory=SharedContextConfig)

    _failure_tracker: FailureTracker = field(default_factory=FailureTracker)
    _references: list[Reference] = field(default_factory=list)
    _reference_ids: set[str] = field(default_factory=set)
    _kv_cache_prefix: str = field(default="")
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_failure(self, worker_id: str, failure_input: str, error: str = "") -> None:
        """Track a failure from any worker."""
        with self._lock:
            self._failure_tracker.record(
                tool_name=f"[{worker_id}]",
                input_str=failure_input,
                error=error,
            )

    def get_failure_context(self, max_failures: int = 10) -> str:
        """Format failures for LLM inclusion."""
        with self._lock:
            return self._failure_tracker.format_context(max_recent=max_failures)

    def get_failure_insights(self) -> list[str]:
        """Extract actionable insights from failures."""
        with self._lock:
            return self._failure_tracker.get_insights()

    def add_references(self, refs: list[Reference]) -> None:
        """Pool compaction references with deduplication."""
        with self._lock:
            for ref in refs:
                ref_id = f"{ref.source}:{ref.key}" if hasattr(ref, "key") else ref.source
                if ref_id not in self._reference_ids:
                    self._reference_ids.add(ref_id)
                    self._references.append(ref)

            # Trim to max
            if len(self._references) > self.config.max_references:
                removed = self._references[: len(self._references) - self.config.max_references]
                self._references = self._references[-self.config.max_references :]
                for ref in removed:
                    ref_id = f"{ref.source}:{ref.key}" if hasattr(ref, "key") else ref.source
                    self._reference_ids.discard(ref_id)

    def search_references(self, query: str) -> list[Reference]:
        """Find references by substring match."""
        with self._lock:
            query_lower = query.lower()
            return [
                r for r in self._references
                if query_lower in r.source.lower()
                or (hasattr(r, "summary") and query_lower in (r.summary or "").lower())
            ]

    @property
    def kv_cache_prefix(self) -> str:
        """Get the shared KV-cache prefix."""
        return self._kv_cache_prefix

    @kv_cache_prefix.setter
    def kv_cache_prefix(self, value: str) -> None:
        self._kv_cache_prefix = value

    def get_stats(self) -> dict[str, int]:
        """Get aggregated stats."""
        with self._lock:
            return {
                "failure_count": len(self._failure_tracker.failures),
                "reference_count": len(self._references),
            }

    def to_json(self) -> dict[str, Any]:
        """Serialize for checkpoint persistence."""
        with self._lock:
            return {
                "failures": [
                    {"tool": f.tool_name, "input": f.input_str, "error": f.error}
                    for f in self._failure_tracker.failures
                ],
                "references": [
                    {"source": r.source, "summary": getattr(r, "summary", "")}
                    for r in self._references
                ],
                "kv_cache_prefix": self._kv_cache_prefix,
            }

    def restore_from(self, data: dict[str, Any]) -> None:
        """Restore from checkpoint data."""
        with self._lock:
            self._failure_tracker = FailureTracker()
            for f in data.get("failures", []):
                self._failure_tracker.record(
                    tool_name=f.get("tool", ""),
                    input_str=f.get("input", ""),
                    error=f.get("error", ""),
                )
            self._references = []
            self._reference_ids = set()
            for r in data.get("references", []):
                ref = Reference(source=r.get("source", ""), summary=r.get("summary", ""))
                self._references.append(ref)
                self._reference_ids.add(ref.source)
            self._kv_cache_prefix = data.get("kv_cache_prefix", "")

    def clear(self) -> None:
        """Clear all state."""
        with self._lock:
            self._failure_tracker = FailureTracker()
            self._references.clear()
            self._reference_ids.clear()
            self._kv_cache_prefix = ""
