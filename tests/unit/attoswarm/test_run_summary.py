from __future__ import annotations

import json
import subprocess
from pathlib import Path

from attoswarm.run_summary import collect_modified_files, resolve_working_dir


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
