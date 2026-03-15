"""Git operations endpoints — commits, blame, diffs (service mode only)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session, get_git_manager

router = APIRouter(prefix="/api/v2/projects/{project_id}", tags=["git-v2"])
logger = logging.getLogger(__name__)


# --- Response models ---


class CommitInfoResponse(BaseModel):
    oid: str
    message: str
    author_name: str
    author_email: str
    timestamp: int
    parent_oids: list[str] = []


class DiffLineResponse(BaseModel):
    origin: str  # '+'/'-'/' '
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


class DiffHunkResponse(BaseModel):
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: list[DiffLineResponse]


class PatchEntryResponse(BaseModel):
    path: str
    status: str
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    hunks: list[DiffHunkResponse] = []


class CommitDetailResponse(BaseModel):
    commit: CommitInfoResponse
    files: list[PatchEntryResponse]


class BlameHunkResponse(BaseModel):
    commit_oid: str
    author_name: str
    author_email: str
    timestamp: int
    start_line: int
    end_line: int


class CommitListResponse(BaseModel):
    commits: list[CommitInfoResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class DiffResponse(BaseModel):
    from_ref: str
    to_ref: str
    files: list[PatchEntryResponse]


# --- Helpers ---


async def _get_repo(project_id: uuid.UUID, session: AsyncSession, auth: AuthContext | None = None):
    from attocode.code_intel.db.models import Repository

    result = await session.execute(select(Repository).where(Repository.id == project_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    # Org isolation
    if auth and auth.org_id and repo.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _patch_entry_from_db_diff(patch) -> PatchEntryResponse:
    """Convert a diff_engine.PatchEntry to PatchEntryResponse."""
    return PatchEntryResponse(
        path=patch.path,
        status=patch.status,
        old_path=patch.old_path,
        additions=patch.additions,
        deletions=patch.deletions,
        hunks=[
            DiffHunkResponse(
                old_start=h.old_start,
                old_lines=h.old_lines,
                new_start=h.new_start,
                new_lines=h.new_lines,
                header=h.header,
                lines=[
                    DiffLineResponse(
                        origin=ln.origin,
                        content=ln.content,
                        old_lineno=ln.old_lineno,
                        new_lineno=ln.new_lineno,
                    )
                    for ln in h.lines
                ],
            )
            for h in patch.hunks
        ],
    )


# --- Endpoints ---


@router.get("/commits", response_model=CommitListResponse)
async def get_commit_log(
    project_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    path: str = Query("", description="Filter commits to those touching this path."),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> CommitListResponse:
    """Get paginated commit log."""
    repo = await _get_repo(project_id, session, auth)
    resolved_ref = ref if ref else repo.default_branch

    # DB fallback for repos without a bare clone (remote-connected repos)
    if not repo.clone_path:
        from attocode.code_intel.db.models import Commit

        query = (
            select(Commit)
            .where(Commit.repo_id == project_id, Commit.branch_name == resolved_ref)
            .order_by(Commit.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        rows = result.scalars().all()

        items = [
            CommitInfoResponse(
                oid=c.oid,
                message=c.message,
                author_name=c.author_name,
                author_email=c.author_email,
                timestamp=c.timestamp,
                parent_oids=c.parent_oids,
            )
            for c in rows
        ]
        return CommitListResponse(
            commits=items,
            total=len(items) + offset,
            limit=limit,
            offset=offset,
            has_more=len(items) == limit,
        )

    git = get_git_manager()
    try:
        commits = git.get_commit_log(
            str(project_id), resolved_ref,
            path=path or None, limit=limit, offset=offset,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    items = [
        CommitInfoResponse(
            oid=c.oid,
            message=c.message,
            author_name=c.author_name,
            author_email=c.author_email,
            timestamp=c.timestamp,
            parent_oids=c.parent_oids,
        )
        for c in commits
    ]

    return CommitListResponse(
        commits=items,
        total=len(items) + offset,  # approximate
        limit=limit,
        offset=offset,
        has_more=len(items) == limit,
    )


@router.get("/commits/{sha}", response_model=CommitDetailResponse)
async def get_commit_detail(
    project_id: uuid.UUID,
    sha: str,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> CommitDetailResponse:
    """Get full commit detail with file diffs."""
    repo = await _get_repo(project_id, session, auth)

    if not repo.clone_path:
        # DB fallback: return commit metadata with changed_files if available
        from attocode.code_intel.db.models import Commit

        result = await session.execute(
            select(Commit).where(Commit.repo_id == project_id, Commit.oid == sha)
        )
        c = result.scalar_one_or_none()
        if c is None:
            raise HTTPException(status_code=404, detail=f"Commit {sha} not found")

        files: list[PatchEntryResponse] = []
        if c.changed_files:
            files = [
                PatchEntryResponse(
                    path=cf.get("path", ""),
                    status=cf.get("status", "M"),
                )
                for cf in c.changed_files
            ]

        return CommitDetailResponse(
            commit=CommitInfoResponse(
                oid=c.oid, message=c.message, author_name=c.author_name,
                author_email=c.author_email, timestamp=c.timestamp, parent_oids=c.parent_oids,
            ),
            files=files,
        )

    git = get_git_manager()
    try:
        commit_info, patches = git.get_commit_detail(str(project_id), sha)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return CommitDetailResponse(
        commit=CommitInfoResponse(
            oid=commit_info.oid,
            message=commit_info.message,
            author_name=commit_info.author_name,
            author_email=commit_info.author_email,
            timestamp=commit_info.timestamp,
            parent_oids=commit_info.parent_oids,
        ),
        files=[
            PatchEntryResponse(
                path=p.path,
                status=p.status,
                old_path=p.old_path,
                additions=p.additions,
                deletions=p.deletions,
                hunks=[
                    DiffHunkResponse(
                        old_start=h.old_start,
                        old_lines=h.old_lines,
                        new_start=h.new_start,
                        new_lines=h.new_lines,
                        header=h.header,
                        lines=[
                            DiffLineResponse(
                                origin=ln.origin,
                                content=ln.content,
                                old_lineno=ln.old_lineno,
                                new_lineno=ln.new_lineno,
                            )
                            for ln in h.lines
                        ],
                    )
                    for h in p.hunks
                ],
            )
            for p in patches
        ],
    )


@router.get("/diff", response_model=DiffResponse)
async def get_diff(
    project_id: uuid.UUID,
    from_ref: str = Query(..., alias="from", description="Base ref"),
    to_ref: str = Query(..., alias="to", description="Target ref"),
    path: str = Query("", description="Filter to specific path"),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> DiffResponse:
    """Diff between two refs with patch content."""
    repo = await _get_repo(project_id, session, auth)

    if not repo.clone_path:
        # DB-backed diff: resolve from_ref/to_ref as branch names
        from attocode.code_intel.db.models import Branch
        from attocode.code_intel.storage.diff_engine import compute_branch_diff

        branch_a_result = await session.execute(
            select(Branch).where(Branch.repo_id == project_id, Branch.name == from_ref)
        )
        branch_a = branch_a_result.scalar_one_or_none()
        if branch_a is None:
            raise HTTPException(status_code=404, detail=f"Branch '{from_ref}' not found")

        branch_b_result = await session.execute(
            select(Branch).where(Branch.repo_id == project_id, Branch.name == to_ref)
        )
        branch_b = branch_b_result.scalar_one_or_none()
        if branch_b is None:
            raise HTTPException(status_code=404, detail=f"Branch '{to_ref}' not found")

        patches = await compute_branch_diff(
            session, branch_a.id, branch_b.id, path_filter=path,
        )

        return DiffResponse(
            from_ref=from_ref,
            to_ref=to_ref,
            files=[_patch_entry_from_db_diff(p) for p in patches],
        )

    git = get_git_manager()

    try:
        patches = git.get_patch(str(project_id), from_ref, to_ref, path=path or None)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return DiffResponse(
        from_ref=from_ref,
        to_ref=to_ref,
        files=[
            PatchEntryResponse(
                path=p.path,
                status=p.status,
                old_path=p.old_path,
                additions=p.additions,
                deletions=p.deletions,
                hunks=[
                    DiffHunkResponse(
                        old_start=h.old_start,
                        old_lines=h.old_lines,
                        new_start=h.new_start,
                        new_lines=h.new_lines,
                        header=h.header,
                        lines=[
                            DiffLineResponse(
                                origin=ln.origin,
                                content=ln.content,
                                old_lineno=ln.old_lineno,
                                new_lineno=ln.new_lineno,
                            )
                            for ln in h.lines
                        ],
                    )
                    for h in p.hunks
                ],
            )
            for p in patches
        ],
    )


@router.get("/blame/{path:path}", response_model=list[BlameHunkResponse])
async def get_blame(
    project_id: uuid.UUID,
    path: str,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> list[BlameHunkResponse]:
    """Get line-level blame for a file."""
    repo = await _get_repo(project_id, session, auth)

    if ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    if not repo.clone_path:
        # DB fallback: query blame_hunks table
        from attocode.code_intel.db.models import BlameHunk

        resolved_ref = ref if ref else repo.default_branch
        result = await session.execute(
            select(BlameHunk)
            .where(
                BlameHunk.repo_id == project_id,
                BlameHunk.path == path,
                BlameHunk.branch_name == resolved_ref,
            )
            .order_by(BlameHunk.start_line)
        )
        hunks = result.scalars().all()
        if not hunks:
            raise HTTPException(
                status_code=404,
                detail=f"No blame data for {path}. Push blame data via notify/blame.",
            )
        return [
            BlameHunkResponse(
                commit_oid=h.commit_oid,
                author_name=h.author_name,
                author_email=h.author_email,
                timestamp=h.timestamp,
                start_line=h.start_line,
                end_line=h.end_line,
            )
            for h in hunks
        ]

    git = get_git_manager()
    resolved_ref = ref if ref else repo.default_branch

    try:
        hunks = git.get_blame(str(project_id), resolved_ref, path)
    except (FileNotFoundError, ValueError, KeyError) as e:
        raise HTTPException(status_code=404, detail=f"Cannot blame: {e}")

    return [
        BlameHunkResponse(
            commit_oid=h.commit_oid,
            author_name=h.author_name,
            author_email=h.author_email,
            timestamp=h.timestamp,
            start_line=h.start_line,
            end_line=h.end_line,
        )
        for h in hunks
    ]
