"""The query-rewrite trial harness and its frozen gates (eval/quality/rewrite_trial.py)."""
import argparse
import hashlib
import json
from copy import deepcopy

import pytest
from attocode_intel._internal.integrations.context.query_rewriter import (
    OPENROUTER_REWRITE,
    QueryRewriter,
)

from eval.quality.mcp_search import run
from eval.quality.rewrite_trial import decide, freshness

OK = {"status": "ok", "elapsed_ms": 500, "words": ["accepts", "negotiate"]}


def trial_runs(split="development"):
    """A passing trial: +3 first-five files across two packs, no losses, a rewrite per search."""
    questions = (("p", "one", [0, 1]), ("q", "two", [0]))
    design = json.dumps({"split": split, "repositories": [
        {"pack": pack, "commit": "c", "queries": [{"id": qid}]} for pack, qid, _ in questions]}).encode()
    arms = {}
    for arm in ("baseline", "candidate"):
        arms[arm] = []
        for pack, qid, gained in questions:
            row = {"id": qid, "pack": pack, "query": qid, "evidence": [{"file": "a"}] * 3,
                   "inspection_hits": [], "pages": {}}
            for page in ("5", "24", "scoped"):
                files = (gained if arm == "candidate" else []) if page == "5" else [0, 1, 2]
                hits = {"files": files, "ranges": files, "visible": []}
                row["pages"][page] = {"request": {"top_k": page}, "seconds": .5, "hits": hits,
                                      "rewrite_diagnostic": [dict(OK)] if arm == "candidate" else []}
                if arm == "candidate":
                    row["pages"][page]["samples"] = [
                        {"seconds": .5, "hits": deepcopy(hits), "ranking_diagnostic": [],
                         "rewrite_diagnostic": [dict(OK)]} for _ in range(3)]
            arms[arm].append({"pack": pack, "arm": arm, "commit": "c", "queries": [row],
                              "questions_sha256": hashlib.sha256(design).hexdigest(),
                              "operator_sha256": "o", "engine_sha256": "e",
                              "samples_may_differ": arm == "candidate",
                              "rerank_calls": {"posted": 0, "refused": 0},
                              "rewrite_calls": {"posted": 9 if arm == "candidate" else 0, "refused": 0}})
    return design, arms["baseline"], arms["candidate"], {"usage": .1}, {"usage": .102}


def pages(runs, names=("5", "24")):
    return [r["queries"][0]["pages"][p] for r in runs for p in names]


def set_files(page, files):
    page["hits"]["files"] = files
    for s in page.get("samples", []):
        s["hits"]["files"] = files


def test_trial_passes_and_reports_rewrites():
    decision = decide(*trial_runs())
    assert decision["passed"], decision["checks"]
    hosted = decision["hosted"]
    assert hosted["files_5_net_by_pack"] == {"p": 2, "q": 1}
    assert (hosted["rewrites"], hosted["fallbacks"], hosted["statuses"]) == (18, 0, {"ok": 18})
    assert hosted["words_per_ok_rewrite"] == 2 and hosted["estimated_usd"] == .0018


def _validation_gain(b, c, before, after):
    set_files(c[0]["queries"][0]["pages"]["5"], [0])


def _single_pack_gain(b, c, before, after):
    set_files(c[0]["queries"][0]["pages"]["5"], [0, 1, 2])
    set_files(c[1]["queries"][0]["pages"]["5"], [])


def _loss_24(b, c, before, after):
    set_files(c[0]["queries"][0]["pages"]["24"], [0, 1])


def _loss_5(b, c, before, after):
    set_files(b[0]["queries"][0]["pages"]["5"], [2])
    set_files(b[1]["queries"][0]["pages"]["5"], [1])


def _statuses(status, count):
    def mutate(b, c, before, after):
        for s in [s for p in pages(c) for s in p["samples"]][:count]:
            s["rewrite_diagnostic"] = [{"status": status, "elapsed_ms": 1500, "words": []}]
    return mutate


