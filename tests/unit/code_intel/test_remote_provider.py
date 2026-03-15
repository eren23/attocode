"""Tests for remote-mode providers (RemoteClient, RemoteAnalysisProvider, etc.).

Uses respx to mock httpx transport so no real HTTP traffic is generated.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from attocode.code_intel.api.providers.remote_provider import (
    RemoteAnalysisProvider,
    RemoteClient,
    RemoteGraphProvider,
    RemoteSearchProvider,
)

SERVER = "https://ci.example.com"
TOKEN = "tok_test_secret"
REPO_ID = "repo-abc-123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(server: str = SERVER) -> RemoteClient:
    return RemoteClient(server, TOKEN, REPO_ID)


# ---------------------------------------------------------------------------
# RemoteClient
# ---------------------------------------------------------------------------


class TestRemoteClient:
    async def test_auth_header_sent(self):
        with respx.mock:
            route = respx.get(f"{SERVER}/healthz").mock(
                return_value=httpx.Response(200, json={"status": "ok"}),
            )
            client = _make_client()
            await client.get("/healthz")
            assert route.called
            sent_auth = route.calls[0].request.headers["authorization"]
            assert sent_auth == f"Bearer {TOKEN}"
            await client.close()

    async def test_trailing_slash_stripped(self):
        with respx.mock:
            route = respx.get(f"{SERVER}/ping").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client(server=f"{SERVER}///")
            await client.get("/ping")
            assert route.called
            await client.close()

    async def test_get_returns_parsed_json(self):
        payload = {"items": [1, 2, 3], "total": 3}
        with respx.mock:
            respx.get(f"{SERVER}/data").mock(
                return_value=httpx.Response(200, json=payload),
            )
            client = _make_client()
            result = await client.get("/data")
            assert result == payload
            await client.close()

    async def test_get_raises_on_non_2xx(self):
        with respx.mock:
            respx.get(f"{SERVER}/missing").mock(
                return_value=httpx.Response(404, json={"detail": "not found"}),
            )
            client = _make_client()
            with pytest.raises(httpx.HTTPStatusError):
                await client.get("/missing")
            await client.close()

    async def test_post_returns_parsed_json(self):
        payload = {"created": True}
        with respx.mock:
            respx.post(f"{SERVER}/create").mock(
                return_value=httpx.Response(201, json=payload),
            )
            client = _make_client()
            result = await client.post("/create", json={"name": "x"})
            assert result == payload
            await client.close()

    async def test_post_raises_on_server_error(self):
        with respx.mock:
            respx.post(f"{SERVER}/fail").mock(
                return_value=httpx.Response(500, json={"detail": "boom"}),
            )
            client = _make_client()
            with pytest.raises(httpx.HTTPStatusError):
                await client.post("/fail")
            await client.close()

    async def test_repo_id_property(self):
        client = _make_client()
        assert client.repo_id == REPO_ID
        await client.close()


# ---------------------------------------------------------------------------
# RemoteAnalysisProvider
# ---------------------------------------------------------------------------


class TestRemoteAnalysisProvider:
    async def test_symbols_url_and_params(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/symbols"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"symbols": []}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            result = await provider.symbols("src/main.py", "main")
            assert result == {"symbols": []}
            assert route.called
            req = route.calls[0].request
            assert req.url.params["path"] == "src/main.py"
            assert req.url.params["branch"] == "main"
            await client.close()

    async def test_search_symbols_without_directory(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/search-symbols"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"results": []}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            await provider.search_symbols("MyClass", "dev")
            req = route.calls[0].request
            assert req.url.params["name"] == "MyClass"
            assert req.url.params["branch"] == "dev"
            assert "directory" not in req.url.params
            await client.close()

    async def test_search_symbols_with_directory(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/search-symbols"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"results": []}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            await provider.search_symbols("MyClass", "dev", directory="src/")
            req = route.calls[0].request
            assert req.url.params["directory"] == "src/"
            await client.close()

    async def test_cross_references(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/cross-references/FooBar"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"refs": []}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            result = await provider.cross_references("FooBar", "main")
            assert result == {"refs": []}
            assert route.calls[0].request.url.params["branch"] == "main"
            await client.close()

    async def test_impact_analysis_uses_post(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/impact-analysis"
        with respx.mock:
            route = respx.post(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"impact": []}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            result = await provider.impact_analysis(["a.py", "b.py"], "main")
            assert result == {"impact": []}
            assert route.called
            await client.close()

    async def test_hotspots(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/hotspots"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"hotspots": []}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            result = await provider.hotspots("main", top_n=5)
            assert result == {"hotspots": []}
            assert route.calls[0].request.url.params["top_n"] == "5"
            await client.close()

    async def test_conventions(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/conventions"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"conventions": {}}),
            )
            client = _make_client()
            provider = RemoteAnalysisProvider(client)
            result = await provider.conventions("main", sample_size=10, path="src/")
            assert result == {"conventions": {}}
            req = route.calls[0].request
            assert req.url.params["sample_size"] == "10"
            assert req.url.params["path"] == "src/"
            await client.close()


# ---------------------------------------------------------------------------
# RemoteSearchProvider
# ---------------------------------------------------------------------------


class TestRemoteSearchProvider:
    async def test_semantic_search_url_and_params(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/semantic-search"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"results": []}),
            )
            client = _make_client()
            provider = RemoteSearchProvider(client)
            result = await provider.semantic_search("find auth", 10, "", "main")
            assert result == {"results": []}
            req = route.calls[0].request
            assert req.url.params["query"] == "find auth"
            assert req.url.params["top_k"] == "10"
            assert "file_filter" not in req.url.params
            await client.close()

    async def test_semantic_search_with_file_filter(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/semantic-search"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"results": []}),
            )
            client = _make_client()
            provider = RemoteSearchProvider(client)
            await provider.semantic_search("query", 5, "*.py", "main")
            req = route.calls[0].request
            assert req.url.params["file_filter"] == "*.py"
            await client.close()

    async def test_security_scan(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/security-scan"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"findings": []}),
            )
            client = _make_client()
            provider = RemoteSearchProvider(client)
            result = await provider.security_scan("full", "src/", "main")
            assert result == {"findings": []}
            req = route.calls[0].request
            assert req.url.params["mode"] == "full"
            assert req.url.params["path"] == "src/"
            await client.close()


# ---------------------------------------------------------------------------
# RemoteGraphProvider
# ---------------------------------------------------------------------------


class TestRemoteGraphProvider:
    async def test_graph_query(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/graph/query"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"nodes": [], "edges": []}),
            )
            client = _make_client()
            provider = RemoteGraphProvider(client)
            result = await provider.graph_query("app.py", "import", "outgoing", 2, "main")
            assert result == {"nodes": [], "edges": []}
            req = route.calls[0].request
            assert req.url.params["file"] == "app.py"
            assert req.url.params["edge_type"] == "import"
            assert req.url.params["direction"] == "outgoing"
            assert req.url.params["depth"] == "2"
            assert req.url.params["branch"] == "main"
            await client.close()

    async def test_find_related(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/graph/related/utils.py"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"related": []}),
            )
            client = _make_client()
            provider = RemoteGraphProvider(client)
            result = await provider.find_related("utils.py", 5, "main")
            assert result == {"related": []}
            req = route.calls[0].request
            assert req.url.params["top_k"] == "5"
            assert req.url.params["branch"] == "main"
            await client.close()

    async def test_community_detection(self):
        expected_path = f"/api/v2/projects/{REPO_ID}/graph/communities"
        with respx.mock:
            route = respx.get(f"{SERVER}{expected_path}").mock(
                return_value=httpx.Response(200, json={"communities": []}),
            )
            client = _make_client()
            provider = RemoteGraphProvider(client)
            result = await provider.community_detection("main", min_community_size=3, max_communities=10)
            assert result == {"communities": []}
            req = route.calls[0].request
            assert req.url.params["min_community_size"] == "3"
            assert req.url.params["max_communities"] == "10"
            await client.close()
