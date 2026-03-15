"""Job status API endpoints (service mode only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.db.models import IndexingJob

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: str
    repo_id: str
    job_type: str
    status: str
    branch_name: str | None = None
    progress: dict = {}
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


def _job_to_response(job: IndexingJob) -> JobResponse:
    return JobResponse(
        id=str(job.id),
        repo_id=str(job.repo_id),
        job_type=job.job_type,
        status=job.status,
        branch_name=job.branch_name,
        progress=job.progress or {},
        error=job.error,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat(),
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> JobResponse:
    """Get job status by ID."""
    result = await session.execute(
        select(IndexingJob).where(IndexingJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.get("/repo/{repo_id}", response_model=JobListResponse)
async def list_repo_jobs(
    repo_id: uuid.UUID,
    status: str = "",
    limit: int = 20,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> JobListResponse:
    """List jobs for a repository."""
    query = select(IndexingJob).where(IndexingJob.repo_id == repo_id)
    if status:
        query = query.where(IndexingJob.status == status)
    query = query.order_by(IndexingJob.created_at.desc()).limit(limit)

    result = await session.execute(query)
    jobs = [_job_to_response(j) for j in result.scalars()]
    return JobListResponse(jobs=jobs)
