import pytest

from eval.matrix.datasets import Instance
from eval.matrix.stats import Z, holm, interval, mde, paired, render, row_metrics, score, sign_flip
from eval.metrics import compute_graded_ndcg


def _instance(iid: str, repo: str = "r", grades: dict | None = None) -> Instance:
    return Instance(id=iid, repo=repo, base_commit="", language="", category="", created_at="",
                    queries={"full": "q"}, gold=["a.py"], grades=grades)


def _row(iid: str, cell: str, files: list[str], status: str = "ok") -> dict:
    return {"instance_id": iid, "variant": "full", "cell": cell, "files": files, "status": status,
            "latency_ms": 1.0}


def test_holm_matches_known_values():
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([None, 0.02, 0.5]) == [None, pytest.approx(0.04), pytest.approx(0.5)]
    assert holm([0.6, 0.7]) == [1.0, 1.0]


def test_locagent_acc_and_graded_rows():
    gold = ["a.py", "b.py"]
    hit = row_metrics(["a.py", "x.py", "b.py"], gold)
    assert (hit["acc1"], hit["acc5"], hit["r5"], hit["mrr5"], hit["ceil24"]) == (1.0, 1.0, 1.0, 1.0, 1.0)
    miss = row_metrics(["x.py", "a.py", "y.py"], gold)  # Acc@5 needs both gold files, Acc@1 only one
    assert (miss["acc1"], miss["acc5"], miss["r5"], miss["mrr5"], miss["ceil24"]) == (0.0, 0.0, 0.5, 0.5, 0.0)

    grades = {"good.py": 3, "ok.py": 1, "bad.py": 0}
    graded = row_metrics(["bad.py", "good.py"], ["good.py", "ok.py"], grades)
    assert graded["mrr5"] == 0.5 and graded["r5"] == 0.5 and 0 < graded["gndcg5"] < 1
    unjudged = row_metrics(["new.py", "good.py"], ["good.py", "ok.py"], grades)
    assert all(unjudged[m] is None for m in ("acc1", "acc5", "acc10", "r5", "mrr5", "gndcg5"))


def test_graded_ndcg_uses_entire_judged_pool_as_ideal():
    grades = {"impl": 3, "test": 2, "swarm": 0}
    assert compute_graded_ndcg(["impl", "test"], grades, 2) == pytest.approx(1.0)
    assert compute_graded_ndcg(["test", "impl"], grades, 2) < 1.0
    assert compute_graded_ndcg(["swarm"], grades, 2) == 0.0
    with pytest.raises(ValueError, match="judgments"):
        compute_graded_ndcg(["unjudged"], grades, 2)


def test_the_cluster_unit_is_the_source_repository():
    # Rows resampled one by one would give a narrow range around 0.5.
    assert interval({"a": [1.0] * 50, "b": [0.0] * 50}) == (0.0, 1.0)
    instances = [_instance(f"d/{repo}-{i}", repo) for repo in ("one", "two") for i in range(30)]
    rows = [_row(inst.id, "base", ["x.py"]) for inst in instances]
    rows += [_row(inst.id, "new", ["a.py"] if inst.repo == "one" else ["x.py"]) for inst in instances]
    comparison = score(instances, rows, [("new", "base")])["comparisons"][0]
    assert (comparison["n"], comparison["repos"], comparison["ci"]) == (60, 2, (0.0, 1.0))


def test_sign_flip_is_symmetric():
    groups = {f"r{i}": [0.2 * (i % 3) - 0.1, 0.3] for i in range(12)}
    assert sign_flip(groups) == sign_flip({repo: [-d for d in ds] for repo, ds in groups.items()})
    assert sign_flip({f"r{i}": [0.0] for i in range(12)}) == 1.0
    assert sign_flip({f"r{i}": [1.0] for i in range(12)}) < 0.01


def test_fewer_than_ten_repositories_is_descriptive():
    def pairs(repos: int) -> list:
        return [(f"i{r}", f"r{r}", 1.0, 0.0) for r in range(repos)]

    one, nine, ten = paired(pairs(1)), paired(pairs(9)), paired(pairs(10))
    assert one["ci"] is None and one["p"] is None and one["mde"] is None
    assert nine["ci"] is not None and nine["p"] is None and nine["mde"] is None
    assert ten["p"] is not None and ten["mde"] is not None
    instances = [_instance(f"d/{i}") for i in range(3)]  # one repository
    rows = [_row(f"d/{i}", cell, ["a.py"]) for i in range(3) for cell in ("base", "new")]
    summary = score(instances, rows, [("new", "base")])
    assert "| descriptive |" in render(summary, [])


def test_mde_is_the_mcnemar_approximation_with_the_design_effect():
    one_row_each = {f"r{i}": [1.0 if i < 5 else -1.0 if i < 10 else 0.0] for i in range(100)}
    assert mde(one_row_each) == (pytest.approx(Z * (0.1 / 100) ** 0.5), 1.0)  # p_disc 0.1, n 100
    assert mde({"a": [1.0] * 5, "b": [-1.0] * 5})[1] == 5.0
    assert mde({"a": [0.0], "b": [0.0]}) == (None, None)


def test_missing_rows_refuse_unless_partial():
    instances = [_instance("d/1"), _instance("d/2")]
    rows = [_row("d/1", "base", ["a.py"]), _row("d/2", "base", ["x.py"]), _row("d/1", "new", ["a.py"])]
    with pytest.raises(ValueError, match="new@full on d: 1 of 2 instances have no row"):
        score(instances, rows, [("new", "base")])
    summary = score(instances, rows, [("new", "base")], partial=True)
    headings = [line for line in render(summary, []).splitlines() if line.startswith("#")]
    assert len(headings) > 3 and all(line.endswith("(PARTIAL)") for line in headings)
    assert summary["comparisons"][0]["n"] == 1


def test_failed_requests_are_counted_not_silent():
    instances = [_instance(f"d/{i}", f"r{i}") for i in range(4)]
    rows = [_row(f"d/{i}", "base", ["x.py", "a.py"]) for i in range(4)]
    rows += [_row("d/0", "new", ["x.py", "a.py"], "request_failed")]  # kept the pool order
    rows += [_row(f"d/{i}", "new", ["a.py", "x.py"]) for i in (1, 2, 3)]
    summary = score(instances, rows, [("new", "base")], metrics=["mrr5"])
    assert next(c for c in summary["cells"] if c["cell"] == "new")["status"] == {"request_failed": 1, "ok": 3}
    comparison = summary["comparisons"][0]
    assert comparison["n"] == 4 and comparison["cell_mean"] == pytest.approx(3.5 / 4)
    assert comparison["ok_only"]["n"] == 3 and comparison["ok_only"]["cell_mean"] == 1.0
    report = render(summary, [])
    assert "1 request_failed" in report and "0.5000 → 1.0000 (3 / 0, n 3)" in report
