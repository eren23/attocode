"""Git worktree helpers for isolated research experiments."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class WorktreeManager:
    """Creates isolated git worktrees for research experiments."""

    def __init__(self, repo_root: str | Path, run_dir: str | Path) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._run_dir = Path(run_dir).resolve()
        self._experiments_dir = self._run_dir / "experiments"
        self._experiments_dir.mkdir(parents=True, exist_ok=True)

    def get_head_commit(self) -> str:
        return self._git_output(["rev-parse", "HEAD"], cwd=self._repo_root).strip()

    def create_worktree(self, experiment_id: str, start_ref: str) -> tuple[Path, str]:
        worktree_path = self._experiments_dir / experiment_id / "worktree"
        branch = f"research/{experiment_id}"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if worktree_path.exists():
            self.remove_worktree(worktree_path, branch=branch)
        self._git(
            ["worktree", "add", "-b", branch, str(worktree_path), start_ref],
            cwd=self._repo_root,
        )
        return worktree_path, branch

    def list_changed_files(self, worktree_path: str | Path) -> list[str]:
        output = self._git_output(
            ["status", "--short", "--porcelain"],
            cwd=worktree_path,
        )
        changed: list[str] = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            changed.append(line[3:].strip())
        return changed

    def capture_diff(self, worktree_path: str | Path) -> str:
        return self._git_output(["diff", "--stat", "--patch"], cwd=worktree_path)

    def apply_diff(self, worktree_path: str | Path, diff_text: str) -> tuple[bool, str]:
        patch_text = self._extract_patch(diff_text)
        if not patch_text.strip():
            return False, "no patch content found"
        if not patch_text.endswith("\n"):
            patch_text = f"{patch_text}\n"

        result = subprocess.run(
            ["git", "apply", "--3way", "--index", "-"],
            cwd=worktree_path,
            input=patch_text,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            return True, "patch applied with git apply --3way"

        subprocess.run(
            ["git", "reset", "--hard", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            check=False,
            text=True,
        )
        message = result.stderr.strip() or result.stdout.strip() or "git apply failed"
        return False, message

    def commit_all(self, worktree_path: str | Path, message: str) -> str:
        changed = self.list_changed_files(worktree_path)
        if not changed:
            return self._git_output(["rev-parse", "HEAD"], cwd=worktree_path).strip()
        self._git(["add", "-A"], cwd=worktree_path)
        self._git(
            [
                "-c",
                "user.name=attoswarm",
                "-c",
                "user.email=attoswarm@example.com",
                "commit",
                "-m",
                message,
            ],
            cwd=worktree_path,
        )
        return self._git_output(["rev-parse", "HEAD"], cwd=worktree_path).strip()

    def remove_worktree(self, worktree_path: str | Path, *, branch: str = "") -> None:
        worktree = Path(worktree_path)
        if worktree.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=self._repo_root,
                capture_output=True,
                check=False,
                text=True,
            )
        if worktree.parent.exists():
            shutil.rmtree(worktree.parent, ignore_errors=True)
        if branch:
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=self._repo_root,
                capture_output=True,
                check=False,
                text=True,
            )
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self._repo_root,
            capture_output=True,
            check=False,
            text=True,
        )

    def _git(self, args: list[str], cwd: str | Path) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            check=True,
            text=True,
        )

    def _git_output(self, args: list[str], cwd: str | Path) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout

    @staticmethod
    def _extract_patch(diff_text: str) -> str:
        if not diff_text.strip():
            return ""
        for marker in ("diff --git ", "--- "):
            idx = diff_text.find(marker)
            if idx != -1:
                return diff_text[idx:]
        return ""
