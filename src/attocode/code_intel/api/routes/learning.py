"""Learning/memory endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    LearningFeedbackRequest,
    LearningItem,
    LearningListResponse,
    LearningRecallItem,
    LearningRecallResponse,
    RecordLearningRequest,
    TextResult,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["learning"],
    dependencies=[Depends(verify_api_key)],
)

router_v2 = APIRouter(
    prefix="/api/v2",
    tags=["learning-v2"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/projects/{project_id}/learnings", response_model=TextResult)
async def record_learning(project_id: str, req: RecordLearningRequest) -> TextResult:
    """Record a new learning."""
    svc = await get_service_or_404(project_id)
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
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.recall(query=query, scope=scope, max_results=max_results))


@router.post("/projects/{project_id}/learnings/{learning_id}/feedback", response_model=TextResult)
async def learning_feedback(project_id: str, learning_id: int, req: LearningFeedbackRequest) -> TextResult:
    """Mark a learning as helpful/unhelpful."""
    svc = await get_service_or_404(project_id)
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
    svc = await get_service_or_404(project_id)
    return TextResult(result=svc.list_learnings(status=status, type=type, scope=scope))


# ------------------------------------------------------------------
# v2 structured endpoints
# ------------------------------------------------------------------


def _store_records_to_items(records: list[dict]) -> list[LearningItem]:
    """Convert raw store records to LearningItem models."""
    return [
        LearningItem(
            id=r["id"],
            type=r["type"],
            description=r["description"],
            details=r.get("details", ""),
            scope=r.get("scope", ""),
            confidence=r.get("confidence", 0.7),
            status=r.get("status", "active"),
            helpful_count=r.get("helpful_count", 0),
            unhelpful_count=r.get("unhelpful_count", 0),
        )
        for r in records
    ]


def _store_records_to_recall_items(records: list[dict]) -> list[LearningRecallItem]:
    """Convert raw store recall records to LearningRecallItem models."""
    return [
        LearningRecallItem(
            id=r["id"],
            type=r["type"],
            description=r["description"],
            scope=r.get("scope", ""),
            confidence=r.get("confidence", 0.7),
            relevance_score=r.get("relevance_score", 0.0),
        )
        for r in records
    ]


@router_v2.get("/projects/{project_id}/learnings", response_model=LearningListResponse)
async def list_learnings_v2(
    project_id: str,
    status: str = "active",
    type: str = "",  # noqa: A002
    scope: str = "",
) -> LearningListResponse:
    """List all learnings (structured)."""
    from fastapi import HTTPException

    try:
        svc = await get_service_or_404(project_id)
        store = svc._get_memory_store()
        records = store.list_all(status=status, type=type or None)
        if scope:
            records = [r for r in records if r["scope"].startswith(scope) or r["scope"] == ""]
        items = _store_records_to_items(records)
        return LearningListResponse(learnings=items, total=len(items))
    except HTTPException:
        return LearningListResponse(learnings=[], total=0)


@router_v2.get("/projects/{project_id}/learnings/recall", response_model=LearningRecallResponse)
async def recall_v2(
    project_id: str,
    query: str = Query(...),
    scope: str = "",
    max_results: int = 10,
) -> LearningRecallResponse:
    """Recall relevant learnings (structured)."""
    from fastapi import HTTPException

    try:
        svc = await get_service_or_404(project_id)
        store = svc._get_memory_store()
        records = store.recall(query=query, scope=scope, max_results=max_results)
        items = _store_records_to_recall_items(records)
        return LearningRecallResponse(query=query, results=items, total=len(items))
    except HTTPException:
        return LearningRecallResponse(query=query, results=[], total=0)
