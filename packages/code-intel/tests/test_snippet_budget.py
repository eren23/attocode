"""Source text discarded by coarse fitting can be restored without losing the page."""

from __future__ import annotations

import json
from copy import deepcopy

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


def legacy_search(monkeypatch, metadata, data, budget, follow_up=None):
    from attocode_intel import output

    with monkeypatch.context() as patch:
        patch.setattr(output, "_restore_search_snippets", lambda result, *args, **kwargs: result)
        return output.bounded_search(
            metadata, data, budget, all_results=data["results"], follow_up=follow_up
        )


def assert_protected_page(before, after):
    old = json.loads(before.content[0].text)
    new = json.loads(after.content[0].text)
    assert len(old["data"]["results"]) == len(new["data"]["results"])
    previews = {"snippet", "snippet_start_line", "snippet_end_line", "snippet_truncated"}
    for previous, current in zip(old["data"]["results"], new["data"]["results"], strict=True):
        assert {k: v for k, v in previous.items() if k not in previews} == {
            k: v for k, v in current.items() if k not in previews
        }
        assert previous["snippet"] in current["snippet"]
        if previous["snippet_start_line"] is None:
            assert current["snippet_start_line"] is current["snippet_end_line"] is None
        else:
            assert current["snippet_start_line"] <= previous["snippet_start_line"]
            assert current["snippet_end_line"] >= previous["snippet_end_line"]
    assert {k: v for k, v in old["data"].items() if k != "results"} == {
        k: v for k, v in new["data"].items() if k != "results"
    }
    assert {k: v for k, v in old["metadata"].items() if k not in {"truncated", "omitted"}} == {
        k: v for k, v in new["metadata"].items() if k not in {"truncated", "omitted"}
    }


def many_source_rows(count=5):
    metadata, data = source_page()
    row = data["results"][0]
    data["results"] = [
        {**deepcopy(row), "file_path": f"src/worker_{i}.py", "score": 1 - i / 100}
        for i in range(count)
    ]
    data["ranking"].update(candidate_pool_count=count, returned_count=count, delivered_count=count)
    return metadata, data


@pytest.mark.parametrize("budget", [600, 1200, 2000, 8000])
def test_complete_fitted_prefix_and_continuation_are_protected(monkeypatch, budget):
    metadata, data = many_source_rows()
    follow = {
        "tool": "semantic_search",
        "arguments": {
            "query": "needle",
            "top_k": 10,
            "workspace": metadata["workspace"],
            "max_tokens": 16000,
        },
        "reruns_current_index": True,
        "reason": "search_deeper",
    }
    before = legacy_search(monkeypatch, metadata, data, budget, follow)
    after = bounded_search(metadata, data, budget, all_results=data["results"], follow_up=follow)
    assert_protected_page(before, after)
    assert response_tokens(after) <= budget


def test_restoration_has_a_global_serialization_probe_cap(monkeypatch):
    from attocode_intel import output

    metadata, data = many_source_rows(24)
    budget = 8000
    before = legacy_search(monkeypatch, metadata, data, budget)
    real_count = output.response_tokens
    calls = []

    def count(result):
        calls.append(result)
        return real_count(result)

    monkeypatch.setattr(output, "response_tokens", count)
    after = output._restore_search_snippets(
        before, data["results"], budget, upstream_truncated=True
    )
    assert 0 < len(calls) <= 12
    assert real_count(after) <= budget
    assert_protected_page(before, after)


def test_nonmonotone_probes_cannot_admit_overbudget_or_lose_text(monkeypatch):
    from attocode_intel import output

    metadata, data = source_page()
    budget = response_tokens(compact_result(metadata, data)) - 1
    before = legacy_search(monkeypatch, metadata, data, budget)
    real_count = output.response_tokens
    calls = []

    def conservative_nonmonotone(result):
        actual = real_count(result)
        measured = max(actual, budget + 1) if len(calls) % 2 else actual
        calls.append((actual, measured))
        return measured

    monkeypatch.setattr(output, "response_tokens", conservative_nonmonotone)
    after = output._restore_search_snippets(
        before, data["results"], budget, upstream_truncated=True
    )
    assert any(measured > actual for actual, measured in calls)
    assert len(calls) <= 12 and real_count(after) <= budget
    assert_protected_page(before, after)


