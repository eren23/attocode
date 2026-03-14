"""Search endpoints — unified v1 (text) + v2 (structured JSON)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import (
    BranchParam,
    get_search_provider,
    get_service_or_404,
)
from attocode.code_intel.api.models import (
    SearchResultsResponse,
    SecurityScanRequest,
    SecurityScanResponse,
    SemanticSearchRequest,
    TextResult,
)

logger = logging.getLogger(__name__)

# --- v1 router: text responses ---

router_v1 = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["search"],
    dependencies=[Depends(verify_api_key)],
)

# --- v2 router: structured JSON ---

router_v2 = APIRouter(
    prefix="/api/v2/projects/{project_id}",
    tags=["search-v2"],
    dependencies=[Depends(verify_api_key)],
)


class IndexStatusResponse(BaseModel):
    provider: str = ""
    available: bool = False
    status: str = "idle"
    total_files: int = 0
    indexed_files: int = 0
    failed_files: int = 0
    coverage: float = 0.0
    elapsed_seconds: float = 0.0
    vector_search_active: bool = False


# ===================================================================
# v1 endpoints
# ===================================================================


@router_v1.post("/search", response_model=TextResult)
async def semantic_search_v1(
    project_id: str,
    req: SemanticSearchRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Semantic search (vector + keyword RRF)."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.semantic_search(
        query=req.query, top_k=req.top_k, file_filter=req.file_filter,
    ))


@router_v1.post("/index", response_model=IndexStatusResponse)
async def start_indexing(
    project_id: str,
    branch: BranchParam = "",
) -> IndexStatusResponse:
    """Start background embedding indexing."""
    svc = await get_service_or_404(project_id)
    result = svc.start_indexing()
    return IndexStatusResponse(**result)


@router_v1.get("/index/status", response_model=IndexStatusResponse)
async def index_status(
    project_id: str,
    branch: BranchParam = "",
) -> IndexStatusResponse:
    """Get current embedding index status."""
    svc = await get_service_or_404(project_id)
    result = svc.indexing_status()
    return IndexStatusResponse(**result)


# ===================================================================
# v2 endpoints
# ===================================================================


@router_v2.post("/search", response_model=SearchResultsResponse)
async def semantic_search_v2(
    project_id: str,
    req: SemanticSearchRequest,
    branch: BranchParam = "",
) -> SearchResultsResponse:
    """Semantic search (structured).

    In service mode with pgvector, embeds the query and runs cosine similarity search.
    Falls back to the local service's text-based search otherwise.
    """
    from fastapi import HTTPException

    try:
        provider = await get_search_provider(project_id)
        return await provider.semantic_search(
            query=req.query, top_k=req.top_k, file_filter=req.file_filter, branch=branch,
        )
    except (RuntimeError, ImportError) as exc:
        logger.warning("Search unavailable for project %s: %s", project_id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Search is not available: {exc}",
        ) from exc


@router_v2.post("/security-scan", response_model=SecurityScanResponse)
async def security_scan_v2(
    project_id: str,
    req: SecurityScanRequest,
    branch: BranchParam = "",
) -> SecurityScanResponse:
    """Security analysis (structured)."""
    provider = await get_search_provider(project_id)
    return await provider.security_scan(mode=req.mode, path=req.path, branch=branch)


# Backward-compatible alias
router = router_v1
