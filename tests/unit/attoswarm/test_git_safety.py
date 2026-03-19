"""Tests for attoswarm.workspace.git_safety.GitSafetyNet.

Covers: setup, finalize, _persist_state, non-git-repo no-ops,
        create_swarm_commit, get_changed_files.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from attoswarm.workspace.git_safety import GitSafetyNet, GitSafetyState


def _make_git_repo(path: Path) -> None:
    """Initialize a real git repo at *path* for integration-style tests."""
    import subprocess

    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), check=True, capture_output=True,
    )
    # Create initial commit so HEAD exists
    (path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path), check=True, capture_output=True,
    )


# ── _persist_state ────────────────────────────────────────────────────


class TestPersistState:
    def test_writes_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(tmp_path), "test-run", str(run_dir))
        net._state = GitSafetyState(
            is_git_repo=True,
            original_branch="main",
            swarm_branch="attoswarm/test-run",
            stash_ref="attoswarm-test-run-pre-run",
            pre_run_head="abc123",
        )
        net._persist_state()

        out = json.loads((run_dir / "git_safety.json").read_text())
        assert out["is_git_repo"] is True
        assert out["original_branch"] == "main"
        assert out["swarm_branch"] == "attoswarm/test-run"
        assert out["stash_ref"] == "attoswarm-test-run-pre-run"
        assert out["pre_run_head"] == "abc123"

    def test_empty_state(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(tmp_path), "test-run", str(run_dir))
        net._persist_state()

        out = json.loads((run_dir / "git_safety.json").read_text())
        assert out["is_git_repo"] is False
        assert out["swarm_branch"] == ""

    def test_missing_run_dir_no_crash(self, tmp_path: Path) -> None:
        """_persist_state should not raise even if run_dir parent is missing."""
        net = GitSafetyNet(str(tmp_path), "x", str(tmp_path / "nonexistent" / "run"))
        # write_json_atomic creates parents, so this should succeed or log warning
        net._persist_state()


# ── setup ─────────────────────────────────────────────────────────────


class TestSetup:
    def test_non_git_repo(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(tmp_path), "r1", str(run_dir))
        state = asyncio.run(net.setup())
        assert state.is_git_repo is False
        assert state.swarm_branch == ""

    def test_non_git_persists_state(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        asyncio.run(net.setup())
        gs_path = run_dir / "git_safety.json"
        assert gs_path.exists()
        data = json.loads(gs_path.read_text())
        assert data["is_git_repo"] is False

    @pytest.mark.asyncio
    async def test_real_git_repo(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        state = await net.setup()

        assert state.is_git_repo is True
        assert state.original_branch in ("main", "master")
        assert state.swarm_branch == "attoswarm/r1"
        assert state.pre_run_head != ""

        # Verify git_safety.json was written
        gs_path = run_dir / "git_safety.json"
        assert gs_path.exists()
        data = json.loads(gs_path.read_text())
        assert data["swarm_branch"] == "attoswarm/r1"
        assert data["original_branch"] == state.original_branch

    @pytest.mark.asyncio
    async def test_stashes_uncommitted_changes(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        # Create uncommitted change
        (wd / "dirty.txt").write_text("uncommitted")
        import subprocess
        subprocess.run(["git", "add", "dirty.txt"], cwd=str(wd), check=True, capture_output=True)

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        state = await net.setup()

        assert state.stash_ref == "attoswarm-r1-pre-run"
        data = json.loads((run_dir / "git_safety.json").read_text())
        assert data["stash_ref"] == "attoswarm-r1-pre-run"

    @pytest.mark.asyncio
    async def test_setup_records_base_ref(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        state = await net.setup(base_ref="HEAD")

        assert state.base_ref == "HEAD"
        data = json.loads((run_dir / "git_safety.json").read_text())
        assert data["base_ref"] == "HEAD"

    @pytest.mark.asyncio
    async def test_setup_prefers_base_commit_for_branch_creation(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        (wd / ".git").mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))

        calls: list[tuple[str, ...]] = []

        async def fake_git(*args: str) -> tuple[int, str]:
            calls.append(tuple(args))
            if args == ("rev-parse", "--abbrev-ref", "HEAD"):
                return 0, "main\n"
            if args == ("rev-parse", "HEAD"):
                return 0, "feedface\n"
            if args == ("rev-parse", "deadbeef"):
                return 0, "deadbeef\n"
            if args == ("status", "--porcelain"):
                return 0, ""
            if args == ("checkout", "-b", "attoswarm/r1", "deadbeef"):
                return 0, ""
            return 0, ""

        net._git = fake_git  # type: ignore[assignment]

        state = await net.setup(base_ref="main", base_commit="deadbeef")

        assert state.base_commit == "deadbeef"
        assert ("checkout", "-b", "attoswarm/r1", "deadbeef") in calls

    @pytest.mark.asyncio
    async def test_reattach_restores_saved_branch(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        resumed = GitSafetyNet(str(wd), "r1", str(run_dir))
        resumed.load_state()
        state = await resumed.reattach()
        assert state.swarm_branch == "attoswarm/r1"


# ── finalize ──────────────────────────────────────────────────────────


class TestFinalize:
    @pytest.mark.asyncio
    async def test_finalize_persists_state(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        # Make a change on the swarm branch
        (wd / "new_file.txt").write_text("content")

        await net.finalize("keep")

        gs_path = run_dir / "git_safety.json"
        assert gs_path.exists()
        data = json.loads(gs_path.read_text())
        # After "keep" finalize, we should still have the branch info
        assert data["swarm_branch"] == "attoswarm/r1"

    @pytest.mark.asyncio
    async def test_finalize_non_git_noop(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(tmp_path), "r1", str(run_dir))
        await net.setup()
        # Should not raise
        await net.finalize("merge")

    @pytest.mark.asyncio
    async def test_finalize_keep_records_result_ref(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        (wd / "new_file.txt").write_text("content")
        await net.finalize("keep")

        data = json.loads((run_dir / "git_safety.json").read_text())
        assert data["finalization_mode"] == "keep"
        assert data["result_ref"] == "attoswarm/r1"


# ── create_swarm_commit ───────────────────────────────────────────────


class TestCreateSwarmCommit:
    @pytest.mark.asyncio
    async def test_non_git_returns_false(self, tmp_path: Path) -> None:
        net = GitSafetyNet(str(tmp_path), "r1", str(tmp_path))
        result = await net.create_swarm_commit("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_changes_returns_false(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()
        # No changes to commit
        result = await net.create_swarm_commit("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_excludes_agent_runtime_files_from_commit(self, tmp_path: Path) -> None:
        import subprocess

        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        agent_dir = wd / ".agent" / "hybrid-swarm"
        agent_dir.mkdir(parents=True)
        (agent_dir / "swarm.state.json").write_text('{"phase":"old"}', encoding="utf-8")
        (wd / "code.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(wd), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "seed swarm files"], cwd=str(wd), check=True, capture_output=True)

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        (agent_dir / "swarm.state.json").write_text('{"phase":"running"}', encoding="utf-8")
        (wd / "code.txt").write_text("changed\n", encoding="utf-8")

        result = await net.create_swarm_commit("test")
        assert result is True

        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=str(wd),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert "code.txt" in diff
        assert ".agent/hybrid-swarm/swarm.state.json" not in diff


# ── get_changed_files ─────────────────────────────────────────────────


class TestGetChangedFiles:
    @pytest.mark.asyncio
    async def test_non_git_returns_empty(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(tmp_path))
        result = await net.get_changed_files()
        assert result == []

    @pytest.mark.asyncio
    async def test_detects_new_file(self, tmp_path: Path) -> None:
        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        # Create and commit a new file on the swarm branch
        (wd / "new.txt").write_text("hello")
        await net.create_swarm_commit("add file")

        files = await net.get_changed_files()
        assert len(files) == 1
        assert files[0]["file"] == "new.txt"
        assert files[0]["action"] == "A"

    @pytest.mark.asyncio
    async def test_finalize_merge_ignores_agent_runtime_files(self, tmp_path: Path) -> None:
        import subprocess

        wd = tmp_path / "project"
        wd.mkdir()
        _make_git_repo(wd)
        agent_dir = wd / ".agent" / "hybrid-swarm"
        agent_dir.mkdir(parents=True)
        (agent_dir / "swarm.state.json").write_text('{"phase":"seed"}', encoding="utf-8")
        (wd / "code.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(wd), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "seed swarm files"], cwd=str(wd), check=True, capture_output=True)

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        net = GitSafetyNet(str(wd), "r1", str(run_dir))
        await net.setup()

        (agent_dir / "swarm.state.json").write_text('{"phase":"runtime"}', encoding="utf-8")
        (wd / "code.txt").write_text("merged\n", encoding="utf-8")

        await net.finalize("merge")

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(wd),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert branch in ("main", "master")
        assert (wd / "code.txt").read_text(encoding="utf-8") == "merged\n"
        assert (agent_dir / "swarm.state.json").read_text(encoding="utf-8") == '{"phase":"seed"}'

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(wd),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert status == ""
