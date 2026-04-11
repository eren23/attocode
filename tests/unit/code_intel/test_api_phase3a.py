"""Phase 3a HTTP route tests — PATCH /repos, GC, snapshot CRUD.

Service-mode endpoints that touch the database are tested here with
``AsyncMock``-backed sessions rather than a real Postgres instance.
This matches the pattern established in ``test_org_isolation.py`` and
``test_api.py`` — the repo's existing service-mode coverage is
unit-style against mocked sessions.

What these tests pin down:

- PATCH /repos validates uniqueness, emits an audit event, persists
  changes, and requires admin+.
- POST /gc admits dry_run to members, gates apply behind admin, and
  writes an audit event on apply.
- POST /snapshots computes a stable manifest hash, rejects duplicates,
  writes snapshot + component rows, and surfaces dry_run without
  touching the session.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Minimal mock session helper
# ---------------------------------------------------------------------------


def _result_with(scalar_one_or_none=None, scalar_value=None, rows=None):
    """Build a MagicMock that mimics a SQLAlchemy Result."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
    result.scalar_one = MagicMock(return_value=scalar_value if scalar_value is not None else 0)
    result.scalar = MagicMock(return_value=scalar_value if scalar_value is not None else 0)
    result.scalars = MagicMock(return_value=rows or [])
    result.fetchall = MagicMock(return_value=rows or [])
    result.fetchone = MagicMock(return_value=None)

    # Make the result iterable (some routes iterate rows directly).
    def _iter():
        return iter(rows or [])
    result.__iter__ = lambda self: _iter()

    return result


