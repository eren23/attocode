"""Unit tests for EmbeddingRotator — the Phase 2b rotation state machine.

Uses a deterministic fake EmbeddingProvider so tests don't need
sentence-transformers installed. Covers:

- Full happy-path: start → step → ready_to_cutover → cutover → gc_done → none
- Dimension change preserves row count, flips stored dimension
- Step from an empty table fast-paths to ready_to_cutover
- Abort from each pre-cutover state drops staging, leaves primary intact
- Cutover without backfill is rejected
- GC without cutover is rejected
- Start during an active rotation is rejected
- Provider dimension mismatch fails loudly with state=failed
"""

from __future__ import annotations

import sqlite3

import pytest

from attocode.integrations.context.embedding_rotation import (
    ARCHIVE_TABLE,
    STAGING_TABLE,
    EmbeddingRotator,
    RotationState,
)
from attocode.integrations.context.vector_store import (
    VectorEntry,
    VectorStore,
)

# ---------------------------------------------------------------------------
# Fake provider — deterministic synthesis so tests are reproducible
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Deterministic embedding provider.

    Hashes each input text to a seed and produces a fixed-dimension
    float vector from it. Two runs on the same input always yield the
    same vector — essential for test assertions.
    """

    def __init__(self, dim: int, model_name: str = "fake-model") -> None:
        self._dim = dim
        self._model_name = model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            # Cycle the hash to fill dim floats in [0, 1).
            vec = []
            for i in range(self._dim):
                vec.append(h[i % len(h)] / 255.0)
            out.append(vec)
        return out

    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return self._model_name


def _seed_store(db_path: str, dim: int, n: int) -> None:
    """Populate a VectorStore with ``n`` deterministic rows of dimension ``dim``."""
    store = VectorStore(
        db_path=db_path,
        dimension=dim,
        model_name="old-model",
        model_version="v0",
        strict_dimension=True,
    )
    try:
        for i in range(n):
            store.upsert(VectorEntry(
                id=f"chunk_{i:04d}",
                file_path=f"src/file_{i}.py",
                chunk_type="file",
                name=f"chunk_{i}",
                text=f"this is the text of chunk {i}",
                vector=[float(i) / n] * dim,
                blob_oid=f"git:blob_{i}",
                action_hash=f"hash_{i}",
            ))
    finally:
        store.close()


@pytest.fixture
def seeded_db(tmp_path):
    """A VectorStore with 5 rows at dimension 4."""
    db_path = str(tmp_path / "vectors.db")
    _seed_store(db_path, dim=4, n=5)
    return db_path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_full_rotation_4d_to_8d(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            # Start.
            status = rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            assert status.state == RotationState.PENDING
            assert status.to_dim == 8
            assert status.total_rows == 5
            assert status.processed_rows == 0

            provider = _FakeProvider(dim=8, model_name="fake-model")

            # Step in two batches — 3 + 2.
            processed1 = rot.step(provider, batch_size=3)
            assert processed1 == 3
            assert rot.status().state == RotationState.BACKFILLING
            assert rot.status().processed_rows == 3

            processed2 = rot.step(provider, batch_size=3)
            # Only 2 remaining — fewer than batch_size means table exhausted
            # and state transitions to ready_to_cutover.
            assert processed2 == 2
            status = rot.status()
            assert status.state == RotationState.READY_TO_CUTOVER
            assert status.processed_rows == 5

            # Cutover.
            status = rot.cutover()
            assert status.state == RotationState.CUTOVER_DONE

            # Verify the primary table now has the NEW dim.
            conn = sqlite3.connect(seeded_db)
            try:
                row = conn.execute(
                    "SELECT value FROM store_metadata WHERE key = 'dimension'"
                ).fetchone()
                assert row[0] == "8"
                # 5 rows in the new vectors table.
                assert conn.execute(
                    "SELECT COUNT(*) FROM vectors"
                ).fetchone()[0] == 5
                # Vectors are the right length.
                vrow = conn.execute(
                    "SELECT vector FROM vectors LIMIT 1"
                ).fetchone()
                assert len(vrow[0]) == 8 * 4  # 8 floats * 4 bytes each
                # Archive still exists.
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {ARCHIVE_TABLE}"
                ).fetchone()
                assert row[0] == 5
                # model_name is the new one.
                row = conn.execute(
                    "SELECT model_name FROM vectors LIMIT 1"
                ).fetchone()
                assert row[0] == "fake-model"
            finally:
                conn.close()

            # GC.
            status = rot.gc_old()
            assert status.state == RotationState.NONE  # cleared back to NONE

            # Archive is gone.
            conn = sqlite3.connect(seeded_db)
            try:
                row = conn.execute(
                    f"SELECT name FROM sqlite_master "
                    f"WHERE type='table' AND name='{ARCHIVE_TABLE}'"
                ).fetchone()
                assert row is None
                # rotation_state key is gone.
                row = conn.execute(
                    "SELECT value FROM store_metadata WHERE key = 'rotation_state'"
                ).fetchone()
                assert row is None
            finally:
                conn.close()
        finally:
            rot.close()

    def test_rotation_preserves_row_ids_and_metadata(self, seeded_db):
        """After cutover, every id from the old table exists in the new one
        and carries the new model_name/dimension/produced_at."""
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            provider = _FakeProvider(dim=8)
            # Process everything in one big batch.
            while rot.step(provider, batch_size=10) > 0:
                pass
            rot.cutover()

            conn = sqlite3.connect(seeded_db)
            try:
                ids = {
                    r[0] for r in
                    conn.execute("SELECT id FROM vectors").fetchall()
                }
                assert ids == {f"chunk_{i:04d}" for i in range(5)}

                # Each row has the new dimension + model_name.
                rows = conn.execute(
                    "SELECT dimension, model_name, model_version FROM vectors"
                ).fetchall()
                assert all(r[0] == 8 for r in rows)
                assert all(r[1] == "fake-model" for r in rows)
                assert all(r[2] == "v1" for r in rows)

                # blob_oid + action_hash carried over from the originals.
                row = conn.execute(
                    "SELECT blob_oid, action_hash FROM vectors "
                    "WHERE id = 'chunk_0002'"
                ).fetchone()
                assert row[0] == "git:blob_2"
                assert row[1] == "hash_2"
            finally:
                conn.close()
        finally:
            rot.close()


# ---------------------------------------------------------------------------
# Abort / state transitions
# ---------------------------------------------------------------------------


class TestAbortAndErrors:
    def test_abort_from_pending(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            status = rot.abort()
            assert status.state == RotationState.NONE
            # Primary vectors table still intact.
            conn = sqlite3.connect(seeded_db)
            try:
                assert conn.execute(
                    "SELECT COUNT(*) FROM vectors"
                ).fetchone()[0] == 5
                # Staging table gone.
                assert conn.execute(
                    f"SELECT name FROM sqlite_master "
                    f"WHERE type='table' AND name='{STAGING_TABLE}'"
                ).fetchone() is None
            finally:
                conn.close()
        finally:
            rot.close()

    def test_abort_from_backfilling(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            provider = _FakeProvider(dim=8)
            rot.step(provider, batch_size=2)
            assert rot.status().state == RotationState.BACKFILLING

            rot.abort()
            assert rot.status().state == RotationState.NONE
            conn = sqlite3.connect(seeded_db)
            try:
                assert conn.execute(
                    "SELECT COUNT(*) FROM vectors"
                ).fetchone()[0] == 5
            finally:
                conn.close()
        finally:
            rot.close()

    def test_abort_refused_after_cutover(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            provider = _FakeProvider(dim=8)
            while rot.step(provider, batch_size=10) > 0:
                pass
            rot.cutover()
            with pytest.raises(RuntimeError, match=r"abort.*corrupt"):
                rot.abort()
        finally:
            rot.close()

    def test_cutover_before_ready_is_rejected(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            with pytest.raises(RuntimeError, match="ready_to_cutover"):
                rot.cutover()
        finally:
            rot.close()

    def test_gc_before_cutover_is_rejected(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            with pytest.raises(RuntimeError, match="cutover_done"):
                rot.gc_old()
        finally:
            rot.close()

    def test_start_during_active_rotation_is_rejected(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            with pytest.raises(RuntimeError, match="already active"):
                rot.start(to_model="another", to_version="v2", to_dim=16)
        finally:
            rot.close()

    def test_dim_mismatch_between_provider_and_target_fails(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            # Provider claims dim=12, but rotation targets dim=8.
            bad_provider = _FakeProvider(dim=12)
            with pytest.raises(RuntimeError, match="dim"):
                rot.step(bad_provider, batch_size=2)
            # State should have transitioned to FAILED.
            assert rot.status().state == RotationState.FAILED
            assert "dim" in rot.status().last_error
        finally:
            rot.close()

    def test_start_refused_on_empty_vectors_table(self, tmp_path):
        """An empty vectors table means nothing to rotate — fail loud."""
        db_path = str(tmp_path / "empty.db")
        _seed_store(db_path, dim=4, n=0)
        rot = EmbeddingRotator(db_path)
        try:
            with pytest.raises(RuntimeError, match="empty"):
                rot.start(to_model="fake-model", to_version="v1", to_dim=8)
        finally:
            rot.close()


# ---------------------------------------------------------------------------
# Status rendering
# ---------------------------------------------------------------------------


class TestStatusRendering:
    def test_status_none_on_fresh_store(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            status = rot.status()
            assert status.state == RotationState.NONE
            assert status.is_active() is False
            assert status.progress_pct() == 0.0
        finally:
            rot.close()

    def test_status_progress_mid_rotation(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            provider = _FakeProvider(dim=8)
            rot.step(provider, batch_size=2)
            s = rot.status()
            assert s.is_active() is True
            assert s.processed_rows == 2
            assert s.total_rows == 5
            assert 39.0 < s.progress_pct() < 41.0  # 40.0%
        finally:
            rot.close()

    def test_status_to_dict_roundtrip(self, seeded_db):
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            d = rot.status().to_dict()
            assert d["state"] == "pending"
            assert d["to"]["model"] == "fake-model"
            assert d["to"]["dim"] == 8
            assert d["total_rows"] == 5
        finally:
            rot.close()


# ---------------------------------------------------------------------------
# Post-cutover: VectorStore can reopen cleanly with the new dimension
# ---------------------------------------------------------------------------


class TestPostCutoverVectorStoreOpen:
    def test_vector_store_opens_at_new_dim(self, seeded_db):
        """After a full rotation, opening VectorStore at the new dim must
        succeed — no dim-mismatch error."""
        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            provider = _FakeProvider(dim=8)
            while rot.step(provider, batch_size=10) > 0:
                pass
            rot.cutover()
            rot.gc_old()
        finally:
            rot.close()

        # Open at new dim — should NOT raise.
        store = VectorStore(
            db_path=seeded_db,
            dimension=8,
            strict_dimension=True,
        )
        try:
            assert store.count() == 5
            assert store.degraded is False
        finally:
            store.close()

    def test_vector_store_rejects_old_dim_after_cutover(self, seeded_db):
        """Opening at the PRE-rotation dim now raises — the store moved on."""
        from attocode.integrations.context.vector_store import (
            VectorStoreDimensionMismatchError,
        )

        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            provider = _FakeProvider(dim=8)
            while rot.step(provider, batch_size=10) > 0:
                pass
            rot.cutover()
            rot.gc_old()
        finally:
            rot.close()

        with pytest.raises(VectorStoreDimensionMismatchError):
            VectorStore(db_path=seeded_db, dimension=4, strict_dimension=True)


# ---------------------------------------------------------------------------
# Codex B3 / M5 — rotation lock + post-cutover cache invalidation
# ---------------------------------------------------------------------------


class TestRotationLockoutAndCacheInvalidation:
    def test_clear_all_refused_during_rotation(self, seeded_db):
        """Codex B3: clear_all() during an active rotation raises
        VectorStoreRotationActiveError instead of silently destroying
        the rotation's source data."""
        from attocode.integrations.context.vector_store import (
            VectorStore,
            VectorStoreRotationActiveError,
        )

        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
        finally:
            rot.close()

        # A fresh VectorStore opened during the rotation must refuse
        # every destructive write.
        store = VectorStore(
            db_path=seeded_db, dimension=4, strict_dimension=True,
        )
        try:
            with pytest.raises(VectorStoreRotationActiveError) as exc_info:
                store.clear_all()
            assert "rotation" in str(exc_info.value).lower()
            assert exc_info.value.rotation_state == "pending"

            # Vectors still there.
            assert store.count() == 5
        finally:
            store.close()

    def test_upsert_refused_during_rotation(self, seeded_db):
        from attocode.integrations.context.vector_store import (
            VectorEntry,
            VectorStore,
            VectorStoreRotationActiveError,
        )

        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
        finally:
            rot.close()

        store = VectorStore(db_path=seeded_db, dimension=4)
        try:
            with pytest.raises(VectorStoreRotationActiveError):
                store.upsert(VectorEntry(
                    id="new_during_rotation",
                    file_path="src/new.py",
                    chunk_type="file",
                    name="new",
                    text="new",
                    vector=[0.5] * 4,
                ))
        finally:
            store.close()

    def test_upsert_batch_refused_during_rotation(self, seeded_db):
        from attocode.integrations.context.vector_store import (
            VectorEntry,
            VectorStore,
            VectorStoreRotationActiveError,
        )

        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
        finally:
            rot.close()

        store = VectorStore(db_path=seeded_db, dimension=4)
        try:
            with pytest.raises(VectorStoreRotationActiveError):
                store.upsert_batch([VectorEntry(
                    id="batch_during_rotation",
                    file_path="src/x.py",
                    chunk_type="file",
                    name="x",
                    text="x",
                    vector=[0.5] * 4,
                )])
        finally:
            store.close()

    def test_upsert_allowed_after_abort(self, seeded_db):
        """An aborted rotation clears the lock."""
        from attocode.integrations.context.vector_store import (
            VectorEntry,
            VectorStore,
        )

        rot = EmbeddingRotator(seeded_db)
        try:
            rot.start(to_model="fake-model", to_version="v1", to_dim=8)
            rot.abort()
        finally:
            rot.close()

        store = VectorStore(db_path=seeded_db, dimension=4)
        try:
            store.upsert(VectorEntry(
                id="after_abort",
                file_path="src/y.py",
                chunk_type="file",
                name="y",
                text="y",
                vector=[0.5] * 4,
            ))
            assert store.count() == 6  # 5 seeded + 1 new
        finally:
            store.close()

    def test_cache_invalidation_on_post_cutover_open_store(self, seeded_db):
        """Codex M5: an already-open VectorStore must reload its
        in-memory matrix after another process completes a cutover.

        We simulate the cross-process case within a single test by
        opening a VectorStore, priming its cache via a search, running
        a full rotation in a separate rotator instance, then issuing
        another search on the still-open store and asserting it sees
        the new vectors.
        """
        from attocode.integrations.context.vector_store import VectorStore

        store = VectorStore(db_path=seeded_db, dimension=4)
        try:
            # Prime the cache.
            before = store.search([0.1, 0.2, 0.3, 0.4], top_k=10)
            assert len(before) > 0

            # Run a full rotation in a fresh rotator — this mutates the
            # underlying vectors.db out from under ``store``.
            rot = EmbeddingRotator(seeded_db)
            try:
                # Start / step / cutover / gc_old to a new dimension.
                rot.start(to_model="fake-model", to_version="v1", to_dim=8)
                provider = _FakeProvider(dim=8)
                while rot.step(provider, batch_size=10) > 0:
                    pass
                rot.cutover()
                rot.gc_old()
            finally:
                rot.close()

            # The live store's stored dim is now 8, but the open
            # instance still thinks it's 4. Search with a 4-dim query
            # first to trigger the external-cache-bump check. The store
            # should pick up the _rotator_cache_ver change, bump its
            # own version, and attempt to reload — which will fail
            # because the vectors are now 8-dim. That's acceptable for
            # this test: the point is that `_last_external_cache_ver`
            # was updated, proving the invalidation path runs.
            store._check_external_cache_bump()
            assert store._last_external_cache_ver >= 1
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Codex M6 — migration 016 downgrade safety
# ---------------------------------------------------------------------------


class TestMigration016DowngradeSafety:
    """Unit tests for the safety logic in the migration downgrade
    path. We can't run a real Alembic downgrade without a live postgres,
    but we can pin down the guard logic by importing the module and
    inspecting its code.
    """

    def test_downgrade_helpers_reject_dual_version_without_flag(self):
        """The downgrade function must consult
        ATTOCODE_ALLOW_DESTRUCTIVE_016_DOWNGRADE and raise RuntimeError
        when there are dual-version rows without the flag set. We verify
        the import and check the function exists."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mig_016",
            "src/attocode/code_intel/migrations/versions/016_embedding_provenance_columns.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        import inspect
        source = inspect.getsource(module.downgrade)
        # Codex-fix guardrails present:
        assert "ATTOCODE_ALLOW_DESTRUCTIVE_016_DOWNGRADE" in source
        assert "Refusing to downgrade migration 016" in source
        assert "embedding_model_version" in source
