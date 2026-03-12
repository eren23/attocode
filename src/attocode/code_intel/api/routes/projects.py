"""Project management endpoints."""

from __future__ import annotations

import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException

from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.api.deps import (
    get_config,
    get_service_or_404,
    list_projects,
    register_project,
)
from fastapi import Query as QueryParam

from attocode.code_intel.api.models import (
    ProjectInfo,
    ProjectListResponse,
    ProjectRegister,
    TextResult,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"], dependencies=[Depends(verify_api_key)])

# Serializes reindex operations so concurrent requests don't corrupt state
_reindex_lock = asyncio.Lock()

# System directories that should never be registered as projects
_BLOCKED_PREFIXES = ("/etc", "/var", "/usr", "/sys", "/proc", "/dev")


@router.post("", response_model=ProjectInfo)
async def create_project(req: ProjectRegister) -> ProjectInfo:
    """Register a project (local path)."""
    abs_path = os.path.abspath(req.path)
    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=400, detail=f"Directory not found: {abs_path}")

    # Block system directories when API key auth is active
    config = get_config()
    if config.api_key:
        for prefix in _BLOCKED_PREFIXES:
            if abs_path == prefix or abs_path.startswith(prefix + "/"):
                raise HTTPException(status_code=400, detail=f"Cannot register system directory: {abs_path}")

    # Idempotent: return existing project if same path already registered
    for pid, svc in list_projects().items():
        if svc.project_dir == abs_path:
            return ProjectInfo(
                id=pid,
                name=req.name or os.path.basename(abs_path),
                path=abs_path,
                status="ready",
            )

    project_id = str(uuid.uuid4())[:8]
    name = req.name or os.path.basename(abs_path)
    register_project(project_id, abs_path, name)

    return ProjectInfo(
        id=project_id,
        name=name,
        path=abs_path,
        status="ready",
    )


@router.get("", response_model=ProjectListResponse)
async def get_projects(
    limit: int = QueryParam(20, ge=1, le=100),
    offset: int = QueryParam(0, ge=0),
) -> ProjectListResponse:
    """List all registered projects."""
    projects = list_projects()
    all_items = []
    for pid, svc in projects.items():
        all_items.append(ProjectInfo(
            id=pid,
            name=os.path.basename(svc.project_dir),
            path=svc.project_dir,
            status="ready",
        ))
    total = len(all_items)
    page = all_items[offset:offset + limit]
    return ProjectListResponse(
        projects=page, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.get("/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str) -> ProjectInfo:
    """Get project details."""
    svc = get_service_or_404(project_id)
    return ProjectInfo(
        id=project_id,
        name=os.path.basename(svc.project_dir),
        path=svc.project_dir,
        status="ready",
    )


@router.post("/{project_id}/reindex", response_model=TextResult)
async def reindex_project(project_id: str) -> TextResult:
    """Trigger a full reindex of the project."""
    svc = get_service_or_404(project_id)
    async with _reindex_lock:
        svc._ast_service = None
        svc._context_mgr = None
        svc._get_ast_service()
        svc._get_context_mgr()
    return TextResult(result="Reindex complete")
