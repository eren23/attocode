"""Garbage-collection endpoints for code-intel storage.

Phase 3a wires the existing :func:`ContentStore.gc_unreferenced` and
:func:`EmbeddingStore.gc_orphaned` functions up to HTTP. Those helpers
have existed since Phase 1 but were never exposed — Phase 2a described
this as gap G9 ("GC is code without a UI"). Now there's a UI.

The semantics match the local-mode ``gc_preview`` / ``gc_run`` pair:

- ``dry_run=true`` (the default) reports what would be removed without
  mutating anything.
- ``dry_run=false`` actually applies the GC. Requires the admin role.

Phase 3b will add retention policies that schedule GC automatically.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.api.routes.orgs import _require_membership
from attocode.code_intel.db.models import Repository
from attocode.code_intel.storage.content_store import ContentStore
from attocode.code_intel.storage.embedding_store import EmbeddingStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/orgs", tags=["gc"])


# --- Request / response models ---


class GCRunRequest(BaseModel):
    """Body for the ``POST .../gc`` endpoint.

    ``types`` selects which stores to GC. Empty list means "all".
    ``min_age_minutes`` gates how fresh an entity can be before it's
    eligible — defaults match the underlying ``gc_unreferenced`` +
    ``gc_orphaned`` defaults (5min for content, 60min for embeddings).
    """

    dry_run: bool = True
    types: list[str] = []
    min_age_minutes: int = 5
    embedding_min_age_minutes: int = 60


class GCTypeResult(BaseModel):
    kind: str
    removed: int


class GCRunResponse(BaseModel):
    repo_id: str
    dry_run: bool
    results: list[GCTypeResult]
    removed_total: int


class GCStatsResponse(BaseModel):
    repo_id: str
    types: dict[str, int]


# --- Helpers ---


async def _load_repo(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    session: AsyncSession,
) -> Repository:
    result = await session.execute(
        select(Repository).where(
            Repository.id == repo_id, Repository.org_id == org_id,
        )
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _parse_types(types: list[str]) -> set[str]:
    """Normalize the ``types`` input, expanding aliases. Empty input
    means every known type."""
    allowed = {"content", "embedding"}
    if not types:
        return set(allowed)
    out: set[str] = set()
    for t in types:
        key = t.strip().lower()
        if key not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"unknown gc type {key!r}; allowed: {sorted(allowed)}",
            )
        out.add(key)
    return out


# --- Endpoints ---


@router.post(
    "/{org_id}/repos/{repo_id}/gc",
    response_model=GCRunResponse,
)
async def gc_run(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    req: GCRunRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> GCRunResponse:
    """Run garbage collection on the repo's code-intel storage.

    ``dry_run=true`` is member-readable. Applying GC
    (``dry_run=false``) requires the admin role — destructive ops
    always do.
    """
    min_role = "member" if req.dry_run else "admin"
    await _require_membership(org_id, auth, session, min_role=min_role)
    await _load_repo(org_id, repo_id, session)

    selected = _parse_types(req.types)
    content_store = ContentStore(session)
    embedding_store = EmbeddingStore(session)

    results: list[GCTypeResult] = []

    if "content" in selected:
        if req.dry_run:
            removed = await _preview_content_gc(
                session,
                min_age_minutes=req.min_age_minutes,
                repo_id=repo_id,
            )
        else:
            removed = await content_store.gc_unreferenced(
                min_age_minutes=req.min_age_minutes,
                repo_id=repo_id,
            )
        results.append(GCTypeResult(kind="content", removed=removed))

    if "embedding" in selected:
        if req.dry_run:
            removed = await _preview_embedding_gc(
                session,
                min_age_minutes=req.embedding_min_age_minutes,
                repo_id=repo_id,
            )
        else:
            removed = await embedding_store.gc_orphaned(
                min_age_minutes=req.embedding_min_age_minutes,
                repo_id=repo_id,
            )
        results.append(GCTypeResult(kind="embedding", removed=removed))

    if not req.dry_run:
        from attocode.code_intel.audit import log_event

        await log_event(
            session,
            org_id,
            "gc.run",
            repo_id=repo_id,
            user_id=auth.user_id,
            detail={
                "types": sorted(selected),
                "removed": {r.kind: r.removed for r in results},
            },
        )
        await session.commit()
    else:
        # Roll back any accidental writes the preview may have caused —
        # it shouldn't, but defensive.
        await session.rollback()

    return GCRunResponse(
        repo_id=str(repo_id),
        dry_run=req.dry_run,
        results=results,
        removed_total=sum(r.removed for r in results),
    )


@router.get(
    "/{org_id}/repos/{repo_id}/gc/stats",
    response_model=GCStatsResponse,
)
async def gc_stats(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> GCStatsResponse:
    """Return per-type counts of entities eligible for GC.

    This is a non-destructive ``SELECT COUNT(...)`` that gives you the
    same numbers ``gc_run(dry_run=True)`` would produce, without
    needing the body payload.
    """
    await _require_membership(org_id, auth, session)
    await _load_repo(org_id, repo_id, session)

    content_count = await _preview_content_gc(
        session, min_age_minutes=5, repo_id=repo_id,
    )
    embedding_count = await _preview_embedding_gc(
        session, min_age_minutes=60, repo_id=repo_id,
    )

    return GCStatsResponse(
        repo_id=str(repo_id),
        types={
            "content": content_count,
            "embedding": embedding_count,
        },
    )


async def _preview_content_gc(
    session: AsyncSession,
    *,
    min_age_minutes: int,
    repo_id: uuid.UUID | None = None,
) -> int:
    """Count how many ``file_contents`` rows are GC-eligible.

    Mirrors :func:`ContentStore.gc_unreferenced` but with a
    ``SELECT COUNT(*)`` that does not mutate the session. When
    ``repo_id`` is set, the count is the same repo-scoped number the
    apply path would delete.
    """
    from sqlalchemy import text

    if repo_id is None:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*) FROM file_contents
                WHERE created_at < NOW() - make_interval(mins => :age)
                  AND sha256 NOT IN (
                    SELECT DISTINCT content_sha FROM branch_files WHERE content_sha IS NOT NULL
                    UNION
                    SELECT DISTINCT content_sha FROM symbols
                    UNION
                    SELECT DISTINCT source_sha FROM dependencies
                    UNION
                    SELECT DISTINCT target_sha FROM dependencies
                    UNION
                    SELECT DISTINCT content_sha FROM embeddings
                  )
                """
            ).bindparams(age=min_age_minutes)
        )
    else:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*) FROM file_contents
                WHERE created_at < NOW() - make_interval(mins => :age)
                  AND sha256 IN (
                    SELECT DISTINCT bf.content_sha
                    FROM branch_files bf
                    JOIN branches b ON b.id = bf.branch_id
                    WHERE b.repo_id = :repo_id AND bf.content_sha IS NOT NULL
                  )
                  AND sha256 NOT IN (
                    SELECT DISTINCT bf.content_sha
                    FROM branch_files bf
                    WHERE bf.content_sha IS NOT NULL
                    UNION
                    SELECT DISTINCT content_sha FROM symbols
                    UNION
                    SELECT DISTINCT source_sha FROM dependencies
                    UNION
                    SELECT DISTINCT target_sha FROM dependencies
                    UNION
                    SELECT DISTINCT content_sha FROM embeddings
                  )
                """
            ).bindparams(age=min_age_minutes, repo_id=str(repo_id))
        )
    return int(result.scalar_one() or 0)


async def _preview_embedding_gc(
    session: AsyncSession,
    *,
    min_age_minutes: int,
    repo_id: uuid.UUID | None = None,
) -> int:
    """Count embeddings that would be removed by
    :func:`EmbeddingStore.gc_orphaned`."""
    from sqlalchemy import text

    if repo_id is None:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*) FROM embeddings
                WHERE created_at < NOW() - make_interval(mins => :age)
                  AND content_sha NOT IN (
                    SELECT DISTINCT content_sha FROM branch_files WHERE content_sha IS NOT NULL
                  )
                """
            ).bindparams(age=min_age_minutes)
        )
    else:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*) FROM embeddings
                WHERE created_at < NOW() - make_interval(mins => :age)
                  AND content_sha IN (
                    SELECT DISTINCT bf.content_sha
                    FROM branch_files bf
                    JOIN branches b ON b.id = bf.branch_id
                    WHERE b.repo_id = :repo_id AND bf.content_sha IS NOT NULL
                  )
                  AND content_sha NOT IN (
                    SELECT DISTINCT content_sha FROM branch_files WHERE content_sha IS NOT NULL
                  )
                """
            ).bindparams(age=min_age_minutes, repo_id=str(repo_id))
        )
    return int(result.scalar_one() or 0)
