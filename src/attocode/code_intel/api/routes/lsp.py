"""LSP proxy endpoints — unified v1 (text) + v2 (structured JSON)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import (
    BranchParam,
    ensure_branch_supported,
    get_lsp_provider,
    get_service_or_404,
)
from attocode.code_intel.api.models import (
    LSPDefinitionResponse,
    LSPDiagnosticsResponse,
    LSPEnrichRequest,
    LSPHoverResponse,
    LSPPositionRequest,
    LSPReferencesRequest,
    LSPReferencesResponse,
    TextResult,
)

# --- v1 router: text responses ---

router_v1 = APIRouter(
    prefix="/api/v1/projects/{project_id}/lsp",
    tags=["lsp"],
    dependencies=[Depends(verify_auth)],
)

# --- v2 router: structured JSON ---

router_v2 = APIRouter(
    prefix="/api/v2/projects/{project_id}/lsp",
    tags=["lsp-v2"],
    dependencies=[Depends(verify_auth)],
)


# ===================================================================
# v1 endpoints
# ===================================================================


@router_v1.post("/definition", response_model=TextResult)
async def lsp_definition_v1(
    project_id: str,
    req: LSPPositionRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Go-to-definition via LSP."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_definition(file=req.file, line=req.line, col=req.col))


@router_v1.post("/references", response_model=TextResult)
async def lsp_references_v1(
    project_id: str,
    req: LSPReferencesRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Find references via LSP."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_references(
        file=req.file, line=req.line, col=req.col,
        include_declaration=req.include_declaration,
    ))


@router_v1.post("/hover", response_model=TextResult)
async def lsp_hover_v1(
    project_id: str,
    req: LSPPositionRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Hover info via LSP."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_hover(file=req.file, line=req.line, col=req.col))


@router_v1.get("/diagnostics", response_model=TextResult)
async def lsp_diagnostics_v1(
    project_id: str,
    file: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Diagnostics from LSP."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.lsp_diagnostics(file=file))


@router_v1.post("/enrich", response_model=TextResult)
async def lsp_enrich_v1(
    project_id: str,
    req: LSPEnrichRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Enrich cross-references using LSP data."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=await svc.lsp_enrich(req.files))


# ===================================================================
# v2 endpoints
# ===================================================================


@router_v2.post("/definition", response_model=LSPDefinitionResponse)
async def lsp_definition_v2(
    project_id: str,
    req: LSPPositionRequest,
    branch: BranchParam = "",
) -> LSPDefinitionResponse:
    """Go-to-definition via LSP (structured)."""
    provider = await get_lsp_provider(project_id)
    return await provider.definition(file=req.file, line=req.line, col=req.col, branch=branch)


@router_v2.post("/references", response_model=LSPReferencesResponse)
async def lsp_references_v2(
    project_id: str,
    req: LSPReferencesRequest,
    branch: BranchParam = "",
) -> LSPReferencesResponse:
    """Find references via LSP (structured)."""
    provider = await get_lsp_provider(project_id)
    return await provider.references(
        file=req.file, line=req.line, col=req.col,
        include_declaration=req.include_declaration, branch=branch,
    )


@router_v2.post("/hover", response_model=LSPHoverResponse)
async def lsp_hover_v2(
    project_id: str,
    req: LSPPositionRequest,
    branch: BranchParam = "",
) -> LSPHoverResponse:
    """Hover info via LSP (structured)."""
    provider = await get_lsp_provider(project_id)
    return await provider.hover(file=req.file, line=req.line, col=req.col, branch=branch)


@router_v2.get("/diagnostics", response_model=LSPDiagnosticsResponse)
async def lsp_diagnostics_v2(
    project_id: str,
    file: str = Query(...),
    branch: BranchParam = "",
) -> LSPDiagnosticsResponse:
    """Diagnostics from LSP (structured)."""
    provider = await get_lsp_provider(project_id)
    return await provider.diagnostics(file=file, branch=branch)


# Backward-compatible alias
router = router_v1
