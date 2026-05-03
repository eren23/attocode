"""Repository snapshot endpoints — server-side point-in-time manifests.

Phase 3a ships CRUD + create over the ``repo_snapshots`` +
``repo_snapshot_components`` tables. A snapshot is a content-addressed
record of everything it takes to reproduce a repo's code-intel state
*right now*: the branch manifest, the symbol + dependency + embedding
coverage, and aggregate stats.

The manifest hash is the SHA-256 of a canonical JSON document shaped
like an OCI v1.1 image manifest — so Phase 3b's OCI adapter can push it
to a registry without changing the database schema.

Limitations of Phase 3a:

- The snapshot describes but does NOT materialize a downloadable tarball
  of the underlying content/symbol/embedding blobs. That's Phase 3b.
- Restore is also Phase 3b. Right now this endpoint set gives you
  create / list / get / delete — the "durable record of state" half.

"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.api.routes.orgs import _require_membership
from attocode.code_intel.api.utils import get_repo_by_org as _load_repo
from attocode.code_intel.db.models import (
    Branch,
    Dependency,
    Embedding,
    FileContent,
    Repository,
    RepoSnapshot,
    RepoSnapshotComponent,
    Symbol,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/orgs", tags=["snapshots"])


# Snapshot / component schema + media type strings match Phase 2a's
# ``snapshot_tools`` local format so a Phase 3b adapter can merge them.
SNAPSHOT_SCHEMA = "atto.snapshot.v1"
_MEDIA_CONTENT = "application/vnd.attocode.content-manifest.v1+json"
_MEDIA_SYMBOLS = "application/vnd.attocode.symbols-manifest.v1+json"
_MEDIA_DEPS = "application/vnd.attocode.deps-manifest.v1+json"
_MEDIA_EMBED = "application/vnd.attocode.embeddings-manifest.v1+json"


# --- Request / response models ---


class SnapshotCreateRequest(BaseModel):
    name: str
    description: str = ""
    branch: str = ""            # empty means "use repo default_branch"
    commit_oid: str = ""        # optional explicit commit pin
    dry_run: bool = False


class SnapshotComponentModel(BaseModel):
    name: str
    media_type: str
    digest: str
    size_bytes: int
    extra: dict = {}


class SnapshotResponse(BaseModel):
    id: str
    repo_id: str
    org_id: str
    branch_id: str | None = None
    name: str
    description: str
    manifest_hash: str
    total_bytes: int
    component_count: int
    commit_oid: str | None = None
    created_at: str
    components: list[SnapshotComponentModel] = []


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotResponse]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class SnapshotDryRunResponse(BaseModel):
    repo_id: str
    branch_id: str | None
    manifest_hash: str
    total_bytes: int
    components: list[SnapshotComponentModel]
    dry_run: bool = True


# --- Helpers ---


def _canonical_json_bytes(obj: object) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    ).encode("ascii")


def _sha256_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


async def _resolve_branch(
    repo: Repository,
    branch_name: str,
    session: AsyncSession,
) -> Branch | None:
    """Return the Branch row matching ``branch_name``, or the repo default.

    Returns None if the repo has no matching branch row — callers should
    treat that as a snapshottable state with empty overlays.
    """
    target = branch_name or repo.default_branch or "main"
    result = await session.execute(
        select(Branch).where(
            Branch.repo_id == repo.id, Branch.name == target,
        )
    )
    return result.scalar_one_or_none()


async def _compute_components(
    session: AsyncSession,
    branch: Branch | None,
) -> tuple[list[SnapshotComponentModel], int]:
    """Compute the content-addressed component list for a snapshot.

    Returns ``(components, total_bytes)``.

    For each component, digest is the SHA-256 of a canonical JSON
    document describing the component contents at this moment. The
    component bodies themselves are NOT embedded in the response — they
    live in the existing storage tables and can be reassembled from the
    digests + the content_store / symbol / dependency / embedding tables
    on read.
    """
    components: list[SnapshotComponentModel] = []
    total_bytes = 0

    # --- Content component ---
    #
    # Every path in the branch overlay manifest mapped to its content
    # SHA. This is the smallest possible representation of "what files
    # are in the snapshot and what's in each one". The digest changes
    # if any path moves, is added, or any content SHA changes.
    content_shas: list[str] = []
    if branch is not None:
        from attocode.code_intel.storage.branch_overlay import BranchOverlay
        overlay = BranchOverlay(session)
        manifest = await overlay.resolve_manifest(branch.id)
        content_shas = sorted(set(manifest.values()))
        # Sum sizes from file_contents — lets the caller plan disk usage.
        if content_shas:
            result = await session.execute(
                select(func.coalesce(func.sum(FileContent.size_bytes), 0))
                .where(FileContent.sha256.in_(content_shas))
            )
            content_bytes = int(result.scalar_one() or 0)
            total_bytes += content_bytes
            content_body = {
                "manifest": manifest,
                "content_shas": content_shas,
                "total_bytes": content_bytes,
            }
        else:
            content_bytes = 0
            content_body = {"manifest": {}, "content_shas": [], "total_bytes": 0}
        components.append(SnapshotComponentModel(
            name="content",
            media_type=_MEDIA_CONTENT,
            digest=_sha256_of(_canonical_json_bytes(content_body)),
            size_bytes=content_bytes,
            extra={"file_count": len(manifest), "sha_count": len(content_shas)},
        ))
    else:
        components.append(SnapshotComponentModel(
            name="content",
            media_type=_MEDIA_CONTENT,
            digest=_sha256_of(b"{}"),
            size_bytes=0,
            extra={"file_count": 0, "sha_count": 0},
        ))

    # --- Symbols component ---
    #
    # Convention: size_bytes is ALWAYS actual bytes. Row counts and
    # other cardinalities go into ``extra``. Symbols / deps / embeddings
    # components report ``size_bytes=0`` because there is no meaningful
    # on-disk byte count for them yet (the OCI adapter will backfill
    # these with real artifact sizes once it ships).
    if content_shas:
        sym_result = await session.execute(
            select(Symbol.content_sha, func.count()).where(
                Symbol.content_sha.in_(content_shas),
            ).group_by(Symbol.content_sha)
        )
        symbol_counts = sorted(
            (row[0], int(row[1])) for row in sym_result
        )
        symbol_total = sum(c for _, c in symbol_counts)
    else:
        symbol_counts = []
        symbol_total = 0
    components.append(SnapshotComponentModel(
        name="symbols",
        media_type=_MEDIA_SYMBOLS,
        digest=_sha256_of(_canonical_json_bytes({"counts": symbol_counts})),
        size_bytes=0,
        extra={"row_count": symbol_total},
    ))

    # --- Dependencies component ---
    if content_shas:
        dep_result = await session.execute(
            select(
                Dependency.source_sha,
                Dependency.target_sha,
                Dependency.dep_type,
            ).where(
                Dependency.source_sha.in_(content_shas),
            ).order_by(
                Dependency.source_sha, Dependency.target_sha, Dependency.dep_type,
            )
        )
        dep_rows = [(r[0], r[1], r[2]) for r in dep_result]
    else:
        dep_rows = []
    components.append(SnapshotComponentModel(
        name="dependencies",
        media_type=_MEDIA_DEPS,
        digest=_sha256_of(_canonical_json_bytes({"edges": dep_rows})),
        size_bytes=0,
        extra={"edge_count": len(dep_rows)},
    ))

    # --- Embeddings components ---
    #
    # Component name includes ``model_version`` so two versions of the
    # same model (during a rotation) live under distinct names instead
    # of colliding on ``embeddings.{model}``. Sort deterministically by
    # (model, version) so DB iteration order can't leak into the
    # manifest hash.
    if content_shas:
        emb_result = await session.execute(
            select(
                Embedding.embedding_model,
                Embedding.embedding_model_version,
                func.count(),
            ).where(
                Embedding.content_sha.in_(content_shas),
            ).group_by(
                Embedding.embedding_model, Embedding.embedding_model_version,
            ).order_by(
                Embedding.embedding_model, Embedding.embedding_model_version,
            )
        )
        for model, version, count in emb_result:
            version_tag = version or "unversioned"
            components.append(SnapshotComponentModel(
                name=f"embeddings.{model}:{version_tag}",
                media_type=_MEDIA_EMBED,
                digest=_sha256_of(_canonical_json_bytes({
                    "model": model,
                    "version": version,
                    "chunk_count": int(count),
                })),
                size_bytes=0,
                extra={
                    "model": model,
                    "model_version": version or "",
                    "chunk_count": int(count),
                },
            ))

    return components, total_bytes


def _compute_manifest_hash(
    *,
    repo_id: uuid.UUID,
    branch_id: uuid.UUID | None,
    commit_oid: str,
    components: list[SnapshotComponentModel],
) -> str:
    """Top-level manifest hash.

    Deliberately excludes transient metadata (name, description,
    created_at, created_by) so two snapshots of identical state under
    different names produce the same hash — required for OCI dedup.

    Sorts by ``(name, digest)`` so identical-name components can't
    reorder based on DB iteration. ``(name, digest)`` is stable even
    when two components share the same logical name — distinct digests
    still produce a deterministic ordering.
    """
    body = {
        "schema": SNAPSHOT_SCHEMA,
        "repo_id": str(repo_id),
        "branch_id": str(branch_id) if branch_id else None,
        "commit_oid": commit_oid or "",
        "components": [
            {
                "name": c.name,
                "media_type": c.media_type,
                "digest": c.digest,
                "size_bytes": c.size_bytes,
            }
            for c in sorted(components, key=lambda x: (x.name, x.digest))
        ],
    }
    return _sha256_of(_canonical_json_bytes(body))


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _to_response(
    snapshot: RepoSnapshot,
    components: list[RepoSnapshotComponent],
) -> SnapshotResponse:
    return SnapshotResponse(
        id=str(snapshot.id),
        repo_id=str(snapshot.repo_id),
        org_id=str(snapshot.org_id),
        branch_id=str(snapshot.branch_id) if snapshot.branch_id else None,
        name=snapshot.name,
        description=snapshot.description,
        manifest_hash=snapshot.manifest_hash,
        total_bytes=snapshot.total_bytes,
        component_count=snapshot.component_count,
        commit_oid=snapshot.commit_oid,
        created_at=snapshot.created_at.isoformat(),
        components=[
            SnapshotComponentModel(
                name=c.name,
                media_type=c.media_type,
                digest=c.digest,
                size_bytes=c.size_bytes,
                extra=dict(c.extra or {}),
            )
            for c in components
        ],
    )


# --- Endpoints ---


@router.post(
    "/{org_id}/repos/{repo_id}/snapshots",
    response_model=SnapshotResponse | SnapshotDryRunResponse,
)
async def create_snapshot(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    req: SnapshotCreateRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotResponse | SnapshotDryRunResponse:
    """Create a content-addressed snapshot of the repo's current state.

    ``dry_run=true`` returns the computed manifest hash + component list
    without inserting anything — useful for diffing against an existing
    snapshot before committing.
    """
    await _require_membership(org_id, auth, session)
    repo = await _load_repo(org_id, repo_id, session)

    if not req.name:
        raise HTTPException(status_code=422, detail="name is required")

    # Resolve branch (may be None if the repo hasn't been indexed yet).
    branch = await _resolve_branch(repo, req.branch, session)
    components, total_bytes = await _compute_components(session, branch)
    manifest_hash = _compute_manifest_hash(
        repo_id=repo_id,
        branch_id=branch.id if branch else None,
        commit_oid=req.commit_oid,
        components=components,
    )

    if req.dry_run:
        return SnapshotDryRunResponse(
            repo_id=str(repo_id),
            branch_id=str(branch.id) if branch else None,
            manifest_hash=manifest_hash,
            total_bytes=total_bytes,
            components=components,
        )

    # Uniqueness: (repo_id, name). IntegrityError from the DB unique
    # constraint would raise 500 — check explicitly for a nice 409.
    existing = await session.execute(
        select(RepoSnapshot).where(
            RepoSnapshot.repo_id == repo_id, RepoSnapshot.name == req.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Snapshot named {req.name!r} already exists for this repo",
        )

    snapshot = RepoSnapshot(
        org_id=org_id,
        repo_id=repo_id,
        branch_id=branch.id if branch else None,
        name=req.name,
        description=req.description,
        manifest_hash=manifest_hash,
        total_bytes=total_bytes,
        component_count=len(components),
        commit_oid=req.commit_oid or None,
        created_by_user_id=auth.user_id,
        extra={},
    )
    session.add(snapshot)
    await session.flush()

    component_rows: list[RepoSnapshotComponent] = []
    for c in components:
        row = RepoSnapshotComponent(
            snapshot_id=snapshot.id,
            name=c.name,
            media_type=c.media_type,
            digest=c.digest,
            size_bytes=c.size_bytes,
            extra=dict(c.extra or {}),
        )
        session.add(row)
        component_rows.append(row)

    from attocode.code_intel.audit import log_event

    await log_event(
        session,
        org_id,
        "snapshot.created",
        repo_id=repo_id,
        user_id=auth.user_id,
        detail={
            "snapshot_id": str(snapshot.id),
            "name": snapshot.name,
            "manifest_hash": snapshot.manifest_hash,
            "component_count": snapshot.component_count,
            "total_bytes": snapshot.total_bytes,
        },
    )

    await session.commit()
    await session.refresh(snapshot)

    return _to_response(snapshot, component_rows)


@router.get(
    "/{org_id}/repos/{repo_id}/snapshots",
    response_model=SnapshotListResponse,
)
async def list_snapshots(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotListResponse:
    """List snapshots for a repository (most recent first)."""
    await _require_membership(org_id, auth, session)
    await _load_repo(org_id, repo_id, session)

    count_result = await session.execute(
        select(func.count()).select_from(
            select(RepoSnapshot).where(RepoSnapshot.repo_id == repo_id).subquery()
        )
    )
    total = int(count_result.scalar() or 0)

    rows_result = await session.execute(
        select(RepoSnapshot)
        .where(RepoSnapshot.repo_id == repo_id)
        .order_by(RepoSnapshot.created_at.desc())
        .offset(offset).limit(limit)
    )
    snapshots: list[RepoSnapshot] = list(rows_result.scalars())

    if not snapshots:
        return SnapshotListResponse(
            snapshots=[], total=total, limit=limit, offset=offset, has_more=False,
        )

    # Batch-fetch components for every snapshot in this page.
    snapshot_ids = [s.id for s in snapshots]
    comp_result = await session.execute(
        select(RepoSnapshotComponent).where(
            RepoSnapshotComponent.snapshot_id.in_(snapshot_ids),
        )
    )
    comps_by_snapshot: dict[uuid.UUID, list[RepoSnapshotComponent]] = {}
    for c in comp_result.scalars():
        comps_by_snapshot.setdefault(c.snapshot_id, []).append(c)

    return SnapshotListResponse(
        snapshots=[
            _to_response(s, comps_by_snapshot.get(s.id, []))
            for s in snapshots
        ],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit < total),
    )


@router.get(
    "/{org_id}/repos/{repo_id}/snapshots/{snapshot_id}",
    response_model=SnapshotResponse,
)
async def get_snapshot(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotResponse:
    """Fetch a single snapshot by id with its full component list."""
    await _require_membership(org_id, auth, session)
    await _load_repo(org_id, repo_id, session)

    result = await session.execute(
        select(RepoSnapshot).where(
            RepoSnapshot.id == snapshot_id,
            RepoSnapshot.repo_id == repo_id,
        )
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    comp_result = await session.execute(
        select(RepoSnapshotComponent).where(
            RepoSnapshotComponent.snapshot_id == snapshot.id,
        )
    )
    return _to_response(snapshot, list(comp_result.scalars()))


@router.delete("/{org_id}/repos/{repo_id}/snapshots/{snapshot_id}")
async def delete_snapshot(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete a snapshot. Requires admin+ role (destructive)."""
    await _require_membership(org_id, auth, session, min_role="admin")
    await _load_repo(org_id, repo_id, session)

    result = await session.execute(
        select(RepoSnapshot).where(
            RepoSnapshot.id == snapshot_id,
            RepoSnapshot.repo_id == repo_id,
        )
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    await session.delete(snapshot)

    from attocode.code_intel.audit import log_event

    await log_event(
        session,
        org_id,
        "snapshot.deleted",
        repo_id=repo_id,
        user_id=auth.user_id,
        detail={"snapshot_id": str(snapshot_id), "name": snapshot.name},
    )
    await session.commit()
    return {"detail": "Snapshot deleted"}
