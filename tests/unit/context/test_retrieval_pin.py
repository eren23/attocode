"""Unit tests for the shared RetrievalPin primitive."""

from __future__ import annotations

import time

from attocode.code_intel.artifacts import (
    RetrievalPin,
    compute_store_hash,
    make_pin_id,
)


class TestComputeStoreHash:
    def test_stable_under_identical_inputs(self):
        a = compute_store_hash(schema_version="1", row_count=10, max_updated_at=123.0)
        b = compute_store_hash(schema_version="1", row_count=10, max_updated_at=123.0)
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_changes_with_row_count(self):
        a = compute_store_hash(schema_version="1", row_count=10, max_updated_at=123.0)
        b = compute_store_hash(schema_version="1", row_count=11, max_updated_at=123.0)
        assert a != b

    def test_changes_with_timestamp(self):
        a = compute_store_hash(schema_version="1", row_count=10, max_updated_at=123.0)
        b = compute_store_hash(schema_version="1", row_count=10, max_updated_at=124.0)
        assert a != b

    def test_changes_with_schema_version(self):
        a = compute_store_hash(schema_version="1", row_count=10, max_updated_at=123.0)
        b = compute_store_hash(schema_version="2", row_count=10, max_updated_at=123.0)
        assert a != b

    def test_extra_dict_affects_hash(self):
        a = compute_store_hash(
            schema_version="1", row_count=10, max_updated_at=123.0,
            extra={"active_model": "bge-small"},
        )
        b = compute_store_hash(
            schema_version="1", row_count=10, max_updated_at=123.0,
            extra={"active_model": "bge-base"},
        )
        assert a != b

    def test_max_updated_at_none_handled(self):
        """Empty store — max_updated_at is None."""
        h = compute_store_hash(schema_version="1", row_count=0, max_updated_at=None)
        assert len(h) == 64


class TestMakePinId:
    def test_pin_id_shape(self):
        pid = make_pin_id()
        assert pid.startswith("pin_")
        # base32(16 bytes) = 26 chars, we strip padding.
        assert len(pid) >= len("pin_") + 20

    def test_pin_ids_are_unique(self):
        ids = {make_pin_id() for _ in range(100)}
        assert len(ids) == 100


class TestRetrievalPinCreate:
    def test_create_populates_hash_and_id(self):
        pin = RetrievalPin.create(
            manifest_hashes={"symbols": "a", "embeddings": "b"},
        )
        assert pin.pin_id.startswith("pin_")
        assert len(pin.manifest_hash) == 64
        assert pin.manifest_hashes == {"symbols": "a", "embeddings": "b"}

    def test_create_sets_expiry(self):
        pin = RetrievalPin.create(
            manifest_hashes={"symbols": "a"}, ttl_seconds=60,
        )
        assert pin.expires_at > pin.created_at
        assert pin.expires_at - pin.created_at == 60

    def test_ttl_zero_means_no_expiry(self):
        pin = RetrievalPin.create(
            manifest_hashes={"symbols": "a"}, ttl_seconds=0,
        )
        assert pin.expires_at == 0.0
        assert not pin.is_expired()

    def test_same_hashes_same_manifest_hash(self):
        pin1 = RetrievalPin.create(manifest_hashes={"symbols": "a", "embeddings": "b"})
        pin2 = RetrievalPin.create(manifest_hashes={"embeddings": "b", "symbols": "a"})
        assert pin1.manifest_hash == pin2.manifest_hash

    def test_changing_hashes_changes_manifest_hash(self):
        pin1 = RetrievalPin.create(manifest_hashes={"symbols": "a"})
        pin2 = RetrievalPin.create(manifest_hashes={"symbols": "b"})
        assert pin1.manifest_hash != pin2.manifest_hash


class TestRetrievalPinDrift:
    def test_no_drift(self):
        pin = RetrievalPin.create(manifest_hashes={"symbols": "a", "embeddings": "b"})
        drift = pin.drift_from({"symbols": "a", "embeddings": "b"})
        assert drift == {}

    def test_mutation_detected(self):
        pin = RetrievalPin.create(manifest_hashes={"symbols": "a", "embeddings": "b"})
        drift = pin.drift_from({"symbols": "a", "embeddings": "CHANGED"})
        assert "embeddings" in drift
        assert drift["embeddings"] == ("b", "CHANGED")
        assert "symbols" not in drift

    def test_removed_store_detected(self):
        pin = RetrievalPin.create(manifest_hashes={"symbols": "a", "embeddings": "b"})
        drift = pin.drift_from({"symbols": "a"})
        assert "embeddings" in drift
        assert drift["embeddings"] == ("b", "")

    def test_added_store_detected(self):
        pin = RetrievalPin.create(manifest_hashes={"symbols": "a"})
        drift = pin.drift_from({"symbols": "a", "new_store": "z"})
        assert "new_store" in drift
        assert drift["new_store"] == ("", "z")


