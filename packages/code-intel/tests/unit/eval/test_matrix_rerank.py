"""Rerank stage of the eval matrix: arms, cache, ledger, privacy and the scorer checks."""

import hashlib
import json
import os
import subprocess
from dataclasses import asdict

import httpx
import pytest
import yaml
from attocode_intel._internal.integrations.context.systemone_ranker import SystemOneChoiceReranker
from attocode_intel.focused_evidence import file_excerpt

from eval.matrix import rerank, stats
from eval.matrix import run as matrix
from eval.matrix.datasets import Instance

FILES = {"a.py": "other = 1\n" * 20 + "def load_config():\n    return parse_toml()\n",
         "b.py": "import a\n", "c.py": "x = 1\n"}
POOL = ["a.py", "b.py", "c.py", "link.py"]


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _workspace(tmp_path, monkeypatch, pools, tags=()):
    """A snapshot of one repository, one instance per pool (pool rows of cell "pool"), and a fake paid arm."""
    root = tmp_path / "bench" / "k"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for path, text in FILES.items():
        (root / path).write_text(text)
    os.symlink("a.py", root / "link.py")
    os.symlink("../outside.py", root / "escape.py")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "c")
    sha = _git(root, "rev-parse", "HEAD")
    instances = [Instance(id=f"pack/k::query {i}", repo="k", base_commit=sha, language="python", category="",
                          created_at="", queries={"full": f"load config {i}"}, gold=["a.py"], grades=None,
                          tags=list(tags) if i == 0 else []) for i in range(len(pools))]
    out, cache = tmp_path / "out", tmp_path / "cache"
    out.mkdir()
    (out / "instances.jsonl").write_text("".join(json.dumps(asdict(inst)) + "\n" for inst in instances))
    (out / "results.jsonl").write_text("".join(json.dumps(
        {"instance_id": inst.id, "variant": "full", "cell": "pool", "files": files, "status": "ok",
         "fallback_reason": None, "latency_ms": 1.0, "pool_sha256": "p", "evidence_sha256": None}) + "\n"
        for inst, files in zip(instances, pools, strict=True)))
    matrix.snapshot(cache, instances, sources=(tmp_path / "bench",))
    calls = []

    def fake(model, query, excerpts):
        calls.append(query)
        return {"status": "ok", "order": list(reversed(range(len(excerpts)))), "error": None, "ms": 1.0,
                "cost_usd": 0.01}

    monkeypatch.setitem(rerank.ARMS, "fake-paid", {"kind": "listwise", "model": "fake", "paid": True})
    monkeypatch.setattr(rerank, "listwise", fake)
    monkeypatch.setattr(rerank, "openrouter_usage", lambda: None)
    monkeypatch.setattr(rerank, "WORKERS", 1)
    return out, cache, instances, calls


def _config(tmp_path, **cfg):
    path = tmp_path / "rerank.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def _rows(out, cell):
    return [r for r in map(json.loads, (out / "results.jsonl").read_text().splitlines()) if r["cell"] == cell]


def _seed_cost(cache, arm, per_call, units=3):
    """A provider-reported call in another run, so the arm has a measured cost and runs no probe calls."""
    db = rerank.Cache(cache / "cache.db")
    db.settle(db.reserve("seed", arm, "", units, per_call, 1.0), per_call, "actual")


def test_excerpts_come_from_the_snapshot_and_stay_inside_it(tmp_path, monkeypatch):
    _out, cache, instances, _calls = _workspace(tmp_path, monkeypatch, [POOL])
    tree = json.loads(matrix._tree_file(cache, "k", instances[0].base_commit).read_text())
    lines = matrix._reader(cache, tree)
    text = file_excerpt(lines("link.py"), "link.py", "config loading")  # a link reads its target
    assert text.startswith("File: link.py") and "load_config" in text and len(text) <= 1350
    with pytest.raises(FileNotFoundError, match="outside the repository"):
        lines("escape.py")
    with pytest.raises(FileNotFoundError, match="not a stored file"):
        lines("gone.py")


