"""Coordinator loop for hybrid swarm execution."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attocode_core.ast_index.indexer import CodeIndex
from attoswarm.adapters.base import AgentProcessSpec
from attoswarm.adapters.registry import get_adapter
from attoswarm.coordinator.budget import BudgetCounter
from attoswarm.coordinator.failure_handler import (
    cascade_skip_blocked as _cascade_skip_blocked_impl,
)
from attoswarm.coordinator.failure_handler import (
    enforce_task_duration_limits as _enforce_task_duration_limits_impl,
)
from attoswarm.coordinator.failure_handler import (
    enforce_task_silence_timeouts as _enforce_task_silence_timeouts_impl,
)
from attoswarm.coordinator.failure_handler import (
    handle_task_failed as _handle_task_failed_impl,
)
from attoswarm.coordinator.failure_handler import (
    mark_running_task_failed as _mark_running_task_failed_impl,
)
from attoswarm.coordinator.merge_queue import MergeQueue
from attoswarm.coordinator.output_harvester import (
    capture_partial_output as _capture_partial_output_impl,
)
from attoswarm.coordinator.output_harvester import (
    detect_file_changes as _detect_file_changes_impl,
)
from attoswarm.coordinator.output_harvester import (
    handle_completion_claim as _handle_completion_claim_impl,
)
from attoswarm.coordinator.output_harvester import (
    harvest_outputs as _harvest_outputs_impl,
)
from attoswarm.coordinator.review_processor import (
    process_review_queue as _process_review_queue_impl,
)
from attoswarm.coordinator.scheduler import (  # noqa: F401
    AgentSlot,
    assign_tasks,
    compute_ready_tasks,
)
from attoswarm.coordinator.state_writer import write_state
from attoswarm.coordinator.task_dispatcher import (
    build_task_prompt as _build_task_prompt_impl,
)
from attoswarm.coordinator.task_dispatcher import (
    dispatch_ready_tasks as _dispatch_ready_tasks_impl,
)
from attoswarm.coordinator.task_dispatcher import (
    send_task_assignment as _send_task_assignment_impl,
)
from attoswarm.coordinator.watchdog import evaluate_watchdog
from attoswarm.protocol.io import append_jsonl, read_json, write_json_atomic
from attoswarm.protocol.locks import locked_file  # noqa: F401
from attoswarm.protocol.models import (
    AgentInbox,
    AgentOutbox,
    BudgetSpec,
    MergePolicy,
    RoleSpec,
    SwarmManifest,
    TaskSpec,
    default_run_layout,
    utc_now_iso,
)
from attoswarm.workspace.worktree import cleanup_worktrees, ensure_workspace_for_agent

if TYPE_CHECKING:
    from attoswarm.config.schema import RoleConfig, SwarmYamlConfig

log = logging.getLogger(__name__)


# Env vars that interfere with nested agent processes (e.g. running from
# within Claude Code would set CLAUDECODE=1 causing claude subprocess to
# refuse with "cannot launch inside another session").
_STRIP_ENV_VARS = {
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_REPL",
    "CLAUDE_CODE_PACKAGE_DIR",
}


SKIP_REVIEW_KINDS: frozenset[str] = frozenset({"judge", "critic", "merge", "analysis", "design"})

TRANSITIONS: dict[str, set[str]] = {
    "pending": {"ready", "running", "failed", "blocked", "skipped"},
    "ready": {"running", "failed", "blocked", "skipped"},
    "running": {"reviewing", "done", "failed", "ready"},
    "reviewing": {"done", "failed", "ready"},
    "done": set(),
    "failed": set(),
    "blocked": {"ready", "failed", "skipped"},
    "skipped": set(),
}


class HybridCoordinator:
    def __init__(self, config: SwarmYamlConfig, goal: str, *, resume: bool = False) -> None:
        self.config = config
        self.goal = goal
        self.resume = resume
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.layout = default_run_layout(Path(config.run.run_dir))

        self.manifest: SwarmManifest | None = None
        self.task_state: dict[str, str] = {}
        self.task_attempts: dict[str, int] = {}
        self.running_task_by_agent: dict[str, str] = {}
        self.running_task_last_progress: dict[str, float] = {}
        self.running_task_started_at: dict[str, float] = {}
        self._task_timeout_overrides: dict[str, int] = {}
        self.outbox_cursors: dict[str, int] = {}

        self.adapters: dict[str, object] = {}
        self.handles: dict[str, object] = {}
        self.role_by_agent: dict[str, RoleSpec] = {}
        self.role_cfg_by_role_id: dict[str, RoleConfig] = {r.role_id: r for r in config.roles}

        self.budget = BudgetCounter(
            max_tokens=config.budget.max_tokens,
            max_cost_usd=config.budget.max_cost_usd,
            chars_per_token=config.budget.chars_per_token_fallback,
        )
        self.merge_queue = MergeQueue()
        self.crash_count = 0
        self.reassigned_tasks = 0
        self.state_seq = 0
        self.agent_restart_count: dict[str, int] = {}

        self.errors: list[dict[str, Any]] = []
        self.transition_log: list[dict[str, Any]] = []

    async def run(self) -> int:
        try:
            self._ensure_layout()

            # Archive previous run artifacts on fresh (non-resume) runs
            if not self.resume:
                from attoswarm.coordinator.archive import archive_previous_run

                archive_previous_run(self.layout)

            if self.resume and self.layout["manifest"].exists():
                self._load_existing_run()
            else:
                self._bootstrap_manifest()

            # Log effective config so it's visible in events
            effective_duration = max(300.0, float(self.config.watchdog.task_max_duration_seconds))
            self._append_event("config.effective", {
                "task_max_duration_seconds": effective_duration,
                "max_runtime_seconds": self.config.run.max_runtime_seconds,
                "max_task_attempts": self.config.retries.max_task_attempts,
                "workspace_mode": self.config.workspace.mode,
                "roles": [r.role_id for r in self.config.roles],
            })

            # Validate backend binaries before spawning
            if not self._preflight_check():
                self._error("preflight", "No backend binaries found on PATH — cannot spawn any agents")
                self._append_event("preflight.fatal", {
                    "error": "No backend binaries found on PATH",
                })
                return 1

            await self._spawn_agents()
            await self._run_loop()
            await self._shutdown_agents()
            return 0
        except Exception as exc:
            self._error("coordinator_crash", f"{type(exc).__name__}: {exc}")
            try:
                await self._shutdown_agents()
            except Exception as exc:
                log.warning("Shutdown failed during crash: %s", exc)
            raise

    def _ensure_layout(self) -> None:
        for key, path in self.layout.items():
            if key in {"manifest", "state", "events"}:
                continue
            path.mkdir(parents=True, exist_ok=True)

    def _preflight_check(self) -> bool:
        """Check that required backend binaries are available. Returns False if none are available."""
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        backends_ok = 0
        for role in self.manifest.roles:
            cfg = self.role_cfg_by_role_id.get(role.role_id)
            if cfg and cfg.command:
                binary = cfg.command[0] if cfg.command[0] != "sh" else None
            else:
                # Default commands wrap in sh -c; check the actual backend binary
                backend_binary = {"codex-mcp": "codex"}.get(role.backend, role.backend)
                binary = backend_binary if backend_binary in {"claude", "codex", "aider", "attocode"} else None
            if binary and not shutil.which(binary):
                self._append_event("preflight.warning", {
                    "role_id": role.role_id,
                    "backend": role.backend,
                    "binary": binary,
                    "error": f"'{binary}' not found on PATH",
                })
                self._error("preflight", f"Backend binary '{binary}' not found for role {role.role_id}")
            else:
                backends_ok += 1
        return backends_ok > 0

    def _bootstrap_manifest(self) -> None:
        roles = [
            RoleSpec(
                role_id=role.role_id,
                role_type=role.role_type,  # type: ignore[arg-type]
                backend=role.backend,
                model=role.model,
                count=role.count,
                write_access=role.write_access,
                workspace_mode=role.workspace_mode,  # type: ignore[arg-type]
                capabilities=role.capabilities,
                task_kinds=role.task_kinds,
                execution_mode=role.execution_mode,
            )
            for role in self.config.roles
        ]

        tasks = self._decompose_initial_tasks(roles)
        budget = BudgetSpec(
            max_tokens=self.config.budget.max_tokens,
            max_cost_usd=self.config.budget.max_cost_usd,
            reserve_ratio=self.config.budget.reserve_ratio,
            chars_per_token_fallback=self.config.budget.chars_per_token_fallback,
        )
        merge = MergePolicy(
            authority_role=self.config.merge.authority_role,
            quality_threshold=self.config.merge.quality_threshold,
        )
        self.manifest = SwarmManifest(
            run_id=self.run_id,
            goal=self.goal,
            roles=roles,
            tasks=tasks,
            budget=budget,
            merge_policy=merge,
        )
        for task in tasks:
            self.task_state[task.task_id] = task.status
            self.task_attempts[task.task_id] = 0
            self._persist_task(task)
        write_json_atomic(self.layout["manifest"], self.manifest.to_dict())
        self._build_index_snapshot()

    def _load_existing_run(self) -> None:
        raw = read_json(self.layout["manifest"], default={})
        saved_version = raw.get("schema_version", "1.0")
        if saved_version != "1.0":
            log.warning(
                "manifest schema_version %s differs from expected 1.0 — resume may be unreliable",
                saved_version,
            )
        roles: list[RoleSpec] = []
        for role in raw.get("roles", []):
            if not isinstance(role, dict):
                continue
            roles.append(
                RoleSpec(
                    role_id=str(role.get("role_id", "worker")),
                    role_type=str(role.get("role_type", "worker")),  # type: ignore[arg-type]
                    backend=str(role.get("backend", "claude")),
                    model=str(role.get("model", "")),
                    count=int(role.get("count", 1)),
                    write_access=bool(role.get("write_access", False)),
                    workspace_mode=str(role.get("workspace_mode", "shared_ro")),  # type: ignore[arg-type]
                    capabilities=[str(x) for x in role.get("capabilities", []) if isinstance(x, str)],
                    task_kinds=[str(x) for x in role.get("task_kinds", []) if isinstance(x, str)],
                    execution_mode=str(role.get("execution_mode", "oneshot")),
                )
            )
        tasks: list[TaskSpec] = []
        for t in raw.get("tasks", []):
            if not isinstance(t, dict):
                continue
            task = TaskSpec(
                task_id=str(t.get("task_id", "")),
                title=str(t.get("title", "")),
                description=str(t.get("description", "")),
                deps=[str(x) for x in t.get("deps", []) if isinstance(x, str)],
                role_hint=str(t.get("role_hint")) if t.get("role_hint") else None,
                priority=int(t.get("priority", 50)),
                acceptance=[str(x) for x in t.get("acceptance", []) if isinstance(x, str)],
                artifacts=[str(x) for x in t.get("artifacts", []) if isinstance(x, str)],
                status=str(t.get("status", "pending")),  # type: ignore[arg-type]
                task_kind=str(t.get("task_kind", "implement")),
                timeout_override=int(t["timeout_override"]) if t.get("timeout_override") is not None else None,
            )
            tasks.append(task)
            if task.timeout_override is not None:
                self._task_timeout_overrides[task.task_id] = task.timeout_override
            task_raw = read_json(self.layout["tasks"] / f"task-{task.task_id}.json", default={})
            status = str(task_raw.get("status", task.status))
            self.task_state[task.task_id] = "ready" if status == "running" else status
            self.task_attempts[task.task_id] = int(task_raw.get("attempts", 0))

        self.run_id = str(raw.get("run_id", self.run_id))
        budget = BudgetSpec(
            max_tokens=int(raw.get("budget", {}).get("max_tokens", self.config.budget.max_tokens)),
            max_cost_usd=float(raw.get("budget", {}).get("max_cost_usd", self.config.budget.max_cost_usd)),
            reserve_ratio=float(raw.get("budget", {}).get("reserve_ratio", self.config.budget.reserve_ratio)),
            chars_per_token_fallback=float(
                raw.get("budget", {}).get(
                    "chars_per_token_fallback", self.config.budget.chars_per_token_fallback
                )
            ),
        )
        merge = MergePolicy(
            authority_role=str(
                raw.get("merge_policy", {}).get("authority_role", self.config.merge.authority_role)
            ),
            quality_threshold=float(
                raw.get("merge_policy", {}).get("quality_threshold", self.config.merge.quality_threshold)
            ),
        )
        self.manifest = SwarmManifest(
            run_id=self.run_id,
            goal=str(raw.get("goal", self.goal)),
            created_at=str(raw.get("created_at", utc_now_iso())),
            roles=roles,
            tasks=tasks,
            budget=budget,
            merge_policy=merge,
        )

        state_raw = read_json(self.layout["state"], default={})
        budget_raw = state_raw.get("budget", {}) if isinstance(state_raw.get("budget"), dict) else {}
        self.budget.used_tokens = int(budget_raw.get("tokens_used", 0))
        self.budget.used_cost_usd = float(budget_raw.get("cost_used_usd", 0.0))
        merge_items = state_raw.get("merge_queue", {}).get("items", [])
        self.merge_queue = MergeQueue.from_list(merge_items if isinstance(merge_items, list) else [])
        self.outbox_cursors = (
            state_raw.get("cursors", {}).get("outbox_seq_by_agent", {})
            if isinstance(state_raw.get("cursors"), dict)
            else {}
        )
        self.state_seq = int(state_raw.get("state_seq", 0))
        saved_overrides = state_raw.get("timeout_overrides")
        if isinstance(saved_overrides, dict):
            self._task_timeout_overrides.update({str(k): int(v) for k, v in saved_overrides.items()})
        self.transition_log = [
            x for x in state_raw.get("task_transition_log", []) if isinstance(x, dict)
        ]
        self.errors = [x for x in state_raw.get("errors", []) if isinstance(x, dict)]

    async def _spawn_agents(self) -> None:
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        for role in self.manifest.roles:
            for i in range(role.count):
                agent_id = f"{role.role_id}-{i+1}"
                try:
                    cmd = self._role_command(role)
                    workspace = ensure_workspace_for_agent(
                        repo_root=Path(self.config.run.working_dir),
                        worktrees_root=self.layout["worktrees"],
                        agent_id=agent_id,
                        workspace_mode=role.workspace_mode,
                        write_access=role.write_access,
                    )
                    spec = AgentProcessSpec(
                        agent_id=agent_id,
                        backend=role.backend,
                        binary=cmd[0],
                        args=cmd[1:],
                        cwd=str(workspace),
                        role=role.role_id,
                        model=role.model,
                        write_access=role.write_access,
                        env={
                            **{k: v for k, v in os.environ.items()
                               if k not in _STRIP_ENV_VARS},
                            "ATTO_AGENT_ID": agent_id,
                            "ATTO_MODEL": role.model,
                        },
                        log_file=str(self.layout["logs"] / f"agent-{agent_id}.log"),
                    )
                    adapter = get_adapter(role.backend)
                    handle = await adapter.spawn(spec)
                    self.adapters[agent_id] = adapter
                    self.handles[agent_id] = handle
                    self.role_by_agent[agent_id] = role
                    self.outbox_cursors.setdefault(agent_id, 0)
                    self.agent_restart_count.setdefault(agent_id, 0)

                    inbox_path = self.layout["agents"] / f"agent-{agent_id}.inbox.json"
                    outbox_path = self.layout["agents"] / f"agent-{agent_id}.outbox.json"
                    if not inbox_path.exists():
                        write_json_atomic(inbox_path, AgentInbox(agent_id=agent_id).to_dict())
                    if not outbox_path.exists():
                        write_json_atomic(outbox_path, AgentOutbox(agent_id=agent_id).to_dict())

                    workspace_effective = (
                        "worktree" if str(workspace) != str(Path(self.config.run.working_dir)) else "shared"
                    )
                    self._append_event(
                        "agent.spawned",
                        {
                            "agent_id": agent_id,
                            "role_id": role.role_id,
                            "backend": role.backend,
                            "model": role.model,
                            "cwd": str(workspace),
                            "workspace_mode": role.workspace_mode,
                            "workspace_effective": workspace_effective,
                        },
                    )
                    if self.config.run.debug:
                        self._append_event(
                            "debug.agent.command",
                            {
                                "agent_id": agent_id,
                                "command": [spec.binary, *spec.args],
                                "cwd": spec.cwd,
                                "env_keys": sorted(spec.env.keys()),
                            },
                        )
                except FileNotFoundError:
                    self._error("spawn_failed", f"Backend binary not found for {role.backend} (agent {agent_id})")
                    self._append_event("agent.spawn_failed", {
                        "agent_id": agent_id,
                        "role_id": role.role_id,
                        "backend": role.backend,
                        "error": f"Binary not found on PATH for backend '{role.backend}'",
                    })
                except Exception as exc:
                    self._error("spawn_failed", f"Failed to spawn {agent_id}: {exc}")
                    self._append_event("agent.spawn_failed", {
                        "agent_id": agent_id,
                        "role_id": role.role_id,
                        "backend": role.backend,
                        "error": str(exc),
                    })

    async def _run_loop(self) -> None:
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        phase = "executing"
        poll = max(self.config.run.poll_interval_ms / 1000.0, 0.05)
        max_runtime = max(self.config.run.max_runtime_seconds, 10)
        started_at = time.monotonic()

        while True:
            await self._harvest_outputs()
            await self._enforce_task_silence_timeouts()
            await self._enforce_task_duration_limits()
            await self._process_review_queue()

            expired_ids = self.merge_queue.expire_stale_items()
            for tid in expired_ids:
                task = next((t for t in self.manifest.tasks if t.task_id == tid), None)
                if task:
                    self._transition_task(tid, "failed", "coordinator", "merge_item_expired")
                    self._persist_task(task, status="failed", last_error="merge_item_expired")
                else:
                    log.warning("Merge queue item %s expired but task not in manifest", tid)
            if expired_ids:
                self._cascade_skip_blocked()

            await self._dispatch_ready_tasks()

            done = all(
                self.task_state.get(t.task_id, t.status) in {"done", "failed", "skipped"}
                for t in self.manifest.tasks
            )
            if done:
                phase = "completed"

            running = {aid: self.handles[aid].process.returncode is None for aid in self.handles}
            heartbeat = {aid: self.handles[aid].last_heartbeat_ts for aid in self.handles}
            wd = evaluate_watchdog(
                heartbeat,
                running,
                timeout_seconds=self.config.watchdog.heartbeat_timeout_seconds,
            )
            for stuck in wd.restart_agents:
                await self._restart_agent(stuck)

            if self.budget.hard_exceeded() or (time.monotonic() - started_at) > max_runtime:
                phase = "failed"
                if (time.monotonic() - started_at) > max_runtime:
                    self._error("timeout", "max runtime exceeded")

            self.state_seq += 1
            tasks = [replace(t, status=self.task_state.get(t.task_id, t.status)) for t in self.manifest.tasks]
            write_state(
                state_path=str(self.layout["state"]),
                run_id=self.run_id,
                phase=phase,
                tasks=tasks,
                active_agents=self._active_agents(),
                dag_edges=[(dep, t.task_id) for t in tasks for dep in t.deps],
                budget=self.budget.as_dict(),
                watchdog={
                    "crash_count": self.crash_count,
                    "reassigned_tasks": self.reassigned_tasks,
                    "stale_agents": len(wd.stale_agents),
                },
                merge_queue={**self.merge_queue.summary(), "items": self.merge_queue.to_list()},
                index_status=self._index_status(),
                cursors={"outbox_seq_by_agent": self.outbox_cursors},
                assignments={"running_by_agent": dict(self.running_task_by_agent)},
                attempts={"by_task": dict(self.task_attempts)},
                state_seq=self.state_seq,
                errors=self.errors[-200:],
                task_transition_log=self.transition_log[-400:],
                event_timeline={
                    "events_file": self.layout["events"].name,
                    "latest_seq": self.state_seq,
                },
                agent_messages_index={"agents_dir": self.layout["agents"].name},
                elapsed_s=time.monotonic() - started_at,
                timeout_overrides=self._task_timeout_overrides or None,
            )
            if phase in {"completed", "failed"}:
                break
            await asyncio.sleep(poll)

    async def _harvest_outputs(self) -> None:
        await _harvest_outputs_impl(self)

    async def _dispatch_ready_tasks(self) -> None:
        await _dispatch_ready_tasks_impl(self)

    def _build_task_prompt(self, task: TaskSpec) -> str:
        return _build_task_prompt_impl(self, task)

    async def _send_task_assignment(self, agent_id: str, task: TaskSpec) -> None:
        await _send_task_assignment_impl(self, agent_id, task)

    async def _process_review_queue(self) -> None:
        await _process_review_queue_impl(self)

    async def _restart_agent(self, agent_id: str) -> None:
        adapter = self.adapters[agent_id]
        handle = self.handles[agent_id]
        await adapter.terminate(handle, reason="watchdog_restart")
        self.crash_count += 1
        self._append_event("agent.restart", {"agent_id": agent_id})
        new_handle = await adapter.spawn(handle.spec)
        self.handles[agent_id] = new_handle
        self.agent_restart_count[agent_id] = self.agent_restart_count.get(agent_id, 0) + 1
        task_id = self.running_task_by_agent.pop(agent_id, None)
        if task_id:
            self._transition_task(task_id, "ready", "watchdog", "agent_restarted")
            self.reassigned_tasks += 1

    async def _shutdown_agents(self) -> None:
        for agent_id, adapter in self.adapters.items():
            handle = self.handles[agent_id]
            await adapter.terminate(handle, reason="shutdown")
        cleanup_worktrees(
            repo_root=Path(self.config.run.working_dir),
            worktrees_root=self.layout["worktrees"],
        )

    def _detect_file_changes(self, agent_id: str, task_id: str) -> None:
        _detect_file_changes_impl(self, agent_id, task_id)

    async def _handle_completion_claim(self, agent_id: str, task_id: str) -> None:
        await _handle_completion_claim_impl(self, agent_id, task_id)

    async def _handle_task_failed(self, agent_id: str, task_id: str, reason: str) -> None:
        await _handle_task_failed_impl(self, agent_id, task_id, reason)

    async def _mark_running_task_failed(self, agent_id: str, reason: str) -> None:
        await _mark_running_task_failed_impl(self, agent_id, reason)

    def _capture_partial_output(self, agent_id: str) -> str:
        return _capture_partial_output_impl(self, agent_id)

    def _cascade_skip_blocked(self) -> list[str]:
        return _cascade_skip_blocked_impl(self)

    async def _enforce_task_silence_timeouts(self) -> None:
        await _enforce_task_silence_timeouts_impl(self)

    async def _enforce_task_duration_limits(self) -> None:
        await _enforce_task_duration_limits_impl(self)

    def _active_agents(self) -> list[dict]:
        active: list[dict] = []
        for agent_id, handle in self.handles.items():
            role = self.role_by_agent[agent_id]
            command = " ".join([handle.spec.binary, *handle.spec.args]).strip()
            task_id = self.running_task_by_agent.get(agent_id)
            task = self._find_task(task_id) if task_id else None
            started_at = self.running_task_started_at.get(task_id, 0) if task_id else 0
            # Convert monotonic to epoch for TUI consumption
            started_epoch = time.time() - (time.monotonic() - started_at) if started_at else 0
            active.append(
                {
                    "agent_id": agent_id,
                    "role_id": role.role_id,
                    "role_type": role.role_type,
                    "backend": role.backend,
                    "model": role.model or role.backend,
                    "execution_mode": role.execution_mode,
                    "status": "running" if handle.process.returncode is None else "exited",
                    "task_id": task_id,
                    "task_title": task.title if task else "",
                    "last_heartbeat_ts": handle.last_heartbeat_ts,
                    "cwd": handle.spec.cwd,
                    "command": command,
                    "exit_code": handle.process.returncode,
                    "restart_count": self.agent_restart_count.get(agent_id, 0),
                    "stderr_tail": handle.stderr_tail[-800:],
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                    "started_at_epoch": started_epoch,
                }
            )
        return active

    def _index_status(self) -> dict[str, Any]:
        snapshot = self.layout["root"] / "index.snapshot.json"
        file_count = 0
        raw = read_json(snapshot, default={})
        if isinstance(raw, dict) and isinstance(raw.get("files"), list):
            file_count = len(raw["files"])
        return {"status": "healthy", "snapshot": snapshot.name, "file_count": file_count}

    def _append_task(self, task: TaskSpec) -> None:
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        self.manifest.tasks.append(task)
        self.task_state[task.task_id] = task.status
        self.task_attempts.setdefault(task.task_id, 0)
        self._persist_task(task)
        write_json_atomic(self.layout["manifest"], self.manifest.to_dict())
        self._append_event(
            "task.created",
            {
                "task_id": task.task_id,
                "task_kind": task.task_kind,
                "role_hint": task.role_hint,
                "deps": task.deps,
            },
        )

    def _persist_task(
        self,
        task: TaskSpec,
        *,
        status: str | None = None,
        last_error: str | None = None,
        assigned_agent_id: str | None = None,
    ) -> None:
        current_status = status or self.task_state.get(task.task_id, task.status)
        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "deps": task.deps,
            "role_hint": task.role_hint,
            "task_kind": task.task_kind,
            "status": current_status,
            "owner_role": task.role_hint,
            "artifacts": task.artifacts,
            "attempts": self.task_attempts.get(task.task_id, 0),
            "last_error": last_error,
            "assigned_agent_id": assigned_agent_id,
            "transitions": [x for x in self.transition_log if x.get("task_id") == task.task_id][-30:],
            "validation": self._validation_snapshot(task.task_id),
            "updated_at": utc_now_iso(),
        }
        write_json_atomic(self.layout["tasks"] / f"task-{task.task_id}.json", payload)

    def _validation_snapshot(self, task_id: str) -> dict[str, Any]:
        review_ids = [
            t.task_id
            for t in (self.manifest.tasks if self.manifest else [])
            if task_id in t.deps and t.task_kind in {"judge", "critic"}
        ]
        statuses = {rid: self.task_state.get(rid, "pending") for rid in review_ids}
        return {"review_task_ids": review_ids, "statuses": statuses}

    def _build_index_snapshot(self) -> None:
        try:
            index = CodeIndex.build(Path(self.config.run.working_dir))
            index.save(self.layout["root"] / "index.snapshot.json")
        except Exception as exc:
            log.warning("index snapshot build failed — continuing without it", exc_info=True)
            self._append_event("index.snapshot_failed", {
                "reason": "build_error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            })

    def _decompose_initial_tasks(self, roles: list[RoleSpec]) -> list[TaskSpec]:
        mode = self.config.orchestration.decomposition
        if mode == "manual":
            return [
                TaskSpec(
                    task_id="t0",
                    title="Primary objective",
                    description=self.goal,
                    role_hint=roles[0].role_id if roles else None,
                    task_kind="implement",
                    status="ready",
                )
            ]

        if mode == "fast":
            role_worker = next(
                (r.role_id for r in roles if r.role_type == "worker"),
                roles[0].role_id if roles else None,
            )
            tasks: list[TaskSpec] = [
                TaskSpec(
                    task_id="t0",
                    title="Implement core changes",
                    description=self.goal,
                    role_hint=role_worker,
                    task_kind="implement",
                    status="ready",
                ),
            ]
            worker_count = sum(r.count for r in roles if r.role_type == "worker")
            if worker_count > 1:
                tasks.append(
                    TaskSpec(
                        task_id="t1",
                        title="Add/adjust tests",
                        description="Add tests that validate behavior and edge cases.",
                        deps=["t0"],
                        role_hint=role_worker,
                        task_kind="test",
                        status="pending",
                    )
                )
            integrate_deps = [t.task_id for t in tasks]
            tasks.append(
                TaskSpec(
                    task_id=f"t{len(tasks)}",
                    title="Integrate and finalize",
                    description="Integrate implementation and tests into coherent final output.",
                    deps=integrate_deps,
                    role_hint=role_worker,
                    task_kind="integrate",
                    status="pending",
                )
            )
            return tasks[: max(1, self.config.orchestration.max_tasks)]

        if mode == "parallel":
            return self._decompose_parallel(roles)

        # LLM mode falls back to parallel (not heuristic) so workers start immediately.
        if mode == "llm":
            self._append_event(
                "decomposition.fallback",
                {"reason": "llm_planner_not_configured", "mode": "parallel"},
            )
            return self._decompose_parallel(roles)

        # Unknown mode string → default pipeline
        if mode not in ("heuristic", "file"):
            self._append_event(
                "decomposition.fallback",
                {"reason": "unknown_mode", "mode": mode, "using": "default_pipeline"},
            )
        max_tasks = max(1, self.config.orchestration.max_tasks)
        role_worker = next((r.role_id for r in roles if r.role_type == "worker"), roles[0].role_id if roles else None)
        role_judge = next((r.role_id for r in roles if r.role_type == "judge"), None)
        role_critic = next((r.role_id for r in roles if r.role_type == "critic"), None)
        role_research = next((r.role_id for r in roles if r.role_type in {"researcher", "orchestrator"}), None)

        base: list[TaskSpec] = [
            TaskSpec(
                task_id="t0",
                title="Analyze goal and constraints",
                description=f"Analyze objective and identify required modules: {self.goal}",
                role_hint=role_research or role_worker,
                task_kind="analysis",
                status="pending",
            ),
            TaskSpec(
                task_id="t1",
                title="Design implementation plan",
                description="Design concrete implementation and file-level plan.",
                deps=["t0"],
                role_hint=role_research or role_worker,
                task_kind="design",
                status="pending",
            ),
            TaskSpec(
                task_id="t2",
                title="Implement core changes",
                description=self.goal,
                deps=["t1"],
                role_hint=role_worker,
                task_kind="implement",
                status="pending",
            ),
            TaskSpec(
                task_id="t3",
                title="Add/adjust tests",
                description="Add tests that validate behavior and edge cases.",
                deps=["t1"],
                role_hint=role_worker,
                task_kind="test",
                status="pending",
            ),
            TaskSpec(
                task_id="t4",
                title="Integrate and finalize",
                description="Integrate implementation and tests into coherent final output.",
                deps=["t2", "t3"],
                role_hint=role_worker,
                task_kind="integrate",
                status="pending",
            ),
        ]

        if role_judge:
            base.append(
                TaskSpec(
                    task_id="t5",
                    title="Judge final quality",
                    description="Evaluate correctness, completeness, and clarity.",
                    deps=["t4"],
                    role_hint=role_judge,
                    task_kind="judge",
                    status="pending",
                )
            )
        if role_critic:
            deps = ["t4"] + (["t5"] if role_judge else [])
            base.append(
                TaskSpec(
                    task_id="t6",
                    title="Critic risk review",
                    description="Identify contradictions, weak assumptions, and regressions.",
                    deps=deps,
                    role_hint=role_critic,
                    task_kind="critic",
                    status="pending",
                )
            )

        tasks = base[:max_tasks]
        for task in tasks:
            task.status = "pending"
        # first task ready for immediate dispatch
        if tasks:
            tasks[0].status = "ready"
        return tasks

    def _decompose_parallel(self, roles: list[RoleSpec]) -> list[TaskSpec]:
        """Create N independent impl tasks that all start as 'ready'.

        Each worker gets an impl task immediately — no sequential pipeline.
        A single integrate task runs after all impl tasks complete.
        Judge/critic tasks are appended after integrate if those roles exist.
        """
        max_tasks = max(1, self.config.orchestration.max_tasks)
        role_worker = next(
            (r.role_id for r in roles if r.role_type == "worker"),
            roles[0].role_id if roles else None,
        )
        role_judge = next((r.role_id for r in roles if r.role_type == "judge"), None)
        role_critic = next((r.role_id for r in roles if r.role_type == "critic"), None)
        worker_count = sum(r.count for r in roles if r.role_type == "worker")

        # With 1 worker, degrade to a single impl task (like fast mode).
        if worker_count <= 1:
            tasks: list[TaskSpec] = [
                TaskSpec(
                    task_id="t0",
                    title="Implement full objective",
                    description=self.goal,
                    role_hint=role_worker,
                    task_kind="implement",
                    status="ready",
                ),
            ]
            return tasks[:max_tasks]

        # Build focus areas based on worker count.
        focus_areas: list[tuple[str, str]] = [
            ("Implement core logic and main features", "implement"),
            ("Implement tests and edge cases", "test"),
        ]
        if worker_count >= 3:
            focus_areas.append(("Implement integration, docs, and auxiliary modules", "implement"))
        for extra in range(3, worker_count):
            focus_areas.append((f"Implement additional scope (area {extra + 1})", "implement"))

        parallel_tasks = focus_areas[:worker_count]

        impl_tasks: list[TaskSpec] = []
        for i, (focus, kind) in enumerate(parallel_tasks):
            task = TaskSpec(
                task_id=f"t{i}",
                title=focus,
                description=(
                    f"{self.goal}\n\n"
                    f"Focus area: {focus}. "
                    "Do not modify files outside your scope unless necessary for your task."
                ),
                role_hint=role_worker,
                task_kind=kind,
                status="ready",
            )
            impl_tasks.append(task)

        integrate_idx = len(impl_tasks)
        integrate_task = TaskSpec(
            task_id=f"t{integrate_idx}",
            title="Integrate and finalize",
            description="Integrate all parallel work into coherent final output. Run tests, fix conflicts.",
            deps=[t.task_id for t in impl_tasks],
            role_hint=role_worker,
            task_kind="integrate",
            status="pending",
        )

        all_tasks: list[TaskSpec] = [*impl_tasks, integrate_task]
        next_idx = integrate_idx + 1

        if role_judge:
            all_tasks.append(
                TaskSpec(
                    task_id=f"t{next_idx}",
                    title="Judge final quality",
                    description="Evaluate correctness, completeness, and clarity.",
                    deps=[integrate_task.task_id],
                    role_hint=role_judge,
                    task_kind="judge",
                    status="pending",
                )
            )
            next_idx += 1

        if role_critic:
            critic_deps = [integrate_task.task_id]
            if role_judge:
                critic_deps.append(f"t{next_idx - 1}")
            all_tasks.append(
                TaskSpec(
                    task_id=f"t{next_idx}",
                    title="Critic risk review",
                    description="Identify contradictions, weak assumptions, and regressions.",
                    deps=critic_deps,
                    role_hint=role_critic,
                    task_kind="critic",
                    status="pending",
                )
            )

        self._append_event(
            "decomposition.parallel",
            {
                "worker_count": worker_count,
                "parallel_tasks": len(impl_tasks),
                "total_tasks": len(all_tasks),
            },
        )
        return all_tasks[:max_tasks]

    def _transition_task(self, task_id: str, to_state: str, actor: str, reason: str) -> None:
        current = self.task_state.get(task_id, "pending")
        if current == to_state:
            return
        allowed = TRANSITIONS.get(current, set())
        if to_state not in allowed:
            self._error("invalid_transition", f"{task_id}: {current}->{to_state} by {actor}")
            return
        self.task_state[task_id] = to_state
        # Find assigned agent for this task
        assigned_agent = ""
        for aid, tid in self.running_task_by_agent.items():
            if tid == task_id:
                assigned_agent = aid
                break
        transition = {
            "task_id": task_id,
            "from_state": current,
            "to_state": to_state,
            "actor": actor,
            "reason": reason,
            "assigned_agent": assigned_agent,
            "timestamp": utc_now_iso(),
        }
        self.transition_log.append(transition)
        self._append_event("task.transition", transition)

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        item = {
            "timestamp": utc_now_iso(),
            "type": event_type,
            "run_id": self.run_id,
            "payload": payload,
        }
        append_jsonl(self.layout["events"], item)

    def _error(self, category: str, message: str) -> None:
        item = {
            "timestamp": utc_now_iso(),
            "category": category,
            "message": message,
            "severity": "error",
        }
        self.errors.append(item)
        self._append_event("error", item)

    def _find_task(self, task_id: str) -> TaskSpec | None:
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        return next((t for t in self.manifest.tasks if t.task_id == task_id), None)

    def _review_roles(self) -> list[str]:
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        ids = [r.role_id for r in self.manifest.roles if r.role_type in {"judge", "critic"}]
        if not ids and self.config.merge.judge_roles:
            ids.extend(self.config.merge.judge_roles)
        return ids

    def _role_type(self, role_id: str) -> str:
        if self.manifest is None:
            raise RuntimeError("Manifest not initialized — cannot proceed")
        for role in self.manifest.roles:
            if role.role_id == role_id:
                return role.role_type
        return "worker"

    def _role_type_by_agent(self, agent_id: str) -> str:
        role = self.role_by_agent.get(agent_id)
        return role.role_type if role else "worker"

    def _exit_reason(self, agent_id: str, base_reason: str) -> str:
        handle = self.handles.get(agent_id)
        if not handle:
            return base_reason
        code = handle.process.returncode
        stderr_tail = (handle.stderr_tail or "").strip().replace("\n", " | ")
        if stderr_tail:
            stderr_tail = stderr_tail[:400]
            return f"{base_reason}; exit_code={code}; stderr={stderr_tail}"
        return f"{base_reason}; exit_code={code}"

    @staticmethod
    def _build_heartbeat_script(agent_cmd: str, *, debug: bool = False) -> str:
        """Wrap *agent_cmd* with a background heartbeat and stdin isolation.

        The wrapper:
        1. Emits an immediate ``[HEARTBEAT]`` on startup so the coordinator
           knows the shell process started.
        2. Spawns a background loop that prints ``[HEARTBEAT]`` every 5 s so
           the coordinator knows the agent is still alive.
        3. Redirects the agent's stdin from ``/dev/null`` to prevent it from
           accidentally consuming the next task line (or blocking on a prompt).
        4. Captures the exit code so ``[TASK_DONE]``/``[TASK_FAILED]`` is
           emitted correctly.

        When *debug* is ``True``, extra ``[DEBUG:*]`` markers are emitted so
        that the operator can see exactly what the wrapper is doing.  Agent
        stderr is also merged into stdout (``2>&1``) so debug output includes
        any error messages from the subprocess.
        """
        if debug:
            return (
                "echo \"[HEARTBEAT]\"; "
                "while IFS= read -r line; do "
                "[ -z \"$line\" ] && continue; "
                "echo \"[DEBUG:STDIN_READ] $(date +%s) len=${#line}\"; "
                "(while true; do sleep 5; echo \"[HEARTBEAT]\"; done) & "
                "_hb=$!; "
                "echo \"[DEBUG:CMD_START] $(date +%s)\"; "
                f"{agent_cmd} 2>&1 < /dev/null; "
                "_rc=$?; "
                "echo \"[DEBUG:CMD_EXIT] $(date +%s) rc=$_rc\"; "
                "kill $_hb 2>/dev/null; wait $_hb 2>/dev/null; "
                "if [ $_rc -eq 0 ]; then echo \"[TASK_DONE]\"; else echo \"[TASK_FAILED]\"; fi; "
                "done"
            )
        return (
            "echo \"[HEARTBEAT]\"; "
            "while IFS= read -r line; do "
            "[ -z \"$line\" ] && continue; "
            "(while true; do sleep 5; echo \"[HEARTBEAT]\"; done) & "
            "_hb=$!; "
            f"{agent_cmd} < /dev/null; "
            "_rc=$?; "
            "kill $_hb 2>/dev/null; wait $_hb 2>/dev/null; "
            "if [ $_rc -eq 0 ]; then echo \"[TASK_DONE]\"; else echo \"[TASK_FAILED]\"; fi; "
            "done"
        )

    def _default_command(self, backend: str, model: str) -> list[str]:
        # Only pass --model when the config explicitly provides one.
        # Empty string means "use the tool's own default".
        model_flag = f"--model {shlex.quote(model)} " if model else ""
        debug = self.config.run.debug

        if backend == "claude":
            agent_cmd = f"claude -p {model_flag}--dangerously-skip-permissions \"$line\""
            return ["sh", "-c", self._build_heartbeat_script(agent_cmd, debug=debug)]
        if backend == "codex":
            agent_cmd = (
                "codex exec --json --skip-git-repo-check --sandbox workspace-write "
                + model_flag
                + "\"$line\""
            )
            return ["sh", "-c", self._build_heartbeat_script(agent_cmd, debug=debug)]
        if backend == "aider":
            agent_cmd = f"aider {model_flag}--message \"$line\""
            return ["sh", "-c", self._build_heartbeat_script(agent_cmd, debug=debug)]
        if backend == "attocode":
            agent_cmd = f"attocode {model_flag}--non-interactive \"$line\""
            return ["sh", "-c", self._build_heartbeat_script(agent_cmd, debug=debug)]
        if backend == "codex-mcp":
            return ["codex", "mcp-server"]
        raise ValueError(f"Unsupported backend: {backend}")

    def _role_command(self, role: RoleSpec) -> list[str]:
        cfg = self.role_cfg_by_role_id.get(role.role_id)
        if cfg and cfg.command:
            return cfg.command
        return self._default_command(role.backend, role.model)