def _make_session(execute_side_effects):
    """Build an AsyncMock session whose ``execute`` returns a scripted
    sequence of Results in order."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(execute_side_effects))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    return session


def _make_membership(role: str) -> MagicMock:
    m = MagicMock()
    m.role = role
    return m


def _make_auth(user_id: uuid.UUID | None = None):
    from attocode.code_intel.api.auth.context import AuthContext
    return AuthContext(user_id=user_id or uuid.uuid4(), auth_method="jwt")


# ---------------------------------------------------------------------------
# PATCH /orgs/{org_id}/repos/{repo_id}
# ---------------------------------------------------------------------------


class TestUpdateRepo:
    @pytest.mark.asyncio
    async def test_rename_persists_and_emits_audit(self):
        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id,
            org_id=org_id,
            name="old_name",
            clone_url="https://example.com/old.git",
            local_path=None,
            default_branch="main",
            language="python",
            index_status="ready",
            last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),  # _require_membership
            _result_with(scalar_one_or_none=repo),                        # load repo
            _result_with(scalar_one_or_none=None),                        # uniqueness probe
        ])

        # Audit log writes to session.add which is already mocked.
        # log_event also calls session.execute? No — it just session.add()s.

        req = UpdateRepoRequest(name="new_name")
        resp = await update_repo(
            org_id=org_id, repo_id=repo_id, req=req, auth=auth, session=session,
        )

        assert resp.name == "new_name"
        assert repo.name == "new_name"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_rename_conflict_returns_409(self):
        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id, org_id=org_id, name="old", clone_url=None,
            local_path=None, default_branch="main", language=None,
            index_status="ready", last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )
        existing_conflict = SimpleNamespace(name="taken")

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),
            _result_with(scalar_one_or_none=repo),
            _result_with(scalar_one_or_none=existing_conflict),
        ])

        req = UpdateRepoRequest(name="taken")
        with pytest.raises(HTTPException) as exc_info:
            await update_repo(
                org_id=org_id, repo_id=repo_id, req=req, auth=auth, session=session,
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_rename_to_empty_422(self):
        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id, org_id=org_id, name="old", clone_url=None,
            local_path=None, default_branch="main", language=None,
            index_status="ready", last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )
        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),
            _result_with(scalar_one_or_none=repo),
        ])
        req = UpdateRepoRequest(name="")
        with pytest.raises(HTTPException) as exc_info:
            await update_repo(
                org_id=org_id, repo_id=repo_id, req=req, auth=auth, session=session,
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_noop_patch_does_not_commit(self):
        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id, org_id=org_id, name="same", clone_url=None,
            local_path=None, default_branch="main", language="python",
            index_status="ready", last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )
        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),
            _result_with(scalar_one_or_none=repo),
        ])
        req = UpdateRepoRequest(name="same", language="python")
        await update_repo(
            org_id=org_id, repo_id=repo_id, req=req, auth=auth, session=session,
        )
        # No changes → no commit.
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_member_role_forbidden(self):
        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
        ])
        req = UpdateRepoRequest(name="new")
        with pytest.raises(HTTPException) as exc_info:
            await update_repo(
                org_id=org_id, repo_id=repo_id, req=req, auth=auth, session=session,
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# GC endpoints
# ---------------------------------------------------------------------------


class TestGCRoutes:
    @pytest.mark.asyncio
    async def test_dry_run_member_allowed(self):
        from attocode.code_intel.api.routes.gc import GCRunRequest, gc_run

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(id=repo_id, org_id=org_id)

        # The preview helpers run SELECT COUNT(*) and the default for
        # our mocked session returns scalar_one() == 0, which is fine.
        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
            _result_with(scalar_one_or_none=repo),
            _result_with(scalar_value=3),   # content preview
            _result_with(scalar_value=1),   # embedding preview
        ])

        resp = await gc_run(
            org_id=org_id, repo_id=repo_id,
            req=GCRunRequest(dry_run=True),
            auth=auth, session=session,
        )
        assert resp.dry_run is True
        assert resp.removed_total == 4
        kinds = {r.kind for r in resp.results}
        assert kinds == {"content", "embedding"}
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited()

    @pytest.mark.asyncio
    async def test_apply_requires_admin(self):
        from attocode.code_intel.api.routes.gc import GCRunRequest, gc_run

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
        ])
        with pytest.raises(HTTPException) as exc_info:
            await gc_run(
                org_id=org_id, repo_id=repo_id,
                req=GCRunRequest(dry_run=False),
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_apply_admin_path_runs_and_commits(self):
        from attocode.code_intel.api.routes.gc import GCRunRequest, gc_run

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(id=repo_id, org_id=org_id)

        # Real GC calls execute DELETE ... RETURNING-less SQL via
        # session.execute. The result's ``rowcount`` attribute is what
        # ContentStore / EmbeddingStore count.
        def make_result(rowcount):
            r = MagicMock()
            r.rowcount = rowcount
            return r

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),  # membership
            _result_with(scalar_one_or_none=repo),                        # repo load
            make_result(rowcount=5),   # content DELETE
            make_result(rowcount=2),   # embedding DELETE
        ])

        resp = await gc_run(
            org_id=org_id, repo_id=repo_id,
            req=GCRunRequest(dry_run=False),
            auth=auth, session=session,
        )
        assert resp.dry_run is False
        kinds_removed = {r.kind: r.removed for r in resp.results}
        assert kinds_removed == {"content": 5, "embedding": 2}
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_unknown_type_422(self):
        from attocode.code_intel.api.routes.gc import GCRunRequest, gc_run

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(id=repo_id, org_id=org_id)

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),
            _result_with(scalar_one_or_none=repo),
        ])
        with pytest.raises(HTTPException) as exc_info:
            await gc_run(
                org_id=org_id, repo_id=repo_id,
                req=GCRunRequest(dry_run=False, types=["bogus"]),
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Snapshot CRUD
# ---------------------------------------------------------------------------


class TestSnapshotCreate:
    @pytest.mark.asyncio
    async def test_dry_run_returns_hash_without_insert(self):
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotCreateRequest,
            create_snapshot,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id, org_id=org_id, default_branch="main",
        )
        # _resolve_branch returns None when there's no branch row —
        # snapshot compute still works, components are empty/zero.
        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
            _result_with(scalar_one_or_none=repo),
            _result_with(scalar_one_or_none=None),  # branch lookup
        ])

        resp = await create_snapshot(
            org_id=org_id, repo_id=repo_id,
            req=SnapshotCreateRequest(name="baseline", dry_run=True),
            auth=auth, session=session,
        )
        # The dry-run response is the SnapshotDryRunResponse type — it
        # has dry_run=True and a manifest_hash.
        assert resp.dry_run is True
        assert resp.manifest_hash.startswith("sha256:")
        assert resp.repo_id == str(repo_id)
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_name_422(self):
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotCreateRequest,
            create_snapshot,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(id=repo_id, org_id=org_id, default_branch="main")

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
            _result_with(scalar_one_or_none=repo),
        ])
        with pytest.raises(HTTPException) as exc_info:
            await create_snapshot(
                org_id=org_id, repo_id=repo_id,
                req=SnapshotCreateRequest(name=""),
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_duplicate_name_409(self):
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotCreateRequest,
            create_snapshot,
        )

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(id=repo_id, org_id=org_id, default_branch="main")
        existing = SimpleNamespace(id=uuid.uuid4(), name="baseline")

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
            _result_with(scalar_one_or_none=repo),
            _result_with(scalar_one_or_none=None),         # branch lookup
            _result_with(scalar_one_or_none=existing),     # duplicate name probe
        ])

        with pytest.raises(HTTPException) as exc_info:
            await create_snapshot(
                org_id=org_id, repo_id=repo_id,
                req=SnapshotCreateRequest(name="baseline", dry_run=False),
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 409


class TestSnapshotDelete:
    @pytest.mark.asyncio
    async def test_member_cannot_delete(self):
        from attocode.code_intel.api.routes.snapshots import delete_snapshot

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()
        auth = _make_auth()

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("member")),
        ])
        with pytest.raises(HTTPException) as exc_info:
            await delete_snapshot(
                org_id=org_id, repo_id=repo_id, snapshot_id=snapshot_id,
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_404_when_missing(self):
        from attocode.code_intel.api.routes.snapshots import delete_snapshot

        org_id = uuid.uuid4()
        repo_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(id=repo_id, org_id=org_id)

        session = _make_session([
            _result_with(scalar_one_or_none=_make_membership("admin")),
            _result_with(scalar_one_or_none=repo),
            _result_with(scalar_one_or_none=None),  # snapshot lookup
        ])
        with pytest.raises(HTTPException) as exc_info:
            await delete_snapshot(
                org_id=org_id, repo_id=repo_id, snapshot_id=snapshot_id,
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Deterministic manifest hash (no DB — pure function test)
# ---------------------------------------------------------------------------


class TestManifestHashDeterminism:
    def test_same_components_same_hash(self):
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotComponentModel,
            _compute_manifest_hash,
        )

        repo_id = uuid.uuid4()
        components = [
            SnapshotComponentModel(
                name="content", media_type="application/vnd.attocode.content-manifest.v1+json",
                digest="sha256:" + "a" * 64, size_bytes=100,
            ),
            SnapshotComponentModel(
                name="symbols", media_type="application/vnd.attocode.symbols-manifest.v1+json",
                digest="sha256:" + "b" * 64, size_bytes=10,
            ),
        ]
        h1 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="", components=components,
        )
        h2 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="",
            components=list(reversed(components)),
        )
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_component_change_changes_hash(self):
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotComponentModel,
            _compute_manifest_hash,
        )

        repo_id = uuid.uuid4()
        base = [
            SnapshotComponentModel(
                name="content", media_type="x",
                digest="sha256:" + "a" * 64, size_bytes=100,
            ),
        ]
        mutated = [
            SnapshotComponentModel(
                name="content", media_type="x",
                digest="sha256:" + "c" * 64, size_bytes=100,
            ),
        ]
        h1 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="", components=base,
        )
        h2 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="", components=mutated,
        )
        assert h1 != h2

    def test_commit_oid_changes_hash(self):
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotComponentModel,
            _compute_manifest_hash,
        )

        repo_id = uuid.uuid4()
        components = [
            SnapshotComponentModel(
                name="content", media_type="x",
                digest="sha256:" + "a" * 64, size_bytes=100,
            ),
        ]
        h1 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="abc123", components=components,
        )
        h2 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="def456", components=components,
        )
        assert h1 != h2

    def test_multi_version_embeddings_distinct_component_names(self):
        """Codex fix M1: two model versions get distinct component names
        like ``embeddings.bge-small:v1`` and ``embeddings.bge-small:v2``,
        so their digests can't collide in the manifest hash."""
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotComponentModel,
            _compute_manifest_hash,
        )

        repo_id = uuid.uuid4()
        # Same component _name_ twice — this should never happen after
        # the M1 naming fix, but prove the hash is stable anyway by
        # using the sorted-by-(name, digest) path.
        duplicated = [
            SnapshotComponentModel(
                name="embeddings.bge-small:v1",
                media_type="application/vnd.attocode.embeddings-manifest.v1+json",
                digest="sha256:" + "a" * 64,
                size_bytes=0,
                extra={"chunk_count": 10},
            ),
            SnapshotComponentModel(
                name="embeddings.bge-small:v2",
                media_type="application/vnd.attocode.embeddings-manifest.v1+json",
                digest="sha256:" + "b" * 64,
                size_bytes=0,
                extra={"chunk_count": 10},
            ),
        ]
        h1 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="",
            components=duplicated,
        )
        h2 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="",
            components=list(reversed(duplicated)),
        )
        assert h1 == h2
        assert "bge-small:v1" != "bge-small:v2"  # sanity

    def test_identical_name_components_order_stable(self):
        """Same logical name + different digests must still produce a
        deterministic hash. The sort key is ``(name, digest)``, so order
        is defined even when ``name`` ties."""
        from attocode.code_intel.api.routes.snapshots import (
            SnapshotComponentModel,
            _compute_manifest_hash,
        )

        repo_id = uuid.uuid4()
        twins = [
            SnapshotComponentModel(
                name="content", media_type="x",
                digest="sha256:" + "0" * 64, size_bytes=0,
            ),
            SnapshotComponentModel(
                name="content", media_type="x",
                digest="sha256:" + "f" * 64, size_bytes=0,
            ),
        ]
        h1 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="", components=twins,
        )
        h2 = _compute_manifest_hash(
            repo_id=repo_id, branch_id=None, commit_oid="",
            components=list(reversed(twins)),
        )
        assert h1 == h2


