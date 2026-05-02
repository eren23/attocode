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
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from attocode.code_intel.api.auth import resolve_auth

if TYPE_CHECKING:
    from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notify"])


# --- Request/Response models ---


class FileChangedRequest(BaseModel):
    paths: list[str] = Field(..., description="List of changed file paths (relative to project root)")
    files: dict[str, str] = Field(default_factory=dict, description="Optional: path → base64-encoded file content (for remote servers that can't read client filesystem)")
    project: str = Field("", description="Project ID or path (local mode: ignored, uses default)")
    branch: str = Field("", description="Branch name (optional, auto-detected if empty)")
    idempotency_key: str = Field("", description="Optional idempotency key to prevent duplicate processing")
    if_match: int | None = Field(None, description="Expected branch version (optimistic concurrency)")


class FileChangedResponse(BaseModel):
    accepted: int = Field(..., description="Number of paths accepted for processing")
    message: str = "Accepted"
    version: int | None = Field(None, description="Current branch version after update")


class FlushRequest(BaseModel):
    project: str = Field("", description="Project ID to flush")
    branch: str = Field("", description="Branch to flush")


# --- Module-level debouncer singleton ---

_debouncer: FileChangeDebouncer | None = None
_pipeline_initialized = False

# --- Idempotency cache ---

_idempotency_cache: dict[str, float] = {}
_IDEMPOTENCY_TTL = 300  # 5 minutes


def _get_debouncer() -> FileChangeDebouncer:
    """Get or create the module-level debouncer singleton."""
    global _debouncer
    if _debouncer is None:
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        _debouncer = FileChangeDebouncer(handler=_handle_debounced_batch)
    return _debouncer


async def _handle_debounced_batch(project_id: str, branch: str, paths: list[str], files: dict[str, str] | None = None, request_if_match: int | None = None) -> None:
    """Handle a debounced batch of file changes.

    This runs after the debounce window closes. It processes files through
    the content-hash-gated incremental pipeline.
    """
    from attocode.code_intel.api import deps

    config = deps.get_config()

    if config.is_service_mode:
        await _handle_service_mode(project_id, branch, paths, files=files or {}, request_if_match=request_if_match)
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


async def _handle_service_mode(project_id: str, branch: str, paths: list[str], *, files: dict[str, str] | None = None, request_if_match: int | None = None) -> None:
    """Process file changes in service mode using the incremental pipeline.

    M2 note: In production, the caller (notify_file_changed route) already requires
    auth via resolve_auth. The project_id should be validated against org scoping
    in a future iteration when full multi-tenant isolation is implemented.
    """
    import base64

    from sqlalchemy import select

    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, Repository
    from attocode.code_intel.indexing.incremental import IncrementalPipeline
    from attocode.code_intel.pubsub import publish_event

    # Decode base64 file contents into bytes
    file_contents: dict[str, bytes] | None = None
    if files:
        file_contents = {}
        for path, b64_data in files.items():
            try:
                file_contents[path] = base64.b64decode(b64_data)
            except Exception:
                logger.warning("Failed to decode base64 content for %s", path)

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

                # If no default branch exists, this becomes the default
                is_first_branch = parent_branch is None

                branch_obj = Branch(
                    repo_id=repo.id,
                    name=branch,
                    parent_branch_id=parent_branch.id if parent_branch else None,
                    is_default=is_first_branch,
                )
                session.add(branch_obj)

                # Update repo.default_branch to match the actual data branch
                if is_first_branch:
                    repo.default_branch = branch

                await session.flush()

            # Advisory lock: prevent concurrent indexing of the same branch
            await IncrementalPipeline.acquire_branch_lock(session, branch_obj.id)

            # If-Match optimistic concurrency check
            if request_if_match is not None:
                from attocode.code_intel.storage.branch_overlay import BranchOverlay

                overlay = BranchOverlay(session)
                try:
                    await overlay.check_version(branch_obj.id, request_if_match)
                except ValueError:
                    current_version = await overlay.get_version(branch_obj.id)
                    raise Exception(f"VERSION_MISMATCH:{current_version}")

            # Run incremental pipeline
            pipeline = IncrementalPipeline(session)
            base_dir = repo.clone_path or repo.local_path
            stats = await pipeline.process_file_changes(
                branch_id=branch_obj.id,
                paths=paths,
                base_dir=base_dir,
                file_contents=file_contents,
            )

            # Transition repo to "indexed" on first successful incremental update
            if stats["processed"] > 0:
                repo.index_status = "indexed"
                repo.last_indexed_at = datetime.now(timezone.utc)

            await session.commit()

            # Reliably trigger embedding generation after batch completes
            if stats["processed"] > 0:
                from attocode.code_intel.workers.job_utils import enqueue_embedding_job
                await enqueue_embedding_job(project_id, branch)

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

        except Exception as exc:
            error_msg = str(exc)
            if error_msg.startswith("VERSION_MISMATCH:"):
                current_version = int(error_msg.split(":")[1])
                logger.info("Version mismatch for %s/%s: current=%d", project_id, branch, current_version)
                await session.rollback()
                return  # Caller should check version
            logger.exception("Error in service mode notify handler")
            await session.rollback()


