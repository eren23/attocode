"""Swarm worker pool --- manages concurrent agent workers with budget and capability matching.

Handles worker selection by capability, budget allocation scaled by task complexity,
system prompt construction (tiered by attempt/config), and asyncio-based concurrency
with graceful cancellation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    SpawnAgentFn,
    SpawnResult,
    SwarmConfig,
    SwarmEvent,
    SwarmTask,
    SwarmWorkerSpec,
    SwarmWorkerStatus,
    TaskTypeConfig,
    WorkerCapability,
    swarm_event,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_DEFAULT_WORKER_TIMEOUT_MS = 120_000
_CANCEL_GRACE_SECONDS = 5.0
_MIN_CANCEL_GRACE_SECONDS = 1.0


# =============================================================================
# SwarmWorkerPool
# =============================================================================


class SwarmWorkerPool:
    """Manages spawning agent workers for swarm tasks.

    Responsibilities:
      - Capability-based worker selection with health-aware scoring
      - Budget computation scaled by task complexity
      - Tiered system prompt building (minimal / reduced / full)
      - Asyncio concurrency control with completion signaling
      - Graceful cancellation with configurable grace window
    """

    # --------------------------------------------------------------------- #
    # Construction
    # --------------------------------------------------------------------- #

    def __init__(
        self,
        config: SwarmConfig,
        spawn_agent_fn: SpawnAgentFn,
        budget_pool: Any,
        health_tracker: Any | None = None,
        shared_context_engine: Any | None = None,
        agent_registry: Any | None = None,
    ) -> None:
        self._config = config
        self._spawn_agent_fn = spawn_agent_fn
        self._budget_pool = budget_pool
        self._health_tracker = health_tracker
        self._shared_context_engine = shared_context_engine
        self._agent_registry = agent_registry

        # Concurrency
        self._max_concurrent: int = max(config.max_concurrency, 1)

        # Active worker tracking: task_id -> worker metadata
        self._active_workers: dict[str, dict[str, Any]] = {}

        # Completed results: task_id -> (SpawnResult, started_at_timestamp)
        self._completed_results: dict[str, tuple[SpawnResult, float]] = {}

        # Signaled whenever a worker finishes so wait_for_any() can wake up
        self._completion_event: asyncio.Event = asyncio.Event()

    # --------------------------------------------------------------------- #
    # Properties
    # --------------------------------------------------------------------- #

    @property
    def available_slots(self) -> int:
        """Number of worker slots available for dispatch."""
        return max(0, self._max_concurrent - len(self._active_workers))

    @property
    def active_count(self) -> int:
        """Number of workers currently running."""
        return len(self._active_workers)

    def get_active_task_ids(self) -> set[str]:
        """Return the set of task IDs that have active workers."""
        return set(self._active_workers.keys())

    def get_active_worker_statuses(self) -> list[SwarmWorkerStatus]:
        """Return status snapshots of all currently active workers."""
        now = time.monotonic()
        statuses: list[SwarmWorkerStatus] = []
        for task_id, entry in self._active_workers.items():
            task: SwarmTask = entry["task"]
            spec: SwarmWorkerSpec = entry["worker_spec"]
            started: float = entry["started_at"]
            statuses.append(
                SwarmWorkerStatus(
                    task_id=task_id,
                    task_description=task.description,
                    model=spec.model,
                    worker_name=spec.name,
                    elapsed_ms=(now - started) * 1000,
                    started_at=started,
                )
            )
        return statuses

    # --------------------------------------------------------------------- #
    # Worker Selection
    # --------------------------------------------------------------------- #

    def select_worker(self, task: SwarmTask) -> SwarmWorkerSpec | None:
        """Select the best worker for *task* based on capability matching.

        Selection strategy:
        1. Find workers whose capabilities include the required capability.
        2. If a health tracker is available, prefer workers whose model is
           healthy and has a higher success rate.
        3. Fall back through capability chains:
           ``test -> code``, ``write -> code``, ``any -> first worker``.

        Returns ``None`` only when the config has zero workers.
        """
        if not self._config.workers:
            return None

        required = self._match_capability(task.type)
        candidates = self._workers_with_capability(required)

        # Fallback chains
        if not candidates:
            if required == WorkerCapability.TEST:
                candidates = self._workers_with_capability(WorkerCapability.CODE)
            elif required == WorkerCapability.WRITE:
                candidates = self._workers_with_capability(WorkerCapability.CODE)
            elif required == WorkerCapability.DOCUMENT:
                candidates = self._workers_with_capability(WorkerCapability.CODE)
            elif required == WorkerCapability.REVIEW:
                candidates = self._workers_with_capability(WorkerCapability.RESEARCH)

        # Ultimate fallback: first worker
        if not candidates:
            candidates = list(self._config.workers)

        # Health-aware scoring
        if self._health_tracker is not None and len(candidates) > 1:
            candidates = self._rank_by_health(candidates)

        return candidates[0] if candidates else None

    # --------------------------------------------------------------------- #
    # Dispatch
    # --------------------------------------------------------------------- #

    async def dispatch(
        self,
        task: SwarmTask,
        worker: SwarmWorkerSpec | None = None,
    ) -> None:
        """Dispatch *task* to a worker, spawning it as an asyncio Task.

        If *worker* is ``None``, one is selected via :meth:`select_worker`.
        Budget is acquired from the pool before spawning.

        Raises ``RuntimeError`` if no worker can be selected.
        """
        if worker is None:
            worker = self.select_worker(task)
        if worker is None:
            raise RuntimeError(
                f"No worker available for task {task.id} (type={task.type})"
            )

        # Compute budget & acquire from pool
        budget = self._compute_worker_budget(task, worker)
        if self._budget_pool is not None:
            try:
                self._budget_pool.acquire(task.id, budget["max_tokens"])
            except Exception:
                logger.warning(
                    "Budget acquisition failed for task %s; dispatching anyway",
                    task.id,
                )

        # Build system prompt
        attempt = task.attempts
        system_prompt = self._build_worker_system_prompt(task, worker, attempt)

        started_at = time.monotonic()

        # Create the asyncio task
        async_task = asyncio.create_task(
            self._run_worker(task, worker, system_prompt, budget),
            name=f"swarm-worker-{task.id}",
        )

        self._active_workers[task.id] = {
            "task": task,
            "worker_spec": worker,
            "started_at": started_at,
            "future": async_task,
        }

        # Completion callback
        async_task.add_done_callback(
            lambda fut: self._on_worker_done(task.id, fut, started_at)
        )

        logger.info(
            "Dispatched task %s to worker %s (model=%s, attempt=%d, budget=%d tokens)",
            task.id,
            worker.name,
            worker.model,
            attempt,
            budget["max_tokens"],
        )

    # --------------------------------------------------------------------- #
    # Wait / Collect
    # --------------------------------------------------------------------- #

    async def wait_for_any(self) -> tuple[str, SpawnResult, float] | None:
        """Wait until at least one worker completes and return its result.

        Returns a tuple ``(task_id, spawn_result, started_at)`` or ``None``
        if there are no active workers (and no pending results).
        """
        while True:
            # Drain any already-completed results first
            if self._completed_results:
                task_id = next(iter(self._completed_results))
                result, started_at = self._completed_results.pop(task_id)
                return task_id, result, started_at

            # Nothing active and nothing pending
            if not self._active_workers:
                return None

            # Wait for the next completion signal
            self._completion_event.clear()
            await self._completion_event.wait()

    # --------------------------------------------------------------------- #
    # Cancellation & Cleanup
    # --------------------------------------------------------------------- #

    async def cancel_all(self) -> None:
        """Cancel all active workers with a brief grace window."""
        if not self._active_workers:
            return

        grace = max(
            _MIN_CANCEL_GRACE_SECONDS,
            min(_CANCEL_GRACE_SECONDS, self._config.worker_timeout / 10_000),
        )

        futures: list[asyncio.Task[Any]] = []
        for entry in self._active_workers.values():
            fut: asyncio.Task[Any] = entry["future"]
            if not fut.done():
                fut.cancel()
                futures.append(fut)

        if futures:
            logger.info(
                "Cancelling %d active workers (grace=%.1fs)", len(futures), grace
            )
            # Wait for cancellation to propagate
            await asyncio.wait(futures, timeout=grace)

        self._active_workers.clear()

    def cleanup(self) -> None:
        """Clear all internal state.

        Does NOT cancel running tasks -- call :meth:`cancel_all` first
        for a graceful shutdown.
        """
        self._active_workers.clear()
        self._completed_results.clear()
        self._completion_event.clear()

    # --------------------------------------------------------------------- #
    # Internal: Worker Execution
    # --------------------------------------------------------------------- #

    async def _run_worker(
        self,
        task: SwarmTask,
        worker: SwarmWorkerSpec,
        system_prompt: str,
        budget: dict[str, Any],
    ) -> SpawnResult:
        """Run the spawn function for a single worker.

        This is the coroutine executed by the asyncio.Task created in
        :meth:`dispatch`.
        """
        timeout_s = budget.get("timeout_ms", _DEFAULT_WORKER_TIMEOUT_MS) / 1000

        try:
            result: SpawnResult = await asyncio.wait_for(
                self._spawn_agent_fn(
                    task=task,
                    worker=worker,
                    system_prompt=system_prompt,
                    max_tokens=budget["max_tokens"],
                    timeout_ms=budget.get("timeout_ms", _DEFAULT_WORKER_TIMEOUT_MS),
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning("Worker for task %s timed out after %.0fs", task.id, timeout_s)
            result = SpawnResult(
                success=False,
                output=f"Worker timed out after {timeout_s:.0f}s",
                tool_calls=-1,  # convention: -1 means timeout
            )
        except asyncio.CancelledError:
            logger.info("Worker for task %s was cancelled", task.id)
            result = SpawnResult(
                success=False,
                output="Worker was cancelled",
                tool_calls=0,
            )
        except Exception as exc:
            logger.error("Worker for task %s failed with error: %s", task.id, exc)
            result = SpawnResult(
                success=False,
                output=f"Worker error: {exc}",
                tool_calls=0,
            )

        return result

    def _on_worker_done(
        self,
        task_id: str,
        future: asyncio.Task[SpawnResult],
        started_at: float,
    ) -> None:
        """Callback when a worker asyncio.Task completes.

        Moves the result into ``_completed_results`` and signals
        ``_completion_event`` so that :meth:`wait_for_any` wakes up.
        """
        # Remove from active
        self._active_workers.pop(task_id, None)

        # Extract result
        if future.cancelled():
            result = SpawnResult(
                success=False,
                output="Worker was cancelled",
                tool_calls=0,
            )
        elif future.exception() is not None:
            exc = future.exception()
            result = SpawnResult(
                success=False,
                output=f"Worker error: {exc}",
                tool_calls=0,
            )
        else:
            result = future.result()

        self._completed_results[task_id] = (result, started_at)

        # Release budget
        if self._budget_pool is not None:
            try:
                self._budget_pool.release(task_id)
            except Exception:
                pass  # best-effort

        # Wake up anyone waiting
        self._completion_event.set()

        duration_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "Worker for task %s completed (success=%s, duration=%dms)",
            task_id,
            result.success,
            duration_ms,
        )

    # --------------------------------------------------------------------- #
    # Internal: Worker Selection Helpers
    # --------------------------------------------------------------------- #

    def _workers_with_capability(
        self, capability: WorkerCapability
    ) -> list[SwarmWorkerSpec]:
        """Return all configured workers that have *capability*."""
        return [
            w for w in self._config.workers if capability in w.capabilities
        ]

    def _rank_by_health(
        self, candidates: list[SwarmWorkerSpec]
    ) -> list[SwarmWorkerSpec]:
        """Rank candidate workers preferring healthy models with better success rates.

        Workers whose model the health tracker considers unhealthy are moved
        to the end.  Among healthy workers, those with a higher success rate
        sort first.
        """
        if self._health_tracker is None:
            return candidates

        def _score(w: SwarmWorkerSpec) -> tuple[int, float]:
            try:
                record = self._health_tracker.get(w.model)
                if record is None:
                    return (1, 1.0)  # unknown = assume healthy, neutral rate
                healthy = 1 if record.healthy else 0
                return (healthy, record.success_rate)
            except Exception:
                return (1, 1.0)

        return sorted(candidates, key=_score, reverse=True)

    # --------------------------------------------------------------------- #
    # Internal: Capability Matching
    # --------------------------------------------------------------------- #

    def _match_capability(self, task_type: str) -> WorkerCapability:
        """Map a task type string to the required worker capability.

        Uses :data:`BUILTIN_TASK_TYPE_CONFIGS` first, then custom task types
        from the swarm config.  Falls back to ``CODE``.
        """
        config = BUILTIN_TASK_TYPE_CONFIGS.get(task_type)
        if config is not None:
            return config.capability

        # Check custom task types from swarm config
        custom = self._config.task_types.get(task_type)
        if custom is not None:
            return custom.capability

        return WorkerCapability.CODE

    # --------------------------------------------------------------------- #
    # Internal: Budget Computation
    # --------------------------------------------------------------------- #

    def _compute_worker_budget(
        self, task: SwarmTask, worker: SwarmWorkerSpec
    ) -> dict[str, Any]:
        """Compute the token budget and timeout for a worker dispatch.

        Token budget scales linearly with task complexity (1--10):

            ``tokens = min_tokens + (max_tokens - min_tokens) * complexity / 10``

        The result is capped at both the worker's ``max_tokens`` and the
        swarm config's ``max_tokens_per_worker``.
        """
        task_type = task.type

        # Lookup type config (builtin -> custom -> defaults)
        type_config: TaskTypeConfig | None = BUILTIN_TASK_TYPE_CONFIGS.get(task_type)
        if type_config is None:
            type_config = self._config.task_types.get(task_type)

        if type_config is not None:
            min_tokens = type_config.min_tokens
            max_tokens = type_config.max_tokens
            timeout_ms = type_config.timeout * 1000
        else:
            min_tokens = 20_000
            max_tokens = 80_000
            timeout_ms = _DEFAULT_WORKER_TIMEOUT_MS

        # Scale by complexity (1-10)
        complexity = max(1, min(10, task.complexity))
        tokens = int(min_tokens + (max_tokens - min_tokens) * complexity / 10)

        # Cap at worker limit
        tokens = min(tokens, worker.max_tokens)
        # Cap at swarm config limit
        tokens = min(tokens, self._config.max_tokens_per_worker)

        return {
            "max_tokens": tokens,
            "timeout_ms": timeout_ms,
        }

    # --------------------------------------------------------------------- #
    # Internal: Prompt Building
    # --------------------------------------------------------------------- #

    def _build_worker_system_prompt(
        self,
        task: SwarmTask,
        worker: SwarmWorkerSpec,
        attempt: int,
    ) -> str:
        """Build the system prompt for a worker dispatch.

        Three tiers of prompt detail are supported:

        - **minimal**: bare task description + target files + retry context.
          Suitable for fast/cheap models or retries where verbosity wastes tokens.
        - **reduced**: adds compact environment info and delegation spec.
          Used for non-research retries.
        - **full**: complete environment, delegation spec, quality
          self-assessment instructions, and goal recitation.  Used for first
          attempts on capable workers.
        """
        tier = self._get_prompt_tier(worker, attempt)
        template = self._select_prompt_template(task.type)
        sections: list[str] = []

        # ---- Core task description (all tiers) ---- #
        sections.append(f"# Task\n\n{task.description}")

        if task.type:
            sections.append(f"**Type:** {task.type}")

        if task.target_files:
            files_str = "\n".join(f"- {f}" for f in task.target_files)
            sections.append(f"**Target files:**\n{files_str}")

        if task.read_files:
            files_str = "\n".join(f"- {f}" for f in task.read_files)
            sections.append(f"**Reference files (read-only):**\n{files_str}")

        # ---- Retry context (all tiers when attempt > 0) ---- #
        if attempt > 0 and task.retry_context is not None:
            rc = task.retry_context
            retry_parts: list[str] = [
                f"\n## Retry Context (attempt {rc.attempt + 1})"
            ]
            if rc.previous_feedback:
                retry_parts.append(
                    f"**Previous feedback:** {rc.previous_feedback}"
                )
            if rc.previous_score:
                retry_parts.append(
                    f"**Previous quality score:** {rc.previous_score}/5"
                )
            if rc.previous_model:
                retry_parts.append(
                    f"**Previous model:** {rc.previous_model}"
                )
            if rc.swarm_progress:
                retry_parts.append(
                    f"**Swarm progress:** {rc.swarm_progress}"
                )
            sections.append("\n".join(retry_parts))

        # ---- Dependency context (all tiers) ---- #
        if task.dependency_context:
            sections.append(
                f"\n## Dependency Context\n\n{task.dependency_context}"
            )

        # ---- Partial context (all tiers) ---- #
        if task.partial_context is not None:
            pc = task.partial_context
            partial_parts: list[str] = [
                f"\n## Partial Dependency Context (ratio: {pc.ratio:.0%})"
            ]
            if pc.succeeded:
                partial_parts.append(
                    "**Completed dependencies:**\n"
                    + "\n".join(f"- {d}" for d in pc.succeeded)
                )
            if pc.failed:
                partial_parts.append(
                    "**Failed dependencies (work around these):**\n"
                    + "\n".join(f"- {d}" for d in pc.failed)
                )
            sections.append("\n".join(partial_parts))

        # ---- Shared context (reduced + full) ---- #
        if tier in ("reduced", "full") and self._shared_context_engine is not None:
            try:
                shared = self._shared_context_engine.get_relevant(task.description)
                if shared:
                    sections.append(f"\n## Shared Context\n\n{shared}")
            except Exception:
                pass  # best-effort

        # ---- Environment info (reduced + full) ---- #
        if tier in ("reduced", "full"):
            env_parts: list[str] = ["\n## Environment"]
            env_parts.append(
                "You are a swarm worker agent. Complete your assigned task "
                "and report results. Do NOT ask questions or wait for input."
            )
            if worker.persona:
                env_parts.append(f"**Persona:** {worker.persona}")
            sections.append("\n".join(env_parts))

        # ---- Delegation spec (reduced + full, non-research) ---- #
        if tier in ("reduced", "full") and template != "research":
            sections.append(
                "\n## Delegation Spec\n\n"
                "- Make concrete changes (create/edit files, run commands).\n"
                "- Do NOT just describe what you would do.\n"
                "- Do NOT output plans or future-intent language.\n"
                "- Verify your changes work (run tests if applicable)."
            )

        # ---- Quality self-assessment (full only) ---- #
        if tier == "full":
            sections.append(
                "\n## Quality Self-Assessment\n\n"
                "Before finishing, evaluate your own work:\n"
                "1. Does the output satisfy the task description?\n"
                "2. Are there any obvious errors or omissions?\n"
                "3. If the task has target files, did you modify them?\n"
                "4. Would a code reviewer approve this change?"
            )

        # ---- Goal recitation (full only) ---- #
        if tier == "full":
            sections.append(
                f"\n## Goal Recitation\n\n"
                f"Your single goal: **{task.description}**\n"
                f"Stay focused. Do not drift into unrelated work."
            )

        return "\n\n".join(sections)

    def _get_prompt_tier(self, worker: SwarmWorkerSpec, attempt: int) -> str:
        """Determine the prompt detail tier for a dispatch.

        Rules:
        - Worker explicitly configured as ``'minimal'`` -> ``'minimal'``
        - Retry (attempt > 0) -> ``'reduced'`` (save tokens on repeated work)
        - Otherwise -> the worker's configured tier (default ``'full'``)
        """
        if worker.prompt_tier == "minimal":
            return "minimal"
        if attempt > 0:
            return "reduced"
        return worker.prompt_tier  # typically 'full'

    def _select_prompt_template(self, task_type: str) -> str:
        """Select the prompt template name for a task type.

        Looks up :data:`BUILTIN_TASK_TYPE_CONFIGS`, then custom task types.
        Defaults to ``'code'``.
        """
        config = BUILTIN_TASK_TYPE_CONFIGS.get(task_type)
        if config is not None:
            return config.prompt_template

        custom = self._config.task_types.get(task_type)
        if custom is not None:
            return custom.prompt_template

        return "code"
