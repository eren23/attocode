"""Remote-mode providers — proxy MCP and HTTP calls through the HTTP API."""

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


class RemoteTextService:
    """Sync/async text-oriented proxy used by MCP remote mode."""

    __slots__ = ("_server", "_repo_id", "_headers", "_client")

    def __init__(self, server: str, token: str, repo_id: str) -> None:
        import httpx

        self._server = server.rstrip("/")
        self._repo_id = repo_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.Client(
            base_url=self._server,
            headers=self._headers,
            timeout=30,
        )

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _unwrap_text(payload: dict[str, Any]) -> str:
        if "result" in payload and isinstance(payload["result"], str):
            return payload["result"]
        return str(payload)

    def _get_json(self, path: str, *, params: Any = None) -> dict[str, Any]:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post_json(self, path: str, *, json: Any = None, params: Any = None) -> dict[str, Any]:
        resp = self._client.post(path, json=json, params=params)
        resp.raise_for_status()
        return resp.json()

    @property
    def project_dir(self) -> str:
        return f"remote:{self._server}#{self._repo_id}"

    def repo_map(self, *, include_symbols: bool = True, max_tokens: int = 6000) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/map",
            params={"include_symbols": include_symbols, "max_tokens": max_tokens},
        )
        return self._unwrap_text(payload)

    def project_summary(self, max_tokens: int = 4000) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/summary",
            params={"max_tokens": max_tokens},
        )
        return self._unwrap_text(payload)

    def bootstrap(self, task_hint: str = "", max_tokens: int = 8000, indexing_depth: str = "auto") -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/bootstrap",
            json={
                "task_hint": task_hint,
                "max_tokens": max_tokens,
                "indexing_depth": indexing_depth,
            },
        )
        return self._unwrap_text(payload)

    def symbols(self, path: str) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/symbols",
            params={"path": path},
        )
        return self._unwrap_text(payload)

    def search_symbols(self, name: str, limit: int = 30, kind: str = "") -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/search-symbols",
            params={"name": name, "limit": limit, "kind": kind},
        )
        return self._unwrap_text(payload)

    def dependencies(self, path: str) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/dependencies",
            params={"path": path},
        )
        return self._unwrap_text(payload)

    def impact_analysis(self, changed_files: list[str]) -> str:
        params = [("files", item) for item in changed_files]
        payload = self._get_json(f"/api/v1/projects/{self._repo_id}/impact", params=params)
        return self._unwrap_text(payload)

    def cross_references(self, symbol_name: str) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/cross-refs",
            params={"symbol": symbol_name},
        )
        return self._unwrap_text(payload)

    def file_analysis(self, path: str) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/file-analysis",
            params={"path": path},
        )
        return self._unwrap_text(payload)

    def dependency_graph(self, start_file: str, depth: int = 2) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/dependency-graph",
            json={"start_file": start_file, "depth": depth},
        )
        return self._unwrap_text(payload)

    def hotspots(self, top_n: int = 15) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/hotspots",
            params={"top_n": top_n},
        )
        return self._unwrap_text(payload)

    def repo_map_ranked(
        self,
        *,
        task_context: str = "",
        token_budget: int = 1024,
        exclude_tests: bool = True,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/repo-map-ranked",
            json={
                "task_context": task_context,
                "token_budget": token_budget,
                "exclude_tests": exclude_tests,
            },
        )
        return self._unwrap_text(payload)

    def conventions(self, sample_size: int = 50, path: str = "") -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/conventions",
            params={"sample_size": sample_size, "path": path},
        )
        return self._unwrap_text(payload)

    def graph_query(self, *, file: str, edge_type: str = "IMPORTS", direction: str = "outbound", depth: int = 2) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/graph/query",
            json={
                "file": file,
                "edge_type": edge_type,
                "direction": direction,
                "depth": depth,
            },
        )
        return self._unwrap_text(payload)

    def graph_dsl(self, query: str) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/graph/dsl",
            json={"query": query},
        )
        return self._unwrap_text(payload)

    def find_related(self, file: str, top_k: int = 10) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/graph/related",
            json={"file": file, "top_k": top_k},
        )
        return self._unwrap_text(payload)

    def community_detection(self, min_community_size: int = 3, max_communities: int = 20) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/graph/communities",
            params={
                "min_community_size": min_community_size,
                "max_communities": max_communities,
            },
        )
        return self._unwrap_text(payload)

    def relevant_context(
        self,
        *,
        files: list[str],
        depth: int = 1,
        max_tokens: int = 4000,
        include_symbols: bool = True,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/graph/context",
            json={
                "files": files,
                "depth": depth,
                "max_tokens": max_tokens,
                "include_symbols": include_symbols,
            },
        )
        return self._unwrap_text(payload)

    def explore_codebase(
        self,
        *,
        path: str = "",
        max_items: int = 30,
        importance_threshold: float = 0.3,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/explore",
            json={
                "path": path,
                "max_items": max_items,
                "importance_threshold": importance_threshold,
            },
        )
        return self._unwrap_text(payload)

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        file_filter: str = "",
        branch: str = "",
        mode: str = "auto",
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/search",
            json={
                "query": query,
                "top_k": top_k,
                "file_filter": file_filter,
                "mode": mode,
            },
            params={"branch": branch},
        )
        return self._unwrap_text(payload)

    def security_scan(self, mode: str = "full", path: str = "") -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/security-scan",
            json={"mode": mode, "path": path},
        )
        return self._unwrap_text(payload)

    def start_indexing(self) -> dict[str, Any]:
        return self._post_json(f"/api/v1/projects/{self._repo_id}/index")

    def indexing_status(self) -> dict[str, Any]:
        return self._get_json(f"/api/v1/projects/{self._repo_id}/index/status")

    def hydration_status(self) -> dict[str, Any]:
        """Mirror :meth:`CodeIntelService.hydration_status` for MCP remote mode."""
        return self._get_json(f"/api/v1/projects/{self._repo_id}/hydration")

    def semantic_search_status(self) -> str:
        payload = self.indexing_status()
        lines = [
            "Semantic search status:",
            f"  Provider: {payload.get('provider', '')}",
            f"  Available: {payload.get('available', False)}",
            f"  Status: {payload.get('status', 'idle')}",
            (
                "  Coverage: "
                f"{float(payload.get('coverage', 0.0)):.0%} "
                f"({payload.get('indexed_files', 0)}/{payload.get('total_files', 0)} files)"
            ),
            f"  Failed: {payload.get('failed_files', 0)}",
            f"  Vector search active: {payload.get('vector_search_active', False)}",
            f"  Health: {payload.get('health_status', 'unknown')}",
        ]
        if payload.get("degraded_reason"):
            lines.append(f"  Degradation reason: {payload['degraded_reason']}")
        if payload.get("last_error"):
            lines.append(f"  Last error: {payload['last_error']}")
        if payload.get("elapsed_seconds", 0):
            lines.append(f"  Elapsed: {float(payload['elapsed_seconds']):.1f}s")
        return "\n".join(lines)

    def dead_code(
        self,
        *,
        scope: str = "",
        entry_points: list[str] | None = None,
        level: str = "symbol",
        min_confidence: float = 0.5,
        top_n: int = 30,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/dead-code",
            json={
                "scope": scope,
                "entry_points": entry_points,
                "level": level,
                "min_confidence": min_confidence,
                "top_n": top_n,
            },
        )
        return self._unwrap_text(payload)

    def distill(
        self,
        *,
        files: list[str] | None = None,
        depth: int = 1,
        level: str = "signatures",
        max_tokens: int = 4000,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/distill",
            json={
                "files": files,
                "depth": depth,
                "level": level,
                "max_tokens": max_tokens,
            },
        )
        return self._unwrap_text(payload)

    def readiness_report(
        self,
        *,
        phases: list[int] | None = None,
        scope: str = "",
        tracer_bullets: bool = True,
        min_severity: str = "info",
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/readiness-report",
            json={
                "phases": phases,
                "scope": scope,
                "tracer_bullets": tracer_bullets,
                "min_severity": min_severity,
            },
        )
        return self._unwrap_text(payload)

    def bug_scan(self, *, base_branch: str = "main", min_confidence: float = 0.5) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/bug-scan",
            json={"base_branch": base_branch, "min_confidence": min_confidence},
        )
        return self._unwrap_text(payload)

    def fast_search(
        self,
        *,
        pattern: str,
        path: str = "",
        max_results: int = 50,
        case_insensitive: bool = False,
        selectivity_threshold: float = 0.10,
        explain: bool = False,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/fast-search",
            json={
                "pattern": pattern,
                "path": path,
                "max_results": max_results,
                "case_insensitive": case_insensitive,
                "selectivity_threshold": selectivity_threshold,
                "explain": explain,
            },
        )
        return self._unwrap_text(payload)

    async def lsp_definition(self, file: str, line: int, col: int = 0) -> str:
        import httpx

        async with httpx.AsyncClient(base_url=self._server, headers=self._headers, timeout=30) as client:
            resp = await client.post(
                f"/api/v1/projects/{self._repo_id}/lsp/definition",
                json={"file": file, "line": line, "col": col},
            )
            resp.raise_for_status()
            return self._unwrap_text(resp.json())

    async def lsp_references(
        self, file: str, line: int, col: int = 0, include_declaration: bool = True,
    ) -> str:
        import httpx

        async with httpx.AsyncClient(base_url=self._server, headers=self._headers, timeout=30) as client:
            resp = await client.post(
                f"/api/v1/projects/{self._repo_id}/lsp/references",
                json={
                    "file": file,
                    "line": line,
                    "col": col,
                    "include_declaration": include_declaration,
                },
            )
            resp.raise_for_status()
            return self._unwrap_text(resp.json())

    async def lsp_hover(self, file: str, line: int, col: int = 0) -> str:
        import httpx

        async with httpx.AsyncClient(base_url=self._server, headers=self._headers, timeout=30) as client:
            resp = await client.post(
                f"/api/v1/projects/{self._repo_id}/lsp/hover",
                json={"file": file, "line": line, "col": col},
            )
            resp.raise_for_status()
            return self._unwrap_text(resp.json())

    async def lsp_enrich(self, files: list[str]) -> str:
        import httpx

        async with httpx.AsyncClient(base_url=self._server, headers=self._headers, timeout=30) as client:
            resp = await client.post(
                f"/api/v1/projects/{self._repo_id}/lsp/enrich",
                json={"files": files},
            )
            resp.raise_for_status()
            return self._unwrap_text(resp.json())

    def lsp_diagnostics(self, file: str) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/lsp/diagnostics",
            params={"file": file},
        )
        return self._unwrap_text(payload)

    def code_evolution(
        self, path: str, symbol: str = "", since: str = "", max_results: int = 20,
    ) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/history/evolution",
            params={"path": path, "symbol": symbol, "since": since, "max_results": max_results},
        )
        return self._unwrap_text(payload)

    def recent_changes(self, days: int = 7, path: str = "", top_n: int = 20) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/history/recent-changes",
            params={"days": days, "path": path, "top_n": top_n},
        )
        return self._unwrap_text(payload)

    def change_coupling(
        self,
        *,
        file: str,
        days: int = 90,
        min_coupling: float = 0.3,
        top_k: int = 20,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/history/change-coupling",
            json={
                "file": file,
                "days": days,
                "min_coupling": min_coupling,
                "top_k": top_k,
            },
        )
        return self._unwrap_text(payload)

    def churn_hotspots(self, *, days: int = 90, top_n: int = 20) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/history/churn-hotspots",
            params={"days": days, "top_n": top_n},
        )
        return self._unwrap_text(payload)

    def merge_risk(self, *, files: list[str], days: int = 90) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/history/merge-risk",
            json={"files": files, "days": days},
        )
        return self._unwrap_text(payload)

    def recall(self, query: str, scope: str = "", max_results: int = 10) -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/learnings/recall",
            params={"query": query, "scope": scope, "max_results": max_results},
        )
        return self._unwrap_text(payload)

    def record_learning(
        self,
        *,
        type: str,  # noqa: A002
        description: str,
        details: str = "",
        scope: str = "",
        confidence: float = 0.7,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/learnings",
            json={
                "type": type,
                "description": description,
                "details": details,
                "scope": scope,
                "confidence": confidence,
            },
        )
        return self._unwrap_text(payload)

    def learning_feedback(self, learning_id: int, helpful: bool) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/learnings/{learning_id}/feedback",
            json={"helpful": helpful},
        )
        return self._unwrap_text(payload)

    def list_learnings(self, status: str = "active", type: str = "", scope: str = "") -> str:  # noqa: A002
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/learnings",
            params={"status": status, "type": type, "scope": scope},
        )
        return self._unwrap_text(payload)

    def record_adr(
        self,
        *,
        title: str,
        context: str,
        decision: str,
        consequences: str = "",
        related_files: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/adrs",
            json={
                "title": title,
                "context": context,
                "decision": decision,
                "consequences": consequences,
                "related_files": related_files,
                "tags": tags,
            },
        )
        return self._unwrap_text(payload)

    def list_adrs(self, status: str = "", tag: str = "", search: str = "") -> str:
        payload = self._get_json(
            f"/api/v1/projects/{self._repo_id}/adrs",
            params={"status": status, "tag": tag, "search": search},
        )
        return self._unwrap_text(payload)

    def get_adr(self, number: int) -> str:
        payload = self._get_json(f"/api/v1/projects/{self._repo_id}/adrs/{number}")
        return self._unwrap_text(payload)

    def update_adr_status(self, *, number: int, status: str, superseded_by: int | None = None) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/adrs/{number}/status",
            json={"status": status, "superseded_by": superseded_by},
        )
        return self._unwrap_text(payload)

    def notify_file_changed(self, files: list[str]) -> str:
        payload = self._post_json(
            f"/api/v1/projects/{self._repo_id}/notify",
            json={"files": files},
        )
        return self._unwrap_text(payload)


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
            params["dir"] = directory
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/search-symbols",
            params=params,
        )

    async def cross_references(self, symbol: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/cross-refs",
            params={"symbol": symbol, "branch": branch},
        )

    async def impact_analysis(self, files: list[str], branch: str) -> dict:
        params: list[tuple[str, str]] = [("branch", branch)] if branch else []
        params.extend(("files", item) for item in files)
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/impact",
            params=params,
        )

    async def dependency_graph(self, start_file: str, depth: int, branch: str, directory: str = "") -> dict:
        payload: dict[str, Any] = {"start_file": start_file, "depth": depth}
        if directory:
            payload["directory"] = directory
        return await self._client.post(
            f"/api/v2/projects/{self._client.repo_id}/dependency-graph",
            json=payload,
            params={"branch": branch},
        )

    async def dependencies(self, path: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/dependencies",
            params={"path": path, "branch": branch},
        )

    async def file_analysis(self, path: str, branch: str) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/file-analysis",
            params={"path": path, "branch": branch},
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
        payload: dict[str, Any] = {"query": query, "top_k": top_k, "file_filter": file_filter}
        return await self._client.post(
            f"/api/v2/projects/{self._client.repo_id}/search",
            json=payload,
            params={"branch": branch},
        )

    async def security_scan(self, mode: str, path: str, branch: str) -> dict:
        return await self._client.post(
            f"/api/v2/projects/{self._client.repo_id}/security-scan",
            json={"mode": mode, "path": path},
            params={"branch": branch},
        )


class RemoteGraphProvider:
    """Proxy graph requests through the remote HTTP API."""

    __slots__ = ("_client",)

    def __init__(self, client: RemoteClient) -> None:
        self._client = client

    async def graph_query(self, file: str, edge_type: str, direction: str, depth: int, branch: str) -> dict:
        return await self._client.post(
            f"/api/v2/projects/{self._client.repo_id}/graph/query",
            json={"file": file, "edge_type": edge_type, "direction": direction, "depth": depth},
            params={"branch": branch},
        )

    async def find_related(self, file: str, top_k: int, branch: str) -> dict:
        return await self._client.post(
            f"/api/v2/projects/{self._client.repo_id}/graph/related",
            json={"file": file, "top_k": top_k},
            params={"branch": branch},
        )

    async def community_detection(self, branch: str, min_community_size: int, max_communities: int) -> dict:
        return await self._client.get(
            f"/api/v2/projects/{self._client.repo_id}/graph/communities",
            params={"branch": branch, "min_community_size": min_community_size, "max_communities": max_communities},
        )
