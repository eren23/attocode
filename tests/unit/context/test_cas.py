"""Unit tests for the local ContentAddressedCache."""

from __future__ import annotations

import os
import time

import pytest

from attocode.code_intel.artifacts import Provenance
from attocode.integrations.context.cas import (
    ContentAddressedCache,
    _normalize_key,
)


@pytest.fixture
def cas(tmp_path):
    return ContentAddressedCache(cas_root=str(tmp_path / "cas"))


def _prov() -> Provenance:
    return Provenance.create(
        artifact_type="symbols",
        action_hash="deadbeef",
        input_blob_oid="git:abc123",
        indexer_name="tree-sitter",
        indexer_version="0.21.0",
    )


class TestNormalizeKey:
    def test_bare_hash_rejected(self):
        with pytest.raises(ValueError, match="algo"):
            _normalize_key("abcdef")

    def test_empty_after_prefix_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            _normalize_key("sha256:")

    def test_unsupported_algo_rejected(self):
        with pytest.raises(ValueError, match="unsupported"):
            _normalize_key("md5:abc")

    def test_sha256_accepted(self):
        algo, hx = _normalize_key("sha256:DEADBEEF")
        assert algo == "sha256"
        assert hx == "deadbeef"

    def test_git_accepted(self):
        algo, hx = _normalize_key("git:abc123")
        assert algo == "git"
        assert hx == "abc123"


class TestPutGet:
    def test_put_then_get(self, cas):
        key = "sha256:" + "a" * 64
        data = b"hello world"
        cas.put(key, data, artifact_type="symbols", provenance=_prov())
        assert cas.get(key, "symbols") == data

    def test_missing_get_returns_none(self, cas):
        assert cas.get("sha256:" + "0" * 64, "symbols") is None

    def test_exists(self, cas):
        key = "sha256:" + "b" * 64
        assert cas.exists(key, "symbols") is False
        cas.put(key, b"x", artifact_type="symbols", provenance=_prov())
        assert cas.exists(key, "symbols") is True

    def test_put_is_idempotent(self, cas):
        """Re-putting the same key overwrites without error."""
        key = "sha256:" + "c" * 64
        cas.put(key, b"v1", artifact_type="symbols", provenance=_prov())
        cas.put(key, b"v1", artifact_type="symbols", provenance=_prov())
        assert cas.get(key, "symbols") == b"v1"

    def test_different_artifact_types_coexist(self, cas):
        """Same key under two artifact types is two distinct entries."""
        key = "sha256:" + "d" * 64
        cas.put(key, b"symbols_blob", artifact_type="symbols", provenance=_prov())
        cas.put(key, b"embedding_blob", artifact_type="embedding", provenance=_prov())
        assert cas.get(key, "symbols") == b"symbols_blob"
        assert cas.get(key, "embedding") == b"embedding_blob"


class TestStat:
    def test_stat_returns_entry(self, cas):
        key = "sha256:" + "e" * 64
        prov = _prov()
        cas.put(key, b"hello", artifact_type="symbols", provenance=prov, action_hash="myhash")
        entry = cas.stat(key, "symbols")
        assert entry is not None
        assert entry.size_bytes == len(b"hello")
        assert entry.refcount == 0
        assert entry.action_hash == "myhash"
        assert entry.provenance is not None
        assert entry.provenance.indexer_name == "tree-sitter"

    def test_stat_missing(self, cas):
        assert cas.stat("sha256:" + "0" * 64, "symbols") is None


class TestRefcount:
    def test_incref_decref(self, cas):
        key = "sha256:" + "f" * 64
        cas.put(key, b"x", artifact_type="symbols", provenance=_prov())
        assert cas.incref(key, "symbols") == 1
        assert cas.incref(key, "symbols") == 2
        assert cas.decref(key, "symbols") == 1
        assert cas.decref(key, "symbols") == 0
        # Doesn't go negative.
        assert cas.decref(key, "symbols") == 0

    def test_incref_missing_returns_zero(self, cas):
        assert cas.incref("sha256:" + "0" * 64, "symbols") == 0


class TestGC:
    def test_dry_run_reports_orphans(self, cas):
        key = "sha256:" + "a" * 64
        cas.put(key, b"data", artifact_type="symbols", provenance=_prov())
        # Bypass the age floor so the entry is eligible.
        result = cas.gc(min_age_seconds=0, dry_run=True)
        assert result["dry_run"] is True
        assert result["would_delete_count"] == 1
        assert result["deleted_count"] == 0

    def test_apply_deletes_orphans(self, cas):
        key = "sha256:" + "a" * 64
        cas.put(key, b"data", artifact_type="symbols", provenance=_prov())
        result = cas.gc(min_age_seconds=0, dry_run=False)
        assert result["deleted_count"] == 1
        assert result["freed_bytes"] == len(b"data")
        assert not cas.exists(key, "symbols")

    def test_refcounted_entries_survive_gc(self, cas):
        key_kept = "sha256:" + "1" * 64
        key_orphan = "sha256:" + "2" * 64
        cas.put(key_kept, b"keep", artifact_type="symbols", provenance=_prov())
        cas.put(key_orphan, b"orphan", artifact_type="symbols", provenance=_prov())
        cas.incref(key_kept, "symbols")

        result = cas.gc(min_age_seconds=0, dry_run=False)
        assert result["deleted_count"] == 1
        assert cas.exists(key_kept, "symbols")
        assert not cas.exists(key_orphan, "symbols")

    def test_age_floor_protects_new_entries(self, cas):
        key = "sha256:" + "3" * 64
        cas.put(key, b"data", artifact_type="symbols", provenance=_prov())
        # 1 hour age floor — the entry we just wrote is too young.
        result = cas.gc(min_age_seconds=3600, dry_run=False)
        assert result["deleted_count"] == 0
        assert cas.exists(key, "symbols")


class TestStats:
    def test_stats_groups_by_type(self, cas):
        cas.put("sha256:" + "1" * 64, b"x", artifact_type="symbols", provenance=_prov())
        cas.put("sha256:" + "2" * 64, b"yy", artifact_type="symbols", provenance=_prov())
        cas.put("sha256:" + "3" * 64, b"zzz", artifact_type="embedding", provenance=_prov())
        stats = cas.stats()
        assert stats["total"]["count"] == 3
        assert stats["by_type"]["symbols"]["count"] == 2
        assert stats["by_type"]["embedding"]["count"] == 1
