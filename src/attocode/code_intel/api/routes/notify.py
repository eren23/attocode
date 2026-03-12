"""File change notification endpoint — hook integration for incremental indexing.

This endpoint receives file change notifications from Claude Code post-tooluse
hooks (or any other client) and feeds them into the debounced incremental
indexing pipeline.

Protocol:
    POST /api/v1/notify/file-changed
    Body: {"paths": ["src/a.py"], "project": "...", "branch": "feat/x"}
    Response: 202 Accepted (processing is async)

Hook integration example (.claude/hooks.toml):
    [hooks.post_tool_use]
    command = "curl -s -X POST http://localhost:8080/api/v1/notify/file-changed ..."
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from attocode.code_intel.api.auth import resolve_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notify"])


# --- Request/Response models ---


class FileChangedRequest(BaseModel):
    paths: list[str] = Field(..., description="List of changed file paths (relative to project root)")
    project: str = Field("", description="Project ID or path (local mode: ignored, uses default)")
    branch: str = Field("", description="Branch name (optional, auto-detected if empty)")


class FileChangedResponse(BaseModel):
    accepted: int = Field(..., description="Number of paths accepted for processing")
    message: str = "Accepted"


class FlushRequest(BaseModel):
    project: str = Field("", description="Project ID to flush")
    branch: str = Field("", description="Branch to flush")


# --- Module-level debouncer singleton ---

_debouncer = None
_pipeline_initialized = False


def _get_debouncer():
    """Get or create the module-level debouncer singleton."""
    global _debouncer
    if _debouncer is None:
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        _debouncer = FileChangeDebouncer(handler=_handle_debounced_batch)
    return _debouncer


async def _handle_debounced_batch(project_id: str, branch: str, paths: list[str]) -> None:
    """Handle a debounced batch of file changes.

    This runs after the debounce window closes. It processes files through
    the content-hash-gated incremental pipeline.
    """
    from attocode.code_intel.api import deps

    config = deps.get_config()

    if config.is_service_mode:
        await _handle_service_mode(project_id, branch, paths)
    else:
        await _handle_local_mode(project_id, paths)


async def _handle_local_mode(project_id: str, paths: list[str]) -> None:
    """Process file changes in local mode using existing CodeIntelService."""
    from attocode.code_intel.api import deps

    try:
        svc = deps.get_service(project_id)
    except ValueError:
        logger.warning("Notify: project %s not found", project_id)
        return

    # Use existing notify_file_changed for each path
    for path in paths:
        try:
            await _call_sync(svc.notify_file_changed, path)
        except Exception as e:
            logger.warning("Error notifying file change %s: %s", path, e)


async def _handle_service_mode(project_id: str, branch: str, paths: list[str]) -> None:
    """Process file changes in service mode using the incremental pipeline.

    M2 note: In production, the caller (notify_file_changed route) already requires
    auth via resolve_auth. The project_id should be validated against org scoping
    in a future iteration when full multi-tenant isolation is implemented.
    """
    from sqlalchemy import select

    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, Repository
    from attocode.code_intel.indexing.incremental import IncrementalPipeline
    from attocode.code_intel.pubsub import publish_event

    async for session in get_session():
        try:
            # Resolve repository — validate it exists
            repo_result = await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(project_id))
            )
            repo = repo_result.scalar_one_or_none()
            if repo is None:
                logger.warning("Notify: repository %s not found", project_id)
                return

            branch_result = await session.execute(
                select(Branch).where(
                    Branch.repo_id == repo.id,
                    Branch.name == branch,
                )
            )
            branch_obj = branch_result.scalar_one_or_none()
            if branch_obj is None:
                # Auto-create branch entry, parented to default
                parent_result = await session.execute(
                    select(Branch).where(
                        Branch.repo_id == repo.id,
                        Branch.is_default == True,  # noqa: E712
                    )
                )
                parent_branch = parent_result.scalar_one_or_none()
                branch_obj = Branch(
                    repo_id=repo.id,
                    name=branch,
                    parent_branch_id=parent_branch.id if parent_branch else None,
                )
                session.add(branch_obj)
                await session.flush()

            # Run incremental pipeline
            pipeline = IncrementalPipeline(session)
            base_dir = repo.clone_path or repo.local_path
            stats = await pipeline.process_file_changes(
                branch_id=branch_obj.id,
                paths=paths,
                base_dir=base_dir,
            )

            await session.commit()

            # Publish event
            await publish_event(
                str(repo.id),
                "index.updated",
                {"paths": paths, "branch": branch, "stats": stats},
            )

            # Log audit event
            from attocode.code_intel.audit import log_event

            await log_event(session, repo.org_id, "commit.notified", repo_id=repo.id, detail={"paths_count": len(paths), "branch": branch})

            logger.info(
                "Incremental update for %s/%s: %d processed, %d unchanged",
                project_id, branch, stats["processed"], stats["skipped_unchanged"],
            )

        except Exception:
            logger.exception("Error in service mode notify handler")
            await session.rollback()


async def _call_sync(func, *args):
    """Call a sync function from async context.

    M7 fix: Use get_running_loop() instead of deprecated get_event_loop().
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


# --- Routes ---


@router.post(
    "/api/v1/notify/file-changed",
    response_model=FileChangedResponse,
    status_code=202,
)
async def notify_file_changed(
    request: FileChangedRequest,
    auth: dict = Depends(resolve_auth),
) -> FileChangedResponse:
    """Notify that files have changed. Returns 202 immediately.

    The actual processing happens asynchronously after debouncing.
    Multiple rapid notifications are batched into a single update.
    """
    if not request.paths:
        raise HTTPException(status_code=422, detail="No paths provided")

    from attocode.code_intel.api import deps

    config = deps.get_config()

    # Resolve project ID
    project_id = request.project or deps.get_default_project_id()

    # Resolve branch (auto-detect from git if not provided)
    branch = request.branch
    if not branch:
        branch = await _detect_current_branch(config.project_dir) if config.project_dir else "main"

    debouncer = _get_debouncer()
    await debouncer.notify(project_id, branch, request.paths)

    return FileChangedResponse(accepted=len(request.paths))


@router.post(
    "/api/v1/notify/flush",
    response_model=FileChangedResponse,
    status_code=200,
)
async def flush_pending(
    request: FlushRequest,
    auth: dict = Depends(resolve_auth),
) -> FileChangedResponse:
    """Force-flush any pending debounced notifications.

    Useful for testing or when you need immediate consistency.
    """
    from attocode.code_intel.api import deps

    project_id = request.project or deps.get_default_project_id()
    branch = request.branch or "main"

    debouncer = _get_debouncer()
    await debouncer.flush(project_id, branch)

    return FileChangedResponse(accepted=0, message="Flushed")


def _detect_current_branch(project_dir: str) -> str:
    """Detect the current git branch from the project directory."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "main"
