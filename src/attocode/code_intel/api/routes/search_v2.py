"""Structured search endpoints (v2)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    SearchResultItem,
    SearchResultsResponse,
    SecurityFinding,
    SecurityScanRequest,
    SecurityScanResponse,
    SemanticSearchRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v2/projects/{project_id}",
    tags=["search-v2"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/search", response_model=SearchResultsResponse)
async def semantic_search(
    project_id: str,
    req: SemanticSearchRequest,
    branch: BranchParam = "",
) -> SearchResultsResponse:
    """Semantic search (structured).

    In service mode with pgvector, embeds the query and runs cosine similarity search.
    Falls back to the local service's text-based search otherwise.
    """
    # Try pgvector-backed search in service mode
    try:
        from attocode.code_intel.api.deps import get_config

        config = get_config()
        if config.is_service_mode:
            return await _pgvector_search(project_id, req, branch)
    except Exception:
        logger.debug("pgvector search unavailable, falling back to local", exc_info=True)

    # Fallback: local service-based search
    svc = get_service_or_404(project_id)
    data = svc.semantic_search_data(
        query=req.query, top_k=req.top_k, file_filter=req.file_filter,
    )
    return SearchResultsResponse(
        query=data["query"],
        results=[SearchResultItem(**r) for r in data["results"]],
        total=data["total"],
    )


async def _pgvector_search(
    project_id: str,
    req: SemanticSearchRequest,
    branch: str,
) -> SearchResultsResponse:
    """Run pgvector cosine similarity search."""
    from attocode.code_intel.api.deps import get_branch_context, get_config
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.storage.embedding_store import EmbeddingStore
    from attocode.integrations.context.embeddings import create_embedding_provider

    config = get_config()
    provider = create_embedding_provider(config.embedding_model)
    if provider.name == "none":
        raise RuntimeError("No embedding provider available")

    # Embed the query
    query_vectors = provider.embed([req.query])
    query_vector = query_vectors[0]

    async for session in get_session():
        # Resolve the branch for this project/repo
        branch_ctx = await get_branch_context(
            project_id, branch or "main", session,
        )

        store = EmbeddingStore(session)
        results = await store.similarity_search(
            branch_id=branch_ctx.branch_id,
            query_vector=query_vector,
            top_k=req.top_k,
            model=provider.name,
        )

        return SearchResultsResponse(
            query=req.query,
            results=[
                SearchResultItem(
                    file_path=r["file"],
                    score=r.get("score", 0.0),
                    snippet=r.get("chunk_text", ""),
                )
                for r in results
            ],
            total=len(results),
        )

    raise RuntimeError("No database session available")


@router.post("/security-scan", response_model=SecurityScanResponse)
async def security_scan(
    project_id: str,
    req: SecurityScanRequest,
    branch: BranchParam = "",
) -> SecurityScanResponse:
    """Security analysis (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.security_scan_data(mode=req.mode, path=req.path)
    return SecurityScanResponse(
        mode=data["mode"],
        path=data["path"],
        findings=[SecurityFinding(**f) for f in data["findings"]],
        total_findings=data["total_findings"],
        summary=data.get("summary", {}),
    )
