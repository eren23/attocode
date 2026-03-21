"""Health check and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from starlette.responses import PlainTextResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe — checks that at least one project or repo is registered."""
    from attocode.code_intel.api.deps import get_config, list_projects

    # Check v1 local projects
    projects = list_projects()
    if projects:
        return {"status": "ready", "projects": len(projects)}

    # In service mode, also check DB repos
    config = get_config()
    if config.is_service_mode:
        from sqlalchemy import func, select

        from attocode.code_intel.db.engine import get_session
        from attocode.code_intel.db.models import Repository

        async for session in get_session():
            result = await session.execute(select(func.count()).select_from(Repository))
            repo_count = result.scalar() or 0
            if repo_count > 0:
                return {"status": "ready", "repos": repo_count}

    return {"status": "not_ready", "reason": "no projects registered"}


@router.get("/api/v1/metrics")
async def metrics(
    format: str = Query("json", description="Response format: 'json' or 'prometheus'"),
):
    """Return aggregated query metrics.

    Supports JSON (default) and Prometheus text exposition format.
    Unauthenticated — intended for monitoring infrastructure.
    """
    from attocode.code_intel.api.middleware import metrics_collector

    if format == "prometheus":
        text = metrics_collector.get_metrics(fmt="prometheus")
        return PlainTextResponse(
            content=text,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return metrics_collector.get_metrics(fmt="json")