def _missing(b, c, before, after):
    pages(c)[0]["samples"][0]["rewrite_diagnostic"] = []


def _slow_rewrite(b, c, before, after):
    for s in [s for p in pages(c, ("5", "24", "scoped")) for s in p["samples"]]:
        s["rewrite_diagnostic"][0]["elapsed_ms"] = 1600


def _slow_search(b, c, before, after):
    for s in [s for p in pages(c) for s in p["samples"]]:
        s["seconds"] = 3


def _baseline_posted(b, c, before, after):
    b[0]["rewrite_calls"]["posted"] = 1


def _baseline_rewrite(b, c, before, after):
    pages(b)[0]["rewrite_diagnostic"] = [dict(OK)]


def _rerank(b, c, before, after):
    c[1]["rerank_calls"]["posted"] = 1


def _refused(b, c, before, after):
    c[0]["rewrite_calls"]["refused"] = 1


def _overspent(b, c, before, after):
    after["usage"] = 1.2


def _usage_reset(b, c, before, after):
    after["usage"] = .05


def _estimate(b, c, before, after):
    c[0]["rewrite_calls"]["posted"] = 20000


@pytest.mark.parametrize("split, mutate, check", [
    ("validation", _validation_gain, "files_5_gain"), ("development", _single_pack_gain, "files_5_gain"),
    ("development", _loss_24, "no_file_loss_24"), ("development", _loss_5, "at_most_one_file_loss_5"),
    ("development", _statuses("timeout", 3), "fallback_rate"),
    ("development", _statuses("missing_credential", 1), "no_config_fallback"),
    ("development", _missing, "rewrite_on_every_search"), ("development", _slow_rewrite, "rewrite_p95"),
    ("development", _slow_search, "search_p95"), ("development", _baseline_posted, "baseline_no_remote_calls"),
    ("development", _baseline_rewrite, "baseline_no_remote_calls"), ("development", _rerank, "no_rerank"),
    ("development", _refused, "no_refused_calls"), ("development", _overspent, "spend"),
    ("development", _usage_reset, "spend"), ("development", _estimate, "spend")])
def test_trial_gate_rejects(split, mutate, check):
    design, b, c, before, after = trial_runs(split)
    mutate(b, c, before, after)
    decision = decide(design, b, c, before, after)
    assert not decision["checks"][check] and not decision["passed"]


def _digest(b, c):
    c[0]["questions_sha256"] = "x"


def _engine(b, c):
    c[0]["engine_sha256"] = "other"


def _missing_pack(b, c):
    del c[1]


def _stable(b, c):
    c[0]["samples_may_differ"] = False


def _two_samples(b, c):
    pages(c)[0]["samples"].pop()


def _lucky_draw(b, c):
    pages(c)[0]["samples"][0]["hits"]["files"] = []


@pytest.mark.parametrize("mutate", [_digest, _engine, _missing_pack, _stable, _two_samples, _lucky_draw])
def test_trial_rejects_mismatched_observations(mutate):
    design, b, c, before, after = trial_runs()
    mutate(b, c)
    with pytest.raises(ValueError):
        decide(design, b, c, before, after)


def test_freshness_reports_near_queries_and_shared_anchors(tmp_path):
    earlier = {"query": "How does the router match a path?", "evidence": [{"file": "r.py", "line": 3}]}
    (tmp_path / "old.json").write_text(json.dumps({"repositories": [{"queries": [earlier]}]}))
    new = tmp_path / "new.json"
    new.write_text(json.dumps({"repositories": [{"queries": [
        {"query": "how does the router match a path", "evidence": [{"file": "x.py", "line": 1}]},
        {"query": "Which hook formats the prompt?", "evidence": [{"file": "r.py", "line": 3}]},
        {"query": "Where are tokens refreshed?", "evidence": [{"file": "t.py", "line": 9}]}]}]}))
    report = freshness(new, tmp_path)
    assert [c["kind"] for c in report["collisions"]] == ["query", "anchor"]
    assert report["queries"] == 3 and report["earlier_queries"] == 1


