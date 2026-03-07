"""Graph query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import get_service_or_404
from attocode.code_intel.api.models import (
    FindRelatedRequest,
    GraphQueryRequest,
    RelevantContextRequest,
    TextResult,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/graph",
    tags=["graph"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/query", response_model=TextResult)
async def graph_query(project_id: str, req: GraphQueryRequest) -> TextResult:
    """BFS traversal over dependency edges."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.graph_query(
        file=req.file, edge_type=req.edge_type, direction=req.direction, depth=req.depth,
    ))


@router.post("/related", response_model=TextResult)
async def find_related(project_id: str, req: FindRelatedRequest) -> TextResult:
    """Find structurally related files."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.find_related(file=req.file, top_k=req.top_k))


@router.get("/communities", response_model=TextResult)
async def community_detection(
    project_id: str,
    min_community_size: int = 3,
    max_communities: int = 20,
) -> TextResult:
    """Detect file communities."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.community_detection(
        min_community_size=min_community_size, max_communities=max_communities,
    ))


@router.post("/context", response_model=TextResult)
async def relevant_context(project_id: str, req: RelevantContextRequest) -> TextResult:
    """Get subgraph capsule for files with neighbors."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.relevant_context(
        files=req.files, depth=req.depth, max_tokens=req.max_tokens,
        include_symbols=req.include_symbols,
    ))
