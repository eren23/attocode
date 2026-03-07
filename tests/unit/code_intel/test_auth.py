"""Tests for API key authentication."""

from __future__ import annotations

import pytest

from attocode.code_intel.api import deps
from attocode.code_intel.api.auth import verify_api_key
from attocode.code_intel.config import CodeIntelConfig


@pytest.fixture(autouse=True)
def _reset():
    deps.reset()
    yield
    deps.reset()


@pytest.mark.asyncio
async def test_no_key_allows_all():
    deps.configure(CodeIntelConfig(api_key=""))
    # Should not raise
    await verify_api_key(authorization=None)


@pytest.mark.asyncio
async def test_key_configured_no_header_401():
    from fastapi import HTTPException

    deps.configure(CodeIntelConfig(api_key="secret"))
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(authorization=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_key_configured_wrong_key_401():
    from fastapi import HTTPException

    deps.configure(CodeIntelConfig(api_key="secret"))
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(authorization="wrong")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_key_configured_correct_key_passes():
    deps.configure(CodeIntelConfig(api_key="secret"))
    await verify_api_key(authorization="secret")


@pytest.mark.asyncio
async def test_key_configured_bearer_prefix_passes():
    deps.configure(CodeIntelConfig(api_key="secret"))
    await verify_api_key(authorization="Bearer secret")


@pytest.mark.asyncio
async def test_empty_authorization_header_401():
    """Empty string authorization should be treated as missing."""
    from fastapi import HTTPException

    deps.configure(CodeIntelConfig(api_key="secret"))
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(authorization="")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_case_sensitive():
    """Lowercase 'bearer' prefix is not recognized."""
    from fastapi import HTTPException

    deps.configure(CodeIntelConfig(api_key="secret"))
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(authorization="bearer secret")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_extra_whitespace():
    """Extra whitespace around the token is stripped."""
    deps.configure(CodeIntelConfig(api_key="secret"))
    await verify_api_key(authorization="Bearer  secret ")
