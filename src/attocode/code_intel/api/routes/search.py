"""Search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import get_service_or_404
from attocode.code_intel.api.models import SemanticSearchRequest, TextResult

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["search"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/search", response_model=TextResult)
async def semantic_search(project_id: str, req: SemanticSearchRequest) -> TextResult:
    """Semantic search (vector + keyword RRF)."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.semantic_search(
        query=req.query, top_k=req.top_k, file_filter=req.file_filter,
    ))
