"""Learning/memory endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    LearningFeedbackRequest,
    RecordLearningRequest,
    TextResult,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["learning"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/projects/{project_id}/learnings", response_model=TextResult)
async def record_learning(project_id: str, req: RecordLearningRequest) -> TextResult:
    """Record a new learning."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.record_learning(
        type=req.type, description=req.description,
        details=req.details, scope=req.scope, confidence=req.confidence,
    ))


@router.get("/projects/{project_id}/learnings/recall", response_model=TextResult)
async def recall(
    project_id: str,
    query: str = Query(...),
    branch: BranchParam = "",
    scope: str = "",
    max_results: int = 10,
) -> TextResult:
    """Recall relevant learnings."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.recall(query=query, scope=scope, max_results=max_results))


@router.post("/projects/{project_id}/learnings/{learning_id}/feedback", response_model=TextResult)
async def learning_feedback(project_id: str, learning_id: int, req: LearningFeedbackRequest) -> TextResult:
    """Mark a learning as helpful/unhelpful."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.learning_feedback(learning_id=learning_id, helpful=req.helpful))


@router.get("/projects/{project_id}/learnings", response_model=TextResult)
async def list_learnings(
    project_id: str,
    branch: BranchParam = "",
    status: str = "active",
    type: str = "",  # noqa: A002
    scope: str = "",
) -> TextResult:
    """List all learnings."""
    svc = get_service_or_404(project_id)
    return TextResult(result=svc.list_learnings(status=status, type=type, scope=scope))