async def _call_sync(func, *args):
    """Call a sync function from async context."""
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

    # Idempotency check
    if request.idempotency_key:
        import time

        now = time.monotonic()
        # Clean expired entries
        expired = [k for k, t in _idempotency_cache.items() if now - t > _IDEMPOTENCY_TTL]
        for k in expired:
            _idempotency_cache.pop(k, None)
        # Check for duplicate
        if request.idempotency_key in _idempotency_cache:
            return FileChangedResponse(accepted=0, message="Duplicate (idempotency key already processed)")
        _idempotency_cache[request.idempotency_key] = now

    from attocode.code_intel.api import deps

    config = deps.get_config()

    # Resolve project ID
    project_id = request.project or deps.get_default_project_id()

    # Resolve branch (auto-detect from git if not provided)
    branch = request.branch
    if not branch:
        branch = await _detect_current_branch(config.project_dir) if config.project_dir else "main"

    debouncer = _get_debouncer()
    await debouncer.notify(project_id, branch, request.paths, files=request.files)

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
    branch = request.branch

    debouncer = _get_debouncer()
    await debouncer.flush(project_id, branch)

    return FileChangedResponse(accepted=0, message="Flushed")


class CommitPushRequest(BaseModel):
    commits: list[dict] = Field(..., description="List of commit dicts: {oid, message, author_name, author_email, timestamp, parent_oids}")
    project: str = Field(..., description="Repository ID")
    branch: str = Field("main", description="Branch name")


class CommitPushResponse(BaseModel):
    stored: int = 0
    skipped: int = 0


