"""AST Unix Socket Client — connects to the AST server socket.

External CC instances and swarm workers use this to query the shared
AST index without importing the full ASTService.

Usage::

    client = ASTClient("/repo/.agent/ast.sock")
    symbols = await client.symbols("src/auth.py")
    refs = await client.cross_refs("parse_file")
    impact = await client.impact(["src/auth.py"])
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ASTClient:
    """Client for the AST Unix socket server."""

    def __init__(self, socket_path: str, *, timeout: float = 5.0) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    @property
    def socket_path(self) -> str:
        return self._socket_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def symbols(self, file: str) -> list[dict[str, Any]]:
        """Get all symbols defined in a file."""
        return await self._call("symbols", {"file": file})

    async def cross_refs(self, symbol: str) -> list[dict[str, Any]]:
        """Get all references/call sites for a symbol."""
        return await self._call("cross_refs", {"symbol": symbol})

    async def impact(self, files: list[str]) -> list[str]:
        """Compute transitive impact set for changed files."""
        return await self._call("impact", {"files": files})

    async def file_tree(self) -> list[dict[str, Any]]:
        """Get all indexed files with symbol counts."""
        return await self._call("file_tree", {})

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Fuzzy symbol search."""
        return await self._call("search", {"query": query})

    async def dependencies(self, file: str) -> list[str]:
        """Get files that the given file imports from."""
        return await self._call("dependencies", {"file": file})

    async def dependents(self, file: str) -> list[str]:
        """Get files that import the given file."""
        return await self._call("dependents", {"file": file})

    async def ping(self) -> bool:
        """Check if the server is reachable."""
        try:
            result = await self._call("file_tree", {})
            return isinstance(result, list)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _call(self, method: str, params: dict[str, Any]) -> Any:
        """Send a request and return the result."""
        request = {"method": method, "params": params}
        request_bytes = json.dumps(request).encode("utf-8") + b"\n"

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket_path),
                timeout=self._timeout,
            )
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            raise ConnectionError(
                f"Cannot connect to AST server at {self._socket_path}: {e}"
            ) from e

        try:
            writer.write(request_bytes)
            await writer.drain()

            response_line = await asyncio.wait_for(
                reader.readline(),
                timeout=self._timeout,
            )

            if not response_line:
                raise ConnectionError("Empty response from AST server")

            response = json.loads(response_line.decode("utf-8").strip())

            if not response.get("ok", False):
                raise RuntimeError(response.get("error", "Unknown error"))

            return response.get("result")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
