"""Source text discarded by coarse fitting can be restored without losing the page."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from attocode_intel.output import bounded_compact, bounded_search, compact_result, response_tokens


def source_page(kind="unicode", workspace="/repo"):
    body = (
        ('    needle = "' + "雪境風雷光雨山海" * 40 + '"\n')
        if kind == "unicode"
        else ("    # needle " + '"\\\t雪"' * 64 + "\r\n")
    )
    row = {
        "file_path": "src/worker.py",
        "name": "worker",
        "chunk_type": "function",
        "score": 0.5,
        "line": 9,
        "end_line": 12,
        "snippet": body,
        "snippet_start_line": 10,
        "snippet_end_line": 10,
        "snippet_truncated": True,
        "matched_terms": ["needle"],
        "match_fields": ["source"],
    }
    return {"workspace": workspace, "truncated": True}, {
        "query": "needle",
        "results": [row],
        "ranking": {"candidate_pool_count": 1, "returned_count": 1, "delivered_count": 1},
    }


@pytest.mark.parametrize("kind", ["unicode", "escaped"])
@pytest.mark.parametrize(
    "workspace", ["/repo", "/" + "long_checkout_name/" * 30], ids=["short-root", "long-root"]
)
def test_small_overflow_preserves_more_than_three_quarters_of_source(kind, workspace):
    metadata, data = source_page(kind, workspace)
    budget = response_tokens(compact_result(metadata, data)) - 1
    original = data["results"][0]["snippet"]
    legacy = bounded_compact(metadata, data, budget, search_results=[])
    old = json.loads(legacy.content[0].text)["data"]["results"][0]["snippet"]
    assert len(old) <= len(original) // 2
    actual = bounded_search(metadata, data, budget, all_results=data["results"])
    delivered = json.loads(actual.content[0].text)["data"]["results"][0]
    assert response_tokens(actual) <= budget
    assert len(delivered["snippet"]) > len(original) * 3 // 4, (
        "snippet restoration boundary: excessive source loss"
    )
    assert old in delivered["snippet"] and delivered["snippet"] in original
    assert delivered["snippet_start_line"] == delivered["snippet_end_line"] == 10


def test_fitting_search_payload_is_byte_identical():
    metadata, data = source_page()
    budget = response_tokens(compact_result(metadata, data)) + 1000
    legacy = bounded_compact(metadata, data, budget, search_results=[])
    actual = bounded_search(metadata, data, budget, all_results=data["results"])
    assert actual.model_dump() == legacy.model_dump()


def test_restoration_does_not_mutate_inputs():
    metadata, data = source_page()
    original = deepcopy((metadata, data))
    budget = response_tokens(compact_result(metadata, data)) - 1
    bounded_search(metadata, data, budget, all_results=data["results"])
    assert (metadata, data) == original


def test_delivered_floor_and_source_coordinates_remain_valid():
    metadata, data = source_page()
    budget = response_tokens(compact_result(metadata, data)) - 1
    legacy = bounded_compact(metadata, data, budget, search_results=[])
    old = json.loads(legacy.content[0].text)["data"]["results"]
    response = bounded_search(metadata, data, budget, all_results=data["results"])
    actual = json.loads(response.content[0].text)["data"]["results"]
    previews = {"snippet", "snippet_start_line", "snippet_end_line", "snippet_truncated"}
    assert len(actual) == len(old) == 1
    for before, after in zip(old, actual, strict=True):
        assert {k: v for k, v in before.items() if k not in previews} == {
            k: v for k, v in after.items() if k not in previews
        }
        assert before["snippet"] in after["snippet"] in data["results"][0]["snippet"]
        assert after["snippet_start_line"] == after["snippet_end_line"] == 10
    assert response_tokens(response) <= budget


def test_snippet_dispatch_reaches_committed_operator(tmp_path, monkeypatch):
    import attocode_intel

    from eval.quality import experiments, snippet_experiment

    root = tmp_path / "dispatch"
    (root / "evidence").mkdir(parents=True)
    monkeypatch.setenv("ATTOCODE_EXPERIMENT_ENGINE", str(Path(attocode_intel.__file__).parent))
    calls = []
    monkeypatch.setattr(snippet_experiment, "run", lambda selected: calls.append(selected))
    experiments.payload("snippet", root)
    assert calls == [root]
    assert json.loads((root / "evidence/controller-complete.json").read_bytes())["complete"] is True
