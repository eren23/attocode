"""Unit tests for the Phase 1 provenance write path.

Codex review M7: migration 017 created the ``provenance`` table but
nothing wrote to it — no ORM, no ``EmbeddingStore`` hook, no helper.
These tests pin down the new write path end-to-end without requiring
a live Postgres: we use ``AsyncMock`` sessions (matching the pattern
in ``test_api_phase3a.py``) and verify the ORM rows that get handed to
``session.add_all`` carry the right shape.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# embedding_provenance_dict
# ---------------------------------------------------------------------------


class TestEmbeddingProvenanceDict:
    def test_required_fields(self):
        from attocode.code_intel.storage.provenance_store import (
            embedding_provenance_dict,
        )

        d = embedding_provenance_dict(
            action_hash="sha256:abc",
            content_sha="aaa" * 16,
            model_name="bge-small",
            model_version="v1",
            dimension=384,
        )
        assert d["action_hash"] == "sha256:abc"
        assert d["artifact_type"] == "embedding_blob_v1"
        assert d["input_blob_oid"] == f"sha256:{'aaa' * 16}"
        assert d["model_name"] == "bge-small"
        assert d["model_version"] == "v1"
        assert d["dimension"] == 384

    def test_extra_flows_through(self):
        from attocode.code_intel.storage.provenance_store import (
            embedding_provenance_dict,
        )

        d = embedding_provenance_dict(
            action_hash="",
            content_sha="x" * 64,
            model_name="m",
            model_version="",
            dimension=768,
            chunk_type="function",
            custom_flag=True,
        )
        assert d["chunk_type"] == "function"
        assert d["custom_flag"] is True


# ---------------------------------------------------------------------------
# write_provenance_rows
# ---------------------------------------------------------------------------


class TestWriteProvenanceRows:
    @pytest.mark.asyncio
    async def test_empty_input_is_noop(self):
        from attocode.code_intel.storage.provenance_store import write_provenance_rows

        session = MagicMock()
        session.add_all = MagicMock()

        count = await write_provenance_rows(session, [])
        assert count == 0
        session.add_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_adds_orm_rows(self):
        from attocode.code_intel.db.models import Provenance
        from attocode.code_intel.storage.provenance_store import write_provenance_rows

        captured: list[list] = []

        def _add_all(rows):
            captured.append(list(rows))

        session = MagicMock()
        session.add_all = _add_all

        rows_in = [
            {
                "action_hash": "sha256:aaa",
                "input_blob_oid": "sha256:b" * 8,  # any placeholder
                "indexer_name": "tree-sitter",
                "indexer_version": "0.21.0",
                "config_digest": "cfg",
                "model_name": "bge-small",  # goes into extra
            },
            {
                "action_hash": "sha256:bbb",
                "input_blob_oid": "sha256:c",
                "indexer_name": "sentence-transformers",
                "indexer_version": "2.2.2",
                "config_digest": "cfg2",
            },
        ]

        n = await write_provenance_rows(session, rows_in)
        assert n == 2
        assert len(captured) == 1
        orm_rows = captured[0]
        assert len(orm_rows) == 2
        assert all(isinstance(r, Provenance) for r in orm_rows)
        # First row routed the unknown ``model_name`` into extra.
        assert orm_rows[0].action_hash == "sha256:aaa"
        assert orm_rows[0].indexer_name == "tree-sitter"
        assert orm_rows[0].extra.get("model_name") == "bge-small"
        # Second row has no extras.
        assert orm_rows[1].extra == {}

    @pytest.mark.asyncio
    async def test_missing_required_fields_get_defaults(self):
        from attocode.code_intel.db.models import Provenance
        from attocode.code_intel.storage.provenance_store import write_provenance_rows

        captured: list[list] = []

        session = MagicMock()
        session.add_all = lambda rows: captured.append(list(rows))

        await write_provenance_rows(session, [{"action_hash": "sha256:x"}])
        assert len(captured) == 1
        row = captured[0][0]
        assert isinstance(row, Provenance)
        assert row.artifact_type == "unknown"
        assert row.input_blob_oid == ""
        assert row.indexer_name == "unknown"
        assert row.indexer_version == "0"
        assert row.producer_service == "attocode-server"
        assert row.producer_host  # non-empty default


# ---------------------------------------------------------------------------
# EmbeddingStore.upsert_embeddings → provenance integration
# ---------------------------------------------------------------------------


class TestEmbeddingStoreProvenanceIntegration:
    @pytest.mark.asyncio
    async def test_upsert_writes_provenance_rows(self):
        """Codex M7: every embedding inserted by ``upsert_embeddings``
        must also produce a provenance row handed to ``session.add``.

        The EmbeddingStore uses ``session.add`` for Embedding rows and
        calls ``write_provenance_rows`` which calls ``session.add_all``
        for Provenance rows. We capture both streams and assert the
        counts match.
        """
        from attocode.code_intel.db.models import Embedding, Provenance
        from attocode.code_intel.storage.embedding_store import EmbeddingStore

        added: list = []
        added_all: list[list] = []

        def _add(obj):
            added.append(obj)

        def _add_all(rows):
            added_all.append(list(rows))

        session = MagicMock()
        session.execute = AsyncMock()  # DELETE pre-upsert
        session.add = _add
        session.add_all = _add_all
        session.flush = AsyncMock()

        store = EmbeddingStore(session)
        await store.upsert_embeddings(
            content_sha="a" * 64,
            embeddings=[
                {
                    "embedding_model": "bge-small",
                    "embedding_model_version": "v1",
                    "embedding_dim": 384,
                    "chunk_text": "def foo(): pass",
                    "chunk_type": "function",
                    "embedding_provenance": {
                        "action_hash": "sha256:first",
                        "config_digest": "cfg_v1",
                    },
                },
                {
                    "embedding_model": "bge-small",
                    "embedding_model_version": "v1",
                    "embedding_dim": 384,
                    "chunk_text": "def bar(): pass",
                    "chunk_type": "function",
                    "embedding_provenance": {
                        "action_hash": "sha256:second",
                        "config_digest": "cfg_v1",
                    },
                },
            ],
        )

        # Two Embedding ORM rows.
        embedding_rows = [r for r in added if isinstance(r, Embedding)]
        assert len(embedding_rows) == 2

        # One batched write_provenance_rows call that produced two
        # Provenance ORM rows.
        assert len(added_all) == 1
        prov_rows = added_all[0]
        assert len(prov_rows) == 2
        assert all(isinstance(r, Provenance) for r in prov_rows)
        assert {r.action_hash for r in prov_rows} == {
            "sha256:first",
            "sha256:second",
        }
        # Both provenance rows point at the same input blob.
        assert all(
            r.input_blob_oid == f"sha256:{'a' * 64}" for r in prov_rows
        )
        # And record the embedding config_digest we passed in.
        assert all(r.config_digest == "cfg_v1" for r in prov_rows)
