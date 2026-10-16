"""Tests for streaming handler, PTY shell, and LSP client modules."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from attocode_intel._internal.errors import ToolError
from attocode_intel._internal.integrations.lsp.client import (
    BUILTIN_SERVERS,
    COMPLETION_KIND_MAP,
    LanguageServerConfig,
    LSPCompletion,
    LSPConfig,
    LSPDiagnostic,
    LSPLocation,
    LSPManager,
    LSPPosition,
    LSPRange,
    _LSPClient,
    _parse_range,
)

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────














# ======================================================================
# StreamConfig
# ======================================================================




# ======================================================================
# _StreamState (internal)
# ======================================================================




# ======================================================================
# StreamHandler
# ======================================================================










# ======================================================================
# SSE Adapter: adapt_openrouter_stream
# ======================================================================




# ======================================================================
# SSE Adapter: adapt_anthropic_stream
# ======================================================================




# ======================================================================
# format_chunk_for_terminal
# ======================================================================




# ======================================================================
# PTYShellConfig
# ======================================================================




# ======================================================================
# CommandResult
# ======================================================================




# ======================================================================
# ShellState
# ======================================================================




# ======================================================================
# PTYShellManager
# ======================================================================








# ======================================================================
# format_shell_state
# ======================================================================




# ======================================================================
# LSPPosition / LSPRange / LSPLocation / LSPDiagnostic / LSPCompletion
# ======================================================================


class TestLSPPosition:
    """Tests for LSPPosition."""

    def test_construction(self) -> None:
        pos = LSPPosition(line=10, character=5)
        assert pos.line == 10
        assert pos.character == 5

    def test_zero_indexed(self) -> None:
        pos = LSPPosition(line=0, character=0)
        assert pos.line == 0
        assert pos.character == 0


class TestLSPRange:
    """Tests for LSPRange."""

    def test_construction(self) -> None:
        r = LSPRange(
            start=LSPPosition(line=1, character=0),
            end=LSPPosition(line=1, character=10),
        )
        assert r.start.line == 1
        assert r.end.character == 10

    def test_same_line_range(self) -> None:
        r = LSPRange(
            start=LSPPosition(line=5, character=3),
            end=LSPPosition(line=5, character=8),
        )
        assert r.start.line == r.end.line

    def test_multi_line_range(self) -> None:
        r = LSPRange(
            start=LSPPosition(line=1, character=0),
            end=LSPPosition(line=10, character=0),
        )
        assert r.start.line < r.end.line


class TestLSPLocation:
    """Tests for LSPLocation."""

    def test_construction(self) -> None:
        loc = LSPLocation(
            uri="file:///tmp/test.py",
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=5),
            ),
        )
        assert loc.uri == "file:///tmp/test.py"
        assert loc.range.start.line == 0


class TestLSPDiagnostic:
    """Tests for LSPDiagnostic."""

    def test_construction(self) -> None:
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=3, character=0),
                end=LSPPosition(line=3, character=10),
            ),
            message="Undefined variable 'x'",
        )
        assert diag.message == "Undefined variable 'x'"
        assert diag.severity == "error"  # default
        assert diag.source is None
        assert diag.code is None

    def test_custom_severity(self) -> None:
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=0),
            ),
            message="unused import",
            severity="warning",
            source="pyright",
            code="reportUnusedImport",
        )
        assert diag.severity == "warning"
        assert diag.source == "pyright"
        assert diag.code == "reportUnusedImport"

    def test_numeric_code(self) -> None:
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=0),
            ),
            message="error",
            code=1234,
        )
        assert diag.code == 1234


class TestLSPCompletion:
    """Tests for LSPCompletion."""

    def test_construction(self) -> None:
        c = LSPCompletion(label="print")
        assert c.label == "print"
        assert c.kind == "text"  # default
        assert c.detail is None
        assert c.documentation is None
        assert c.insert_text is None

    def test_full_completion(self) -> None:
        c = LSPCompletion(
            label="print",
            kind="function",
            detail="print(*objects)",
            documentation="Print objects to the text stream file.",
            insert_text="print($1)",
        )
        assert c.kind == "function"
        assert c.detail == "print(*objects)"
        assert c.documentation is not None
        assert c.insert_text == "print($1)"


# ======================================================================
# LanguageServerConfig
# ======================================================================


class TestLanguageServerConfig:
    """Tests for LanguageServerConfig."""

    def test_construction(self) -> None:
        cfg = LanguageServerConfig(command="pyright-langserver")
        assert cfg.command == "pyright-langserver"
        assert cfg.args == []
        assert cfg.extensions == []
        assert cfg.language_id == ""

    def test_full_construction(self) -> None:
        cfg = LanguageServerConfig(
            command="typescript-language-server",
            args=["--stdio"],
            extensions=[".ts", ".tsx"],
            language_id="typescript",
        )
        assert cfg.args == ["--stdio"]
        assert ".ts" in cfg.extensions
        assert cfg.language_id == "typescript"


# ======================================================================
# LSPConfig
# ======================================================================


class TestLSPConfig:
    """Tests for LSPConfig."""

    def test_defaults(self) -> None:
        cfg = LSPConfig()
        assert cfg.enabled is True
        assert cfg.servers == {}
        assert cfg.auto_detect is True
        assert cfg.timeout == 30.0
        assert cfg.root_uri == ""

    def test_custom_config(self) -> None:
        server = LanguageServerConfig(command="my-lsp")
        cfg = LSPConfig(
            enabled=False,
            servers={"custom": server},
            auto_detect=False,
            timeout=60.0,
            root_uri="file:///workspace",
        )
        assert cfg.enabled is False
        assert "custom" in cfg.servers
        assert cfg.auto_detect is False
        assert cfg.timeout == 60.0


# ======================================================================
# BUILTIN_SERVERS
# ======================================================================


class TestBuiltinServers:
    """Tests for BUILTIN_SERVERS constant."""

    def test_has_typescript(self) -> None:
        assert "typescript" in BUILTIN_SERVERS
        ts = BUILTIN_SERVERS["typescript"]
        assert ts.command == "typescript-language-server"
        assert ".ts" in ts.extensions
        assert ".tsx" in ts.extensions
        assert ".js" in ts.extensions

    def test_has_python(self) -> None:
        assert "python" in BUILTIN_SERVERS
        py = BUILTIN_SERVERS["python"]
        assert py.command == "pyright-langserver"
        assert ".py" in py.extensions
        assert ".pyi" in py.extensions

    def test_has_rust(self) -> None:
        assert "rust" in BUILTIN_SERVERS
        rs = BUILTIN_SERVERS["rust"]
        assert rs.command == "rust-analyzer"
        assert ".rs" in rs.extensions

    def test_has_go(self) -> None:
        assert "go" in BUILTIN_SERVERS
        go = BUILTIN_SERVERS["go"]
        assert go.command == "gopls"
        assert ".go" in go.extensions

    def test_has_json(self) -> None:
        assert "json" in BUILTIN_SERVERS
        j = BUILTIN_SERVERS["json"]
        assert j.command == "vscode-json-language-server"
        assert ".json" in j.extensions
        assert ".jsonc" in j.extensions

    def test_all_have_language_id(self) -> None:
        for lang_id, cfg in BUILTIN_SERVERS.items():
            assert cfg.language_id == lang_id


# ======================================================================
# COMPLETION_KIND_MAP
# ======================================================================


class TestCompletionKindMap:
    """Tests for COMPLETION_KIND_MAP constant."""

    def test_has_expected_mappings(self) -> None:
        assert COMPLETION_KIND_MAP[1] == "text"
        assert COMPLETION_KIND_MAP[2] == "method"
        assert COMPLETION_KIND_MAP[3] == "function"
        assert COMPLETION_KIND_MAP[4] == "constructor"
        assert COMPLETION_KIND_MAP[5] == "field"
        assert COMPLETION_KIND_MAP[6] == "variable"
        assert COMPLETION_KIND_MAP[7] == "class"
        assert COMPLETION_KIND_MAP[8] == "interface"
        assert COMPLETION_KIND_MAP[9] == "module"
        assert COMPLETION_KIND_MAP[10] == "property"
        assert COMPLETION_KIND_MAP[14] == "keyword"
        assert COMPLETION_KIND_MAP[15] == "snippet"

    def test_unknown_kind_not_present(self) -> None:
        assert 999 not in COMPLETION_KIND_MAP


# ======================================================================
# _parse_range (internal helper)
# ======================================================================


class TestParseRange:
    """Tests for _parse_range internal function."""

    def test_valid_range(self) -> None:
        r = _parse_range({
            "start": {"line": 5, "character": 10},
            "end": {"line": 5, "character": 20},
        })
        assert isinstance(r, LSPRange)
        assert r.start.line == 5
        assert r.start.character == 10
        assert r.end.line == 5
        assert r.end.character == 20

    def test_empty_dict_defaults_to_zero(self) -> None:
        r = _parse_range({})
        assert r.start.line == 0
        assert r.start.character == 0
        assert r.end.line == 0
        assert r.end.character == 0

    def test_partial_start_defaults(self) -> None:
        r = _parse_range({"start": {"line": 3}})
        assert r.start.line == 3
        assert r.start.character == 0

    def test_partial_end_defaults(self) -> None:
        r = _parse_range({"end": {"character": 7}})
        assert r.end.line == 0
        assert r.end.character == 7


# ======================================================================
# _LSPClient (internal)
# ======================================================================


class TestLSPClientInit:
    """Tests for _LSPClient construction."""

    def test_construction(self) -> None:
        cfg = LanguageServerConfig(
            command="test-server",
            args=["--stdio"],
            language_id="test",
        )
        client = _LSPClient(cfg, root_uri="file:///workspace")
        assert client.language_id == "test"
        assert client.is_initialized is False

    def test_not_initialized_by_default(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        assert client.is_initialized is False

    @pytest.mark.asyncio
    async def test_get_definition_returns_none_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_definition("file:///tmp/a.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_completions_returns_empty_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_completions("file:///tmp/a.py", 0, 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_hover_returns_none_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_hover("file:///tmp/a.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_references_returns_empty_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_references("file:///tmp/a.py", 0, 0)
        assert result == []

    def test_notify_document_open_noop_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        # Should not raise
        client.notify_document_open("file:///tmp/a.py", "content")

    def test_notify_document_change_noop_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        client.notify_document_change("file:///tmp/a.py", "content", 2)

    def test_notify_document_close_noop_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        client.notify_document_close("file:///tmp/a.py")


class TestLSPClientHandleMessage:
    """Tests for _LSPClient._handle_message."""

    def _make_client(self) -> _LSPClient:
        cfg = LanguageServerConfig(command="x", language_id="y")
        return _LSPClient(cfg, root_uri="file:///tmp")

    def test_response_resolves_pending_future(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        client._pending[1] = future

        client._handle_message({"id": 1, "result": {"key": "value"}})
        assert future.done()
        assert future.result() == {"key": "value"}
        loop.close()

    def test_error_response_sets_exception(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        client._pending[2] = future

        client._handle_message({
            "id": 2,
            "error": {"message": "Method not found"},
        })
        assert future.done()
        with pytest.raises(ToolError, match="Method not found"):
            future.result()
        loop.close()

    def test_unknown_id_ignored(self) -> None:
        client = self._make_client()
        # No pending for id=999
        client._handle_message({"id": 999, "result": None})
        # Should not raise

    def test_notification_with_diagnostics(self) -> None:
        received: list[tuple[str, list]] = []

        def on_diags(uri: str, diags: list[LSPDiagnostic]) -> None:
            received.append((uri, diags))

        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp", on_diagnostics=on_diags)

        client._handle_message({
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///tmp/test.py",
                "diagnostics": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "message": "undefined name 'x'",
                    "severity": 1,
                    "source": "pyright",
                }],
            },
        })

        assert len(received) == 1
        assert received[0][0] == "file:///tmp/test.py"
        assert len(received[0][1]) == 1
        assert received[0][1][0].message == "undefined name 'x'"
        assert received[0][1][0].severity == "error"
        assert received[0][1][0].source == "pyright"

    def test_notification_diagnostic_severity_mapping(self) -> None:
        received: list[tuple[str, list]] = []

        def on_diags(uri: str, diags: list[LSPDiagnostic]) -> None:
            received.append((uri, diags))

        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp", on_diagnostics=on_diags)

        client._handle_message({
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///tmp/t.py",
                "diagnostics": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "e1", "severity": 1},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "w1", "severity": 2},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "i1", "severity": 3},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "h1", "severity": 4},
                ],
            },
        })

        diags = received[0][1]
        assert diags[0].severity == "error"
        assert diags[1].severity == "warning"
        assert diags[2].severity == "information"
        assert diags[3].severity == "hint"

    def test_already_done_future_not_overwritten(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        future.set_result("already done")
        client._pending[3] = future

        # Should not raise even though future is already resolved
        client._handle_message({"id": 3, "result": "new value"})
        assert future.result() == "already done"
        loop.close()


class TestLSPClientProcessBuffer:
    """Tests for _LSPClient._process_buffer."""

    def _make_client(self) -> _LSPClient:
        cfg = LanguageServerConfig(command="x", language_id="y")
        return _LSPClient(cfg, root_uri="file:///tmp")

    def test_parses_complete_message(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        client._pending[1] = future

        content = json.dumps({"id": 1, "result": "ok"}).encode()
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        client._buffer = header + content

        client._process_buffer()
        assert future.done()
        assert future.result() == "ok"
        loop.close()

    def test_incomplete_message_waits(self) -> None:
        client = self._make_client()
        content = json.dumps({"id": 1, "result": "ok"}).encode()
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        # Only provide partial content
        client._buffer = header + content[:5]

        client._process_buffer()
        # Should not have processed anything; buffer still has data
        assert len(client._buffer) > 0

    def test_no_header_clears_garbage(self) -> None:
        client = self._make_client()
        # No Content-Length header, just data with \r\n\r\n separator
        client._buffer = b"Garbage-Header: true\r\n\r\nsome content"
        client._process_buffer()
        # Should skip past the header since no Content-Length match

    def test_multiple_messages_in_buffer(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        f1: asyncio.Future = loop.create_future()
        f2: asyncio.Future = loop.create_future()
        client._pending[1] = f1
        client._pending[2] = f2

        msg1 = json.dumps({"id": 1, "result": "first"}).encode()
        msg2 = json.dumps({"id": 2, "result": "second"}).encode()
        client._buffer = (
            f"Content-Length: {len(msg1)}\r\n\r\n".encode() + msg1
            + f"Content-Length: {len(msg2)}\r\n\r\n".encode() + msg2
        )

        client._process_buffer()
        assert f1.result() == "first"
        assert f2.result() == "second"
        loop.close()


# ======================================================================
# LSPManager
# ======================================================================


class TestLSPManagerInit:
    """Tests for LSPManager construction."""

    def test_default_construction(self) -> None:
        mgr = LSPManager()
        assert mgr.get_active_servers() == []

    def test_custom_config(self) -> None:
        cfg = LSPConfig(enabled=False, timeout=60.0)
        mgr = LSPManager(config=cfg)
        assert mgr._enabled is False
        assert mgr._timeout == 60.0

    def test_get_active_servers_empty_initially(self) -> None:
        mgr = LSPManager()
        assert mgr.get_active_servers() == []

    def test_is_server_running_false_initially(self) -> None:
        mgr = LSPManager()
        assert mgr.is_server_running("typescript") is False
        assert mgr.is_server_running("python") is False
        assert mgr.is_server_running("nonexistent") is False


class TestLSPManagerEvents:
    """Tests for LSPManager event subscription."""

    def test_on_subscribes_returns_unsubscribe(self) -> None:
        mgr = LSPManager()
        events: list[str] = []
        unsub = mgr.on(lambda e, d: events.append(e))
        assert callable(unsub)

        mgr._emit("test.event", {})
        assert len(events) == 1

    def test_unsubscribe_removes_listener(self) -> None:
        mgr = LSPManager()
        events: list[str] = []
        unsub = mgr.on(lambda e, d: events.append(e))

        mgr._emit("test.event", {})
        assert len(events) == 1

        unsub()
        mgr._emit("test.event", {})
        assert len(events) == 1

    def test_listener_error_silently_caught(self) -> None:
        mgr = LSPManager()

        def bad(e: str, d: dict) -> None:
            raise ValueError("oops")

        events: list[str] = []
        mgr.on(bad)
        mgr.on(lambda e, d: events.append(e))

        mgr._emit("test.event", {})
        assert len(events) == 1


class TestLSPManagerHelpers:
    """Tests for LSPManager internal helpers."""

    def test_to_uri_with_file_path(self) -> None:
        result = LSPManager._to_uri("/tmp/test.py")
        assert result == "file:///tmp/test.py"

    def test_to_uri_already_uri(self) -> None:
        result = LSPManager._to_uri("file:///tmp/test.py")
        assert result == "file:///tmp/test.py"

    def test_get_client_for_file_no_matching_extension(self) -> None:
        mgr = LSPManager()
        client = mgr._get_client_for_file("test.unknown")
        assert client is None

    def test_get_client_for_file_not_started(self) -> None:
        mgr = LSPManager()
        # .py matches python, but no client started
        client = mgr._get_client_for_file("test.py")
        assert client is None

    def test_detect_languages_with_pyproject(self, tmp_path: Any) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "python" in result

    def test_detect_languages_with_tsconfig(self, tmp_path: Any) -> None:
        (tmp_path / "tsconfig.json").write_text("{}")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "typescript" in result

    def test_detect_languages_with_cargo(self, tmp_path: Any) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "rust" in result

    def test_detect_languages_with_go_mod(self, tmp_path: Any) -> None:
        (tmp_path / "go.mod").write_text("module test")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "go" in result

    def test_detect_languages_with_package_json(self, tmp_path: Any) -> None:
        (tmp_path / "package.json").write_text("{}")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "typescript" in result

    def test_detect_languages_with_requirements_txt(self, tmp_path: Any) -> None:
        (tmp_path / "requirements.txt").write_text("pytest")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "python" in result

    def test_detect_languages_empty_dir(self, tmp_path: Any) -> None:
        result = LSPManager._detect_languages(str(tmp_path))
        assert result == []

    def test_detect_languages_multiple(self, tmp_path: Any) -> None:
        (tmp_path / "pyproject.toml").write_text("")
        (tmp_path / "tsconfig.json").write_text("")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "python" in result
        assert "typescript" in result

    def test_custom_servers_merged_with_builtin(self) -> None:
        custom = LanguageServerConfig(
            command="my-lsp",
            language_id="custom",
            extensions=[".custom"],
        )
        cfg = LSPConfig(servers={"custom": custom})
        mgr = LSPManager(config=cfg)
        assert "custom" in mgr._servers
        assert "typescript" in mgr._servers  # builtin still present


class TestLSPManagerAsync:
    """Tests for async LSPManager methods."""

    @pytest.mark.asyncio
    async def test_start_server_unknown_language_raises(self) -> None:
        from attocode_intel._internal.errors import ConfigurationError

        mgr = LSPManager()
        with pytest.raises(ConfigurationError, match="No server configuration"):
            await mgr.start_server("klingon")

    @pytest.mark.asyncio
    async def test_start_server_missing_binary_raises(self) -> None:
        from attocode_intel._internal.errors import ConfigurationError

        mgr = LSPManager()
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(ConfigurationError, match="Language server not found"),
        ):
            await mgr.start_server("python")

    @pytest.mark.asyncio
    async def test_stop_server_not_started_noop(self) -> None:
        mgr = LSPManager()
        await mgr.stop_server("python")  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_all_empty_noop(self) -> None:
        mgr = LSPManager()
        await mgr.stop_all()  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_clears_all(self) -> None:
        mgr = LSPManager()
        mgr.on(lambda e, d: None)
        assert len(mgr._listeners) == 1

        await mgr.cleanup()
        assert len(mgr._listeners) == 0
        assert mgr._diagnostics_cache == {}

    @pytest.mark.asyncio
    async def test_get_definition_no_client_returns_none(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_definition("test.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_completions_no_client_returns_empty(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_completions("test.py", 0, 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_hover_no_client_returns_none(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_hover("test.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_references_no_client_returns_empty(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_references("test.py", 0, 0)
        assert result == []

    def test_get_diagnostics_no_cache_returns_empty(self) -> None:
        mgr = LSPManager()
        result = mgr.get_diagnostics("test.py")
        assert result == []

    def test_get_diagnostics_from_cache(self) -> None:
        mgr = LSPManager()
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=5),
            ),
            message="error here",
        )
        uri = f"file://{os.path.abspath('test.py')}"
        mgr._diagnostics_cache[uri] = [diag]
        result = mgr.get_diagnostics("test.py")
        assert len(result) == 1
        assert result[0].message == "error here"

    def test_notify_file_opened_no_client_noop(self) -> None:
        mgr = LSPManager()
        # Should not raise
        mgr.notify_file_opened("test.py", "content")

    def test_notify_file_changed_no_client_noop(self) -> None:
        mgr = LSPManager()
        mgr.notify_file_changed("test.py", "new content")

    def test_notify_file_closed_no_client_noop(self) -> None:
        mgr = LSPManager()
        mgr.notify_file_closed("test.py")

    @pytest.mark.asyncio
    async def test_auto_start_disabled_returns_empty(self) -> None:
        cfg = LSPConfig(enabled=False)
        mgr = LSPManager(config=cfg)
        result = await mgr.auto_start("/tmp")
        assert result == []

    @pytest.mark.asyncio
    async def test_auto_start_no_auto_detect_returns_empty(self) -> None:
        cfg = LSPConfig(auto_detect=False)
        mgr = LSPManager(config=cfg)
        result = await mgr.auto_start("/tmp")
        assert result == []

    @pytest.mark.asyncio
    async def test_start_server_already_started_noop(self) -> None:
        mgr = LSPManager()
        # Manually put a client in
        cfg = LanguageServerConfig(command="x", language_id="python")
        mock_client = _LSPClient(cfg, root_uri="file:///tmp")
        mgr._clients["python"] = mock_client

        # Should return without trying to start again
        with patch("shutil.which", return_value="/usr/bin/pyright-langserver"):
            await mgr.start_server("python")

    @pytest.mark.asyncio
    async def test_get_definition_unknown_extension_returns_none(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_definition("test.xyz", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_stop_server_emits_event(self) -> None:
        mgr = LSPManager()
        events: list[tuple[str, dict]] = []
        mgr.on(lambda e, d: events.append((e, d)))

        LanguageServerConfig(command="x", language_id="python")
        mock_client = MagicMock(spec=_LSPClient)
        mock_client.stop = AsyncMock()
        mgr._clients["python"] = mock_client

        await mgr.stop_server("python")

        stopped_events = [e for e in events if e[0] == "lsp.stopped"]
        assert len(stopped_events) == 1
        assert stopped_events[0][1]["language_id"] == "python"
