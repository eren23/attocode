"""Tests for the frozen-pool decision/reranker trial adapter."""

from __future__ import annotations

import httpx
import pytest
from attocode_intel._internal.integrations.context.systemone_ranker import SystemOneChoiceReranker

from eval.model_rerank_trial import _choice_scores, _excerpt, _select, _systemone_http_scores


def test_excerpt_is_bounded_and_scoped(tmp_path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "config.py").write_text(
        "other = 1\n" * 20 + "def load_config():\n    return parse_toml()\n"
    )
    text = _excerpt(tmp_path, "src/config.py", "config loading")
    assert text.startswith("File: src/config.py")
    assert "load_config" in text
    assert len(text) <= 1350
    with pytest.raises(ValueError, match="outside repository"):
        _excerpt(tmp_path, "../outside.py", "config loading")


def test_select_requires_requested_case() -> None:
    pool = {"repos": [{"repo": "demo", "queries": [{"query": "config loading"}]}]}
    assert len(_select(pool, {"demo::config loading"})) == 1
    assert len(_select(pool, set(), {"demo"})) == 1
    with pytest.raises(ValueError, match="absent from pool"):
        _select(pool, {"demo::missing"})
    with pytest.raises(ValueError, match="Repositories absent"):
        _select(pool, set(), {"unknown"})


def test_choice_scores_preserves_full_probability_order() -> None:
    class Model:
        def system_one(self, *, state, questions):
            assert state["query"] == "config loading"
            assert list(questions["best"]["criteria"]) == ["0", "1", "2"]
            return {"answers": {"best": {"probabilities": {"0": 0.1, "1": 0.7, "2": 0.2}}}}

    scores, failures = _choice_scores(
        Model(), "config loading", ["a", "b", "c"], ["one", "two", "three"], remote=False
    )
    assert scores == [0.1, 0.7, 0.2]
    assert failures == 0


def test_choice_failure_is_explicit() -> None:
    class Model:
        def system_one(self, *, state, questions):
            return {"answers": {"best": {"probabilities": {"0": 1.0}}}}

    scores, failures = _choice_scores(Model(), "query", ["a", "b"], ["one", "two"], remote=False)
    assert scores == [0.5, 0.5]
    assert failures == 2


def test_http_trial_uses_production_adapter_and_preserves_fallback() -> None:
    def response(_request):
        return httpx.Response(
            200,
            json={
                "answers": {
                    "best": {
                        "choice": "1",
                        "probabilities": {"0": 0.2, "1": 0.8},
                    }
                }
            },
        )

    ranker = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        transport=httpx.MockTransport(response),
    )
    scores, failures, reason = _systemone_http_scores(
        ranker,
        "find cache",
        ["a.py", "b.py"],
        ["File: a.py", "File: b.py"],
    )
    assert scores == [0.2, 0.8] and failures == 0 and reason is None

    invalid = SystemOneChoiceReranker(
        "http://127.0.0.1:8000/v1/systemone",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    scores, failures, reason = _systemone_http_scores(
        invalid,
        "find cache",
        ["a.py", "b.py"],
        ["File: a.py", "File: b.py"],
    )
    assert scores == [0.5, 0.5] and failures == 2 and reason == "transport_error"
