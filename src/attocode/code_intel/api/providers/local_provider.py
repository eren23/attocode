"""Local-mode providers — wrap CodeIntelService._data() methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

from attocode.code_intel.api.deps import ensure_branch_supported
from attocode.code_intel.api.models import (
    CodeChunkItem,
    CommunityItem,
    CommunityResponse,
    ConventionsResponse,
    ConventionStats,
    CrossRefResponse,
    DependencyGraphResponse,
    DependencyResponse,
    FileAnalysisResponse,
    FileMetricsItem,
    FindRelatedResponse,
    FunctionMetricsItem,
    GraphQueryHop,
    GraphQueryResponse,
    HotspotsResponse,
    ImpactAnalysisResponse,
    LSPCompletionItem,
    LSPCompletionsResponse,
    LSPDefinitionResponse,
    LSPDiagnosticItem,
    LSPDiagnosticsResponse,
    LSPHoverResponse,
    LSPIncomingCallItem,
    LSPIncomingCallsResponse,
    LSPLocation,
    LSPOutgoingCallItem,
    LSPOutgoingCallsResponse,
    LSPReferencesResponse,
    LSPWorkspaceSymbolItem,
    LSPWorkspaceSymbolResponse,
    ReferenceItem,
    RelatedFileItem,
    SearchResultItem,
    SearchResultsResponse,
    SecurityFinding,
    SecurityScanResponse,
    SymbolItem,
    SymbolListResponse,
    SymbolSearchResponse,
)

if TYPE_CHECKING:
    from attocode.code_intel.service import CodeIntelService


class LocalAnalysisProvider:
    """Wraps CodeIntelService for analysis endpoints in local/CLI mode."""

    __slots__ = ("_svc",)

    def __init__(self, svc: CodeIntelService) -> None:
        self._svc = svc

    async def symbols(self, path: str, branch: str) -> SymbolListResponse:
        ensure_branch_supported(branch)
        data = self._svc.symbols_data(path)
        return SymbolListResponse(
            path=path,
            symbols=[SymbolItem(**s) for s in data],
        )

    async def search_symbols(self, name: str, branch: str, directory: str = "") -> SymbolSearchResponse:
        ensure_branch_supported(branch)
        data = self._svc.search_symbols_data(name)
        items = [SymbolItem(**s) for s in data]
        if directory:
            items = [s for s in items if s.file_path.startswith(directory)]
        return SymbolSearchResponse(
            query=name,
            definitions=items,
        )

    async def cross_references(self, symbol: str, branch: str) -> CrossRefResponse:
        ensure_branch_supported(branch)
        data = self._svc.cross_references_data(symbol)
        return CrossRefResponse(
            symbol=data["symbol"],
            definitions=[SymbolItem(**d) for d in data["definitions"]],
            references=[ReferenceItem(**r) for r in data["references"]],
            total_references=data["total_references"],
        )

    async def impact_analysis(self, files: list[str], branch: str) -> ImpactAnalysisResponse:
        ensure_branch_supported(branch)
        data = self._svc.impact_analysis_data(files)
        from attocode.code_intel.api.models import ImpactLayer

        return ImpactAnalysisResponse(
            changed_files=data["changed_files"],
            impacted_files=data["impacted_files"],
            total_impacted=data["total_impacted"],
            layers=[ImpactLayer(**layer) for layer in data.get("layers", [])],
        )

    async def dependency_graph(
        self, start_file: str, depth: int, branch: str, directory: str = "",
    ) -> DependencyGraphResponse:
        ensure_branch_supported(branch)
        data = self._svc.dependency_graph_data(start_file, depth=depth)
        # dependency_graph_data returns {start_file, depth, forward, reverse}
        # Convert to nodes/edges format for DependencyGraphResponse
        from attocode.code_intel.api.models import DependencyGraphEdge, DependencyGraphNode

        seen: set[str] = set()
        nodes: list[DependencyGraphNode] = []
        edges: list[DependencyGraphEdge] = []
        root = data["start_file"]

        # Add root node
        seen.add(root)
        nodes.append(DependencyGraphNode(id=root, label=root, type="file"))

        # Forward deps (imports from start_file)
        for entry in data.get("forward", []):
            p = entry["path"]
            if p not in seen:
                seen.add(p)
                nodes.append(DependencyGraphNode(id=p, label=p, type="file"))
            edges.append(DependencyGraphEdge(source=root, target=p, type="import"))

        # Reverse deps (files that import start_file)
        for entry in data.get("reverse", []):
            p = entry["path"]
            if p not in seen:
                seen.add(p)
                nodes.append(DependencyGraphNode(id=p, label=p, type="file"))
            edges.append(DependencyGraphEdge(source=p, target=root, type="import"))

        # Filter by directory prefix if specified
        if directory:
            node_ids = {n.id for n in nodes if n.id.startswith(directory)}
            nodes = [n for n in nodes if n.id in node_ids]
            edges = [e for e in edges if e.source in node_ids and e.target in node_ids]

        return DependencyGraphResponse(nodes=nodes, edges=edges)

    async def dependencies(self, path: str, branch: str) -> DependencyResponse:
        ensure_branch_supported(branch)
        data = self._svc.dependencies_data(path)
        return DependencyResponse(**data)

    async def file_analysis(self, path: str, branch: str) -> FileAnalysisResponse:
        ensure_branch_supported(branch)
        data = self._svc.file_analysis_data(path)
        return FileAnalysisResponse(
            path=data["path"],
            language=data["language"],
            line_count=data["line_count"],
            imports=data["imports"],
            exports=data["exports"],
            chunks=[CodeChunkItem(**c) for c in data["chunks"]],
        )

    async def hotspots(self, branch: str, top_n: int) -> HotspotsResponse:
        ensure_branch_supported(branch)
        data = self._svc.hotspots_data(top_n=top_n)
        return HotspotsResponse(
            file_hotspots=[FileMetricsItem(**f) for f in data["file_hotspots"]],
            function_hotspots=[FunctionMetricsItem(**f) for f in data["function_hotspots"]],
            orphan_files=[FileMetricsItem(**f) for f in data["orphan_files"]],
        )

    async def conventions(
        self, branch: str, sample_size: int, path: str,
    ) -> ConventionsResponse:
        ensure_branch_supported(branch)
        data = self._svc.conventions_data(sample_size=sample_size, path=path)
        return ConventionsResponse(
            sample_size=data["sample_size"],
            path=data["path"],
            stats=ConventionStats(**data["stats"]) if data["stats"] else ConventionStats(),
            dir_stats={
                k: ConventionStats(**v) for k, v in data.get("dir_stats", {}).items()
            },
        )


class LocalSearchProvider:
    """Wraps CodeIntelService for search endpoints in local/CLI mode."""

    __slots__ = ("_svc",)

    def __init__(self, svc: CodeIntelService) -> None:
        self._svc = svc

    async def semantic_search(
        self, query: str, top_k: int, file_filter: str, branch: str,
    ) -> SearchResultsResponse:
        ensure_branch_supported(branch)
        data = self._svc.semantic_search_data(
            query=query, top_k=top_k, file_filter=file_filter,
        )
        # Codex M4 (round 3): produce a pin compatible with the stdio
        # MCP's ``_stamp_pin`` footer so local-mode HTTP clients see the
        # same round-trippable state identifier. We import from the
        # MCP-free ``pin_store`` module — NOT ``pin_tools`` — because
        # ``pin_tools`` transitively imports ``_shared``, whose module
        # body calls ``sys.exit(1)`` when ``mcp`` is unavailable and
        # that ``SystemExit`` would escape any ``except Exception``.
        # The pin is actually persisted via ``PinStore.save()`` so
        # ``pin_resolve(pin_id)`` works end-to-end.
        #
        # Codex round-4 fix P2 #2: pass the bound service's
        # ``project_dir`` explicitly. Without this the pin would be
        # minted from ``ATTOCODE_PROJECT_DIR``/cwd, so an HTTP server
        # registering multiple projects via ``register_project`` would
        # persist pins into the wrong repo's ``.attocode/cache/pins.db``
        # and ``pin_resolve(resp.pin_id)`` would round-trip to unrelated
        # state.
        pin_id = ""
        manifest_hash = ""
        try:
            from attocode.code_intel.tools.pin_store import (
                compute_and_persist_pin,
            )
            server_pin = compute_and_persist_pin(
                self._svc.project_dir, ttl_seconds=0,
            )
            pin_id = server_pin.pin_id
            manifest_hash = server_pin.manifest_hash
        except Exception:
            pass
        return SearchResultsResponse(
            query=data["query"],
            results=[SearchResultItem(**r) for r in data["results"]],
            total=data["total"],
            pin_id=pin_id,
            manifest_hash=manifest_hash,
        )

    async def security_scan(
        self, mode: str, path: str, branch: str,
    ) -> SecurityScanResponse:
        ensure_branch_supported(branch)
        data = self._svc.security_scan_data(mode=mode, path=path)
        return SecurityScanResponse(
            mode=data["mode"],
            path=data["path"],
            findings=[SecurityFinding(**f) for f in data["findings"]],
            total_findings=data["total_findings"],
            summary=data.get("summary", {}),
        )


class LocalGraphProvider:
    """Wraps CodeIntelService for graph endpoints in local/CLI mode."""

    __slots__ = ("_svc",)

    def __init__(self, svc: CodeIntelService) -> None:
        self._svc = svc

    async def graph_query(
        self, file: str, edge_type: str, direction: str, depth: int, branch: str,
    ) -> GraphQueryResponse:
        ensure_branch_supported(branch)
        data = self._svc.graph_query_data(
            file=file, edge_type=edge_type, direction=direction, depth=depth,
        )
        return GraphQueryResponse(
            root=data["root"],
            direction=data["direction"],
            depth=data["depth"],
            hops=[GraphQueryHop(**h) for h in data["hops"]],
            total_reachable=data["total_reachable"],
        )

    async def find_related(
        self, file: str, top_k: int, branch: str,
    ) -> FindRelatedResponse:
        ensure_branch_supported(branch)
        data = self._svc.find_related_data(file=file, top_k=top_k)
        return FindRelatedResponse(
            file=data["file"],
            related=[RelatedFileItem(**r) for r in data["related"]],
        )

    async def community_detection(
        self, branch: str, min_community_size: int, max_communities: int,
    ) -> CommunityResponse:
        ensure_branch_supported(branch)
        import os
        from collections import Counter

        from attocode.code_intel.api.models import CommunityBridge

        data = self._svc.community_detection_data(
            min_community_size=min_community_size,
            max_communities=max_communities,
        )

        # Handle directory-based fallback: convert modules to CommunityItem format
        if "modules" in data:
            fallback_communities = []
            for mod in data["modules"]:
                fallback_communities.append(CommunityItem(
                    id=mod["id"],
                    files=mod["files"],
                    size=mod["file_count"],
                    theme=mod["directory"],
                    internal_edges=0,
                    external_edges=0,
                    hub=mod["key_files"][0]["path"] if mod.get("key_files") else "",
                    hub_internal_degree=0,
                    top_dirs=[mod["directory"]],
                ))
            return CommunityResponse(
                method=data["method"],
                modularity=data["modularity"],
                communities=fallback_communities,
                bridges=[],
            )

        # Build file-to-community-index mapping
        file_to_comm: dict[str, int] = {}
        communities = data["communities"]
        for c in communities:
            for f in c["files"]:
                file_to_comm[f] = c["id"]

        # Compute top_dirs per community
        for c in communities:
            dirs = [os.path.dirname(f) or "(root)" for f in c["files"]]
            top = [d for d, _ in Counter(dirs).most_common(3)]
            c["top_dirs"] = top

        # Compute bridges between communities
        svc = self._svc._get_ast_service()
        idx = svc._index
        bridge_counts: dict[tuple[int, int], int] = {}
        bridge_samples: dict[tuple[int, int], list[str]] = {}
        for src, deps in idx.file_dependencies.items():
            src_comm = file_to_comm.get(src)
            if src_comm is None:
                continue
            for tgt in deps:
                tgt_comm = file_to_comm.get(tgt)
                if tgt_comm is None or tgt_comm == src_comm:
                    continue
                key = (min(src_comm, tgt_comm), max(src_comm, tgt_comm))
                bridge_counts[key] = bridge_counts.get(key, 0) + 1
                samples = bridge_samples.setdefault(key, [])
                if len(samples) < 3:
                    samples.append(src)

        bridges = [
            CommunityBridge(
                source_id=k[0], target_id=k[1],
                edge_count=v, sample_files=bridge_samples.get(k, []),
            )
            for k, v in sorted(bridge_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        return CommunityResponse(
            method=data["method"],
            modularity=data["modularity"],
            communities=[CommunityItem(**c) for c in communities],
            bridges=bridges,
        )


class LocalLSPProvider:
    """Wraps CodeIntelService for LSP endpoints in local/CLI mode."""

    __slots__ = ("_svc",)

    def __init__(self, svc: CodeIntelService) -> None:
        self._svc = svc

    async def definition(
        self, file: str, line: int, col: int, branch: str,
    ) -> LSPDefinitionResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_definition_data(file=file, line=line, col=col)
        loc = data.get("location")
        return LSPDefinitionResponse(
            location=LSPLocation(**loc) if loc else None,
            error=data.get("error"),
        )

    async def references(
        self, file: str, line: int, col: int,
        include_declaration: bool, branch: str,
    ) -> LSPReferencesResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_references_data(
            file=file, line=line, col=col,
            include_declaration=include_declaration,
        )
        return LSPReferencesResponse(
            locations=[LSPLocation(**loc) for loc in data["locations"]],
            total=data["total"],
            error=data.get("error"),
        )

    async def hover(
        self, file: str, line: int, col: int, branch: str,
    ) -> LSPHoverResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_hover_data(file=file, line=line, col=col)
        return LSPHoverResponse(**data)

    async def diagnostics(
        self, file: str, branch: str,
    ) -> LSPDiagnosticsResponse:
        ensure_branch_supported(branch)
        data = self._svc.lsp_diagnostics_data(file=file)
        return LSPDiagnosticsResponse(
            file=data["file"],
            diagnostics=[LSPDiagnosticItem(**d) for d in data["diagnostics"]],
            total=data["total"],
            error=data.get("error"),
        )

    async def completions(
        self, file: str, line: int, col: int, branch: str, limit: int = 20,
    ) -> LSPCompletionsResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_completions_data(file, line, col, limit)
        return LSPCompletionsResponse(
            file=data["file"],
            line=data["line"],
            col=data["col"],
            completions=[LSPCompletionItem(**c) for c in data["completions"]],
            total=data["total"],
            error=data.get("error"),
        )

    async def workspace_symbol(
        self, query: str, branch: str, limit: int = 30,
    ) -> LSPWorkspaceSymbolResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_workspace_symbol_data(query, limit)
        return LSPWorkspaceSymbolResponse(
            query=data["query"],
            symbols=[LSPWorkspaceSymbolItem(**s) for s in data["symbols"]],
            total=data["total"],
            error=data.get("error"),
        )

    async def incoming_calls(
        self, file: str, line: int, col: int, branch: str,
    ) -> LSPIncomingCallsResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_incoming_calls_data(file, line, col)
        return LSPIncomingCallsResponse(
            symbol=data["symbol"],
            file=data["file"],
            line=data["line"],
            col=data["col"],
            callers=[LSPIncomingCallItem(**c) for c in data["callers"]],
            total=data["total"],
            error=data.get("error"),
        )

    async def outgoing_calls(
        self, file: str, line: int, col: int, branch: str,
    ) -> LSPOutgoingCallsResponse:
        ensure_branch_supported(branch)
        data = await self._svc.lsp_outgoing_calls_data(file, line, col)
        return LSPOutgoingCallsResponse(
            symbol=data["symbol"],
            file=data["file"],
            line=data["line"],
            col=data["col"],
            callees=[LSPOutgoingCallItem(**c) for c in data["callees"]],
            total=data["total"],
            error=data.get("error"),
        )
