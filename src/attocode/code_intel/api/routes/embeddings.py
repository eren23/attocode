"""Embedding and indexing status dashboard endpoints (service mode only)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_branch_context, get_db_session

router = APIRouter(prefix="/api/v2/repos/{repo_id}", tags=["embeddings"])
logger = logging.getLogger(__name__)


# --- Response models ---


class EmbeddingStatusResponse(BaseModel):
    total_files: int
    embedded_files: int
    coverage_pct: float
    model: str


class FileEmbeddingStatus(BaseModel):
    path: str
    content_sha: str
    has_embedding: bool


class FileEmbeddingListResponse(BaseModel):
    files: list[FileEmbeddingStatus]
    total: int
    limit: int
    offset: int
    has_more: bool


class IndexingStatusResponse(BaseModel):
    index_status: str
    last_indexed_at: str | None = None
    active_jobs: int = 0
    embedding_coverage_pct: float = 0.0
    total_files: int = 0
    embedded_files: int = 0


# --- Helpers ---


async def _get_repo(repo_id: uuid.UUID, session: AsyncSession):
    from attocode.code_intel.db.models import Repository

    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


# --- Endpoints ---


@router.get("/embeddings/status", response_model=EmbeddingStatusResponse)
async def get_embedding_status(
    repo_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    model: str = Query("default", description="Embedding model name."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> EmbeddingStatusResponse:
    """Get embedding coverage for a repo branch."""
    repo = await _get_repo(repo_id, session)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(repo_id, resolved_ref, session)
    except HTTPException:
        return EmbeddingStatusResponse(
            total_files=0, embedded_files=0, coverage_pct=0.0, model=model,
        )

    content_shas = branch_ctx.content_shas
    total = len(content_shas)
    if total == 0:
        return EmbeddingStatusResponse(
            total_files=0, embedded_files=0, coverage_pct=0.0, model=model,
        )

    from attocode.code_intel.storage.embedding_store import EmbeddingStore

    store = EmbeddingStore(session)
    embedded_shas = await store.batch_has_embeddings(content_shas, model)
    embedded = len(embedded_shas)

    return EmbeddingStatusResponse(
        total_files=total,
        embedded_files=embedded,
        coverage_pct=round(embedded / total * 100, 1) if total > 0 else 0.0,
        model=model,
    )


@router.get("/embeddings/files", response_model=FileEmbeddingListResponse)
async def get_file_embedding_status(
    repo_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    model: str = Query("default", description="Embedding model name."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> FileEmbeddingListResponse:
    """Get per-file embedding status (paginated)."""
    repo = await _get_repo(repo_id, session)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(repo_id, resolved_ref, session)
    except HTTPException:
        return FileEmbeddingListResponse(
            files=[], total=0, limit=limit, offset=offset, has_more=False,
        )

    manifest = branch_ctx.manifest
    content_shas = branch_ctx.content_shas
    total = len(manifest)

    # Batch check which SHAs have embeddings
    from attocode.code_intel.storage.embedding_store import EmbeddingStore

    store = EmbeddingStore(session)
    embedded_shas = await store.batch_has_embeddings(content_shas, model)

    # Paginate over sorted manifest entries
    sorted_paths = sorted(manifest.keys())
    page = sorted_paths[offset:offset + limit]

    files = []
    for path in page:
        sha = manifest[path]
        files.append(FileEmbeddingStatus(
            path=path,
            content_sha=sha,
            has_embedding=sha in embedded_shas,
        ))

    return FileEmbeddingListResponse(
        files=files,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit < total),
    )


@router.get("/indexing/status", response_model=IndexingStatusResponse)
async def get_indexing_status(
    repo_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> IndexingStatusResponse:
    """Get combined indexing + embedding progress."""
    from attocode.code_intel.db.models import IndexingJob, Repository

    repo = await _get_repo(repo_id, session)

    # Count active indexing jobs
    active_result = await session.execute(
        select(func.count()).select_from(
            select(IndexingJob.id).where(
                IndexingJob.repo_id == repo_id,
                IndexingJob.status.in_(["queued", "running"]),
            ).subquery()
        )
    )
    active_jobs = active_result.scalar() or 0

    # Get embedding coverage
    resolved_ref = ref if ref else repo.default_branch
    total_files = 0
    embedded_files = 0
    coverage_pct = 0.0

    try:
        branch_ctx = await get_branch_context(repo_id, resolved_ref, session)
        content_shas = branch_ctx.content_shas
        total_files = len(content_shas)

        if total_files > 0:
            from attocode.code_intel.storage.embedding_store import EmbeddingStore

            store = EmbeddingStore(session)
            embedded_shas = await store.batch_has_embeddings(content_shas, "default")
            embedded_files = len(embedded_shas)
            coverage_pct = round(embedded_files / total_files * 100, 1)
    except HTTPException:
        pass

    return IndexingStatusResponse(
        index_status=repo.index_status,
        last_indexed_at=repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
        active_jobs=active_jobs,
        embedding_coverage_pct=coverage_pct,
        total_files=total_files,
        embedded_files=embedded_files,
    )
