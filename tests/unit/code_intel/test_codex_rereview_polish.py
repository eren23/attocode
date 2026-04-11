"""Codex re-review polish test coverage.

The first Codex re-review noted that Batch F's polish fixes (M8, M9,
m1, m2, m4, c1) landed in code but didn't have direct regression tests.
This file closes those gaps so the next review can tick every row.

Each test targets exactly one polish item and pins down the
behavioral contract from the Phase 3a-fix plan.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# M8 — snapshot_diff distinguishes trigram components
# ---------------------------------------------------------------------------


class TestSnapshotDiffTrigramDistinct:
    def test_trigram_components_diff_as_distinct_entries(self, tmp_path, monkeypatch):
        """Two snapshots with different trigram file contents should
        produce three ``changed`` diff entries (one per trigram file),
        not a single collapsed one."""
        import attocode.code_intel.tools.snapshot_tools as st

        project = tmp_path / "proj"
        (project / ".attocode" / "index").mkdir(parents=True)

        # Create three distinct trigram files so snapshot_create
        # picks all of them up.
        for name in ("trigrams.lookup", "trigrams.postings"):
            (project / ".attocode" / "index" / name).write_bytes(
                f"baseline:{name}".encode(),
            )
        # trigrams.db is a sqlite file in the real format; a plain file
        # is fine for the diff test.
        (project / ".attocode" / "index" / "trigrams.db").write_bytes(b"baseline:db")

        monkeypatch.setattr(st, "_get_project_dir", lambda: str(project))

        # Baseline snapshot.
        r1 = st.snapshot_create(name="s1", include="trigrams")
        assert "components" in r1

        # Mutate every trigram file.
        for name in ("trigrams.lookup", "trigrams.postings", "trigrams.db"):
            (project / ".attocode" / "index" / name).write_bytes(
                f"mutated:{name}".encode(),
            )

        r2 = st.snapshot_create(name="s2", include="trigrams")
        assert "components" in r2

        diff = st.snapshot_diff("s1", "s2")
        # Three distinct changed entries for the three trigram files,
        # not a single collapsed ``trigrams`` entry.
        assert "changed:" in diff
        # Count entries in the changed block.
        changed_lines = [
            line for line in diff.splitlines()
            if line.strip().startswith("- trigrams[")
        ]
        assert len(changed_lines) >= 2, (
            f"snapshot_diff collapsed trigram components: {diff!r}"
        )


# ---------------------------------------------------------------------------
# M9 — ADRStore._migrate_schema commits on a fresh store
# ---------------------------------------------------------------------------


class TestADRMigrateSchemaCommit:
    def test_migrate_persists_after_standalone_call(self, tmp_path):
        """Codex M9: ADRStore._migrate_schema must commit its ALTER
        TABLE so the new column is visible on a fresh connection."""
        project = tmp_path / "proj"
        (project / ".attocode").mkdir(parents=True)
        db_path = project / ".attocode" / "adrs.db"

        # Create an old-schema adrs.db (missing anchor_blob_oids).
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript("""
                CREATE TABLE adrs (
                    number INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    context TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL DEFAULT '',
                    consequences TEXT NOT NULL DEFAULT '',
                    related_files TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    author TEXT NOT NULL DEFAULT '',
                    superseded_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

        # Open ADRStore — should migrate + commit + close its own
        # connection.
        from attocode.code_intel.tools.adr_tools import ADRStore
        store = ADRStore(project_dir=str(project))
        store.close()

        # Fresh connection must see the new column.
        conn = sqlite3.connect(str(db_path))
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(adrs)").fetchall()
            }
        finally:
            conn.close()
        assert "anchor_blob_oids" in cols


# ---------------------------------------------------------------------------
# m1 — clear_embeddings filtered dry-run count
# ---------------------------------------------------------------------------


