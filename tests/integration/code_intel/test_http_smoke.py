"""HTTP smoke tests: full stack with real CodeIntelService.

Unlike unit tests, these do NOT mock the service — the real
CodeIntelService handles requests through the HTTP layer.
"""

from __future__ import annotations

import pytest
import httpx

from attocode.code_intel.api import deps
from attocode.code_intel.api.app import create_app
from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService

pytestmark = pytest.mark.integration


@pytest.fixture()
async def client(sample_project_dir: str):
    """Create an HTTP client backed by a real service on the sample project."""
    deps.reset()
    CodeIntelService._reset_instances()

    config = CodeIntelConfig(project_dir=sample_project_dir)
    app = create_app(config)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    deps.reset()
    CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_smoke_health(client: httpx.AsyncClient):
    """GET /health returns 200."""
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_smoke_register_and_map(client: httpx.AsyncClient, sample_project_dir: str):
    """POST /projects + GET /map returns a real repo tree."""
    # Register the project
    r = await client.post("/api/v1/projects", json={"path": sample_project_dir})
    assert r.status_code == 200
    project_id = r.json()["id"]

    # Get map
    r = await client.get(f"/api/v1/projects/{project_id}/map")
    assert r.status_code == 200
    result = r.json()["result"]
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_smoke_symbols(client: httpx.AsyncClient):
    """GET /symbols returns real symbols from the default project."""
    r = await client.get("/api/v1/projects/default/symbols", params={"path": "main.py"})
    assert r.status_code == 200
    result = r.json()["result"]
    assert "App" in result


@pytest.mark.asyncio
async def test_smoke_search(client: httpx.AsyncClient):
    """GET /search-symbols finds a real symbol."""
    r = await client.get("/api/v1/projects/default/search-symbols", params={"name": "User"})
    assert r.status_code == 200
    result = r.json()["result"]
    assert len(result) > 0
    assert "User" in result


@pytest.mark.asyncio
async def test_smoke_learning_roundtrip(client: httpx.AsyncClient):
    """POST /learnings + GET /learnings/recall round-trips."""
    # Record
    r = await client.post(
        "/api/v1/projects/default/learnings",
        json={
            "type": "pattern",
            "description": "Use dataclasses for simple models",
            "details": "Smoke test learning",
        },
    )
    assert r.status_code == 200

    # Recall
    r = await client.get(
        "/api/v1/projects/default/learnings/recall",
        params={"query": "dataclasses models"},
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert "dataclass" in result.lower() or "model" in result.lower()
