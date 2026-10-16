import json
import math
import sys
from dataclasses import asdict

import pytest

from eval.matrix import agents
from eval.matrix.agents import pairs, report, setup_row, sizing, spearman, task_values
from eval.matrix.datasets import Instance
from eval.matrix.stats import Z, paired

TOKENS = {"input_tokens": 100, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 400,
          "output_tokens": 20}


def _run(iid: str, setup: str, trial: int, acc5: float, *, failed: bool = False, cost: float = 0.1) -> dict:
    """A runs.jsonl row as localize_study.grade writes it."""
    return {"instance_id": iid, "setup": setup, "trial": trial, "failed": failed, "acc1": acc5, "acc5": acc5,
            "recall10": acc5, "mrr5": acc5, "seconds": 600 if failed else 30.0, "turns": None if failed else 6,
            "cost_usd": None if failed else cost, "tokens": TOKENS, "mcp_calls": int(setup == "intel"),
            "mcp_warming_results": 0}


def _study(tmp_path, runs: list[dict], repos: dict[str, str], setups: list[str], offline: list[dict] = ()):
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"study_id": "f" * 64, "model": "m", "config_id": "c", "trials": 2, "setups": setups}))
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in runs))
    instances = [Instance(id=iid, repo=repo, base_commit="", language="", category="", created_at="",
                          queries={"full": "q"}, gold=["a.py"], grades=None) for iid, repo in repos.items()]
    (tmp_path / "instances.jsonl").write_text("".join(json.dumps(asdict(inst)) + "\n" for inst in instances))
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in offline))
    return tmp_path / "instances.jsonl"


def _gain_study(tmp_path, n_repos: int):
    """5 tasks per repository and 2 trials. native hits 2 tasks per repository; intel hits 0, 1 or
    2 more, so intel is native + 0.2 over 3 repositories. intel costs twice as much."""
    runs, repos = [], {}
    for r in range(n_repos):
        for t in range(5):
            iid = f"d/r{r}-{t}"
            repos[iid] = f"r{r}"
            for trial in range(2):
                runs += [_run(iid, "native", trial, float(t < 2)),
                         _run(iid, "intel", trial, float(t < 2 + r % 3), cost=0.2),
                         _run(iid, "issue_only", trial, 0.0, cost=0.01)]
    return runs, repos, _study(tmp_path, runs, repos, ["native", "intel", "issue_only"])


def test_intel_gain_over_twelve_repositories(tmp_path):
    runs, repos, instances = _gain_study(tmp_path, 12)
    values = task_values(runs)
    result = paired(pairs(values["intel"], values["native"], "acc5", repos), 2000)
    assert result["delta"] == pytest.approx(0.2) and result["ci"][0] <= 0.2 <= result["ci"][1]
    assert result["p"] is not None and result["mde"] is not None

    text = report(tmp_path, instances, draws=2000)
    assert "| intel | Acc@5 | 60 (12) | 0.400 | 0.600 | +0.200 | 12 / 0 |" in text
    assert "| intel | Cost (USD) | 60 (12) | 0.1000 | 0.2000 | ×2.000 | 60 / 0 |" in text
    assert "descriptive |" not in text
    # The contamination control has scores but no paired row.
    assert "| issue_only | 60 | 120 | 0 |" in text and "| issue_only | Acc@5 |" not in text


def test_fewer_than_ten_repositories_is_descriptive(tmp_path):
    _runs, _repos, instances = _gain_study(tmp_path, 5)
    line = next(row for row in report(tmp_path, instances, draws=2000).splitlines()
                if row.startswith("| intel | Acc@5 |"))
    cells = [cell.strip() for cell in line.split("|")]
    assert cells[3] == "25 (5)" and " to " in cells[8]  # the range stays
    assert cells[9:11] == ["descriptive", "–"]  # no p-value and no MDE


