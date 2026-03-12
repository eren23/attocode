"""Structured search endpoints (v2)."""

from __future__ import annotations

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
    """Semantic search (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.semantic_search_data(
        query=req.query, top_k=req.top_k, file_filter=req.file_filter,
    )
    return SearchResultsResponse(
        query=data["query"],
        results=[SearchResultItem(**r) for r in data["results"]],
        total=data["total"],
    )


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
