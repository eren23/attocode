"""Language Server Protocol client manager.

Manages LSP clients for multiple programming languages,
providing definitions, completions, hover info, references,
and diagnostics via the LSP JSON-RPC protocol.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# =============================================================================
# Types
# =============================================================================


@dataclass
class LSPPosition:
    """Position in a document (0-indexed)."""

    line: int
    character: int


@dataclass
class LSPRange:
    """Range in a document."""

    start: LSPPosition
    end: LSPPosition


@dataclass
class LSPLocation:
    """Location in a document."""

    uri: str
    range: LSPRange


@dataclass
class LSPDiagnostic:
    """Diagnostic message from a language server."""

    range: LSPRange
    message: str
    severity: str = "error"  # error, warning, information, hint
    source: str | None = None
    code: str | int | None = None


@dataclass
class LSPCompletion:
    """Completion item from a language server."""

    label: str
    kind: str = "text"
    detail: str | None = None
    documentation: str | None = None
    insert_text: str | None = None


@dataclass
class LanguageServerConfig:
    """Configuration for a language server."""

    command: str
    args: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    language_id: str = ""


@dataclass
class LSPConfig:
    """LSP manager configuration."""

    enabled: bool = True
    servers: dict[str, LanguageServerConfig] = field(default_factory=dict)
    auto_detect: bool = True
    timeout: float = 30.0
    root_uri: str = ""


LSPEventListener = Callable[[str, dict[str, Any]], None]


# =============================================================================
# Built-in Server Configs
# =============================================================================

BUILTIN_SERVERS: dict[str, LanguageServerConfig] = {
    "typescript": LanguageServerConfig(
        command="typescript-language-server",
        args=["--stdio"],
        extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
        language_id="typescript",
    ),
    "python": LanguageServerConfig(
        command="pyright-langserver",
        args=["--stdio"],
        extensions=[".py", ".pyi"],
        language_id="python",
    ),
    "rust": LanguageServerConfig(
        command="rust-analyzer",
        args=[],
        extensions=[".rs"],
        language_id="rust",
    ),
    "go": LanguageServerConfig(
        command="gopls",
        args=[],
        extensions=[".go"],
        language_id="go",
    ),
    "json": LanguageServerConfig(
        command="vscode-json-language-server",
        args=["--stdio"],
        extensions=[".json", ".jsonc"],
        language_id="json",
    ),
}

COMPLETION_KIND_MAP: dict[int, str] = {
    1: "text", 2: "method", 3: "function", 4: "constructor",
    5: "field", 6: "variable", 7: "class", 8: "interface",
    9: "module", 10: "property", 14: "keyword", 15: "snippet",
}


# =============================================================================
# LSP Client (Internal)
# =============================================================================


class _LSPClient:
    """Internal LSP client for a single language server.

    Communicates via JSON-RPC 2.0 over stdio using the
    Content-Length header framing protocol.
    """

    def __init__(
        self,
        config: LanguageServerConfig,
        root_uri: str,
        timeout: float = 30.0,
        on_diagnostics: Callable[[str, list[LSPDiagnostic]], None] | None = None,
    ) -> None:
        self._config = config
        self._root_uri = root_uri
        self._timeout = timeout
        self._on_diagnostics = on_diagnostics

        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._buffer = b""
        self._initialized = False
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def language_id(self) -> str:
        return self._config.language_id

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def start(self) -> None:
        """Start the language server and initialize it."""
        self._process = await asyncio.create_subprocess_exec(  # noqa: S603
            self._config.command,
            *self._config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if not self._process.stdout or not self._process.stdin:
            raise RuntimeError(f"Failed to spawn {self._config.command}")

        # Start reading responses in background
        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize
        await self._request("initialize", {
            "processId": os.getpid(),
            "rootUri": self._root_uri,
            "capabilities": {
                "textDocument": {
                    "completion": {"completionItem": {"snippetSupport": True}},
                    "hover": {},
                    "definition": {},
                    "references": {},
                    "publishDiagnostics": {},
                },
            },
        })
        self._notify("initialized", {})
        self._initialized = True

    async def stop(self) -> None:
        """Stop the language server."""
        if not self._process or not self._initialized:
            return

        try:
            await self._request("shutdown", None)
            self._notify("exit", None)
        except Exception:
            pass

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._process.returncode is None:
            self._process.kill()
            await self._process.wait()

        self._process = None
        self._initialized = False

        # Cancel pending requests
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def get_definition(
        self, uri: str, line: int, character: int
    ) -> LSPLocation | None:
        """Get symbol definition location."""
        if not self._initialized:
            return None

        result = await self._request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not result:
            return None

        loc = result[0] if isinstance(result, list) else result
        if not loc or not isinstance(loc, dict):
            return None

        return LSPLocation(
            uri=loc["uri"],
            range=_parse_range(loc["range"]),
        )

    async def get_completions(
        self, uri: str, line: int, character: int
    ) -> list[LSPCompletion]:
        """Get completion items at position."""
        if not self._initialized:
            return []

        result = await self._request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not result:
            return []

        items: list[Any]
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            items = result.get("items", [])
        else:
            items = []

        completions: list[LSPCompletion] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            doc = item.get("documentation")
            if isinstance(doc, dict):
                doc = doc.get("value", "")
            completions.append(LSPCompletion(
                label=str(item.get("label", "")),
                kind=COMPLETION_KIND_MAP.get(item.get("kind", 1), "text"),
                detail=item.get("detail"),
                documentation=doc if isinstance(doc, str) else None,
                insert_text=item.get("insertText") or item.get("label"),
            ))
        return completions

    async def get_hover(
        self, uri: str, line: int, character: int
    ) -> str | None:
        """Get hover information at position."""
        if not self._initialized:
            return None

        result = await self._request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not result or not isinstance(result, dict):
            return None

        contents = result.get("contents")
        if not contents:
            return None
        if isinstance(contents, str):
            return contents
        if isinstance(contents, list):
            parts = []
            for c in contents:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    parts.append(c.get("value", ""))
            return "\n".join(parts)
        if isinstance(contents, dict):
            return contents.get("value")
        return None

    async def get_references(
        self,
        uri: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> list[LSPLocation]:
        """Get all references to a symbol."""
        if not self._initialized:
            return []

        result = await self._request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": include_declaration},
        })
        if not result or not isinstance(result, list):
            return []

        return [
            LSPLocation(uri=loc["uri"], range=_parse_range(loc["range"]))
            for loc in result
            if isinstance(loc, dict) and "uri" in loc and "range" in loc
        ]

    def notify_document_open(self, uri: str, text: str) -> None:
        """Notify server about file open."""
        if not self._initialized:
            return
        self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": self._config.language_id,
                "version": 1,
                "text": text,
            },
        })

    def notify_document_change(
        self, uri: str, text: str, version: int = 1
    ) -> None:
        """Notify server about file change."""
        if not self._initialized:
            return
        self._notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": version},
            "contentChanges": [{"text": text}],
        })

    def notify_document_close(self, uri: str) -> None:
        """Notify server about file close."""
        if not self._initialized:
            return
        self._notify("textDocument/didClose", {
            "textDocument": {"uri": uri},
        })

    # Internal protocol methods

    async def _request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and wait for response."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("LSP server not running")

        self._request_id += 1
        req_id = self._request_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = future

        message = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        self._send_message(message)

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"Request {method} timed out") from None

    def _notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        asyncio.ensure_future(self._send_message(message))

    async def _send_message(self, message: dict[str, Any]) -> None:
        """Send a message with Content-Length header framing."""
        if not self._process or not self._process.stdin:
            return
        content = json.dumps(message).encode()
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        self._process.stdin.write(header + content)
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """Background loop reading LSP responses."""
        assert self._process is not None
        assert self._process.stdout is not None

        try:
            while True:
                data = await self._process.stdout.read(8192)
                if not data:
                    break
                self._buffer += data
                self._process_buffer()
        except asyncio.CancelledError:
            pass

    def _process_buffer(self) -> None:
        """Parse complete messages from the buffer."""
        while True:
            header_end = self._buffer.find(b"\r\n\r\n")
            if header_end == -1:
                break

            header = self._buffer[:header_end].decode(errors="replace")
            match = re.search(r"Content-Length:\s*(\d+)", header, re.IGNORECASE)
            if not match:
                self._buffer = self._buffer[header_end + 4:]
                continue

            content_length = int(match.group(1))
            message_start = header_end + 4
            message_end = message_start + content_length

            if len(self._buffer) < message_end:
                break  # Not enough data yet

            content = self._buffer[message_start:message_end]
            self._buffer = self._buffer[message_end:]

            try:
                msg = json.loads(content)
                self._handle_message(msg)
            except json.JSONDecodeError:
                pass

    def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle an incoming JSON-RPC message."""
        msg_id = message.get("id")
        if msg_id is not None and msg_id in self._pending:
            future = self._pending.pop(msg_id)
            if future.done():
                return
            error = message.get("error")
            if error:
                future.set_exception(
                    RuntimeError(error.get("message", "Unknown error"))
                )
            else:
                future.set_result(message.get("result"))
        elif "method" in message:
            self._handle_notification(message["method"], message.get("params"))

    def _handle_notification(self, method: str, params: Any) -> None:
        """Handle server notification."""
        if method == "textDocument/publishDiagnostics" and self._on_diagnostics:
            uri = params.get("uri", "")
            raw_diags = params.get("diagnostics", [])
            severity_map = {1: "error", 2: "warning", 3: "information", 4: "hint"}
            diagnostics = []
            for d in raw_diags:
                r = d.get("range", {})
                diagnostics.append(LSPDiagnostic(
                    range=_parse_range(r),
                    message=d.get("message", ""),
                    severity=severity_map.get(d.get("severity", 1), "error"),
                    source=d.get("source"),
                    code=d.get("code"),
                ))
            self._on_diagnostics(uri, diagnostics)


