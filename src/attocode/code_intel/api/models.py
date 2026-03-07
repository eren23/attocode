"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


# ------------------------------------------------------------------
# Analysis
# ------------------------------------------------------------------


class DependencyGraphRequest(BaseModel):
    start_file: str
    depth: int = 2


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
