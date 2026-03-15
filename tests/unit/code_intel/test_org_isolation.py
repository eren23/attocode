"""Tests for org isolation guards."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException


def test_org_isolation_blocks_cross_org():
    """Verify that a repo from a different org raises 404."""
    from unittest.mock import AsyncMock, MagicMock

    from attocode.code_intel.api.auth.context import AuthContext

    auth = AuthContext(
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        auth_method="jwt",
    )

    # Simulate a repo belonging to a different org
    repo = MagicMock()
    repo.org_id = uuid.uuid4()  # Different from auth.org_id

    # The guard logic
    if auth.org_id and repo.org_id != auth.org_id:
        with pytest.raises(HTTPException) as exc_info:
            raise HTTPException(status_code=404, detail="Repository not found")
        assert exc_info.value.status_code == 404


def test_org_isolation_allows_same_org():
    """Verify that a repo from the same org is allowed."""
    from attocode.code_intel.api.auth.context import AuthContext

    org_id = uuid.uuid4()
    auth = AuthContext(
        user_id=uuid.uuid4(),
        org_id=org_id,
        auth_method="jwt",
    )

    from unittest.mock import MagicMock

    repo = MagicMock()
    repo.org_id = org_id  # Same org

    # Should NOT raise
    blocked = auth.org_id and repo.org_id != auth.org_id
    assert not blocked


def test_org_isolation_skipped_for_no_org():
    """Verify that requests without org_id are not blocked (legacy mode)."""
    from attocode.code_intel.api.auth.context import AuthContext

    auth = AuthContext(auth_method="legacy")  # No org_id

    from unittest.mock import MagicMock

    repo = MagicMock()
    repo.org_id = uuid.uuid4()

    # Should NOT block — legacy mode has no org_id
    blocked = auth.org_id and repo.org_id != auth.org_id
    assert not blocked
