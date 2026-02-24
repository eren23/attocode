"""Tests for attoswarm.workspace.worktree lifecycle functions."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from attoswarm.workspace.worktree import (
    _delete_branch,
    _prune_worktrees,
    cleanup_worktrees,
    ensure_workspace_for_agent,
)


# ---------------------------------------------------------------------------
# _prune_worktrees
# ---------------------------------------------------------------------------


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_prune_worktrees_calls_git(mock_run: MagicMock) -> None:
    _prune_worktrees(Path("/repo"))
    mock_run.assert_called_once_with(
        ["git", "worktree", "prune"],
        cwd=Path("/repo"),
        check=True,
        capture_output=True,
        text=True,
    )


@patch("attoswarm.workspace.worktree.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git"))
def test_prune_worktrees_swallows_errors(mock_run: MagicMock) -> None:
    # Should not raise
    _prune_worktrees(Path("/repo"))


# ---------------------------------------------------------------------------
# _delete_branch
# ---------------------------------------------------------------------------


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_delete_branch_calls_git(mock_run: MagicMock) -> None:
    _delete_branch(Path("/repo"), "attoswarm/worker-1")
    mock_run.assert_called_once_with(
        ["git", "branch", "-D", "attoswarm/worker-1"],
        cwd=Path("/repo"),
        check=True,
        capture_output=True,
        text=True,
    )


@patch("attoswarm.workspace.worktree.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git"))
def test_delete_branch_swallows_errors(mock_run: MagicMock) -> None:
    # Should not raise even when branch doesn't exist
    _delete_branch(Path("/repo"), "attoswarm/worker-1")


# ---------------------------------------------------------------------------
# ensure_workspace_for_agent — prune + retry on branch exists
# ---------------------------------------------------------------------------


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_ensure_workspace_returns_repo_root_for_shared_mode(mock_run: MagicMock) -> None:
    result = ensure_workspace_for_agent(
        repo_root=Path("/repo"),
        worktrees_root=Path("/repo/.wt"),
        agent_id="worker-1",
        workspace_mode="shared_ro",
        write_access=False,
    )
    assert result == Path("/repo")
    mock_run.assert_not_called()


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_ensure_workspace_returns_existing_path(mock_run: MagicMock, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    wt = tmp_path / "worktrees" / "worker-1"
    wt.mkdir(parents=True)
    result = ensure_workspace_for_agent(
        repo_root=tmp_path,
        worktrees_root=tmp_path / "worktrees",
        agent_id="worker-1",
        workspace_mode="worktree",
        write_access=True,
    )
    assert result == wt
    mock_run.assert_not_called()


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_ensure_workspace_prunes_before_create(mock_run: MagicMock, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    wt_root = tmp_path / "worktrees"

    ensure_workspace_for_agent(
        repo_root=repo,
        worktrees_root=wt_root,
        agent_id="worker-1",
        workspace_mode="worktree",
        write_access=True,
    )

    # First call should be prune, second should be worktree add
    calls = mock_run.call_args_list
    assert calls[0] == call(
        ["git", "worktree", "prune"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert calls[1][0][0][:3] == ["git", "worktree", "add"]


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_ensure_workspace_retries_on_branch_exists(mock_run: MagicMock, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    wt_root = tmp_path / "worktrees"

    # First prune succeeds, first add fails (branch exists), delete succeeds, second add succeeds
    mock_run.side_effect = [
        None,  # prune
        subprocess.CalledProcessError(128, "git", stderr="branch already exists"),  # first add
        None,  # branch delete
        None,  # second add (retry)
    ]

    result = ensure_workspace_for_agent(
        repo_root=repo,
        worktrees_root=wt_root,
        agent_id="worker-1",
        workspace_mode="worktree",
        write_access=True,
    )

    assert result == wt_root / "worker-1"
    assert mock_run.call_count == 4
    # The third call should be branch -D
    assert mock_run.call_args_list[2][0][0] == ["git", "branch", "-D", "attoswarm/worker-1"]


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_ensure_workspace_falls_back_on_total_failure(mock_run: MagicMock, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    wt_root = tmp_path / "worktrees"

    # Prune succeeds, first add fails, delete succeeds, second add also fails
    mock_run.side_effect = [
        None,  # prune
        subprocess.CalledProcessError(128, "git"),  # first add
        None,  # branch delete
        Exception("still fails"),  # second add
    ]

    result = ensure_workspace_for_agent(
        repo_root=repo,
        worktrees_root=wt_root,
        agent_id="worker-1",
        workspace_mode="worktree",
        write_access=True,
    )

    assert result == repo  # Falls back to shared workspace


# ---------------------------------------------------------------------------
# cleanup_worktrees
# ---------------------------------------------------------------------------


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_ensure_workspace_falls_back_when_no_git(mock_run: MagicMock, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    # No .git directory created
    wt_root = tmp_path / "worktrees"

    result = ensure_workspace_for_agent(
        repo_root=repo,
        worktrees_root=wt_root,
        agent_id="worker-1",
        workspace_mode="worktree",
        write_access=True,
    )

    assert result == repo  # Falls back to shared workspace
    mock_run.assert_not_called()  # No git commands attempted


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_cleanup_worktrees_removes_all(mock_run: MagicMock, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    wt_root = tmp_path / "worktrees"
    (wt_root / "worker-1").mkdir(parents=True)
    (wt_root / "worker-2").mkdir(parents=True)

    cleanup_worktrees(repo, wt_root)

    # Should have: remove worker-1, delete branch worker-1, remove worker-2, delete branch worker-2, prune
    cmd_prefixes = [c[0][0][:3] for c in mock_run.call_args_list]
    assert cmd_prefixes.count(["git", "worktree", "remove"]) == 2
    assert cmd_prefixes.count(["git", "branch", "-D"]) == 2
    # Final prune
    assert mock_run.call_args_list[-1][0][0] == ["git", "worktree", "prune"]


@patch("attoswarm.workspace.worktree.subprocess.run")
def test_cleanup_worktrees_noop_when_no_dir(mock_run: MagicMock, tmp_path: Path) -> None:
    cleanup_worktrees(tmp_path / "repo", tmp_path / "nonexistent")
    mock_run.assert_not_called()
