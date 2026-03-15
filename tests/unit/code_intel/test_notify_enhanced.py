"""Tests for idempotency and If-Match in the notify/file-changed endpoint.

Covers:
- Duplicate idempotency_key returns 202 with accepted=0
- Empty idempotency_key skips dedup
- if_match field accepted in request body
- Cache cleanup removes expired entries
- Cache cleanup preserves non-expired entries
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
import pytest

from attocode.code_intel.api import deps
from attocode.code_intel.api.app import create_app
from attocode.code_intel.api.routes import notify
from attocode.code_intel.config import CodeIntelConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def client():
    deps.reset()
    config = CodeIntelConfig(project_dir="/tmp/test-project")
    app = create_app(config)

    mock_svc = MagicMock()
    mock_svc.project_dir = "/tmp/test-project"
    deps._services["default"] = mock_svc

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    notify._idempotency_cache.clear()
    deps.reset()


@pytest.fixture(autouse=True)
def mock_debouncer(monkeypatch):
    """Mock the debouncer to prevent actual async processing."""
    mock_db = AsyncMock()
    monkeypatch.setattr("attocode.code_intel.api.routes.notify._get_debouncer", lambda: mock_db)
    return mock_db


@pytest.fixture(autouse=True)
def mock_default_project_id(monkeypatch):
    """Mock get_default_project_id to return a stub value.

    The deps module is imported locally inside the route handler, so we
    patch the function on the deps module itself.
    """
    monkeypatch.setattr(deps, "get_default_project_id", lambda: "default")


@pytest.fixture(autouse=True)
def mock_detect_branch(monkeypatch):
    """Mock _detect_current_branch to avoid subprocess calls and the sync/await mismatch."""
    async def _fake_detect(project_dir: str) -> str:
        return "main"

    monkeypatch.setattr(notify, "_detect_current_branch", _fake_detect)


# ---------------------------------------------------------------------------
# 1. Duplicate idempotency_key returns 202 with accepted=0
# ---------------------------------------------------------------------------


async def test_duplicate_idempotency_key_returns_accepted_zero(client):
    """Sending the same idempotency_key twice returns 202 with accepted=0."""
    payload = {
        "paths": ["src/a.py"],
        "idempotency_key": "unique-key-001",
    }

    r1 = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r1.status_code == 202
    assert r1.json()["accepted"] == 1

    r2 = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r2.status_code == 202
    assert r2.json()["accepted"] == 0
    assert "Duplicate" in r2.json()["message"]


# ---------------------------------------------------------------------------
# 2. Empty idempotency_key skips dedup
# ---------------------------------------------------------------------------


async def test_empty_idempotency_key_skips_dedup(client):
    """Requests with no idempotency_key are both accepted normally."""
    payload = {"paths": ["src/b.py"]}

    r1 = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r1.status_code == 202
    assert r1.json()["accepted"] == 1

    r2 = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r2.status_code == 202
    assert r2.json()["accepted"] == 1


# ---------------------------------------------------------------------------
# 3. if_match field accepted in request body
# ---------------------------------------------------------------------------


async def test_if_match_field_accepted(client):
    """The if_match field is accepted in the request body without error."""
    payload = {
        "paths": ["src/c.py"],
        "if_match": 42,
    }

    r = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r.status_code == 202
    assert r.json()["accepted"] == 1


async def test_if_match_null_accepted(client):
    """if_match=null (the default) is valid."""
    payload = {
        "paths": ["src/d.py"],
        "if_match": None,
    }

    r = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r.status_code == 202
    assert r.json()["accepted"] == 1


# ---------------------------------------------------------------------------
# 4. Cache cleanup removes expired entries (>5 min)
# ---------------------------------------------------------------------------


async def test_cache_cleanup_removes_expired_entries(client):
    """Expired idempotency keys (>300s) are evicted, allowing re-use."""
    key = "expire-test-key"
    payload = {"paths": ["src/e.py"], "idempotency_key": key}

    # First request: key is stored
    r1 = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r1.status_code == 202
    assert r1.json()["accepted"] == 1
    assert key in notify._idempotency_cache

    # Simulate time passing beyond TTL (300s)
    notify._idempotency_cache[key] = time.monotonic() - 301

    # Second request: expired key should be cleaned up, request accepted
    r2 = await client.post("/api/v1/notify/file-changed", json=payload)
    assert r2.status_code == 202
    assert r2.json()["accepted"] == 1


# ---------------------------------------------------------------------------
# 5. Cache cleanup doesn't remove non-expired entries
# ---------------------------------------------------------------------------


async def test_cache_cleanup_keeps_non_expired_entries(client):
    """Non-expired keys remain in the cache and block duplicates."""
    key_old = "old-key"
    key_new = "new-key"

    # Seed the cache: old-key is expired, new-key is fresh
    notify._idempotency_cache[key_old] = time.monotonic() - 301
    notify._idempotency_cache[key_new] = time.monotonic()

    # Trigger cleanup by sending a request with an idempotency_key
    payload = {"paths": ["src/f.py"], "idempotency_key": "trigger-key"}
    await client.post("/api/v1/notify/file-changed", json=payload)

    # Expired key should have been removed
    assert key_old not in notify._idempotency_cache
    # Fresh key should still be present
    assert key_new in notify._idempotency_cache

    # Verify the fresh key still blocks duplicates
    payload_new = {"paths": ["src/g.py"], "idempotency_key": key_new}
    r = await client.post("/api/v1/notify/file-changed", json=payload_new)
    assert r.status_code == 202
    assert r.json()["accepted"] == 0
    assert "Duplicate" in r.json()["message"]
