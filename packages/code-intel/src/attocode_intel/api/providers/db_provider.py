"""Service-mode providers — query Postgres DB directly."""

from __future__ import annotations

import logging
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from attocode_intel.api.deps import BranchContext
    from attocode_intel.api.models import FindRelatedResponse, GraphQueryResponse

from attocode_intel.api.models import (
    CodeChunkItem,
    CommunityItem,
    CommunityResponse,
    ConventionsResponse,
    ConventionStats,
    CrossRefResponse,
    DependencyGraphEdge,
    DependencyGraphNode,
    DependencyGraphResponse,
    DependencyResponse,
    FileAnalysisResponse,
    FileMetricsItem,
    HotspotsResponse,
    ImpactAnalysisResponse,
    LSPDefinitionResponse,
    LSPDiagnosticsResponse,
    LSPHoverResponse,
    LSPLocation,
    LSPReferencesResponse,
    ReferenceItem,
    SearchResultItem,
    SearchResultsResponse,
    SecurityFinding,
    SecurityScanResponse,
    SymbolItem,
    SymbolListResponse,
    SymbolSearchResponse,
)

logger = logging.getLogger(__name__)


class DbAnalysisProvider:
    """DB-backed analysis provider for service mode."""

    __slots__ = ("_project_id",)

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def symbols(self, path: str, branch: str) -> SymbolListResponse:
        from sqlalchemy import select

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.db.models import Symbol

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            manifest = branch_ctx.manifest

            if path:
                content_sha = manifest.get(path)
                if not content_sha:
                    return SymbolListResponse(path=path, symbols=[])
                result = await session.execute(
                    select(Symbol).where(Symbol.content_sha == content_sha)
                )
            else:
                shas = set(manifest.values())
                if not shas:
                    return SymbolListResponse(path="", symbols=[])
                result = await session.execute(
                    select(Symbol).where(Symbol.content_sha.in_(shas))
                )

            rows = result.scalars().all()
            sha_to_path = branch_ctx.sha_to_path
            items = [
                SymbolItem(
                    name=s.name,
                    kind=s.kind,
                    file_path=sha_to_path.get(s.content_sha, ""),
                    start_line=s.line_start or 0,
                    end_line=s.line_end or 0,
                    signature=s.signature or "",
                )
                for s in rows
            ]
            return SymbolListResponse(path=path, symbols=items)

        return SymbolListResponse(path=path, symbols=[])

    async def search_symbols(self, name: str, branch: str, directory: str = "") -> SymbolSearchResponse:
        from sqlalchemy import select

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.db.models import Symbol

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            shas = branch_ctx.content_shas
            if not shas:
                return SymbolSearchResponse(query=name, definitions=[])

            result = await session.execute(
                select(Symbol)
                .where(
                    Symbol.content_sha.in_(shas),
                    Symbol.name.ilike(f"%{name}%"),
                )
                .limit(100)
            )
            rows = result.scalars().all()
            sha_to_path = branch_ctx.sha_to_path
            items = [
                SymbolItem(
                    name=s.name,
                    kind=s.kind,
                    file_path=sha_to_path.get(s.content_sha, ""),
                    start_line=s.line_start or 0,
                    end_line=s.line_end or 0,
                    signature=s.signature or "",
                )
                for s in rows
            ]
            if directory:
                items = [s for s in items if s.file_path.startswith(directory)]
            return SymbolSearchResponse(query=name, definitions=items)

        return SymbolSearchResponse(query=name, definitions=[])

    async def cross_references(self, symbol_name: str, branch: str) -> CrossRefResponse:
        from itertools import islice

        from sqlalchemy import or_, select

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.db.models import Symbol, SymbolReference

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            content_shas = branch_ctx.content_shas
            if not content_shas:
                return CrossRefResponse(
                    symbol=symbol_name, definitions=[], references=[], total_references=0
                )

            result = await session.execute(
                select(Symbol).where(Symbol.content_sha.in_(content_shas))
            )
            rows = result.scalars().all()
            sha_to_paths: dict[str, list[str]] = {}
            for path, sha in sorted(branch_ctx.manifest.items()):
                sha_to_paths.setdefault(sha, []).append(path)

            definitions = [
                SymbolItem(
                    name=s.name,
                    kind=s.kind,
                    file_path=path,
                    start_line=s.line_start or 0,
                    end_line=s.line_end or 0,
                    signature=s.signature or "",
                )
                for s in rows
                for path in sha_to_paths.get(s.content_sha, [])
                if s.name == symbol_name or s.name.endswith(f".{symbol_name}")
            ]

            ref_result = await session.execute(
                select(SymbolReference)
                .where(
                    SymbolReference.content_sha.in_(content_shas),
                    or_(
                        SymbolReference.symbol_name == symbol_name,
                        SymbolReference.symbol_name.endswith(f".{symbol_name}"),
                    ),
                )
                .order_by(SymbolReference.content_sha, SymbolReference.line, SymbolReference.id)
                .limit(500)
            )
            ref_rows = ref_result.scalars().all()
            references = list(islice((
                ReferenceItem(
                    ref_kind=r.ref_kind,
                    symbol=r.symbol_name,
                    caller_qualified_name=r.caller_qualified_name,
                    file_path=path,
                    line=r.line,
                )
                for r in ref_rows
                for path in sha_to_paths.get(r.content_sha, [])
            ), 500))

            return CrossRefResponse(
                symbol=symbol_name,
                definitions=definitions,
                references=references,
                total_references=len(references),
            )

        return CrossRefResponse(
            symbol=symbol_name, definitions=[], references=[], total_references=0
        )

    async def impact_analysis(self, files: list[str], branch: str) -> ImpactAnalysisResponse:
        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.api.models import ImpactLayer
        from attocode_intel.db.engine import get_session

        async for session in get_session():
            branch_ctx = await get_branch_context(uuid.UUID(self._project_id), branch, session)
            # Content hashes identify bytes, not import destinations. An unchanged
            # importer may target different bytes on another branch or after an edit.
            # Resolve current branch paths rather than following stale cached SHAs.
            edges = await self._compute_import_edges(session, branch_ctx)
            reverse: dict[str, set[str]] = {}
            for edge in edges:
                reverse.setdefault(edge["target"], set()).add(edge["source"])
            changed = set(files) & set(branch_ctx.manifest)
            visited = set(changed)
            frontier = set(changed)
            layers: list[ImpactLayer] = []
            depth = 0
            while frontier:
                depth += 1
                following = set().union(*(reverse.get(path, set()) for path in frontier)) - visited
                if following:
                    layers.append(ImpactLayer(depth=depth, files=sorted(following)))
                visited.update(following)
                frontier = following
            # Nearest dependents first, so budget trimming drops the farthest files.
            impacted = [path for layer in layers for path in layer.files]
            return ImpactAnalysisResponse(
                changed_files=files, impacted_files=impacted,
                total_impacted=len(impacted), layers=layers,
            )
        return ImpactAnalysisResponse(changed_files=files, impacted_files=[], total_impacted=0)

    async def dependency_graph(
        self, start_file: str, depth: int, branch: str, directory: str = "",
    ) -> DependencyGraphResponse:
        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.storage.dependency_store import DependencyStore

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            dep_store = DependencyStore(session)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            raw = await dep_store.get_graph_for_branch(branch_ctx.branch_id)

            raw_nodes = raw.get("nodes", [])
            raw_edges = raw.get("edges", [])

            # Fallback: compute edges on-the-fly from import extraction
            # when the Dependency table is empty but we have files
            if not raw_edges and raw_nodes:
                raw_edges = await self._compute_import_edges(session, branch_ctx)

            if start_file:
                adj: dict[str, list[str]] = {}
                for e in raw_edges:
                    adj.setdefault(e["source"], []).append(e["target"])
                    adj.setdefault(e["target"], []).append(e["source"])

                # Resolve start_file: exact match or directory prefix
                if start_file in adj:
                    seeds = {start_file}
                else:
                    prefix = start_file.rstrip("/") + "/"
                    seeds = {n["path"] for n in raw_nodes if n["path"].startswith(prefix)}

                if not seeds:
                    return DependencyGraphResponse(nodes=[], edges=[])

                reachable: set[str] = set()
                bfs_frontier = seeds
                for _ in range(depth):
                    next_frontier: set[str] = set()
                    for f in bfs_frontier:
                        if f not in reachable:
                            reachable.add(f)
                            next_frontier.update(adj.get(f, []))
                    bfs_frontier = next_frontier - reachable
                reachable.update(bfs_frontier)

                raw_nodes = [n for n in raw_nodes if n["path"] in reachable]
                raw_edges = [
                    e for e in raw_edges
                    if e["source"] in reachable and e["target"] in reachable
                ]

            nodes = [
                DependencyGraphNode(id=n["path"], label=n["path"], type="file")
                for n in raw_nodes
            ]
            edges = [
                DependencyGraphEdge(
                    source=e["source"], target=e["target"],
                    type=e.get("type", "import"),
                )
                for e in raw_edges
            ]

            # Filter by directory prefix if specified
            if directory:
                node_ids = {n.id for n in nodes if n.id.startswith(directory)}
                nodes = [n for n in nodes if n.id in node_ids]
                edges = [e for e in edges if e.source in node_ids and e.target in node_ids]

            return DependencyGraphResponse(nodes=nodes, edges=edges)

        return DependencyGraphResponse(nodes=[], edges=[])

    async def _compute_import_edges(self, session: AsyncSession, branch_ctx: BranchContext) -> list[dict]:
        """Resolve supported imports against current paths; read content in bounded batches.

        This is syntactic Python/JS/TS import reachability, not proof of semantic
        impact. No arbitrary first-500-file cutoff or SHA-to-single-path collapse.
        """
        from sqlalchemy import select

        from attocode_intel._internal.integrations.context.codebase_context import (
            python_module_index,
        )
        from attocode_intel.db.models import FileContent
        from attocode_intel.indexing.full_indexer import _load_path_aliases, _resolve_import_path
        from attocode_intel.indexing.parser import detect_language, extract_imports

        manifest = branch_ctx.manifest
        known_paths = set(manifest)
        python_index = python_module_index(known_paths)
        sha_to_paths: dict[str, list[str]] = {}
        aliases: dict[str, str] = {}
        for path, sha in sorted(manifest.items()):
            if path.endswith(("tsconfig.json", "jsconfig.json")):
                content = await session.scalar(select(FileContent.content).where(FileContent.sha256 == sha))
                if content:
                    aliases.update(_load_path_aliases({path}, {path: content}))
            if detect_language(path) in ("python", "javascript", "typescript"):
                sha_to_paths.setdefault(sha, []).append(path)
        shas = sorted(sha_to_paths)
        edges: list[dict] = []
        for offset in range(0, len(shas), 32):
            # Indexed files are capped at 1 MB; do not load an entire repository's bodies.
            result = await session.execute(select(FileContent.sha256, FileContent.content).where(
                FileContent.sha256.in_(shas[offset:offset + 32])))
            for sha, content in result:
                if content is None:
                    continue
                for source in sha_to_paths[sha]:
                    language = detect_language(source)
                    imports = extract_imports(content, source, language)
                    targets = {_resolve_import_path(imp, source, known_paths, language,
                                                     aliases=aliases, python_index=python_index)
                               for imp in imports}
                    for target in sorted(t for t in targets if t and t != source):
                        edges.append({"source": source, "target": target, "type": "import", "weight": 1.0})
        return edges

    async def hotspots(self, branch: str, top_n: int) -> HotspotsResponse:
        from sqlalchemy import func as sa_func
        from sqlalchemy import select

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.db.models import Dependency, FileContent, Symbol

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            content_shas = branch_ctx.content_shas

            if not content_shas:
                return HotspotsResponse(file_hotspots=[], function_hotspots=[], orphan_files=[])

            sym_result = await session.execute(
                select(Symbol.content_sha, sa_func.count())
                .where(Symbol.content_sha.in_(content_shas))
                .group_by(Symbol.content_sha)
            )
            sym_counts: dict[str, int] = dict(sym_result.all())

            fan_out_result = await session.execute(
                select(Dependency.source_sha, sa_func.count())
                .where(Dependency.source_sha.in_(content_shas), Dependency.target_sha.in_(content_shas))
                .group_by(Dependency.source_sha)
            )
            fan_out: dict[str, int] = dict(fan_out_result.all())

            fan_in_result = await session.execute(
                select(Dependency.target_sha, sa_func.count())
                .where(Dependency.source_sha.in_(content_shas), Dependency.target_sha.in_(content_shas))
                .group_by(Dependency.target_sha)
            )
            fan_in: dict[str, int] = dict(fan_in_result.all())

            size_result = await session.execute(
                select(FileContent.sha256, FileContent.size_bytes)
                .where(FileContent.sha256.in_(content_shas))
            )
            file_sizes: dict[str, int] = dict(size_result.all())

            # The two maps have different key sets and iteration orders. Match
            # both counts to the same file, and compute maxima once per request.
            max_sym = max(sym_counts.values(), default=1) or 1
            max_conn = max((fan_in.get(sha, 0) + fan_out.get(sha, 0) for sha in content_shas), default=1) or 1
            max_size = max(file_sizes.values(), default=1) or 1
            max_lines = max(max_size // 40, 1)
            items: list[FileMetricsItem] = []
            # Distinct paths sharing content are still distinct files in the UI.
            for path, sha in branch_ctx.manifest.items():
                sc = sym_counts.get(sha, 0)
                fi = fan_in.get(sha, 0)
                fo = fan_out.get(sha, 0)
                size = file_sizes.get(sha, 0)
                lines = max(size // 40, 1) if size > 0 else 0
                composite = (
                    0.3 * (sc / max(max_sym, 1))
                    + 0.3 * ((fi + fo) / max(max_conn, 1))
                    + 0.2 * (lines / max(max_lines, 1))
                    + 0.2 * (size / max(max_size, 1))
                )
                items.append(FileMetricsItem(
                    path=path,
                    line_count=lines,
                    symbol_count=sc,
                    fan_in=fi,
                    fan_out=fo,
                    density=round(sc / max(lines, 1), 3),
                    composite=round(composite, 4),
                ))

            items.sort(key=lambda x: (-x.composite, x.path))
            return HotspotsResponse(
                file_hotspots=items[:top_n],
                function_hotspots=[],
                orphan_files=[],
            )

        return HotspotsResponse(file_hotspots=[], function_hotspots=[], orphan_files=[])

    async def dependencies(self, path: str, branch: str) -> DependencyResponse:
        """Falls back to CodeIntelService (no DB-specific implementation)."""
        from attocode_intel.api.deps import get_service_or_404

        svc = await get_service_or_404(self._project_id)
        data = svc.dependencies_data(path)
        return DependencyResponse(**data)

    async def file_analysis(self, path: str, branch: str) -> FileAnalysisResponse:
        """Falls back to CodeIntelService (no DB-specific implementation)."""
        from attocode_intel.api.deps import get_service_or_404

        svc = await get_service_or_404(self._project_id)
        data = svc.file_analysis_data(path)
        return FileAnalysisResponse(
            path=data["path"],
            language=data["language"],
            line_count=data["line_count"],
            imports=data["imports"],
            exports=data["exports"],
            chunks=[CodeChunkItem(**c) for c in data["chunks"]],
        )

    async def conventions(
        self, branch: str, sample_size: int, path: str,
    ) -> ConventionsResponse:
        from sqlalchemy import select

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.db.models import Symbol

        snake_re = re.compile(r"^[a-z][a-z0-9_]*$")
        camel_re = re.compile(r"^[a-z][a-zA-Z0-9]*$")

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            manifest = branch_ctx.manifest
            content_shas = branch_ctx.content_shas

            if not content_shas:
                return ConventionsResponse(sample_size=0, path=path, stats=ConventionStats())

            if path:
                filtered_shas = {sha for p, sha in manifest.items() if p.startswith(path)}
            else:
                filtered_shas = content_shas

            if not filtered_shas:
                return ConventionsResponse(sample_size=0, path=path, stats=ConventionStats())

            result = await session.execute(
                select(Symbol).where(Symbol.content_sha.in_(filtered_shas))
            )
            symbols = result.scalars().all()

            total_functions = 0
            total_classes = 0
            snake_names = 0
            camel_names = 0
            typed_return = 0
            async_count = 0

            for s in symbols:
                if s.kind in ("function", "method"):
                    total_functions += 1
                    if snake_re.match(s.name):
                        snake_names += 1
                    elif camel_re.match(s.name) and any(c.isupper() for c in s.name[1:]):
                        camel_names += 1
                    if s.signature and "->" in s.signature:
                        typed_return += 1
                    meta = s.metadata_ or {}
                    if meta.get("async"):
                        async_count += 1
                elif s.kind == "class":
                    total_classes += 1

            stats = ConventionStats(
                total_functions=total_functions,
                total_classes=total_classes,
                snake_names=snake_names,
                camel_names=camel_names,
                typed_return=typed_return,
                async_count=async_count,
            )
            return ConventionsResponse(
                sample_size=len(filtered_shas),
                path=path,
                stats=stats,
            )

        return ConventionsResponse(sample_size=0, path=path, stats=ConventionStats())


class DbSearchProvider:
    """DB-backed search provider for service mode."""

    __slots__ = ("_project_id",)

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def semantic_search(
        self, query: str, top_k: int, file_filter: str, branch: str,
    ) -> SearchResultsResponse:
        """Run pgvector cosine similarity search."""
        import uuid as _uuid

        from attocode_intel._internal.integrations.context.embeddings import (
            create_embedding_provider,
        )
        from attocode_intel.api.deps import get_branch_context, get_config
        from attocode_intel.db.engine import get_session
        from attocode_intel.storage.embedding_store import EmbeddingStore

        config = get_config()
        provider = create_embedding_provider(config.embedding_model)
        if provider.name == "none":
            raise RuntimeError("No embedding provider available")

        query_vectors = provider.embed([query])
        query_vector = query_vectors[0]

        async for session in get_session():
            branch_ctx = await get_branch_context(
                _uuid.UUID(self._project_id), branch, session,
            )

            store = EmbeddingStore(session)
            results = await store.similarity_search(
                branch_id=branch_ctx.branch_id,
                query_vector=query_vector,
                top_k=top_k,
                model=provider.name,
                file_filter=file_filter,
            )

            items = [
                SearchResultItem(
                    file_path=r["file"],
                    score=r.get("score", 0.0),
                    snippet=r.get("chunk_text", ""),
                )
                for r in results
            ]

            # Best-effort line number enrichment from symbols
            query_words = [w for w in query.split() if len(w) >= 3]
            if query_words:
                from sqlalchemy import select as sa_select

                from attocode_intel.db.models import BranchFile, Symbol

                sha_by_file: dict[str, str] = {}
                for r in results:
                    bf_result = await session.execute(
                        sa_select(BranchFile.content_sha).where(
                            BranchFile.branch_id == branch_ctx.branch_id,
                            BranchFile.path == r["file"],
                        ).limit(1)
                    )
                    bf_row = bf_result.first()
                    if bf_row:
                        sha_by_file[r["file"]] = bf_row[0]

                for item in items:
                    sha = sha_by_file.get(item.file_path)
                    if not sha:
                        continue
                    for word in query_words:
                        sym_result = await session.execute(
                            sa_select(Symbol.line_start)
                            .where(Symbol.content_sha == sha)
                            .where(Symbol.name.ilike(f"%{word}%"))
                            .limit(1)
                        )
                        row = sym_result.first()
                        if row:
                            item.line = row[0]
                            break

            # Codex M4: populate the ``pin_id`` + ``manifest_hash`` fields
            # so search responses carry the same state-snapshot identifier
            # the local stdio MCP emits via ``_stamp_pin``.
            from attocode_intel.api.routes._pin_helper import (
                build_retrieval_pin,
            )
            try:
                server_pin = await build_retrieval_pin(
                    session,
                    repo_id=_uuid.UUID(self._project_id),
                    branch_id=branch_ctx.branch_id,
                )
                pin_id = server_pin.pin_id
                manifest_hash = server_pin.manifest_hash
            except Exception:
                pin_id = ""
                manifest_hash = ""

            return SearchResultsResponse(
                query=query,
                results=items,
                total=len(items),
                pin_id=pin_id,
                manifest_hash=manifest_hash,
            )

        raise RuntimeError("No database session available")


    async def security_scan(
        self, mode: str, path: str, branch: str,
    ) -> SecurityScanResponse:
        """DB-backed security scan — runs regex patterns on stored content."""
        import uuid as _uuid

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.storage.security_scanner_db import db_security_scan

        async for session in get_session():
            repo_id = _uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)

            result = await db_security_scan(
                session,
                branch_ctx.branch_id,
                branch_ctx.manifest,
                mode=mode,
                path_filter=path,
            )

            return SecurityScanResponse(
                mode=result["mode"],
                path=result["path"],
                findings=[SecurityFinding(**f) for f in result["findings"]],
                total_findings=result["total_findings"],
                summary=result.get("summary", {}),
            )

        return SecurityScanResponse(
            mode=mode, path=path, findings=[], total_findings=0,
            summary={"error": "No database session available"},
        )


class DbGraphProvider:
    """DB-backed graph provider for service mode."""

    __slots__ = ("_project_id",)

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def graph_query(
        self, file: str, edge_type: str, direction: str, depth: int, branch: str,
    ) -> GraphQueryResponse:
        """Falls back to CodeIntelService (no DB-specific implementation)."""
        from attocode_intel.api.deps import get_service_or_404
        from attocode_intel.api.models import GraphQueryHop, GraphQueryResponse

        svc = await get_service_or_404(self._project_id)
        data = svc.graph_query_data(
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
        """Falls back to CodeIntelService (no DB-specific implementation)."""
        from attocode_intel.api.deps import get_service_or_404
        from attocode_intel.api.models import FindRelatedResponse, RelatedFileItem

        svc = await get_service_or_404(self._project_id)
        data = svc.find_related_data(file=file, top_k=top_k)
        return FindRelatedResponse(
            file=data["file"],
            related=[RelatedFileItem(**r) for r in data["related"]],
        )

    async def community_detection(
        self, branch: str, min_community_size: int, max_communities: int,
    ) -> CommunityResponse:
        import os
        from collections import Counter

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.api.models import CommunityBridge
        from attocode_intel.community import bfs_connected_components, louvain_communities
        from attocode_intel.db.engine import get_session
        from attocode_intel.storage.dependency_store import DependencyStore

        async for session in get_session():
            repo_id = uuid.UUID(self._project_id)
            branch_ctx = await get_branch_context(repo_id, branch, session)
            dep_store = DependencyStore(session)
            raw = await dep_store.get_graph_for_branch(branch_ctx.branch_id)

            raw_edges = raw.get("edges", [])
            all_files: set[str] = {n["path"] for n in raw.get("nodes", [])}

            adj: dict[str, set[str]] = {}
            weights: dict[tuple[str, str], float] = {}
            for e in raw_edges:
                src, tgt = e["source"], e["target"]
                adj.setdefault(src, set()).add(tgt)
                adj.setdefault(tgt, set()).add(src)
                key = (min(src, tgt), max(src, tgt))
                weights[key] = weights.get(key, 0.0) + e.get("weight", 1.0)

            try:
                communities, modularity = louvain_communities(all_files, adj, weights)
                method = "louvain"
            except ImportError:
                communities, modularity = bfs_connected_components(all_files, adj)
                method = "connected_components"

            communities = [c for c in communities if len(c) >= min_community_size]
            communities.sort(key=len, reverse=True)
            communities = communities[:max_communities]

            # Detect trivial results and use directory-based fallback
            is_trivial = len(communities) <= 1 or modularity < 0.05
            if is_trivial:
                # Group files by top-level directory as modules
                dir_groups: dict[str, list[str]] = {}
                for f in all_files:
                    parts = f.split("/")
                    top_dir = parts[0] if len(parts) > 1 else "(root)"
                    dir_groups.setdefault(top_dir, []).append(f)

                fallback_items: list[CommunityItem] = []
                for idx_fb, (dir_name, file_list) in enumerate(
                    sorted(dir_groups.items(), key=lambda x: len(x[1]), reverse=True),
                ):
                    fallback_items.append(CommunityItem(
                        id=idx_fb,
                        files=sorted(file_list),
                        size=len(file_list),
                        theme=dir_name,
                        internal_edges=0,
                        external_edges=0,
                        hub=sorted(file_list)[0] if file_list else "",
                        hub_internal_degree=0,
                        top_dirs=[dir_name],
                    ))

                return CommunityResponse(
                    method=f"{method}+directory-fallback",
                    modularity=round(modularity, 4),
                    communities=fallback_items,
                    bridges=[],
                )

            # Build file-to-community-index mapping
            file_to_comm: dict[str, int] = {}
            items: list[CommunityItem] = []
            for idx, comm in enumerate(communities):
                for f in comm:
                    file_to_comm[f] = idx

                internal = 0
                external = 0
                degree: dict[str, int] = {f: 0 for f in comm}
                for f in comm:
                    for neighbor in adj.get(f, set()):
                        if neighbor in comm:
                            internal += 1
                            degree[f] += 1
                        else:
                            external += 1
                internal //= 2

                hub = max(degree, key=degree.get) if degree else ""  # type: ignore[arg-type]
                hub_deg = degree.get(hub, 0)

                sorted_files = sorted(comm)
                if sorted_files:
                    prefix = sorted_files[0]
                    for f in sorted_files[1:]:
                        while not f.startswith(prefix):
                            prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
                            if not prefix:
                                break
                    theme = prefix.rstrip("/") or "mixed"
                else:
                    theme = ""

                # Compute top directories
                dirs = [os.path.dirname(f) or "(root)" for f in sorted_files]
                top_dirs = [d for d, _ in Counter(dirs).most_common(3)]

                items.append(CommunityItem(
                    id=idx,
                    files=sorted_files,
                    size=len(comm),
                    theme=theme,
                    internal_edges=internal,
                    external_edges=external,
                    hub=hub,
                    hub_internal_degree=hub_deg,
                    top_dirs=top_dirs,
                ))

            # Compute bridges between communities
            bridge_counts: dict[tuple[int, int], int] = {}
            bridge_samples: dict[tuple[int, int], list[str]] = {}
            for e in raw_edges:
                src_comm = file_to_comm.get(e["source"])
                tgt_comm = file_to_comm.get(e["target"])
                if src_comm is None or tgt_comm is None or src_comm == tgt_comm:
                    continue
                key = (min(src_comm, tgt_comm), max(src_comm, tgt_comm))
                bridge_counts[key] = bridge_counts.get(key, 0) + 1
                samples = bridge_samples.setdefault(key, [])
                if len(samples) < 3:
                    samples.append(e["source"])

            bridges = [
                CommunityBridge(
                    source_id=k[0], target_id=k[1],
                    edge_count=v, sample_files=bridge_samples.get(k, []),
                )
                for k, v in sorted(bridge_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            return CommunityResponse(
                method=method, modularity=round(modularity, 4),
                communities=items, bridges=bridges,
            )

        return CommunityResponse(method="none", modularity=0.0, communities=[])


class DbLSPProvider:
    """DB-backed LSP provider for remote repos without a language server.

    Provides best-effort definition/references/hover using the symbol and
    symbol_reference tables. Diagnostics returns empty (requires real LS).
    """

    __slots__ = ("_project_id",)

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def _declaration(self, session, branch_ctx, file, line, col):
        """Only a unique declaration line is supported by this column-free index.

        A containing function is not the symbol under a cursor in its body.
        Never silently substitute that function for an unresolved call site.
        """
        from sqlalchemy import select

        from attocode_intel.db.models import Symbol

        sha = branch_ctx.manifest.get(file)
        if sha is None:
            return None, "File is not indexed on this branch"
        if col != 0:
            return None, "Symbol index has no columns; use col=0 for a declaration line or a language server for cursor resolution"
        result = await session.execute(
            select(Symbol).where(Symbol.content_sha == sha, Symbol.line_start == line).limit(2)
        )
        rows = result.scalars().all()
        if len(rows) != 1:
            return None, ("Ambiguous declaration line" if rows else
                          "Symbol index supports declaration lines only; cursor resolution requires a language server")
        return rows[0], None

    async def definition(self, file: str, line: int, col: int, branch: str) -> LSPDefinitionResponse:
        """Return an indexed declaration, without guessing a same-name target."""
        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session

        async for session in get_session():
            ctx = await get_branch_context(uuid.UUID(self._project_id), branch, session)
            symbol, error = await self._declaration(session, ctx, file, line, col)
            return LSPDefinitionResponse(
                location=LSPLocation(file=file, line=symbol.line_start, col=0) if symbol else None,
                source="symbol_index", error=error,
            )
        return LSPDefinitionResponse(source="symbol_index", error="Index session unavailable")

    async def references(
        self, file: str, line: int, col: int, branch: str, include_declaration: bool = True,
    ) -> LSPReferencesResponse:
        """Return branch-scoped name candidates for a unique indexed declaration."""
        from sqlalchemy import select

        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session
        from attocode_intel.db.models import Symbol, SymbolReference

        async for session in get_session():
            ctx = await get_branch_context(uuid.UUID(self._project_id), branch, session)
            symbol, error = await self._declaration(session, ctx, file, line, col)
            if symbol is None:
                return LSPReferencesResponse(locations=[], total=0, source="symbol_index", error=error)
            result = await session.execute(select(Symbol).where(
                Symbol.content_sha.in_(ctx.content_shas), Symbol.name == symbol.name,
            ).limit(2))
            definitions = result.scalars().all()
            # Content may be reused at multiple paths; those are distinct definitions too.
            if len(definitions) != 1 or sum(sha == symbol.content_sha for sha in ctx.manifest.values()) != 1:
                return LSPReferencesResponse(locations=[], total=0, source="symbol_index",
                                             error="Ambiguous symbol name; reference resolution requires a language server")
            result = await session.execute(select(SymbolReference).where(
                SymbolReference.content_sha.in_(ctx.content_shas),
                SymbolReference.symbol_name == symbol.name,
            ).order_by(SymbolReference.content_sha, SymbolReference.line).limit(501))
            rows = result.scalars().all()
            # Expand identical content at branch paths without retaining an
            # unbounded cross product of paths and references. One extra result
            # detects truncation; ordering is stable across database row order.
            lines_by_sha: dict[str, set[int]] = {}
            for ref in rows[:500]:
                lines_by_sha.setdefault(ref.content_sha, set()).add(ref.line)
            positions = set()
            for path, sha in sorted(ctx.manifest.items()):
                for ref_line in sorted(lines_by_sha.get(sha, ())):
                    positions.add((path, ref_line))
                    if len(positions) > 500:
                        break
                if len(positions) > 500:
                    break
            if include_declaration:
                positions.add((file, symbol.line_start))
            ordered = sorted(positions)
            truncated = len(rows) > 500 or len(ordered) > 500
            locations = [LSPLocation(file=path, line=ref_line, col=0) for path, ref_line in ordered[:500]]
            return LSPReferencesResponse(
                locations=locations, total=len(locations), source="symbol_index",
                note="Name-matched candidates, not resolved references; columns are unavailable (col=0).",
                error="Reference result limit reached; more candidates may exist" if truncated else None,
            )
        return LSPReferencesResponse(locations=[], total=0, source="symbol_index", error="Index session unavailable")

    async def hover(self, file: str, line: int, col: int, branch: str) -> LSPHoverResponse:
        """Display stored declaration metadata, without inferring cursor bindings."""
        from attocode_intel.api.deps import get_branch_context
        from attocode_intel.db.engine import get_session

        async for session in get_session():
            ctx = await get_branch_context(uuid.UUID(self._project_id), branch, session)
            symbol, error = await self._declaration(session, ctx, file, line, col)
            return LSPHoverResponse(
                content=(f"{symbol.kind} {symbol.name}\n{symbol.signature or ''}".rstrip()) if symbol else None,
                file=file, line=line, col=col, source="symbol_index", error=error,
            )
        return LSPHoverResponse(file=file, line=line, col=col, source="symbol_index", error="Index session unavailable")

    async def diagnostics(self, file: str, branch: str) -> LSPDiagnosticsResponse:
        """Unsupported is not evidence that a remote file has no diagnostics."""
        return LSPDiagnosticsResponse(
            file=file, diagnostics=[], total=0,
            error="Diagnostics require a running language server (not available for remote repos)",
        )

    async def completions(self, file: str, line: int, col: int, branch: str, limit: int = 20) -> dict:
        """Completions require a real language server."""
        return {
            "file": file, "line": line, "col": col,
            "completions": [], "total": 0,
            "error": "Completions require a running language server (not available for remote repos)",
        }

    async def workspace_symbol(self, query: str, branch: str, limit: int = 30) -> dict:
        """Workspace symbol search requires a real language server."""
        return {
            "query": query,
            "symbols": [], "total": 0,
            "error": "Workspace symbol search requires a running language server (not available for remote repos)",
        }

    async def incoming_calls(self, file: str, line: int, col: int, branch: str) -> dict:
        """Incoming call hierarchy requires a real language server."""
        return {
            "symbol": "", "file": file, "line": line, "col": col,
            "callers": [], "total": 0,
            "error": "Call hierarchy requires a running language server (not available for remote repos)",
        }

    async def outgoing_calls(self, file: str, line: int, col: int, branch: str) -> dict:
        """Outgoing call hierarchy requires a real language server."""
        return {
            "symbol": "", "file": file, "line": line, "col": col,
            "callees": [], "total": 0,
            "error": "Call hierarchy requires a running language server (not available for remote repos)",
        }
