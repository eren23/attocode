"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe — checks that at least one project is registered."""
    from attocode.code_intel.api.deps import list_projects

    projects = list_projects()
    if not projects:
        return {"status": "not_ready", "reason": "no projects registered"}
    return {"status": "ready", "projects": len(projects)}
