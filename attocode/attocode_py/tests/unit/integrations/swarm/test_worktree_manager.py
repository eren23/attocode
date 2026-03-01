"""Tests for swarm worktree manager -- git worktree isolation for workers."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from attocode.integrations.swarm.worktree_manager import (
    MergeResult,
    WorktreeInfo,
    WorktreeManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ---------------------------------------------------------------------------
# WorktreeInfo / MergeResult dataclasses
# ---------------------------------------------------------------------------


class TestWorktreeInfo:
    def test_defaults(self):
        info = WorktreeInfo(task_id="t1", branch_name="swarm/t1", worktree_path="/tmp/t1")
        assert info.created is False
        assert info.merged is False
        assert info.conflict is False
        assert info.conflict_files == []


class TestMergeResult:
    def test_success(self):
        r = MergeResult(success=True, merged_files=["a.py"])
        assert r.success is True
        assert r.error == ""

    def test_failure(self):
        r = MergeResult(success=False, error="conflict")
        assert r.success is False


# ---------------------------------------------------------------------------
# WorktreeManager.__init__
# ---------------------------------------------------------------------------


class TestWorktreeManagerInit:
    @patch("subprocess.run")
    def test_detects_main_branch(self, mock_run):
        mock_run.return_value = _make_run_result(stdout="develop\n")
        mgr = WorktreeManager("/fake/repo")
        assert mgr._main_branch == "develop"

    @patch("subprocess.run")
    def test_fallback_on_detached_head(self, mock_run):
        mock_run.return_value = _make_run_result(stdout="HEAD\n")
        mgr = WorktreeManager("/fake/repo")
        assert mgr._main_branch == "main"

    @patch("subprocess.run", side_effect=Exception("no git"))
    def test_fallback_on_error(self, mock_run):
        mgr = WorktreeManager("/fake/repo")
        assert mgr._main_branch == "main"

    def test_explicit_main_branch(self):
        with patch("subprocess.run"):
            mgr = WorktreeManager("/fake/repo", main_branch="master")
        assert mgr._main_branch == "master"

    def test_custom_worktree_base_dir(self):
        with patch("subprocess.run"):
            mgr = WorktreeManager("/fake/repo", worktree_base_dir="/custom/wt")
        assert mgr._worktree_base == "/custom/wt"


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    @patch("os.path.isdir")
    @patch("subprocess.run")
    def test_true_when_dot_git_exists(self, mock_run, mock_isdir):
        mock_isdir.return_value = True
        mock_run.return_value = _make_run_result(stdout="main\n")
        mgr = WorktreeManager("/fake/repo")
        assert mgr.is_git_repo() is True
        mock_isdir.assert_called_with("/fake/repo/.git")

    @patch("os.path.isdir")
    @patch("subprocess.run")
    def test_false_when_no_dot_git(self, mock_run, mock_isdir):
        mock_isdir.return_value = False
        mock_run.return_value = _make_run_result(stdout="main\n")
        mgr = WorktreeManager("/fake/repo")
        assert mgr.is_git_repo() is False


# ---------------------------------------------------------------------------
# create_worktree
# ---------------------------------------------------------------------------


class TestCreateWorktree:
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_creates_worktree_success(self, mock_run, mock_exists, mock_makedirs):
        # First call: _detect_main_branch, second: git worktree add
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),  # detect branch
            _make_run_result(returncode=0),       # worktree add
        ]
        mgr = WorktreeManager("/fake/repo")
        info = mgr.create_worktree("task-1")
        assert info.created is True
        assert info.task_id == "task-1"
        assert "task-1" in info.worktree_path

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_returns_cached_worktree(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=0),
        ]
        mgr = WorktreeManager("/fake/repo")
        info1 = mgr.create_worktree("task-1")
        info2 = mgr.create_worktree("task-1")
        assert info1 is info2

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_fallback_without_new_branch(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=1, stderr="branch exists"),  # -b fails
            _make_run_result(returncode=0),  # retry without -b
        ]
        mgr = WorktreeManager("/fake/repo")
        info = mgr.create_worktree("task-2")
        assert info.created is True

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_failure_marks_not_created(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=1, stderr="fatal error"),
            _make_run_result(returncode=1, stderr="fatal error"),
        ]
        mgr = WorktreeManager("/fake/repo")
        info = mgr.create_worktree("task-3")
        assert info.created is False

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_sanitizes_task_id(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=0),
        ]
        mgr = WorktreeManager("/fake/repo")
        info = mgr.create_worktree("path/with spaces/task")
        assert "path-with-spaces-task" in info.branch_name


# ---------------------------------------------------------------------------
# get_worktree_path
# ---------------------------------------------------------------------------


class TestGetWorktreePath:
    @patch("subprocess.run")
    def test_returns_none_for_unknown(self, mock_run):
        mock_run.return_value = _make_run_result(stdout="main\n")
        mgr = WorktreeManager("/fake/repo")
        assert mgr.get_worktree_path("unknown") is None

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_returns_path_for_created(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=0),
        ]
        mgr = WorktreeManager("/fake/repo")
        info = mgr.create_worktree("t1")
        assert mgr.get_worktree_path("t1") == info.worktree_path


# ---------------------------------------------------------------------------
# merge_worktree
# ---------------------------------------------------------------------------


class TestMergeWorktree:
    @patch("subprocess.run")
    def test_merge_not_found(self, mock_run):
        mock_run.return_value = _make_run_result(stdout="main\n")
        mgr = WorktreeManager("/fake/repo")
        result = mgr.merge_worktree("nonexistent")
        assert result.success is False
        assert "not found" in result.error.lower()

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_merge_no_changes(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),     # detect branch
            _make_run_result(returncode=0),          # worktree add
            _make_run_result(stdout=""),              # diff --name-only (empty)
        ]
        mgr = WorktreeManager("/fake/repo")
        mgr.create_worktree("t1")
        result = mgr.merge_worktree("t1")
        assert result.success is True

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_merge_success(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=0),             # worktree add
            _make_run_result(stdout="a.py\nb.py\n"),     # diff
            _make_run_result(returncode=0),              # merge --no-ff
        ]
        mgr = WorktreeManager("/fake/repo")
        mgr.create_worktree("t1")
        result = mgr.merge_worktree("t1")
        assert result.success is True
        assert result.merged_files == ["a.py", "b.py"]

    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_merge_already_merged(self, mock_run, mock_exists, mock_makedirs):
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=0),
            _make_run_result(stdout=""),  # diff (empty = no changes)
        ]
        mgr = WorktreeManager("/fake/repo")
        mgr.create_worktree("t1")
        mgr.merge_worktree("t1")  # first merge marks merged=True
        result = mgr.merge_worktree("t1")  # second merge is a no-op
        assert result.success is True


# ---------------------------------------------------------------------------
# cleanup_worktree
# ---------------------------------------------------------------------------


class TestCleanupWorktree:
    @patch("subprocess.run")
    def test_cleanup_unknown_task(self, mock_run):
        mock_run.return_value = _make_run_result(stdout="main\n")
        mgr = WorktreeManager("/fake/repo")
        assert mgr.cleanup_worktree("unknown") is True

    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_cleanup_removes_from_tracking(self, mock_run, mock_exists, mock_makedirs):
        mock_exists.return_value = False
        mock_run.side_effect = [
            _make_run_result(stdout="main\n"),
            _make_run_result(returncode=0),  # worktree add
            _make_run_result(returncode=0),  # worktree remove
            _make_run_result(returncode=0),  # branch -D
            _make_run_result(returncode=0),  # worktree prune
        ]
        mgr = WorktreeManager("/fake/repo")
        mgr.create_worktree("t1")
        assert mgr.cleanup_worktree("t1") is True
        assert mgr.get_worktree_path("t1") is None


# ---------------------------------------------------------------------------
# cleanup_all / get_all_worktrees
# ---------------------------------------------------------------------------


class TestCleanupAll:
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_cleanup_all(self, mock_run, mock_exists, mock_makedirs):
        # detect branch + 2x worktree add + 2x (remove + branch + prune)
        mock_run.return_value = _make_run_result(returncode=0, stdout="main\n")
        mgr = WorktreeManager("/fake/repo")
        mgr.create_worktree("t1")
        mgr.create_worktree("t2")
        assert len(mgr.get_all_worktrees()) == 2
        mgr.cleanup_all()
        assert len(mgr.get_all_worktrees()) == 0
