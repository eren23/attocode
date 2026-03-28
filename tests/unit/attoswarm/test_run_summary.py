from __future__ import annotations

import json
import subprocess
from pathlib import Path

from attoswarm.run_summary import collect_modified_files, collect_timeout_stats, resolve_working_dir


def test_collect_modified_files_prefers_changes_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "changes.json").write_text(
        json.dumps([{"file_path": "src/a.py"}, {"file_path": "src/b.py"}]),
        encoding="utf-8",
    )

    assert collect_modified_files(run_dir, {}) == ["src/a.py", "src/b.py"]


def test_collect_modified_files_falls_back_to_task_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    tasks_dir = run_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (run_dir / "changes.json").write_text("[]", encoding="utf-8")
    (tasks_dir / "task-t1.json").write_text(
        json.dumps({"files_modified": ["src/a.py", "src/b.py"]}),
        encoding="utf-8",
    )

    assert collect_modified_files(run_dir, {}) == ["src/a.py", "src/b.py"]


def test_collect_modified_files_falls_back_to_git_status(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / ".agent" / "hybrid-swarm").mkdir(parents=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked.write_text("two\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    files = collect_modified_files(repo / ".agent" / "hybrid-swarm", {})

    assert files == ["new.txt", "tracked.txt"]


def test_collect_modified_files_excludes_runtime_artifacts_from_git_status(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    run_dir = repo / ".agent" / "hybrid-swarm"
    run_dir.mkdir(parents=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    tracked.write_text("two\n", encoding="utf-8")
    (run_dir / "swarm.state.json").write_text('{"phase":"running"}', encoding="utf-8")

    files = collect_modified_files(run_dir, {})

    assert files == ["tracked.txt"]


def test_resolve_working_dir_uses_persisted_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    resolved = resolve_working_dir(run_dir, {"working_dir": str(tmp_path)})

    assert resolved == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Helpers for collect_timeout_stats tests
# ---------------------------------------------------------------------------


def _make_trace_entry(
    task_id: str,
    entry_type: str,
    data: dict,
    agent_id: str = "agent-1",
) -> str:
    """Return a single JSONL line matching the subagent_manager trace format."""
    entry = {
        "timestamp": 1711600000.0,
        "agent_id": agent_id,
        "task_id": task_id,
        "entry_type": entry_type,
        "data": data,
        "trace_id": "",
        "span_id": "",
    }
    return json.dumps(entry)


def _write_trace_file(agents_dir: Path, task_id: str, lines: list[str]) -> None:
    """Write a .trace.jsonl file into the agents directory."""
    trace_path = agents_dir / f"agent-{task_id}.trace.jsonl"
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# collect_timeout_stats tests
# ---------------------------------------------------------------------------


def test_timeout_stats_returns_zeros_when_no_trace_files(tmp_path: Path) -> None:
    """agents/ dir exists but is empty -- all counters should be zero."""
    run_dir = tmp_path / "run"
    (run_dir / "agents").mkdir(parents=True)

    stats = collect_timeout_stats(run_dir)

    assert stats["timed_out"] == 0
    assert stats["near_timeout"] == 0
    assert stats["zero_token"] == 0
    assert stats["timed_out_ids"] == []
    assert stats["near_timeout_ids"] == []
    assert stats["zero_token_ids"] == []


def test_timeout_stats_returns_zeros_when_agents_dir_missing(tmp_path: Path) -> None:
    """run_dir exists but agents/ subdirectory does not."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    stats = collect_timeout_stats(run_dir)

    assert stats["timed_out"] == 0
    assert stats["near_timeout"] == 0
    assert stats["zero_token"] == 0


def test_timeout_stats_counts_timed_out_tasks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    agents_dir = run_dir / "agents"
    agents_dir.mkdir(parents=True)

    # Task that timed out (entry_type=error, timed_out=True)
    _write_trace_file(agents_dir, "task-1", [
        _make_trace_entry("task-1", "error", {
            "cost_usd": 0.01,
            "tokens_used": 500,
            "duration_s": 120.0,
            "files_modified": [],
            "error": "timeout exceeded",
            "timed_out": True,
            "near_timeout": False,
        }),
    ])

    # Task that completed normally (no timeout flags)
    _write_trace_file(agents_dir, "task-2", [
        _make_trace_entry("task-2", "cost_delta", {
            "cost_usd": 0.02,
            "tokens_used": 1000,
            "duration_s": 30.0,
            "files_modified": ["src/a.py"],
            "error": "",
            "timed_out": False,
            "near_timeout": False,
        }),
    ])

    stats = collect_timeout_stats(run_dir)

    assert stats["timed_out"] == 1
    assert stats["near_timeout"] == 0
    assert stats["zero_token"] == 0


def test_timeout_stats_counts_near_timeout_tasks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    agents_dir = run_dir / "agents"
    agents_dir.mkdir(parents=True)

    _write_trace_file(agents_dir, "task-1", [
        _make_trace_entry("task-1", "cost_delta", {
            "cost_usd": 0.05,
            "tokens_used": 2000,
            "duration_s": 110.0,
            "files_modified": ["src/b.py"],
            "error": "",
            "timed_out": False,
            "near_timeout": True,
        }),
    ])

    stats = collect_timeout_stats(run_dir)

    assert stats["near_timeout"] == 1
    assert stats["timed_out"] == 0


def test_timeout_stats_counts_zero_token_tasks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    agents_dir = run_dir / "agents"
    agents_dir.mkdir(parents=True)

    # Successful task (cost_delta) with tokens_used=0 -- suspicious
    _write_trace_file(agents_dir, "task-1", [
        _make_trace_entry("task-1", "cost_delta", {
            "cost_usd": 0.0,
            "tokens_used": 0,
            "duration_s": 1.0,
            "files_modified": [],
            "error": "",
            "timed_out": False,
            "near_timeout": False,
        }),
    ])

    # Error entry with tokens_used=0 should NOT count as zero_token
    # (the function only checks cost_delta entries for zero-token)
    _write_trace_file(agents_dir, "task-2", [
        _make_trace_entry("task-2", "error", {
            "cost_usd": 0.0,
            "tokens_used": 0,
            "duration_s": 0.5,
            "files_modified": [],
            "error": "some error",
            "timed_out": False,
            "near_timeout": False,
        }),
    ])

    stats = collect_timeout_stats(run_dir)

    assert stats["zero_token"] == 1
    assert "task-1" in stats["zero_token_ids"]
    assert "task-2" not in stats["zero_token_ids"]


def test_timeout_stats_returns_correct_task_ids(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    agents_dir = run_dir / "agents"
    agents_dir.mkdir(parents=True)

    # Timed-out task
    _write_trace_file(agents_dir, "task-alpha", [
        _make_trace_entry("task-alpha", "error", {
            "cost_usd": 0.01,
            "tokens_used": 100,
            "duration_s": 120.0,
            "files_modified": [],
            "error": "timeout",
            "timed_out": True,
            "near_timeout": False,
        }),
    ])

    # Near-timeout task
    _write_trace_file(agents_dir, "task-beta", [
        _make_trace_entry("task-beta", "cost_delta", {
            "cost_usd": 0.03,
            "tokens_used": 1500,
            "duration_s": 108.0,
            "files_modified": [],
            "error": "",
            "timed_out": False,
            "near_timeout": True,
        }),
    ])

    # Zero-token task
    _write_trace_file(agents_dir, "task-gamma", [
        _make_trace_entry("task-gamma", "cost_delta", {
            "cost_usd": 0.0,
            "tokens_used": 0,
            "duration_s": 0.1,
            "files_modified": [],
            "error": "",
            "timed_out": False,
            "near_timeout": False,
        }),
    ])

    # Normal task -- should not appear in any list
    _write_trace_file(agents_dir, "task-delta", [
        _make_trace_entry("task-delta", "cost_delta", {
            "cost_usd": 0.02,
            "tokens_used": 800,
            "duration_s": 45.0,
            "files_modified": ["src/c.py"],
            "error": "",
            "timed_out": False,
            "near_timeout": False,
        }),
    ])

    # Non-result entry type (should be skipped entirely)
    _write_trace_file(agents_dir, "task-epsilon", [
        _make_trace_entry("task-epsilon", "llm_request", {
            "model": "claude-3",
        }),
    ])

    stats = collect_timeout_stats(run_dir)

    assert stats["timed_out"] == 1
    assert stats["timed_out_ids"] == ["task-alpha"]

    assert stats["near_timeout"] == 1
    assert stats["near_timeout_ids"] == ["task-beta"]

    assert stats["zero_token"] == 1
    assert stats["zero_token_ids"] == ["task-gamma"]
