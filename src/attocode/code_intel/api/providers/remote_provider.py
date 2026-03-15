"""Remote-mode providers — proxy MCP tool calls through the HTTP API."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RemoteClient:
    """HTTP client for the remote code-intel API."""

    def __init__(self, server: str, token: str, repo_id: str) -> None:
        import httpx
        self._server = server.rstrip("/")
        self._repo_id = repo_id
        self._client = httpx.AsyncClient(
            base_url=self._server,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

    async def get(self, path: str, **kwargs) -> dict:
        resp = await self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, **kwargs) -> dict:
        resp = await self._client.post(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def repo_id(self) -> str:
        return self._repo_id


class RemoteAnalysisProvider:
    """Proxy analysis requests through the remote HTTP API."""

    __slots__ = ("_client",)

    def __init__(self, client: RemoteClient) -> None:
        self._client = client

    async def symbols(self, path: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/symbols",
            params={"path": path, "branch": branch},
        )

    async def search_symbols(self, name: str, branch: str, directory: str = "") -> dict:
        params: dict[str, str] = {"name": name, "branch": branch}
        if directory:
            params["directory"] = directory
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/search-symbols",
            params=params,
        )

    async def cross_references(self, symbol: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/cross-references/{symbol}",
            params={"branch": branch},
        )

    async def impact_analysis(self, files: list[str], branch: str) -> dict:
        return await self._client.post(
            f"/api/v2/projects/{self._client.repo_id}/impact-analysis",
            json={"files": files, "branch": branch},
        )

    async def dependency_graph(self, start_file: str, depth: int, branch: str, directory: str = "") -> dict:
        params: dict[str, Any] = {"start_file": start_file, "depth": depth, "branch": branch}
        if directory:
            params["directory"] = directory
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/dependency-graph",
            params=params,
        )

    async def dependencies(self, path: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/dependencies/{path}",
            params={"branch": branch},
        )

    async def file_analysis(self, path: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/file-analysis/{path}",
            params={"branch": branch},
        )

    async def hotspots(self, branch: str, top_n: int) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/hotspots",
            params={"branch": branch, "top_n": top_n},
        )

    async def conventions(self, branch: str, sample_size: int, path: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/conventions",
            params={"branch": branch, "sample_size": sample_size, "path": path},
        )


class RemoteSearchProvider:
    """Proxy search requests through the remote HTTP API."""

    __slots__ = ("_client",)

    def __init__(self, client: RemoteClient) -> None:
        self._client = client

    async def semantic_search(self, query: str, top_k: int, file_filter: str, branch: str) -> dict:
        params: dict[str, Any] = {"query": query, "top_k": top_k, "branch": branch}
        if file_filter:
            params["file_filter"] = file_filter
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/semantic-search",
            params=params,
        )

    async def security_scan(self, mode: str, path: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/security-scan",
            params={"mode": mode, "path": path, "branch": branch},
        )


class RemoteGraphProvider:
    """Proxy graph requests through the remote HTTP API."""

    __slots__ = ("_client",)

    def __init__(self, client: RemoteClient) -> None:
        self._client = client

    async def graph_query(self, file: str, edge_type: str, direction: str, depth: int, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/graph/query",
            params={"file": file, "edge_type": edge_type, "direction": direction, "depth": depth, "branch": branch},
        )

    async def find_related(self, file: str, top_k: int, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/graph/related/{file}",
            params={"top_k": top_k, "branch": branch},
        )

    async def community_detection(self, branch: str, min_community_size: int, max_communities: int) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/graph/communities",
            params={"branch": branch, "min_community_size": min_community_size, "max_communities": max_communities},
        )