def _tiny(tmp_path, monkeypatch, *, rewrite=True):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "settings.py").write_text(
        'def load_settings(path):\n    """Load settings from a configuration file."""\n    return open(path).read()\n')
    design = tmp_path / "design.json"
    design.write_text(json.dumps({"budget": 2000, "repositories": [{"pack": "tiny", "commit": "c", "queries": [
        {"id": "tiny:1", "query": "load settings", "evidence": [
            {"file": "settings.py", "line": 1, "quote": "def load_settings(path):",
             "source_sha256": hashlib.sha256((source / "settings.py").read_bytes()).hexdigest()}]}]}]}))
    for name in ("ATTOCODE_LOCAL_ONLY", "ATTOCODE_INTEL_QUERY_REWRITE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    if rewrite:
        monkeypatch.setenv("ATTOCODE_INTEL_QUERY_REWRITE", "openrouter")
        monkeypatch.setenv("ATTOCODE_INTEL_RANKING_ALLOW_REMOTE", "1")
        monkeypatch.setenv("ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE", str(source.resolve()))
    sent = []

    def post(self, body, headers):
        sent.append(body)
        return {"model": OPENROUTER_REWRITE["model"],
                "choices": [{"message": {"content": '["load_settings", "read_config"]'}}]}

    monkeypatch.setattr(QueryRewriter, "_post", post)
    return source, design, sent


def _args(tmp_path, source, design, **kwargs):
    return argparse.Namespace(questions=design, source=source, output=tmp_path / "out.json", pack="tiny",
                              arm="candidate", capture_generation=False, samples_may_differ=True,
                              max_rerank_calls=0, require_rerank=False, warmup_timeout=30, **kwargs)


@pytest.mark.asyncio
async def test_rewrite_cap_refuses_before_any_request_leaves(tmp_path, monkeypatch):
    source, design, sent = _tiny(tmp_path, monkeypatch)
    args = _args(tmp_path, source, design, max_rewrite_calls=0, require_rewrite=True)
    with pytest.raises(RuntimeError, match="Rewrite call limit"):
        await run(args)
    assert sent == [] and not args.output.exists()


@pytest.mark.asyncio
async def test_require_rewrite_refuses_an_unconfigured_arm(tmp_path, monkeypatch):
    source, design, sent = _tiny(tmp_path, monkeypatch, rewrite=False)
    args = _args(tmp_path, source, design, max_rewrite_calls=50, require_rewrite=True)
    with pytest.raises(RuntimeError, match="not configured"):
        await run(args)
    assert sent == [] and not args.output.exists()


@pytest.mark.asyncio
async def test_run_records_every_rewrite_and_counts_calls(tmp_path, monkeypatch):
    source, design, sent = _tiny(tmp_path, monkeypatch)
    args = _args(tmp_path, source, design, max_rewrite_calls=50, require_rewrite=True)
    await run(args)
    out = json.loads(args.output.read_text())
    # One warmup, one preflight, then three pages of three samples.
    assert out["rewrite_calls"] == {"posted": 11, "refused": 0} and len(sent) == 11
    assert [[d["status"] for d in p] for p in out["rewrite_preflight"]] == [["ok"]]
    (row,) = out["queries"]
    diagnostics = [s["rewrite_diagnostic"] for p in row["pages"].values() for s in p["samples"]]
    assert len(diagnostics) == 9
    assert all([d["status"] for d in ds] == ["ok"] and ds[0]["words"] == ["load_settings", "read_config"]
               for ds in diagnostics)
    assert all(m["content"] != "" and "settings.py" not in m["content"] for b in sent for m in b["messages"])
