"""Unit tests for the shared action-hash primitive."""

from __future__ import annotations

import pytest

from attocode.code_intel.artifacts import (
    ARTIFACT_TYPES,
    compute_action_hash,
    compute_config_digest,
)


class TestComputeActionHash:
    def test_stable_across_calls(self):
        """Same inputs → same hash, every time."""
        kwargs = dict(
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            input_blob_oid="git:abc123",
            config={"language": "python", "parser_version": "1.0"},
        )
        a = compute_action_hash("symbols", **kwargs)
        b = compute_action_hash("symbols", **kwargs)
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_changes_with_artifact_type(self):
        kwargs = dict(
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            input_blob_oid="git:abc123",
            config={"language": "python"},
        )
        a = compute_action_hash("symbols", **kwargs)
        b = compute_action_hash("ast", **kwargs)
        assert a != b

    def test_changes_with_indexer_version(self):
        base = dict(
            indexer_name="tree-sitter",
            input_blob_oid="git:abc123",
            config={"language": "python"},
        )
        a = compute_action_hash("symbols", indexer_version="1.0.0", **base)
        b = compute_action_hash("symbols", indexer_version="1.0.1", **base)
        assert a != b

    def test_changes_with_input_blob(self):
        base = dict(
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            config={"language": "python"},
        )
        a = compute_action_hash("symbols", input_blob_oid="git:aaa", **base)
        b = compute_action_hash("symbols", input_blob_oid="git:bbb", **base)
        assert a != b

    def test_changes_with_whitelisted_config_key(self):
        """Any change to a whitelisted config_subset key changes the hash."""
        base = dict(
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            input_blob_oid="git:abc123",
        )
        a = compute_action_hash(
            "symbols",
            config={"language": "python", "parser_version": "1.0"},
            **base,
        )
        b = compute_action_hash(
            "symbols",
            config={"language": "python", "parser_version": "1.1"},
            **base,
        )
        assert a != b

    def test_ignores_non_whitelisted_keys(self):
        """Keys not in config_subset don't affect the hash (meta config)."""
        base = dict(
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            input_blob_oid="git:abc123",
        )
        a = compute_action_hash(
            "symbols",
            config={"language": "python", "display_mode": "verbose"},
            **base,
        )
        b = compute_action_hash(
            "symbols",
            config={"language": "python", "display_mode": "compact"},
            **base,
        )
        assert a == b

    def test_rejects_unknown_artifact_type(self):
        with pytest.raises(ValueError, match="unknown artifact_type"):
            compute_action_hash(
                "totally_made_up_type",  # type: ignore[arg-type]
                indexer_name="x",
                indexer_version="1",
                input_blob_oid="sha256:deadbeef",
                config={},
            )

    def test_embedding_config_captures_model(self):
        base = dict(
            indexer_name="sentence-transformers",
            indexer_version="2.2.2",
            input_blob_oid="git:foo",
        )
        a = compute_action_hash(
            "embedding",
            config={"model_name": "bge-small", "dimension": 384, "normalize": True},
            **base,
        )
        b = compute_action_hash(
            "embedding",
            config={"model_name": "bge-base", "dimension": 768, "normalize": True},
            **base,
        )
        assert a != b

    def test_input_tree_oid_affects_hash(self):
        base = dict(
            indexer_name="tree-sitter",
            indexer_version="0.21.0",
            input_blob_oid="git:abc",
            config={"language": "python"},
        )
        a = compute_action_hash("symbols", input_tree_oid=None, **base)
        b = compute_action_hash("symbols", input_tree_oid="git:tree_xxx", **base)
        assert a != b


class TestConfigDigest:
    def test_missing_whitelisted_key_defaults_to_none(self):
        """Adding a new whitelisted key should be backwards-compatible only
        if the new key starts missing (None)."""
        a = compute_config_digest("symbols", {"language": "python"})
        # Adding an unknown key doesn't change it.
        b = compute_config_digest("symbols", {"language": "python", "unknown": "x"})
        assert a == b

    def test_rejects_unknown_artifact_type(self):
        with pytest.raises(ValueError):
            compute_config_digest("not_real", {})


class TestArtifactTypes:
    def test_all_expected_types_present(self):
        """Lock-in test — any new artifact type must be explicitly added."""
        expected = {
            "symbols",
            "references",
            "embedding",
            "ast",
            "deps",
            "repo_map_entry",
            "stack_graph",
            "conventions",
            "learning_ref",
            "symbol_set_v1",
            "dep_graph_v1",
            "embedding_blob_v1",
            "stack_graph_partial_v1",
            "repo_map_slice_v1",
            "conventions_v1",
        }
        assert expected.issubset(ARTIFACT_TYPES)