def test_a_paid_arm_stops_at_the_cap_and_refuses_to_start_over_it(tmp_path, monkeypatch):
    out, cache, instances, calls = _workspace(tmp_path, monkeypatch, [POOL, POOL])
    _seed_cost(cache, "fake-paid", 0.01)  # 0.01 per call of 3 files, reserved at 1.5 times
    config = _config(tmp_path, rerank=[{"arm": "fake-paid", "pools": ["pool"], "pages": [3]}])
    with pytest.raises(SystemExit, match="refused: .* pass the cap"):
        matrix.rerank_pools(out, cache, instances, config, budget_usd=0.015)  # estimate 0.02
    assert calls == []
    matrix.rerank_pools(out, cache, instances, config, budget_usd=0.022)
    assert len(calls) == 1  # 0.01 spent, and 0.015 more in flight would pass 0.022
    assert rerank.ledger(cache / "cache.db", str(out.resolve())) == {"fake-paid": (1, 0.01)}
    rows = _rows(out, "pool>fake-paid.3")
    assert len(rows) == 1 and rows[0]["files"] == ["c.py", "b.py", "a.py", "link.py"]  # the pool tail follows


def test_a_cache_hit_costs_nothing_and_a_missing_file_is_a_status(tmp_path, monkeypatch):
    out, cache, instances, calls = _workspace(tmp_path, monkeypatch, [POOL, ["gone.py", *POOL]])
    _seed_cost(cache, "fake-paid", 0.01)
    config = _config(tmp_path, rerank=[{"arm": "fake-paid", "pools": ["pool"], "pages": [3]},
                                       {"arm": "none", "pools": ["pool"], "pages": [3]}])
    matrix.rerank_pools(out, cache, instances, config, budget_usd=1)
    assert len(calls) == 1
    first = {r["instance_id"]: r for r in _rows(out, "pool>fake-paid.3")}
    missing = first[instances[1].id]
    assert missing["status"] == "missing_file" and missing["files"] == ["gone.py", *POOL]  # the pool order
    assert first[instances[0].id]["cache_hit"] is False and first[instances[0].id]["cost_usd"] == 0.01
    matrix.rerank_pools(out, cache, instances, config, budget_usd=0)  # no paid job, so the earlier spend is no refusal
    assert len(calls) == 1  # no new call
    again = {r["instance_id"]: r for r in _rows(out, "pool>fake-paid.3")}
    assert again[instances[0].id]["cache_hit"] is True and again[instances[0].id]["files"] == first[instances[0].id]["files"]
    assert rerank.ledger(cache / "cache.db", str(out.resolve())) == {"fake-paid": (1, 0.01)}
    assert [r["files"] for r in _rows(out, "pool>none.3")] == [POOL, ["gone.py", *POOL]]


def test_a_retry_makes_failed_requests_again_and_keeps_invalid_answers(tmp_path, monkeypatch):
    out, cache, instances, calls = _workspace(tmp_path, monkeypatch, [POOL, POOL])
    _seed_cost(cache, "fake-paid", 0.01)
    first = iter(["request_failed", "invalid_output"])

    def flaky(model, query, excerpts):
        calls.append(query)
        status = next(first, "ok")
        return {"status": status, "order": list(range(len(excerpts))) if status == "ok" else None,
                "error": None if status == "ok" else status, "ms": 1.0, "cost_usd": 0.01}

    monkeypatch.setattr(rerank, "listwise", flaky)
    config = _config(tmp_path, rerank=[{"arm": "fake-paid", "pools": ["pool"], "pages": [3]}])
    matrix.rerank_pools(out, cache, instances, config, budget_usd=1)
    failed = {r["instance_id"]: r["status"] for r in _rows(out, "pool>fake-paid.3")}
    matrix.rerank_pools(out, cache, instances, config, budget_usd=1, retry_failed=True)
    assert len(calls) == 3  # one more call: an invalid answer is a result of the arm
    after = {r["instance_id"]: r["status"] for r in _rows(out, "pool>fake-paid.3")}
    assert after == {key: "ok" if status == "request_failed" else status for key, status in failed.items()}
    assert sorted(after.values()) == ["invalid_output", "ok"]


def test_repeats_have_their_own_cache_keys(tmp_path, monkeypatch):
    out, cache, instances, calls = _workspace(tmp_path, monkeypatch, [POOL, POOL], tags=["core"])
    _seed_cost(cache, "fake-paid", 0.01)
    config = tmp_path / "rerank.yaml"  # YAML 1.1 reads a bare on: key as True
    config.write_text("rerank:\n- {arm: fake-paid, pools: [pool], pages: [3], on: all}\n"
                      "repeats: {arms: [fake-paid], n: 3, on: core}\n")
    matrix.rerank_pools(out, cache, instances, config, budget_usd=1)
    assert len(calls) == 4  # instance 0 (core) three times, instance 1 once
    assert [len(_rows(out, cell)) for cell in ("pool>fake-paid.3", "pool>fake-paid.3~r1", "pool>fake-paid.3~r2")] \
        == [2, 1, 1]
    jobs, missing = rerank.plan(yaml.safe_load(config.read_text()), instances,
                                {(r["instance_id"], r["variant"], r["cell"]): r for r in _rows(out, "pool")})
    matrix._evidence(cache, [job for job in jobs if job.inst == instances[0]])
    assert missing == 0 and len({job.key for job in jobs if job.inst == instances[0]}) == 3


