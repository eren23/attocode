"""Graph query endpoints — unified v1 (text) + v2 (structured JSON)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import (
    BranchParam,
    get_graph_provider,
    get_service_or_404,
)
from attocode.code_intel.api.models import (
    CommunityResponse,
    FindRelatedRequest,
    FindRelatedResponse,
    GraphQueryRequest,
    GraphQueryResponse,
    RelevantContextRequest,
    TextResult,
)

# --- v1 router: text responses ---

router_v1 = APIRouter(
    prefix="/api/v1/projects/{project_id}/graph",
    tags=["graph"],
    dependencies=[Depends(verify_auth)],
)

# --- v2 router: structured JSON ---

router_v2 = APIRouter(
    prefix="/api/v2/projects/{project_id}/graph",
    tags=["graph-v2"],
    dependencies=[Depends(verify_auth)],
)


# ===================================================================
# v1 endpoints
# ===================================================================


@router_v1.post("/query", response_model=TextResult)
async def graph_query_v1(
    project_id: str,
    req: GraphQueryRequest,
    branch: BranchParam = "",
) -> TextResult:
    """BFS traversal over dependency edges."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.graph_query(
        file=req.file, edge_type=req.edge_type, direction=req.direction, depth=req.depth,
    ))


@router_v1.post("/related", response_model=TextResult)
async def find_related_v1(
    project_id: str,
    req: FindRelatedRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Find structurally related files."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.find_related(file=req.file, top_k=req.top_k))


@router_v1.get("/communities", response_model=TextResult)
async def community_detection_v1(
    project_id: str,
    branch: BranchParam = "",
    min_community_size: int = 3,
    max_communities: int = 20,
) -> TextResult:
    """Detect file communities."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.community_detection(
        min_community_size=min_community_size, max_communities=max_communities,
    ))


@router_v1.post("/context", response_model=TextResult)
async def relevant_context_v1(
    project_id: str,
    req: RelevantContextRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Get subgraph capsule for files with neighbors."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.relevant_context(
        files=req.files, depth=req.depth, max_tokens=req.max_tokens,
        include_symbols=req.include_symbols,
    ))


# ===================================================================
# v2 endpoints
# ===================================================================


@router_v2.post("/query", response_model=GraphQueryResponse)
async def graph_query_v2(
    project_id: str,
    req: GraphQueryRequest,
    branch: BranchParam = "",
) -> GraphQueryResponse:
    """BFS traversal over dependency edges (structured)."""
    provider = await get_graph_provider(project_id)
    return await provider.graph_query(
        file=req.file, edge_type=req.edge_type,
        direction=req.direction, depth=req.depth, branch=branch,
    )


@router_v2.post("/related", response_model=FindRelatedResponse)
async def find_related_v2(
    project_id: str,
    req: FindRelatedRequest,
    branch: BranchParam = "",
) -> FindRelatedResponse:
    """Find structurally related files (structured)."""
    provider = await get_graph_provider(project_id)
    return await provider.find_related(file=req.file, top_k=req.top_k, branch=branch)


@router_v2.get("/communities", response_model=CommunityResponse)
async def community_detection_v2(
    project_id: str,
    branch: BranchParam = "",
    min_community_size: int = 3,
    max_communities: int = 20,
) -> CommunityResponse:
    """Detect file communities (structured)."""
    provider = await get_graph_provider(project_id)
    return await provider.community_detection(
        branch=branch,
        min_community_size=min_community_size,
        max_communities=max_communities,
    )


@router_v2.post("/context", response_model=TextResult)
async def relevant_context_v2(
    project_id: str,
    req: RelevantContextRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Get subgraph capsule (text — inherently text-shaped)."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.relevant_context(
        files=req.files, depth=req.depth, max_tokens=req.max_tokens,
        include_symbols=req.include_symbols,
    ))


# Backward-compatible alias
router = router_v1
