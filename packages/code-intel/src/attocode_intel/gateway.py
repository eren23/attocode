"""Shared operation gateway for local and remote MCP/HTTP clients."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from filelock import FileLock
from mcp import types
from mcp.server.lowlevel import Server

from attocode_intel.catalog import INSTRUCTIONS, registered_tools, tool_catalog
from attocode_intel.output import bounded_text
from attocode_intel.request_context import RequestContext, bind_request, resolve_workspace


class OperationGateway:
    def __init__(
        self,
        project: str = "",
        profile: str = "full",
        resolver=None,
        *,
        watch=True,
        watch_debounce=500,
        max_workspaces=8,
    ):
        self.project = project
        self.profile = profile
        self.resolver = resolver
        self._workers = {}
        self._stores = {}
        self.watch, self.watch_debounce = watch, watch_debounce
        self._closed = False
        self.max_workspaces = max(1, max_workspaces)
        self._active = {}
        self._last_used = {}
        self._lifecycle = asyncio.Lock()

    def catalog(self):
        from attocode_intel.remote import remote_profile

        return tool_catalog(
            remote_profile.get() if self.resolver else self.profile, remote=bool(self.resolver)
        )

    async def close(self):
        self._closed = True
        async with self._lifecycle:
            for key in list(self._workers):
                await self._drop_workspace(key)

    async def _drop_workspace(self, key):
        stores, worker = self._stores[key], self._workers[key]
        if watcher := stores.get("watcher"):
            await asyncio.to_thread(watcher.close)
        await asyncio.get_running_loop().run_in_executor(worker, self._close_stores, stores)
        worker.shutdown(wait=True)
        for mapping in (self._workers, self._stores, self._active, self._last_used):
            mapping.pop(key, None)

    async def _acquire_workspace(self, context):
        key = (context.project_dir, context.source)
        async with self._lifecycle:
            if self._closed:
                raise ValueError("Gateway is closed")
            if key not in self._workers:
                if len(self._workers) >= self.max_workspaces:
                    idle = [key for key in self._workers if not self._active[key]]
                    if not idle:
                        raise ValueError(
                            "All workspace slots are busy; retry after an operation completes"
                        )
                    await self._drop_workspace(min(idle, key=self._last_used.get))
                self._workers[key] = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="intel-workspace"
                )
                self._stores[key] = {}
                self._active[key] = 0
            self._active[key] += 1
            self._last_used[key] = time.monotonic()
            return replace(context, stores=self._stores[key])

    @staticmethod
    def _close_stores(stores):
        service = stores.get("service")
        if service:
            if service._ast_service:
                service._ast_service.stop_hydration()
                if service._ast_service._store:
                    service._ast_service._store.close()
            if service._lsp_manager:
                asyncio.run(service._lsp_manager.stop_all())
            for resource in (service._memory_store, service._semantic_search):
                if resource:
                    resource.close()
        for name, resource in stores.items():
            if name not in {"service", "watcher"} and hasattr(resource, "close"):
                resource.close()

    @staticmethod
    def _refresh_sync(context):
        from attocode_intel.freshness import FreshnessTracker

        with bind_request(context):
            directory = Path(context.project_dir) / ".attocode" / "cache"
            directory.mkdir(parents=True, exist_ok=True)
            with FileLock(str(directory / "operations.lock"), timeout=30):
                tracker = context.stores.setdefault(
                    "freshness", FreshnessTracker(context.project_dir)
                )
                tracker.refresh(context.service)

    async def execute(self, name: str, arguments: dict) -> types.CallToolResult:
        if self._closed:
            raise ValueError("Gateway is closed")
        args = dict(arguments)
        workspace = args.pop("workspace", "")
        revision = args.pop("revision", "")
        names = {tool.name for tool in self.catalog()}
        if name not in names:
            raise ValueError(f"Tool {name!r} is not available in profile {self.profile!r}")
        import jsonschema

        schema = next(t.inputSchema for t in self.catalog() if t.name == name)
        jsonschema.validate(arguments, schema)
        if name == "cross_repo_search":
            results = []
            for target in args["workspaces"]:
                response = await self.execute(
                    "semantic_search",
                    {
                        "workspace": target,
                        "query": args["query"],
                        "top_k": args.get("top_k", 10),
                        "mode": "keyword",
                    },
                )
                structured = response.structuredContent
                for rank, match in enumerate(structured["data"]["results"], 1):
                    results.append(
                        {
                            **match,
                            "workspace": structured["metadata"]["workspace"],
                            "revision": structured["metadata"]["revision"],
                            "source": structured["metadata"]["source"],
                            "fusion_score": 1 / (60 + rank),
                        }
                    )
            results.sort(key=lambda row: row["fusion_score"], reverse=True)
            results = results[: args.get("top_k", 10)]
            text, truncated = bounded_text(json.dumps(results), 8000)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
                structuredContent={
                    "data": results,
                    "metadata": {
                        "truncated": truncated,
                        "ranking": "reciprocal_rank",
                        "workspaces": args["workspaces"],
                    },
                },
            )
        if self.resolver:
            context = await self.resolver(workspace, revision, name)
            from attocode_intel.knowledge import KNOWLEDGE_TOOLS, execute_knowledge

            if name in KNOWLEDGE_TOOLS:
                budget = args.pop("max_tokens", 8000)
                data = await execute_knowledge(context, name, args)
                header = f"Source: remote | Workspace: {context.workspace} | Revision: {context.revision}\n"
                text, truncated = bounded_text(header + json.dumps(data), budget)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                    structuredContent={
                        "result": text,
                        "data": data,
                        "metadata": {
                            "workspace": context.workspace,
                            "revision": context.revision,
                            "source": "remote",
                            "truncated": truncated,
                        },
                    },
                )
        else:
            if revision:
                raise ValueError(
                    "Local analysis uses the working tree; revision selection is remote-only."
                )
            path = resolve_workspace(workspace, self.project)
            context = RequestContext(path, path)
        key = (context.project_dir, context.source)
        if self.resolver and name == "bootstrap" and args.get("task_hint"):
            from attocode_intel.knowledge import execute_knowledge

            args["_knowledge"] = await execute_knowledge(
                context, "recall", {"query": args["task_hint"], "max_results": 5}
            )
        context = await self._acquire_workspace(context)
        if self.watch and context.source == "local" and "watcher" not in context.stores:
            from attocode_intel.freshness import WorkspaceWatcher

            context.stores["watcher"] = WorkspaceWatcher(
                context.project_dir,
                lambda: (
                    None if self._closed else self._workers[key].submit(self._refresh_sync, context)
                ),
                self.watch_debounce,
            )
        from contextvars import copy_context

        try:
            return await asyncio.get_running_loop().run_in_executor(
                self._workers[key],
                copy_context().run,
                self._execute_sync,
                context,
                name,
                args,
            )
        finally:
            if key in self._active:
                self._active[key] -= 1

    def _execute_sync(self, context, name, args):
        lock_dir = Path(context.project_dir) / ".attocode" / "cache"
        lock_dir.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        budget = int(args.get("max_tokens", 8000))
        knowledge = args.pop("_knowledge", None)
        with FileLock(str(lock_dir / "operations.lock"), timeout=30), bind_request(context):
            if name == "capabilities":
                from importlib.util import find_spec

                from attocode_intel.remote import remote_profile

                payload = {
                    "workspace": context.workspace,
                    "source": context.source,
                    "revision": context.revision,
                    "profile": remote_profile.get() if self.resolver else self.profile,
                    "profiles": ["daily", "full"],
                    "tools": [t.name for t in self.catalog()],
                    "enhancements": {
                        "embeddings_package_installed": bool(find_spec("sentence_transformers")),
                        "watcher_active": "watcher" in context.stores,
                    },
                    "guidance": INSTRUCTIONS,
                }
                text = json.dumps(payload, indent=2)
            else:
                from attocode_intel.local_knowledge import LEARNING_TOOLS, execute_local_knowledge

                tool = registered_tools().get(name)
                # Validate even when called by a REST operation endpoint.
                if tool:
                    args = tool.fn_metadata.arg_model.model_validate(args).model_dump()
                else:
                    args.pop("max_tokens", None)
                service = context.service
                if context.source == "remote":
                    root = Path(context.project_dir).resolve()
                    for key, value in args.items():
                        if key in {
                            "path",
                            "file",
                            "file_path",
                            "files",
                            "changed_files",
                            "directory",
                            "scope",
                        }:
                            for candidate in value if isinstance(value, list) else [value]:
                                if candidate and not (root / candidate).resolve().is_relative_to(
                                    root
                                ):
                                    raise ValueError(
                                        "Path must remain inside the selected repository"
                                    )
                if context.source == "local":
                    from attocode_intel.freshness import FreshnessTracker

                    tracker = context.stores.setdefault(
                        "freshness", FreshnessTracker(context.project_dir)
                    )
                    tracker.refresh(service)
                payload = None
                if name in LEARNING_TOOLS:
                    payload = execute_local_knowledge(context, name, args)
                    text = json.dumps(payload)
                elif name == "review_change":
                    from attocode_intel.change_review import review

                    payload = review(service, args.get("files"), args.get("mode", "full"))
                    text = json.dumps(payload, default=str, indent=2)
                elif name == "semantic_search":
                    mgr = service._get_semantic_search()
                    results = (
                        mgr._keyword_search(args["query"], args["top_k"], args["file_filter"])
                        if args.get("mode") == "keyword"
                        else mgr.search(
                            args["query"], top_k=args["top_k"], file_filter=args["file_filter"]
                        )
                    )
                    payload = {
                        "query": args["query"],
                        "results": [
                            {"file_path": r.file_path, "score": r.score, "snippet": r.text}
                            for r in results
                        ],
                    }
                    text = mgr.format_results(results)
                else:
                    result = tool.fn(**args)
                    if inspect.isawaitable(result):
                        result = asyncio.run(result)
                    text = result if isinstance(result, str) else json.dumps(result, default=str)
                    if name in {
                        "symbols",
                        "search_symbols",
                        "dependencies",
                        "cross_references",
                        "call_graph",
                        "file_analysis",
                        "hotspots",
                        "dependency_graph",
                    }:
                        method = getattr(service, name + "_data")
                        parameters = inspect.signature(method).parameters
                        payload = method(
                            **{key: value for key, value in args.items() if key in parameters}
                        )
                    elif name == "impact_analysis":
                        payload = service.impact_analysis_data(
                            args.get("files", args.get("changed_files", []))
                        )
                    if name in {
                        "install_pack",
                        "install_community_pack",
                        "import_rules",
                        "rule_hygiene",
                        "evolve_rules",
                    }:
                        context.stores.pop("rules", None)
            if name == "bootstrap" and args.get("task_hint"):
                if context.source == "local":
                    from attocode_intel.local_knowledge import execute_local_knowledge

                    knowledge = execute_local_knowledge(
                        context, "recall", {"query": args["task_hint"], "max_results": 5}
                    )
                if knowledge:
                    knowledge_text = bounded_text(json.dumps(knowledge), max(1, budget // 4))[0]
                    text = (
                        "## Relevant project knowledge (verify entries marked stale)\n"
                        + knowledge_text
                        + "\n\n"
                        + text
                    )
            service = context.service
            ast_service = service._ast_service
            coverage = ast_service.hydration_snapshot() if ast_service else {"phase": "not_started"}
            phase = coverage.get("phase", "unknown")
            header = f"Source: {context.source} | Workspace: {context.workspace} | Revision: {context.revision} | Index: {phase}\n"
            if phase != "ready" or coverage.get("discovery_truncated"):
                header += "Coverage is incomplete; missing results do not prove absence.\n"
            text, truncated = bounded_text(header + text, budget)
            truncated = truncated or "[Truncated;" in text
            metadata = {
                "workspace": context.workspace,
                "source": context.source,
                "revision": context.revision,
                "coverage": coverage,
                "freshness": "committed_snapshot" if context.source == "remote" else "working_tree",
                "truncated": truncated,
                "duration_ms": round((time.monotonic() - start) * 1000, 2),
            }
            structured = {"result": text, "metadata": metadata}
            if payload is not None:
                structured["capabilities" if name == "capabilities" else "data"] = payload
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)], structuredContent=structured
            )


def create_mcp_server(gateway: OperationGateway) -> Server:
    server = Server("attocode-code-intel", version="0.1.0", instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools():
        return gateway.catalog()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        # Advertised roots are advisory, never a substitute for remote authorization.
        if not gateway.resolver and not gateway.project and not arguments.get("workspace"):
            session = server.request_context.session
            try:
                roots = await session.list_roots()
                from urllib.parse import unquote, urlparse

                paths = [
                    unquote(urlparse(str(root.uri)).path)
                    for root in roots.roots
                    if str(root.uri).startswith("file://")
                ]
            except Exception:
                paths = []
            if len(paths) == 1:
                arguments = {**arguments, "workspace": paths[0]}
            elif len(paths) > 1:
                raise ValueError(f"Multiple workspace roots; supply workspace explicitly: {paths}")
        return await gateway.execute(name, arguments)

    @server.list_resources()
    async def list_resources():
        return [
            types.Resource(
                uri="attocode://guidelines", name="Agent guidelines", mimeType="text/plain"
            )
        ]

    @server.list_resource_templates()
    async def list_resource_templates():
        return [
            types.ResourceTemplate(uriTemplate=template, name=name, mimeType="text/plain")
            for template, name in (
                (
                    "attocode://project/{path}{?workspace,revision}",
                    "File analysis in a selected workspace",
                ),
                (
                    "attocode://symbols/{name}{?workspace,revision}",
                    "Symbol references in a selected workspace",
                ),
                ("attocode://learnings{?workspace,revision}", "Repository knowledge"),
            )
        ]

    @server.read_resource()
    async def read_resource(uri):
        from urllib.parse import parse_qs, unquote, urlparse

        from mcp.server.lowlevel.helper_types import ReadResourceContents

        if str(uri) == "attocode://guidelines":
            return [ReadResourceContents(INSTRUCTIONS, mime_type="text/plain")]
        parsed = urlparse(str(uri))
        if parsed.scheme != "attocode":
            raise ValueError("Unknown resource scheme")
        args = {
            key: value[-1]
            for key, value in parse_qs(parsed.query).items()
            if key in {"workspace", "revision"}
        }
        if parsed.netloc == "project":
            name, args["path"] = "symbols", unquote(parsed.path.lstrip("/"))
        elif parsed.netloc == "symbols":
            name, args["symbol_name"] = "cross_references", unquote(parsed.path.lstrip("/"))
        elif parsed.netloc == "learnings":
            name = "list_learnings"
        else:
            raise ValueError("Unknown intelligence resource")
        result = await call_tool(name, args)
        return [ReadResourceContents(result.content[0].text, mime_type="text/plain")]

    return server
