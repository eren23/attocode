"""Tests for QW4: Atomic git commits per swarm task.

Covers:
- GitSafetyNet.create_task_commit() — staging, commit message format, error handling
- ResultPipeline integration — pipeline_git_commit called for successful tasks
- PipelineResult.commits tracking
- SwarmEvent emission with event_type="git_commit"
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from attoswarm.coordinator.event_bus import EventBus, SwarmEvent
from attoswarm.coordinator.result_pipeline import PipelineResult, ResultPipeline
from attoswarm.coordinator.subagent_manager import TaskResult
from attoswarm.workspace.git_safety import GitSafetyNet


# ── helpers ──────────────────────────────────────────────────────────


def _make_git_repo(path: Path) -> None:
    """Initialize a real git repo with an initial commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), check=True, capture_output=True,
    )
    (path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path), check=True, capture_output=True,
    )


def _git_log(path: Path, fmt: str = "%s") -> list[str]:
    """Return commit messages (one-line) from the repo at *path*."""
    result = subprocess.run(
        ["git", "log", "--format=" + fmt],
        cwd=str(path), check=True, capture_output=True, text=True,
    )
    return [line for line in result.stdout.strip().splitlines() if line]


class MockHandlers:
    """Mock PipelineHandlers with git commit support."""

    def __init__(self, commit_results: dict[str, str] | None = None) -> None:
        self.budget_updates: list[str] = []
        self.learnings: list[str] = []
        self.diffs: list[str] = []
        self.projections: int = 0
        self.dag_updates: list[tuple[str, bool]] = []
        self._commit_results = commit_results or {}

    async def pipeline_update_budget(self, result: TaskResult) -> None:
        self.budget_updates.append(result.task_id)

    async def pipeline_test_verify(self, result: TaskResult) -> bool:
        return True

    async def pipeline_syntax_verify(self, result: TaskResult) -> bool:
        return True

    async def pipeline_record_learning(self, result: TaskResult) -> None:
        self.learnings.append(result.task_id)

    async def pipeline_capture_diff(self, result: TaskResult) -> None:
        self.diffs.append(result.task_id)

    async def pipeline_run_projection(self) -> None:
        self.projections += 1

    async def pipeline_update_dag(self, result: TaskResult, success: bool) -> int:
        self.dag_updates.append((result.task_id, success))
        return 1 if success else 0

    async def pipeline_git_commit(self, result: TaskResult) -> str | None:
        return self._commit_results.get(result.task_id)


# ── GitSafetyNet.create_task_commit ──────────────────────────────────


