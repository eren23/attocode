"""Authenticated repository selection and immutable Git snapshots."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from contextvars import ContextVar
from pathlib import Path

from filelock import FileLock

from attocode_intel.catalog import is_write, remote_available
from attocode_intel.request_context import RequestContext

remote_workspace: ContextVar[str] = ContextVar("remote_workspace", default="")
remote_profile: ContextVar[str] = ContextVar("remote_profile", default="full")

remote_identity: ContextVar[object | None] = ContextVar("intelligence_identity", default=None)


async def authorized_repo(repo_id: str, auth, *, write: bool = False):
    from fastapi import HTTPException
    from sqlalchemy import select

    from attocode_intel.db.engine import get_session
    from attocode_intel.db.models import OrgMembership, Repository

    try:
        rid = uuid.UUID(repo_id)
    except ValueError as exc:
        raise HTTPException(
            404, "Repository not found; supply workspace as a repository ID"
        ) from exc
    if auth is None or auth.auth_method == "legacy":
        raise HTTPException(401, "Authentication required")
    required = "write" if write else "read"
    if (
        auth.auth_method == "api_key"
        and required not in auth.scopes
        and f"intelligence:{required}" not in auth.scopes
    ):
        raise HTTPException(403, f"API key requires intelligence:{required} scope")
    async for session in get_session():
        repo = (
            await session.execute(select(Repository).where(Repository.id == rid))
        ).scalar_one_or_none()
        if repo is None or (auth.org_id and auth.org_id != repo.org_id):
            raise HTTPException(404, "Repository not found")
        if auth.user_id:
            membership = (
                await session.execute(
                    select(OrgMembership).where(
                        OrgMembership.org_id == repo.org_id,
                        OrgMembership.user_id == auth.user_id,
                        OrgMembership.accepted_at.is_not(None),
                    )
                )
            ).scalar_one_or_none()
            if membership is None:
                raise HTTPException(404, "Repository not found")
        elif auth.auth_method != "api_key" or auth.org_id != repo.org_id:
            raise HTTPException(404, "Repository not found")
        return repo
    raise HTTPException(503, "Repository database unavailable")


def committed_snapshot(
    repo_path: str, cache_root: str, repo_id: str, revision: str
) -> tuple[str, str]:
    """Create a detached worktree; never change the source checkout or upload edits."""

    def git(*args):
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-C",
                repo_path,
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        return result.stdout.strip()

    commit = git("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
    base = Path(cache_root) / ".intelligence-snapshots" / repo_id
    base.mkdir(parents=True, exist_ok=True)
    target = base / commit
    with FileLock(str(base / "snapshots.lock"), timeout=90):
        if not (target / ".git").exists():
            git("worktree", "add", "--detach", str(target), commit)
        # Prevent repository symlinks from exposing files outside the snapshot.
        for path in target.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(target.resolve()):
                raise ValueError(
                    f"Snapshot contains an external symlink: {path.relative_to(target)}"
                )
    return str(target.resolve()), commit


class RemoteResolver:
    def __init__(self, config):
        self.config = config

    async def __call__(self, workspace, revision, name):
        workspace = workspace or remote_workspace.get()
        auth = remote_identity.get()
        write = is_write(name)
        repo = await authorized_repo(workspace, auth, write=write)
        if not remote_available(name):
            raise ValueError(
                "This operation is local-only; remote source snapshots cannot be modified."
            )
        path = repo.clone_path or repo.local_path
        if not path:
            raise ValueError("Repository has not been cloned or indexed yet")
        path, commit = await asyncio.to_thread(
            committed_snapshot,
            path,
            self.config.git_clone_dir,
            str(repo.id),
            revision or repo.default_branch,
        )
        return RequestContext(path, str(repo.id), commit, "remote", auth)
