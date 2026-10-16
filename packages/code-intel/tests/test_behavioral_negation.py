"""Behavioral clauses must not penalize code implementing their requirements."""
import pytest
from attocode_intel import focused_evidence
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.query_ranking import query_diagnostics


@pytest.mark.parametrize("marker", ["without", "avoid"])
@pytest.mark.parametrize("clause", ["leaking credentials", "buffering the file", "mutating the cookie jar",
                                   "accepting incomplete documents", "overriding headers", "forcing stdin into memory",
                                   "creating a JSON tree", "dropping binary detection settings"])
def test_behavioral_clause_keeps_legacy_retrieval_terms_but_removes_penalty(clause, marker):
    query = "prepare response " + marker + " " + clause
    assert focused_evidence.task_terms(query)[0] == {"prepare", "response"}
    assert focused_evidence.scope_exclusion_terms(query) == set()
    assert focused_evidence.scope_exclusion_terms(query, fold=False) == set()


@pytest.mark.parametrize("query", ["bootstrap without swarm", "bootstrap without unrelated swarm modules",
                                   "cleanup upload without cache", "prepare response excluding examples",
                                   "prepare response without logging modules", "prepare response without Spring",
                                   "prepare response without examples but with credentials"])
def test_explicit_and_ambiguous_source_scopes_preserve_existing_penalties(query):
    assert focused_evidence.scope_exclusion_terms(query) == focused_evidence.task_terms(query)[1]


def test_mixed_behavior_and_scope_clauses_do_not_erase_real_exclusions():
    query = "authenticate without leaking credentials, excluding unrelated examples"
    assert focused_evidence.scope_exclusion_terms(query) == {"example"}
    assert focused_evidence.task_terms(query)[0] == {"authenticate"}


@pytest.mark.parametrize("body", [False, True])
def test_search_preserves_generation_and_no_longer_demotes_credential_implementation(tmp_path, monkeypatch, body):
    query = "authentication without leaking credentials"
    manager = SemanticSearchManager(str(tmp_path))
    manager._kw_index_built = True
    target = SemanticSearchResult("src/credentials.py", "function", "authenticate", "authentication credentials", 1, 1, 3)
    noise = SemanticSearchResult("src/unrelated.py", "function", "authenticate", "authentication", .8, 1, 3)
    queries = []
    def keyword(self, text, top_k, scope):
        queries.append(text)
        return [target, noise]
    monkeypatch.setattr(SemanticSearchManager, "_keyword_search", keyword)
    monkeypatch.setattr(SemanticSearchManager, "_body_search", lambda *args: [target, noise] if body else [])
    monkeypatch.setattr(SemanticSearchManager, "_file_search", lambda *args: [])
    try:
        hits = manager.search_candidates(query, top_k=24)
        assert queries == ["authentication"]  # no broad rewrite of candidate generation
        assert hits[0].file_path == target.file_path
        # An explicit component exclusion still penalizes the same file.
        assert manager.search_candidates("authentication without credentials", 24)[0].file_path == noise.file_path
    finally:
        manager.close()


def test_behavioral_requirement_does_not_hide_matching_components():
    hits = [SemanticSearchResult("src/credentials.py", "function", "refresh", "cache generation credentials", 1, 1, 3),
            SemanticSearchResult("integrations/cache.py", "function", "refresh", "cache generation", .9, 1, 3)]
    assert query_diagnostics("cache generation without leaking credentials", hits)["ambiguous"]
    assert not query_diagnostics("cache generation without credentials", hits)["ambiguous"]


def test_behavioral_clause_without_punctuation_keeps_following_scope():
    assert focused_evidence.scope_exclusion_terms("authenticate without leaking credentials excluding examples") == {"example"}


@pytest.mark.parametrize("split", ["development", "validation"])
def test_frozen_negation_decisions_replay_with_generation_and_scope_controls(split):
    import gzip
    import hashlib
    import json
    from pathlib import Path

    from eval.quality.negation_trial import decide

    root = Path(__file__).resolve().parents[1] / "evals"
    record = json.loads((root / "results/2026-10-16-negation-decision.json").read_text())
    packed = (root / "results/2026-10-16-negation-observations.json.gz").read_bytes()
    assert hashlib.sha256(packed).hexdigest() == record["artifact"]["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert len(raw) == record["artifact"]["raw_bytes"] < 10_000_000
    assert hashlib.sha256(raw).hexdigest() == record["artifact"]["raw_sha256"]
    questions = (root / f"designs/2026-10-16-negation-{split}.json").read_bytes()
    design = json.loads(questions)
    rows = {}
    for item in json.loads(raw):
        if item["split"] == split:
            observation = item["observation"]
            assert observation["questions_sha256"] == hashlib.sha256(questions).hexdigest()
            rows.setdefault(observation["arm"], []).extend(observation["queries"])
    ids = [q["id"] for group in design["repositories"] for q in group["queries"]]
    actual = decide(rows["baseline"], rows["candidate"], ids)
    assert actual == record["splits"][split] and actual["passed"]


@pytest.mark.parametrize("failure", ["generation", "scope"])
def test_gate_rejects_changed_generation_or_scoped_results(failure):
    from copy import deepcopy

    from eval.quality.negation_trial import decide

    pages = {p: {"request": {"top_k": p}, "seconds": .01,
                 "hits": {"files": [0], "ranges": [], "visible": []},
                 "generation_diagnostic": [{"stage": s, "results": []} for s in ("keyword", "body", "file_bm25")],
                 "response": {"data": {"results": [{"file_path": "a"}]}}} for p in ("5", "24", "scoped")}
    baseline = [{"id": "one", "query": "quota without examples", "category": "scope",
                 "evidence": [{"file": "a"}], "inspection_hits": [], "pages": pages}]
    candidate = deepcopy(baseline)
    if failure == "generation":
        candidate[0]["pages"]["5"]["generation_diagnostic"][0]["results"] = ["changed"]
    else:
        candidate[0]["pages"]["5"]["response"]["data"]["results"] = [{"file_path": "b"}]
    assert not decide(baseline, candidate, ["one"])["passed"]
