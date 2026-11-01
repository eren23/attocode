"""Acceptance rules of the test-recall trial, on synthetic observation rows."""
import hashlib
import json
from copy import deepcopy

import pytest

from eval.quality.test_recall_trial import decide, freshness


def runs(split="development"):
    """A passing trial: +2 first-five files across two packs, one untouched control."""
    questions = (("p", "p-1", "retry tests", [0, 1]), ("q", "q-1", "parser test", [0]),
                 ("q", "q-2", "parser config", [0]))
    design = json.dumps({"split": split, "repositories": [
        {"pack": pack, "commit": "c", "queries": [{"id": qid} for p, qid, _, _ in questions if p == pack]}
        for pack in ("p", "q")]}).encode()
    arms = {}
    for arm in ("baseline", "candidate"):
        arms[arm] = []
        for pack in ("p", "q"):
            rows = []
            for p, qid, query, gained in questions:
                if p != pack:
                    continue
                control = "test" not in query
                row = {"id": qid, "pack": pack, "query": query, "evidence": [{"file": "a"}] * 3,
                       "inspection_hits": [], "pages": {}}
                for page in ("5", "24", "scoped"):
                    files = gained if (page != "5" or arm == "candidate" or control) else []
                    row["pages"][page] = {"request": {"top_k": page}, "seconds": .2,
                                          "hits": {"files": files, "ranges": files, "visible": []},
                                          "response": {"data": {"results": [{"file_path": qid}]}}}
                rows.append(row)
            arms[arm].append({"pack": pack, "arm": arm, "commit": "c", "queries": rows,
                              "questions_sha256": hashlib.sha256(design).hexdigest(),
                              "operator_sha256": "o", "engine_sha256": "e"})
    return design, arms["baseline"], arms["candidate"]


def page(arm_runs, qid, number):
    return next(r for run in arm_runs for r in run["queries"] if r["id"] == qid)["pages"][number]


def test_trial_passes_and_reports_net_gain():
    decision = decide(*runs())
    assert decision["passed"], decision["checks"]
    assert decision["trial"]["files_5_net_by_pack"] == {"p": 2, "q": 1}
    assert decision["trial"]["test_queries"] == 2


def test_validation_needs_three_net_files():
    design, baseline, candidate = runs("validation")
    page(candidate, "p-1", "5")["hits"]["files"] = [0]
    decision = decide(design, baseline, candidate)
    assert not decision["checks"]["files_5_gain"]


def _single_pack(b, c):
    page(c, "q-1", "5")["hits"]["files"] = []
    page(c, "p-1", "5")["hits"]["files"] = [0, 1, 2]


def _loss_5(b, c):
    page(b, "p-1", "5")["hits"]["files"] = [2]


def _loss_24(b, c):
    page(c, "q-1", "24")["hits"]["files"] = []


def _control_changed(b, c):
    page(c, "q-2", "24")["response"]["data"]["results"] = [{"file_path": "other"}]


@pytest.mark.parametrize("change,check", [
    (_single_pack, "files_5_gain"), (_loss_5, "no_file_loss_5"),
    (_loss_24, "no_file_loss_24"), (_control_changed, "controls_identical")])
def test_trial_rejects(change, check):
    design, baseline, candidate = runs()
    change(baseline, candidate)
    decision = decide(design, baseline, candidate)
    assert not decision["checks"][check] and not decision["passed"]


def test_test_query_page_changes_are_not_control_changes():
    design, baseline, candidate = runs()
    page(candidate, "p-1", "24")["response"]["data"]["results"] = [{"file_path": "other"}]
    assert decide(design, baseline, candidate)["checks"]["controls_identical"]


@pytest.mark.parametrize("field,value", [("engine_sha256", "x"), ("questions_sha256", "x"), ("commit", "x")])
def test_trial_rejects_mismatched_observations(field, value):
    design, baseline, candidate = runs()
    candidate = deepcopy(candidate)
    candidate[0][field] = value
    with pytest.raises(ValueError):
        decide(design, baseline, candidate)


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
