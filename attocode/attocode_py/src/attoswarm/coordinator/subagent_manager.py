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
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from attocode.integrations.context.ast_service import ASTService
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


@dataclass(slots=True)
class AgentStatus:
    """Status snapshot of a worker agent."""

    agent_id: str
    task_id: str
    status: str             # "idle" | "claiming" | "running" | "done" | "error"
    started_at: float = 0.0
    tokens_used: int = 0
    model: str = ""


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
        file_ledger: "FileLedger | None" = None,
        ast_service: "ASTService | None" = None,
        spawn_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._file_ledger = file_ledger
        self._ast_service = ast_service
        self._spawn_fn = spawn_fn

        # Status tracking
        self._agent_statuses: dict[str, AgentStatus] = {}
        self._status_callbacks: list[Callable[[AgentStatus], Any]] = []

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

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

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

        async with self._semaphore:
            start = time.time()

            # 1. Claim files
            self._emit_status(agent_id, task_id, "claiming")
            if self._file_ledger and target_files:
                for f in target_files:
                    ok = await self._file_ledger.claim_file(f, agent_id, task_id)
                    if not ok:
                        await self._file_ledger.release_all_claims(agent_id)
                        self._emit_status(agent_id, task_id, "error")
                        return TaskResult(
                            task_id=task_id,
                            success=False,
                            error=f"Could not claim file: {f}",
                        )

            # 2. Spawn worker
            self._emit_status(agent_id, task_id, "running")
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
            except asyncio.TimeoutError:
                result = TaskResult(
                    task_id=task_id,
                    success=False,
                    error=f"Task timed out after {timeout}s",
                )
            except Exception as exc:
                result = TaskResult(
                    task_id=task_id,
                    success=False,
                    error=str(exc),
                )

            # 3. Release claims
            if self._file_ledger:
                await self._file_ledger.release_all_claims(agent_id)

            result.duration_s = time.time() - start
            status = "done" if result.success else "error"
            self._emit_status(agent_id, task_id, status, tokens=result.tokens_used)

            return result

    def _emit_status(
        self,
        agent_id: str,
        task_id: str,
        status: str,
        tokens: int = 0,
    ) -> None:
        s = AgentStatus(
            agent_id=agent_id,
            task_id=task_id,
            status=status,
            started_at=time.time(),
            tokens_used=tokens,
        )
        self._agent_statuses[agent_id] = s
        for cb in self._status_callbacks:
            try:
                cb(s)
            except Exception as exc:
                logger.debug("Status callback error: %s", exc)