def test_a_failed_run_scores_zero_and_costs_the_worst_run():
    # A failed row with a stale score must still score 0.
    runs = [_run("d/a", "intel", 0, 1.0, cost=0.1), _run("d/a", "intel", 1, 1.0, failed=True),
            _run("d/b", "intel", 0, 1.0, cost=0.3)]
    tasks = task_values(runs)["intel"]
    assert (tasks["d/a"]["acc5"], tasks["d/a"]["hits"]) == (0.5, [True, False])
    assert tasks["d/a"]["cost"] == pytest.approx(0.2)  # 0.1 and the worst cost, 0.3
    row = setup_row(tasks)
    assert (row["failures"], row["acc5"], row["pass_any"], row["pass_all"]) == (1, 0.75, 1.0, 0.5)
    assert (row["cost"], row["seconds"], row["turns"]) == (0.3, 30.0, 6)


def test_offline_rr_against_the_agent_and_a_missing_row(tmp_path):
    # The gold file is at offline rank 7, 4, 3 and 1; the agent hits 0, 1, 2 and 3 of 3 trials.
    # d/t4 has no offline row: it is counted, not scored.
    ranks, runs = {"d/t0": 7, "d/t1": 4, "d/t2": 3, "d/t3": 1}, []
    for t in range(5):
        runs += [_run(f"d/t{t}", "intel", trial, float(trial < min(t, 3))) for trial in range(3)]
    offline = [{"instance_id": iid, "variant": "full", "cell": "product", "status": "ok",
                "files": [f"x{i}.py" for i in range(1, rank)] + ["a.py"]} for iid, rank in ranks.items()]
    offline += [{"instance_id": "d/t4", "variant": "full", "cell": "bm25", "files": ["a.py"]},
                {"instance_id": "d/t4", "variant": "short", "cell": "product", "files": ["a.py"]}]
    instances = _study(tmp_path, runs, {f"d/t{t}": "r" for t in range(5)}, ["intel"], offline)

    text = report(tmp_path, instances, tmp_path, draws=200)
    assert "4 of 5 tasks have a row. A task without a row is not scored. No row: d/t4." in text
    # Spearman 1; offline hit and agent hit 2, hit and miss 1 (d/t1), miss and hit 0, miss and miss 1.
    assert "| intel | 4 | 1.000 | 2 | 1 | 0 | 1 |" in text
    with pytest.raises(SystemExit, match="no rows of cell nope"):
        report(tmp_path, instances, tmp_path, cell="nope", draws=200)


def test_spearman_uses_average_ranks():
    assert spearman([0.1, 0.2, 0.5, 1.0], [0.0, 0.1, 0.3, 0.9]) == pytest.approx(1.0)
    assert spearman([0.1, 0.5, 1.0], [0.0, 0.0, 1.0]) == pytest.approx(math.sqrt(3) / 2)
    assert spearman([0.1, 0.5, 1.0], [1.0, 1.0, 1.0]) is None
    assert spearman([0.1, 0.5], [0.0, 1.0]) is None


def test_sizing_solves_the_mde_for_the_task_count(tmp_path):
    runs, repos, _instances = _gain_study(tmp_path, 12)
    values = task_values(runs)
    z = sizing(pairs(values["intel"], values["native"], "acc5", repos))
    assert (z["n"], z["repos"], z["p_disc"]) == (60, 12, pytest.approx(0.2))
    variance = Z * Z * z["p_disc"] * z["deff"]
    for target, needed in zip(agents.TARGETS, z["needed"], strict=True):
        assert variance / needed <= target ** 2 < variance / (needed - 1)
    assert sizing([("d/a", "r", 1.0, 1.0)])["needed"] == [None, None]


def test_cli_writes_the_report_and_refuses_an_unknown_task(tmp_path, monkeypatch):
    _runs, _repos, instances = _gain_study(tmp_path, 3)
    monkeypatch.setattr(sys, "argv", ["agents", str(tmp_path), "--instances", str(instances)])
    agents.main()
    assert (tmp_path / "agent_report.md").read_text().startswith("# Agent localization report")
    (tmp_path / "runs.jsonl").write_text(json.dumps(_run("d/other", "native", 0, 1.0)) + "\n")
    with pytest.raises(SystemExit, match="1 study tasks have no instance"):
        report(tmp_path, instances)
