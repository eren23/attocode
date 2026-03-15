"""Branch management and comparison endpoints (service mode only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.db.models import Branch, Repository

router = APIRouter(prefix="/api/v1/repos/{repo_id}/branches", tags=["branches"])


class BranchResponse(BaseModel):
    id: str
    name: str
    head_commit: str | None = None
    is_default: bool
    last_indexed_at: str | None = None
    overlay_stats: dict = {}


class BranchListResponse(BaseModel):
    branches: list[BranchResponse]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class BranchCompareRequest(BaseModel):
    base_branch: str
    compare_branch: str


class BranchCompareResponse(BaseModel):
    base: str
    compare: str
    files_changed: dict  # path → change_type


async def _get_repo(repo_id: uuid.UUID, session: AsyncSession) -> Repository:
    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("", response_model=BranchListResponse)
async def list_branches(
    repo_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> BranchListResponse:
    """List branches with overlay stats."""
    await _get_repo(repo_id, session)

    from attocode.code_intel.storage.branch_overlay import BranchOverlay

    overlay = BranchOverlay(session)

    count_result = await session.execute(
        select(func.count()).select_from(
            select(Branch).where(Branch.repo_id == repo_id).subquery()
        )
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id)
        .offset(offset).limit(limit)
    )
    branches = []
    for b in result.scalars():
        stats = await overlay.get_overlay_stats(b.id)
        branches.append(BranchResponse(
            id=str(b.id),
            name=b.name,
            head_commit=b.head_commit,
            is_default=b.is_default,
            last_indexed_at=b.last_indexed_at.isoformat() if b.last_indexed_at else None,
            overlay_stats=stats,
        ))
    return BranchListResponse(
        branches=branches, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.get("/{branch_name}", response_model=BranchResponse)
async def get_branch(
    repo_id: uuid.UUID,
    branch_name: str,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> BranchResponse:
    """Get branch detail."""
    await _get_repo(repo_id, session)

    result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == branch_name)
    )
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail=f"Branch '{branch_name}' not found")

    from attocode.code_intel.storage.branch_overlay import BranchOverlay

    overlay = BranchOverlay(session)
    stats = await overlay.get_overlay_stats(branch.id)

    return BranchResponse(
        id=str(branch.id),
        name=branch.name,
        head_commit=branch.head_commit,
        is_default=branch.is_default,
        last_indexed_at=branch.last_indexed_at.isoformat() if branch.last_indexed_at else None,
        overlay_stats=stats,
    )


@router.post("/compare", response_model=BranchCompareResponse)
async def compare_branches(
    repo_id: uuid.UUID,
    req: BranchCompareRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> BranchCompareResponse:
    """Compare two branches — returns file-level diff."""
    await _get_repo(repo_id, session)

    base_result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == req.base_branch)
    )
    base = base_result.scalar_one_or_none()
    if base is None:
        raise HTTPException(status_code=404, detail=f"Branch '{req.base_branch}' not found")

    compare_result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == req.compare_branch)
    )
    compare = compare_result.scalar_one_or_none()
    if compare is None:
        raise HTTPException(status_code=404, detail=f"Branch '{req.compare_branch}' not found")

    from attocode.code_intel.storage.branch_overlay import BranchOverlay

    overlay = BranchOverlay(session)
    diff = await overlay.diff_branches(base.id, compare.id)

    return BranchCompareResponse(
        base=req.base_branch,
        compare=req.compare_branch,
        files_changed=diff,
    )


class BranchMergeRequest(BaseModel):
    source_branch: str
    target_branch: str
    delete_source: bool = True


class BranchMergeResponse(BaseModel):
    source: str
    target: str
    added: int = 0
    modified: int = 0
    deleted: int = 0
    total: int = 0


@router.post("/merge", response_model=BranchMergeResponse)
async def merge_branches(
    repo_id: uuid.UUID,
    req: BranchMergeRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> BranchMergeResponse:
    """Merge source branch overlay into target branch."""
    await _get_repo(repo_id, session)

    source_result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == req.source_branch)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail=f"Branch '{req.source_branch}' not found")

    target_result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == req.target_branch)
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"Branch '{req.target_branch}' not found")

    if source.is_default:
        raise HTTPException(status_code=400, detail="Cannot merge the default branch as source")

    from attocode.code_intel.storage.branch_overlay import BranchOverlay

    overlay = BranchOverlay(session)
    stats = await overlay.merge_branch(
        source.id, target.id, delete_source=req.delete_source,
    )

    from attocode.code_intel.audit import log_event

    repo = await _get_repo(repo_id, session)
    await log_event(
        session, repo.org_id, "branch.merged", repo_id=repo_id,
        detail={"source": req.source_branch, "target": req.target_branch, "stats": stats},
    )

    await session.commit()

    return BranchMergeResponse(
        source=req.source_branch,
        target=req.target_branch,
        **stats,
    )


@router.delete("/{branch_name}")
async def delete_branch(
    repo_id: uuid.UUID,
    branch_name: str,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete a branch overlay (not the git branch)."""
    await _get_repo(repo_id, session)

    result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == branch_name)
    )
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail=f"Branch '{branch_name}' not found")

    if branch.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default branch overlay")

    repo = await _get_repo(repo_id, session)

    await session.delete(branch)

    from attocode.code_intel.audit import log_event

    await log_event(session, repo.org_id, "branch.deleted", repo_id=repo_id, detail={"branch_name": branch_name})

    await session.commit()
    return {"detail": f"Branch overlay '{branch_name}' deleted"}