def test_remote_arms_run_only_on_public_datasets(tmp_path, monkeypatch):
    out, cache, instances, _calls = _workspace(tmp_path, monkeypatch, [POOL])
    config = _config(tmp_path, rerank=[{"arm": "jev-choice", "pools": ["pool"], "pages": [3]}])
    with pytest.raises(SystemExit, match="refused: jev-choice on pack"):
        matrix.rerank_pools(out, cache, instances, config, budget_usd=1)
    assert not rerank.remote("systemone-http", {"endpoint": "http://127.0.0.1:8765/v1/systemone"})
    assert rerank.remote("systemone-http", {"endpoint": "http://localhost:8765/v1/systemone"})  # a name can resolve anywhere
    assert rerank.remote("haiku45-listwise", {})


def _row(iid, cell, files, **extra):
    return {"instance_id": iid, "variant": "full", "cell": cell, "files": files, "status": "ok",
            "latency_ms": 1.0, "pool_sha256": "p", **extra}


def _instances(n):
    return [Instance(id=f"d/{i}", repo=f"r{i}", base_commit="", language="", category="", created_at="",
                     queries={"full": "q"}, gold=["a.py"], grades=None) for i in range(n)]


def test_the_scorer_refuses_a_rerank_row_of_another_pool():
    rows = [_row("d/0", "pool", ["x.py", "a.py", "y.py"]),
            _row("d/0", "pool>arm.2", ["a.py", "x.py", "y.py"], pool_cell="pool", page=2, arm="arm")]
    stats.score(_instances(1), rows)
    rows[1]["pool_sha256"] = "other"
    with pytest.raises(ValueError, match="same pool hash"):
        stats.score(_instances(1), rows)
    rows[1] |= {"pool_sha256": "p", "files": ["y.py", "x.py", "a.py"]}  # y.py is not in the page
    with pytest.raises(ValueError, match="first 2 files"):
        stats.score(_instances(1), rows)


def test_a_cell_that_keeps_the_pool_order_is_a_harness_failure():
    instances, pool = _instances(20), ["x0.py", "x1.py", "x2.py", "x3.py", "x4.py", "a.py"]  # gold at rank 6
    rows = [_row(inst.id, "pool", pool) for inst in instances]
    for cell, arm, moved in (("pool>stuck.6", "stuck", 1), ("pool>fine.6", "fine", 2), ("pool>none.6", "none", 0)):
        rows += [_row(inst.id, cell, pool[::-1] if i < moved else pool, pool_cell="pool", page=6, arm=arm,
                      cost_usd=0.001, cache_hit=i < 10) for i, inst in enumerate(instances)]
    summary = stats.score(instances, rows)
    assert summary["harness"] == {"pool>stuck.6": 0.95}
    report = stats.render(summary, [])
    assert "Harness failure: pool>stuck.6 keeps the pool order on 95% of its rows." in report
    # The report pairs each rerank cell with its pool. Ceiling 1, Acc@5 0.05, efficiency 0.05.
    summary = stats.score(instances, rows, [("pool>stuck.6", "pool")])
    assert "| pool>stuck.6@full | d | 20 | 1.0000 | 0.0500 | 0.0500 | +0.0500 | 0.1401 | 0 | 1 / 1 | 1.00 | 50% |" \
        in stats.render(summary, [])


