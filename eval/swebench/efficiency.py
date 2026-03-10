"""Swarm efficiency extractor from run artifacts.

Analyzes attoswarm run directories to compute efficiency metrics:
- Parallelism utilization
- Critical path ratio
- Retry success rate
- Budget accuracy
- Task completion rate
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EfficiencyMetrics:
    """Efficiency metrics for a single swarm run."""

    run_id: str = ""

    # Parallelism: sum(agent_active_time) / (wall_time * max_concurrency)
    parallelism_utilization: float = 0.0

    # Critical path: critical_path_tasks / total_tasks
    critical_path_ratio: float = 0.0

    # Retry: retries_succeeded / total_retries
    retry_success_rate: float = 0.0

    # Budget: actual_tokens / budgeted_tokens
    budget_accuracy: float = 0.0

    # Task completion: done_tasks / total_tasks
    task_completion_rate: float = 0.0

    # Raw numbers
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    retried_tasks: int = 0
    retries_succeeded: int = 0
    wall_time_seconds: float = 0.0
    total_agent_time_seconds: float = 0.0
    max_concurrency: int = 1
    tokens_budgeted: int = 0
    tokens_used: int = 0


def extract_efficiency(run_dir: str) -> EfficiencyMetrics:
    """Extract efficiency metrics from a swarm run directory.

    Expected structure:
        run_dir/
            swarm.state.json    — final orchestrator state
            swarm.events.jsonl  — event log
    """
    metrics = EfficiencyMetrics()

    state = _load_json(os.path.join(run_dir, "swarm.state.json"))
    if not state:
        return metrics

    metrics.run_id = state.get("run_id", "")

    # Task counts: prefer dag_summary counters, fall back to dag.nodes.
    dag_summary = state.get("dag_summary", {})
    if isinstance(dag_summary, dict) and any(k in dag_summary for k in ("pending", "running", "done", "failed")):
        pending = int(dag_summary.get("pending", 0) or 0)
        running = int(dag_summary.get("running", 0) or 0)
        done = int(dag_summary.get("done", 0) or 0)
        failed = int(dag_summary.get("failed", 0) or 0)
        metrics.total_tasks = pending + running + done + failed
        metrics.completed_tasks = done
        metrics.failed_tasks = failed
    else:
        dag = state.get("dag", {})
        nodes = dag.get("nodes", []) if isinstance(dag, dict) else []
        task_list = nodes if isinstance(nodes, list) else []
        metrics.total_tasks = len(task_list)
        metrics.completed_tasks = sum(
            1 for t in task_list
            if isinstance(t, dict) and t.get("status") in ("done", "completed")
        )
        metrics.failed_tasks = sum(
            1 for t in task_list
            if isinstance(t, dict) and t.get("status") in ("failed", "error", "skipped")
        )

    # Task completion rate
    if metrics.total_tasks > 0:
        metrics.task_completion_rate = metrics.completed_tasks / metrics.total_tasks

    # Budget
    budget = state.get("budget", {})
    metrics.tokens_budgeted = budget.get("max_tokens", 0)
    metrics.tokens_used = budget.get("tokens_used", 0)
    if metrics.tokens_budgeted > 0:
        metrics.budget_accuracy = metrics.tokens_used / metrics.tokens_budgeted

    # Wall time
    metrics.wall_time_seconds = state.get("elapsed_s", 0.0)

    # Max concurrency from DAG summary
    dag = state.get("dag_summary", {})
    metrics.max_concurrency = int(dag.get("max_parallelism", 1) or 1) if isinstance(dag, dict) else 1

    # Process events for parallelism and retry metrics
    events = _load_events(os.path.join(run_dir, "swarm.events.jsonl"))
    if events:
        _process_events(metrics, events)

    # Critical path from DAG
    _compute_critical_path(metrics, state)

    return metrics


def extract_efficiency_batch(run_dirs: list[str]) -> list[EfficiencyMetrics]:
    """Extract efficiency metrics from multiple run directories."""
    return [extract_efficiency(d) for d in run_dirs if os.path.isdir(d)]


def format_efficiency_report(metrics_list: list[EfficiencyMetrics]) -> str:
    """Format efficiency metrics as a readable report."""
    lines = [
        "# Swarm Efficiency Report",
        "",
        "| Run ID | Tasks | Completion | Parallelism | Budget Acc. | Retry Rate | Wall Time |",
        "|--------|-------|------------|-------------|-------------|------------|-----------|",
    ]

    for m in metrics_list:
        lines.append(
            f"| {m.run_id[:12]} | {m.completed_tasks}/{m.total_tasks} | "
            f"{m.task_completion_rate:.0%} | {m.parallelism_utilization:.0%} | "
            f"{m.budget_accuracy:.0%} | {m.retry_success_rate:.0%} | "
            f"{m.wall_time_seconds:.0f}s |"
        )

    # Averages
    if len(metrics_list) > 1:
        avg_completion = sum(m.task_completion_rate for m in metrics_list) / len(metrics_list)
        avg_parallel = sum(m.parallelism_utilization for m in metrics_list) / len(metrics_list)
        avg_budget = sum(m.budget_accuracy for m in metrics_list) / len(metrics_list)
        lines.extend([
            "",
            f"**Averages**: Completion={avg_completion:.0%}, "
            f"Parallelism={avg_parallel:.0%}, "
            f"Budget Accuracy={avg_budget:.0%}",
        ])

    return "\n".join(lines)


def _load_json(path: str) -> dict[str, Any]:
    """Load a JSON file, returning empty dict on error."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_events(path: str) -> list[dict[str, Any]]:
    """Load events from a JSONL file."""
    if not os.path.exists(path):
        return []
    events = []
    try:
        with open(path) as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return events


def _process_events(metrics: EfficiencyMetrics, events: list[dict]) -> None:
    """Process event log to compute parallelism and retry metrics."""
    agent_starts: dict[str, float] = {}
    total_agent_time = 0.0
    retries = 0
    retry_successes = 0

    for evt in events:
        evt_type = evt.get("type") or evt.get("event_type") or ""
        ts = _to_seconds(evt.get("timestamp", 0))
        payload = evt.get("payload", {}) if isinstance(evt.get("payload"), dict) else {}

        if evt_type == "agent.started":
            agent_id = evt.get("agent_id") or payload.get("agent_id", "")
            if agent_id:
                agent_starts[agent_id] = ts

        elif evt_type == "agent.completed":
            agent_id = evt.get("agent_id") or payload.get("agent_id", "")
            if agent_id in agent_starts:
                total_agent_time += ts - agent_starts.pop(agent_id)

        elif evt_type == "task.retry":
            retries += 1

        elif evt_type == "task.retry_succeeded":
            retry_successes += 1

    metrics.total_agent_time_seconds = total_agent_time
    metrics.retried_tasks = retries
    metrics.retries_succeeded = retry_successes

    if retries > 0:
        metrics.retry_success_rate = retry_successes / retries

    # Parallelism utilization
    if metrics.wall_time_seconds > 0 and metrics.max_concurrency > 0:
        metrics.parallelism_utilization = (
            total_agent_time / (metrics.wall_time_seconds * metrics.max_concurrency)
        )


def _compute_critical_path(metrics: EfficiencyMetrics, state: dict) -> None:
    """Compute critical path ratio from DAG info."""
    dag = state.get("dag_summary", {})
    critical_path_len = dag.get("critical_path_length", 0)
    if metrics.total_tasks > 0 and critical_path_len > 0:
        metrics.critical_path_ratio = critical_path_len / metrics.total_tasks


def _to_seconds(value: Any) -> float:
    """Best-effort conversion of event timestamps to seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0
