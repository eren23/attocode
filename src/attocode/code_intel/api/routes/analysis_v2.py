"""Structured analysis endpoints (v2 — returns JSON, not text)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    CodeChunkItem,
    ConventionsResponse,
    ConventionStats,
    CrossRefResponse,
    DependencyGraphRequest,
    DependencyGraphResponse,
    DependencyResponse,
    FileAnalysisResponse,
    FileMetricsItem,
    FunctionMetricsItem,
    HotspotsResponse,
    ImpactAnalysisResponse,
    ReferenceItem,
    RepoStatsResponse,
    SymbolItem,
    SymbolListResponse,
    SymbolSearchResponse,
)

router = APIRouter(
    prefix="/api/v2/projects/{project_id}",
    tags=["analysis-v2"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/symbols", response_model=SymbolListResponse)
async def symbols(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> SymbolListResponse:
    """List symbols in a file (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.symbols_data(path)
    return SymbolListResponse(
        path=path,
        symbols=[SymbolItem(**s) for s in data],
    )


@router.get("/search-symbols", response_model=SymbolSearchResponse)
async def search_symbols(
    project_id: str,
    name: str = Query(...),
    branch: BranchParam = "",
) -> SymbolSearchResponse:
    """Fuzzy symbol search (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.search_symbols_data(name)
    return SymbolSearchResponse(
        query=name,
        definitions=[SymbolItem(**s) for s in data],
    )


@router.get("/dependencies", response_model=DependencyResponse)
async def dependencies(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> DependencyResponse:
    """File dependencies (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.dependencies_data(path)
    return DependencyResponse(**data)


@router.post("/dependency-graph", response_model=DependencyGraphResponse)
async def dependency_graph(
    project_id: str,
    req: DependencyGraphRequest,
    branch: BranchParam = "",
) -> DependencyGraphResponse:
    """Dependency graph (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.dependency_graph_data(req.start_file, depth=req.depth)
    return DependencyGraphResponse(**data)


@router.get("/impact", response_model=ImpactAnalysisResponse)
async def impact_analysis(
    project_id: str,
    files: Annotated[list[str], Query(description="Changed file paths")],
    branch: BranchParam = "",
) -> ImpactAnalysisResponse:
    """Transitive impact analysis (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.impact_analysis_data(files)
    return ImpactAnalysisResponse(**data)


@router.get("/cross-refs", response_model=CrossRefResponse)
async def cross_references(
    project_id: str,
    symbol: str = Query(...),
    branch: BranchParam = "",
) -> CrossRefResponse:
    """Symbol cross-references (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.cross_references_data(symbol)
    return CrossRefResponse(
        symbol=data["symbol"],
        definitions=[SymbolItem(**d) for d in data["definitions"]],
        references=[ReferenceItem(**r) for r in data["references"]],
        total_references=data["total_references"],
    )


@router.get("/file-analysis", response_model=FileAnalysisResponse)
async def file_analysis(
    project_id: str,
    path: str = Query(...),
    branch: BranchParam = "",
) -> FileAnalysisResponse:
    """Detailed single-file analysis (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.file_analysis_data(path)
    return FileAnalysisResponse(
        path=data["path"],
        language=data["language"],
        line_count=data["line_count"],
        imports=data["imports"],
        exports=data["exports"],
        chunks=[CodeChunkItem(**c) for c in data["chunks"]],
    )


@router.get("/hotspots", response_model=HotspotsResponse)
async def hotspots(
    project_id: str,
    branch: BranchParam = "",
    top_n: int = Query(15, ge=1, le=200),
) -> HotspotsResponse:
    """Risk/complexity hotspots (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.hotspots_data(top_n=top_n)
    return HotspotsResponse(
        file_hotspots=[FileMetricsItem(**f) for f in data["file_hotspots"]],
        function_hotspots=[FunctionMetricsItem(**f) for f in data["function_hotspots"]],
        orphan_files=[FileMetricsItem(**f) for f in data["orphan_files"]],
    )


@router.get("/conventions", response_model=ConventionsResponse)
async def conventions(
    project_id: str,
    branch: BranchParam = "",
    sample_size: int = 50,
    path: str = "",
) -> ConventionsResponse:
    """Coding conventions (structured)."""
    svc = get_service_or_404(project_id)
    data = svc.conventions_data(sample_size=sample_size, path=path)
    return ConventionsResponse(
        sample_size=data["sample_size"],
        path=data["path"],
        stats=ConventionStats(**data["stats"]) if data["stats"] else ConventionStats(),
        dir_stats={
            k: ConventionStats(**v) for k, v in data.get("dir_stats", {}).items()
        },
    )


@router.get("/stats", response_model=RepoStatsResponse)
async def repo_stats(
    project_id: str,
    branch: BranchParam = "",
) -> RepoStatsResponse:
    """Aggregate repository statistics."""
    svc = get_service_or_404(project_id)
    data = svc.repo_stats_data()
    return RepoStatsResponse(**data)



# Text-only endpoints (map, summary, bootstrap, explore) live in v1 only.
# v2 is structured JSON — clients should use v1 for text endpoints.
