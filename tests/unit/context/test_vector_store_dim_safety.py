"""Regression tests for the local embedding footgun.

The old ``VectorStore._validate_dimension`` silently DELETED every row when
the provider's dimension changed vs the stored dimension. This test pins
down the new behavior: **raise, never wipe.**
"""

from __future__ import annotations

import os

import pytest

from attocode.integrations.context.vector_store import (
    VectorEntry,
    VectorStore,
    VectorStoreDimensionMismatchError,
)


@pytest.fixture
def tmp_vec_db(tmp_path):
    return str(tmp_path / "vectors.db")


def _populate(db_path: str, dimension: int, n: int = 5) -> VectorStore:
    store = VectorStore(db_path=db_path, dimension=dimension, strict_dimension=True)
    for i in range(n):
        store.upsert(
            VectorEntry(
                id=f"id_{i}",
                file_path=f"src/file_{i}.py",
                chunk_type="file",
                name=f"chunk_{i}",
                text=f"text {i}",
                vector=[float(i)] * dimension,
            )
        )
    return store


class TestDimensionMismatchRaises:
    def test_reopen_with_different_dim_raises(self, tmp_vec_db):
        # Populate at dim=8.
        store_a = _populate(tmp_vec_db, 8, n=3)
        assert store_a.count() == 3
        store_a.close()

        # Reopen with dim=16 → should RAISE, not wipe.
        with pytest.raises(VectorStoreDimensionMismatchError) as exc:
            VectorStore(db_path=tmp_vec_db, dimension=16, strict_dimension=True)
        assert exc.value.stored == 8
        assert exc.value.expected == 16

        # Verify the rows were NOT wiped.
        import sqlite3
        conn = sqlite3.connect(f"file:{tmp_vec_db}?mode=ro", uri=True)
        try:
            count = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        finally:
            conn.close()
        assert count == 3, "mismatched dim must not wipe existing vectors"

    def test_degraded_mode_preserves_rows(self, tmp_vec_db):
        _populate(tmp_vec_db, 8, n=4).close()

        # Non-strict: store should open, mark itself degraded, not wipe.
        store = VectorStore(db_path=tmp_vec_db, dimension=16, strict_dimension=False)
        assert store.degraded is True
        assert store.degraded_reason == "dimension_mismatch"
        assert store.count() == 4  # rows preserved

        # Writes refuse in degraded mode.
        with pytest.raises(VectorStoreDimensionMismatchError):
            store.upsert(
                VectorEntry(
                    id="new",
                    file_path="src/new.py",
                    chunk_type="file",
                    name="new",
                    text="t",
                    vector=[1.0] * 16,
                )
            )

        # Still preserved after the failed write.
        assert store.count() == 4

    def test_same_dim_reopens_cleanly(self, tmp_vec_db):
        _populate(tmp_vec_db, 8, n=2).close()
        store = VectorStore(db_path=tmp_vec_db, dimension=8, strict_dimension=True)
        assert store.degraded is False
        assert store.count() == 2


class TestV1SchemaMigration:
    def test_v1_store_gains_new_columns(self, tmp_path):
        """A fresh v1-shaped store (no provenance columns) is upgraded in place."""
        import sqlite3

        db = str(tmp_path / "v1.db")
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                """CREATE TABLE vectors (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    vector BLOB NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE file_metadata (
                    file_path TEXT PRIMARY KEY,
                    last_indexed_at REAL NOT NULL,
                    file_mtime REAL NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                """CREATE TABLE store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            conn.execute(
                "INSERT INTO store_metadata VALUES ('dimension', '8')"
            )
            # Seed one row with a vector so the 'legacy' marker fires.
            import struct
            packed = struct.pack("8f", *([0.5] * 8))
            conn.execute(
                """INSERT INTO vectors (id, file_path, chunk_type, name, text, vector)
                   VALUES ('legacy1', 'src/a.py', 'file', 'a', 't', ?)""",
                (packed,),
            )
            conn.commit()
        finally:
            conn.close()

        # Open via VectorStore — v1 schema should be migrated in place.
        store = VectorStore(db_path=db, dimension=8, strict_dimension=True)
        assert not store.degraded

        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(vectors)").fetchall()}
            for col in (
                "model_name", "model_version", "dimension",
                "produced_at", "blob_oid", "action_hash",
            ):
                assert col in columns, f"migration should add {col}"

            row = conn.execute(
                "SELECT value FROM store_metadata WHERE key='schema_version'"
            ).fetchone()
            assert row is not None
            assert row[0] == "2"

            # Pre-migration row should be flagged with legacy marker.
            row = conn.execute(
                "SELECT model_name FROM vectors WHERE id='legacy1'"
            ).fetchone()
            assert row is not None
            assert row[0] == "legacy-pre-v2"
        finally:
            conn.close()
