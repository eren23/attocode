"""Acceptance rules of the hosted embedding trial, on synthetic observation rows."""
import hashlib
import json
from copy import deepcopy

import pytest

from eval.quality.embed_trial import NO_CALLS, decide, freshness

USAGE = ({"usage": 1.0}, {"usage": 1.5})


def runs(split="development"):
    """A passing trial: +3 first-five files across two packs."""
    questions = (("p", "p-1", [0, 1]), ("q", "q-1", [0]), ("q", "q-2", [0, 1]))
    design = json.dumps({"split": split, "repositories": [
        {"pack": pack, "commit": "c", "queries": [{"id": qid} for p, qid, _ in questions if p == pack]}
        for pack in ("p", "q")]}).encode()
    arms = {}
    for arm in ("baseline", "candidate"):
        arms[arm] = []
        for pack in ("p", "q"):
            rows = []
            for p, qid, gained in questions:
                if p != pack:
                    continue
                row = {"id": qid, "pack": pack, "query": qid, "evidence": [{"file": "a"}] * 3,
                       "inspection_hits": [], "pages": {}}
                for page in ("5", "24", "scoped"):
                    files = gained if (page != "5" or arm == "candidate") else gained[:-1]
                    hits = {"files": files, "ranges": files, "visible": []}
                    row["pages"][page] = {"request": {"top_k": page}, "seconds": .2, "hits": hits}
                    if arm == "candidate":
                        row["pages"][page]["samples"] = [
                            {"seconds": .3, "hits": deepcopy(hits), "dense": {"status": "ok", "ms": 90, "files": 4}}
                            for _ in range(3)]
                rows.append(row)
            cand = arm == "candidate"
            arms[arm].append({
                "pack": pack, "arm": arm, "commit": "c", "queries": rows,
                "questions_sha256": hashlib.sha256(design).hexdigest(),
                "operator_sha256": "o", "engine_sha256": "e", "samples_may_differ": cand,
                "embed_calls": ({"posted": 5, "refused": 0, "cost": .1, "models": ["voyage-code-4-20261001"]}
                                if cand else deepcopy(NO_CALLS)),
                "embed_index": {"chunks": 9, "stored": 9, "abort": None} if cand else None})
    return design, arms["baseline"], arms["candidate"]


def page(arm_runs, qid, number):
    return next(r for run in arm_runs for r in run["queries"] if r["id"] == qid)["pages"][number]


def decide_runs(design, baseline, candidate, usage=USAGE, limit=5.0):
    return decide(design, baseline, candidate, *usage, limit)


def test_trial_passes_and_reports_net_gain():
    decision = decide_runs(*runs())
    assert decision["passed"], decision["checks"]
    assert decision["hosted"]["files_5_net_by_pack"] == {"p": 1, "q": 2}
    assert decision["hosted"]["dense_statuses"] == {"ok": 27}


def test_validation_needs_three_net_files():
    design, baseline, candidate = runs("validation")
    assert decide_runs(design, baseline, candidate)["checks"]["files_5_gain"]
    for s in page(candidate, "q-2", "5")["samples"]:
        s["hits"]["files"] = [0]
    page(candidate, "q-2", "5")["hits"]["files"] = [0]
    assert not decide_runs(design, baseline, candidate)["checks"]["files_5_gain"]


def _single_pack(b, c):
    for s in page(c, "p-1", "5")["samples"]:
        s["hits"]["files"] = [0]
    page(c, "p-1", "5")["hits"]["files"] = [0]


def _loss_24(b, c):
    for s in page(c, "q-1", "24")["samples"]:
        s["hits"]["files"] = []
    page(c, "q-1", "24")["hits"]["files"] = []


def _dense_failed(b, c):
    page(c, "p-1", "5")["samples"][0]["dense"] = {"status": "failed", "ms": 1500, "files": 0}
    page(c, "p-1", "24")["samples"][0]["dense"] = {"status": "failed", "ms": 1500, "files": 0}


def _refused_consent(b, c):
    page(c, "p-1", "5")["samples"][0]["dense"] = {"status": "off", "ms": 0, "files": 0}


def _slow(b, c):
    for s in page(c, "p-1", "24")["samples"]:
        s["seconds"] = 3.0


def _baseline_called(b, c):
    b[0]["embed_calls"]["posted"] = 1


def _wrong_model(b, c):
    c[0]["embed_calls"]["models"].append("voyage-3")


def _not_indexed(b, c):
    c[1]["embed_index"]["abort"] = "status 402"


def _refused_call(b, c):
    c[1]["embed_calls"]["refused"] = 1


@pytest.mark.parametrize("change,check", [
    (_single_pack, "files_5_gain"), (_loss_24, "no_file_loss_24"), (_dense_failed, "fallback_rate"),
    (_refused_consent, "no_consent_refusal"), (_slow, "search_p95"),
    (_baseline_called, "baseline_no_remote_calls"), (_wrong_model, "pinned_model"),
    (_not_indexed, "packs_indexed"), (_refused_call, "no_refused_calls")])
def test_trial_rejects(change, check):
    design, baseline, candidate = runs()
    change(baseline, candidate)
    decision = decide_runs(design, baseline, candidate)
    assert not decision["checks"][check] and not decision["passed"]


def test_spend_counts_both_the_harness_and_the_key():
    design, baseline, candidate = runs()
    assert not decide_runs(design, baseline, candidate, limit=.1)["checks"]["spend"]
    assert not decide_runs(design, baseline, candidate, usage=({"usage": 1}, {"usage": 9}))["checks"]["spend"]


def test_page_hits_must_be_the_worst_of_three_samples():
    design, baseline, candidate = runs()
    page(candidate, "p-1", "5")["samples"][2]["hits"]["files"] = [0]
    with pytest.raises(ValueError):
        decide_runs(design, baseline, candidate)


@pytest.mark.parametrize("field,value", [("engine_sha256", "x"), ("questions_sha256", "x"),
                                         ("commit", "x"), ("samples_may_differ", False)])
def test_trial_rejects_mismatched_observations(field, value):
    design, baseline, candidate = runs()
    candidate = deepcopy(candidate)
    candidate[0][field] = value
    with pytest.raises(ValueError):
        decide_runs(design, baseline, candidate)


def test_freshness_finds_near_queries_and_shared_anchors(tmp_path):
    old = {"repositories": [{"queries": [{"query": "Where are the retry tests?",
                                          "evidence": [{"file": "t/a.py", "line": 4}]}]}]}
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "broken.json").write_text("{")
    new = tmp_path / "new.json"
    new.write_text(json.dumps({"repositories": [{"queries": [
        {"query": "where are the retry tests", "evidence": [{"file": "t/b.py", "line": 1}]},
        {"query": "cookie parser tests", "evidence": [{"file": "t/a.py", "line": 4}]},
        {"query": "unrelated words here", "evidence": [{"file": "t/c.py", "line": 9}]}]}]}))
    report = freshness(new, tmp_path)
    assert [c["kind"] for c in report["collisions"]] == ["query", "anchor"]
    assert report["unparsed"] == ["broken.json"]
