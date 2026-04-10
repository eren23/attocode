"""Unit tests for CacheManifest — the local schema-version registry."""

from __future__ import annotations

import json
import os

from attocode.integrations.context.cache_manifest import (
    MANIFEST_SCHEMA_VERSION,
    CacheManifest,
)


class TestLoadSave:
    def test_load_missing_returns_empty(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        assert m.manifest_version == MANIFEST_SCHEMA_VERSION
        assert m.stores == {}

    def test_save_roundtrip(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="index/symbols.db", schema_version=2)
        m.register("embeddings", path="vectors/embeddings.db", schema_version=2)
        m.save()

        path = os.path.join(str(tmp_path), ".attocode", "cache_manifest.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["stores"]["symbols"]["schema_version"] == 2
        assert data["stores"]["embeddings"]["path"] == "vectors/embeddings.db"

        # Reload — state survives the roundtrip.
        m2 = CacheManifest.load(str(tmp_path))
        assert m2.get_store("symbols").schema_version == 2
        assert m2.get_store("embeddings").path == "vectors/embeddings.db"

    def test_save_is_atomic(self, tmp_path):
        """Save uses tempfile + rename; no .tmp files left behind on success."""
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=1)
        m.save()
        attocode_dir = os.path.join(str(tmp_path), ".attocode")
        leftovers = [
            f for f in os.listdir(attocode_dir)
            if f.startswith("cache_manifest_") and f.endswith(".tmp")
        ]
        assert leftovers == []

    def test_malformed_json_returns_fresh(self, tmp_path):
        attocode_dir = os.path.join(str(tmp_path), ".attocode")
        os.makedirs(attocode_dir, exist_ok=True)
        path = os.path.join(attocode_dir, "cache_manifest.json")
        with open(path, "w") as f:
            f.write("not json {{{")
        m = CacheManifest.load(str(tmp_path))
        assert m.stores == {}


class TestRegisterAndBump:
    def test_register_is_idempotent(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=1)
        m.register("symbols", path="p", schema_version=1)
        assert len(m.stores) == 1

    def test_register_updates_version(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=1)
        m.register("symbols", path="p", schema_version=2)
        assert m.get_store("symbols").schema_version == 2

    def test_bump_records_migration_time(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=1)
        assert m.get_store("symbols").last_migrated_at == ""
        m.bump("symbols", new_schema_version=2)
        assert m.get_store("symbols").schema_version == 2
        assert m.get_store("symbols").last_migrated_at != ""

    def test_bump_unregistered_raises(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        import pytest
        with pytest.raises(KeyError):
            m.bump("ghost_store", new_schema_version=1)


class TestNeedsMigration:
    def test_missing_store_needs_migration(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        assert m.needs_migration("symbols", target=1) is True

    def test_behind_needs_migration(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=1)
        assert m.needs_migration("symbols", target=2) is True

    def test_at_target_does_not_need_migration(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=2)
        assert m.needs_migration("symbols", target=2) is False

    def test_above_target_does_not_need_migration(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="p", schema_version=3)
        assert m.needs_migration("symbols", target=2) is False


class TestSummary:
    def test_summary_shape(self, tmp_path):
        m = CacheManifest.load(str(tmp_path))
        m.register("symbols", path="index/symbols.db", schema_version=2)
        m.register("embeddings", path="vectors/embeddings.db", schema_version=2)
        s = m.summary()
        assert s["manifest_version"] == MANIFEST_SCHEMA_VERSION
        assert s["project_dir"] == str(tmp_path)
        assert set(s["stores"]) == {"symbols", "embeddings"}
