"""Tests for IncrementalPipeline.acquire_branch_lock advisory locking."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from attocode.code_intel.indexing.incremental import IncrementalPipeline


# ---------------------------------------------------------------------------
# acquire_branch_lock — key derivation
# ---------------------------------------------------------------------------


class TestAcquireBranchLockKeyDerivation:
    async def test_lock_key_derived_from_first_8_bytes_masked(self):
        """Lock key = first 8 bytes of UUID interpreted as big-endian int, masked to 63 bits."""
        branch_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        expected_key = int.from_bytes(branch_id.bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF

        session = AsyncMock()
        await IncrementalPipeline.acquire_branch_lock(session, branch_id)

        session.execute.assert_awaited_once()
        bound = session.execute.call_args[0][0]
        # The TextClause carries compiled_cache params; extract the key via
        # the bound parameters dict.
        assert bound.compile().params["key"] == expected_key

    async def test_key_always_non_negative(self):
        """The 0x7FFFFFFFFFFFFFFF mask guarantees a non-negative 63-bit key."""
        # UUID whose first 8 bytes have the high bit set
        branch_id = uuid.UUID("ffffffff-ffff-ffff-0000-000000000000")
        expected_key = int.from_bytes(branch_id.bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF
        assert expected_key >= 0

        session = AsyncMock()
        await IncrementalPipeline.acquire_branch_lock(session, branch_id)

        bound = session.execute.call_args[0][0]
        key = bound.compile().params["key"]
        assert key >= 0
        assert key == expected_key


# ---------------------------------------------------------------------------
# acquire_branch_lock — SQL execution
# ---------------------------------------------------------------------------


class TestAcquireBranchLockSQL:
    async def test_executes_pg_advisory_xact_lock(self):
        """The method must execute pg_advisory_xact_lock with the computed key."""
        session = AsyncMock()
        branch_id = uuid.uuid4()
        await IncrementalPipeline.acquire_branch_lock(session, branch_id)

        session.execute.assert_awaited_once()
        clause = session.execute.call_args[0][0]
        assert "pg_advisory_xact_lock" in str(clause)


# ---------------------------------------------------------------------------
# Determinism & uniqueness
# ---------------------------------------------------------------------------


class TestLockKeyProperties:
    async def test_same_uuid_produces_same_key(self):
        """Calling acquire_branch_lock twice with the same UUID must produce the same key."""
        branch_id = uuid.UUID("aabbccdd-eeff-0011-2233-445566778899")
        session1 = AsyncMock()
        session2 = AsyncMock()

        await IncrementalPipeline.acquire_branch_lock(session1, branch_id)
        await IncrementalPipeline.acquire_branch_lock(session2, branch_id)

        key1 = session1.execute.call_args[0][0].compile().params["key"]
        key2 = session2.execute.call_args[0][0].compile().params["key"]
        assert key1 == key2

    async def test_different_uuids_produce_different_keys(self):
        """Two distinct UUIDs should map to distinct lock keys."""
        # UUIDs must differ in the first 8 bytes (the lock key source)
        id_a = uuid.UUID("00000000-0000-0001-0000-000000000000")
        id_b = uuid.UUID("00000000-0000-0002-0000-000000000000")
        session_a = AsyncMock()
        session_b = AsyncMock()

        await IncrementalPipeline.acquire_branch_lock(session_a, id_a)
        await IncrementalPipeline.acquire_branch_lock(session_b, id_b)

        key_a = session_a.execute.call_args[0][0].compile().params["key"]
        key_b = session_b.execute.call_args[0][0].compile().params["key"]
        assert key_a != key_b


# ---------------------------------------------------------------------------
# process_file_changes — lock failure is silently caught
# ---------------------------------------------------------------------------


class TestLockFailureSilentlyCaught:
    @patch.object(
        IncrementalPipeline,
        "acquire_branch_lock",
        new_callable=AsyncMock,
        side_effect=Exception("not postgres"),
    )
    async def test_lock_failure_does_not_propagate(self, mock_lock: AsyncMock):
        """If acquire_branch_lock raises, process_file_changes catches it and continues."""
        session = AsyncMock()

        with (
            patch("attocode.code_intel.storage.branch_overlay.BranchOverlay") as MockOverlay,
            patch("attocode.code_intel.storage.content_store.ContentStore"),
            patch("attocode.code_intel.storage.symbol_store.SymbolStore"),
            patch("attocode.code_intel.storage.embedding_store.EmbeddingStore"),
        ):
            overlay = AsyncMock()
            overlay.resolve_manifest = AsyncMock(return_value={})
            MockOverlay.return_value = overlay

            pipeline = IncrementalPipeline(session)
            # Should not raise despite the lock failure
            stats = await pipeline.process_file_changes(
                branch_id=uuid.uuid4(), paths=[], base_dir="/tmp"
            )

        mock_lock.assert_awaited_once()
        assert stats["processed"] == 0
        assert stats["errors"] == 0