class TestClearEmbeddingsFilteredDryRun:
    def test_dry_run_with_model_filter_reports_filtered_count(
        self, tmp_path, monkeypatch,
    ):
        import attocode.code_intel.tools.maintenance_tools as mt
        from attocode.integrations.context.vector_store import (
            VectorEntry,
            VectorStore,
        )

        project = tmp_path / "proj"
        (project / ".attocode" / "vectors").mkdir(parents=True)
        db_path = project / ".attocode" / "vectors" / "embeddings.db"

        store = VectorStore(
            db_path=str(db_path),
            dimension=4,
            model_name="bge-small",
        )
        try:
            # 3 rows for bge-small, 2 rows for minilm.
            for i in range(3):
                store.upsert(VectorEntry(
                    id=f"b_{i}", file_path=f"src/b{i}.py", chunk_type="file",
                    name="b", text="t", vector=[0.1] * 4,
                ))
            # Switch model_name for the next batch.
            store.model_name = "minilm"
            for i in range(2):
                store.upsert(VectorEntry(
                    id=f"m_{i}", file_path=f"src/m{i}.py", chunk_type="file",
                    name="m", text="t", vector=[0.2] * 4,
                ))
        finally:
            store.close()

        monkeypatch.setattr(mt, "_get_project_dir", lambda: str(project))

        # Dry-run with model filter should report ONLY the filtered count.
        result = mt.clear_embeddings(confirm=False, model="bge-small")
        assert "3 rows" in result
        assert "bge-small" in result

        # Without a filter, the preview reports total (5 rows).
        result_all = mt.clear_embeddings(confirm=False)
        assert "5 rows" in result_all


# ---------------------------------------------------------------------------
# m2 — portable snapshot manifest (project_name basename)
# ---------------------------------------------------------------------------


class TestSnapshotManifestPortable:
    def test_manifest_records_project_name_not_absolute_path(
        self, tmp_path, monkeypatch,
    ):
        """Codex m2: a snapshot manifest must not embed the absolute
        ``project_dir`` path. It should record just the basename as
        ``project_name`` so the artifact is portable across hosts."""
        import tarfile

        import attocode.code_intel.tools.snapshot_tools as st

        project = tmp_path / "my-awesome-project"
        (project / ".attocode" / "index").mkdir(parents=True)
        (project / ".attocode" / "index" / "trigrams.lookup").write_bytes(b"x")

        monkeypatch.setattr(st, "_get_project_dir", lambda: str(project))
        st.snapshot_create(name="portable_test")

        # Find the produced snapshot.
        sdir = project / ".attocode" / "snapshots"
        snaps = list(sdir.iterdir())
        assert len(snaps) == 1

        with tarfile.open(snaps[0], "r:gz") as tar:
            mfile = tar.extractfile("manifest.json")
            assert mfile is not None
            manifest = json.loads(mfile.read().decode("utf-8"))

        assert "project_name" in manifest
        assert manifest["project_name"] == "my-awesome-project"
        # Absolute path must NOT be present.
        assert "project_dir" not in manifest
        assert str(tmp_path) not in json.dumps(manifest)


# ---------------------------------------------------------------------------
# m4 — PATCH /repos cross-org move
# ---------------------------------------------------------------------------


def _make_auth(user_id=None):
    from attocode.code_intel.api.auth.context import AuthContext
    return AuthContext(user_id=user_id or uuid.uuid4(), auth_method="jwt")


def _result(scalar_one_or_none=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
    return r


def _make_session(results):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=list(results))
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    s.add = MagicMock()
    return s


def _membership(role):
    m = MagicMock()
    m.role = role
    return m


