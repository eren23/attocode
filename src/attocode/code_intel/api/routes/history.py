"""History endpoints — code evolution and change-history utilities."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import BranchParam, ensure_branch_supported, get_service_or_404
from attocode.code_intel.api.models import ChangeCouplingRequest, MergeRiskRequest, TextResult

router_v1 = APIRouter(
    prefix="/api/v1/projects/{project_id}/history",
    tags=["history"],
    dependencies=[Depends(verify_auth)],
)

router_v2 = APIRouter(
    prefix="/api/v2/projects/{project_id}",
    tags=["history-v2"],
    dependencies=[Depends(verify_auth)],
)
logger = logging.getLogger(__name__)


# --- Response models ---


class FileStatEntry(BaseModel):
    path: str
    added: int = 0
    removed: int = 0


class EvolutionCommit(BaseModel):
    sha: str
    author: str
    email: str
    date: str
    subject: str
    files: list[FileStatEntry] = []


class CodeEvolutionResponse(BaseModel):
    path: str
    symbol: str = ""
    since: str = ""
    commits: list[EvolutionCommit]
    total: int


class RecentFileEntry(BaseModel):
    path: str
    commits: int
    added: int
    removed: int
    last_date: str = ""


class RecentChangesResponse(BaseModel):
    days: int
    path: str = ""
    commit_count: int
    total_files_changed: int
    files: list[RecentFileEntry]


# --- Endpoints ---


@router_v1.get("/evolution", response_model=TextResult)
async def code_evolution_v1(
    project_id: str,
    path: str = Query(..., description="File path to trace history for"),
    symbol: str = Query("", description="Optional symbol name filter"),
    since: str = Query("", description="Date filter (e.g. '2024-01-01', '3 months ago')"),
    max_results: int = Query(20, ge=1, le=100),
    branch: BranchParam = "",
) -> TextResult:
    """Get change history for a file or symbol."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.code_evolution(
        path=path,
        symbol=symbol,
        since=since,
        max_results=max_results,
    ))


@router_v1.get("/recent-changes", response_model=TextResult)
async def recent_changes_v1(
    project_id: str,
    days: int = Query(7, ge=1, le=365),
    path: str = Query("", description="Optional path prefix filter"),
    top_n: int = Query(20, ge=1, le=200),
    branch: BranchParam = "",
) -> TextResult:
    """Show recently modified files and change frequency."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.recent_changes(days=days, path=path, top_n=top_n))


@router_v1.post("/change-coupling", response_model=TextResult)
async def change_coupling_v1(
    project_id: str,
    req: ChangeCouplingRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Find files that frequently change together."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.change_coupling(
        file=req.file,
        days=req.days,
        min_coupling=req.min_coupling,
        top_k=req.top_k,
    ))


@router_v1.get("/churn-hotspots", response_model=TextResult)
async def churn_hotspots_v1(
    project_id: str,
    days: int = Query(90, ge=1, le=3650),
    top_n: int = Query(20, ge=1, le=200),
    branch: BranchParam = "",
) -> TextResult:
    """Rank high-churn files."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.churn_hotspots(days=days, top_n=top_n))


@router_v1.post("/merge-risk", response_model=TextResult)
async def merge_risk_v1(
    project_id: str,
    req: MergeRiskRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Predict additional files likely to require changes."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.merge_risk(files=req.files, days=req.days))


@router_v2.get("/evolution", response_model=CodeEvolutionResponse)
async def code_evolution(
    project_id: str,
    path: str = Query(..., description="File path to trace history for"),
    symbol: str = Query("", description="Optional symbol name filter"),
    since: str = Query("", description="Date filter (e.g. '2024-01-01', '3 months ago')"),
    max_results: int = Query(20, ge=1, le=100),
) -> CodeEvolutionResponse:
    """Get change history for a file or symbol."""
    svc = await get_service_or_404(project_id)
    data = svc.code_evolution_data(
        path=path, symbol=symbol, since=since, max_results=max_results,
    )
    return CodeEvolutionResponse(**data)


@router_v2.get("/recent-changes", response_model=RecentChangesResponse)
async def recent_changes(
    project_id: str,
    days: int = Query(7, ge=1, le=365),
    path: str = Query("", description="Optional path prefix filter"),
    top_n: int = Query(20, ge=1, le=200),
) -> RecentChangesResponse:
    """Show recently modified files and change frequency."""
    svc = await get_service_or_404(project_id)
    data = svc.recent_changes_data(days=days, path=path, top_n=top_n)
    return RecentChangesResponse(**data)


router = router_v1
