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
        result = await observe(gateway, "quota limit", top_k=5, budget=2000, capture_generation=True)
        assert depths and min(depths) >= 24
        data = result["response"]["data"]
        assert data["ranking"]["delivered_count"] == len(data["results"])
        assert result["request"]["max_tokens"] == 2000
        assert any("quota limit" in h["snippet"] for h in data["results"])
        assert result["pre_hydration_diagnostic"]
        assert {r["stage"] for r in result["generation_diagnostic"]} == {"keyword", "body", "file_bm25"}
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


@pytest.mark.parametrize("split", ["development", "validation"])
def test_search_batch_decisions_replay_from_hash_bound_observations(split):
    import gzip
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evals"
    stem = "2026-10-17-search-batch"
    recorded = json.loads((root / "results" / f"{stem}-decision.json").read_text())
    patch = (root / "designs" / f"{stem}-candidate.patch.gz").read_bytes()
    assert hashlib.sha256(patch).hexdigest() == recorded["candidate"]["compressed_sha256"]
    assert hashlib.sha256(gzip.decompress(patch)).hexdigest() == recorded["candidate"]["patch_sha256"]
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
        if item["split"] == split:
            assert item["observation"]["questions_sha256"] == hashlib.sha256(questions).hexdigest()
            rows.setdefault(item["observation"]["arm"], []).extend(item["observation"]["queries"])
    decision = recorded["splits"][split]
    assert compare(rows["a0"], rows["f"], expected) == decision["fixes"]
    assert compare(rows["f"], rows["c"], expected) == decision["candidate"]
    # The rejection: changed exact-symbol controls (development) and an individual loss (validation).
    controls = [q for q in rows["f"] if q["category"] == "control"]
    by_id = {q["id"]: q for q in rows["c"]}
    changed = [q["id"] for q in controls for page in q["pages"]
               if q["pages"][page]["response"]["data"]["results"]
               != by_id[q["id"]]["pages"][page]["response"]["data"]["results"]]
    assert bool(changed) == (not decision["candidate_controls_identical"])
    assert not recorded["candidate_rules"]["controls_identical"]
    assert not recorded["candidate_rules"]["zero_individual_losses"]


