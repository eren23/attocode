"""Swarm event bridge -- persists events and maintains live state for TUI/dashboard.

Subscribes to swarm orchestrator events and:
1. Appends every event to an append-only JSONL file (events.jsonl)
2. Accumulates state into an in-memory snapshot for live queries
3. Writes rate-limited state.json and per-task detail files for TUI consumption
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from typing import IO, Any, Callable

from attocode.integrations.swarm.types import (
    ArtifactInventory,
    ModelHealthRecord,
    OrchestratorDecision,
    SwarmEvent,
    SwarmPhase,
    SwarmQueueStats,
    SwarmStatus,
    SwarmTask,
    SwarmTaskStatus,
    SwarmWorkerStatus,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class SwarmEventBridge:
    """Accumulates swarm events and persists them for TUI and dashboard consumption.

    The bridge maintains an in-memory snapshot of the swarm state that is
    continuously updated as events arrive.  It also writes:
    - ``events.jsonl`` -- append-only event log
    - ``state.json`` -- rate-limited snapshot of accumulated state
    - ``tasks/<task_id>.json`` -- per-task detail files
    - ``codemap.json``, ``blackboard.json``, ``budget-pool.json`` -- auxiliary snapshots
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        output_dir: str = ".agent/swarm-live",
        max_lines: int = 5000,
        max_state_writes_per_sec: int = 5,
    ) -> None:
        self._output_dir = output_dir
        self._max_lines = max_lines
        self._seq: int = 0

        # File handle
        self._events_file: IO[str] | None = None

        # Accumulated state
        self._tasks: dict[str, SwarmTask] = {}
        self._edges: list[tuple[str, str]] = []
        self._last_status: SwarmStatus | None = None
        self._timeline: list[dict[str, Any]] = []
        self._errors: list[dict[str, Any]] = []
        self._decisions: list[OrchestratorDecision] = []
        self._model_health: list[ModelHealthRecord] = []
        self._config_snapshot: dict[str, Any] = {}
        self._plan: dict[str, Any] | None = None
        self._verification: VerificationResult | None = None
        self._artifact_inventory: ArtifactInventory | None = None
        self._worker_log_files: list[str] = []

        # Quality / wave / hollow tracking
        self._quality_results: dict[str, dict[str, Any]] = {}
        self._wave_reviews: list[dict[str, Any]] = []
        self._quality_rejections: int = 0
        self._total_retries: int = 0
        self._hollow_streak: int = 0
        self._total_dispatches: int = 0
        self._total_hollows: int = 0

        # Rate-limiting for state writes
        self._pending_write: asyncio.TimerHandle | None = None
        self._min_state_interval: float = (
            1.0 / max_state_writes_per_sec if max_state_writes_per_sec > 0 else 0.2
        )
        self._last_state_write: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attach(self, orchestrator: Any) -> Callable[[], None]:
        """Subscribe to an orchestrator's event stream.

        Args:
            orchestrator: An object with an ``on(event_type, callback)`` method
                or a ``subscribe(callback)`` method.

        Returns:
            An unsubscribe callable that detaches the bridge.
        """
        self._ensure_output_dir()

        # Open events file in append mode
        events_path = os.path.join(self._output_dir, "events.jsonl")
        self._events_file = open(events_path, "a", encoding="utf-8")  # noqa: SIM115

        # Try subscribe(callback) first, then on("*", callback)
        if hasattr(orchestrator, "subscribe"):
            unsub = orchestrator.subscribe(self._handle_event)
            return self._make_unsubscribe(unsub)
        elif hasattr(orchestrator, "on"):
            unsub = orchestrator.on("*", self._handle_event)
            return self._make_unsubscribe(unsub)
        else:
            logger.warning(
                "Orchestrator has no subscribe/on method; bridge not attached"
            )
            return lambda: None

    def set_tasks(self, tasks: list[SwarmTask]) -> None:
        """Initialize the task map and edge list after decomposition.

        Called when ``swarm.tasks.loaded`` fires or directly by the
        orchestrator after decomposition completes.
        """
        self._tasks.clear()
        self._edges.clear()

        for task in tasks:
            self._tasks[task.id] = task
            for dep_id in task.dependencies or []:
                self._edges.append((dep_id, task.id))

        self._schedule_state_write()

    def write_code_map_snapshot(self, data: dict[str, Any]) -> None:
        """Write codemap.json to the output directory."""
        self._write_json_file("codemap.json", data)

    def write_blackboard_snapshot(self, data: dict[str, Any]) -> None:
        """Write blackboard.json to the output directory."""
        self._write_json_file("blackboard.json", data)

    def write_budget_pool_snapshot(self, data: dict[str, Any]) -> None:
        """Write budget-pool.json to the output directory."""
        self._write_json_file("budget-pool.json", data)

    def get_live_state(self) -> dict[str, Any]:
        """Return the current accumulated state snapshot.

        This is the same data that is written to state.json, suitable for
        serving over an API or reading from the TUI.
        """
        return self._build_state_dict()

    def close(self) -> None:
        """Cancel pending writes, flush final state, and close the events file."""
        # Cancel any pending debounced write
        if self._pending_write is not None:
            self._pending_write.cancel()
            self._pending_write = None

        # Final state write
        try:
            self._write_state()
        except Exception:
            logger.debug("Failed to write final state on close", exc_info=True)

        # Close events file
        if self._events_file is not None:
            try:
                self._events_file.close()
            except Exception:
                logger.debug("Failed to close events file", exc_info=True)
            self._events_file = None

    # ------------------------------------------------------------------
    # Event Handler
    # ------------------------------------------------------------------

    def _handle_event(self, event: SwarmEvent) -> None:
        """Main event handler.  Dispatches to type-specific handlers."""
        self._seq += 1

        # Append to JSONL log
        self._append_event_to_file(event)

        event_type = event.type
        data = event.data

        if event_type == "swarm.start":
            self._on_start(data)
        elif event_type == "swarm.tasks.loaded":
            self._on_tasks_loaded(data)
        elif event_type == "swarm.task.dispatched":
            self._on_task_dispatched(data)
            self._total_dispatches += 1
        elif event_type == "swarm.task.completed":
            self._on_task_completed(data)
            attempt = data.get("attempt", 1)
            if attempt > 1:
                self._total_retries += attempt - 1
        elif event_type == "swarm.task.failed":
            self._on_task_failed(data)
            attempt = data.get("attempt", 1)
            if attempt > 1:
                self._total_retries += attempt - 1
        elif event_type == "swarm.task.skipped":
            self._on_task_skipped(data)
        elif event_type == "swarm.complete":
            self._on_complete(data)
        elif event_type == "swarm.budget.update":
            self._append_timeline(event)
        elif event_type == "swarm.model.health":
            self._on_model_health(data)
        elif event_type == "swarm.orchestrator.decision":
            self._on_decision(data)
        elif event_type == "swarm.error":
            self._on_error(data)
        elif event_type == "swarm.hollow_detected":
            self._on_hollow_detected(data)
        elif event_type == "swarm.wave.review":
            self._on_wave_review(data)
        elif event_type == "swarm.quality.result":
            self._on_quality_result(data)
        elif event_type == "swarm.quality.rejected":
            self._quality_rejections += 1
            self._append_timeline(event)
        elif event_type == "swarm.model.failover":
            self._append_timeline(event)
        elif event_type == "swarm.task.attempt":
            self._append_timeline(event)
        else:
            # Generic timeline entry for all other events
            self._append_timeline(event)

        self._schedule_state_write()

    # ------------------------------------------------------------------
    # Type-Specific Handlers
    # ------------------------------------------------------------------

    def _on_start(self, data: dict[str, Any]) -> None:
        """Reset all accumulated state on swarm start."""
        self._tasks.clear()
        self._edges.clear()
        self._timeline.clear()
        self._errors.clear()
        self._decisions.clear()
        self._model_health.clear()
        self._worker_log_files.clear()
        self._plan = None
        self._verification = None
        self._artifact_inventory = None
        self._quality_results.clear()
        self._wave_reviews.clear()
        self._quality_rejections = 0
        self._total_retries = 0
        self._hollow_streak = 0
        self._total_dispatches = 0
        self._total_hollows = 0
        self._seq = 1

        self._last_status = SwarmStatus(phase=SwarmPhase.DECOMPOSING)
        self._config_snapshot = data.get("config", {})

    def _on_tasks_loaded(self, data: dict[str, Any]) -> None:
        """Handle decomposition result -- populate task map."""
        tasks_raw = data.get("tasks", [])
        tasks: list[SwarmTask] = []

        for t in tasks_raw:
            if isinstance(t, SwarmTask):
                tasks.append(t)
            elif isinstance(t, dict):
                # Minimal conversion from dict
                task = SwarmTask(
                    id=t.get("id", ""),
                    description=t.get("description", ""),
                )
                task.type = t.get("type", task.type)
                task.complexity = t.get("complexity", 5)
                task.dependencies = t.get("dependencies", [])
                task.wave = t.get("wave", 0)
                task.status = SwarmTaskStatus(t.get("status", "pending"))
                task.target_files = t.get("target_files")
                task.is_foundation = t.get("is_foundation", False)
                tasks.append(task)

        self.set_tasks(tasks)

        if self._last_status:
            self._last_status.phase = SwarmPhase.SCHEDULING
            self._last_status.queue.total = len(tasks)

        self._plan = data.get("plan")

    def _on_task_dispatched(self, data: dict[str, Any]) -> None:
        """Update task state to dispatched."""
        task_id = data.get("task_id", "")
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.DISPATCHED
            task.dispatched_at = time.time()
            task.assigned_model = data.get("model")
            self._write_task_detail(task_id, data)

        if self._last_status:
            self._last_status.phase = SwarmPhase.EXECUTING
            worker_status = SwarmWorkerStatus(
                task_id=task_id,
                task_description=data.get("description", task.description if task else ""),
                model=data.get("model", ""),
                worker_name=data.get("worker_name", ""),
                elapsed_ms=0.0,
                started_at=time.time(),
            )
            self._last_status.active_workers.append(worker_status)
            self._last_status.current_wave = data.get(
                "wave", self._last_status.current_wave
            )
            self._update_queue_stats()

    def _on_task_completed(self, data: dict[str, Any]) -> None:
        """Update task state to completed."""
        task_id = data.get("task_id", "")
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.COMPLETED
            task.degraded = data.get("degraded", False)
            self._write_task_detail(task_id, data)

        if self._last_status:
            self._last_status.active_workers = [
                w for w in self._last_status.active_workers if w.task_id != task_id
            ]
            self._update_queue_stats()

        # Track worker log files
        log_file = data.get("log_file")
        if log_file and log_file not in self._worker_log_files:
            self._worker_log_files.append(log_file)

    def _on_task_failed(self, data: dict[str, Any]) -> None:
        """Update task state to failed."""
        task_id = data.get("task_id", "")
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.FAILED
            task.failure_mode = data.get("failure_mode")
            self._write_task_detail(task_id, data)

        if self._last_status:
            self._last_status.active_workers = [
                w for w in self._last_status.active_workers if w.task_id != task_id
            ]
            self._update_queue_stats()

        # Record as error
        self._errors.append(
            {
                "timestamp": time.time(),
                "task_id": task_id,
                "error": data.get("error", "unknown"),
                "failure_mode": data.get("failure_mode"),
            }
        )
        if len(self._errors) > 100:
            self._errors = self._errors[-100:]

    def _on_task_skipped(self, data: dict[str, Any]) -> None:
        """Update task state to skipped."""
        task_id = data.get("task_id", "")
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.SKIPPED
            self._write_task_detail(task_id, data)

        if self._last_status:
            self._update_queue_stats()

    def _on_complete(self, data: dict[str, Any]) -> None:
        """Handle swarm completion."""
        if self._last_status:
            self._last_status.phase = SwarmPhase.COMPLETED
            self._last_status.active_workers = []
            self._update_queue_stats()

        # Store final artifacts
        artifact_inv = data.get("artifact_inventory")
        if artifact_inv is not None:
            if isinstance(artifact_inv, ArtifactInventory):
                self._artifact_inventory = artifact_inv
            elif isinstance(artifact_inv, dict):
                self._artifact_inventory = ArtifactInventory(
                    total_files=artifact_inv.get("total_files", 0),
                    total_bytes=artifact_inv.get("total_bytes", 0),
                )

        verification = data.get("verification")
        if verification is not None:
            if isinstance(verification, VerificationResult):
                self._verification = verification

        # Cancel any pending debounced writes and do a final immediate write
        if self._pending_write is not None:
            self._pending_write.cancel()
            self._pending_write = None
        self._write_state()

    def _on_model_health(self, data: dict[str, Any]) -> None:
        """Upsert model health record."""
        model = data.get("model", "")
        if not model:
            return

        # Find existing or create new
        existing = next((h for h in self._model_health if h.model == model), None)
        if existing is not None:
            existing.successes = data.get("successes", existing.successes)
            existing.failures = data.get("failures", existing.failures)
            existing.rate_limits = data.get("rate_limits", existing.rate_limits)
            existing.last_rate_limit = data.get("last_rate_limit", existing.last_rate_limit)
            existing.average_latency_ms = data.get("average_latency_ms", existing.average_latency_ms)
            existing.healthy = data.get("healthy", existing.healthy)
            existing.quality_rejections = data.get("quality_rejections", existing.quality_rejections)
            existing.success_rate = data.get("success_rate", existing.success_rate)
        else:
            self._model_health.append(
                ModelHealthRecord(
                    model=model,
                    successes=data.get("successes", 0),
                    failures=data.get("failures", 0),
                    rate_limits=data.get("rate_limits", 0),
                    last_rate_limit=data.get("last_rate_limit"),
                    average_latency_ms=data.get("average_latency_ms", 0.0),
                    healthy=data.get("healthy", True),
                    quality_rejections=data.get("quality_rejections", 0),
                    success_rate=data.get("success_rate", 1.0),
                )
            )

    def _on_decision(self, data: dict[str, Any]) -> None:
        """Record an orchestrator decision."""
        decision = OrchestratorDecision(
            timestamp=data.get("timestamp", time.time()),
            phase=data.get("phase", ""),
            decision=data.get("decision", ""),
            reasoning=data.get("reasoning", ""),
        )
        self._decisions.append(decision)
        if len(self._decisions) > 100:
            self._decisions = self._decisions[-100:]

    def _on_error(self, data: dict[str, Any]) -> None:
        """Record a swarm error."""
        self._errors.append(
            {
                "timestamp": data.get("timestamp", time.time()),
                "phase": data.get("phase", ""),
                "message": data.get("message", ""),
                "task_id": data.get("task_id"),
            }
        )
        if len(self._errors) > 100:
            self._errors = self._errors[-100:]

    def _on_hollow_detected(self, data: dict[str, Any]) -> None:
        """Increment hollow streak and total hollows."""
        self._hollow_streak += 1
        self._total_hollows += 1
        self._append_timeline(SwarmEvent(type="swarm.hollow_detected", data=data))

    def _on_wave_review(self, data: dict[str, Any]) -> None:
        """Append a wave review assessment."""
        self._wave_reviews.append({
            "timestamp": time.time(),
            "wave": data.get("wave"),
            "assessment": data.get("assessment", ""),
            "task_assessments": data.get("task_assessments", []),
            "fixup_count": data.get("fixup_count", 0),
        })
        if len(self._wave_reviews) > 50:
            self._wave_reviews = self._wave_reviews[-50:]

    def _on_quality_result(self, data: dict[str, Any]) -> None:
        """Store a per-task quality gate result."""
        task_id = data.get("task_id", "")
        if task_id:
            self._quality_results[task_id] = {
                "score": data.get("score"),
                "feedback": data.get("feedback", ""),
                "passed": data.get("passed", False),
                "artifact_auto_fail": data.get("artifact_auto_fail", False),
            }
        if not data.get("passed", True):
            self._quality_rejections += 1

    # ------------------------------------------------------------------
    # State Writing (Rate-Limited)
    # ------------------------------------------------------------------

    def _schedule_state_write(self) -> None:
        """Schedule a rate-limited state.json write.

        If a write is already pending, skip.  Otherwise, schedule one
        after ``_min_state_interval`` seconds.
        """
        if self._pending_write is not None:
            return  # Already scheduled

        now = time.time()
        elapsed = now - self._last_state_write
        if elapsed >= self._min_state_interval:
            # Enough time has passed -- write immediately
            self._write_state()
            return

        # Schedule a deferred write
        delay = self._min_state_interval - elapsed
        try:
            loop = asyncio.get_running_loop()
            self._pending_write = loop.call_later(delay, self._execute_deferred_write)
        except RuntimeError:
            # No running event loop -- write synchronously
            self._write_state()

    def _execute_deferred_write(self) -> None:
        """Callback for the deferred state write timer."""
        self._pending_write = None
        self._write_state()

    def _write_state(self) -> None:
        """Write the current accumulated state to state.json."""
        self._last_state_write = time.time()
        state_dict = self._build_state_dict()

        path = os.path.join(self._output_dir, "state.json")
        try:
            self._ensure_output_dir()
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, default=_json_default, indent=None)
            os.replace(tmp_path, path)
        except Exception:
            logger.debug("Failed to write state.json", exc_info=True)

    def _build_state_dict(self) -> dict[str, Any]:
        """Build the full state snapshot dictionary."""
        tasks_dict: dict[str, Any] = {}
        for tid, task in self._tasks.items():
            tasks_dict[tid] = {
                "id": task.id,
                "description": task.description,
                "type": task.type.value if hasattr(task.type, "value") else str(task.type),
                "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "complexity": task.complexity,
                "wave": task.wave,
                "assigned_model": task.assigned_model,
                "is_foundation": task.is_foundation,
                "attempts": task.attempts,
                "degraded": task.degraded,
                "dependencies": task.dependencies or [],
                "target_files": task.target_files or [],
                "read_files": task.read_files or [],
                "failure_mode": (
                    task.failure_mode.value
                    if hasattr(task.failure_mode, "value")
                    else str(task.failure_mode)
                ) if task.failure_mode else None,
                "quality_score": (
                    task.result.quality_score if task.result else None
                ),
            }
            # Enrich with result data when available
            if task.result:
                tasks_dict[tid]["output"] = (task.result.output or "")[:500]
                tasks_dict[tid]["files_modified"] = task.result.files_modified
                tasks_dict[tid]["cost_used"] = task.result.cost_used
                tasks_dict[tid]["duration_ms"] = task.result.duration_ms
                tasks_dict[tid]["tool_calls"] = task.result.tool_calls
                tasks_dict[tid]["tokens_used"] = task.result.tokens_used

        status_dict: dict[str, Any] = {}
        if self._last_status:
            status_dict = {
                "phase": self._last_status.phase.value,
                "current_wave": self._last_status.current_wave,
                "total_waves": self._last_status.total_waves,
                "active_workers": [asdict(w) for w in self._last_status.active_workers],
                "queue": {
                    "ready": self._last_status.queue.ready,
                    "running": self._last_status.queue.running,
                    "completed": self._last_status.queue.completed,
                    "failed": self._last_status.queue.failed,
                    "skipped": self._last_status.queue.skipped,
                    "total": self._last_status.queue.total,
                },
                "budget": {
                    "tokens_used": self._last_status.budget.tokens_used,
                    "tokens_total": self._last_status.budget.tokens_total,
                    "cost_used": self._last_status.budget.cost_used,
                    "cost_total": self._last_status.budget.cost_total,
                },
                "orchestrator": {
                    "tokens": self._last_status.orchestrator.tokens,
                    "cost": self._last_status.orchestrator.cost,
                    "calls": self._last_status.orchestrator.calls,
                },
            }

        return {
            "seq": self._seq,
            "timestamp": time.time(),
            "status": status_dict,
            "tasks": tasks_dict,
            "edges": [{"source": s, "target": t} for s, t in self._edges],
            "timeline": self._timeline[-200:],
            "errors": self._errors[-100:],
            "decisions": [
                {
                    "timestamp": d.timestamp,
                    "phase": d.phase,
                    "decision": d.decision,
                    "reasoning": d.reasoning,
                }
                for d in self._decisions[-100:]
            ],
            "model_health": [
                {
                    "model": h.model,
                    "successes": h.successes,
                    "failures": h.failures,
                    "rate_limits": h.rate_limits,
                    "healthy": h.healthy,
                    "success_rate": h.success_rate,
                    "average_latency_ms": h.average_latency_ms,
                }
                for h in self._model_health
            ],
            "config": self._config_snapshot,
            "plan": self._plan,
            "verification": asdict(self._verification) if self._verification else None,
            "artifact_inventory": (
                asdict(self._artifact_inventory) if self._artifact_inventory else None
            ),
            "worker_log_files": self._worker_log_files,
            "quality_stats": {
                "total_rejections": self._quality_rejections,
                "total_retries": self._total_retries,
                "hollow_streak": self._hollow_streak,
                "total_dispatches": self._total_dispatches,
                "total_hollows": self._total_hollows,
            },
            "wave_reviews": self._wave_reviews[-50:],
            "quality_results": self._quality_results,
        }

    # ------------------------------------------------------------------
    # Per-Task Detail
    # ------------------------------------------------------------------

    def _write_task_detail(self, task_id: str, data: dict[str, Any]) -> None:
        """Write a per-task JSON detail file."""
        tasks_dir = os.path.join(self._output_dir, "tasks")
        try:
            os.makedirs(tasks_dir, exist_ok=True)
            # Sanitize task_id for filesystem
            safe_id = task_id.replace("/", "_").replace("\\", "_")
            path = os.path.join(tasks_dir, f"{safe_id}.json")

            task = self._tasks.get(task_id)
            detail: dict[str, Any] = dict(data)
            if task:
                detail["current_status"] = (
                    task.status.value
                    if hasattr(task.status, "value")
                    else str(task.status)
                )
                detail["attempts"] = task.attempts
                detail["assigned_model"] = task.assigned_model
                detail["degraded"] = task.degraded

            with open(path, "w", encoding="utf-8") as f:
                json.dump(detail, f, default=_json_default, indent=2)
        except Exception:
            logger.debug("Failed to write task detail for %s", task_id, exc_info=True)

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def _append_timeline(self, event: SwarmEvent) -> None:
        """Add a timeline entry from an event, trimming to 200 entries."""
        entry: dict[str, Any] = {
            "seq": self._seq,
            "timestamp": time.time(),
            "type": event.type,
        }
        # Include select data fields
        for key in (
            "task_id", "wave", "model", "reason", "phase", "message",
            "score", "feedback", "passed", "success", "duration_ms",
            "tool_calls", "from_model", "to_model", "failure_mode",
            "attempt", "output", "files_modified", "session_id",
            "num_turns", "stderr", "tokens_used", "cost_used",
        ):
            if key in event.data:
                entry[key] = event.data[key]

        self._timeline.append(entry)
        if len(self._timeline) > 200:
            self._timeline = self._timeline[-200:]

    # ------------------------------------------------------------------
    # Queue Stats
    # ------------------------------------------------------------------

    def _update_queue_stats(self) -> None:
        """Recalculate queue statistics from the task map."""
        if not self._last_status:
            return

        q = self._last_status.queue
        q.ready = 0
        q.running = 0
        q.completed = 0
        q.failed = 0
        q.skipped = 0
        q.total = len(self._tasks)

        for task in self._tasks.values():
            if task.status in (SwarmTaskStatus.PENDING, SwarmTaskStatus.READY):
                q.ready += 1
            elif task.status == SwarmTaskStatus.DISPATCHED:
                q.running += 1
            elif task.status == SwarmTaskStatus.COMPLETED:
                q.completed += 1
            elif task.status == SwarmTaskStatus.FAILED:
                q.failed += 1
            elif task.status in (SwarmTaskStatus.SKIPPED, SwarmTaskStatus.DECOMPOSED):
                q.skipped += 1

    # ------------------------------------------------------------------
    # File I/O Helpers
    # ------------------------------------------------------------------

    def _ensure_output_dir(self) -> None:
        """Create the output directory if it doesn't exist."""
        os.makedirs(self._output_dir, exist_ok=True)

    def _append_event_to_file(self, event: SwarmEvent) -> None:
        """Append a single event as a JSON line to events.jsonl."""
        if self._events_file is None:
            return

        try:
            line = json.dumps(
                {
                    "seq": self._seq,
                    "timestamp": time.time(),
                    "type": event.type,
                    "data": event.data,
                },
                default=_json_default,
            )
            self._events_file.write(line + "\n")
            self._events_file.flush()
        except Exception:
            logger.debug("Failed to append event to JSONL", exc_info=True)

    def _write_json_file(self, filename: str, data: dict[str, Any]) -> None:
        """Write an arbitrary JSON file to the output directory."""
        try:
            self._ensure_output_dir()
            path = os.path.join(self._output_dir, filename)
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, default=_json_default, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            logger.debug("Failed to write %s", filename, exc_info=True)

    def _make_unsubscribe(self, unsub: Any) -> Callable[[], None]:
        """Create an unsubscribe function that also closes the bridge."""

        def _unsub() -> None:
            if callable(unsub):
                unsub()
            self.close()

        return _unsub


# =============================================================================
# Module-Level Helpers
# =============================================================================


def _json_default(obj: Any) -> Any:
    """Default serializer for json.dump that handles dataclasses and enums."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
