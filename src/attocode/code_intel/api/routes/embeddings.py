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

router = APIRouter(prefix="/api/v2/projects/{project_id}", tags=["embeddings"])
logger = logging.getLogger(__name__)


# --- Response models ---


class EmbeddingStatusResponse(BaseModel):
    total_files: int
    embedded_files: int
    coverage_pct: float
    model: str
    provider_available: bool = True
    provider_hint: str = ""


class FileEmbeddingStatus(BaseModel):
    path: str
    content_sha: str
    has_embedding: bool
    chunk_count: int = 0
    last_embedded_at: str | None = None


class FileEmbeddingListResponse(BaseModel):
    files: list[FileEmbeddingStatus]
    total: int
    limit: int
    offset: int
    has_more: bool


class SimilarFileItem(BaseModel):
    file_path: str
    score: float
    snippet: str = ""


class FindSimilarResponse(BaseModel):
    source_file: str
    similar: list[SimilarFileItem]


class IndexingStatusResponse(BaseModel):
    index_status: str
    last_indexed_at: str | None = None
    active_jobs: int = 0
    embedding_coverage_pct: float = 0.0
    total_files: int = 0
    embedded_files: int = 0


# --- Helpers ---


async def _get_repo(project_id: uuid.UUID, session: AsyncSession):
    from attocode.code_intel.db.models import Repository

    result = await session.execute(select(Repository).where(Repository.id == project_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _resolve_model_name(model: str) -> str:
    """Resolve 'default' to the actual embedding provider name."""
    if model != "default":
        return model
    try:
        from attocode.code_intel.api.deps import get_config
        from attocode.integrations.context.embeddings import create_embedding_provider
        config = get_config()
        provider = create_embedding_provider(config.embedding_model)
        return provider.name
    except Exception:
        return model


# --- Endpoints ---


@router.get("/embeddings/status", response_model=EmbeddingStatusResponse)
async def get_embedding_status(
    project_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    model: str = Query("default", description="Embedding model name."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> EmbeddingStatusResponse:
    """Get embedding coverage for a repo branch."""
    repo = await _get_repo(project_id, session)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(project_id, resolved_ref, session)
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

    model = _resolve_model_name(model)
    store = EmbeddingStore(session)
    embedded_shas = await store.batch_has_embeddings(content_shas, model)
    embedded = len(embedded_shas)

    response = EmbeddingStatusResponse(
        total_files=total,
        embedded_files=embedded,
        coverage_pct=round(embedded / total * 100, 1) if total > 0 else 0.0,
        model=model,
    )

    from attocode.integrations.context.embeddings import create_embedding_provider
    from attocode.code_intel.api.deps import get_config

    config = get_config()
    try:
        provider = create_embedding_provider(config.embedding_model)
        if provider.name == "none":
            response.provider_available = False
            response.provider_hint = (
                "No embedding provider detected. "
                "Install sentence-transformers (`pip install attocode[semantic]`) or set OPENAI_API_KEY."
            )
    except (ImportError, RuntimeError) as exc:
        response.provider_available = False
        response.provider_hint = str(exc)

    return response


@router.get("/embeddings/files", response_model=FileEmbeddingListResponse)
async def get_file_embedding_status(
    project_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    model: str = Query("default", description="Embedding model name."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Filter files by path substring (case-insensitive)."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> FileEmbeddingListResponse:
    """Get per-file embedding status (paginated)."""
    repo = await _get_repo(project_id, session)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(project_id, resolved_ref, session)
    except HTTPException:
        return FileEmbeddingListResponse(
            files=[], total=0, limit=limit, offset=offset, has_more=False,
        )

    manifest = branch_ctx.manifest
    content_shas = branch_ctx.content_shas
    total = len(manifest)

    # Batch check which SHAs have embeddings
    from attocode.code_intel.storage.embedding_store import EmbeddingStore

    model = _resolve_model_name(model)
    store = EmbeddingStore(session)
    stats = await store.batch_embedding_stats(content_shas, model)

    # Paginate over sorted manifest entries
    sorted_paths = sorted(manifest.keys())
    if search:
        search_lower = search.lower()
        sorted_paths = [p for p in sorted_paths if search_lower in p.lower()]
    total = len(sorted_paths)  # recalculate after filtering
    page = sorted_paths[offset:offset + limit]

    files = []
    for path in page:
        sha = manifest[path]
        sha_stats = stats.get(sha)
        files.append(FileEmbeddingStatus(
            path=path,
            content_sha=sha,
            has_embedding=sha_stats is not None,
            chunk_count=sha_stats["chunk_count"] if sha_stats else 0,
            last_embedded_at=sha_stats["last_embedded"].isoformat() if sha_stats and sha_stats["last_embedded"] else None,
        ))

    return FileEmbeddingListResponse(
        files=files,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit < total),
    )


@router.post("/embeddings/similar", response_model=FindSimilarResponse)
async def find_similar_files(
    project_id: uuid.UUID,
    content_sha: str = Query(..., description="Content SHA of source file"),
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> FindSimilarResponse:
    """Find files similar to a given file by its content SHA."""
    repo = await _get_repo(project_id, session)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(project_id, resolved_ref, session)
    except HTTPException:
        return FindSimilarResponse(source_file="unknown", similar=[])

    model = _resolve_model_name("default")

    from attocode.code_intel.storage.embedding_store import EmbeddingStore

    store = EmbeddingStore(session)
    results = await store.find_similar_by_sha(
        branch_ctx.branch_id, content_sha, top_k=10, model=model,
    )

    # Resolve source file path
    sha_to_path = {sha: path for path, sha in branch_ctx.manifest.items()}
    source_file = sha_to_path.get(content_sha, "unknown")

    return FindSimilarResponse(
        source_file=source_file,
        similar=[
            SimilarFileItem(
                file_path=r["file"],
                score=r["score"],
                snippet=r.get("chunk_text", "")[:200],
            )
            for r in results
        ],
    )


class GenerateEmbeddingsRequest(BaseModel):
    branch: str = "main"


class GenerateEmbeddingsResponse(BaseModel):
    job_id: str
    status: str
    message: str


@router.post("/embeddings/generate", response_model=GenerateEmbeddingsResponse)
async def trigger_generate_embeddings(
    project_id: uuid.UUID,
    req: GenerateEmbeddingsRequest = GenerateEmbeddingsRequest(),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> GenerateEmbeddingsResponse:
    """Trigger embedding generation for a branch.

    Enqueues an ARQ background job to generate embeddings for all files
    in the specified branch that don't already have them.
    """
    # Validate that the repository exists (raises 404 otherwise).
    await _get_repo(project_id, session)

    # Fail fast if no embedding provider is available
    from attocode.integrations.context.embeddings import create_embedding_provider
    from attocode.code_intel.api.deps import get_config

    config = get_config()
    try:
        provider = create_embedding_provider(config.embedding_model)
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if provider.name == "none":
        raise HTTPException(
            status_code=400,
            detail="No embedding provider available. Install sentence-transformers or set OPENAI_API_KEY.",
        )

    # Enqueue the ARQ job
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        from attocode.code_intel.api.deps import get_config

        config = get_config()
        if not config.redis_url:
            raise HTTPException(status_code=503, detail="Redis not configured — cannot enqueue jobs")

        redis_settings = RedisSettings.from_dsn(config.redis_url)
        pool = await create_pool(redis_settings)
        job = await pool.enqueue_job(
            "generate_embeddings",
            str(project_id),
            req.branch,
        )
        await pool.close()

        return GenerateEmbeddingsResponse(
            job_id=job.job_id if job else "unknown",
            status="queued",
            message=f"Embedding generation queued for branch '{req.branch}'",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to enqueue embedding generation job")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {e}")


@router.get("/indexing/status", response_model=IndexingStatusResponse)
async def get_indexing_status(
    project_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> IndexingStatusResponse:
    """Get combined indexing + embedding progress."""
    from attocode.code_intel.db.models import IndexingJob

    repo = await _get_repo(project_id, session)

    # Count active indexing jobs
    active_result = await session.execute(
        select(func.count()).select_from(
            select(IndexingJob.id).where(
                IndexingJob.repo_id == project_id,
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
        branch_ctx = await get_branch_context(project_id, resolved_ref, session)
        content_shas = branch_ctx.content_shas
        total_files = len(content_shas)

        if total_files > 0:
            from attocode.code_intel.storage.embedding_store import EmbeddingStore

            store = EmbeddingStore(session)
            embedded_shas = await store.batch_has_embeddings(content_shas, _resolve_model_name("default"))
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