@pytest.mark.parametrize("split", ["development", "validation", "previous_development", "previous_validation"])
def test_file_coverage_decisions_replay_from_hash_bound_observations(split):
    import gzip
    import hashlib
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evals"
    stem = "2026-10-17-file-coverage"
    recorded = json.loads((root / "results" / f"{stem}-decision.json").read_text())
    for patch in recorded["patches"].values():
        data = (root / patch["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == patch["compressed_sha256"]
        assert hashlib.sha256(gzip.decompress(data)).hexdigest() == patch["patch_sha256"]
    compressed = (root / "results" / f"{stem}-observations.json.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == recorded["artifact"]["gzip_sha256"]
    raw = gzip.decompress(compressed)
    assert len(raw) == recorded["artifact"]["raw_bytes"] < 5_000_000
    assert hashlib.sha256(raw).hexdigest() == recorded["artifact"]["raw_sha256"]
    decision = recorded["splits"][split]
    questions = (root / decision["questions_file"]).read_bytes()
    assert hashlib.sha256(questions).hexdigest() == decision["questions_sha256"]
    rows = {}
    for item in json.loads(raw):
        if item["split"] == split:
            assert item["observation"]["questions_sha256"] == decision["questions_sha256"]
            rows.setdefault(item["observation"]["arm"], []).extend(item["observation"]["queries"])
    expected = [q["id"] for q in rows["B"]]
    base = {q["id"]: q for q in rows["B"]}
    test_word = re.compile(r"\btest(?:s|ed|ing)?\b", re.I)
    for arm, record in decision.items():
        if arm in ("questions_file", "questions_sha256"):
            continue
        assert compare(rows["B"], rows[arm], expected) == record["compare"]
        same = {(q["id"], page): q["pages"][page]["response"]["data"]["results"]
                == base[q["id"]]["pages"][page]["response"]["data"]["results"]
                for q in rows[arm] for page in q["pages"]}
        assert record["controls_identical"] == all(
            ok for (qid, _), ok in same.items() if base[qid]["category"] == "control")
        assert record["no_test_word_identical"] == all(
            ok for (qid, _), ok in same.items() if not test_word.search(base[qid]["query"]))
    # Both rejections: individual losses for C2f, implementation-file losses for T.
    assert not recorded["c2_rules"]["zero_individual_losses"]
    assert not recorded["c2_rules"]["validation_first_five_gain_at_least_1"]
    assert not recorded["t_rules"]["test_intent_zero_individual_losses"]
    assert recorded["t_rules"]["negative_control_identical"]


def _replay_slot_decision(stem, candidate_arm, split, baseline="B"):
    """Recompute every recorded comparison and identity check from the hash-bound public files."""
    import gzip
    import hashlib
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evals"
    recorded = json.loads((root / "results" / f"{stem}-decision.json").read_text())
    candidate = (root / "designs" / f"{stem}-candidate.json").read_bytes()
    assert hashlib.sha256(candidate).hexdigest() == recorded["candidate_record_sha256"]
    assert json.loads(candidate)["candidate"]["engine_sha256"] == recorded["engine_sha256"][candidate_arm]
    for patch in recorded["patches"].values():
        data = (root / patch["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == patch["compressed_sha256"]
        assert hashlib.sha256(gzip.decompress(data)).hexdigest() == patch["patch_sha256"]
    compressed = (root / "results" / f"{stem}-observations.json.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == recorded["artifact"]["gzip_sha256"]
    raw = gzip.decompress(compressed)
    assert len(raw) == recorded["artifact"]["raw_bytes"]
    assert hashlib.sha256(raw).hexdigest() == recorded["artifact"]["raw_sha256"]
    decision = recorded["splits"][split]
    questions = (root / decision["questions_file"]).read_bytes()
    assert hashlib.sha256(questions).hexdigest() == decision["questions_sha256"]
    rows = {}
    for item in json.loads(raw):
        if item["split"] == split:
            assert item["observation"]["questions_sha256"] == decision["questions_sha256"]
            rows.setdefault(item["observation"]["arm"], []).extend(item["observation"]["queries"])
    expected = [q["id"] for q in rows[baseline]]
    base = {q["id"]: q for q in rows[baseline]}
    test_word = re.compile(r"\btest(?:s|ed|ing)?\b", re.I)
    for arm, record in decision.items():
        if arm in ("questions_file", "questions_sha256"):
            continue
        replayed = compare(rows[baseline], rows[arm], expected)
        assert replayed == {k: v for k, v in record["compare"].items() if k != "individual_gains"}
        same = {(q["id"], page): q["pages"][page]["response"]["data"]["results"]
                == base[q["id"]]["pages"][page]["response"]["data"]["results"]
                for q in rows[arm] for page in q["pages"]}
        assert record["controls_identical"] == all(
            ok for (qid, _), ok in same.items() if base[qid].get("category") == "control")
        assert record["no_test_word_identical"] == all(
            ok for (qid, _), ok in same.items() if not test_word.search(base[qid]["query"]))
    return recorded


@pytest.mark.parametrize("split", ["development", "validation"])
def test_test_source_slot_decisions_replay_from_hash_bound_observations(split):
    recorded = _replay_slot_decision("2026-10-17-test-source-slot", "T3", split)
    # T2 loses judged tests on development; T3 holds every development and validation rule.
    assert not recorded["rules"]["T2_development"]["zero_individual_losses"]
    assert all(v for k, v in recorded["rules"]["T3_validation"].items() if k not in ("first_five_net_gain", "gain_packs"))
    assert all(v for k, v in recorded["rules"]["T3_development"].items() if k != "first_five_net_gain")


@pytest.mark.parametrize("split", ["development", "validation"])
def test_paired_source_decisions_replay_from_hash_bound_observations(split):
    recorded = _replay_slot_decision("2026-10-18-paired-source", "P", split)
    # Pf loses a judged test on development. P holds every development rule but gains
    # nothing on validation: no paired source it moved was a judged implementation.
    assert not recorded["rules"]["Pf_development"]["zero_individual_losses"]
    assert all(v for k, v in recorded["rules"]["P_development"].items() if k != "first_five_net_gain")
    validation = recorded["rules"]["P_validation"]
    assert validation["zero_individual_losses"] and validation["compare_passes"]
    assert validation["first_five_net_gain"] == 0 and not validation["gains_in_at_least_2_packs"]
    assert recorded["decision"]["P"] == "rejected on validation"


@pytest.mark.parametrize("split", ["development", "validation", "validation_repeat_1", "validation_repeat_2"])
def test_query_source_decisions_replay_from_hash_bound_observations(split):
    recorded = _replay_slot_decision("2026-10-18-query-source", "S1", split, baseline="D")
    # S1 holds every judged rule but fails the frozen p95 limit in the one validation run.
    # The two repeats came after the decision and pass compare, but they cannot change it.
    rules = recorded["validation_rules"]
    assert rules["zero_individual_losses"] and rules["files_24_net_gain_at_least_2_in_2_packs"]
    assert rules["identity_holds"] and not rules["compare_checks"]["latency"]
    assert recorded["decision"]["S1"] == "rejected on validation"
    assert recorded["splits"][split]["S1"]["compare"]["passed"] == (split != "validation")


def test_query_source_s2_decision_replays_from_hash_bound_observations():
    """S2 reruns the S1 order with a three-round latency rule; it passes latency but loses a judged test file."""
    import gzip
    import hashlib
    import json
    import re
    import statistics
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evals"
    recorded = json.loads((root / "results" / "2026-10-18-query-source-s2-decision.json").read_text())
    freeze = (root / "designs" / "2026-10-18-query-source-s2-freeze.json").read_bytes()
    assert hashlib.sha256(freeze).hexdigest() == recorded["freeze_sha256"]
    patch = (root / recorded["patch"]["file"]).read_bytes()
    assert hashlib.sha256(gzip.decompress(patch)).hexdigest() == json.loads(freeze)["candidate"]["patch_sha256"]
    questions = (root / recorded["questions_file"]).read_bytes()
    assert hashlib.sha256(questions).hexdigest() == recorded["questions_sha256"]
    compressed = (root / "results" / "2026-10-18-query-source-s2-observations.json.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == recorded["artifact"]["gzip_sha256"]
    rows = {}
    for item in json.loads(gzip.decompress(compressed)):
        assert item["observation"]["questions_sha256"] == recorded["questions_sha256"]
        rows.setdefault((item["round"], item["observation"]["arm"]), {}).update(
            {q["id"]: q for q in item["observation"]["queries"]})
    ids = [q["id"] for g in json.loads(questions)["repositories"] for q in g["queries"]]

    def merged(arm):  # round-1 rows; page-5 seconds = median of the three round medians
        out = []
        for qid in ids:
            row = deepcopy(rows[(1, arm)][qid])
            row["pages"]["5"]["seconds"] = statistics.median(rows[(r, arm)][qid]["pages"]["5"]["seconds"] for r in (1, 2, 3))
            out.append(row)
        return out

    base, cand = merged("D"), merged("S2")
    replayed = compare(base, cand, ids)
    assert replayed == {k: v for k, v in recorded["compare"].items() if k != "individual_gains"}
    test_word = re.compile(r"\btest(?:s|ed|ing)?\b", re.I)
    for old, new in zip(base, cand, strict=True):
        if old.get("category") == "control" or not test_word.search(old["query"]):
            assert all(old["pages"][p]["response"]["data"]["results"] == new["pages"][p]["response"]["data"]["results"]
                       for p in old["pages"])
    assert replayed["checks"]["latency"] and not replayed["checks"]["file_totals_no_loss"]
    assert [(x["id"], x["page"]) for x in replayed["individual_losses"]] == [("vapor:query-source-s2-3", "24")]
    assert recorded["decision"] == "rejected on validation"


def test_test_support_development_rejection_replays_from_delivery():
    """Helper demotion must recover judged tests before fresh validation is spent."""
    import gzip
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evals"
    stem = "2026-10-20-test-support"
    decision = json.loads((root / "results" / f"{stem}-decision.json").read_text())
    freeze_raw = (root / "designs" / f"{stem}-freeze.json").read_bytes()
    questions_raw = (root / "designs" / f"{stem}-development.json").read_bytes()
    compressed = (root / "results" / f"{stem}-observations.json.gz").read_bytes()
    assert hashlib.sha256(freeze_raw).hexdigest() == decision["freeze_sha256"]
    freeze = json.loads(freeze_raw)
    assert hashlib.sha256(questions_raw).hexdigest() == freeze["questions_sha256"]
    assert hashlib.sha256(compressed).hexdigest() == decision["artifact_sha256"]
    artifact = json.loads(gzip.decompress(compressed))
    assert hashlib.sha256(artifact["candidate_patch"].encode()).hexdigest() == freeze["candidate_patch_sha256"]
    assert hashlib.sha256(artifact["operator"].encode()).hexdigest() == freeze["operator_sha256"]
    questions = [q for g in json.loads(questions_raw)["repositories"] for q in g["queries"]]
    ids = [q["id"] for q in questions]
    arms = {arm: [q for obs in artifact["observations"] if obs["arm"] == arm
                  for q in obs["queries"]] for arm in ("B", "C")}
    for obs in artifact["observations"]:
        assert obs["questions_sha256"] == freeze["questions_sha256"]
        assert obs["engine_sha256"] == decision["engine_sha256"][obs["arm"]]
    for arm in arms.values():
        assert [q["id"] for q in arm] == ids
        for q, frozen in zip(arm, questions, strict=True):
            assert q["query"] == frozen["query"] and q["evidence"] == frozen["evidence"]
            for page in q["pages"].values():
                assert page["hits"] == evidence_hits(page["response"]["data"]["results"], q["evidence"])
    replayed = compare(arms["B"], arms["C"], ids)
    assert replayed == decision["comparison"]
    gains = []
    for old, new in zip(arms["B"], arms["C"], strict=True):
        gained = set(new["pages"]["5"]["hits"]["files"]) - set(old["pages"]["5"]["hits"]["files"])
        gains.extend((old["id"], i) for i in gained)
        for page in old["pages"]:
            assert old["pages"][page]["generation_diagnostic"] == new["pages"][page]["generation_diagnostic"]
    assert gains == []
    assert decision["decision"] == "rejected on development: no judged test recovered at five"
    assert decision["fresh_validation_started"] is False
    assert not replayed["individual_losses"]
