"""ADR endpoints — text-oriented parity for MCP architecture-decision tools."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import BranchParam, ensure_branch_supported, get_service_or_404
from attocode.code_intel.api.models import RecordADRRequest, TextResult, UpdateADRStatusRequest

router_v1 = APIRouter(
    prefix="/api/v1/projects/{project_id}/adrs",
    tags=["adrs"],
    dependencies=[Depends(verify_auth)],
)


@router_v1.post("", response_model=TextResult)
async def record_adr_v1(
    project_id: str,
    req: RecordADRRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Record a new architecture decision."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.record_adr(
        title=req.title,
        context=req.context,
        decision=req.decision,
        consequences=req.consequences,
        related_files=req.related_files,
        tags=req.tags,
    ))


@router_v1.get("", response_model=TextResult)
async def list_adrs_v1(
    project_id: str,
    branch: BranchParam = "",
    status: str = "",
    tag: str = "",
    search: str = Query("", description="Search title, context, and decision"),
) -> TextResult:
    """List ADRs with optional filtering."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.list_adrs(status=status, tag=tag, search=search))


@router_v1.get("/{number}", response_model=TextResult)
async def get_adr_v1(
    project_id: str,
    number: int,
    branch: BranchParam = "",
) -> TextResult:
    """Fetch a single ADR."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.get_adr(number))


@router_v1.post("/{number}/status", response_model=TextResult)
async def update_adr_status_v1(
    project_id: str,
    number: int,
    req: UpdateADRStatusRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Update ADR lifecycle state."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.update_adr_status(
        number=number,
        status=req.status,
        superseded_by=req.superseded_by,
    ))


router = router_v1
