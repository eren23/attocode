"""Code analysis endpoints — unified v1 (text) + v2 (structured JSON)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import (
    BranchParam,
    get_analysis_provider,
    get_service_or_404,
)
from attocode.code_intel.api.models import (
    BootstrapRequest,
    ConventionsResponse,
    CrossRefResponse,
    DependencyGraphRequest,
    DependencyGraphResponse,
    DependencyResponse,
    ExploreRequest,
    FileAnalysisResponse,
    HotspotsResponse,
    ImpactAnalysisResponse,
    NotifyFilesRequest,
    SecurityScanRequest,
    SymbolListResponse,
    SymbolSearchResponse,
    TextResult,
)

# --- v1 router: text responses (MCP-compatible) ---

router_v1 = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["analysis"],
    dependencies=[Depends(verify_auth)],
)

# --- v2 router: structured JSON responses ---

router_v2 = APIRouter(
    prefix="/api/v2/projects/{project_id}",
    tags=["analysis-v2"],
    dependencies=[Depends(verify_auth)],
)


# ===================================================================
# v1 endpoints — text output, call CodeIntelService directly
# ===================================================================


@router_v1.get("/map", response_model=TextResult)
async def repo_map(
    project_id: str,
    branch: BranchParam = "",
    include_symbols: bool = True,
    max_tokens: int = 6000,
) -> TextResult:
    """Get token-budgeted repository map."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.repo_map(include_symbols=include_symbols, max_tokens=max_tokens))


@router_v1.get("/summary", response_model=TextResult)
async def project_summary(
    project_id: str,
    branch: BranchParam = "",
    max_tokens: int = 4000,
) -> TextResult:
    """Get high-level project overview."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.project_summary(max_tokens=max_tokens))


@router_v1.post("/bootstrap", response_model=TextResult)
async def bootstrap(
    project_id: str,
    req: BootstrapRequest,
    branch: BranchParam = "",
) -> TextResult:
    """All-in-one codebase orientation."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.bootstrap(task_hint=req.task_hint, max_tokens=req.max_tokens))


@router_v1.get("/symbols", response_model=TextResult)
async def symbols_v1(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """List symbols in a file."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.symbols(path))


@router_v1.get("/search-symbols", response_model=TextResult)
async def search_symbols_v1(
    project_id: str,
    name: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Fuzzy symbol search across project."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.search_symbols(name))


@router_v1.get("/dependencies", response_model=TextResult)
async def dependencies_v1(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """File dependencies (forward/reverse)."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.dependencies(path))


@router_v1.get("/impact", response_model=TextResult)
async def impact_analysis_v1(
    project_id: str,
    files: Annotated[list[str], Query(description="Changed file paths")],
    branch: BranchParam = "",
) -> TextResult:
    """Transitive impact analysis."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.impact_analysis(files))


@router_v1.get("/cross-refs", response_model=TextResult)
async def cross_references_v1(
    project_id: str,
    symbol: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Symbol cross-references."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.cross_references(symbol))


@router_v1.get("/file-analysis", response_model=TextResult)
async def file_analysis_v1(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Detailed single-file analysis."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.file_analysis(path))


@router_v1.post("/dependency-graph", response_model=TextResult)
async def dependency_graph_v1(
    project_id: str,
    req: DependencyGraphRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Dependency graph from a starting file."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.dependency_graph(req.start_file, depth=req.depth))


@router_v1.get("/hotspots", response_model=TextResult)
async def hotspots_v1(
    project_id: str,
    branch: BranchParam = "",
    top_n: int = 15,
) -> TextResult:
    """Risk/complexity analysis."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.hotspots(top_n=top_n))


@router_v1.get("/conventions", response_model=TextResult)
async def conventions_v1(
    project_id: str,
    branch: BranchParam = "",
    sample_size: int = 50,
    path: str = "",
) -> TextResult:
    """Coding conventions."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.conventions(sample_size=sample_size, path=path))


@router_v1.post("/explore", response_model=TextResult)
async def explore(
    project_id: str,
    req: ExploreRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Hierarchical drill-down navigation."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.explore_codebase(
        path=req.path, max_items=req.max_items, importance_threshold=req.importance_threshold,
    ))


@router_v1.post("/security-scan", response_model=TextResult)
async def security_scan_v1(
    project_id: str,
    req: SecurityScanRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Security analysis."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.security_scan(mode=req.mode, path=req.path))


@router_v1.post("/notify", response_model=TextResult)
async def notify_files(project_id: str, req: NotifyFilesRequest) -> TextResult:
    """Notify about changed files."""
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.notify_file_changed(req.files))


# ===================================================================
# v2 endpoints — structured JSON, use providers
# ===================================================================


@router_v2.get("/symbols", response_model=SymbolListResponse)
async def symbols_v2(
    project_id: str,
    path: str = Query(""),
    branch: BranchParam = "",
) -> SymbolListResponse:
    """List symbols in a file (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.symbols(path, branch)


@router_v2.get("/search-symbols", response_model=SymbolSearchResponse)
async def search_symbols_v2(
    project_id: str,
    name: str = Query(...),
    dir: str = Query("", description="Directory prefix filter"),
    branch: BranchParam = "",
) -> SymbolSearchResponse:
    """Fuzzy symbol search (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.search_symbols(name, branch, directory=dir)


@router_v2.get("/dependencies", response_model=DependencyResponse)
async def dependencies_v2(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> DependencyResponse:
    """File dependencies (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.dependencies(path, branch)


@router_v2.post("/dependency-graph", response_model=DependencyGraphResponse)
async def dependency_graph_v2(
    project_id: str,
    req: DependencyGraphRequest,
    branch: BranchParam = "",
) -> DependencyGraphResponse:
    """Dependency graph (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.dependency_graph(req.start_file, req.depth, branch, directory=req.directory)


@router_v2.get("/impact", response_model=ImpactAnalysisResponse)
async def impact_analysis_v2(
    project_id: str,
    files: Annotated[list[str], Query(description="Changed file paths")],
    branch: BranchParam = "",
) -> ImpactAnalysisResponse:
    """Transitive impact analysis (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.impact_analysis(files, branch)


@router_v2.get("/cross-refs", response_model=CrossRefResponse)
async def cross_references_v2(
    project_id: str,
    symbol: str = Query(...),
    branch: BranchParam = "",
) -> CrossRefResponse:
    """Symbol cross-references (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.cross_references(symbol, branch)


@router_v2.get("/file-analysis", response_model=FileAnalysisResponse)
async def file_analysis_v2(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> FileAnalysisResponse:
    """Detailed single-file analysis (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.file_analysis(path, branch)


@router_v2.get("/hotspots", response_model=HotspotsResponse)
async def hotspots_v2(
    project_id: str,
    branch: BranchParam = "",
    top_n: int = Query(15, ge=1, le=200),
) -> HotspotsResponse:
    """Risk/complexity hotspots (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.hotspots(branch, top_n)


@router_v2.get("/conventions", response_model=ConventionsResponse)
async def conventions_v2(
    project_id: str,
    branch: BranchParam = "",
    sample_size: int = 50,
    path: str = "",
) -> ConventionsResponse:
    """Coding conventions (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.conventions(branch, sample_size, path)


# Backward-compatible alias: old code may import `router` from this module.
router = router_v1
