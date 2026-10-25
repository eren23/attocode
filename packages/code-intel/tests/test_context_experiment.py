"""Qualification arithmetic must fail closed before any contextual relevance run."""

from copy import deepcopy

import pytest


def fixture(candidate_ms=1):
    design = {
        "rounds": [
            ["baseline", "candidate_plain", "candidate"],
            ["candidate", "candidate_plain", "baseline"],
            ["baseline", "candidate_plain", "candidate"],
        ],
        "requests": {
            "depths": [5, 24],
            "budgets": [2000, 8000],
            "scoped_depth": 5,
            "scoped_budget": 8000,
        },
        "gates": {
            "distinct_file_and_visible_gains_at_5_each_round": 2,
            "repositories_with_gains_each_round": 2,
            "warm_p95_floor_ms": 250,
            "warm_p95_ratio": 2,
        },
        "packs": [],
    }
    reports = []
    for pack in ("one", "two"):
        q = {
            "id": pack + "-q",
            "query": "find a bounded behavior",
            "kind": "implementation",
            "context_file": "caller.py",
            "evidence": [
                {"file": pack + ".py", "line": 1, "quote": "evidence", "source_sha256": "0" * 64}
            ],
        }
        design["packs"].append({"id": pack, "questions": [q]})
        pages = []
        for n, arms in enumerate(design["rounds"]):
            for arm in arms:
                for depth, budget, scope in [(d, b, "") for d in (5, 24) for b in (2000, 8000)] + [
                    (5, 8000, pack + ".py")
                ]:
                    args = {
                        "query": q["query"],
                        "top_k": depth,
                        "max_tokens": budget,
                        "file_filter": scope,
                    }
                    if arm == "candidate":
                        args["context_file"] = "caller.py"
                    pages.append(
                        {
                            "round": n,
                            "arm": arm,
                            "question": q["id"],
                            "kind": q["kind"],
                            "arguments": args,
                            "milliseconds": candidate_ms if arm == "candidate" else 1,
                            "control_sha256": "a" * 64,
                            "judgment": {
                                "files": [pack + ".py"] if arm == "candidate" else [],
                                "visible": [0] if arm == "candidate" else [],
                            },
                        }
                    )
        reports.append({"status": "complete", "pack": pack, "pages": pages})
    return design, reports


def test_frozen_context_gates_accept_distinct_visible_file_gains():
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    assert decide(reports, design)["decision"] == "retain"


@pytest.mark.parametrize("missing", ["files", "visible"])
def test_new_file_and_visible_excerpt_are_both_required(missing):
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    for row in reports[1]["pages"]:
        if row["arm"] == "candidate":
            row["judgment"][missing] = []
    assert decide(reports, design)["decision"] == "reject"


def test_rounds_and_budgets_cannot_multiply_a_single_repository_gain():
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    for row in reports[1]["pages"]:
        row["judgment"] = {"files": [], "visible": []}
    assert decide(reports, design)["decision"] == "reject"


def test_candidate_without_context_must_preserve_the_default_payload():
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    next(row for row in reports[0]["pages"] if row["arm"] == "candidate_plain")[
        "control_sha256"
    ] = "b" * 64
    assert decide(reports, design)["decision"] == "reject"


def test_scoped_excerpt_loss_cannot_be_hidden_by_unscoped_gains():
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    for row in reports[0]["pages"]:
        if row["arguments"]["file_filter"]:
            row["judgment"] = {
                "files": ["one.py"],
                "visible": [] if row["arm"] == "candidate" else [0],
            }
    assert decide(reports, design)["decision"] == "reject"


@pytest.mark.parametrize("broken", ["missing", "duplicate"])
def test_incomplete_capture_has_no_quality_verdict(broken):
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    if broken == "missing":
        reports[0]["pages"].pop()
    else:
        reports[0]["pages"].append(deepcopy(reports[0]["pages"][0]))
    result = decide(reports, design)
    assert result["status"] == "incomplete" and result["decision"] is None


def test_wrong_query_binding_is_incomplete():
    from eval.quality.context_experiment import decide

    design, reports = fixture()
    reports[0]["pages"][0]["arguments"]["query"] = "a different question"
    assert decide(reports, design)["decision"] is None


@pytest.mark.parametrize("milliseconds,decision", [(250, "retain"), (250.1, "reject")])
def test_context_latency_has_a_frozen_250ms_floor(milliseconds, decision):
    from eval.quality.context_experiment import decide

    design, reports = fixture(milliseconds)
    assert decide(reports, design)["decision"] == decision


def test_only_existing_four_timing_fields_are_canonicalized():
    from eval.quality.context_experiment import control_data

    old = {
        "ranking": {
            "index": {
                "warmup_seconds": 1,
                "keyword_seconds": 2,
                "importance_seconds": 3,
                "body_seconds": 4,
                "coverage": 1,
            }
        }
    }
    new = deepcopy(old)
    for field in ("warmup_seconds", "keyword_seconds", "importance_seconds", "body_seconds"):
        new["ranking"]["index"][field] = 99
    assert control_data(old) == control_data(new)
    new["ranking"]["index"]["coverage"] = 0
    assert control_data(old) != control_data(new)


def test_continuation_workspace_must_match_before_normalization(tmp_path):
    from eval.quality.context_experiment import control_data

    with pytest.raises(ValueError, match="workspace"):
        control_data({"follow_up": {"arguments": {"workspace": "/different"}}}, tmp_path)


def test_context_cannot_supply_the_judged_answer_file():
    import json
    from pathlib import Path

    from eval.quality.context_experiment import validate_design

    design = json.loads(
        Path("packages/code-intel/evals/designs/2026-10-25-context-search.json").read_bytes()
    )
    q = design["packs"][0]["questions"][0]
    q["context_file"] = q["evidence"][0]["file"]
    with pytest.raises(ValueError, match="context"):
        validate_design(design)


def test_context_dispatch_reaches_the_committed_operator(tmp_path, monkeypatch):
    from pathlib import Path
    import attocode_intel
    from eval.quality import context_experiment, experiments

    root = tmp_path / "dispatch"
    (root / "evidence").mkdir(parents=True)
    monkeypatch.setenv("ATTOCODE_EXPERIMENT_ENGINE", str(Path(attocode_intel.__file__).parent))
    calls = []
    monkeypatch.setattr(context_experiment, "run", lambda selected: calls.append(selected))
    experiments.payload("context_search", root)
    assert calls == [root]
    import json

    assert json.loads((root / "evidence/controller-complete.json").read_bytes())["complete"] is True