# ---------------------------------------------------------------------------
# GC repo scoping — Codex fix B1
# ---------------------------------------------------------------------------


class TestGCRepoScoping:
    """``ContentStore.gc_unreferenced`` and ``EmbeddingStore.gc_orphaned``
    now accept a ``repo_id`` kwarg that restricts the DELETE to blobs
    that were tracked by the target repo's branches. These tests
    validate the query shape without a real DB by capturing the SQL
    text and bind params.
    """

    @pytest.mark.asyncio
    async def test_content_store_passes_repo_id_to_sql(self):
        from attocode.code_intel.storage.content_store import ContentStore

        captured: list[tuple[str, dict]] = []

        async def _execute(stmt, *args, **kwargs):
            # Capture the compiled SQL + bind params.
            text_str = str(stmt)
            binds = dict(getattr(stmt, "compile", lambda: None)().params) if hasattr(stmt, "compile") else {}
            captured.append((text_str, binds))
            result = MagicMock()
            result.rowcount = 0
            return result

        session = MagicMock()
        session.execute = AsyncMock(side_effect=_execute)

        store = ContentStore(session)
        await store.gc_unreferenced(min_age_minutes=5, repo_id=uuid.uuid4())

        assert captured, "gc_unreferenced should issue at least one SQL statement"
        sql, binds = captured[0]
        assert "branches b" in sql
        assert "b.repo_id" in sql
        assert binds.get("repo_id") is not None

    @pytest.mark.asyncio
    async def test_embedding_store_passes_repo_id_to_sql(self):
        from attocode.code_intel.storage.embedding_store import EmbeddingStore

        captured: list[tuple[str, dict]] = []

        async def _execute(stmt, *args, **kwargs):
            text_str = str(stmt)
            binds = dict(getattr(stmt, "compile", lambda: None)().params) if hasattr(stmt, "compile") else {}
            captured.append((text_str, binds))
            result = MagicMock()
            result.rowcount = 0
            return result

        session = MagicMock()
        session.execute = AsyncMock(side_effect=_execute)

        store = EmbeddingStore(session)
        await store.gc_orphaned(min_age_minutes=60, repo_id=uuid.uuid4())

        assert captured
        sql, binds = captured[0]
        assert "branches b" in sql
        assert "b.repo_id" in sql
        assert binds.get("repo_id") is not None

    @pytest.mark.asyncio
    async def test_global_sweep_unchanged_without_repo_id(self):
        """``repo_id=None`` must preserve the pre-fix global sweep behavior."""
        from attocode.code_intel.storage.content_store import ContentStore

        captured: list[str] = []

        async def _execute(stmt, *args, **kwargs):
            captured.append(str(stmt))
            result = MagicMock()
            result.rowcount = 0
            return result

        session = MagicMock()
        session.execute = AsyncMock(side_effect=_execute)

        store = ContentStore(session)
        await store.gc_unreferenced(min_age_minutes=5)  # no repo_id
        assert captured
        # Global form has no "branches b" join in the DELETE.
        assert "branches b" not in captured[0]


