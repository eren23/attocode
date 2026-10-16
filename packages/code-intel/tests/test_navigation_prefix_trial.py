"""Candidate scope and complete, per-query acceptance checks for the prefix trial."""
import copy

import pytest

from eval.quality.navigation_prefix_trial import gate, normalize


@pytest.mark.parametrize(("query", "expected"), [
    ("Trace how timers register callbacks", "timers register callbacks"),
    ("  PLEASE Show how exceptions capture a trace", "exceptions capture a trace"),
    ("Explain how trace spans are recorded without unrelated logging", "trace spans are recorded without unrelated logging"),
    ("trace how", "trace how"),
    ("trace how the", "trace how the"),
    ("Trace", "Trace"),
    ("traceHow", "traceHow"),
    ("trace how tests capture frames", "trace how tests capture frames"),
    ("Show how test fixtures are built", "Show how test fixtures are built"),
    ("Record a trace showing how timers wake", "Record a trace showing how timers wake"),
    ("Trace the transition to completion", "Trace the transition to completion"),
])
def test_candidate_only_strips_leading_navigation_phrase(query, expected):
    assert normalize(query) == expected
    assert normalize(query, "*.scala") == query


def eligible_rows():
    rows = []
    for i in range(12):
        before = ["a", "n1", "n2", "n3", "n4", "b"]
        after = ["a", "b", "n1", "n2", "n3", "n4"] if i < 2 else before
        rows.append({"id": str(i), "pack": str(i % 3), "labels": ["a", "b"],
                     "arms": {"baseline": {"files": before, "seconds": .01},
                              "candidate": {"files": after, "seconds": .01}}})
    return rows


def test_complete_qualified_candidate_passes():
    rows = eligible_rows()
    result = gate(rows, [str(i) for i in range(12)])
    assert result["passed"]
    assert result["candidate"]["pairs5"] - result["baseline"]["pairs5"] == 2


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "wrong_id", "missing_arm", "unlabeled"])
def test_incomplete_or_unpaired_observations_cannot_pass(corruption):
    rows = eligible_rows()
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    elif corruption == "wrong_id":
        rows[-1]["id"] = "unknown"
    elif corruption == "missing_arm":
        del rows[-1]["arms"]["candidate"]
    else:
        rows[-1]["labels"] = []
    with pytest.raises(ValueError):
        gate(rows, [str(i) for i in range(12)])


@pytest.mark.parametrize("loss", ["label24", "any5", "latency", "one_repo", "no_gain"])
def test_aggregate_gains_do_not_override_required_checks(loss):
    rows = eligible_rows()
    if loss == "label24":
        rows[-1]["arms"]["candidate"]["files"] = ["a"]
    elif loss == "any5":
        rows[-1]["arms"]["candidate"]["files"] = ["n1", "n2", "n3", "n4", "n5", "a", "b"]
    elif loss == "latency":
        rows[-1]["arms"]["candidate"]["seconds"] = .1
    elif loss == "one_repo":
        rows[1]["pack"] = rows[0]["pack"]
    else:
        rows[1]["arms"]["candidate"]["files"] = rows[1]["arms"]["baseline"]["files"]
    assert not gate(rows, [str(i) for i in range(12)])["passed"]
