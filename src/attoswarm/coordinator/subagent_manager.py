"""SubagentManager — semaphore-gated worker dispatch for shared workspace.

Manages the lifecycle of worker subagents:
1. Claims files via FileLedger before dispatching.
2. Uses an asyncio.Semaphore to cap concurrency.
3. Collects results and releases claims on completion.
4. Reports status changes to registered callbacks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from attoswarm.coordinator.concurrency import AdaptiveConcurrency

if TYPE_CHECKING:
    from collections.abc import Callable

    from attocode.integrations.context.ast_service import ASTService
    from attoswarm.coordinator.health_monitor import HealthMonitor
    from attoswarm.workspace.file_ledger import FileLedger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TaskResult:
    """Result of executing a single task."""

    task_id: str
    success: bool
    files_modified: list[str] = field(default_factory=list)
    result_summary: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    error: str = ""
    timed_out: bool = False
    near_timeout: bool = False


@dataclass(slots=True)
class AgentStatus:
    """Status snapshot of a worker agent."""

    agent_id: str
    task_id: str
    status: str             # "idle" | "claiming" | "running" | "done" | "error"
    started_at: float = 0.0
    tokens_used: int = 0
    backend: str = ""
    model: str = ""
    activity: str = ""      # human-readable current activity label
    tool_call_count: int = 0
    current_tool: str = ""        # e.g. "Edit", "Bash", "Read"
    files_touched: list[str] = field(default_factory=list)
    llm_turns: int = 0
    last_activity_ts: float = 0.0


# ---------------------------------------------------------------------------
# SubagentManager
# ---------------------------------------------------------------------------


class SubagentManager:
    """Semaphore-gated executor for parallel subagent tasks.

    ``execute_batch`` runs a list of tasks concurrently (up to
    ``max_concurrency``).  Each task goes through:

    1. Claim target files via FileLedger.
    2. Spawn a worker via the adapter registry.
    3. Collect the result.
    4. Release claims.

    The actual agent spawning is delegated to the ``spawn_fn`` callback,
    which should match the adapter interface.
    """

    def __init__(
        self,
        max_concurrency: int,
        file_ledger: FileLedger | None = None,
        ast_service: ASTService | None = None,
        spawn_fn: Callable[..., Any] | None = None,
        *,
        concurrency_floor: int = 1,
        concurrency_ceiling: int = 8,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._concurrency = AdaptiveConcurrency(
            initial=max_concurrency,
            floor=concurrency_floor,
            ceiling=concurrency_ceiling,
        )
        # Keep a plain semaphore reference for backward compat
        self._semaphore = self._concurrency
        self._file_ledger = file_ledger
        self._ast_service = ast_service
        self._spawn_fn = spawn_fn

        # Health monitor (set externally by orchestrator)
        self._health_monitor: HealthMonitor | None = None

        # Status tracking
        self._agent_statuses: dict[str, AgentStatus] = {}
        self._status_callbacks: list[Callable[[AgentStatus], Any]] = []

        # Process tracking for graceful shutdown
        self._active_processes: set[asyncio.subprocess.Process] = set()
        self._shutdown_requested: bool = False

        # Trace callback for per-agent trace streaming
        self._trace_callback: Callable[[dict[str, Any]], None] | None = None
        self._trace_dir: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_batch(
        self,
        tasks: list[dict[str, Any]],
        timeout: float = 600.0,
    ) -> list[TaskResult]:
        """Execute a batch of tasks concurrently (semaphore-gated).

        Each *task* dict must have at minimum:
        - ``task_id``: str
        - ``description``: str
        - ``target_files``: list[str]

        Optional keys: ``role``, ``model``, ``read_files``, ``file_version_snapshot``.
        """
        coros = [
            self._execute_one(task, timeout=timeout)
            for task in tasks
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        final: list[TaskResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(TaskResult(
                    task_id=tasks[i]["task_id"],
                    success=False,
                    error=str(r),
                ))
            else:
                final.append(r)
        return final

    async def execute_single(
        self,
        task: dict[str, Any],
        timeout: float = 600.0,
    ) -> TaskResult:
        """Execute a single task (still semaphore-gated)."""
        return await self._execute_one(task, timeout=timeout)

    def on_status_change(self, callback: Callable[[AgentStatus], Any]) -> None:
        """Register a callback for agent status changes."""
        self._status_callbacks.append(callback)

    def get_active_agents(self) -> list[AgentStatus]:
        """Return currently active agent statuses."""
        return [s for s in self._agent_statuses.values() if s.status == "running"]

    def get_all_agents(self) -> list[AgentStatus]:
        """Return all tracked agent statuses regardless of state."""
        return list(self._agent_statuses.values())

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def register_process(self, proc: asyncio.subprocess.Process) -> None:
        """Track an active subprocess for shutdown management."""
        self._active_processes.add(proc)

    def unregister_process(self, proc: asyncio.subprocess.Process) -> None:
        """Remove a completed subprocess from tracking."""
        self._active_processes.discard(proc)

    async def shutdown_all(self, timeout: float = 5.0) -> None:
        """Gracefully terminate all active subprocesses (SIGTERM -> wait -> SIGKILL)."""
        self._shutdown_requested = True
        if not self._active_processes:
            return

        procs = list(self._active_processes)
        logger.info("Shutting down %d active processes...", len(procs))

        # Phase 1: SIGTERM via process group (safe because start_new_session=True)
        for proc in procs:
            try:
                if proc.returncode is None:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

        # Phase 2: Wait up to timeout for graceful exit
        wait_time = min(timeout, 3.0)
        await asyncio.sleep(wait_time)

        # Phase 3: SIGKILL survivors
        for proc in procs:
            try:
                if proc.returncode is None:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

        self._active_processes.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute_one(
        self,
        task: dict[str, Any],
        timeout: float = 600.0,
    ) -> TaskResult:
        task_id = task["task_id"]
        agent_id = f"agent-{task_id}"
        target_files = task.get("target_files", [])
        task_backend = str(task.get("backend", ""))
        task_model = str(task.get("model", ""))

        async with self._concurrency:
            # Circuit breaker: skip dispatch if the model is tripped
            if self._health_monitor and task_model and self._health_monitor.check_circuit_breaker(task_model):
                logger.warning(
                    "Circuit breaker open for model %s — skipping task %s",
                    task_model,
                    task_id,
                )
                self._emit_status(agent_id, task_id, "error", backend=task_backend, model=task_model)
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    error=f"Circuit breaker open for model {task_model}",
                )

            start = time.time()

            # 1. Claim files
            self._emit_status(agent_id, task_id, "claiming", backend=task_backend, model=task_model)
            if self._file_ledger and target_files:
                for f in target_files:
                    ok = await self._file_ledger.claim_file(f, agent_id, task_id)
                    if not ok:
                        await self._file_ledger.release_all_claims(agent_id)
                        self._emit_status(agent_id, task_id, "error", backend=task_backend, model=task_model)
                        return TaskResult(
                            task_id=task_id,
                            success=False,
                            error=f"Could not claim file: {f}",
                        )

            # 1b. Start claim heartbeat (renew every 60s)
            heartbeat_task: asyncio.Task[None] | None = None
            if self._file_ledger and target_files:
                async def _heartbeat() -> None:
                    while True:
                        await asyncio.sleep(60.0)
                        for f in target_files:
                            try:
                                await self._file_ledger.renew_claim(f, agent_id)
                            except Exception as exc:
                                logger.debug("Claim heartbeat renewal failed for %s (agent %s): %s", f, agent_id, exc)
                heartbeat_task = asyncio.create_task(_heartbeat())

            # 2. Spawn worker
            self._emit_status(agent_id, task_id, "running", backend=task_backend, model=task_model)
            try:
                if self._spawn_fn:
                    result = await asyncio.wait_for(
                        self._spawn_fn(task),
                        timeout=timeout,
                    )
                else:
                    # No spawn function — return a stub result
                    result = TaskResult(
                        task_id=task_id,
                        success=True,
                        result_summary="(no spawn_fn configured — stub)",
                    )
            except TimeoutError:
                result = TaskResult(
                    task_id=task_id,
                    success=False,
                    error=f"Task timed out after {timeout}s",
                    timed_out=True,
                )
            except Exception as exc:
                result = TaskResult(
                    task_id=task_id,
                    success=False,
                    error=str(exc),
                )

            # 2b. Cancel heartbeat
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # 3. Release claims
            if self._file_ledger:
                await self._file_ledger.release_all_claims(agent_id)

            result.duration_s = time.time() - start

            # Near-timeout detection: task completed but used >90% of the timeout
            if not result.timed_out and result.duration_s >= timeout * 0.9:
                result.near_timeout = True
                logger.warning(
                    "Task %s near timeout: %.1fs elapsed of %.1fs limit (%.0f%%)",
                    task_id, result.duration_s, timeout,
                    (result.duration_s / timeout) * 100,
                )

            # Suspicious zero-token check
            if result.success and result.tokens_used == 0:
                logger.warning(
                    "Task %s reported success but tokens_used=0 — possible instrumentation gap",
                    task_id,
                )

            status = "done" if result.success else "error"
            self._emit_status(
                agent_id,
                task_id,
                status,
                tokens=result.tokens_used,
                backend=task_backend,
                model=task_model,
            )

            # Feed outcome to adaptive concurrency + health monitor
            if result.success:
                self._concurrency.on_success()
            elif "rate limit" in (result.error or "").lower() or "rate_limit" in (result.error or "").lower():
                self._concurrency.on_rate_limit()
            elif "timed out" in (result.error or "").lower() or "timeout" in (result.error or "").lower():
                self._concurrency.on_timeout()

            if self._health_monitor and task_model:
                outcome = "success" if result.success else "failure"
                if "rate limit" in (result.error or "").lower():
                    outcome = "rate_limit"
                elif "timed out" in (result.error or "").lower():
                    outcome = "timeout"
                self._health_monitor.record_outcome(
                    task_model, outcome, duration_s=result.duration_s,
                )

            # Write trace entry
            self._write_trace_entry(agent_id, task_id, "cost_delta" if result.success else "error", {
                "cost_usd": result.cost_usd,
                "tokens_used": result.tokens_used,
                "duration_s": result.duration_s,
                "files_modified": result.files_modified,
                "error": result.error or "",
                "timed_out": result.timed_out,
                "near_timeout": result.near_timeout,
            })

            return result

    def _emit_status(
        self,
        agent_id: str,
        task_id: str,
        status: str,
        tokens: int = 0,
        backend: str = "",
        model: str = "",
    ) -> None:
        existing = self._agent_statuses.get(agent_id)
        started = existing.started_at if existing and existing.started_at else time.time()
        s = AgentStatus(
            agent_id=agent_id,
            task_id=task_id,
            status=status,
            started_at=started,
            tokens_used=tokens,
            backend=backend or (existing.backend if existing else ""),
            model=model or (existing.model if existing else ""),
            activity=existing.activity if existing else "",
            tool_call_count=existing.tool_call_count if existing else 0,
            current_tool=existing.current_tool if existing else "",
            files_touched=list(existing.files_touched) if existing else [],
            llm_turns=existing.llm_turns if existing else 0,
            last_activity_ts=existing.last_activity_ts if existing else 0.0,
        )
        self._agent_statuses[agent_id] = s
        for cb in self._status_callbacks:
            try:
                cb(s)
            except Exception as exc:
                logger.debug("Status callback error: %s", exc)

    def _write_trace_entry(
        self,
        agent_id: str,
        task_id: str,
        entry_type: str,
        data: dict[str, Any],
    ) -> None:
        """Write a trace entry to the agent's trace JSONL file."""
        if not self._trace_dir:
            return
        import json as _json
        from pathlib import Path as _Path

        # Update in-memory activity label
        status = self._agent_statuses.get(agent_id)
        if status:
            if entry_type == "tool_call":
                status.activity = data.get("tool", data.get("name", "tool_call"))
            elif entry_type == "llm_request":
                status.activity = "thinking"
            elif entry_type == "llm_response":
                status.activity = "processing response"
            elif entry_type == "file_write":
                status.activity = f"writing {data.get('file', '')}"
            elif entry_type == "error":
                status.activity = "error"
            else:
                status.activity = entry_type

        try:
            trace_path = _Path(self._trace_dir) / f"agent-{task_id}.trace.jsonl"
            # Attach trace context if available
            from attoswarm.coordinator.trace_context import current_span as _current_span
            span = _current_span()
            entry = {
                "timestamp": time.time(),
                "agent_id": agent_id,
                "task_id": task_id,
                "entry_type": entry_type,
                "data": data,
                "trace_id": span.trace_id if span else "",
                "span_id": span.span_id if span else "",
            }
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(_json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("Trace write failed for agent %s: %s", agent_id, exc)
