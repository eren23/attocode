"""Workspace isolation helpers (hybrid by role)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def _prune_worktrees(repo_root: Path) -> None:
    """Run ``git worktree prune`` to clean up stale bookkeeping entries."""
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        log.warning("git worktree prune failed: %s", exc.stderr)


def _delete_branch(repo_root: Path, branch_name: str) -> None:
    """Force-delete a local branch that may be left over from a previous run."""
    try:
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        pass  # Branch may not exist — that's fine.


def ensure_workspace_for_agent(
    repo_root: Path,
    worktrees_root: Path,
    agent_id: str,
    workspace_mode: str,
    write_access: bool,
) -> Path:
    if workspace_mode != "worktree" or not write_access:
        return repo_root

    if not (repo_root / ".git").exists():
        log.warning(
            "No .git found in %s — worktree mode unavailable, falling back to shared workspace",
            repo_root,
        )
        return repo_root

    path = worktrees_root / agent_id
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    branch_name = f"attoswarm/{agent_id}"

    # Prune stale worktree bookkeeping before attempting creation.
    _prune_worktrees(repo_root)

    try:
        subprocess.run(
            ["git", "worktree", "add", str(path), "-b", branch_name],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        # Branch may exist from a previous run — delete it and retry once.
        _delete_branch(repo_root, branch_name)
        try:
            subprocess.run(
                ["git", "worktree", "add", str(path), "-b", branch_name],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            # Fallback to shared workspace if worktree creation still fails.
            return repo_root
    except Exception:
        return repo_root
    return path


def cleanup_worktrees(repo_root: Path, worktrees_root: Path) -> None:
    """Remove all agent worktrees and their branches, then prune."""
    if not worktrees_root.exists():
        return

    for child in sorted(worktrees_root.iterdir()):
        if not child.is_dir():
            continue
        branch_name = f"attoswarm/{child.name}"
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(child)],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            log.warning("git worktree remove %s failed: %s", child.name, exc.stderr)
        _delete_branch(repo_root, branch_name)

    _prune_worktrees(repo_root)
