"""Helpers for shutdown/resume summaries."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from attoswarm.config.loader import load_swarm_yaml
from attoswarm.protocol.io import read_json

logger = logging.getLogger(__name__)


def resolve_working_dir(run_dir: str | Path, state: dict[str, Any] | None = None) -> Path | None:
    """Best-effort repo root resolution for a swarm run."""
    run_path = Path(run_dir)
    state = state or {}

    direct = _normalize_working_dir(state.get("working_dir"), run_path)
    if direct:
        return direct

    for agent in state.get("active_agents", []):
        if not isinstance(agent, dict):
            continue
        direct = _normalize_working_dir(agent.get("cwd"), run_path)
        if direct:
            return direct

    heuristic = _heuristic_root(run_path)
    if heuristic:
        return heuristic

    cfg_path = run_path / "swarm.yaml"
    if cfg_path.exists():
        try:
            cfg = load_swarm_yaml(cfg_path)
        except (OSError, ValueError):
            return None
        return _normalize_working_dir(cfg.run.working_dir, run_path)

    return None


def collect_modified_files(run_dir: str | Path, state: dict[str, Any] | None = None) -> list[str]:
    """Return best-effort modified file paths for a swarm run."""
    run_path = Path(run_dir)
    runtime_prefixes = _runtime_prefixes(run_path, state)

    changed = _filter_runtime_files(_changed_files_from_manifest(run_path / "changes.json"), runtime_prefixes)
    if changed:
        return changed

    changed = _filter_runtime_files(_changed_files_from_tasks(run_path / "tasks"), runtime_prefixes)
    if changed:
        return changed

    working_dir = resolve_working_dir(run_path, state)
    if not working_dir:
        return []
    return _filter_runtime_files(_changed_files_from_git(working_dir), runtime_prefixes)


def _runtime_prefixes(run_dir: Path, state: dict[str, Any] | None = None) -> list[str]:
    working_dir = resolve_working_dir(run_dir, state)
    if not working_dir:
        return [".agent"]

    prefixes: set[str] = set()
    try:
        rel = run_dir.resolve().relative_to(working_dir.resolve()).as_posix()
    except ValueError:
        rel = ""

    if rel:
        prefixes.add(rel)
        if rel == ".agent" or rel.startswith(".agent/"):
            prefixes.add(".agent")
    else:
        prefixes.add(".agent")
    return sorted(prefixes)


def _filter_runtime_files(files: list[str], runtime_prefixes: list[str]) -> list[str]:
    if not runtime_prefixes:
        return files
    filtered: list[str] = []
    for path in files:
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in runtime_prefixes):
            continue
        filtered.append(path)
    return filtered


def _normalize_working_dir(raw: Any, run_dir: Path) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (run_dir / raw).resolve()
    else:
        path = path.resolve()
    return path if path.exists() else None


def _heuristic_root(run_dir: Path) -> Path | None:
    if run_dir.parent.name != ".agent":
        return None
    candidate = run_dir.parent.parent.resolve()
    return candidate if candidate.exists() else None


def _changed_files_from_manifest(path: Path) -> list[str]:
    raw = read_json(path, default=[])
    if not isinstance(raw, list):
        return []
    files = sorted({
        str(item.get("file_path", "")).strip()
        for item in raw
        if isinstance(item, dict) and str(item.get("file_path", "")).strip()
    })
    return files


def _changed_files_from_tasks(tasks_dir: Path) -> list[str]:
    if not tasks_dir.exists():
        return []
    files: set[str] = set()
    for task_path in tasks_dir.glob("task-*.json"):
        task = read_json(task_path, default={})
        if not isinstance(task, dict):
            continue
        for fp in task.get("files_modified", []):
            if isinstance(fp, str) and fp.strip():
                files.add(fp.strip())
    return sorted(files)


def _changed_files_from_git(working_dir: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    files: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.add(path)
    return sorted(files)


# ---------------------------------------------------------------------------
# Timeout statistics
# ---------------------------------------------------------------------------


def collect_timeout_stats(run_dir: str | Path) -> dict[str, Any]:
    """Scan agent trace files and return timeout/near-timeout counts.

    Returns a dict with:
      - timed_out:      number of tasks that hit the timeout wall
      - near_timeout:   number of tasks that completed but used >90% of timeout
      - zero_token:     number of tasks that reported success with 0 tokens
      - timed_out_ids:  list of task IDs that timed out
      - near_timeout_ids: list of task IDs that were near timeout
      - zero_token_ids:  list of task IDs with suspicious zero-token results
    """
    agents_dir = Path(run_dir) / "agents"
    stats: dict[str, Any] = {
        "timed_out": 0,
        "near_timeout": 0,
        "zero_token": 0,
        "timed_out_ids": [],
        "near_timeout_ids": [],
        "zero_token_ids": [],
    }
    if not agents_dir.is_dir():
        return stats

    for trace_path in agents_dir.glob("*.trace.jsonl"):
        try:
            with trace_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    data = entry.get("data", {})
                    if not isinstance(data, dict):
                        continue
                    entry_type = entry.get("entry_type", "")
                    task_id = entry.get("task_id", "")

                    # Only inspect cost_delta / error entries (final result traces)
                    if entry_type not in ("cost_delta", "error"):
                        continue

                    if data.get("timed_out"):
                        stats["timed_out"] += 1
                        stats["timed_out_ids"].append(task_id)
                    if data.get("near_timeout"):
                        stats["near_timeout"] += 1
                        stats["near_timeout_ids"].append(task_id)
                    # Zero-token on successful entries only
                    if entry_type == "cost_delta" and data.get("tokens_used", -1) == 0:
                        stats["zero_token"] += 1
                        stats["zero_token_ids"].append(task_id)
        except OSError:
            continue

    return stats