class TestCreateTaskCommit:
    @pytest.mark.asyncio
    async def test_non_git_returns_none(self, tmp_path: Path) -> None:
        net = GitSafetyNet(str(tmp_path), "r1", str(tmp_path))
        result = await net.create_task_commit("t1", "did stuff")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_swarm_branch_returns_none(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        # Don't call setup() — no swarm branch
        net._state.is_git_repo = True
        result = await net.create_task_commit("t1", "summary")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_changes_returns_none(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        result = await net.create_task_commit("t1", "nothing changed")
        assert result is None

    @pytest.mark.asyncio
    async def test_commits_with_stage_all(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        (wd / "feature.py").write_text("print('hello')")
        result = await net.create_task_commit("t1", "Add greeting feature")
        assert result is not None
        assert len(result) >= 7  # short hash at minimum

        msgs = _git_log(wd)
        assert any("swarm(t1): Add greeting feature" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_commits_specific_files(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        (wd / "wanted.py").write_text("keep")
        (wd / "unwanted.py").write_text("skip")

        result = await net.create_task_commit("t2", "partial", files=["wanted.py"])
        assert result is not None

        # Only wanted.py should be in the commit
        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=str(wd), check=True, capture_output=True, text=True,
        ).stdout.strip().splitlines()
        assert "wanted.py" in diff
        assert "unwanted.py" not in diff

    @pytest.mark.asyncio
    async def test_commit_message_truncates_long_summary(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        (wd / "file.py").write_text("x")
        long_summary = "A" * 200
        result = await net.create_task_commit("t3", long_summary)
        assert result is not None

        msgs = _git_log(wd)
        commit_msg = msgs[0]
        # Should be truncated: "swarm(t3): " + 80 chars
        assert len(commit_msg) <= len("swarm(t3): ") + 80

    @pytest.mark.asyncio
    async def test_error_does_not_raise(self, tmp_path: Path) -> None:
        """create_task_commit should swallow errors and return None."""
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        # Force _git to raise
        async def _exploding_git(*args: str) -> tuple[int, str]:
            raise RuntimeError("git exploded")

        net._git = _exploding_git  # type: ignore[assignment]

        result = await net.create_task_commit("t4", "boom")
        assert result is None  # no exception raised

    @pytest.mark.asyncio
    async def test_excludes_runtime_artifacts(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        agent_dir = wd / ".agent" / "hybrid-swarm"
        agent_dir.mkdir(parents=True)
        (agent_dir / "state.json").write_text("{}")
        subprocess.run(["git", "add", "."], cwd=str(wd), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "seed agent dir"],
            cwd=str(wd), check=True, capture_output=True,
        )

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        # Modify both product code and runtime artifacts
        (wd / "code.py").write_text("product code")
        (agent_dir / "state.json").write_text('{"phase":"running"}')

        result = await net.create_task_commit("t5", "product change")
        assert result is not None

        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=str(wd), check=True, capture_output=True, text=True,
        ).stdout.strip().splitlines()
        assert "code.py" in diff
        assert ".agent/hybrid-swarm/state.json" not in diff


# ── ResultPipeline integration ───────────────────────────────────────


class TestPipelineGitCommit:
    @pytest.mark.asyncio
    async def test_commit_called_for_successful_tasks_with_files(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers(commit_results={"t1": "abc1234"})
        results = [
            TaskResult(task_id="t1", success=True, files_modified=["a.py"]),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.commits == {"t1": "abc1234"}

    @pytest.mark.asyncio
    async def test_commit_not_called_for_failed_tasks(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers(commit_results={"t1": "abc1234"})
        results = [
            TaskResult(task_id="t1", success=False, files_modified=["a.py"], error="fail"),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.commits == {}

    @pytest.mark.asyncio
    async def test_commit_not_called_without_modified_files(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers(commit_results={"t1": "abc1234"})
        results = [
            TaskResult(task_id="t1", success=True),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.commits == {}

    @pytest.mark.asyncio
    async def test_commit_none_not_tracked(self) -> None:
        """If pipeline_git_commit returns None, no entry in commits."""
        pipeline = ResultPipeline()
        handlers = MockHandlers(commit_results={})  # returns None for all
        results = [
            TaskResult(task_id="t1", success=True, files_modified=["a.py"]),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.commits == {}

    @pytest.mark.asyncio
    async def test_multiple_tasks_multiple_commits(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers(commit_results={
            "t1": "aaa1111",
            "t2": "bbb2222",
        })
        results = [
            TaskResult(task_id="t1", success=True, files_modified=["a.py"]),
            TaskResult(task_id="t2", success=True, files_modified=["b.py"]),
            TaskResult(task_id="t3", success=False, error="timeout"),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.commits == {"t1": "aaa1111", "t2": "bbb2222"}
        assert pr.completed == 2
        assert pr.failed == 1


# ── PipelineResult.commits ───────────────────────────────────────────


class TestPipelineResultCommits:
    def test_default_empty(self) -> None:
        pr = PipelineResult()
        assert pr.commits == {}

    def test_stores_commit_hashes(self) -> None:
        pr = PipelineResult(commits={"t1": "abc123", "t2": "def456"})
        assert pr.commits["t1"] == "abc123"
        assert len(pr.commits) == 2


# ── Event emission ───────────────────────────────────────────────────


class TestGitCommitEvent:
    def test_event_type_documented(self) -> None:
        """Verify git_commit is a valid SwarmEvent event_type."""
        event = SwarmEvent(event_type="git_commit", task_id="t1", message="test")
        assert event.event_type == "git_commit"

    def test_event_bus_emits_git_commit(self) -> None:
        bus = EventBus()
        received: list[SwarmEvent] = []
        bus.subscribe(lambda e: received.append(e))

        bus.emit(SwarmEvent(
            event_type="git_commit",
            task_id="t1",
            message="Committed t1: abc12345",
            data={"commit": "abc12345full", "files": ["a.py"]},
        ))

        assert len(received) == 1
        assert received[0].event_type == "git_commit"
        assert received[0].task_id == "t1"
        assert received[0].data["commit"] == "abc12345full"
        assert received[0].data["files"] == ["a.py"]
