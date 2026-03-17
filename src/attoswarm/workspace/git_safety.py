"""Git Safety Net — protect repos during swarm runs.

Stashes uncommitted changes, creates a swarm branch, and provides
merge/keep/discard finalization after the run completes.

Non-git repos: all methods are no-ops (graceful fallback).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitSafetyState:
    """Snapshot of git state before the swarm run."""

    is_git_repo: bool = False
    original_branch: str = ""
    swarm_branch: str = ""
    stash_ref: str = ""
    pre_run_head: str = ""


class GitSafetyNet:
    """Protect git repos during swarm runs."""

    def __init__(self, working_dir: str, run_id: str, run_dir: str) -> None:
        self._wd = working_dir
        self._run_id = run_id
        self._run_dir = run_dir
        self._state = GitSafetyState()

    @property
    def state(self) -> GitSafetyState:
        return self._state

    async def setup(self) -> GitSafetyState:
        """Check if git repo, stash uncommitted changes, create swarm branch."""
        if not Path(self._wd, ".git").exists():
            self._state.is_git_repo = False
            self._persist_state()
            return self._state

        self._state.is_git_repo = True

        # Get current branch
        rc, branch = await self._git("rev-parse", "--abbrev-ref", "HEAD")
        if rc != 0:
            logger.warning("Could not determine current branch")
            self._persist_state()
            return self._state
        self._state.original_branch = branch.strip()

        # Get current HEAD
        rc, head = await self._git("rev-parse", "HEAD")
        if rc == 0:
            self._state.pre_run_head = head.strip()

        # Stash uncommitted changes (if any)
        rc, status = await self._git("status", "--porcelain")
        if rc == 0 and status.strip():
            stash_msg = f"attoswarm-{self._run_id}-pre-run"
            rc, out = await self._git("stash", "push", "-m", stash_msg)
            if rc == 0 and "No local changes" not in out:
                self._state.stash_ref = stash_msg
                logger.info("Stashed uncommitted changes: %s", stash_msg)

        # Create swarm branch
        swarm_branch = f"attoswarm/{self._run_id}"
        rc, _ = await self._git("checkout", "-b", swarm_branch)
        if rc == 0:
            self._state.swarm_branch = swarm_branch
            logger.info("Created swarm branch: %s", swarm_branch)
        else:
            logger.warning("Failed to create swarm branch %s", swarm_branch)

        self._persist_state()
        return self._state

    async def create_swarm_commit(self, message: str = "") -> bool:
        """Commit all changes on the swarm branch."""
        if not self._state.is_git_repo or not self._state.swarm_branch:
            return False

        msg = message or f"attoswarm run {self._run_id}"
        rc, _ = await self._git("add", "-A")
        if rc != 0:
            return False

        # Check if there's anything to commit
        rc, _ = await self._git("diff", "--cached", "--quiet")
        if rc == 0:
            return False  # Nothing staged

        rc, _ = await self._git("commit", "-m", msg)
        return rc == 0

    async def finalize(self, mode: str = "keep") -> None:
        """Finalize the swarm run: merge, keep, or discard the swarm branch.

        Modes:
          - "merge": commit on swarm branch, checkout original, merge
          - "keep": commit on swarm branch, checkout original (branch preserved)
          - "discard": checkout original, delete swarm branch, revert
        """
        if not self._state.is_git_repo:
            return

        if mode == "discard":
            await self._git("checkout", "--force", self._state.original_branch)
            if self._state.swarm_branch:
                await self._git("branch", "-D", self._state.swarm_branch)
            await self.revert_all()
        elif mode == "merge":
            await self.create_swarm_commit()
            await self._git("checkout", self._state.original_branch)
            if self._state.swarm_branch:
                rc, out = await self._git("merge", self._state.swarm_branch)
                if rc == 0:
                    logger.info("Merged swarm branch into %s", self._state.original_branch)
                else:
                    logger.warning("Merge failed: %s", out[:200])
        else:  # "keep"
            await self.create_swarm_commit()
            await self._git("checkout", self._state.original_branch)
            logger.info(
                "Swarm branch preserved: %s (review with: git log %s)",
                self._state.swarm_branch,
                self._state.swarm_branch,
            )

        # Pop stash if we stashed
        if self._state.stash_ref:
            rc, stash_list = await self._git("stash", "list")
            if rc == 0 and self._state.stash_ref in stash_list:
                await self._git("stash", "pop")

        self._persist_state()

    async def revert_all(self) -> None:
        """Revert all changes in the working directory."""
        if not self._state.is_git_repo:
            return
        await self._git("checkout", ".")
        await self._git("clean", "-fd")

    async def get_changed_files(self) -> list[dict[str, str]]:
        """Get list of changed files vs original branch."""
        if not self._state.is_git_repo or not self._state.original_branch:
            return []

        rc, out = await self._git(
            "diff", "--name-status", self._state.original_branch, "HEAD",
        )
        if rc != 0:
            return []

        result: list[dict[str, str]] = []
        for line in out.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                result.append({"action": parts[0], "file": parts[1]})
        return result

    def _persist_state(self) -> None:
        """Write git safety state to JSON for TUI consumption."""
        from attoswarm.protocol.io import write_json_atomic
        state_path = Path(self._run_dir) / "git_safety.json"
        try:
            write_json_atomic(state_path, asdict(self._state))
        except Exception as exc:
            logger.warning("Failed to persist git_safety.json: %s", exc)

    async def _git(self, *args: str) -> tuple[int, str]:
        """Run a git command and return (returncode, stdout).

        Uses create_subprocess_exec (not shell) to avoid injection.
        All arguments are passed as a flat argv list.
        """
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._wd,
        )
        stdout, stderr = await proc.communicate()
        out = (stdout or b"").decode("utf-8", errors="replace")
        assert proc.returncode is not None
        return proc.returncode, out
