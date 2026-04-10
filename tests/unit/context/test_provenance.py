"""Unit tests for the shared Provenance dataclass."""

from __future__ import annotations

import json

from attocode.code_intel.artifacts import LEGACY_INDEXER_NAME, Provenance, legacy_provenance


class TestProvenanceCreate:
    def test_create_sets_host_and_now(self):
        p = Provenance.create(
            artifact_type="embedding",
            action_hash="deadbeef",
            input_blob_oid="git:abc",
            indexer_name="sentence-transformers",
            indexer_version="2.2.2",
            config={"model_name": "bge-small", "dimension": 384},
        )
        assert p.artifact_type == "embedding"
        assert p.action_hash == "deadbeef"
        assert p.input_blob_oid == "git:abc"
        assert p.indexer_name == "sentence-transformers"
        assert p.indexer_version == "2.2.2"
        assert p.producer_host  # non-empty
        assert p.produced_at > 0
        # Config JSON is canonical.
        cfg = json.loads(p.config_json)
        assert cfg == {"model_name": "bge-small", "dimension": 384}

    def test_embedding_fields(self):
        p = Provenance.create(
            artifact_type="embedding",
            action_hash="h",
            input_blob_oid="git:x",
            indexer_name="i",
            indexer_version="1",
            model_name="bge-small",
            model_version="v1",
            dimension=384,
            preprocessing_digest="ppd",
        )
        assert p.model_name == "bge-small"
        assert p.model_version == "v1"
        assert p.dimension == 384
        assert p.preprocessing_digest == "ppd"


class TestProvenanceSerialization:
    def test_roundtrip_dict(self):
        p = Provenance.create(
            artifact_type="symbols",
            action_hash="abc",
            input_blob_oid="git:123",
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            config={"language": "python"},
        )
        d = p.to_dict()
        p2 = Provenance.from_dict(d)
        assert p == p2

    def test_roundtrip_json(self):
        p = Provenance.create(
            artifact_type="symbols",
            action_hash="abc",
            input_blob_oid="git:123",
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
        )
        text = p.to_json()
        p2 = Provenance.from_dict(json.loads(text))
        assert p == p2

    def test_from_dict_is_tolerant_of_missing_fields(self):
        """Rows inserted by very old code may only have a subset of fields.
        The loader should fall back to sensible defaults."""
        p = Provenance.from_dict({
            "artifact_type": "symbols",
            "action_hash": "abc",
            "input_blob_oid": "git:x",
        })
        assert p.indexer_name == LEGACY_INDEXER_NAME
        assert p.indexer_version == "0"
        assert p.schema_version >= 1

    def test_frozen_immutable(self):
        """Provenance is frozen — assignment raises."""
        p = Provenance.create(
            artifact_type="symbols",
            action_hash="abc",
            input_blob_oid="git:x",
            indexer_name="i",
            indexer_version="1",
        )
        try:
            p.artifact_type = "other"  # type: ignore[misc]
        except (AttributeError, TypeError):
            # Frozen dataclasses raise FrozenInstanceError (subclass of
            # AttributeError); slotted dataclasses may raise TypeError.
            pass
        else:
            raise AssertionError("Provenance should be frozen")


class TestLegacyProvenance:
    def test_legacy_marker(self):
        p = legacy_provenance("symbols", input_blob_oid="git:abc")
        assert p.indexer_name == LEGACY_INDEXER_NAME
        assert p.producer_service == "attocode-backfill"
        assert p.indexer_version == "0"

    def test_legacy_is_findable(self):
        """The whole point of LEGACY_INDEXER_NAME is that callers can grep
        for it later to find rows that need re-indexing."""
        p = legacy_provenance("embedding", input_blob_oid="git:x")
        assert LEGACY_INDEXER_NAME in p.to_json()
