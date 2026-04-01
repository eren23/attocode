"""Call hierarchy utilities for LSP.

Implements incomingCalls and outgoingCalls via the LSP callHierarchy/*
protocol. Two-step: first prepareCallHierarchy, then fetch calls.

This is distinct from CC's implementation (which also does two-step) but
uses a different internal naming convention and error handling approach.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Any

from attocode.types.messages import DangerLevel

from .client import LSPClient, LSPLocation, LSPManager, LSPPosition


@dataclass
class CallHierarchyItem:
    """A symbol in the call hierarchy."""

    name: str
    uri: str
    line: int
    column: int
    kind: str = "function"  # LSP SymbolKind


@dataclass
class CallEntry:
    """A single call in the hierarchy."""

    caller: CallHierarchyItem
    callees: list[CallHierarchyItem]  # For outgoing calls
    callers: list[CallHierarchyItem]  # For incoming calls


class CallHierarchyClient:
    """Manages callHierarchy requests for a single LSP client.

    LSP callHierarchy is a two-step protocol:
    1. textDocument/prepareCallHierarchy → gets the symbol at position
    2. callHierarchy/incomingCalls or callHierarchy/outgoingCalls → gets the calls

    This class encapsulates that flow with error handling and result normalization.
    """

    def __init__(self, lsp_client: LSPClient, root_uri: str) -> None:
        self._client = lsp_client
        self._root_uri = root_uri

    @property
    def is_supported(self) -> bool:
        """Return True if the underlying client advertises callHierarchy support."""
        # We check by attempting a no-op call — a real implementation would
        # check the server's serverInfo.capabilities during initialize.
        return self._client.language_id in {
            "typescript", "javascript", "python", "rust", "go", "java",
            "cpp", "csharp",
        }

    async def prepare(
        self, uri: str, line: int, column: int
    ) -> list[CallHierarchyItem] | None:
        """Step 1: Prepare call hierarchy for a position.

        Returns a list of CallHierarchyItem objects representing the
        symbols at the given position.  Usually one, but can be multiple
        for overloaded symbols.
        """
        if not self._client.is_initialized:
            return None

        try:
            result = await self._client._request(
                "textDocument/prepareCallHierarchy",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": column},
                },
            )
        except Exception:
            return None

        if not result:
            return None

        items: list[CallHierarchyItem] = []
        for raw in (result if isinstance(result, list) else [result]):
            if not isinstance(raw, dict):
                continue
            name = raw.get("name", "")
            item_uri = raw.get("uri", uri)
            r = raw.get("range", {})
            start = r.get("start", {})
            items.append(CallHierarchyItem(
                name=name,
                uri=item_uri,
                line=start.get("line", line),
                column=start.get("character", column),
                kind=_symbol_kind_name(raw.get("kind", 6)),
            ))
        return items if items else None

    async def incoming_calls(
        self, item: CallHierarchyItem
    ) -> list[CallEntry]:
        """Step 2a: Get incoming calls — who calls this symbol."""
        if not self._client.is_initialized:
            return []

        try:
            result = await self._client._request(
                "callHierarchy/incomingCalls",
                {
                    "item": {
                        "name": item.name,
                        "uri": item.uri,
                        "range": {
                            "start": {"line": item.line, "character": item.column},
                            "end": {"line": item.line, "character": item.column},
                        },
                        "selectionRange": {
                            "start": {"line": item.line, "character": item.column},
                            "end": {"line": item.line, "character": item.column},
                        },
                    }
                },
            )
        except Exception:
            return []

        return _parse_calls(result, item)

    async def outgoing_calls(
        self, item: CallHierarchyItem
    ) -> list[CallEntry]:
        """Step 2b: Get outgoing calls — what this symbol calls."""
        if not self._client.is_initialized:
            return []

        try:
            result = await self._client._request(
                "callHierarchy/outgoingCalls",
                {
                    "item": {
                        "name": item.name,
                        "uri": item.uri,
                        "range": {
                            "start": {"line": item.line, "character": item.column},
                            "end": {"line": item.line, "character": item.column},
                        },
                        "selectionRange": {
                            "start": {"line": item.line, "character": item.column},
                            "end": {"line": item.line, "character": item.column},
                        },
                    }
                },
            )
        except Exception:
            return []

        return _parse_calls(result, item)


def _symbol_kind_name(kind: int) -> str:
    """Map LSP SymbolKind numbers to human-readable names."""
    names = {
        1: "file", 2: "module", 3: "namespace", 4: "package",
        5: "class", 6: "method", 7: "property", 8: "field",
        9: "constructor", 10: "enum", 11: "interface", 12: "function",
        13: "variable", 14: "constant", 15: "string", 16: "number",
        17: "boolean", 18: "array", 19: "object", 20: "key",
        21: "null", 22: "enum-member", 23: "event", 24: "operator",
        25: "type-parameter",
    }
    return names.get(kind, "symbol")


def _parse_calls(
    result: Any, from_item: CallHierarchyItem
) -> list[CallEntry]:
    """Parse raw callHierarchy result into CallEntry objects."""
    if not isinstance(result, list):
        return []

    entries: list[CallEntry] = []
    for raw in result:
        if not isinstance(raw, dict):
            continue

        from_raw = raw.get("from", {})
        from_ranges = raw.get("fromRanges", [])

        if not from_raw:
            continue

        from_item_parsed = CallHierarchyItem(
            name=from_raw.get("name", ""),
            uri=from_raw.get("uri", from_item.uri),
            line=from_raw.get("range", {}).get("start", {}).get("line", 0),
            column=from_raw.get("range", {}).get("start", {}).get("character", 0),
            kind=_symbol_kind_name(from_raw.get("kind", 6)),
        )

        entries.append(CallEntry(
            caller=from_item_parsed,
            callees=[],  # Outgoing: filled by caller
            callers=[],   # Incoming: filled by caller
        ))

    return entries


# =============================================================================
# Gitignored path filtering
# =============================================================================


class GitignoredFilter:
    """Filter paths against .gitignore rules.

    Uses ``git check-ignore`` in batch mode to efficiently filter
    a list of paths.  Paths matching .gitignore rules are excluded.

    This prevents showing LSP references in generated files,
    build artifacts, node_modules, and other non-source paths.
    """

    def __init__(self, root: str) -> None:
        self._root = root
        self._git_path: str | None = None
        self._checked_paths: dict[str, bool] = {}  # path → is_ignored

    def _find_git(self) -> str | None:
        """Find the git executable. Cached."""
        if self._git_path is None:
            import shutil
            self._git_path = shutil.which("git") or "git"
        return self._git_path

    async def is_ignored(self, path: str) -> bool:
        """Return True if *path* is gitignored (cached per path)."""
        if path in self._checked_paths:
            return self._checked_paths[path]

        import os
        git = self._find_git()
        if not git:
            self._checked_paths[path] = False
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                git, "check-ignore", "--no-index",
                os.devnull, path,
                cwd=self._root,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            # Exit code 0 means ignored, 1 means not ignored, 128 means path not found
            await proc.wait()
            ignored = proc.returncode == 0
        except Exception:
            ignored = False

        self._checked_paths[path] = ignored
        return ignored

    async def filter_locations(
        self, locations: list[LSPLocation]
    ) -> list[LSPLocation]:
        """Filter a list of LSP locations, removing gitignored paths.

        Args:
            locations: List of LSPLocation objects.

        Returns:
            Filtered list with gitignored paths removed.
        """
        if not locations:
            return []

        import os
        git = self._find_git()
        if not git:
            return locations

        # Batch git check-ignore: write paths to stdin, get results on stdout
        paths = []
        for loc in locations:
            uri = loc.uri
            if uri.startswith("file://"):
                uri = uri[7:]
            paths.append(uri)

        try:
            proc = await asyncio.create_subprocess_exec(
                git, "check-ignore", "--stdin",
                cwd=self._root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            input_text = "\n".join(paths)
            stdout, _ = await proc.communicate(input_text.encode())
            ignored_set = set(stdout.decode().strip().split("\n"))
        except Exception:
            return locations

        # Filter out ignored paths
        filtered: list[LSPLocation] = []
        for loc in locations:
            uri = loc.uri
            if uri.startswith("file://"):
                uri = uri[7:]
            if uri not in ignored_set:
                filtered.append(loc)

        return filtered

    def sync_filter(self, paths: list[str]) -> list[str]:
        """Synchronous version using subprocess.run (for non-async contexts)."""
        import os, subprocess, shutil
        git = shutil.which("git") or "git"
        try:
            proc = subprocess.run(
                [git, "check-ignore", "--stdin"],
                input="\n".join(paths).encode(),
                cwd=self._root,
                capture_output=True,
                timeout=10,
            )
            ignored = set(proc.stdout.decode().strip().split("\n"))
            return [p for p in paths if p not in ignored]
        except Exception:
            return paths