def _parse_range(r: dict[str, Any]) -> LSPRange:
    """Parse an LSP range from a dict."""
    start = r.get("start", {})
    end = r.get("end", {})
    return LSPRange(
        start=LSPPosition(
            line=start.get("line", 0),
            character=start.get("character", 0),
        ),
        end=LSPPosition(
            line=end.get("line", 0),
            character=end.get("character", 0),
        ),
    )


# =============================================================================
# LSP Manager
# =============================================================================


class LSPManager:
    """Manages multiple LSP clients for different languages.

    Auto-detects project languages and starts appropriate servers.
    Provides unified API for definitions, completions, hover, and refs.
    """

    def __init__(self, config: LSPConfig | None = None) -> None:
        cfg = config or LSPConfig()
        self._enabled = cfg.enabled
        self._servers = {**BUILTIN_SERVERS, **cfg.servers}
        self._auto_detect = cfg.auto_detect
        self._timeout = cfg.timeout
        self._root_uri = cfg.root_uri or f"file://{os.getcwd()}"

        self._clients: dict[str, _LSPClient] = {}
        self._listeners: set[LSPEventListener] = set()
        self._diagnostics_cache: dict[str, list[LSPDiagnostic]] = {}

    async def auto_start(self, workspace_root: str | None = None) -> list[str]:
        """Auto-detect and start LSP servers for detected languages."""
        if not self._enabled or not self._auto_detect:
            return []

        root_uri = f"file://{workspace_root}" if workspace_root else self._root_uri
        root_path = workspace_root or os.getcwd()

        detected = self._detect_languages(root_path)
        started: list[str] = []

        for lang_id in detected:
            try:
                await self.start_server(lang_id, root_uri)
                started.append(lang_id)
            except Exception as exc:
                self._emit("lsp.error", {
                    "language_id": lang_id, "error": str(exc),
                })

        return started

    async def start_server(
        self, language_id: str, root_uri: str | None = None
    ) -> None:
        """Start a specific language server."""
        if language_id in self._clients:
            return

        server_config = self._servers.get(language_id)
        if not server_config:
            raise ValueError(
                f"No server configuration for language: {language_id}"
            )

        if not shutil.which(server_config.command):
            raise RuntimeError(
                f"Language server not found: {server_config.command}"
            )

        def on_diags(uri: str, diags: list[LSPDiagnostic]) -> None:
            self._diagnostics_cache[uri] = diags
            self._emit("lsp.diagnostics", {"uri": uri, "diagnostics": diags})

        client = _LSPClient(
            server_config,
            root_uri or self._root_uri,
            self._timeout,
            on_diags,
        )
        await client.start()
        self._clients[language_id] = client
        self._emit("lsp.started", {
            "language_id": language_id,
            "command": server_config.command,
        })

    async def stop_server(self, language_id: str) -> None:
        """Stop a specific language server."""
        client = self._clients.pop(language_id, None)
        if client:
            await client.stop()
            self._emit("lsp.stopped", {"language_id": language_id})

    async def stop_all(self) -> None:
        """Stop all language servers."""
        tasks = [self.stop_server(lid) for lid in list(self._clients)]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def get_definition(
        self, file: str, line: int, col: int
    ) -> LSPLocation | None:
        """Get symbol definition."""
        client = self._get_client_for_file(file)
        if not client:
            return None
        uri = self._to_uri(file)
        return await client.get_definition(uri, line, col)

    async def get_completions(
        self, file: str, line: int, col: int
    ) -> list[LSPCompletion]:
        """Get completions at position."""
        client = self._get_client_for_file(file)
        if not client:
            return []
        uri = self._to_uri(file)
        return await client.get_completions(uri, line, col)

    async def get_hover(
        self, file: str, line: int, col: int
    ) -> str | None:
        """Get hover information."""
        client = self._get_client_for_file(file)
        if not client:
            return None
        uri = self._to_uri(file)
        return await client.get_hover(uri, line, col)

    async def get_references(
        self, file: str, line: int, col: int,
        include_declaration: bool = True,
    ) -> list[LSPLocation]:
        """Get all references to a symbol."""
        client = self._get_client_for_file(file)
        if not client:
            return []
        uri = self._to_uri(file)
        return await client.get_references(uri, line, col, include_declaration)

    def get_diagnostics(self, file: str) -> list[LSPDiagnostic]:
        """Get cached diagnostics for a file."""
        uri = self._to_uri(file)
        return self._diagnostics_cache.get(uri, [])

    def notify_file_opened(self, file: str, content: str) -> None:
        """Notify about file open."""
        client = self._get_client_for_file(file)
        if client:
            client.notify_document_open(self._to_uri(file), content)

    def notify_file_changed(
        self, file: str, content: str, version: int = 1
    ) -> None:
        """Notify about file change."""
        client = self._get_client_for_file(file)
        if client:
            client.notify_document_change(self._to_uri(file), content, version)

    def notify_file_closed(self, file: str) -> None:
        """Notify about file close."""
        client = self._get_client_for_file(file)
        if client:
            client.notify_document_close(self._to_uri(file))

    def get_active_servers(self) -> list[str]:
        """Get list of active language server IDs."""
        return list(self._clients.keys())

    def is_server_running(self, language_id: str) -> bool:
        """Check if a language server is running."""
        client = self._clients.get(language_id)
        return client.is_initialized if client else False

    def on(self, listener: LSPEventListener) -> Callable[[], None]:
        """Subscribe to LSP events. Returns unsubscribe function."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def cleanup(self) -> None:
        """Stop all servers and clean up resources."""
        await self.stop_all()
        self._listeners.clear()
        self._diagnostics_cache.clear()

    # Internal helpers

    @staticmethod
    def _to_uri(file: str) -> str:
        """Convert file path to URI."""
        if file.startswith("file://"):
            return file
        return f"file://{os.path.abspath(file)}"

    def _get_client_for_file(self, file: str) -> _LSPClient | None:
        """Find the appropriate client for a file extension."""
        ext = Path(file).suffix.lower()
        for lang_id, server_config in self._servers.items():
            if ext in server_config.extensions:
                return self._clients.get(lang_id)
        return None

    @staticmethod
    def _detect_languages(root_path: str) -> list[str]:
        """Detect languages based on project files."""
        detected: set[str] = set()
        check_files = [
            ("package.json", "typescript"),
            ("tsconfig.json", "typescript"),
            ("pyproject.toml", "python"),
            ("requirements.txt", "python"),
            ("Cargo.toml", "rust"),
            ("go.mod", "go"),
        ]
        for filename, language in check_files:
            if (Path(root_path) / filename).exists():
                detected.add(language)
        return list(detected)

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass
