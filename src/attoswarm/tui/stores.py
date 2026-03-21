"""State and event polling store for attoswarm TUI."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from attoswarm.protocol.io import read_json


def _to_epoch(ts: Any) -> float:
    """Normalize a timestamp (epoch number or ISO string) to a float epoch."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str) and ts:
        try:
            from datetime import datetime
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    return 0.0


class StateStore:
    def __init__(self, run_dir: str) -> None:
        self.run_dir = Path(run_dir)
        self.state_path = self.run_dir / "swarm.state.json"
        self.events_path = self.run_dir / "swarm.events.jsonl"
        self._task_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cache_ttl = 5.0

        # State-level cache: (mtime, state_seq, data)
        self._state_cache: tuple[float, int, dict[str, Any]] | None = None

        # Incremental JSONL event reading
        self._events_last_size: int = 0
        self._events_cache: list[dict[str, Any]] = []

        # Cross-run staleness detection
        self._last_run_id: str | None = None

    def _invalidate_run_caches(self) -> None:
        """Clear caches that can leak stale data across run_id transitions."""
        self._events_cache.clear()
        self._events_last_size = 0
        self._task_cache.clear()

        for attr in list(vars(self)):
            if (
                attr.startswith("_trace_summary_")
                or attr.startswith("_trace_offset_")
                or attr in {"_messages_cache", "_sidecar_cache", "_events_last_stat"}
            ):
                delattr(self, attr)

    def read_state(self) -> dict[str, Any]:
        """Read state with mtime + state_seq change detection."""
        try:
            mtime = self.state_path.stat().st_mtime
        except OSError:
            return {}
        if self._state_cache is not None:
            cached_mtime, cached_seq, cached_data = self._state_cache
            if mtime == cached_mtime:
                return cached_data
        data = read_json(self.state_path, default={})
        seq = data.get("state_seq", 0) if isinstance(data, dict) else 0

        # Cross-run staleness: if run_id changed, invalidate all caches
        if isinstance(data, dict):
            run_id = data.get("run_id", "")
            if run_id and run_id != self._last_run_id:
                # New run detected (or first run after _last_run_id was None)
                if self._last_run_id is not None:
                    # Only clear caches if we had a PREVIOUS run cached
                    self._invalidate_run_caches()
                self._last_run_id = run_id
            elif run_id:
                self._last_run_id = run_id

        self._state_cache = (mtime, seq, data)
        return data

    def has_new_events(self) -> bool:
        """Check if events file has grown since last read (no I/O beyond stat).

        Caches the stat'd size so that a subsequent ``read_events`` call in the
        same refresh cycle avoids a redundant stat.
        """
        try:
            size = self.events_path.stat().st_size
        except OSError:
            return False
        self._events_last_stat: int = size
        return size != self._events_last_size

    _MAX_CACHED_EVENTS = 2000

    def read_events(self, limit: int = 200) -> list[dict[str, Any]]:
        """Incremental JSONL read — only parses new bytes since last call."""
        if not self.events_path.exists():
            return []
        # Re-use size from has_new_events() if available (same refresh cycle)
        size = getattr(self, "_events_last_stat", None)
        if size is None:
            try:
                size = self.events_path.stat().st_size
            except OSError:
                return self._events_cache[-limit:]
        else:
            self._events_last_stat = None  # consume cached value

        if size == self._events_last_size:
            return self._events_cache[-limit:]  # No new data

        with self.events_path.open("rb") as f:
            if self._events_last_size > 0 and size > self._events_last_size:
                # Read only new bytes
                f.seek(self._events_last_size)
            else:
                # File truncated or first read — reset
                self._events_cache.clear()
                self._events_last_size = 0
            last_good_pos = f.tell()
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith(b"\n"):
                        # Unterminated line at EOF — partial write in progress
                        break
                    # Terminated but corrupt — skip past it
                    last_good_pos = f.tell()
                    continue
                if isinstance(item, dict):
                    self._events_cache.append(item)
                last_good_pos = f.tell()
            self._events_last_size = last_good_pos

        # Cap in-memory cache to prevent unbounded growth
        if len(self._events_cache) > self._MAX_CACHED_EVENTS:
            self._events_cache = self._events_cache[-self._MAX_CACHED_EVENTS:]

        return self._events_cache[-limit:]

    def read_agent_box(self, agent_id: str, box: str) -> dict[str, Any]:
        path = self.run_dir / "agents" / f"agent-{agent_id}.{box}.json"
        return read_json(path, default={})

    def read_task(self, task_id: str) -> dict[str, Any]:
        path = self.run_dir / "tasks" / f"task-{task_id}.json"
        return read_json(path, default={})

    def _read_task_cached(self, task_id: str) -> dict[str, Any]:
        """Read task with a short TTL cache to avoid N+1 file reads per refresh."""
        now = time.time()
        entry = self._task_cache.get(task_id)
        if entry and now - entry[0] < self._cache_ttl:
            return entry[1]
        data = self.read_task(task_id)
        self._task_cache[task_id] = (now, data)
        return data

    # ── Data transform helpers for rich widgets ──────────────────────

    _ACTIVITY_LABELS: dict[str, str] = {
        "spawn": "Starting...",
        "agent.spawned": "Starting...",
        "claim": "Claiming task",
        "task.claimed": "Claiming task",
        "complete": "Completed",
        "task.completed": "Completed",
        "fail": "Failed",
        "task.failed": "Failed",
    }

    def build_agent_activity(
        self, raw_events: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Scan events for per-agent latest activity.

        Returns ``{agent_id: activity_string}`` with human-readable descriptions.
        """
        activity: dict[str, str] = {}
        for ev in raw_events:
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            agent_id = str(
                ev.get("agent_id", "")
                or payload.get("agent_id", "")
            )
            if not agent_id:
                continue

            etype = str(ev.get("type", ev.get("event_type", "")))

            if etype == "task.files_changed":
                files = payload.get("files", [])
                if isinstance(files, list) and files:
                    first = str(files[0]).rsplit("/", 1)[-1]
                    extra = f" +{len(files) - 1}" if len(files) > 1 else ""
                    activity[agent_id] = f"Editing {first}{extra}"
                continue

            label = self._ACTIVITY_LABELS.get(etype)
            if label:
                activity[agent_id] = label
            else:
                # Fallback to event message — don't use raw etype as it
                # overwrites previously-set meaningful labels
                msg = str(
                    ev.get("message", "")
                    or payload.get("message", "")
                )[:60]
                if msg:
                    activity[agent_id] = msg

        return activity

    def build_agent_list(
        self,
        state: dict[str, Any],
        activity: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Transform active_agents into AgentsDataTable-compatible format."""
        now = time.time()

        # Build task_id -> title lookup from DAG
        title_map: dict[str, str] = {}
        for node in state.get("dag", {}).get("nodes", []):
            title_map[str(node.get("task_id", ""))] = str(node.get("title", ""))

        out: list[dict[str, Any]] = []
        for row in state.get("active_agents", []):
            agent_id = str(row.get("agent_id", "?"))
            task_id = str(row.get("task_id", ""))
            started = row.get("started_at_epoch", 0)
            if started and isinstance(started, (int, float)):
                secs = int(now - started)
                elapsed = f"{secs // 60}m{secs % 60:02d}s"
            else:
                elapsed = ""
            # Trace summary enrichment
            trace = self.build_agent_trace_summary(task_id) if task_id else {}

            out.append({
                "agent_id": agent_id,
                "status": str(row.get("status", "idle")),
                "task_id": task_id,
                "backend": str(row.get("backend", "")),
                "model": str(row.get("model", row.get("backend", ""))),
                "role_type": str(row.get("role_type", "")),
                "execution_mode": str(row.get("execution_mode", "")),
                "tokens_used": int(row.get("tokens_used", 0)),
                "elapsed": elapsed,
                "task_title": str(row.get("task_title", "")) or title_map.get(task_id, ""),
                "activity": (activity or {}).get(agent_id, ""),
                "cwd": str(row.get("cwd", "")),
                "exit_code": row.get("exit_code"),
                "restart_count": int(row.get("restart_count", 0)),
                "stderr_tail": str(row.get("stderr_tail", "")),
                "command": str(row.get("command", "")),
                "tool_calls": trace.get("tool_calls", []),
                "error_count": trace.get("error_count", 0),
                "last_error": trace.get("last_error", ""),
                "files_written": trace.get("files_written", []),
                "total_cost": trace.get("total_cost", 0.0),
            })
        return out

    def build_task_list(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Transform dag.nodes into TaskBoard/TasksDataTable-compatible format.

        Prefers enriched data from DAG nodes (written by state_writer) to avoid
        N+1 per-task file reads.  Falls back to per-task JSON when enriched
        fields are missing.
        """
        dag = state.get("dag", {})
        nodes = dag.get("nodes", [])
        edges = dag.get("edges", [])
        # Build reverse lookup: target -> [source]
        deps_map = self._parse_edges(edges)

        attempts = state.get("attempts", {})
        by_task = attempts.get("by_task", {}) if isinstance(attempts, dict) else {}

        # Build forward map (source -> [targets]) once for O(1) is_foundation lookup
        fwd_map: dict[str, list[str]] = {}
        for edge in edges:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                src = str(edge[0])
                tgt = str(edge[1])
            elif isinstance(edge, dict):
                src = str(edge.get("source", edge.get("from", "")))
                tgt = str(edge.get("target", edge.get("to", "")))
            else:
                continue
            if src:
                fwd_map.setdefault(src, []).append(tgt)

        out: list[dict[str, Any]] = []
        for node in nodes:
            task_id = str(node.get("task_id", ""))

            # Use enriched DAG node data; fall back to per-task JSON only if needed
            task_kind = node.get("task_kind", "")
            role_hint = node.get("role_hint", "")
            assigned_agent = node.get("assigned_agent", "")
            if not task_kind and not role_hint:
                detail = self._read_task_cached(task_id)
                task_kind = task_kind or detail.get("task_kind", "")
                role_hint = role_hint or detail.get("role_hint", "")
                assigned_agent = assigned_agent or detail.get("assigned_agent", "")

            # is_foundation: prefer serialized value, fall back to edge count
            is_foundation = node.get("is_foundation")
            if is_foundation is None:
                is_foundation = len(fwd_map.get(task_id, [])) >= 3

            out.append({
                "task_id": task_id,
                "title": str(node.get("title", "")),
                "status": str(node.get("status", "pending")),
                "description": str(node.get("description", ""))[:200],
                "task_kind": str(task_kind),
                "role_hint": str(role_hint),
                "assigned_agent": str(assigned_agent),
                "target_files": node.get("target_files", []),
                "result_summary": str(node.get("result_summary", "")),
                "attempts": int(node.get("attempts", 0)) or int(node.get("attempt_count", 0)) or int(by_task.get(task_id, 0)),
                "depends_on": deps_map.get(task_id, []),
                "tokens_used": int(node.get("tokens_used", 0)),
                "cost_usd": float(node.get("cost_usd", 0.0)),
                "is_foundation": bool(is_foundation),
                "quality_score": node.get("quality_score"),
            })
        return out

    def build_dag_nodes(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Transform dag into DependencyDAGView-compatible format (with levels)."""
        dag = state.get("dag", {})
        nodes = dag.get("nodes", [])
        edges = dag.get("edges", [])

        deps_map = self._parse_edges(edges)

        # Compute topological levels
        node_ids = [str(n.get("task_id", "")) for n in nodes]
        levels: dict[str, int] = {}
        for nid in node_ids:
            self._compute_level(nid, deps_map, levels)

        # Build reverse dependency map (source -> [targets that depend on it])
        depended_by_map: dict[str, list[str]] = {}
        for edge in edges:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                src = str(edge[0])
                tgt = str(edge[1])
            elif isinstance(edge, dict):
                src = str(edge.get("source", edge.get("from", "")))
                tgt = str(edge.get("target", edge.get("to", "")))
            else:
                continue
            if src:
                depended_by_map.setdefault(src, []).append(tgt)

        out: list[dict[str, Any]] = []
        for node in nodes:
            tid = str(node.get("task_id", ""))
            out.append({
                "task_id": tid,
                "status": str(node.get("status", "pending")),
                "depends_on": deps_map.get(tid, []),
                "depended_by": node.get("depended_by", depended_by_map.get(tid, [])),
                "level": levels.get(tid, 0),
            })
        return out

    @staticmethod
    def _parse_edges(edges: list[Any]) -> dict[str, list[str]]:
        """Parse edges into a target -> [sources] dependency map.

        Handles both list format ``[[a, b], ...]`` (from state_writer)
        and dict format ``[{source, target}, ...]``.
        """
        deps_map: dict[str, list[str]] = {}
        for edge in edges:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                src, tgt = str(edge[0]), str(edge[1])
            elif isinstance(edge, dict):
                src = str(edge.get("source", edge.get("from", "")))
                tgt = str(edge.get("target", edge.get("to", "")))
            else:
                continue
            if tgt:
                deps_map.setdefault(tgt, []).append(src)
        return deps_map

    @staticmethod
    def _compute_level(
        node_id: str,
        deps_map: dict[str, list[str]],
        levels: dict[str, int],
        _visiting: set[str] | None = None,
    ) -> int:
        if node_id in levels:
            return levels[node_id]
        if _visiting is None:
            _visiting = set()
        if node_id in _visiting:
            levels[node_id] = 0
            return 0  # Break cycle
        _visiting.add(node_id)
        deps = deps_map.get(node_id, [])
        if not deps:
            levels[node_id] = 0
        else:
            levels[node_id] = max(
                StateStore._compute_level(d, deps_map, levels, _visiting)
                for d in deps
            ) + 1
        _visiting.discard(node_id)
        return levels[node_id]

    def build_event_list(self, raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw JSONL events into EventTimeline-compatible format."""
        out: list[dict[str, Any]] = []
        for ev in raw_events:
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}

            # Message — check direct field first (SwarmEvent), then nested payload (HybridCoordinator)
            msg = (
                ev.get("message", "")
                or payload.get("message", "")
                or payload.get("debug_detail", "")
                or payload.get("debug_marker", "")
                or payload.get("reason", "")
                or payload.get("event_type", "")
                or str(ev.get("type", ""))
            )

            ts_raw = ev.get("timestamp", "")
            # Convert ISO timestamp to epoch if needed
            if isinstance(ts_raw, str) and ts_raw:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except Exception:
                    ts = 0
            elif isinstance(ts_raw, (int, float)):
                ts = ts_raw
            else:
                ts = 0

            # Type — SwarmEvent uses "event_type", HybridCoordinator uses "type"
            etype = str(ev.get("type", ev.get("event_type", "info")))
            # Map common event types to timeline categories
            type_map = {
                "agent.spawned": "spawn",
                "task.claimed": "claim",
                "task.completed": "complete",
                "task.failed": "fail",
                "task.skipped": "skip",
                "file.written": "write",
                "conflict.detected": "conflict",
                "budget.warning": "budget",
                "spawn": "spawn",
                "claim": "claim",
                "complete": "complete",
                "fail": "fail",
            }
            timeline_type = type_map.get(etype, etype.split(".")[-1] if "." in etype else "info")

            # Task ID — SwarmEvent has top-level "task_id", HybridCoordinator nests it
            task_id = str(ev.get("task_id", "") or payload.get("task_id", payload.get("task", "")))
            agent_id = str(ev.get("agent_id", "") or payload.get("agent_id", ""))

            out.append({
                "type": timeline_type,
                "message": str(msg)[:120],
                "timestamp": ts,
                "agent_id": agent_id,
                "task_id": task_id,
            })
        return out

    def read_file_activity(self) -> dict[str, list[dict[str, Any]]]:
        """Scan swarm events for task.files_changed to build file activity map."""
        events = self.read_events(limit=500)
        activity: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            if ev.get("type") != "task.files_changed":
                continue
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            agent_id = str(payload.get("agent_id", ""))
            files = payload.get("files", [])
            if not isinstance(files, list):
                continue
            for fp in files:
                activity.setdefault(str(fp), []).append({
                    "agent_id": agent_id,
                    "action": "write",
                })
        return activity

    def read_all_messages(self) -> list[dict[str, Any]]:
        """Read all agent inbox/outbox messages and produce unified timeline.

        Returns list of dicts with: direction, agent_id, kind, task_id,
        timestamp, payload_preview — sorted by timestamp.
        """
        agents_dir = self.run_dir / "agents"
        if not agents_dir.exists():
            return []

        now = time.time()
        cache_key = "_messages_cache"
        cached = getattr(self, cache_key, None)
        if cached and now - cached[0] < 5.0:
            return cached[1]

        messages: list[dict[str, Any]] = []

        for path in agents_dir.iterdir():
            if not path.name.endswith(".json"):
                continue
            name = path.name

            # Parse agent-{id}.inbox.json or agent-{id}.outbox.json
            if ".inbox.json" in name:
                direction_label = "coordinator\u2192agent"
                agent_id = name.replace("agent-", "").replace(".inbox.json", "")
            elif ".outbox.json" in name:
                direction_label = "agent\u2192coordinator"
                agent_id = name.replace("agent-", "").replace(".outbox.json", "")
            else:
                continue

            data = read_json(path, default={})
            items_key = "events" if ".outbox.json" in name else "messages"
            for msg in data.get(items_key, []):
                if not isinstance(msg, dict):
                    continue
                kind = msg.get("kind", "") or msg.get("type", "")
                payload = msg.get("payload", {})
                payload_str = self._extract_payload_preview(kind, payload)

                messages.append({
                    "direction": direction_label,
                    "agent_id": agent_id,
                    "kind": kind,
                    "task_id": str(msg.get("task_id", "") or ""),
                    "timestamp": msg.get("timestamp", ""),
                    "payload_preview": payload_str,
                })

        # Fallback: if no inbox/outbox files found, synthesize from events
        if not messages:
            messages = self._synthesize_messages_from_events()

        # Sort by timestamp
        messages.sort(key=lambda m: _to_epoch(m.get("timestamp", "")))

        setattr(self, cache_key, (now, messages))
        return messages

    def _synthesize_messages_from_events(self) -> list[dict[str, Any]]:
        """Convert swarm events into message-like dicts as fallback.

        Used when SwarmOrchestrator (shared workspace mode) is active and
        does not write inbox/outbox files.
        """
        _EVENT_TO_MESSAGE: dict[str, tuple[str, str]] = {  # noqa: N806
            "spawn": ("coordinator\u2192agent", "task_assign"),
            "agent.spawned": ("coordinator\u2192agent", "task_assign"),
            "agent.task.launch": ("coordinator\u2192agent", "task_assign"),
            "complete": ("agent\u2192coordinator", "task_done"),
            "task.completed": ("agent\u2192coordinator", "task_done"),
            "fail": ("agent\u2192coordinator", "task_failed"),
            "task.failed": ("agent\u2192coordinator", "task_failed"),
            "retry": ("coordinator\u2192agent", "retry"),
        }

        raw_events = self.read_events(limit=500)
        out: list[dict[str, Any]] = []
        for ev in raw_events:
            etype = str(ev.get("type", ev.get("event_type", "")))
            mapping = _EVENT_TO_MESSAGE.get(etype)
            if not mapping:
                continue
            direction, kind = mapping
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
            agent_id = str(ev.get("agent_id", "") or payload.get("agent_id", ""))
            task_id = str(ev.get("task_id", "") or payload.get("task_id", ""))

            # Build structured payload from event data
            synth_payload: dict[str, Any] = {**payload, **data}
            synth_payload.setdefault("message", ev.get("message", ""))
            msg_text = self._extract_payload_preview(kind, synth_payload)

            entry: dict[str, Any] = {
                "direction": direction,
                "agent_id": agent_id,
                "kind": kind,
                "task_id": task_id,
                "timestamp": ev.get("timestamp", ""),
                "payload_preview": msg_text,
            }
            # Attach extra fields for rendering badges
            tokens = data.get("tokens_used", 0) or payload.get("tokens_used", 0)
            cost = data.get("cost_usd", 0) or payload.get("cost_usd", 0)
            if tokens:
                entry["tokens_used"] = int(tokens)
            if cost:
                entry["cost_usd"] = float(cost)
            out.append(entry)
        return out

    @staticmethod
    def _extract_payload_preview(kind: str, payload: Any) -> str:
        """Extract a human-readable preview from a message payload."""
        if not isinstance(payload, dict):
            return str(payload)[:200] if payload else ""

        if kind in ("task_assign",):
            title = payload.get("title", "") or payload.get("description", "")
            return str(title)[:100] if title else str(payload)[:200]

        if kind in ("task_done", "task_completed"):
            result = payload.get("result_summary", "") or payload.get("message", "")
            n_files = len(payload.get("files_modified", []))
            parts: list[str] = []
            if result:
                parts.append(f"Result: {str(result)[:80]}")
            if n_files:
                parts.append(f"{n_files} files")
            return " | ".join(parts) if parts else str(payload)[:200]

        if kind in ("task_failed",):
            err = payload.get("error", "") or payload.get("message", "")
            cause = payload.get("failure", {}).get("cause", "") if isinstance(payload.get("failure"), dict) else ""
            if err:
                prefix = f"[{cause}] " if cause else ""
                return f"Error: {prefix}{str(err)[:100]}"
            return str(payload)[:200]

        if kind == "retry":
            attempt = payload.get("attempt", "?")
            reason = payload.get("reason", "") or payload.get("message", "")
            return f"Attempt {attempt}: {str(reason)[:80]}" if reason else f"Attempt {attempt}"

        # Fallback
        msg = payload.get("message", "")
        if msg:
            return str(msg)[:200]
        return str(payload)[:200]

    def build_task_detail(
        self, task_id: str, state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build DetailInspector-compatible dict for a task.

        Tries the per-task JSON file first; falls back to reconstructing
        from the DAG + event log when the file doesn't exist.
        """
        task = self.read_task(task_id)
        if task:
            detail: dict[str, Any] = {
                "kind": "task",
                "task_id": task_id,
                "title": task.get("title", ""),
                "status": task.get("status", ""),
                "task_kind": task.get("task_kind", ""),
                "description": task.get("description", ""),
                "deps": task.get("depends_on", task.get("deps", [])),
                "target_files": task.get("target_files", []),
                "files_modified": task.get("files_modified", []),
                "result_summary": task.get("result_summary", ""),
                "tokens_used": int(task.get("tokens_used", 0)),
                "cost_usd": float(task.get("cost_usd", 0.0)),
                "attempt_count": int(task.get("attempt_count", 0)),
                "attempt_history": task.get("attempt_history", []),
            }
            # Read prompt file if exists
            prompt_path = self.run_dir / "agents" / f"agent-{task_id}.prompt.txt"
            if prompt_path.exists():
                try:
                    detail["prompt_preview"] = prompt_path.read_text(encoding="utf-8")[:500]
                except Exception:
                    pass
            # Read diff file if exists
            diff_path = self.run_dir / "tasks" / f"task-{task_id}.diff"
            if diff_path.exists():
                try:
                    detail["diff_content"] = diff_path.read_text(encoding="utf-8")[:5000]
                except Exception:
                    pass
            # Read activity sidecar if exists
            activity_path = self.run_dir / "agents" / f"agent-{task_id}.activity.txt"
            if activity_path.exists():
                try:
                    detail["agent_activity"] = activity_path.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            if detail.get("status") == "pending":
                detail["blocked_reason"] = self._diagnose_pending(task_id, state)
            return detail

        # -- Fallback: reconstruct from state DAG + events ----------------
        if state is None:
            state = self.read_state()
        dag = state.get("dag", {})
        node = next(
            (n for n in dag.get("nodes", []) if str(n.get("task_id", "")) == task_id),
            None,
        )
        if not node:
            return {}

        # Scan events for spawn/complete/fail timing + agent info
        events = self.read_events(limit=500)
        agent_id = ""
        spawn_ts = 0.0
        complete_ts = 0.0
        result_msg = ""
        files_modified: list[str] = []
        for ev in events:
            ev_task = str(
                ev.get("task_id", "")
                or (ev.get("payload", {}) or {}).get("task_id", "")
            )
            if ev_task != task_id:
                continue
            etype = str(ev.get("event_type", ev.get("type", "")))
            if etype == "spawn":
                spawn_ts = _to_epoch(ev.get("timestamp", 0))
                agent_id = str(ev.get("agent_id", "")) or f"agent-{task_id}"
            elif etype in ("complete", "task.completed"):
                complete_ts = _to_epoch(ev.get("timestamp", 0))
                result_msg = str(ev.get("message", ""))
                data = ev.get("data", ev.get("payload", {})) or {}
                files_modified = data.get("files_modified", [])
            elif etype in ("fail", "task.failed"):
                complete_ts = _to_epoch(ev.get("timestamp", 0))
                result_msg = str(ev.get("message", ""))

        # Find matching agent entry for model info
        model = ""
        for ag in state.get("active_agents", []):
            if str(ag.get("task_id", "")) == task_id:
                model = str(ag.get("model", ag.get("backend", "")))
                if not agent_id:
                    agent_id = str(ag.get("agent_id", ""))
                break

        # Compute duration
        duration = ""
        if spawn_ts and complete_ts:
            secs = int(complete_ts - spawn_ts)
            duration = f"{secs // 60}m{secs % 60:02d}s" if secs >= 60 else f"{secs}s"

        # Dependencies from edges
        edges = dag.get("edges", [])
        deps = [
            str(e[0])
            for e in edges
            if isinstance(e, (list, tuple)) and len(e) >= 2 and str(e[1]) == task_id
        ]

        fallback_detail: dict[str, Any] = {
            "kind": "task",
            "task_id": task_id,
            "title": str(node.get("title", "")),
            "status": str(node.get("status", "pending")),
            "task_kind": "",
            "description": result_msg,
            "deps": deps,
            "target_files": files_modified,
            "agent_id": agent_id,
            "model": model,
            "duration": duration,
        }
        if fallback_detail.get("status") == "pending":
            fallback_detail["blocked_reason"] = self._diagnose_pending(task_id, state)
        return fallback_detail

    def _diagnose_pending(
        self, task_id: str, state: dict[str, Any] | None = None,
    ) -> str:
        """Explain why a pending task hasn't executed."""
        if state is None:
            state = self.read_state()
        dag = state.get("dag", {})
        edges = dag.get("edges", [])
        deps_map = self._parse_edges(edges)
        deps = deps_map.get(task_id, [])

        nodes = {str(n.get("task_id", "")): n for n in dag.get("nodes", [])}

        if not deps:
            return "No dependencies -- should be ready (possible orchestrator bug)"

        dep_statuses: list[tuple[str, str]] = []
        for dep_id in deps:
            dep_node = nodes.get(dep_id, {})
            dep_statuses.append((dep_id, str(dep_node.get("status", "unknown"))))

        pending_deps = [d for d, s in dep_statuses if s == "pending"]
        failed_deps = [d for d, s in dep_statuses if s in ("failed", "skipped")]
        running_deps = [d for d, s in dep_statuses if s == "running"]

        parts: list[str] = []
        if pending_deps:
            parts.append(f"Waiting on pending: {', '.join(pending_deps)}")
        if running_deps:
            parts.append(f"Waiting on running: {', '.join(running_deps)}")
        if failed_deps:
            parts.append(f"Blocked by failed: {', '.join(failed_deps)}")

        # Check if swarm ended before this task was reached
        phase = state.get("phase", "")
        if phase == "completed" and not running_deps:
            all_deps_done = all(s == "done" for _, s in dep_statuses)
            if all_deps_done:
                parts.append(
                    "All deps done -- swarm ended before task was scheduled (orchestrator bug)"
                )
            elif pending_deps:
                parts.append("Swarm ended while dependencies still pending")

        return "; ".join(parts) if parts else "Unknown"

    def build_per_task_costs(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Return per-task cost breakdown for budget display."""
        dag = state.get("dag", {})
        nodes = dag.get("nodes", [])
        costs: list[dict[str, Any]] = []
        for node in nodes:
            cost = float(node.get("cost_usd", 0))
            if cost > 0:
                costs.append({
                    "task_id": str(node.get("task_id", "")),
                    "cost_usd": cost,
                    "tokens_used": int(node.get("tokens_used", 0)),
                })
        costs.sort(key=lambda c: c["cost_usd"], reverse=True)
        return costs

    def build_agent_detail(
        self, agent_id: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Build DetailInspector-compatible dict for an agent."""
        agents = state.get("active_agents", [])
        row = next(
            (a for a in agents if str(a.get("agent_id", "")) == agent_id),
            None,
        )
        if not row or not isinstance(row, dict):
            return {}

        task_id = str(row.get("task_id", ""))

        # Get task title from persisted data or DAG
        task_title = str(row.get("task_title", ""))
        if not task_title:
            for node in state.get("dag", {}).get("nodes", []):
                if str(node.get("task_id", "")) == task_id:
                    task_title = str(node.get("title", ""))
                    break

        # Scan events for timing, result, and files
        events = self.read_events(limit=500)
        spawn_ts = 0.0
        complete_ts = 0.0
        result_msg = ""
        files: list[str] = []
        for ev in events:
            ev_task = str(
                ev.get("task_id", "")
                or (ev.get("payload", {}) or {}).get("task_id", "")
            )
            ev_agent = str(
                ev.get("agent_id", "")
                or (ev.get("payload", {}) or {}).get("agent_id", "")
            )
            if ev_task != task_id and ev_agent != agent_id:
                continue
            etype = str(ev.get("event_type", ev.get("type", "")))
            if etype == "spawn":
                spawn_ts = _to_epoch(ev.get("timestamp", 0))
            elif etype in ("complete", "task.completed"):
                complete_ts = _to_epoch(ev.get("timestamp", 0))
                result_msg = str(ev.get("message", ""))
                data = ev.get("data", ev.get("payload", {})) or {}
                for fp in data.get("files_modified", []):
                    if str(fp) not in files:
                        files.append(str(fp))
            elif etype in ("fail", "task.failed"):
                complete_ts = _to_epoch(ev.get("timestamp", 0))
                result_msg = str(ev.get("message", ""))
            elif etype == "task.files_changed":
                payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
                if str(payload.get("agent_id", "")) == agent_id:
                    for fp in payload.get("files", []):
                        if str(fp) not in files:
                            files.append(str(fp))

        # Compute elapsed from events if not already available
        elapsed = str(row.get("elapsed", ""))
        if not elapsed and spawn_ts and complete_ts:
            secs = int(complete_ts - spawn_ts)
            elapsed = f"{secs // 60}m{secs % 60:02d}s" if secs >= 60 else f"{secs}s"

        # Trace summary + task-level enrichment
        trace_summary = self.build_agent_trace_summary(task_id) if task_id else {}
        task_data = self._read_task_cached(task_id) if task_id else {}
        cost_usd = trace_summary.get("total_cost", 0.0) or float(task_data.get("cost_usd", 0.0))
        result_summary = task_data.get("result_summary", "")

        return {
            "kind": "agent",
            "agent_id": agent_id,
            "status": str(row.get("status", "")),
            "task_id": task_id,
            "task_title": task_title,
            "backend": str(row.get("backend", "")),
            "model": str(row.get("model", row.get("backend", ""))),
            "role_type": str(row.get("role_type", "")),
            "execution_mode": str(row.get("execution_mode", "")),
            "tokens_used": int(row.get("tokens_used", 0)),
            "elapsed": elapsed,
            "result": result_msg,
            "files_modified": files,
            "cwd": str(row.get("cwd", "")),
            "exit_code": row.get("exit_code"),
            "restart_count": int(row.get("restart_count", 0)),
            "stderr_tail": str(row.get("stderr_tail", "")),
            "trace_summary": trace_summary,
            "cost_usd": cost_usd,
            "result_summary": result_summary,
        }

    # ── Activity sidecar helpers ─────────────────────────────────

    def read_activity_sidecars(self) -> dict[str, str]:
        """Scan agents/*.activity.txt and return {task_id: label} with 1s TTL cache."""
        now = time.time()
        cached = getattr(self, "_sidecar_cache", None)
        if cached and now - cached[0] < 3.0:
            return cached[1]

        agents_dir = self.run_dir / "agents"
        result: dict[str, str] = {}
        if agents_dir.exists():
            for p in agents_dir.iterdir():
                if p.name.endswith(".activity.txt"):
                    # agent-{task_id}.activity.txt
                    task_id = p.name.replace("agent-", "").replace(".activity.txt", "")
                    try:
                        label = p.read_text(encoding="utf-8").strip()
                        if label:
                            result[task_id] = label
                    except Exception:
                        pass

        self._sidecar_cache = (now, result)
        return result

    # ── Trace summary helpers ──────────────────────────────────────

    def build_agent_trace_summary(self, task_id: str) -> dict[str, Any]:
        """Summarise last 50 lines of agent-{task_id}.trace.jsonl.

        Returns tool_calls, tool_counts, files_written, error_count,
        last_error, llm_call_count, total_cost.  Cached with 3s TTL.
        """
        now = time.time()
        cache_key = f"_trace_summary_{task_id}"
        cached = getattr(self, cache_key, None)
        if cached and now - cached[0] < 3.0:
            return cached[1]

        empty: dict[str, Any] = {
            "tool_calls": [],
            "tool_counts": {},
            "files_written": [],
            "error_count": 0,
            "last_error": "",
            "llm_call_count": 0,
            "total_cost": 0.0,
        }

        trace_path = self.run_dir / "agents" / f"agent-{task_id}.trace.jsonl"
        if not trace_path.exists():
            setattr(self, cache_key, (now, empty))
            return empty

        # Read last ~8KB to get roughly 50 entries without reading whole file
        try:
            size = trace_path.stat().st_size
            read_from = max(0, size - 8192)
            lines: list[dict[str, Any]] = []
            with trace_path.open("rb") as f:
                if read_from > 0:
                    f.seek(read_from)
                    f.readline()  # discard partial line
                for raw in f:
                    try:
                        entry = json.loads(raw)
                        if isinstance(entry, dict):
                            lines.append(entry)
                    except json.JSONDecodeError:
                        continue
            lines = lines[-50:]
        except Exception:
            setattr(self, cache_key, (now, empty))
            return empty

        tool_counts: dict[str, int] = {}
        files_written: list[str] = []
        error_count = 0
        last_error = ""
        llm_call_count = 0
        total_cost = 0.0

        for entry in lines:
            etype = entry.get("type", entry.get("event_type", ""))

            # Tool calls
            tool = entry.get("tool", "") or entry.get("tool_name", "")
            if tool:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

            # File writes
            if etype in ("file_write", "file.written", "task.files_changed"):
                fp = entry.get("file", "") or entry.get("path", "")
                if fp:
                    basename = str(fp).rsplit("/", 1)[-1]
                    if basename and basename not in files_written:
                        files_written.append(basename)
                for fp2 in entry.get("files", []):
                    basename2 = str(fp2).rsplit("/", 1)[-1]
                    if basename2 and basename2 not in files_written:
                        files_written.append(basename2)

            # Errors
            if etype in ("error", "tool_error", "agent_error"):
                error_count += 1
                msg = str(entry.get("message", entry.get("error", "")))[:80]
                if msg:
                    last_error = msg

            # LLM calls
            if etype in ("llm_call", "llm.response", "llm_response"):
                llm_call_count += 1
                total_cost += float(entry.get("cost_usd", entry.get("cost", 0)) or 0)

        # Build deduplicated recent-first tool list
        seen_tools: list[str] = []
        for entry in reversed(lines):
            tool = entry.get("tool", "") or entry.get("tool_name", "")
            if tool and tool not in seen_tools:
                seen_tools.append(tool)

        result: dict[str, Any] = {
            "tool_calls": seen_tools,
            "tool_counts": tool_counts,
            "files_written": files_written,
            "error_count": error_count,
            "last_error": last_error,
            "llm_call_count": llm_call_count,
            "total_cost": total_cost,
        }
        setattr(self, cache_key, (now, result))
        return result

    # ── Transparency helpers (Workstream 2) ───────────────────────

    def read_agent_trace(self, task_id: str) -> list[dict[str, Any]]:
        """Read agent trace JSONL file incrementally.

        Returns new entries since last call for this task_id.
        """
        trace_path = self.run_dir / "agents" / f"agent-{task_id}.trace.jsonl"
        if not trace_path.exists():
            return []

        cache_key = f"_trace_offset_{task_id}"
        last_offset = getattr(self, cache_key, 0)

        entries: list[dict[str, Any]] = []
        try:
            size = trace_path.stat().st_size
            if size <= last_offset:
                return []

            with trace_path.open("rb") as f:
                f.seek(last_offset)
                for line in f:
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, dict):
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
                setattr(self, cache_key, f.tell())
        except Exception:
            pass

        return entries

    _SUGGESTION_MAP: dict[str, str] = {
        "timeout": "Increase task timeout or split into smaller subtasks.",
        "budget": "Increase budget limit or reduce task scope.",
        "crash": "Check worker logs for stack trace.",
        "dep_failure": "Fix upstream dependency first.",
        "coordination": "Reduce file overlap between parallel tasks.",
        "agent_error": "Review task prompt for clarity.",
        "quality": "Relax quality threshold or add more context to task.",
        "token_limit": "Split task into smaller subtasks to reduce token usage.",
    }

    def build_failure_chain(
        self,
        state: dict[str, Any],
        events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build failure chain data from events for FailureChainWidget."""
        if events is None:
            events = self.read_events(limit=500)
        failures: list[dict[str, Any]] = []

        for ev in events:
            etype = str(ev.get("type", ev.get("event_type", "")))
            if etype not in ("fail", "task.failed"):
                continue

            data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
            failure_data = data.get("failure", {})

            task_id = str(ev.get("task_id", "") or data.get("task_id", ""))
            cause = failure_data.get("cause", "agent_error")
            suggestion = failure_data.get("suggestion", "")
            if not suggestion:
                suggestion = self._SUGGESTION_MAP.get(cause, "")
            failures.append({
                "task_id": task_id,
                "cause": cause,
                "confidence": failure_data.get("confidence", 0.0),
                "evidence": failure_data.get("evidence", str(ev.get("message", ""))[:200]),
                "chain": failure_data.get("chain", [task_id]),
                "suggestion": suggestion,
            })

        return failures

    def build_decision_list(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract decisions from state for DecisionsPane."""
        return state.get("decisions", [])

    def build_conflict_list(
        self,
        state: dict[str, Any],
        events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build conflict list from events for ConflictPanel."""
        if events is None:
            events = self.read_events(limit=500)
        conflicts: list[dict[str, Any]] = []

        for ev in events:
            etype = str(ev.get("type", ev.get("event_type", "")))
            if etype not in ("conflict", "conflict.detected"):
                continue
            data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
            conflicts.append({
                "file_path": data.get("file_path", ""),
                "task_a": data.get("task_a", ""),
                "task_b": data.get("task_b", ""),
                "symbol_name": data.get("symbol_name", ""),
                "resolution": data.get("resolution", ""),
                "strategy": data.get("strategy", ""),
                "blast_radius_files": data.get("blast_radius_files", []),
            })

        return conflicts

    def list_history(self) -> list[dict[str, Any]]:
        """List archived runs from history/ dir."""
        history_dir = self.run_dir / "history"
        if not history_dir.is_dir():
            return []
        runs: list[dict[str, Any]] = []
        for entry in sorted(history_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            state_path = entry / "swarm.state.json"
            state = read_json(state_path, default={}) if state_path.exists() else {}
            manifest_path = entry / "swarm.manifest.json"
            manifest = read_json(manifest_path, default={}) if manifest_path.exists() else {}
            lineage = manifest.get("lineage", state.get("lineage", {}))
            if not isinstance(lineage, dict):
                lineage = {}
            runs.append({
                "run_id": entry.name,
                "goal": manifest.get("goal", state.get("goal", "")),
                "phase": state.get("phase", "unknown"),
                "task_count": len(manifest.get("tasks", [])),
                "continuation_mode": lineage.get("continuation_mode", ""),
                "parent_run_id": lineage.get("parent_run_id", ""),
                "path": str(entry),
            })
        return runs
