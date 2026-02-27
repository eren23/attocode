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
        self._cache_ttl = 2.0

    def read_state(self) -> dict[str, Any]:
        return read_json(self.state_path, default={})

    def read_events(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        out: list[dict[str, Any]] = []
        lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-max(limit, 1):]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

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

    def build_agent_list(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Transform active_agents into AgentGrid-compatible format."""
        now = time.time()

        # Build task_id -> title lookup from DAG
        title_map: dict[str, str] = {}
        for node in state.get("dag", {}).get("nodes", []):
            title_map[str(node.get("task_id", ""))] = str(node.get("title", ""))

        out: list[dict[str, Any]] = []
        for row in state.get("active_agents", []):
            task_id = str(row.get("task_id", ""))
            started = row.get("started_at_epoch", 0)
            if started and isinstance(started, (int, float)):
                secs = int(now - started)
                elapsed = f"{secs // 60}m{secs % 60:02d}s"
            else:
                elapsed = ""
            out.append({
                "agent_id": str(row.get("agent_id", "?")),
                "status": str(row.get("status", "idle")),
                "task_id": task_id,
                "model": str(row.get("backend", row.get("model", ""))),
                "tokens_used": int(row.get("tokens_used", 0)),
                "elapsed": elapsed,
                "task_title": str(row.get("task_title", "")) or title_map.get(task_id, ""),
            })
        return out

    def build_task_list(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Transform dag.nodes into TaskBoard-compatible format."""
        dag = state.get("dag", {})
        nodes = dag.get("nodes", [])
        edges = dag.get("edges", [])
        # Build reverse lookup: target -> [source]
        deps_map = self._parse_edges(edges)

        attempts = state.get("attempts", {})
        by_task = attempts.get("by_task", {}) if isinstance(attempts, dict) else {}

        out: list[dict[str, Any]] = []
        for node in nodes:
            task_id = str(node.get("task_id", ""))
            detail = self._read_task_cached(task_id)
            out.append({
                "task_id": task_id,
                "title": str(node.get("title", detail.get("title", ""))),
                "status": str(node.get("status", "pending")),
                "task_kind": str(detail.get("task_kind", "")),
                "role_hint": str(detail.get("role_hint", "")),
                "attempts": int(by_task.get(task_id, detail.get("attempts", 0))),
                "depends_on": deps_map.get(task_id, []),
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

        out: list[dict[str, Any]] = []
        for node in nodes:
            tid = str(node.get("task_id", ""))
            out.append({
                "task_id": tid,
                "status": str(node.get("status", "pending")),
                "depends_on": deps_map.get(tid, []),
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
                    from datetime import datetime, timezone
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

    def build_task_detail(
        self, task_id: str, state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build DetailInspector-compatible dict for a task.

        Tries the per-task JSON file first; falls back to reconstructing
        from the DAG + event log when the file doesn't exist.
        """
        task = self.read_task(task_id)
        if task:
            return {
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
            }

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

        return {
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

        return {
            "kind": "agent",
            "agent_id": agent_id,
            "status": str(row.get("status", "")),
            "task_id": task_id,
            "task_title": task_title,
            "model": str(row.get("backend", row.get("model", ""))),
            "tokens_used": int(row.get("tokens_used", 0)),
            "elapsed": elapsed,
            "result": result_msg,
            "files_modified": files,
        }
