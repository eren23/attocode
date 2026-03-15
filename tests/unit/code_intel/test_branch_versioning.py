"""Tests for BranchOverlay optimistic concurrency (version checks)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.code_intel.storage.branch_overlay import BranchOverlay


def _make_overlay(version: int | None = 0) -> BranchOverlay:
    """Create a BranchOverlay with a mock session returning *version* from get_version."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = version
    session.execute = AsyncMock(return_value=mock_result)
    return BranchOverlay(session)


# -- get_version ---------------------------------------------------------------


async def test_get_version_returns_scalar():
    overlay = _make_overlay(version=7)
    branch_id = uuid.uuid4()
    assert await overlay.get_version(branch_id) == 7


async def test_get_version_returns_zero_when_none():
    overlay = _make_overlay(version=None)
    branch_id = uuid.uuid4()
    assert await overlay.get_version(branch_id) == 0


# -- check_version ------------------------------------------------------------


async def test_check_version_passes_on_match():
    overlay = _make_overlay(version=5)
    branch_id = uuid.uuid4()
    # Should complete without raising
    await overlay.check_version(branch_id, expected=5)


async def test_check_version_raises_on_mismatch():
    overlay = _make_overlay(version=3)
    branch_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Branch version mismatch"):
        await overlay.check_version(branch_id, expected=5)


# -- set_files_batch -----------------------------------------------------------


async def test_set_files_batch_empty_returns_immediately():
    overlay = _make_overlay(version=1)
    branch_id = uuid.uuid4()
    await overlay.set_files_batch(branch_id, files=[], expected_version=1)
    # Session should never have been touched (no execute, no flush)
    overlay._session.execute.assert_not_awaited()
    overlay._session.flush.assert_not_awaited()


async def test_set_files_batch_with_expected_version_calls_check():
    """When expected_version is provided, check_version must run before the write."""
    branch_id = uuid.uuid4()
    overlay = _make_overlay(version=4)

    with patch.object(overlay, "check_version", new_callable=AsyncMock) as mock_check:
        # _bump_version also calls execute, so wire that up too
        with patch.object(overlay, "_bump_version", new_callable=AsyncMock, return_value=5):
            await overlay.set_files_batch(
                branch_id,
                files=[("a.py", "sha1", "modified")],
                expected_version=4,
            )
        mock_check.assert_awaited_once_with(branch_id, 4)


async def test_set_files_batch_without_expected_version_skips_check():
    """Backward compat: expected_version=None must skip the version check."""
    branch_id = uuid.uuid4()
    overlay = _make_overlay(version=4)

    with patch.object(overlay, "check_version", new_callable=AsyncMock) as mock_check:
        with patch.object(overlay, "_bump_version", new_callable=AsyncMock, return_value=5):
            await overlay.set_files_batch(
                branch_id,
                files=[("a.py", "sha1", "added")],
                expected_version=None,
            )
        mock_check.assert_not_awaited()


async def test_set_files_batch_raises_on_version_mismatch():
    """A concrete end-to-end check: version mismatch propagates ValueError."""
    branch_id = uuid.uuid4()
    overlay = _make_overlay(version=2)

    with pytest.raises(ValueError, match="Branch version mismatch"):
        await overlay.set_files_batch(
            branch_id,
            files=[("b.py", "sha2", "added")],
            expected_version=99,
        )