@router.post(
    "/api/v1/notify/commits",
    response_model=CommitPushResponse,
    status_code=200,
)
async def push_commits(
    request: CommitPushRequest,
    auth: dict = Depends(resolve_auth),
) -> CommitPushResponse:
    """Push commit metadata for DB-backed commit history (remote repos)."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Commit, Repository

    if not request.commits:
        return CommitPushResponse()

    stored = 0
    skipped = 0

    async for session in get_session():
        try:
            repo_result = await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(request.project))
            )
            repo = repo_result.scalar_one_or_none()
            if repo is None:
                logger.warning("push_commits: repository %s not found", request.project)
                return CommitPushResponse()

            for c in request.commits:
                try:
                    values = {
                        "repo_id": repo.id,
                        "oid": c["oid"],
                        "message": c.get("message", ""),
                        "author_name": c.get("author_name", ""),
                        "author_email": c.get("author_email", ""),
                        "timestamp": int(c.get("timestamp", 0)),
                        "parent_oids": c.get("parent_oids", []),
                        "branch_name": request.branch,
                    }
                    if c.get("changed_files"):
                        values["changed_files"] = c["changed_files"]
                    stmt = pg_insert(Commit.__table__).values(
                        **values,
                    ).on_conflict_do_nothing(
                        constraint="uq_commits_repo_oid",
                    )
                    result = await session.execute(stmt)
                    if result.rowcount:
                        stored += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.warning("Error storing commit %s: %s", c.get("oid", "?"), e)
                    skipped += 1

            await session.commit()
        except Exception:
            logger.exception("Error in push_commits handler")
            await session.rollback()

    return CommitPushResponse(stored=stored, skipped=skipped)


class BulkSyncRequest(BaseModel):
    files: dict[str, str] = Field(..., description="Map of path → base64-encoded content (up to 500 files)")
    project: str = Field(..., description="Repository ID")
    branch: str = Field("main", description="Branch name")


class BulkSyncResponse(BaseModel):
    processed: int = 0
    skipped_unchanged: int = 0


@router.post(
    "/api/v1/notify/bulk-sync",
    response_model=BulkSyncResponse,
    status_code=200,
)
async def bulk_sync(
    request: BulkSyncRequest,
    auth: dict = Depends(resolve_auth),
) -> BulkSyncResponse:
    """Bulk sync files — bypasses debouncer for fast initial sync.

    Accepts up to 500 files per request. Direct pipeline call in single transaction.
    """
    import base64

    from sqlalchemy import select

    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, Repository
    from attocode.code_intel.indexing.incremental import IncrementalPipeline

    if not request.files:
        return BulkSyncResponse()

    if len(request.files) > 500:
        raise HTTPException(status_code=422, detail="Maximum 500 files per bulk-sync request")

    async for session in get_session():
        try:
            repo_result = await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(request.project))
            )
            repo = repo_result.scalar_one_or_none()
            if repo is None:
                raise HTTPException(status_code=404, detail="Repository not found")

            branch_result = await session.execute(
                select(Branch).where(
                    Branch.repo_id == repo.id,
                    Branch.name == request.branch,
                )
            )
            branch_obj = branch_result.scalar_one_or_none()
            if branch_obj is None:
                # Auto-create branch
                parent_result = await session.execute(
                    select(Branch).where(
                        Branch.repo_id == repo.id,
                        Branch.is_default == True,  # noqa: E712
                    )
                )
                parent_branch = parent_result.scalar_one_or_none()
                is_first = parent_branch is None
                branch_obj = Branch(
                    repo_id=repo.id,
                    name=request.branch,
                    parent_branch_id=parent_branch.id if parent_branch else None,
                    is_default=is_first,
                )
                session.add(branch_obj)
                if is_first:
                    repo.default_branch = request.branch
                await session.flush()

            # Advisory lock
            await IncrementalPipeline.acquire_branch_lock(session, branch_obj.id)

            # Decode file contents
            file_contents: dict[str, bytes] = {}
            for path, b64_data in request.files.items():
                try:
                    file_contents[path] = base64.b64decode(b64_data)
                except Exception:
                    logger.warning("Failed to decode base64 content for %s", path)

            # Run pipeline directly (no debounce)
            pipeline = IncrementalPipeline(session)
            base_dir = repo.clone_path or repo.local_path
            stats = await pipeline.process_file_changes(
                branch_id=branch_obj.id,
                paths=list(file_contents.keys()),
                base_dir=base_dir,
                file_contents=file_contents,
            )

            if stats["processed"] > 0:
                repo.index_status = "indexed"
                repo.last_indexed_at = datetime.now(timezone.utc)

            await session.commit()

            # Trigger embeddings
            if stats["processed"] > 0:
                from attocode.code_intel.workers.job_utils import enqueue_embedding_job
                await enqueue_embedding_job(request.project, request.branch)

            return BulkSyncResponse(
                processed=stats["processed"],
                skipped_unchanged=stats["skipped_unchanged"],
            )

        except HTTPException:
            raise
        except Exception:
            logger.exception("Error in bulk sync handler")
            await session.rollback()
            raise HTTPException(status_code=500, detail="Internal error during bulk sync")

    raise HTTPException(status_code=503, detail="No database session available")


class BlamePushRequest(BaseModel):
    hunks: list[dict] = Field(..., description="List of blame hunk dicts")
    project: str = Field(..., description="Repository ID")
    branch: str = Field("main", description="Branch name")
    path: str = Field(..., description="File path for blame data")


class BlamePushResponse(BaseModel):
    stored: int = 0


@router.post(
    "/api/v1/notify/blame",
    response_model=BlamePushResponse,
    status_code=200,
)
async def push_blame(
    request: BlamePushRequest,
    auth: dict = Depends(resolve_auth),
) -> BlamePushResponse:
    """Push blame data for DB-backed blame (remote repos)."""
    from sqlalchemy import select

    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import BlameHunk, Repository

    if not request.hunks:
        return BlamePushResponse()

    stored = 0

    async for session in get_session():
        try:
            repo_result = await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(request.project))
            )
            repo = repo_result.scalar_one_or_none()
            if repo is None:
                return BlamePushResponse()

            # Delete existing blame for this file/branch (replace)
            from sqlalchemy import delete

            await session.execute(
                delete(BlameHunk).where(
                    BlameHunk.repo_id == repo.id,
                    BlameHunk.path == request.path,
                    BlameHunk.branch_name == request.branch,
                )
            )

            for h in request.hunks:
                hunk = BlameHunk(
                    repo_id=repo.id,
                    path=request.path,
                    branch_name=request.branch,
                    commit_oid=h.get("commit_oid", ""),
                    author_name=h.get("author_name", ""),
                    author_email=h.get("author_email", ""),
                    timestamp=int(h.get("timestamp", 0)),
                    start_line=int(h.get("start_line", 0)),
                    end_line=int(h.get("end_line", 0)),
                )
                session.add(hunk)
                stored += 1

            await session.commit()
        except Exception:
            logger.exception("Error in push_blame handler")
            await session.rollback()

    return BlamePushResponse(stored=stored)


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
