"""History endpoints — code evolution and recent changes (v2 structured JSON)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import get_service_or_404

router = APIRouter(
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


@router.get("/evolution", response_model=CodeEvolutionResponse)
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


@router.get("/recent-changes", response_model=RecentChangesResponse)
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
