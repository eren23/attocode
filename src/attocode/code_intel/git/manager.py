"""Git repository manager — clone, fetch, branches, diffs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from attocode.code_intel.git.credentials import Credential, CredentialStore
from attocode.code_intel.git.models import (
    BlameHunk,
    BranchInfo,
    CommitInfo,
    DiffEntry,
    DiffHunk,
    DiffLine,
    PatchEntry,
    TreeEntry,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GitRepoManager:
    """Manages git operations on bare repositories.

    All operations are designed for bare repos to minimize disk usage.
    """

    def __init__(self, clone_dir: str, ssh_key_path: str = "") -> None:
        self._clone_dir = Path(clone_dir)
        self._cred_store = CredentialStore(ssh_key_path)
        self._path_overrides: dict[str, Path] = {}
        self._clone_dir.mkdir(parents=True, exist_ok=True)

    def register_path(self, repo_id: str, path: str | Path) -> None:
        """Register a path override for a repo (e.g. local directory imports)."""
        self._path_overrides[repo_id] = Path(path)

    def _repo_path(self, repo_id: str) -> Path:
        """Return the filesystem path for a repo's bare clone."""
        if repo_id in self._path_overrides:
            return self._path_overrides[repo_id]
        return self._clone_dir / f"{repo_id}.git"

    def clone(
        self,
        url: str,
        repo_id: str,
        credential: Credential | None = None,
    ) -> str:
        """Clone a remote repository as a bare repo.

        Returns the local clone path.
        """
        import pygit2

        dest = self._repo_path(repo_id)
        if dest.exists():
            logger.info("Repo %s already cloned at %s", repo_id, dest)
            return str(dest)

        callbacks = self._cred_store.resolve(credential)
        logger.info("Cloning %s → %s (bare)", url, dest)

        pygit2.clone_repository(
            url,
            str(dest),
            bare=True,
            callbacks=callbacks,
        )
        return str(dest)

    def fetch(
        self,
        repo_id: str,
        credential: Credential | None = None,
    ) -> None:
        """Fetch updates from the remote origin."""
        import pygit2

        path = self._repo_path(repo_id)
        if not path.exists():
            raise FileNotFoundError(f"Repository {repo_id} not found at {path}")

        repo = pygit2.Repository(str(path))
        remote = repo.remotes["origin"]
        callbacks = self._cred_store.resolve(credential)

        logger.info("Fetching updates for %s", repo_id)
        remote.fetch(callbacks=callbacks)

    def list_branches(self, repo_id: str) -> list[BranchInfo]:
        """List all branches in the repository."""
        import pygit2

        path = self._repo_path(repo_id)
        if not path.exists():
            raise FileNotFoundError(f"Repository {repo_id} not found")

        repo = pygit2.Repository(str(path))
        default_branch = "main"

        # Try to detect default branch from HEAD
        try:
            head_ref = repo.references.get("HEAD")
            if head_ref and head_ref.target:
                target = str(head_ref.target)
                if target.startswith("refs/heads/"):
                    default_branch = target[len("refs/heads/"):]
        except Exception:
            pass

        branches = []
        for ref_name in repo.references:
            if not ref_name.startswith("refs/heads/") and not ref_name.startswith("refs/remotes/origin/"):
                continue

            name = ref_name
            if name.startswith("refs/heads/"):
                name = name[len("refs/heads/"):]
            elif name.startswith("refs/remotes/origin/"):
                name = name[len("refs/remotes/origin/"):]
                if name == "HEAD":
                    continue

            ref = repo.references[ref_name]
            try:
                commit = ref.peel(pygit2.Commit)
            except Exception:
                continue

            branches.append(BranchInfo(
                name=name,
                commit=str(commit.id),
                is_default=(name == default_branch),
            ))

        return branches

    def get_diff(
        self,
        repo_id: str,
        from_ref: str,
        to_ref: str,
    ) -> list[DiffEntry]:
        """Get the file diff between two refs (branches, commits)."""
        import pygit2

        path = self._repo_path(repo_id)
        repo = pygit2.Repository(str(path))

        from_commit = self._resolve_ref(repo, from_ref)
        to_commit = self._resolve_ref(repo, to_ref)

        diff = repo.diff(from_commit, to_commit)
        entries = []
        for patch in diff:
            delta = patch.delta
            status_map = {
                pygit2.GIT_DELTA_ADDED: "added",
                pygit2.GIT_DELTA_DELETED: "deleted",
                pygit2.GIT_DELTA_MODIFIED: "modified",
                pygit2.GIT_DELTA_RENAMED: "renamed",
            }
            status = status_map.get(delta.status, "modified")
            entries.append(DiffEntry(
                path=delta.new_file.path,
                status=status,
                old_path=delta.old_file.path if status == "renamed" else None,
                additions=patch.line_stats[1],
                deletions=patch.line_stats[2],
            ))
        return entries

    def read_file(
        self,
        repo_id: str,
        ref: str,
        file_path: str,
    ) -> bytes:
        """Read a file's content at a specific ref."""
        import pygit2

        path = self._repo_path(repo_id)
        repo = pygit2.Repository(str(path))
        commit = self._resolve_ref(repo, ref)
        tree = commit.tree

        # Walk the tree path
        entry = tree[file_path]
        blob = repo.get(entry.id)
        if blob is None or not isinstance(blob, pygit2.Blob):
            raise FileNotFoundError(f"File not found: {file_path} at {ref}")
        return blob.data

    def get_tree(
        self,
        repo_id: str,
        ref: str,
        path: str = "",
    ) -> list[TreeEntry]:
        """List entries in a directory at a specific ref."""
        import pygit2

        repo_path = self._repo_path(repo_id)
        repo = pygit2.Repository(str(repo_path))
        commit = self._resolve_ref(repo, ref)
        tree = commit.tree

        if path:
            entry = tree[path]
            subtree = repo.get(entry.id)
            if not isinstance(subtree, pygit2.Tree):
                raise ValueError(f"Path is not a directory: {path}")
            tree = subtree

        entries = []
        for entry in tree:
            obj = repo.get(entry.id)
            entry_type = "blob" if isinstance(obj, pygit2.Blob) else "tree"
            size = len(obj.data) if isinstance(obj, pygit2.Blob) else 0
            entry_path = f"{path}/{entry.name}" if path else entry.name
            entries.append(TreeEntry(
                name=entry.name,
                path=entry_path,
                type=entry_type,
                size=size,
                oid=str(entry.id),
            ))
        return entries

    def get_commit_log(
        self,
        repo_id: str,
        ref: str,
        path: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommitInfo]:
        """Walk commit history from a ref, optionally filtered by path."""
        import pygit2

        repo_path = self._repo_path(repo_id)
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository {repo_id} not found")

        repo = pygit2.Repository(str(repo_path))
        commit = self._resolve_ref(repo, ref)

        commits = []
        seen = 0
        for c in repo.walk(commit.id, pygit2.GIT_SORT_TIME):
            if path:
                # Filter: only include commits that touch the specified path
                if not self._commit_touches_path(repo, c, path):
                    continue
            if seen < offset:
                seen += 1
                continue
            commits.append(CommitInfo(
                oid=str(c.id),
                message=c.message.strip(),
                author_name=c.author.name,
                author_email=c.author.email,
                timestamp=c.commit_time,
                parent_oids=[str(p) for p in c.parent_ids],
            ))
            if len(commits) >= limit:
                break
            seen += 1

        return commits

    def _commit_touches_path(self, repo, commit, path: str) -> bool:
        """Check if a commit modified the given path compared to its first parent."""
        try:
            entry = commit.tree[path]
        except KeyError:
            # Path doesn't exist in this commit
            if commit.parents:
                try:
                    commit.parents[0].tree[path]
                    return True  # Deleted in this commit
                except KeyError:
                    return False
            return False

        if not commit.parents:
            return True  # Initial commit

        try:
            parent_entry = commit.parents[0].tree[path]
            return entry.id != parent_entry.id
        except KeyError:
            return True  # Added in this commit

    def get_commit_detail(
        self,
        repo_id: str,
        commit_sha: str,
    ) -> tuple[CommitInfo, list[PatchEntry]]:
        """Get full commit info + diff against parent."""
        import pygit2

        path = self._repo_path(repo_id)
        if not path.exists():
            raise FileNotFoundError(f"Repository {repo_id} not found")

        repo = pygit2.Repository(str(path))
        commit = self._resolve_ref(repo, commit_sha)

        info = CommitInfo(
            oid=str(commit.id),
            message=commit.message.strip(),
            author_name=commit.author.name,
            author_email=commit.author.email,
            timestamp=commit.commit_time,
            parent_oids=[str(p) for p in commit.parent_ids],
        )

        # Diff against first parent (or empty tree for root commit)
        if commit.parents:
            diff = repo.diff(commit.parents[0], commit)
        else:
            diff = commit.tree.diff_to_tree()

        patches = self._diff_to_patches(diff)
        return info, patches

    def get_blame(
        self,
        repo_id: str,
        ref: str,
        file_path: str,
    ) -> list[BlameHunk]:
        """Get line-level blame for a file at a ref."""
        import pygit2

        path = self._repo_path(repo_id)
        if not path.exists():
            raise FileNotFoundError(f"Repository {repo_id} not found")

        repo = pygit2.Repository(str(path))
        commit = self._resolve_ref(repo, ref)

        blame = repo.blame(file_path, newest_commit=commit.id)
        hunks = []
        for hunk in blame:
            hunks.append(BlameHunk(
                commit_oid=str(hunk.final_commit_id),
                author_name=hunk.final_committer.name if hunk.final_committer else "",
                author_email=hunk.final_committer.email if hunk.final_committer else "",
                timestamp=hunk.final_committer.time if hunk.final_committer else 0,
                start_line=hunk.final_start_line_number,
                end_line=hunk.final_start_line_number + hunk.lines_in_hunk - 1,
            ))

        return hunks

    def get_patch(
        self,
        repo_id: str,
        from_ref: str,
        to_ref: str,
        path: str | None = None,
    ) -> list[PatchEntry]:
        """Get diff with full patch content between two refs."""
        import pygit2

        repo_path = self._repo_path(repo_id)
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository {repo_id} not found")

        repo = pygit2.Repository(str(repo_path))
        from_commit = self._resolve_ref(repo, from_ref)
        to_commit = self._resolve_ref(repo, to_ref)

        diff = repo.diff(from_commit, to_commit)
        patches = self._diff_to_patches(diff)

        if path:
            patches = [p for p in patches if p.path == path or p.old_path == path]

        return patches

    def _diff_to_patches(self, diff) -> list[PatchEntry]:
        """Convert a pygit2 Diff to structured PatchEntry list."""
        import pygit2

        status_map = {
            pygit2.GIT_DELTA_ADDED: "added",
            pygit2.GIT_DELTA_DELETED: "deleted",
            pygit2.GIT_DELTA_MODIFIED: "modified",
            pygit2.GIT_DELTA_RENAMED: "renamed",
        }

        patches = []
        for patch in diff:
            delta = patch.delta
            status = status_map.get(delta.status, "modified")

            hunks = []
            for hunk in patch.hunks:
                lines = []
                for line in hunk.lines:
                    lines.append(DiffLine(
                        origin=line.origin,
                        content=line.content.rstrip("\n"),
                        old_lineno=line.old_lineno if line.old_lineno >= 0 else None,
                        new_lineno=line.new_lineno if line.new_lineno >= 0 else None,
                    ))
                hunks.append(DiffHunk(
                    old_start=hunk.old_start,
                    old_lines=hunk.old_lines,
                    new_start=hunk.new_start,
                    new_lines=hunk.new_lines,
                    header=hunk.header.strip(),
                    lines=lines,
                ))

            patches.append(PatchEntry(
                path=delta.new_file.path,
                status=status,
                old_path=delta.old_file.path if status == "renamed" else None,
                additions=patch.line_stats[1],
                deletions=patch.line_stats[2],
                hunks=hunks,
            ))

        return patches

    def get_disk_usage(self, repo_id: str) -> int:
        """Get total disk usage of a repo clone in bytes."""
        path = self._repo_path(repo_id)
        if not path.exists():
            return 0
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        return total

    def delete(self, repo_id: str) -> None:
        """Delete a repo's bare clone from disk.

        Skips deletion for repos with path overrides (local directory imports)
        to avoid nuking the user's project directory.
        """
        if repo_id in self._path_overrides:
            logger.info("Skipping delete for local repo %s (path override)", repo_id)
            self._path_overrides.pop(repo_id, None)
            return

        import shutil

        path = self._repo_path(repo_id)
        if path.exists():
            shutil.rmtree(path)
            logger.info("Deleted clone for %s", repo_id)

    def _resolve_ref(self, repo, ref: str):
        """Resolve a ref string to a pygit2 Commit object."""
        import pygit2

        # Try as branch name
        for prefix in ("refs/heads/", "refs/remotes/origin/", ""):
            full_ref = f"{prefix}{ref}" if prefix else ref
            try:
                reference = repo.references[full_ref]
                obj = repo.get(reference.target)
                if isinstance(obj, pygit2.Commit):
                    return obj
            except (KeyError, ValueError):
                pass

        # Try as commit hash
        try:
            obj = repo.revparse_single(ref)
            if isinstance(obj, pygit2.Commit):
                return obj
            if isinstance(obj, pygit2.Tag):
                return obj.get_object()
        except (KeyError, ValueError):
            pass

        raise ValueError(f"Cannot resolve ref: {ref}")
