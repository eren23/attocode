"""SystemOne ranking is opt-in, bounded, and fail-closed to original order."""

from __future__ import annotations

import json
import threading

import httpx
import pytest
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchResult
from attocode_intel._internal.integrations.context.systemone_ranker import SystemOneChoiceReranker
from attocode_intel.config import CodeIntelConfig
from attocode_intel.service import CodeIntelService


def _answer(scores: list[float]) -> dict:
    return {
        "answers": {
            "best": {
                "choice": str(max(range(len(scores)), key=scores.__getitem__)),
                "confidence": max(scores),
                "probabilities": {str(i): score for i, score in enumerate(scores)},
            }
        }
    }


def _candidates() -> list[tuple[str, str, float]]:
    return [
        ("a", "File: a.py\n1: irrelevant", 0.9),
        ("b", "File: b.py\n1: handles generation", 0.8),
    ]


def test_local_choice_uses_one_bounded_typed_request_and_stable_probabilities(monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.url.path == "/v1/systemone"
        return httpx.Response(200, json=_answer([0.2, 0.8]))

    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        model="local-model",
        max_query_chars=5,
        max_excerpt_chars=12,
        transport=httpx.MockTransport(respond),
    )
    ranked = ranker.rerank_result("query should be bounded", _candidates(), top_k=2)
    assert ranked.reranked
    assert [row[0] for row in ranked.candidates] == ["b", "a"]
    assert len(seen) == 1
    assert seen[0]["model"] == "local-model"
    assert seen[0]["state"]["query"] == "query"
    assert seen[0]["questions"]["best"]["type"] == "choice"
    assert all(len(text) <= 12 for text in seen[0]["questions"]["best"]["criteria"].values())


@pytest.mark.parametrize(
    "response",
    [
        {"answers": {"best": {"choice": "0", "probabilities": {"0": 1.0}}}},
        _answer([float("nan"), 0.5]),
        _answer([0.2, 0.2]),
        {"answers": {"best": {"choice": "7", "probabilities": {"0": 0.4, "1": 0.6}}}},
        {"answers": {"best": {"choice": "0", "probabilities": {"0": 0.2, "1": 0.8}}}},
    ],
)
def test_invalid_distributions_preserve_original_order(response):
    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
    )
    result = ranker.rerank_result("query", _candidates(), top_k=2)
    assert result.candidates == _candidates()
    assert not result.reranked and result.fallback_reason == "invalid_response"


def test_unexpected_model_identity_is_rejected():
    response = {**_answer([0.2, 0.8]), "model": "different-model"}
    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        model="pinned-model",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
    )
    result = ranker.rerank_result("query", _candidates())
    assert not result.reranked and result.fallback_reason == "invalid_response"


def test_remote_requires_consent_and_https_and_redacts_known_secrets(monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    endpoint = "https://rank.example/v1/systemone"
    with pytest.raises(ValueError, match="not permitted"):
        SystemOneChoiceReranker(endpoint)
    with pytest.raises(ValueError, match="HTTPS"):
        SystemOneChoiceReranker("http://rank.example/v1/systemone", allow_remote=True)
    with pytest.raises(ValueError, match="HTTPS"):
        SystemOneChoiceReranker("http://localhost:8000/v1/systemone")
    with pytest.raises(ValueError, match="not permitted"):
        SystemOneChoiceReranker(endpoint, allow_remote=True, service_mode=True)
    with pytest.raises(ValueError, match="without credentials"):
        SystemOneChoiceReranker("http://user:password@127.0.0.1/v1/systemone")
    monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
    with pytest.raises(ValueError, match="not permitted"):
        SystemOneChoiceReranker(endpoint, allow_remote=True)
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY")
    monkeypatch.setenv("RANKING_TEST_KEY", "private-test-token")

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer private-test-token"
        body = json.loads(request.content)
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in json.dumps(body)
        assert "[REDACTED:" in json.dumps(body)
        return httpx.Response(200, json=_answer([0.8, 0.2]))

    ranker = SystemOneChoiceReranker(
        endpoint,
        auth_env="RANKING_TEST_KEY",
        allow_remote=True,
        transport=httpx.MockTransport(respond),
    )
    result = ranker.rerank_result(
        "find sk-abcdefghijklmnopqrstuvwxyz",
        [("a", "File: a.py\nsk-abcdefghijklmnopqrstuvwxyz", 0.8), ("b", "File: b.py\nclean", 0.7)],
    )
    assert result.reranked
    monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
    assert ranker.rerank_result("query", _candidates()).fallback_reason == "remote_disabled"


def test_default_deadline_reflects_local_and_remote_latency(monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    local = SystemOneChoiceReranker("http://127.0.0.1:8000/v1/systemone")
    remote = SystemOneChoiceReranker("https://rank.example/v1/systemone", allow_remote=True)
    assert local.timeout_seconds == 5.0
    assert remote.timeout_seconds == 0.8


def test_missing_credential_does_not_send_source(monkeypatch):
    monkeypatch.delenv("RANKING_TEST_MISSING", raising=False)
    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        auth_env="RANKING_TEST_MISSING",
        transport=httpx.MockTransport(lambda _request: pytest.fail("unexpected request")),
    )
    result = ranker.rerank_result("query", _candidates())
    assert not result.reranked and result.fallback_reason == "missing_credential"


def test_ranking_environment_config_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "systemone")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_ENDPOINT", "http://127.0.0.1:8000/v1/systemone")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_MODEL", "selected-model")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_TIMEOUT_MS", "950")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_MAX_CANDIDATES", "8")
    config = CodeIntelConfig.from_env()
    assert config.ranking_provider == "systemone"
    assert config.ranking_model == "selected-model"
    assert config.ranking_timeout_ms == 950
    assert config.ranking_max_candidates == 8
    service = CodeIntelService(str(tmp_path))
    assert service._systemone_ranker.model == "selected-model"
    assert service._systemone_ranker.max_candidates == 8


