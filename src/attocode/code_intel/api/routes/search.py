"""Search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import get_service_or_404
from attocode.code_intel.api.models import SemanticSearchRequest, TextResult

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["search"],
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


@router.post("/search", response_model=TextResult)
async def semantic_search(project_id: str, req: SemanticSearchRequest) -> TextResult:
    """Semantic search (vector + keyword RRF)."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.semantic_search(
        query=req.query, top_k=req.top_k, file_filter=req.file_filter,
    ))


@router.post("/index", response_model=IndexStatusResponse)
async def start_indexing(project_id: str) -> IndexStatusResponse:
    """Start background embedding indexing."""
    svc = get_service_or_404(project_id)
    result = svc.start_indexing()
    return IndexStatusResponse(**result)


@router.get("/index/status", response_model=IndexStatusResponse)
async def index_status(project_id: str) -> IndexStatusResponse:
    """Get current embedding index status."""
    svc = get_service_or_404(project_id)
    result = svc.indexing_status()
    return IndexStatusResponse(**result)
