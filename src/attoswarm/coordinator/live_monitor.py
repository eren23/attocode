"""Hot-path live telemetry persistence for the swarm TUI.

Separates high-frequency UI data from heavyweight checkpoint state.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from attoswarm.protocol.io import append_jsonl, write_json_fast
from attoswarm.protocol.models import utc_now_iso


class LiveMonitor:
    """Persist a live event journal plus a lightweight materialized view."""

    def __init__(
        self,
        *,
        events_path: Path,
        state_path: Path,
        snapshot_builder: Callable[[], dict[str, Any]],
        snapshot_debounce_s: float = 0.1,
    ) -> None:
        self._events_path = events_path
        self._state_path = state_path
        self._snapshot_builder = snapshot_builder
        self._snapshot_debounce_s = snapshot_debounce_s
        self._seq = 0
        self._dirty = False
        self._last_snapshot_ts = 0.0

    def emit(
        self,
        *,
        event_type: str,
        task_id: str = "",
        agent_id: str = "",
        message: str = "",
        payload: dict[str, Any] | None = None,
        force_snapshot: bool = False,
        timestamp: float | None = None,
    ) -> None:
        self._seq += 1
        ts = timestamp if timestamp is not None else time.time()
        append_jsonl(
            self._events_path,
            {
                "seq": self._seq,
                "type": event_type,
                "kind": event_type,
                "timestamp": ts,
                "task_id": task_id,
                "agent_id": agent_id,
                "message": message,
                "payload": payload or {},
            },
        )
        self._dirty = True
        self.persist_snapshot(force=force_snapshot)

    def persist_snapshot(self, *, force: bool = False) -> None:
        now = time.time()
        if not self._dirty and not force:
            return
        if not force and now - self._last_snapshot_ts < self._snapshot_debounce_s:
            return
        snapshot = self._snapshot_builder()
        snapshot["updated_at"] = snapshot.get("updated_at") or utc_now_iso()
        snapshot["live_seq"] = self._seq
        write_json_fast(self._state_path, snapshot)
        self._dirty = False
        self._last_snapshot_ts = now

