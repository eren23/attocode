"""Code analysis endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import get_service_or_404
from attocode.code_intel.api.models import (
    BootstrapRequest,
    DependencyGraphRequest,
    ExploreRequest,
    NotifyFilesRequest,
    SecurityScanRequest,
    TextResult,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["analysis"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/map", response_model=TextResult)
async def repo_map(
    project_id: str,
    include_symbols: bool = True,
    max_tokens: int = 6000,
) -> TextResult:
    """Get token-budgeted repository map."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.repo_map(include_symbols=include_symbols, max_tokens=max_tokens))


@router.get("/summary", response_model=TextResult)
async def project_summary(project_id: str, max_tokens: int = 4000) -> TextResult:
    """Get high-level project overview."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.project_summary(max_tokens=max_tokens))


@router.post("/bootstrap", response_model=TextResult)
async def bootstrap(project_id: str, req: BootstrapRequest) -> TextResult:
    """All-in-one codebase orientation."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.bootstrap(task_hint=req.task_hint, max_tokens=req.max_tokens))


@router.get("/symbols", response_model=TextResult)
async def symbols(project_id: str, path: str = Query(...)) -> TextResult:
    """List symbols in a file."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.symbols(path))


@router.get("/search-symbols", response_model=TextResult)
async def search_symbols(project_id: str, name: str = Query(...)) -> TextResult:
    """Fuzzy symbol search across project."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.search_symbols(name))


@router.get("/dependencies", response_model=TextResult)
async def dependencies(project_id: str, path: str = Query(...)) -> TextResult:
    """File dependencies (forward/reverse)."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.dependencies(path))


@router.get("/impact", response_model=TextResult)
async def impact_analysis(project_id: str, files: list[str] = Query(..., description="Changed file paths")) -> TextResult:
    """Transitive impact analysis."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.impact_analysis(files))


@router.get("/cross-refs", response_model=TextResult)
async def cross_references(project_id: str, symbol: str = Query(...)) -> TextResult:
    """Symbol cross-references."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.cross_references(symbol))


@router.get("/file-analysis", response_model=TextResult)
async def file_analysis(project_id: str, path: str = Query(...)) -> TextResult:
    """Detailed single-file analysis."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.file_analysis(path))


@router.post("/dependency-graph", response_model=TextResult)
async def dependency_graph(project_id: str, req: DependencyGraphRequest) -> TextResult:
    """Dependency graph from a starting file."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.dependency_graph(req.start_file, depth=req.depth))


@router.get("/hotspots", response_model=TextResult)
async def hotspots(project_id: str, top_n: int = 15) -> TextResult:
    """Risk/complexity analysis."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.hotspots(top_n=top_n))


@router.get("/conventions", response_model=TextResult)
async def conventions(project_id: str, sample_size: int = 50, path: str = "") -> TextResult:
    """Coding conventions."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.conventions(sample_size=sample_size, path=path))


@router.post("/explore", response_model=TextResult)
async def explore(project_id: str, req: ExploreRequest) -> TextResult:
    """Hierarchical drill-down navigation."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.explore_codebase(
        path=req.path, max_items=req.max_items, importance_threshold=req.importance_threshold,
    ))


@router.post("/security-scan", response_model=TextResult)
async def security_scan(project_id: str, req: SecurityScanRequest) -> TextResult:
    """Security analysis."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.security_scan(mode=req.mode, path=req.path))


@router.post("/notify", response_model=TextResult)
async def notify_files(project_id: str, req: NotifyFilesRequest) -> TextResult:
    """Notify about changed files."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.notify_file_changed(req.files))