# ---------------------------------------------------------------------------
# Snapshot size_bytes semantics — Codex fix M2
# ---------------------------------------------------------------------------


class TestSnapshotSizeSemantics:
    """Non-content components now report ``size_bytes=0`` and move
    cardinality into ``extra``. This lets Phase 3b's OCI adapter use
    ``size_bytes`` as a real byte count."""

    def test_component_model_allows_zero_sizes(self):
        from attocode.code_intel.api.routes.snapshots import SnapshotComponentModel
        # Symbols/deps/embeddings components all construct with size_bytes=0.
        c = SnapshotComponentModel(
            name="symbols",
            media_type="application/vnd.attocode.symbols-manifest.v1+json",
            digest="sha256:" + "a" * 64,
            size_bytes=0,
            extra={"row_count": 42},
        )
        assert c.size_bytes == 0
        assert c.extra["row_count"] == 42

    @pytest.mark.asyncio
    async def test_compute_components_puts_counts_in_extra(self):
        """Codex re-review gap: Batch A's M2 test only checked the Pydantic
        model shape. Verify the real ``_compute_components()`` emits
        ``size_bytes=0`` for symbols / dependencies / embeddings
        components and that the cardinality ends up in ``extra``.

        We use an AsyncMock session whose ``execute`` returns scripted
        aggregate results shaped like SQLAlchemy Row objects. The
        function walks branch overlay → content shas → sum bytes →
        group-by symbols / deps / embeddings — we provide deterministic
        returns for each step so the output is predictable.
        """
        from attocode.code_intel.api.routes.snapshots import _compute_components

        branch_id = uuid.uuid4()
        branch = SimpleNamespace(id=branch_id)

        # Scripted execute results:
        # 1. branch overlay manifest lookup — handled by BranchOverlay
        #    helpers which also call session.execute.
        # 2. file_contents size SUM.
        # 3. symbols group-by.
        # 4. dependencies order_by rows.
        # 5. embeddings group-by.

        # Captured rows
        symbol_rows = [("sha_a", 3), ("sha_b", 5)]   # 8 symbols total
        dep_rows = [("sha_a", "sha_b", "import"), ("sha_b", "sha_a", "call")]
        emb_rows = [("bge-small", "v1", 10), ("bge-small", "v2", 7)]

        def _mk(rows=None, scalar=None, scalar_one=None):
            r = MagicMock()
            r.scalar_one = MagicMock(return_value=scalar_one if scalar_one is not None else 0)
            r.scalar = MagicMock(return_value=scalar if scalar is not None else 0)
            r.__iter__ = lambda self: iter(rows or [])
            # Required to make ``for model, version, count in emb_result:``
            # iterate correctly — SQLAlchemy Result proxies return row
            # tuples when iterated.
            return r

        # Build a side_effect list. BranchOverlay.resolve_manifest
        # internally calls execute a few times. We fake it by patching
        # BranchOverlay.resolve_manifest directly.
        from unittest.mock import patch
        manifest = {"src/a.py": "sha_a", "src/b.py": "sha_b"}

        async def fake_resolve(self_overlay, bid):
            return manifest

        with patch(
            "attocode.code_intel.storage.branch_overlay.BranchOverlay.resolve_manifest",
            new=fake_resolve,
        ):
            session = MagicMock()
            session.execute = AsyncMock(side_effect=[
                _mk(scalar_one=150),          # SUM(size_bytes) → 150
                _mk(rows=symbol_rows),        # symbols group-by
                _mk(rows=dep_rows),           # dependencies order_by
                _mk(rows=emb_rows),           # embeddings group-by
            ])

            components, total_bytes = await _compute_components(session, branch)

        # There should be at least content + symbols + dependencies +
        # 2 embedding components (one per model version).
        assert total_bytes == 150
        by_name = {c.name: c for c in components}
        assert "content" in by_name
        assert "symbols" in by_name
        assert "dependencies" in by_name
        # M1: embedding components are per-version.
        assert "embeddings.bge-small:v1" in by_name
        assert "embeddings.bge-small:v2" in by_name

        # M2: non-content components all report ``size_bytes=0`` with
        # cardinality pushed into ``extra``.
        assert by_name["symbols"].size_bytes == 0
        assert by_name["symbols"].extra.get("row_count") == 8

        assert by_name["dependencies"].size_bytes == 0
        assert by_name["dependencies"].extra.get("edge_count") == 2

        assert by_name["embeddings.bge-small:v1"].size_bytes == 0
        assert by_name["embeddings.bge-small:v1"].extra.get("chunk_count") == 10
        assert by_name["embeddings.bge-small:v2"].size_bytes == 0
        assert by_name["embeddings.bge-small:v2"].extra.get("chunk_count") == 7

        # Content component keeps real bytes.
        assert by_name["content"].size_bytes == 150
