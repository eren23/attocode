"""Structured LSP proxy endpoints (v2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    LSPDefinitionResponse,
    LSPDiagnosticItem,
    LSPDiagnosticsResponse,
    LSPHoverResponse,
    LSPLocation,
    LSPPositionRequest,
    LSPReferencesRequest,
    LSPReferencesResponse,
)

router = APIRouter(
    prefix="/api/v2/projects/{project_id}/lsp",
    tags=["lsp-v2"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/definition", response_model=LSPDefinitionResponse)
async def lsp_definition(
    project_id: str,
    req: LSPPositionRequest,
    branch: BranchParam = "",
) -> LSPDefinitionResponse:
    """Go-to-definition via LSP (structured)."""
    svc = get_service_or_404(project_id)
    data = await svc.lsp_definition_data(file=req.file, line=req.line, col=req.col)
    loc = data.get("location")
    return LSPDefinitionResponse(
        location=LSPLocation(**loc) if loc else None,
        error=data.get("error"),
    )


@router.post("/references", response_model=LSPReferencesResponse)
async def lsp_references(
    project_id: str,
    req: LSPReferencesRequest,
    branch: BranchParam = "",
) -> LSPReferencesResponse:
    """Find references via LSP (structured)."""
    svc = get_service_or_404(project_id)
    data = await svc.lsp_references_data(
        file=req.file, line=req.line, col=req.col,
        include_declaration=req.include_declaration,
    )
    return LSPReferencesResponse(
        locations=[LSPLocation(**loc) for loc in data["locations"]],
        total=data["total"],
        error=data.get("error"),
    )


@router.post("/hover", response_model=LSPHoverResponse)
async def lsp_hover(
    project_id: str,
    req: LSPPositionRequest,
    branch: BranchParam = "",
) -> LSPHoverResponse:
    """Hover info via LSP (structured)."""
    svc = get_service_or_404(project_id)
    data = await svc.lsp_hover_data(file=req.file, line=req.line, col=req.col)
    return LSPHoverResponse(**data)


@router.get("/diagnostics", response_model=LSPDiagnosticsResponse)
async def lsp_diagnostics(
    project_id: str,
    file: str = Query(...),
    branch: BranchParam = "",
) -> LSPDiagnosticsResponse:
    """Diagnostics from LSP (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.lsp_diagnostics_data(file=file)
    return LSPDiagnosticsResponse(
        file=data["file"],
        diagnostics=[LSPDiagnosticItem(**d) for d in data["diagnostics"]],
        total=data["total"],
        error=data.get("error"),
    )
