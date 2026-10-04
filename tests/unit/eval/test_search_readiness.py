"""Meta-harness search metrics must not treat cold indexes as failed retrieval."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_meta_harness_runners_wait_and_separate_cold_start(monkeypatch, tmp_path):
    import attocode.code_intel.service as service_module
    from eval import search_quality
    from eval.meta_harness import experiment_search_quality
    from eval.meta_harness.evaluator import CodeIntelBenchEvaluator

    class FakeManager:
        ready = False

        def candidate_diagnostics(self):
            return {"status": "ready" if self.ready else "warming"}

        def wait_for_body_index(self, timeout):
            self.ready = True
            return True

    class FakeService:
        def __init__(self, repo_path):
            self.manager = FakeManager()

        def _get_semantic_search(self):
            return self.manager

        def semantic_search(self, query, top_k=10):
            if not self.manager.ready:
                return "Search index warming; retry shortly. Missing results do not prove absence."
            return "1. [function] handler.py:1-3 — handler (score: 1.000)"

    monkeypatch.setattr(service_module, "CodeIntelService", FakeService)
    monkeypatch.setattr(experiment_search_quality, "CodeIntelService", FakeService)
    monkeypatch.setitem(search_quality.REPO_CONFIGS, "fixture", str(tmp_path))
    monkeypatch.setattr(search_quality, "load_ground_truth", lambda _repo: [
        {"query": "handler", "relevant_files": ["handler.py"]},
    ])
    monkeypatch.setattr(experiment_search_quality, "load_ground_truth", search_quality.load_ground_truth)
    config = SimpleNamespace(apply_to_service=lambda _svc: None)

    meta = CodeIntelBenchEvaluator(search_repos=["fixture"])
    meta_result = meta._run_search_quality(config)
    assert meta_result["per_repo"]["fixture"]["mrr"] == 1.0
    assert meta_result["per_repo"]["fixture"]["search_cold_start_ms"] >= 0

    experiment = experiment_search_quality.evaluate_with_config(config, ["fixture"])
    assert experiment[0].mrr == 1.0
    assert experiment[0].search_cold_start_ms >= 0


@pytest.mark.asyncio
async def test_meta_harness_cannot_accept_bench_only_when_search_is_warming(
    monkeypatch, tmp_path,
):
    from eval.meta_harness.evaluator import CodeIntelBenchEvaluator

    evaluator = CodeIntelBenchEvaluator()
    monkeypatch.setattr(
        evaluator, "_run_search_quality",
        lambda _config: {"error": "fixture: search_index_not_ready: timeout", "composite": None},
    )
    monkeypatch.setattr(evaluator, "_run_mcp_bench", lambda _config: {"composite": 1.0})
    result = await evaluator.evaluate(str(tmp_path))
    assert not result.success
    assert "search_index_not_ready" in result.error
