"""Direct repo lookup endpoint (by repo_id, without org context)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.api.routes.orgs import RepoResponse
from attocode.code_intel.db.models import Repository

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo_by_id(
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> RepoResponse:
    """Look up a repository directly by ID (without requiring org context)."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Org isolation: verify the repo belongs to the authenticated user's org
    if auth.org_id and repo.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="Repository not found")

    return RepoResponse(
        id=str(repo.id),
        name=repo.name,
        clone_url=repo.clone_url,
        default_branch=repo.default_branch,
        language=repo.language,
        index_status=repo.index_status,
        last_indexed_at=repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
        created_at=repo.created_at.isoformat(),
    )
