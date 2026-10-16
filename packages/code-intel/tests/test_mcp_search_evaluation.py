"""The quality operator must measure the consumer's actual budgeted output."""
from copy import deepcopy

import pytest
from attocode_intel.gateway import OperationGateway

from eval.quality.mcp_search import compare, evidence_hits, observe


def test_visible_evidence_requires_literal_quote_in_the_same_file_and_snippet_lines():
    evidence = [{"file": "a.py", "line": 40, "quote": "return answer"}]
    hit = {"file_path": "a.py", "line": 1, "end_line": 100, "snippet": "return answer",
           "snippet_start_line": 2, "snippet_end_line": 3}
    assert evidence_hits([hit], evidence) == {"files": [0], "ranges": [0], "visible": []}
    hit.update(snippet_start_line=40, snippet_end_line=40)
    assert evidence_hits([hit], evidence)["visible"] == [0]
    hit["file_path"] = "b.py"
    assert evidence_hits([hit], evidence) == {"files": [], "ranges": [], "visible": []}


@pytest.mark.asyncio
async def test_operator_uses_gateway_depth_hydration_and_budget(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager

    (tmp_path / "quota.py").write_text("def quota():\n    return 'quota limit'\n")
    depths = []
    search = SemanticSearchManager.search_candidates
    def record(self, query, top_k=50, file_filter="", **kwargs):
        depths.append(top_k)
        return search(self, query, top_k=top_k, file_filter=file_filter, **kwargs)
    monkeypatch.setattr(SemanticSearchManager, "search_candidates", record)
    gateway = OperationGateway(str(tmp_path), profile="daily", watch=False)
    try:
        result = await observe(gateway, "quota limit", top_k=5, budget=2000)
        assert depths and min(depths) >= 24
        data = result["response"]["data"]
        assert data["ranking"]["delivered_count"] == len(data["results"])
        assert result["request"]["max_tokens"] == 2000
        assert any("quota limit" in h["snippet"] for h in data["results"])
        assert result["pre_hydration_diagnostic"]
    finally:
        await gateway.close()


def paired_rows():
    row = {"id": "one", "query": "quota", "evidence": [{"file": "a"}], "inspection_hits": [], "pages": {}}
    for page in ("5", "24", "scoped"):
        row["pages"][page] = {"request": {"top_k": page, "max_tokens": 2000}, "seconds": .01,
                              "hits": {"files": [0], "ranges": [0], "visible": [0]}}
    return [row]


@pytest.mark.parametrize("failure", ["missing", "duplicate", "judgment", "request", "files", "visible", "latency"])
def test_acceptance_rejects_invalid_or_regressed_delivery(failure):
    baseline = paired_rows()
    candidate = deepcopy(baseline)
    if failure == "missing":
        candidate = []
    elif failure == "duplicate":
        candidate *= 2
    elif failure == "judgment":
        candidate[0]["query"] = "other"
    elif failure == "request":
        candidate[0]["pages"]["5"]["request"]["max_tokens"] = 4000
    elif failure in {"files", "visible"}:
        candidate[0]["pages"]["5"]["hits"][failure] = []
    else:
        candidate[0]["pages"]["5"]["seconds"] = .2
    if failure in {"missing", "duplicate", "judgment", "request"}:
        with pytest.raises(ValueError):
            compare(baseline, candidate, ["one"])
    else:
        assert not compare(baseline, candidate, ["one"])["passed"]


def test_paired_omission_of_a_frozen_question_is_rejected():
    with pytest.raises(ValueError):
        compare(paired_rows(), paired_rows(), ["one", "missing-from-both"])


@pytest.mark.parametrize("split", ["development", "validation", "confirmation"])
def test_frozen_delivery_decisions_replay_from_hash_bound_observations(split):
    import gzip
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evals"
    stem = "2026-10-16-search-correctness"
    recorded = json.loads((root / "results" / f"{stem}-decision.json").read_text())
    candidates = root / "designs" / f"{stem}-candidates"
    manifest = json.loads((candidates / "manifest.json").read_text())
    for entry in manifest["arms"].values():
        packed = (candidates / entry["patch_file"]).read_bytes()
        assert hashlib.sha256(packed).hexdigest() == entry["compressed_sha256"]
        assert hashlib.sha256(gzip.decompress(packed)).hexdigest() == entry["patch_sha256"]
    compressed = (root / "results" / f"{stem}-observations.json.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == recorded["artifact"]["gzip_sha256"]
    raw = gzip.decompress(compressed)
    assert len(raw) == recorded["artifact"]["raw_bytes"] < 5_000_000
    assert hashlib.sha256(raw).hexdigest() == recorded["artifact"]["raw_sha256"]
    questions = (root / "designs" / f"{stem}-{split}.json").read_bytes()
    design = json.loads(questions)
    expected = [q["id"] for group in design["repositories"] for q in group["queries"]]
    rows = {}
    for item in json.loads(raw):
        if item["split"] != split:
            continue
        observation = item["observation"]
        assert observation["questions_sha256"] == hashlib.sha256(questions).hexdigest()
        rows.setdefault(observation["arm"], []).extend(observation["queries"])
    for arm, decision in recorded["splits"][split].items():
        assert compare(rows["baseline"], rows[arm], expected) == decision
    if split == "confirmation":
        assert all(d["passed"] for d in recorded["splits"][split].values())
