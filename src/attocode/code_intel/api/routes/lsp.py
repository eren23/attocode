"""LSP proxy endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import get_service_or_404
from attocode.code_intel.api.models import LSPPositionRequest, LSPReferencesRequest, TextResult

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/lsp",
    tags=["lsp"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/definition", response_model=TextResult)
async def lsp_definition(project_id: str, req: LSPPositionRequest) -> TextResult:
    """Go-to-definition via LSP."""
    svc = get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_definition(file=req.file, line=req.line, col=req.col))


@router.post("/references", response_model=TextResult)
async def lsp_references(project_id: str, req: LSPReferencesRequest) -> TextResult:
    """Find references via LSP."""
    svc = get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_references(
        file=req.file, line=req.line, col=req.col,
        include_declaration=req.include_declaration,
    ))


@router.post("/hover", response_model=TextResult)
async def lsp_hover(project_id: str, req: LSPPositionRequest) -> TextResult:
    """Hover info via LSP."""
    svc = get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_hover(file=req.file, line=req.line, col=req.col))


@router.get("/diagnostics", response_model=TextResult)
async def lsp_diagnostics(project_id: str, file: str = Query(...)) -> TextResult:
    """Diagnostics from LSP."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.lsp_diagnostics(file=file))
