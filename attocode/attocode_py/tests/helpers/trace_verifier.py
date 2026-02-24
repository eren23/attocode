"""TraceVerifier — loads a swarm run directory and runs integrity assertions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from attoswarm.coordinator.loop import TRANSITIONS
from attoswarm.protocol.io import read_json


# Markers that should never appear in raw agent output — they indicate
# the agent is echoing/injecting control signals.
POISONED_MARKERS: frozenset[str] = frozenset({
    "[TASK_DONE]",
    "[TASK_FAILED]",
    "[HEARTBEAT]",
    "[CONTROL]",
    "[EXIT]",
})


@dataclass
class VerificationResult:
    """Outcome of a single verification check."""

    check: str
    passed: bool
    details: str = ""
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        base = f"[{status}] {self.check}"
        if self.details:
            base += f" — {self.details}"
        if self.violations:
            base += "\n  " + "\n  ".join(self.violations[:10])
            if len(self.violations) > 10:
                base += f"\n  ... and {len(self.violations) - 10} more"
        return base


class TraceVerifier:
    """Load a run directory and expose assertion methods.

    Usage::

        v = TraceVerifier("/path/to/run_abc123")
        results = v.run_all()
        for r in results:
            print(r)
    """

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.state: dict[str, Any] = read_json(self.run_dir / "swarm.state.json", default={})
        self.manifest: dict[str, Any] = read_json(self.run_dir / "swarm.manifest.json", default={})
        self.events: list[dict[str, Any]] = self._load_events()
        self.tasks: dict[str, dict[str, Any]] = self._load_tasks()

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _load_events(self) -> list[dict[str, Any]]:
        path = self.run_dir / "swarm.events.jsonl"
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def _load_tasks(self) -> dict[str, dict[str, Any]]:
        tasks_dir = self.run_dir / "tasks"
        if not tasks_dir.is_dir():
            return {}
        out: dict[str, dict[str, Any]] = {}
        for p in tasks_dir.glob("task-*.json"):
            data = read_json(p, default={})
            tid = data.get("task_id", p.stem.removeprefix("task-"))
            out[tid] = data
        return out

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def assert_no_poisoned_prompts(self) -> VerificationResult:
        """Scan agent.event log lines for control markers that should not
        appear in raw agent output."""
        violations: list[str] = []
        for i, ev in enumerate(self.events):
            if ev.get("type") != "agent.event":
                continue
            payload = ev.get("payload", {})
            msg = str(payload.get("message", ""))
            for marker in POISONED_MARKERS:
                if marker in msg:
                    violations.append(
                        f"event[{i}] agent={payload.get('agent_id', '?')} "
                        f"contains '{marker}' in message"
                    )
        return VerificationResult(
            check="no_poisoned_prompts",
            passed=len(violations) == 0,
            details=f"scanned {sum(1 for e in self.events if e.get('type') == 'agent.event')} agent.event entries",
            violations=violations,
        )

    def assert_correct_task_transitions(self) -> VerificationResult:
        """Verify every task.transition event follows the canonical FSM."""
        violations: list[str] = []
        for i, ev in enumerate(self.events):
            if ev.get("type") != "task.transition":
                continue
            payload = ev.get("payload", {})
            from_state = payload.get("from_state", "")
            to_state = payload.get("to_state", "")
            task_id = payload.get("task_id", "?")

            allowed = TRANSITIONS.get(from_state)
            if allowed is None:
                violations.append(
                    f"event[{i}] task={task_id}: unknown from_state '{from_state}'"
                )
            elif to_state not in allowed:
                violations.append(
                    f"event[{i}] task={task_id}: illegal transition "
                    f"'{from_state}' -> '{to_state}' (allowed: {sorted(allowed)})"
                )
        return VerificationResult(
            check="correct_task_transitions",
            passed=len(violations) == 0,
            details=f"checked {sum(1 for e in self.events if e.get('type') == 'task.transition')} transitions",
            violations=violations,
        )

    def assert_all_tasks_have_terminal_events(self) -> VerificationResult:
        """Every 'done' task should have agent.task.exit and
        agent.task.classified events."""
        done_tasks = {tid for tid, t in self.tasks.items() if t.get("status") == "done"}
        exit_tasks: set[str] = set()
        classified_tasks: set[str] = set()

        for ev in self.events:
            etype = ev.get("type", "")
            payload = ev.get("payload", {})
            tid = payload.get("task_id", "")
            if etype == "agent.task.exit":
                exit_tasks.add(tid)
            elif etype == "agent.task.classified":
                classified_tasks.add(tid)

        missing_exit = done_tasks - exit_tasks
        missing_classified = done_tasks - classified_tasks
        violations: list[str] = []
        for tid in sorted(missing_exit):
            violations.append(f"task={tid}: missing agent.task.exit event")
        for tid in sorted(missing_classified):
            violations.append(f"task={tid}: missing agent.task.classified event")

        return VerificationResult(
            check="all_tasks_have_terminal_events",
            passed=len(violations) == 0,
            details=f"{len(done_tasks)} done tasks checked",
            violations=violations,
        )

    def assert_no_stuck_agents(self, max_gap_seconds: float = 30.0) -> VerificationResult:
        """No heartbeat gap > max_gap_seconds between consecutive
        agent.event entries for the same agent."""
        # Group events by agent
        agent_times: dict[str, list[str]] = {}
        for ev in self.events:
            if ev.get("type") != "agent.event":
                continue
            payload = ev.get("payload", {})
            aid = payload.get("agent_id", "")
            ts = ev.get("timestamp", "")
            if aid and ts:
                agent_times.setdefault(aid, []).append(ts)

        violations: list[str] = []
        for aid, timestamps in agent_times.items():
            parsed: list[datetime] = []
            for ts in timestamps:
                try:
                    parsed.append(datetime.fromisoformat(ts))
                except ValueError:
                    continue
            parsed.sort()
            for i in range(1, len(parsed)):
                gap = (parsed[i] - parsed[i - 1]).total_seconds()
                if gap > max_gap_seconds:
                    violations.append(
                        f"agent={aid}: gap of {gap:.1f}s between "
                        f"{parsed[i-1].isoformat()} and {parsed[i].isoformat()}"
                    )

        return VerificationResult(
            check="no_stuck_agents",
            passed=len(violations) == 0,
            details=f"checked {len(agent_times)} agents",
            violations=violations,
        )

    def assert_budget_within_limits(self) -> VerificationResult:
        """tokens_used <= tokens_max and cost_used <= cost_max."""
        budget = self.state.get("budget", {})
        tokens_used = budget.get("tokens_used", 0)
        tokens_max = budget.get("tokens_max", 0)
        cost_used = budget.get("cost_used_usd", 0.0)
        cost_max = budget.get("cost_max_usd", 0.0)

        violations: list[str] = []
        if tokens_max > 0 and tokens_used > tokens_max:
            violations.append(
                f"tokens: {tokens_used} used > {tokens_max} max"
            )
        if cost_max > 0 and cost_used > cost_max:
            violations.append(
                f"cost: ${cost_used:.4f} used > ${cost_max:.4f} max"
            )

        return VerificationResult(
            check="budget_within_limits",
            passed=len(violations) == 0,
            details=f"tokens={tokens_used}/{tokens_max} cost=${cost_used:.4f}/${cost_max:.4f}",
            violations=violations,
        )

    def assert_exit_codes_propagated(self) -> VerificationResult:
        """No tasks left in 'running' when the agent assigned to them has
        a non-null exit code."""
        active_agents = self.state.get("active_agents", [])
        exited_agents: dict[str, int] = {}
        for a in active_agents:
            ec = a.get("exit_code")
            if ec is not None:
                exited_agents[a.get("agent_id", "")] = ec

        violations: list[str] = []
        dag_nodes = self.state.get("dag", {}).get("nodes", [])
        for node in dag_nodes:
            if node.get("status") != "running":
                continue
            tid = node.get("task_id", "")
            task_data = self.tasks.get(tid, {})
            assigned = task_data.get("assigned_agent_id", "")
            if assigned in exited_agents:
                violations.append(
                    f"task={tid} still 'running' but agent={assigned} "
                    f"has exit_code={exited_agents[assigned]}"
                )

        return VerificationResult(
            check="exit_codes_propagated",
            passed=len(violations) == 0,
            details=f"{len(exited_agents)} exited agents, "
                    f"{sum(1 for n in dag_nodes if n.get('status') == 'running')} running tasks",
            violations=violations,
        )

    def assert_coding_tasks_produced_output(self) -> VerificationResult:
        """Implement/test/integrate tasks that reached 'done' should show
        evidence of file operations in agent events.

        This is a heuristic check — it looks for file-related keywords in
        agent event messages. Skipped for tasks with no agent events.
        """
        coding_kinds = {"implement", "test", "integrate"}
        file_keywords = {"wrote", "created", "edited", "modified", "write_file", "edit_file", "patch"}

        violations: list[str] = []
        for tid, task_data in self.tasks.items():
            if task_data.get("status") != "done":
                continue
            if task_data.get("task_kind", "") not in coding_kinds:
                continue

            # Gather agent events for this task
            task_messages: list[str] = []
            for ev in self.events:
                payload = ev.get("payload", {})
                if payload.get("task_id") == tid and ev.get("type") == "agent.event":
                    task_messages.append(str(payload.get("message", "")))

            if not task_messages:
                # No agent events — skip (fake workers won't have these)
                continue

            combined = " ".join(task_messages).lower()
            if not any(kw in combined for kw in file_keywords):
                violations.append(
                    f"task={tid} ({task_data.get('task_kind', '')}) reached 'done' "
                    f"but no file operation evidence in {len(task_messages)} agent messages"
                )

        return VerificationResult(
            check="coding_tasks_produced_output",
            passed=len(violations) == 0,
            details=f"checked {sum(1 for t in self.tasks.values() if t.get('task_kind', '') in coding_kinds and t.get('status') == 'done')} coding tasks",
            violations=violations,
        )

    # ------------------------------------------------------------------
    # Aggregate runner
    # ------------------------------------------------------------------

    def run_all(self) -> list[VerificationResult]:
        """Run all checks and return results."""
        return [
            self.assert_no_poisoned_prompts(),
            self.assert_correct_task_transitions(),
            self.assert_all_tasks_have_terminal_events(),
            self.assert_no_stuck_agents(),
            self.assert_budget_within_limits(),
            self.assert_exit_codes_propagated(),
            self.assert_coding_tasks_produced_output(),
        ]

    def summary(self) -> str:
        """Run all checks and return a formatted summary."""
        results = self.run_all()
        lines = [f"TraceVerifier: {self.run_dir}", "=" * 60]
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        for r in results:
            lines.append(str(r))
        lines.append("=" * 60)
        lines.append(f"Total: {passed} passed, {failed} failed out of {len(results)} checks")
        return "\n".join(lines)
