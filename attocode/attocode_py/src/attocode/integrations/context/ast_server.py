"""AST Unix Socket Server — serves AST data over `.agent/ast.sock`.

External CC instances in swarm mode can connect to this socket to query
the shared code intelligence index maintained by the orchestrator.

Protocol: newline-delimited JSON (one request, one response per line).

Request format::

    {"method": "symbols", "params": {"file": "src/auth.py"}}

Response format::

    {"ok": true, "result": [...]}
    {"ok": false, "error": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class ASTServer:
    """Unix domain socket server exposing ASTService queries.

    Usage::

        svc = ASTService.get_instance("/repo")
        server = ASTServer(svc, socket_path="/repo/.agent/ast.sock")
        await server.start()
        # ... later ...
        await server.stop()
    """

    def __init__(
        self,
        ast_service: Any,
        socket_path: str | None = None,
    ) -> None:
        self._ast_service = ast_service
        root = getattr(ast_service, "root_dir", getattr(ast_service, "_root_dir", "."))
        self._socket_path = socket_path or os.path.join(root, ".agent", "ast.sock")
        self._server: asyncio.AbstractServer | None = None

    @property
    def socket_path(self) -> str:
        return self._socket_path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start listening on the Unix socket."""
        # Ensure parent directory exists
        parent = os.path.dirname(self._socket_path)
        os.makedirs(parent, exist_ok=True)

        # Remove stale socket file
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self._socket_path,
        )
        logger.info("AST server listening on %s", self._socket_path)

    async def stop(self) -> None:
        """Stop the server and remove the socket file."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass
        logger.info("AST server stopped")

    # ------------------------------------------------------------------
    # Client handling
    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection (one request per line)."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    request = json.loads(line.decode("utf-8").strip())
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    response = {"ok": False, "error": f"Invalid JSON: {e}"}
                    writer.write(json.dumps(response).encode("utf-8") + b"\n")
                    await writer.drain()
                    continue

                response = self._dispatch(request)
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            logger.debug("AST server client error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Method dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a JSON-RPC-style request to the appropriate handler."""
        method = request.get("method", "")
        params = request.get("params", {})

        handlers = {
            "symbols": self._handle_symbols,
            "cross_refs": self._handle_cross_refs,
            "impact": self._handle_impact,
            "file_tree": self._handle_file_tree,
            "search": self._handle_search,
            "dependencies": self._handle_dependencies,
            "dependents": self._handle_dependents,
        }

        handler = handlers.get(method)
        if handler is None:
            return {
                "ok": False,
                "error": f"Unknown method: {method}. Available: {sorted(handlers.keys())}",
            }

        try:
            result = handler(params)
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_symbols(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return all symbols defined in a file.

        Params: ``{"file": "src/auth.py"}``
        """
        file_path = params.get("file", "")
        if not file_path:
            raise ValueError("'file' parameter required")

        locations = self._ast_service.get_file_symbols(file_path)
        return [
            {
                "name": loc.name,
                "qualified_name": loc.qualified_name,
                "kind": loc.kind,
                "file": loc.file_path,
                "start_line": loc.start_line,
                "end_line": loc.end_line,
            }
            for loc in locations
        ]

    def _handle_cross_refs(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return all call sites / references for a symbol.

        Params: ``{"symbol": "parse_file"}``
        """
        symbol = params.get("symbol", "")
        if not symbol:
            raise ValueError("'symbol' parameter required")

        refs = self._ast_service.get_callers(symbol)
        return [
            {
                "symbol_name": ref.symbol_name,
                "ref_kind": ref.ref_kind,
                "file": ref.file_path,
                "line": ref.line,
            }
            for ref in refs
        ]

    def _handle_impact(self, params: dict[str, Any]) -> list[str]:
        """Compute transitive impact set for changed files.

        Params: ``{"files": ["src/auth.py"]}`` or ``{"file": "src/auth.py", "symbol": "..."}``
        """
        files = params.get("files", [])
        if not files:
            single = params.get("file", "")
            if single:
                files = [single]
        if not files:
            raise ValueError("'files' or 'file' parameter required")

        return sorted(self._ast_service.get_impact(files))

    def _handle_file_tree(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return all indexed files with symbol counts.

        Params: ``{}`` (no required params)
        """
        cache = getattr(self._ast_service, "_ast_cache", {})
        index = getattr(self._ast_service, "_index", None)
        result = []

        for rel_path in sorted(cache.keys()):
            file_ast = cache[rel_path]
            symbol_count = 0
            if index:
                symbol_count = len(index.file_symbols.get(rel_path, set()))

            func_count = len(getattr(file_ast, "functions", []))
            class_count = len(getattr(file_ast, "classes", []))

            result.append({
                "file": rel_path,
                "symbols": symbol_count,
                "functions": func_count,
                "classes": class_count,
            })

        return result

    def _handle_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Fuzzy symbol search.

        Params: ``{"query": "parse"}``
        """
        query = params.get("query", "")
        if not query:
            raise ValueError("'query' parameter required")

        locations = self._ast_service.find_symbol(query)
        return [
            {
                "name": loc.name,
                "qualified_name": loc.qualified_name,
                "kind": loc.kind,
                "file": loc.file_path,
                "start_line": loc.start_line,
                "end_line": loc.end_line,
            }
            for loc in locations
        ]

    def _handle_dependencies(self, params: dict[str, Any]) -> list[str]:
        """Files that the given file imports from.

        Params: ``{"file": "src/auth.py"}``
        """
        file_path = params.get("file", "")
        if not file_path:
            raise ValueError("'file' parameter required")

        return sorted(self._ast_service.get_dependencies(file_path))

    def _handle_dependents(self, params: dict[str, Any]) -> list[str]:
        """Files that import the given file.

        Params: ``{"file": "src/auth.py"}``
        """
        file_path = params.get("file", "")
        if not file_path:
            raise ValueError("'file' parameter required")

        return sorted(self._ast_service.get_dependents(file_path))