def test_listwise_needs_a_json_list_of_every_candidate(monkeypatch):
    assert rerank.index_list("[2, 0, 1]", 3) == [2, 0, 1]
    assert rerank.index_list("```json\n[1, 0]\n```", 2) == [1, 0]
    for text in ("[0, 0, 1]", "[0, 1]", "[true, 0, 1]", "0, 1, 2", "The order is [0, 1, 2]"):
        assert rerank.index_list(text, 3) is None
    monkeypatch.setattr(rerank, "openrouter_key", lambda: "test")
    answers = ["1, 0]", "b.py looks best"]

    def post(url, *, json, timeout, headers):
        assert json["model"] == "anthropic/claude-haiku-4.5" and "[1]\nFile: b.py" in json["messages"][1]["content"]
        assert json["messages"][-1] == {"role": "assistant", "content": "["}  # the answer starts as an array
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": answers.pop(0)}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 9, "cost": 0.000945}})

    monkeypatch.setattr(httpx, "post", post)
    output = rerank.listwise("anthropic/claude-haiku-4.5", "config", ["File: a.py", "File: b.py"])
    assert output["status"] == "ok" and output["order"] == [1, 0] and output["tokens"] == [900, 9]
    output = rerank.listwise("anthropic/claude-haiku-4.5", "config", ["File: a.py", "File: b.py"])
    assert output["status"] == "invalid_output" and output["order"] is None
    assert output["error"] == "[b.py looks best" and output["cost_usd"] == 0.000945  # a bad answer still costs


def _jev(monkeypatch, answer):
    from attocode_intel.confidence import jev

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")  # restored after the test
    seen = []

    def decide(site, state, questions, incumbent, chosen):
        seen.append((state, questions))
        if isinstance(answer, Exception):
            raise answer
        return {"answers": {"best": {"probabilities": answer}}}

    monkeypatch.setattr(jev, "_decide", decide)
    return seen


def test_jev_choice_ranks_by_the_full_probability_order(monkeypatch):
    seen = _jev(monkeypatch, {"0": 0.1, "1": 0.7, "2": 0.2})
    output = rerank.jev_choice("config loading", ["one", "two", "three"])
    assert output["status"] == "ok" and output["order"] == [1, 2, 0] and output["scores"] == [0.1, 0.7, 0.2]
    assert seen[0][0]["query"] == "config loading" and list(seen[0][1]["best"]["criteria"]) == ["0", "1", "2"]


def test_jev_choice_failures_are_explicit(monkeypatch):
    _jev(monkeypatch, {"0": 1.0})
    assert rerank.jev_choice("query", ["one", "two"])["status"] == "invalid_output"
    _jev(monkeypatch, TimeoutError("slow"))
    output = rerank.jev_choice("query", ["one", "two"])
    assert output["status"] == "request_failed" and output["order"] is None and "slow" in output["error"]


def test_old_jev_trials_load_under_the_keys_of_the_stage():
    excerpts, query = ["File: a.py\n1", "File: b.py\n2"], "x" * 600
    case = {"query": query, "baseline_files": ["a.py", "b.py"], "ranked_files": ["b.py", "a.py"], "failures": 0,
            "scores": [0.2, 0.8], "fallback_reason": None, "inference_ms": 5.0,
            "evidence_sha256": hashlib.sha256("\n".join(excerpts).encode()).hexdigest()}
    [(key, output)] = rerank.legacy_outputs({"model": "jev-choice", "max_query_chars": 512, "cases": [case]})
    assert key == rerank.listwise_key("jev-choice", rerank.revision("jev-choice", {}), 1, query[:512],
                                      rerank.evidence_hash(excerpts), 0)
    assert output["status"] == "ok" and output["order"] == [1, 0]
    failed = rerank.legacy_outputs({"model": "jev-choice", "cases": [case | {"failures": 2}]})[0][1]
    assert failed["status"] == "request_failed" and failed["order"] is None
    assert rerank.legacy_outputs({"model": "qwen3", "cases": [case]}) == []


def test_systemone_http_uses_the_product_adapter_and_keeps_its_fallback():
    def answer(_request):
        return httpx.Response(200, json={"answers": {"best": {"choice": "1", "probabilities": {"0": 0.2, "1": 0.8}}}})

    ranker = SystemOneChoiceReranker("http://127.0.0.1:8000/v1/systemone", transport=httpx.MockTransport(answer))
    output = rerank.systemone(ranker, "find cache", ["File: a.py", "File: b.py"])
    assert output["status"] == "ok" and output["order"] == [1, 0] and output["scores"] == [0.2, 0.8]
    broken = SystemOneChoiceReranker("http://127.0.0.1:8000/v1/systemone",
                                     transport=httpx.MockTransport(lambda _request: httpx.Response(500)))
    output = rerank.systemone(broken, "find cache", ["File: a.py", "File: b.py"])
    assert output["status"] == "request_failed" and output["error"] == "transport_error"
