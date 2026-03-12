"""Structured graph query endpoints (v2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    CommunityItem,
    CommunityResponse,
    FindRelatedRequest,
    FindRelatedResponse,
    GraphQueryHop,
    GraphQueryRequest,
    GraphQueryResponse,
    RelatedFileItem,
    RelevantContextRequest,
    TextResult,
)

router = APIRouter(
    prefix="/api/v2/projects/{project_id}/graph",
    tags=["graph-v2"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/query", response_model=GraphQueryResponse)
async def graph_query(
    project_id: str,
    req: GraphQueryRequest,
    branch: BranchParam = "",
) -> GraphQueryResponse:
    """BFS traversal over dependency edges (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.graph_query_data(
        file=req.file, edge_type=req.edge_type,
        direction=req.direction, depth=req.depth,
    )
    return GraphQueryResponse(
        root=data["root"],
        direction=data["direction"],
        depth=data["depth"],
        hops=[GraphQueryHop(**h) for h in data["hops"]],
        total_reachable=data["total_reachable"],
    )


@router.post("/related", response_model=FindRelatedResponse)
async def find_related(
    project_id: str,
    req: FindRelatedRequest,
    branch: BranchParam = "",
) -> FindRelatedResponse:
    """Find structurally related files (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.find_related_data(file=req.file, top_k=req.top_k)
    return FindRelatedResponse(
        file=data["file"],
        related=[RelatedFileItem(**r) for r in data["related"]],
    )


@router.get("/communities", response_model=CommunityResponse)
async def community_detection(
    project_id: str,
    branch: BranchParam = "",
    min_community_size: int = 3,
    max_communities: int = 20,
) -> CommunityResponse:
    """Detect file communities (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.community_detection_data(
        min_community_size=min_community_size,
        max_communities=max_communities,
    )
    return CommunityResponse(
        method=data["method"],
        modularity=data["modularity"],
        communities=[CommunityItem(**c) for c in data["communities"]],
    )


@router.post("/context", response_model=TextResult)
async def relevant_context(
    project_id: str,
    req: RelevantContextRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Get subgraph capsule (text — inherently text-shaped)."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.relevant_context(
        files=req.files, depth=req.depth, max_tokens=req.max_tokens,
        include_symbols=req.include_symbols,
    ))