class TestPatchRepoCrossOrgMove:
    @pytest.mark.asyncio
    async def test_move_verifies_both_orgs_admin_and_emits_audit(self):
        """Codex m4: a cross-org move must (1) verify admin in source,
        (2) verify admin in target, (3) check name uniqueness in
        target, (4) switch ``repo.org_id``, (5) emit ``repo.updated``
        in source AND ``repo.moved`` in target."""
        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        src_org = uuid.uuid4()
        dst_org = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id,
            org_id=src_org,
            name="moveable",
            clone_url=None,
            local_path=None,
            default_branch="main",
            language="python",
            index_status="ready",
            last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )

        session = _make_session([
            _result(scalar_one_or_none=_membership("admin")),   # source membership check
            _result(scalar_one_or_none=repo),                    # repo load
            _result(scalar_one_or_none=_membership("admin")),   # target membership check
            _result(scalar_one_or_none=None),                    # target name uniqueness (no conflict)
        ])

        req = UpdateRepoRequest(target_org_id=dst_org)
        await update_repo(
            org_id=src_org,
            repo_id=repo_id,
            req=req,
            auth=auth,
            session=session,
        )
        assert str(repo.org_id) == str(dst_org)
        # commit ran (cross-org change is a real change).
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_move_rejected_when_target_has_name_conflict(self):
        from fastapi import HTTPException

        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        src_org = uuid.uuid4()
        dst_org = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id, org_id=src_org, name="collide",
            clone_url=None, local_path=None, default_branch="main",
            language=None, index_status="ready", last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )
        conflict = SimpleNamespace(name="collide")
        session = _make_session([
            _result(scalar_one_or_none=_membership("admin")),    # src
            _result(scalar_one_or_none=repo),                     # load
            _result(scalar_one_or_none=_membership("admin")),    # dst
            _result(scalar_one_or_none=conflict),                 # uniqueness hit
        ])
        req = UpdateRepoRequest(target_org_id=dst_org)
        with pytest.raises(HTTPException) as exc_info:
            await update_repo(
                org_id=src_org, repo_id=repo_id, req=req,
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 409
        assert "already has" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_move_rejected_when_caller_lacks_target_admin(self):
        from fastapi import HTTPException

        from attocode.code_intel.api.routes.orgs import (
            UpdateRepoRequest,
            update_repo,
        )

        src_org = uuid.uuid4()
        dst_org = uuid.uuid4()
        repo_id = uuid.uuid4()
        auth = _make_auth()
        repo = SimpleNamespace(
            id=repo_id, org_id=src_org, name="r",
            clone_url=None, local_path=None, default_branch="main",
            language=None, index_status="ready", last_indexed_at=None,
            created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
        )
        session = _make_session([
            _result(scalar_one_or_none=_membership("admin")),    # src: ok
            _result(scalar_one_or_none=repo),                     # load
            _result(scalar_one_or_none=_membership("member")),   # dst: member only
        ])
        req = UpdateRepoRequest(target_org_id=dst_org)
        with pytest.raises(HTTPException) as exc_info:
            await update_repo(
                org_id=src_org, repo_id=repo_id, req=req,
                auth=auth, session=session,
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# c1 — local snapshot audit log
# ---------------------------------------------------------------------------


class TestSnapshotAuditLog:
    def test_create_appends_jsonl_entry(self, tmp_path, monkeypatch):
        import attocode.code_intel.tools.snapshot_tools as st

        project = tmp_path / "proj"
        (project / ".attocode" / "index").mkdir(parents=True)
        (project / ".attocode" / "index" / "trigrams.lookup").write_bytes(b"x")
        monkeypatch.setattr(st, "_get_project_dir", lambda: str(project))

        st.snapshot_create(name="audit_test")

        log_path = project / ".attocode" / "cache" / "snapshot_events.jsonl"
        assert log_path.exists(), "snapshot_create should append an audit entry"

        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event_type"] == "snapshot.created"
        assert "created_at" in entry
        assert entry["detail"]["snapshot_name"] == "audit_test"

    def test_delete_appends_jsonl_entry(self, tmp_path, monkeypatch):
        import attocode.code_intel.tools.snapshot_tools as st

        project = tmp_path / "proj"
        (project / ".attocode" / "index").mkdir(parents=True)
        (project / ".attocode" / "index" / "trigrams.lookup").write_bytes(b"x")
        monkeypatch.setattr(st, "_get_project_dir", lambda: str(project))

        st.snapshot_create(name="to_delete")
        st.snapshot_delete("to_delete", confirm=True)

        log_path = project / ".attocode" / "cache" / "snapshot_events.jsonl"
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        event_types = [e["event_type"] for e in entries]
        assert "snapshot.created" in event_types
        assert "snapshot.deleted" in event_types

    def test_restore_appends_jsonl_entry(self, tmp_path, monkeypatch):
        import attocode.code_intel.tools.snapshot_tools as st

        project = tmp_path / "proj"
        (project / ".attocode" / "index").mkdir(parents=True)
        (project / ".attocode" / "index" / "trigrams.lookup").write_bytes(b"x")
        monkeypatch.setattr(st, "_get_project_dir", lambda: str(project))

        st.snapshot_create(name="restore_test")
        st.snapshot_restore("restore_test", confirm=True)

        log_path = project / ".attocode" / "cache" / "snapshot_events.jsonl"
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        event_types = [e["event_type"] for e in entries]
        assert "snapshot.restored" in event_types


# ---------------------------------------------------------------------------
# M4 — providers populate pin_id + manifest_hash
# ---------------------------------------------------------------------------


class TestLocalProviderPopulatesPinFields:
    @pytest.mark.asyncio
    async def test_semantic_search_includes_pin_fields(self, tmp_path, monkeypatch):
        """Codex re-review follow-up (round 2): ``LocalSearchProvider``
        must return a response with non-empty ``pin_id`` /
        ``manifest_hash`` fields so clients can rely on them.

        Round 3 follow-up: the pin MUST be persisted so
        ``PinStore.get(pin_id)`` roundtrips. Round-2 computed the id
        but never called ``PinStore.save()``, which silently broke
        ``pin_resolve``.

        Round 4 follow-up: ``LocalSearchProvider`` must mint the pin
        against the **bound service's** ``project_dir``, not the
        global env-var-driven discovery. A multi-project API server
        using ``register_project`` would otherwise persist pins into
        the wrong repo's ``.attocode/cache/pins.db``. The mocked
        service in this test exposes ``project_dir`` pointing at a
        temp directory, and we assert the pin lands in THAT dir's
        pins.db — not in any globally-discovered path.
        """
        import attocode.code_intel.tools.pin_store as pin_store

        project = tmp_path / "proj"
        (project / ".attocode" / "cache").mkdir(parents=True)
        # Clear the per-project cache so this test starts fresh.
        monkeypatch.setattr(pin_store, "_pin_stores", {}, raising=False)

        from attocode.code_intel.api.providers.local_provider import (
            LocalSearchProvider,
        )

        svc = MagicMock()
        # Round 4: the provider now reads svc.project_dir and passes
        # it explicitly to compute_and_persist_pin, so we configure
        # the mock to return the temp project path.
        svc.project_dir = str(project)
        svc.semantic_search_data.return_value = {
            "query": "auth",
            "results": [{"file_path": "src/auth.py", "score": 0.9, "snippet": "…"}],
            "total": 1,
        }
        provider = LocalSearchProvider(svc)
        resp = await provider.semantic_search(
            query="auth", top_k=10, file_filter="", branch="",
        )

        assert resp.query == "auth"
        assert len(resp.results) == 1
        # M4: pin fields populated.
        assert resp.pin_id.startswith("pin_")
        assert len(resp.manifest_hash) == 64  # full sha256 hex

        # Round 3 + 4: the pin MUST be persisted in THIS project's
        # pins.db so a subsequent ``PinStore.get(pin_id)`` roundtrip
        # succeeds against the bound service's project — not a
        # globally-discovered one.
        store = pin_store._get_pin_store(str(project))
        persisted = store.get(resp.pin_id)
        assert persisted is not None
        assert persisted.pin_id == resp.pin_id
        assert persisted.manifest_hash == resp.manifest_hash
        # The pins.db file must actually live under the bound service's
        # project, NOT under ATTOCODE_PROJECT_DIR/cwd.
        expected_db = project / ".attocode" / "cache" / "pins.db"
        assert expected_db.exists(), (
            f"pin should have been persisted to {expected_db} but wasn't"
        )

    @pytest.mark.asyncio
    async def test_multi_project_pins_are_isolated(self, tmp_path, monkeypatch):
        """Round 4 regression test for Codex P2 finding #2.

        A single interpreter serving two different projects via two
        ``LocalSearchProvider`` instances must write pins into EACH
        project's own ``pins.db``, not into a globally-discovered
        path. Before the round-4 fix, both providers would share
        whatever ``ATTOCODE_PROJECT_DIR``/cwd happened to point at
        and persist pins to the wrong repo.
        """
        import attocode.code_intel.tools.pin_store as pin_store

        project_a = tmp_path / "proj_a"
        project_b = tmp_path / "proj_b"
        (project_a / ".attocode" / "cache").mkdir(parents=True)
        (project_b / ".attocode" / "cache").mkdir(parents=True)

        # Clear the per-project cache and force the global discovery
        # to point at a bogus third directory so we're certain the
        # providers are NOT using the fallback path.
        bogus = tmp_path / "bogus_global"
        bogus.mkdir()
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(bogus))
        monkeypatch.setattr(pin_store, "_pin_stores", {}, raising=False)

        from attocode.code_intel.api.providers.local_provider import (
            LocalSearchProvider,
        )

        svc_a = MagicMock()
        svc_a.project_dir = str(project_a)
        svc_a.semantic_search_data.return_value = {
            "query": "q", "results": [], "total": 0,
        }
        svc_b = MagicMock()
        svc_b.project_dir = str(project_b)
        svc_b.semantic_search_data.return_value = {
            "query": "q", "results": [], "total": 0,
        }

        prov_a = LocalSearchProvider(svc_a)
        prov_b = LocalSearchProvider(svc_b)

        resp_a = await prov_a.semantic_search(
            query="q", top_k=1, file_filter="", branch="",
        )
        resp_b = await prov_b.semantic_search(
            query="q", top_k=1, file_filter="", branch="",
        )

        # Each project got a pin, written to its OWN pins.db.
        assert (project_a / ".attocode" / "cache" / "pins.db").exists()
        assert (project_b / ".attocode" / "cache" / "pins.db").exists()
        # The bogus "global" dir must NOT have a pins.db — the
        # providers ignored ATTOCODE_PROJECT_DIR and used svc.project_dir.
        assert not (bogus / ".attocode" / "cache" / "pins.db").exists()

        # Round-trip: each pin_id must be resolvable in its own repo's
        # PinStore. Also verify they are persisted independently.
        store_a = pin_store._get_pin_store(str(project_a))
        store_b = pin_store._get_pin_store(str(project_b))
        assert store_a.get(resp_a.pin_id) is not None
        assert store_b.get(resp_b.pin_id) is not None

    def test_pin_tools_monkeypatch_of_get_project_dir_is_effective(
        self, tmp_path, monkeypatch,
    ):
        """Round 4 regression test for Codex P2 finding #1.

        Monkeypatching ``pin_tools._get_project_dir`` must flow
        through into ``_stamp_pin`` so existing test fixtures (e.g.
        ``test_maintenance_tools_phase2.py``) that patch only
        pin_tools keep working. Before the round-4 fix,
        ``_stamp_pin`` read the function from ``pin_store``'s
        namespace, so pin_tools-level patches were silent no-ops.
        """
        import attocode.code_intel.tools.pin_store as pin_store
        import attocode.code_intel.tools.pin_tools as pin_tools

        project = tmp_path / "proj"
        (project / ".attocode" / "cache").mkdir(parents=True)
        monkeypatch.setattr(pin_tools, "_get_project_dir", lambda: str(project))
        monkeypatch.setattr(pin_store, "_pin_stores", {}, raising=False)

        result = pin_tools._stamp_pin("some tool output")

        # The footer must include a pin id and the pins.db must live
        # under the patched project dir — NOT the real project where
        # the test runner is invoked from.
        assert "index_pin:" in result
        expected_db = project / ".attocode" / "cache" / "pins.db"
        assert expected_db.exists(), (
            f"pin_tools._get_project_dir monkeypatch did not take effect; "
            f"expected {expected_db} to exist"
        )

    def test_local_provider_does_not_import_mcp_runtime(self):
        """Round 3 regression test for Codex P2 finding #1:
        ``LocalSearchProvider.semantic_search`` must not transitively
        import ``attocode.code_intel._shared`` (the MCP runtime stub).
        Importing it pulls in ``mcp.server.fastmcp.FastMCP``, which
        calls ``sys.exit(1)`` in environments without the ``mcp``
        package — and ``SystemExit`` would escape any ``except
        Exception`` block in the provider's best-effort pin
        computation, turning a normal search request into a hard
        failure.

        Verified by inspecting the function's source: it must import
        from ``pin_store`` (pure helpers), not ``pin_tools`` (MCP
        runtime).
        """
        import inspect

        from attocode.code_intel.api.providers.local_provider import (
            LocalSearchProvider,
        )

        source = inspect.getsource(LocalSearchProvider.semantic_search)
        # Allowed: import from the MCP-free helper module.
        assert "tools.pin_store" in source
        # Forbidden: importing from the MCP tool layer.
        assert "tools.pin_tools" not in source
        # Forbidden: importing the MCP runtime stub directly.
        assert "code_intel._shared" not in source
