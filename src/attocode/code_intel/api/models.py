"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# ------------------------------------------------------------------
# Common
# ------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str


# ------------------------------------------------------------------
# Projects
# ------------------------------------------------------------------


class ProjectRegister(BaseModel):
    path: str = Field(..., description="Local path to the project directory")
    name: str = Field("", description="Optional human-readable name (auto-detected if empty)")


class ProjectInfo(BaseModel):
    id: str
    name: str
    path: str
    status: str
    file_count: int = 0
    symbol_count: int = 0


class ProjectListResponse(BaseModel):
    projects: list[ProjectInfo]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


# ------------------------------------------------------------------
# Analysis
# ------------------------------------------------------------------


class DependencyGraphRequest(BaseModel):
    start_file: str = ""
    depth: int = Field(3, ge=1, le=10)
    directory: str = ""


class GraphQueryRequest(BaseModel):
    file: str
    edge_type: str = "IMPORTS"
    direction: str = "outbound"
    depth: int = 2


class FindRelatedRequest(BaseModel):
    file: str
    top_k: int = 10


class RelevantContextRequest(BaseModel):
    files: list[str]
    depth: int = 1
    max_tokens: int = 4000
    include_symbols: bool = True


class BootstrapRequest(BaseModel):
    task_hint: str = ""
    max_tokens: int = 8000


class ExploreRequest(BaseModel):
    path: str = ""
    max_items: int = 30
    importance_threshold: float = 0.3


class SecurityScanRequest(BaseModel):
    mode: str = "full"
    path: str = ""


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------


class SemanticSearchRequest(BaseModel):
    query: str
    top_k: int = 10
    file_filter: str = ""


# ------------------------------------------------------------------
# Learning
# ------------------------------------------------------------------


class RecordLearningRequest(BaseModel):
    type: str
    description: str
    details: str = ""
    scope: str = ""
    confidence: float = 0.7


class LearningFeedbackRequest(BaseModel):
    helpful: bool


# ------------------------------------------------------------------
# LSP
# ------------------------------------------------------------------


class LSPPositionRequest(BaseModel):
    file: str
    line: int
    col: int = 0


class LSPReferencesRequest(BaseModel):
    file: str
    line: int
    col: int = 0
    include_declaration: bool = True


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------


class NotifyFilesRequest(BaseModel):
    files: list[str]


# ------------------------------------------------------------------
# Generic text result
# ------------------------------------------------------------------


class TextResult(BaseModel):
    result: str


# ------------------------------------------------------------------
# Pagination
# ------------------------------------------------------------------


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
    has_more: bool


# ------------------------------------------------------------------
# Structured v2 responses
# ------------------------------------------------------------------


class FileMetricsItem(BaseModel):
    path: str
    line_count: int = 0
    symbol_count: int = 0
    public_symbols: int = 0
    fan_in: int = 0
    fan_out: int = 0
    density: float = 0.0
    composite: float = 0.0
    categories: list[str] = []


class FunctionMetricsItem(BaseModel):
    file_path: str
    name: str
    line_count: int = 0
    param_count: int = 0
    is_public: bool = True
    has_return_type: bool = False


class HotspotsResponse(BaseModel):
    file_hotspots: list[FileMetricsItem]
    function_hotspots: list[FunctionMetricsItem]
    orphan_files: list[FileMetricsItem]


class SymbolItem(BaseModel):
    kind: str = ""
    name: str = ""
    qualified_name: str = ""
    signature: str = ""
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0


class SymbolListResponse(BaseModel):
    path: str
    symbols: list[SymbolItem]


class SymbolSearchResponse(BaseModel):
    query: str
    definitions: list[SymbolItem]


class DependencyResponse(BaseModel):
    path: str
    imports: list[str]
    imported_by: list[str]


class DependencyGraphNode(BaseModel):
    id: str
    label: str
    type: str = "file"


class DependencyGraphEdge(BaseModel):
    source: str
    target: str
    type: str = "import"


class DependencyGraphResponse(BaseModel):
    nodes: list[DependencyGraphNode]
    edges: list[DependencyGraphEdge]


class ImpactLayer(BaseModel):
    depth: int
    files: list[str]


class ImpactAnalysisResponse(BaseModel):
    changed_files: list[str]
    impacted_files: list[str]
    total_impacted: int
    layers: list[ImpactLayer] = []


class ReferenceItem(BaseModel):
    ref_kind: str = ""
    file_path: str = ""
    line: int = 0


class CrossRefResponse(BaseModel):
    symbol: str
    definitions: list[SymbolItem]
    references: list[ReferenceItem]
    total_references: int


class CodeChunkItem(BaseModel):
    kind: str = ""
    name: str = ""
    parent: str | None = None
    signature: str | None = None
    start_line: int = 0
    end_line: int = 0