@pytest.mark.parametrize("upstream", [False, True])
@pytest.mark.parametrize("unrelated", [False, True])
def test_full_restoration_cleans_only_its_own_omission(upstream, unrelated):
    from attocode_intel.output import _restore_search_snippets

    metadata, data = source_page()
    original = data["results"][0]
    original.update(line=10, end_line=10, snippet_truncated=False)
    rows = deepcopy(data["results"])
    data["results"][0].update(snippet=original["snippet"][:40], snippet_truncated=True)
    metadata["truncated"] = True
    metadata["omitted"] = {"data.results.snippet": "shortened"}
    if unrelated:
        metadata["omitted"]["data.other"] = "shortened"
    before = compact_result(metadata, data)
    after = _restore_search_snippets(before, rows, 8000, upstream_truncated=upstream)
    page = json.loads(after.content[0].text)
    assert page["data"]["results"] == rows
    assert not page["metadata"].get("omitted", {}).get("data.results.snippet")
    assert page["metadata"]["truncated"] is (upstream or unrelated)
    assert bool(page["metadata"].get("omitted", {}).get("data.other")) is unrelated
    assert_protected_page(before, after)
    assert response_tokens(after) <= 8000


def test_repeated_text_keeps_corresponding_source_rows():
    from attocode_intel.output import _restore_search_snippets

    metadata, data = many_source_rows(2)
    for i, row in enumerate(data["results"]):
        row.update(
            file_path="src/worker.py",
            line=10 + i * 10,
            end_line=10 + i * 10,
            snippet_start_line=10 + i * 10,
            snippet_end_line=10 + i * 10,
            snippet=row["snippet"] + f"# source marker {i}",
        )
        row["snippet_end_line"] += 1
        row["end_line"] += 1
    originals = deepcopy(data["results"])
    for row in data["results"]:
        row.update(snippet=row["snippet"][:32], snippet_end_line=row["snippet_start_line"])
    before = compact_result(metadata, data)
    after = _restore_search_snippets(before, originals, 8000, upstream_truncated=True)
    assert json.loads(after.content[0].text)["data"]["results"] == originals
    assert_protected_page(before, after)


async def test_actual_gateway_preserves_source_and_budget_after_restoration(tmp_path, monkeypatch):
    import asyncio
    import time

    from attocode_intel.gateway import OperationGateway
    from attocode_intel.service import CodeIntelService

    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    body = 'def worker():\n    needle = "' + "雪境風雷光雨山海" * 80 + '"\n    return needle\n'
    (tmp_path / "worker.py").write_text(body)
    service = CodeIntelService(str(tmp_path))
    manager = service._get_semantic_search()
    manager.warm()
    assert manager.wait_for_body_index(timeout=10)
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    arguments = {"query": "needle", "top_k": 24, "max_tokens": 8000}
    try:
        deadline = time.monotonic() + 20
        while True:
            full = await gateway.execute_mcp("semantic_search", arguments)
            assert not full.isError
            page = json.loads(full.content[0].text)
            if page["data"]["ranking"]["index"]["status"] == "ready":
                break
            assert time.monotonic() < deadline
            await asyncio.sleep(0.05)
        budget = response_tokens(full) - 1
        from attocode_intel import output

        with monkeypatch.context() as patch:
            patch.setattr(output, "_restore_search_snippets", lambda result, *a, **k: result)
            before = await gateway.execute_mcp(
                "semantic_search", {**arguments, "max_tokens": budget}
            )
        after = await gateway.execute_mcp("semantic_search", {**arguments, "max_tokens": budget})
        assert not before.isError and not after.isError
        assert_protected_page(before, after)
        assert response_tokens(after) <= budget
        for hit in json.loads(after.content[0].text)["data"]["results"]:
            assert hit["file_path"] == "worker.py"
            lines = body.splitlines(keepends=True)
            assert hit["snippet"] in "".join(
                lines[hit["snippet_start_line"] - 1 : hit["snippet_end_line"]]
            )
    finally:
        await gateway.close()
        manager.close()