class TestRetrievalPinExpiry:
    def test_is_expired_past(self):
        past = RetrievalPin.create(manifest_hashes={}, ttl_seconds=1)
        # Fake a past expiry by constructing via from_dict.
        stale = RetrievalPin.from_dict({
            **past.to_dict(),
            "expires_at": time.time() - 10,
        })
        assert stale.is_expired()

    def test_is_expired_future(self):
        pin = RetrievalPin.create(manifest_hashes={}, ttl_seconds=3600)
        assert not pin.is_expired()


# ---------------------------------------------------------------------------
# Codex M3 — _stamp_pin round-trip via PinStore
# ---------------------------------------------------------------------------


class TestStampPinRoundTrip:
    """After Codex fix M3, ``_stamp_pin`` persists a deterministic pin
    id on every call so ``verify_pin`` / ``pin_resolve`` can look it up
    by the exact string that appears in the tool footer.
    """

    def _extract_pin_id(self, footer: str) -> str:
        for line in footer.splitlines():
            if line.startswith("index_pin:"):
                return line.split(":", 1)[1].strip()
        raise AssertionError(f"No index_pin in footer: {footer!r}")

    def _extract_manifest_hash(self, footer: str) -> str:
        for line in footer.splitlines():
            if line.startswith("manifest_hash:"):
                return line.split(":", 1)[1].strip()
        raise AssertionError(f"No manifest_hash in footer: {footer!r}")

    def test_stamp_persists_and_full_manifest_hash(self, tmp_path, monkeypatch):
        """Stamping a result persists the pin so ``PinStore.get``
        returns it, and the footer contains the full 64-char
        ``manifest_hash`` (no more ``…`` truncation)."""
        from attocode.code_intel.tools import pin_tools

        # Redirect the project dir to a temp location so the test
        # doesn't read or write the user's real .attocode.
        project = tmp_path / "proj"
        (project / ".attocode" / "cache").mkdir(parents=True)
        monkeypatch.setattr(pin_tools, "_get_project_dir", lambda: str(project))
        monkeypatch.setattr(pin_tools, "_pin_store", None, raising=False)

        result = pin_tools._stamp_pin("hello world result")
        pin_id = self._extract_pin_id(result)
        manifest_hash = self._extract_manifest_hash(result)

        assert pin_id.startswith("pin_")
        # Full 64-hex manifest hash — no ellipsis.
        assert "…" not in manifest_hash
        assert len(manifest_hash) == 64

        # The persisted pin is findable via PinStore.get().
        store = pin_tools._get_pin_store()
        pin = store.get(pin_id)
        assert pin is not None
        assert pin.pin_id == pin_id
        assert pin.manifest_hash == manifest_hash

    def test_stamp_is_idempotent(self, tmp_path, monkeypatch):
        """Two stamps on an unchanged state yield the same deterministic
        id and the PinStore collapses them to one row (no churn)."""
        from attocode.code_intel.tools import pin_tools

        project = tmp_path / "proj"
        (project / ".attocode" / "cache").mkdir(parents=True)
        monkeypatch.setattr(pin_tools, "_get_project_dir", lambda: str(project))
        monkeypatch.setattr(pin_tools, "_pin_store", None, raising=False)

        result1 = pin_tools._stamp_pin("first")
        result2 = pin_tools._stamp_pin("second")
        id1 = self._extract_pin_id(result1)
        id2 = self._extract_pin_id(result2)
        assert id1 == id2  # deterministic

        store = pin_tools._get_pin_store()
        # Only one row persisted — upsert collapsed the duplicate.
        all_pins = store.list_all()
        matching = [p for p in all_pins if p.pin_id == id1]
        assert len(matching) == 1


# ---------------------------------------------------------------------------
# Codex M4 — SearchResultsResponse carries pin fields
# ---------------------------------------------------------------------------


class TestServerSearchResponsePinFields:
    def test_default_empty_for_legacy_clients(self):
        """Existing clients that don't set pin fields still construct
        a valid SearchResultsResponse — the new fields default to
        empty strings."""
        from attocode.code_intel.api.models import (
            SearchResultItem,
            SearchResultsResponse,
        )

        resp = SearchResultsResponse(
            query="auth middleware",
            results=[SearchResultItem(file_path="src/auth.py", score=0.9)],
            total=1,
        )
        assert resp.pin_id == ""
        assert resp.manifest_hash == ""

    def test_pin_fields_roundtrip(self):
        from attocode.code_intel.api.models import SearchResultsResponse

        resp = SearchResultsResponse(
            query="x",
            results=[],
            total=0,
            pin_id="pin_" + "a" * 20,
            manifest_hash="b" * 64,
        )
        assert resp.pin_id == "pin_" + "a" * 20
        assert resp.manifest_hash == "b" * 64