def test_remote_opt_in_is_scoped_to_one_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    config = CodeIntelConfig(
        ranking_provider="systemone",
        ranking_endpoint="https://rank.example/v1/systemone",
        ranking_allow_remote=True,
        ranking_remote_workspace=str(allowed),
    )
    assert CodeIntelService(str(allowed), config)._systemone_ranker.remote is True
    denied = CodeIntelService(str(other), config)
    assert denied._systemone_ranker is None
    assert denied._systemone_status == "invalid_config"

    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "systemone")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_ENDPOINT", "https://rank.example/v1/systemone")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_ALLOW_REMOTE", "1")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE", str(allowed))
    assert CodeIntelService(str(allowed))._systemone_ranker.remote is True
    assert CodeIntelService(str(other))._systemone_ranker is None


def test_redirect_does_not_send_source_to_a_second_endpoint():
    requested = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://elsewhere.example/v1/systemone"})

    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        transport=httpx.MockTransport(respond),
    )
    result = ranker.rerank_result("query", _candidates())
    assert not result.reranked and result.fallback_reason == "transport_error"
    assert requested == ["http://127.0.0.1:8000/v1/systemone"]


def test_timeout_is_bounded_and_keeps_one_inflight_slot():
    entered = threading.Event()
    release = threading.Event()

    def respond(_request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json=_answer([0.2, 0.8]))

    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        timeout_seconds=0.02,
        transport=httpx.MockTransport(respond),
    )
    try:
        first = ranker.rerank_result("query", _candidates())
        assert entered.is_set()
        assert first.fallback_reason == "timeout"
        second = ranker.rerank_result("query", _candidates())
        assert second.fallback_reason == "busy"
    finally:
        release.set()


def test_service_ranks_distinct_files_and_preserves_retrieval_scores(tmp_path):
    for name, body in (
        ("a.py", "def old():\n    return 'unrelated'\n"),
        ("b.py", "def refresh():\n    return 'cache generation'\n"),
        ("c.py", "def other():\n    return 'something'\n"),
    ):
        (tmp_path / name).write_text(body)
    rows = [
        SemanticSearchResult("a.py", "function", "old", "old", 0.9, 1, 2),
        SemanticSearchResult("a.py", "file", "a", "old", 0.85, 1, 2),
        SemanticSearchResult("b.py", "function", "refresh", "cache generation", 0.8, 1, 2),
        SemanticSearchResult("c.py", "function", "other", "other", 0.7, 1, 2),
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        criteria = json.loads(request.content)["questions"]["best"]["criteria"]
        assert list(criteria) == ["0", "1", "2"]
        assert "cache generation" in criteria["1"]
        return httpx.Response(200, json=_answer([0.1, 0.8, 0.1]))

    cfg = CodeIntelConfig(
        ranking_provider="systemone", ranking_endpoint="http://127.0.0.1:8000/v1/systemone"
    )
    service = CodeIntelService(str(tmp_path), cfg)
    assert service._systemone_ranker.timeout_seconds == 5.0
    service._systemone_ranker._transport = httpx.MockTransport(respond)
    ranked, metadata = service._rank_search_results("cache generation", rows, 4)
    assert [row.file_path for row in ranked] == ["b.py", "a.py", "c.py", "a.py"]
    assert [row.score for row in ranked] == [0.8, 0.9, 0.7, 0.85]
    assert metadata["method"] == "systemone_choice"
    assert metadata["reranked_count"] == 3
    assert metadata["remote"] is False


def test_unavailable_source_and_bad_configuration_do_not_call_model(tmp_path):
    row = SemanticSearchResult("absent.py", "file", "absent", "stale index", 0.5)
    (tmp_path / "present.py").write_text("def present():\n    pass\n")
    present = SemanticSearchResult("present.py", "function", "present", "present", 0.4)
    cfg = CodeIntelConfig(
        ranking_provider="systemone", ranking_endpoint="http://127.0.0.1:8000/v1/systemone"
    )
    service = CodeIntelService(str(tmp_path), cfg)
    result, metadata = service._rank_search_results("query", [row, present], 1)
    assert result == [row] and metadata["fallback_reason"] == "evidence_unavailable"

    invalid = CodeIntelService(
        str(tmp_path),
        CodeIntelConfig(
            ranking_provider="systemone",
            ranking_endpoint="https://rank.example/v1/systemone",
        ),
    )
    result, metadata = invalid._rank_search_results("query", [row], 1)
    assert result == [row] and metadata["fallback_reason"] == "invalid_config"

    off = CodeIntelService(str(tmp_path), CodeIntelConfig(ranking_provider="off"))
    result, metadata = off._rank_search_results("query", [row], 1)
    assert result == [row] and metadata["model_status"] == "off"