class FileAnalysisResponse(BaseModel):
    path: str
    language: str = ""
    line_count: int = 0
    imports: list[str] = []
    exports: list[str] = []
    chunks: list[CodeChunkItem] = []


class SearchResultItem(BaseModel):
    file_path: str = ""
    score: float = 0.0
    snippet: str = ""
    line: int | None = None


class SearchResultsResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total: int


class SecurityFinding(BaseModel):
    severity: str = ""
    category: str = ""
    file_path: str = ""
    line: int | None = None
    message: str = ""
    suggestion: str = ""


class SecurityScanResponse(BaseModel):
    mode: str
    path: str = ""
    findings: list[SecurityFinding]
    total_findings: int
    summary: dict = {}


class ConventionStats(BaseModel):
    total_functions: int = 0
    snake_names: int = 0
    camel_names: int = 0
    typed_return: int = 0
    typed_params: int = 0
    total_params: int = 0
    has_docstring_fn: int = 0
    has_docstring_cls: int = 0
    total_classes: int = 0
    async_count: int = 0
    from_imports: int = 0
    plain_imports: int = 0
    relative_imports: int = 0
    total_imports: int = 0
    decorator_counts: dict[str, int] = {}
    dataclass_count: int = 0
    abstract_count: int = 0
    base_classes: dict[str, int] = {}
    exception_classes: list[dict] = []
    private_functions: int = 0
    staticmethod_count: int = 0
    classmethod_count: int = 0
    property_count: int = 0
    all_exports_count: int = 0
    file_sizes: list[int] = []


class ConventionsResponse(BaseModel):
    sample_size: int
    path: str = ""
    stats: ConventionStats
    dir_stats: dict[str, ConventionStats] = {}


class CommunityItem(BaseModel):
    id: int
    files: list[str]
    size: int
    theme: str = ""
    internal_edges: int = 0
    external_edges: int = 0
    hub: str = ""
    hub_internal_degree: int = 0
    top_dirs: list[str] = []


class CommunityBridge(BaseModel):
    source_id: int
    target_id: int
    edge_count: int
    sample_files: list[str] = []


class CommunityResponse(BaseModel):
    method: str
    modularity: float
    communities: list[CommunityItem]
    bridges: list[CommunityBridge] = []


class GraphQueryHop(BaseModel):
    depth: int
    files: list[str]


class GraphQueryResponse(BaseModel):
    root: str
    direction: str
    depth: int
    hops: list[GraphQueryHop]
    total_reachable: int


class RelatedFileItem(BaseModel):
    path: str
    score: int
    relation_type: str


class FindRelatedResponse(BaseModel):
    file: str
    related: list[RelatedFileItem]


class LSPLocation(BaseModel):
    file: str
    line: int
    col: int


class LSPDefinitionResponse(BaseModel):
    location: LSPLocation | None = None
    error: str | None = None


class LSPReferencesResponse(BaseModel):
    locations: list[LSPLocation]
    total: int
    error: str | None = None


class LSPHoverResponse(BaseModel):
    content: str | None = None
    file: str = ""
    line: int = 0
    col: int = 0
    error: str | None = None


class LSPDiagnosticItem(BaseModel):
    severity: str = ""
    source: str | None = None
    code: str | None = None
    line: int = 0
    col: int = 0
    message: str = ""


class LSPDiagnosticsResponse(BaseModel):
    file: str
    diagnostics: list[LSPDiagnosticItem]
    total: int
    error: str | None = None


# ------------------------------------------------------------------
# File content API
# ------------------------------------------------------------------


class FileContentResponse(BaseModel):
    path: str
    content: str
    language: str = ""
    size_bytes: int = 0
    line_count: int = 0


class TreeEntry(BaseModel):
    name: str
    type: str  # "file" or "dir"
    size_bytes: int | None = None
    language: str | None = None


class FileTreeResponse(BaseModel):
    path: str
    entries: list[TreeEntry]


# ------------------------------------------------------------------
# Repository stats
# ------------------------------------------------------------------


class RepoStatsResponse(BaseModel):
    file_count: int = 0
    total_lines: int = 0
    symbol_count: int = 0
    dependency_count: int = 0
    languages: dict[str, int] = {}


# ------------------------------------------------------------------
# Learning v2 (structured)
# ------------------------------------------------------------------


class LearningItem(BaseModel):
    id: int
    type: str
    description: str
    details: str = ""
    scope: str = ""
    confidence: float = 0.7
    status: str = "active"
    helpful_count: int = 0
    unhelpful_count: int = 0


class LearningListResponse(BaseModel):
    learnings: list[LearningItem]
    total: int


class LearningRecallItem(BaseModel):
    id: int
    type: str
    description: str
    scope: str = ""
    confidence: float = 0.7
    relevance_score: float = 0.0


class LearningRecallResponse(BaseModel):
    query: str
    results: list[LearningRecallItem]
    total: int
