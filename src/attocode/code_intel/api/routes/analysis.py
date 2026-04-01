"""Code analysis endpoints — unified v1 (text) + v2 (structured JSON)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import (
    BranchParam,
    ensure_branch_supported,
    get_analysis_provider,
    get_service_or_404,
)
from attocode.code_intel.api.models import (
    BootstrapRequest,
    BugScanRequest,
    ConventionsResponse,
    CrossRefResponse,
    DeadCodeRequest,
    DependencyGraphRequest,
    DependencyGraphResponse,
    DependencyResponse,
    DistillRequest,
    ExploreRequest,
    FileAnalysisResponse,
    HotspotsResponse,
    ImpactAnalysisResponse,
    NotifyFilesRequest,
    ReadinessReportRequest,
    RepoMapRankedRequest,
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
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.repo_map(include_symbols=include_symbols, max_tokens=max_tokens))


@router_v1.get("/summary", response_model=TextResult)
async def project_summary(
    project_id: str,
    branch: BranchParam = "",
    max_tokens: int = 4000,
) -> TextResult:
    """Get high-level project overview."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.project_summary(max_tokens=max_tokens))


@router_v1.post("/bootstrap", response_model=TextResult)
async def bootstrap(
    project_id: str,
    req: BootstrapRequest,
    branch: BranchParam = "",
) -> TextResult:
    """All-in-one codebase orientation."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.bootstrap(
        task_hint=req.task_hint,
        max_tokens=req.max_tokens,
        indexing_depth=req.indexing_depth,
    ))


@router_v1.get("/hydration")
async def hydration_status(
    project_id: str,
    branch: BranchParam = "",
) -> dict:
    """Progressive AST / embedding hydration state (MCP ``hydration_status`` parity)."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return svc.hydration_status()


@router_v1.get("/symbols", response_model=TextResult)
async def symbols_v1(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """List symbols in a file."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.symbols(path))


@router_v1.get("/search-symbols", response_model=TextResult)
async def search_symbols_v1(
    project_id: str,
    name: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Fuzzy symbol search across project."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.search_symbols(name))


@router_v1.get("/dependencies", response_model=TextResult)
async def dependencies_v1(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """File dependencies (forward/reverse)."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.dependencies(path))


@router_v1.get("/impact", response_model=TextResult)
async def impact_analysis_v1(
    project_id: str,
    files: Annotated[list[str], Query(description="Changed file paths")],
    branch: BranchParam = "",
) -> TextResult:
    """Transitive impact analysis."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.impact_analysis(files))


@router_v1.get("/cross-refs", response_model=TextResult)
async def cross_references_v1(
    project_id: str,
    symbol: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Symbol cross-references."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.cross_references(symbol))


@router_v1.get("/file-analysis", response_model=TextResult)
async def file_analysis_v1(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> TextResult:
    """Detailed single-file analysis."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.file_analysis(path))


@router_v1.post("/dependency-graph", response_model=TextResult)
async def dependency_graph_v1(
    project_id: str,
    req: DependencyGraphRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Dependency graph from a starting file."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.dependency_graph(req.start_file, depth=req.depth))


@router_v1.get("/hotspots", response_model=TextResult)
async def hotspots_v1(
    project_id: str,
    branch: BranchParam = "",
    top_n: int = 15,
) -> TextResult:
    """Risk/complexity analysis."""
    ensure_branch_supported(branch)
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
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.conventions(sample_size=sample_size, path=path))


@router_v1.post("/explore", response_model=TextResult)
async def explore(
    project_id: str,
    req: ExploreRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Hierarchical drill-down navigation."""
    ensure_branch_supported(branch)
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
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.security_scan(mode=req.mode, path=req.path))


@router_v1.post("/repo-map-ranked", response_model=TextResult)
async def repo_map_ranked_v1(
    project_id: str,
    req: RepoMapRankedRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Task-aware repository ranking."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.repo_map_ranked(
        task_context=req.task_context,
        token_budget=req.token_budget,
        exclude_tests=req.exclude_tests,
    ))


@router_v1.post("/dead-code", response_model=TextResult)
async def dead_code_v1(
    project_id: str,
    req: DeadCodeRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Dead-code detection."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.dead_code(
        scope=req.scope,
        entry_points=req.entry_points,
        level=req.level,
        min_confidence=req.min_confidence,
        top_n=req.top_n,
    ))


@router_v1.post("/distill", response_model=TextResult)
async def distill_v1(
    project_id: str,
    req: DistillRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Compressed codebase context."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.distill(
        files=req.files,
        depth=req.depth,
        level=req.level,
        max_tokens=req.max_tokens,
    ))


@router_v1.post("/readiness-report", response_model=TextResult)
async def readiness_report_v1(
    project_id: str,
    req: ReadinessReportRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Readiness audit report."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.readiness_report(
        phases=req.phases,
        scope=req.scope,
        tracer_bullets=req.tracer_bullets,
        min_severity=req.min_severity,
    ))


@router_v1.post("/bug-scan", response_model=TextResult)
async def bug_scan_v1(
    project_id: str,
    req: BugScanRequest,
    branch: BranchParam = "",
) -> TextResult:
    """Scan the current diff for likely bugs."""
    ensure_branch_supported(branch)
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.bug_scan(
        base_branch=req.base_branch,
        min_confidence=req.min_confidence,
    ))


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
    directory: str = Query("", alias="dir", description="Directory prefix filter"),
    branch: BranchParam = "",
) -> SymbolSearchResponse:
    """Fuzzy symbol search (structured)."""
    provider = await get_analysis_provider(project_id)
    return await provider.search_symbols(name, branch, directory=directory)


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
