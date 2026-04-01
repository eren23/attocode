"""Round-trip tests for LSP API models (completions, calls, workspace symbol)."""

from __future__ import annotations

from attocode.code_intel.api.models import (
    LSPCompletionsResponse,
    LSPIncomingCallItem,
    LSPIncomingCallsResponse,
    LSPOutgoingCallItem,
    LSPOutgoingCallsResponse,
    LSPWorkspaceSymbolItem,
    LSPWorkspaceSymbolResponse,
)


def test_lsp_completions_response_parse() -> None:
    raw = {
        "file": "src/a.py",
        "line": 2,
        "col": 5,
        "completions": [
            {"label": "foo", "kind": "function", "detail": "()->None"},
        ],
        "total": 1,
        "error": None,
    }
    m = LSPCompletionsResponse.model_validate(raw)
    assert m.completions[0].label == "foo"
    assert m.total == 1


def test_lsp_incoming_calls_response_parse() -> None:
    raw = {
        "symbol": "bar",
        "file": "src/a.py",
        "line": 1,
        "col": 0,
        "callers": [
            {
                "name": "caller",
                "container": "mod",
                "file": "src/b.py",
                "line": 10,
                "col": 4,
            },
        ],
        "total": 1,
    }
    m = LSPIncomingCallsResponse.model_validate(raw)
    assert m.callers[0].file == "src/b.py"


def test_lsp_outgoing_calls_response_parse() -> None:
    raw = {
        "symbol": "main",
        "file": "main.py",
        "line": 0,
        "col": 0,
        "callees": [
            LSPOutgoingCallItem(
                name="helper",
                file="util.py",
                line=3,
                col=0,
            ).model_dump(),
        ],
        "total": 1,
    }
    m = LSPOutgoingCallsResponse.model_validate(raw)
    assert m.callees[0].name == "helper"


def test_lsp_workspace_symbol_response_parse() -> None:
    raw = {
        "query": "User",
        "symbols": [
            LSPWorkspaceSymbolItem(
                name="User",
                kind="class",
                file="models.py",
                line=5,
                container="app.models",
            ).model_dump(),
        ],
        "total": 1,
    }
    m = LSPWorkspaceSymbolResponse.model_validate(raw)
    assert m.symbols[0].container == "app.models"
