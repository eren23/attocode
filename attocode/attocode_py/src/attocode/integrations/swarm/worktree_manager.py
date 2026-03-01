"""Git worktree manager for swarm worker isolation.

Each swarm worker gets its own git worktree so that parallel workers
cannot overwrite each other's file changes.  After a worker completes,
its worktree is merged back to the main branch (or conflict is flagged).

Lifecycle:
    1. ``create_worktree(task_id)`` — creates a new branch + worktree
    2. Worker runs in the worktree directory
    3. ``merge_worktree(task_id)`` — merges changes back to main
    4. ``cleanup_worktree(task_id)`` — removes the worktree
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorktreeInfo:
    """Metadata for a single worktree."""

    task_id: str
    branch_name: str
    worktree_path: str
    created: bool = False
    merged: bool = False
    conflict: bool = False
    conflict_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MergeResult:
    """Result of merging a worktree back to main."""

    success: bool
    merged_files: list[str] = field(default_factory=list)
    conflict_files: list[str] = field(default_factory=list)
    error: str = ""


class WorktreeManager:
    """Manages git worktrees for swarm worker isolation.

    Each worker gets a unique branch + worktree under
    ``<repo_root>/.attocode/worktrees/<task_id>/``.
    """

    def __init__(
        self,
        repo_root: str,
        *,
        worktree_base_dir: str | None = None,
        main_branch: str | None = None,
    ) -> None:
        self._repo_root = os.path.abspath(repo_root)
        self._worktree_base = worktree_base_dir or os.path.join(
            self._repo_root, ".attocode", "worktrees",
        )
        self._main_branch = main_branch or self._detect_main_branch()
        self._worktrees: dict[str, WorktreeInfo] = {}

    def _detect_main_branch(self) -> str:
        """Detect the current branch or HEAD."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            branch = result.stdout.strip()
            return branch if branch and branch != "HEAD" else "main"
        except Exception:
            return "main"

    def is_git_repo(self) -> bool:
        """Check if repo_root is a git repository."""
        return os.path.isdir(os.path.join(self._repo_root, ".git"))

    def create_worktree(self, task_id: str) -> WorktreeInfo:
        """Create a git worktree for a worker task.

        Creates a new branch ``swarm/<task_id>`` from the current HEAD
        and a worktree at ``<base>/<task_id>/``.

        Returns WorktreeInfo with the worktree path.
        """
        if task_id in self._worktrees:
            return self._worktrees[task_id]

        # Sanitize task_id for branch name
        safe_id = task_id.replace("/", "-").replace(" ", "-")[:60]
        branch_name = f"swarm/{safe_id}"
        worktree_path = os.path.join(self._worktree_base, safe_id)

        info = WorktreeInfo(
            task_id=task_id,
            branch_name=branch_name,
            worktree_path=worktree_path,
        )

        # Clean up stale worktree if exists
        if os.path.exists(worktree_path):
            self._remove_worktree_dir(worktree_path)

        os.makedirs(self._worktree_base, exist_ok=True)

        try:
            # Create new branch from current HEAD and worktree in one step
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, worktree_path],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # Branch might already exist; try without -b
                result = subprocess.run(
                    ["git", "worktree", "add", worktree_path, branch_name],
                    cwd=self._repo_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

            if result.returncode == 0:
                info.created = True
                logger.info(
                    "Created worktree for task %s at %s (branch: %s)",
                    task_id, worktree_path, branch_name,
                )
            else:
                logger.warning(
                    "Failed to create worktree for task %s: %s",
                    task_id, result.stderr.strip(),
                )

        except Exception as exc:
            logger.warning("Worktree creation failed for task %s: %s", task_id, exc)

        self._worktrees[task_id] = info
        return info

    def get_worktree_path(self, task_id: str) -> str | None:
        """Get the worktree path for a task, or None if not created."""
        info = self._worktrees.get(task_id)
        if info and info.created:
            return info.worktree_path
        return None

    def merge_worktree(self, task_id: str) -> MergeResult:
        """Merge a worktree's changes back to the main branch.

        Uses ``git merge --no-ff`` to preserve the branch history.
        If there are conflicts, reports them without resolving.
        """
        info = self._worktrees.get(task_id)
        if not info or not info.created:
            return MergeResult(success=False, error="Worktree not found or not created")

        if info.merged:
            return MergeResult(success=True)

        try:
            # Check if the worktree branch has any changes
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", f"{self._main_branch}...{info.branch_name}"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            changed_files = [f.strip() for f in diff_result.stdout.strip().split("\n") if f.strip()]

            if not changed_files:
                info.merged = True
                return MergeResult(success=True)

            # Attempt merge
            merge_result = subprocess.run(
                ["git", "merge", "--no-ff", "--no-edit", info.branch_name],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if merge_result.returncode == 0:
                info.merged = True
                logger.info(
                    "Merged worktree for task %s: %d files",
                    task_id, len(changed_files),
                )
                return MergeResult(success=True, merged_files=changed_files)

            # Merge conflict
            # Get list of conflicting files
            conflict_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            conflict_files = [f.strip() for f in conflict_result.stdout.strip().split("\n") if f.strip()]

            # Abort the failed merge
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )

            info.conflict = True
            info.conflict_files = conflict_files

            logger.warning(
                "Merge conflict for task %s: %d conflicting files: %s",
                task_id, len(conflict_files), conflict_files,
            )
            return MergeResult(
                success=False,
                conflict_files=conflict_files,
                error="Merge conflict",
            )

        except Exception as exc:
            return MergeResult(success=False, error=str(exc))

    def cleanup_worktree(self, task_id: str) -> bool:
        """Remove a worktree and its branch.

        Safe to call even if the worktree doesn't exist.
        """
        info = self._worktrees.pop(task_id, None)
        if not info:
            return True

        try:
            # Remove worktree
            if os.path.exists(info.worktree_path):
                subprocess.run(
                    ["git", "worktree", "remove", "--force", info.worktree_path],
                    cwd=self._repo_root,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

            # Delete branch if merged
            if info.merged:
                subprocess.run(
                    ["git", "branch", "-d", info.branch_name],
                    cwd=self._repo_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            else:
                # Force delete unmerged branch
                subprocess.run(
                    ["git", "branch", "-D", info.branch_name],
                    cwd=self._repo_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            # Prune stale worktree references
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )

            logger.info("Cleaned up worktree for task %s", task_id)
            return True

        except Exception as exc:
            logger.warning("Worktree cleanup failed for task %s: %s", task_id, exc)
            return False

    def cleanup_all(self) -> None:
        """Clean up all tracked worktrees."""
        task_ids = list(self._worktrees.keys())
        for task_id in task_ids:
            self.cleanup_worktree(task_id)

    def get_all_worktrees(self) -> list[WorktreeInfo]:
        """Get info about all tracked worktrees."""
        return list(self._worktrees.values())

    def _remove_worktree_dir(self, path: str) -> None:
        """Force-remove a worktree directory."""
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", path],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            pass
        # Fallback: rm -rf
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
            except Exception:
                pass
