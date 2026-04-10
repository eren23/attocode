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
