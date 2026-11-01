"""Trial candidate: the opt-in hosted query rewrite (evals/results/2026-11-query-rewrite.md)."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from attocode_intel._internal.integrations.context.query_rewriter import (
    INSTRUCTION,
    OPENROUTER_REWRITE,
    QueryRewriter,
)
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.config import CodeIntelConfig
from attocode_intel.gateway import OperationGateway
from attocode_intel.service import CodeIntelService

LOCAL = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = OPENROUTER_REWRITE["model"]


def _answer(content: str, model: str = MODEL) -> dict:
    return {"model": model, "choices": [{"message": {"role": "assistant", "content": content}}]}


def _rewriter(respond, **kwargs) -> QueryRewriter:
    return QueryRewriter(LOCAL, model=MODEL, transport=httpx.MockTransport(respond), **kwargs)


@pytest.mark.parametrize(("content", "model", "expected"), [
    ('["req.accepts", "negotiateType"]', MODEL, ("ok", ["req.accepts", "negotiateType"])),
    ('```json\n["accepts"]\n```', MODEL, ("ok", ["accepts"])),
    ('[]', MODEL + "-20261015", ("ok", [])),
    ("accepts, negotiate", MODEL, ("invalid_response", [])),
    ('["accepts"]', "anthropic/other", ("invalid_response", [])),
    (json.dumps([f"w{i}" for i in range(13)]), MODEL, ("invalid_response", [])),
    (json.dumps(["x" * 81]), MODEL, ("invalid_response", [])),
    ('[1, "accepts"]', MODEL, ("invalid_response", [])),
    ('{"words": ["accepts"]}', MODEL, ("invalid_response", [])),
])
def test_response_parsing(content, model, expected):
    status, words, elapsed = _rewriter(lambda _r: httpx.Response(200, json=_answer(content, model))).rewrite("q")
    assert (status, words) == expected and elapsed >= 0


def test_request_carries_only_the_redacted_question(monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    monkeypatch.setenv("REWRITE_TEST_KEY", "private-test-token")
    sent = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer private-test-token"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=_answer('["accepts"]'))

    rewriter = QueryRewriter(
        "https://rewrite.example/v1/chat/completions", model=MODEL, auth_env="REWRITE_TEST_KEY",
        allow_remote=True, transport=httpx.MockTransport(respond))
    assert rewriter.rewrite("find sk-abcdefghijklmnopqrstuvwxyz " + "x" * 600)[0] == "ok"
    (body,) = sent
    assert set(body) == {"model", "temperature", "max_tokens", "messages"}
    assert (body["model"], body["temperature"], body["max_tokens"]) == (MODEL, 0, 120)
    system, user = body["messages"]
    assert system == {"role": "system", "content": INSTRUCTION}
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in user["content"] and "[REDACTED:" in user["content"]
    assert len(user["content"]) < 600


def test_consent_and_endpoint_refusals(monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    remote = "https://rewrite.example/v1/chat/completions"
    with pytest.raises(ValueError, match="not permitted"):
        QueryRewriter(remote, model=MODEL)
    with pytest.raises(ValueError, match="not permitted"):
        QueryRewriter(remote, model=MODEL, allow_remote=True, service_mode=True)
    with pytest.raises(ValueError, match="HTTPS"):
        QueryRewriter("http://rewrite.example/v1", model=MODEL, allow_remote=True)
    with pytest.raises(ValueError, match="without credentials"):
        QueryRewriter("https://user:pw@rewrite.example/v1", model=MODEL, allow_remote=True)
    with pytest.raises(ValueError, match="environment-variable name"):
        QueryRewriter(remote, model=MODEL, allow_remote=True, auth_env="sk-not-a-name")
    with pytest.raises(ValueError, match="invalid rewrite settings"):
        QueryRewriter(LOCAL, model=MODEL, timeout_seconds=0)
    monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
    with pytest.raises(ValueError, match="not permitted"):
        QueryRewriter(remote, model=MODEL, allow_remote=True)
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY")

    rewriter = QueryRewriter(remote, model=MODEL, allow_remote=True, auth_env="REWRITE_TEST_MISSING",
                             transport=httpx.MockTransport(lambda _r: pytest.fail("unexpected request")))
    monkeypatch.delenv("REWRITE_TEST_MISSING", raising=False)
    assert rewriter.rewrite("query")[:2] == ("missing_credential", [])
    monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
    assert rewriter.rewrite("query")[:2] == ("remote_disabled", [])
    assert rewriter.rewrite("  ")[:2] == ("empty_query", [])


def test_transport_errors_and_redirects_give_no_words():
    requested = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://elsewhere.example/v1"})

    assert _rewriter(redirect).rewrite("q")[:2] == ("transport_error", [])
    assert requested == [LOCAL]
    assert _rewriter(lambda _r: httpx.Response(500, text="no")).rewrite("q")[:2] == ("transport_error", [])
    big = httpx.Response(200, content=b"[" + b" " * 70_000 + b"]")
    assert _rewriter(lambda _r: big).rewrite("q")[:2] == ("invalid_response", [])


def test_timeout_is_bounded_and_keeps_one_inflight_slot():
    entered, release = threading.Event(), threading.Event()

    def respond(_request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json=_answer('["accepts"]'))

    rewriter = _rewriter(respond, timeout_seconds=0.02)
    try:
        assert rewriter.rewrite("q")[:2] == ("timeout", [])
        assert entered.is_set()
        assert rewriter.rewrite("q")[:2] == ("busy", [])
    finally:
        release.set()


def test_service_wiring_is_off_by_default_and_scoped(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    allowed, other = tmp_path / "allowed", tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    for name in ("ATTOCODE_INTEL_QUERY_REWRITE", "ATTOCODE_INTEL_RANKING_ALLOW_REMOTE",
                 "ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE"):
        monkeypatch.delenv(name, raising=False)
    off = CodeIntelService(str(allowed))
    assert off._query_rewriter is None and off._query_rewrite_status == "not_configured"
    assert off._rewrite_terms("anything") == []

    monkeypatch.setenv("ATTOCODE_INTEL_QUERY_REWRITE", "openrouter")
    # No remote consent: the configuration is refused, nothing is sent.
    assert CodeIntelService(str(allowed))._query_rewrite_status == "invalid_config"
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_ALLOW_REMOTE", "1")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE", str(allowed))
    service = CodeIntelService(str(allowed))
    rewriter = service._query_rewriter
    assert service._query_rewrite_status == "configured"
    assert (rewriter.endpoint, rewriter.model, rewriter.auth_env, rewriter.timeout_seconds, rewriter.remote) == (
        OPENROUTER_REWRITE["endpoint"], MODEL, "OPENROUTER_API_KEY", 1.5, True)
    assert CodeIntelService(str(other))._query_rewrite_status == "invalid_config"
    # Explicit configuration does not read the environment.
    assert CodeIntelService(str(allowed), CodeIntelConfig())._query_rewriter is None
    monkeypatch.setenv("ATTOCODE_INTEL_QUERY_REWRITE", "another")
    assert CodeIntelService(str(allowed))._query_rewrite_status == "invalid_config"


QUERY = "decide which media type the client wants"
MISS = "src/negotiation.py"


def _manager(tmp_path):
    # The miss shares no word with the question, only with the rewrite.
    for i in range(6):
        target = tmp_path / "src" / f"client_{i}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"def client_media_{i}():\n    return 'client media type'\n")
    (tmp_path / MISS).write_text("def accepts(offered):\n    return negotiate(offered)\n")
    mgr = SemanticSearchManager(str(tmp_path))
    mgr.search_candidates(QUERY)
    assert mgr.wait_for_body_index(timeout=30)
    return mgr


def test_extra_terms_add_one_body_list_and_nothing_else(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    try:
        calls = []
        original = SemanticSearchManager._body_search

        def counted(self, terms, *args, **kwargs):
            calls.append(list(terms))
            return original(self, terms, *args, **kwargs)

        monkeypatch.setattr(SemanticSearchManager, "_body_search", counted)
        trace: dict = {}
        base = mgr.search_candidates(QUERY, top_k=10, trace=trace)
        assert MISS not in trace["fused"] and len(calls) == 1
        # Empty or already-known words: same result, no extra search.
        assert mgr.search_candidates(QUERY, top_k=10, extra_terms=[]) == base
        assert mgr.search_candidates(QUERY, top_k=10, extra_terms=["Media", "client"]) == base
        assert len(calls) == 3
        trace = {}
        mgr.search_candidates(QUERY, top_k=10, trace=trace, extra_terms=["accepts", "negotiate", "client"])
        assert MISS in trace["fused"]
        assert calls[-1] == ["accepts", "negotiate"]
        assert MISS in [hit.file_path for hit in mgr.search(QUERY, top_k=10, extra_terms=["accepts"])]
    finally:
        mgr.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("words", [[], ["accepts"]])
async def test_gateway_rewrites_once_per_request(tmp_path, monkeypatch, words):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("def main(): pass\n")
    rewrites, searches = [], []
    manager = SimpleNamespace(
        warm=lambda: None,
        search=lambda *args, **kwargs: searches.append(kwargs) or [],
        search_candidates=lambda *args, **kwargs: searches.append(kwargs) or [],
        candidate_diagnostics=lambda: {"status": "ready"},
        format_results=lambda results, query: "",
    )
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    # The warmup wrapper can run the search twice.
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: (search(), search())[1])
    monkeypatch.setattr(CodeIntelService, "_rewrite_terms", lambda self, query: rewrites.append(query) or words)
    gateway = OperationGateway(str(tmp_path), "lean", watch=False)
    try:
        for mode in ("keyword", "auto"):
            response = await gateway.execute_mcp("semantic_search", {"query": "pick a type", "mode": mode})
            assert not response.isError, response.content
    finally:
        await gateway.close()
    assert rewrites == ["pick a type", "pick a type"]
    assert len(searches) == 4
    assert all(kwargs.get("extra_terms") == (words or None) for kwargs in searches)
