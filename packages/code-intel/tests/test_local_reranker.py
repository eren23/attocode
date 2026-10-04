"""Offline, bounded, opt-in reranking; tests never download model weights."""

import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest
from attocode_intel._internal.integrations.context.reranker import (
    LocalCrossEncoderReranker,
    model_tree_sha256,
)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    path = tmp_path / "installed-model"
    path.mkdir()
    (path / "config.json").write_text('{"model_type":"bert"}')
    (path / "model.safetensors").write_bytes(b"preinstalled weights")
    return path


def _wait_ready(reranker: LocalCrossEncoderReranker) -> None:
    deadline = time.monotonic() + 2
    while reranker.status == "loading" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert reranker.status == "ready"


def _fake_sentence_transformers(monkeypatch, factory):
    module = ModuleType("sentence_transformers")
    module.CrossEncoder = factory
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_local_prewarm_is_explicit_offline_and_bounded(monkeypatch, model_dir):
    seen = {}

    class FakeModel:
        def __init__(self, path, **kwargs):
            seen["load"] = (path, kwargs)

        def predict(self, pairs, **kwargs):
            seen["pairs"] = pairs
            return [0.1, 0.9]

    _fake_sentence_transformers(monkeypatch, FakeModel)
    reranker = LocalCrossEncoderReranker(
        model_dir, model_tree_sha256(model_dir), max_candidates=2,
        max_query_chars=4, max_excerpt_chars=5,
    )
    candidates = [("first", "first long excerpt", 10.0),
                  ("second", "second long excerpt", 9.0),
                  ("tail", "third long excerpt", 8.0)]
    cold = reranker.rerank_result("query", candidates, top_k=3)
    assert cold.candidates == candidates and cold.fallback_reason == "cold"
    assert "load" not in seen
    assert reranker.start_prewarm() is True
    assert reranker.start_prewarm() is False
    _wait_ready(reranker)
    assert seen["load"] == (str(model_dir), {"local_files_only": True, "trust_remote_code": False})
    result = reranker.rerank_result("query", candidates, top_k=3)
    assert result.reranked and result.fallback_reason is None
    assert [item[0] for item in result.candidates] == ["second", "first", "tail"]
    assert seen["pairs"] == [("quer", "first"), ("quer", "secon")]


def test_fingerprint_failure_does_not_load_weights(monkeypatch, model_dir):
    def forbidden(*args, **kwargs):
        pytest.fail("model loader should not run after digest mismatch")

    _fake_sentence_transformers(monkeypatch, forbidden)
    reranker = LocalCrossEncoderReranker(model_dir, "0" * 64)
    assert reranker.start_prewarm()
    deadline = time.monotonic() + 2
    while reranker.status == "loading" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert reranker.status == "failed"
    assert reranker.rerank_result("query", [("id", "body", 1)]).fallback_reason == "failed"
    assert not reranker.start_prewarm()


def test_timeout_stays_busy_until_inflight_prediction_finishes(monkeypatch, model_dir):
    entered = threading.Event()
    release = threading.Event()

    class SlowModel:
        def __init__(self, *args, **kwargs):
            pass

        def predict(self, pairs, **kwargs):
            entered.set()
            assert release.wait(2)
            return [0.7]

    _fake_sentence_transformers(monkeypatch, SlowModel)
    reranker = LocalCrossEncoderReranker(
        model_dir, model_tree_sha256(model_dir), timeout_seconds=0.02,
    )
    reranker.start_prewarm()
    _wait_ready(reranker)
    candidates = [("id", "source snippet", 1.0)]
    try:
        first = reranker.rerank_result("query", candidates)
        assert entered.is_set()
        assert first.fallback_reason == "timeout" and first.candidates == candidates
        second = reranker.rerank_result("query", candidates)
        assert second.fallback_reason == "busy" and second.candidates == candidates
    finally:
        release.set()


@pytest.mark.parametrize("scores", [[float("nan")], [], None])
def test_invalid_predictions_fall_back(monkeypatch, model_dir, scores):
    class InvalidModel:
        def __init__(self, *args, **kwargs):
            pass

        def predict(self, pairs, **kwargs):
            return scores

    _fake_sentence_transformers(monkeypatch, InvalidModel)
    reranker = LocalCrossEncoderReranker(model_dir, model_tree_sha256(model_dir))
    reranker.start_prewarm()
    _wait_ready(reranker)
    candidates = [("id", "source", 1.0)]
    result = reranker.rerank_result("query", candidates)
    assert result.candidates == candidates and result.fallback_reason == "prediction_failed"


def test_model_pin_rejects_symlinks_and_relative_paths(model_dir, tmp_path):
    with pytest.raises(ValueError):
        LocalCrossEncoderReranker("relative-model", "0" * 64)
    (model_dir / "external").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        model_tree_sha256(model_dir)
