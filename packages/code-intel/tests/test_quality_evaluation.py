"""Adversarial quality grading: citations, omissions, distractors, drift, and client parity."""
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def quality(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "evals"))
    import quality_scoring as scoring
    import quality_tasks as tasks
    root = tmp_path / "source"
    root.mkdir()
    (root / "api.py").write_text("from service import render\nreturn render(value)\n")
    (root / "service.py").write_text("return encode(value)\n")
    (root / "unrelated.py").write_text("return status()\n")
    task = {"id": "express:quality_fixture", "repo": "express", "family": "quality", "question": "Trace rendering.",
            "mutation": None, "candidate_files": ["api.py", "service.py", "unrelated.py"],
            "relevant_files": ["api.py", "service.py"], "claims": [
                tasks.claim("flow", "API delegates to render and render encodes the value.", "supported",
                            tasks.anchor("api.py", "return render(value)"), tasks.anchor("service.py", "return encode(value)")),
                tasks.claim("bypass", "API bypasses render.", "contradicted", tasks.anchor("api.py", "return render(value)")),
                tasks.claim("latency", "Production latency is below 1ms.", "insufficient", tasks.anchor("service.py", "return encode(value)"))]}
    task = tasks.compile_task(root, task)
    answer = {"claims": [{"id": c["id"], "verdict": c["verdict"], "confidence": 1.0,
                           "evidence": [{k: a[k] for k in ("path", "line", "quote")} for g in c["evidence_groups"] for a in g],
                           "explanation": "Source establishes the conclusion."} for c in task["claims"]],
              "ranked_files": ["api.py", "service.py"], "summary": "Delegation crosses two modules; deployment data is absent."}
    return scoring, tasks, root, task, answer


def test_correct_conclusions_need_every_source_step(quality):
    scoring, _, root, task, answer = quality
    good = scoring.grade(root, task, answer)
    assert good["automated_pass"] and good["metrics"]["grounded_claim_recall"] == 1
    assert good["prose_review"] == "pending"
    answer["claims"][0]["evidence"].pop()
    partial = scoring.grade(root, task, answer)
    assert not partial["automated_pass"]
    assert partial["metrics"]["verdict_accuracy"] == 1
    assert partial["metrics"]["grounded_claim_recall"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("attack", ["fabricated_quote", "wrong_line", "unrelated_quote", "escape", "bool_line", "nan", "duplicate_claim", "unknown_claim"])
def test_bad_answers_do_not_pass_by_looking_structured(quality, attack, tmp_path):
    scoring, _, root, task, answer = quality
    c = answer["claims"][0]
    if attack == "fabricated_quote":
        c["evidence"][0]["quote"] = "invented source"
    elif attack == "wrong_line":
        c["evidence"][0]["line"] = 1
    elif attack == "unrelated_quote":
        c["evidence"][0] = {"path": "unrelated.py", "line": 1, "quote": "return status()"}
    elif attack == "escape":
        (tmp_path / "secret.py").write_text("return render(value)\n")
        c["evidence"][0] = {"path": "../secret.py", "line": 1, "quote": "return render(value)"}
    elif attack == "bool_line":
        c["evidence"][0]["line"] = True
    elif attack == "nan":
        c["confidence"] = math.nan
    elif attack == "duplicate_claim":
        answer["claims"].append(copy.deepcopy(c))
    elif attack == "unknown_claim":
        c["id"] = "invented"
    assert not scoring.grade(root, task, answer)["automated_pass"]


def test_omissions_and_blanket_abstention_have_visible_cost(quality):
    scoring, _, root, task, answer = quality
    for c in answer["claims"]:
        c["verdict"] = "insufficient"
    abstained = scoring.grade(root, task, answer)
    assert abstained["metrics"]["balanced_verdict_accuracy"] == pytest.approx(1 / 3)
    assert not abstained["automated_pass"]
    answer["claims"] = answer["claims"][-1:]
    omitted = scoring.grade(root, task, answer)
    assert omitted["metrics"]["grounded_claim_precision"] == 1
    assert omitted["metrics"]["answer_coverage"] == pytest.approx(1 / 3)
    assert omitted["metrics"]["grounded_claim_recall"] == pytest.approx(1 / 3)
    assert not omitted["automated_pass"]


def test_wrong_confident_claims_and_unrelated_citations_are_penalized(quality):
    scoring, _, root, task, answer = quality
    answer["claims"][1]["verdict"] = "supported"
    confident = scoring.grade(root, task, answer)
    assert confident["metrics"]["unsupported_assertion_rate"] == .5
    assert confident["metrics"]["brier_score"] == pytest.approx(1 / 3)
    answer["claims"][1]["confidence"] = .1
    assert scoring.grade(root, task, answer)["metrics"]["brier_score"] < confident["metrics"]["brier_score"]
    answer["claims"][1]["verdict"] = "contradicted"
    answer["claims"][0]["evidence"].append({"path": "unrelated.py", "line": 1, "quote": "return status()"})
    padded = scoring.grade(root, task, answer)
    assert padded["metrics"]["citation_validity"] == 1
    assert padded["metrics"]["citation_anchor_precision"] < 1
    assert not padded["automated_pass"]
    assert padded["assessment"] == "needs_review"


def test_valid_context_citations_require_review_without_becoming_answer_errors(quality):
    scoring, _, root, task, answer = quality
    context = {"path": "api.py", "line": 1, "quote": "from service import render"}
    answer["claims"][0]["evidence"].extend([context, context])
    result = scoring.grade(root, task, answer)
    assert result["metrics"]["verdict_accuracy"] == 1
    assert result["metrics"]["grounded_claim_recall"] == 1
    assert result["metrics"]["citation_validity"] == 1
    assert result["assessment"] == "needs_review" and not result["automated_pass"]
    assert result["citation_review"] == {"required": True, "unmatched": [{"claim": "flow", **context}], "invalid": []}
    assert "require review" in result["issues"][0]
    # A real quotation can support the explanation without matching the rubric's required step.
    # Conversely, a fabricated quotation is a source error even when all verdicts are correct.
    answer["claims"][0]["evidence"][-1] = {**context, "quote": "from invented import render"}
    invalid = scoring.grade(root, task, answer)
    assert invalid["assessment"] == "failed"
    assert invalid["citation_review"]["invalid"][0]["reason"] == "Quote does not match the cited source excerpt"


def test_review_only_results_are_reported_separately_from_wrong_verdicts(quality):
    scoring, _, root, task, answer = quality
    answer["claims"][0]["evidence"].append({"path": "api.py", "line": 1, "quote": "from service import render"})
    review = scoring.grade(root, task, answer)
    answer["claims"][0]["verdict"] = "contradicted"
    wrong = scoring.grade(root, task, answer)
    assert wrong["assessment"] == "failed" and wrong["citation_review"]["required"]
    rows = [{"id": f"{task['id']}:codex:{i}:native", "task": task["id"], "client": "codex", "repeat": i,
             "lane": "native", "study_id": "fixture", "model": "fixed", "status": "completed", "passed": False,
             "seconds": 1, "quality": grade} for i, grade in enumerate([review, wrong])]
    manifest = {"schedule": rows, "study_id": "fixture", "models": {"codex": "fixed"}, "lanes": ["native"]}
    group = scoring.summarize(manifest, rows)["groups"][0]
    assert group["automated_passes"] == 0 and group["citation_review_required"] == 2
    assert group["assessments"] == {"passed": 0, "needs_review": 1, "failed": 1, "unclassified": 0}


def test_retrieval_penalizes_return_everything_duplicates_and_missing_files(quality):
    scoring, _, root, task, answer = quality
    answer["ranked_files"] = ["unrelated.py", "api.py", "service.py"]
    ranked = scoring.grade(root, task, answer)
    assert ranked["metrics"]["retrieval_recall"] == 1
    assert ranked["metrics"]["retrieval_precision"] == pytest.approx(2 / 3)
    assert ranked["metrics"]["mrr"] == .5 and ranked["metrics"]["ndcg"] < 1
    assert not ranked["automated_pass"]
    answer["ranked_files"] = ["api.py", "api.py"]
    assert scoring.grade(root, task, answer)["issues"]
    answer["ranked_files"] = []
    empty = scoring.grade(root, task, answer)
    assert empty["metrics"]["retrieval_recall"] == 0 and empty["metrics"]["retrieval_precision"] is None


def test_source_drift_and_symlinks_invalidate_rubric(quality, tmp_path):
    scoring, tasks, root, task, answer = quality
    path = root / "api.py"
    original = path.read_text()
    path.write_text("# edit shifts source\n" + original)
    with pytest.raises(ValueError, match="no longer matches"):
        scoring.grade(root, task, answer)
    path.unlink()
    outside = tmp_path / "outside.py"
    outside.write_text(original)
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="no longer matches"):
        scoring.grade(root, task, answer)
    with pytest.raises(ValueError, match="escaping"):
        tasks.compile_task(root, task)


def test_manifest_public_prompt_hides_gold_and_design_is_paired(quality):
    _, tasks, _, task, _ = quality
    import study
    public = json.loads(tasks.prompt(task).split("\n", 1)[1])
    assert set(public) == {"question", "claims", "candidate_files", "answer_schema"}
    assert all(set(c) == {"id", "text"} for c in public["claims"])
    selected, repeats, lanes = study.design("quality")
    assert len(selected) == 7 and repeats == 3 and len(lanes) == 4
    assert len(study.schedule(selected, repeats, lanes=lanes)) == 252
    assert len(study.schedule(study.TASKS)) == 720
    assert len(study.design("pilot")[0]) == 1


def test_discovery_hides_paths_and_accepts_unjudged_source_for_review(quality):
    scoring, tasks, root, task, answer = quality
    extra = root / "fastapi/helper.py"
    extra.parent.mkdir()
    extra.write_text("return render(value)\n")
    task["discovery"] = True
    task = tasks.compile_task(root, task)
    public = json.loads(tasks.prompt(task).split("\n", 1)[1])
    assert "candidate_files" not in public
    assert not any(p in json.dumps(public) for p in task["file_hashes"])
    assert "fastapi/helper.py" in task["file_hashes"]
    answer["ranked_files"].append("fastapi/helper.py")
    answer["claims"][0]["evidence"].append({"path": "fastapi/helper.py", "line": 1, "quote": "return render(value)"})
    result = scoring.grade(root, task, answer)
    assert result["assessment"] == "needs_review" and not result["automated_pass"]
    assert result["metrics"]["citation_validity"] == 1
    assert result["metrics"]["retrieval_recall"] == 1
    assert result["metrics"]["retrieval_precision"] is None
    assert result["metrics"]["retrieval_f1"] is None
    assert result["metrics"]["retrieval_judgment_coverage"] == pytest.approx(2 / 3)
    assert result["retrieval_review"] == {"required": True, "unjudged": ["fastapi/helper.py"], "invalid": []}
    answer["ranked_files"].append("../invented.py")
    escaped = scoring.grade(root, task, answer)
    assert escaped["assessment"] == "failed" and escaped["retrieval_review"]["invalid"] == ["../invented.py"]
    answer["ranked_files"].pop()
    # A known distractor is still a retrieval mismatch, even alongside unjudged source.
    answer["ranked_files"].append("unrelated.py")
    assert scoring.grade(root, task, answer)["assessment"] == "failed"


def test_unknown_relevance_does_not_create_a_comparison_gain(quality):
    scoring, tasks, root, task, answer = quality
    task["discovery"] = True
    (root / "fastapi").mkdir()
    (root / "fastapi/other.py").write_text("return render(value)\n")
    task = tasks.compile_task(root, task)
    good = scoring.grade(root, task, answer)
    answer["ranked_files"].append("fastapi/other.py")
    unjudged = scoring.grade(root, task, answer)
    rows = [{"id": f"{task['id']}:codex:0:{lane}", "task": task["id"], "client": "codex", "repeat": 0,
             "lane": lane, "study_id": "fixture", "model": "fixed", "status": "completed", "passed": grade["automated_pass"],
             "seconds": 1, "quality": grade} for lane, grade in [("native", good), ("intel_base", unjudged)]]
    manifest = {"schedule": rows, "study_id": "fixture", "models": {"codex": "fixed"}, "lanes": ["native", "intel_base"]}
    report = scoring.summarize(manifest, rows)
    comparison = next(c for c in report["comparisons"] if c["current"] == "intel_base" and c["comparator"] == "native")
    assert len(comparison["pairs"]) == 1 and comparison["retrieval_f1_pairs_observed"] == 0
    assert comparison["mean_retrieval_f1_delta"] is None


def test_integer_valued_json_line_numbers_are_valid(quality):
    scoring, _, root, task, answer = quality
    answer["claims"][0]["evidence"][0]["line"] = float(answer["claims"][0]["evidence"][0]["line"])
    assert scoring.grade(root, task, answer)["automated_pass"]


def test_contiguous_citations_cover_inner_anchors_but_not_fabricated_lines(quality):
    scoring, _, root, task, answer = quality
    answer["claims"][0]["evidence"][0] = {
        "path": "api.py", "line": 1, "quote": "from service import render\nreturn render(value)"}
    valid = scoring.grade(root, task, answer)
    assert valid["automated_pass"] and valid["metrics"]["grounded_claim_recall"] == 1
    answer["claims"][0]["evidence"][0]["quote"] = "from service import render\nreturn invented(value)"
    invalid = scoring.grade(root, task, answer)
    assert invalid["assessment"] == "failed" and invalid["metrics"]["citation_validity"] < 1
    assert invalid["metrics"]["grounded_claim_recall"] == pytest.approx(2 / 3)


def test_quote_ranges_cannot_move_lines_or_dump_entire_files(quality):
    scoring, tasks, root, task, answer = quality
    (root / "api.py").write_text("from service import render\nreturn render(value)\n" + "# context\n" * 12)
    task = tasks.compile_task(root, task)
    cite = answer["claims"][0]["evidence"][0]
    cite.update(line=1, quote=(root / "api.py").read_text())
    assert "12-line" in scoring.grade(root, task, answer)["citation_review"]["invalid"][0]["reason"]
    cite.update(line=2, quote="from service import render\nreturn render(value)")
    assert not scoring.grade(root, task, answer)["automated_pass"]


def test_client_schema_override_preserves_native_access(quality, tmp_path):
    scoring = quality[0]
    import study_clients
    for client in ("claude", "codex", "cursor"):
        directory = tmp_path / client
        directory.mkdir()
        cmd = study_clients.command(client, "fixed", directory, directory, {}, "question", answer_schema=scoring.ANSWER_SCHEMA)
        assert json.loads((directory / "schema.json").read_text()) == scoring.ANSWER_SCHEMA
        if client == "claude":
            assert json.loads(cmd[cmd.index("--json-schema") + 1]) == scoring.ANSWER_SCHEMA
            assert "Read" in cmd[cmd.index("--tools") + 1]
    assert study_clients.SCHEMA != scoring.ANSWER_SCHEMA


def test_quality_run_retains_wrong_answers_and_keeps_rubric_outside_source(quality, tmp_path, monkeypatch):
    scoring, tasks, root, task, answer = quality
    import pilot
    import study
    source = tmp_path / "study/sources/express"
    source.parent.mkdir(parents=True)
    import shutil
    shutil.copytree(root, source)
    directory = source.parents[1]
    task["prompts"] = [tasks.prompt(task)]
    rows = [{"id": f"{task['id']}:codex:0:{lane}", "task": task["id"], "client": "codex", "repeat": 0, "lane": lane}
            for lane in ("native", "intel_base")]
    manifest = {"mode": "quality", "tasks": [task], "models": {"codex": "fixed"}, "study_id": "study",
                "timeout": 600, "schedule": rows, "lanes": ["native", "intel_base"], "python": sys.executable,
                "revisions": {"express": "pinned"}}
    study.write_json(directory / "preparation.json", {"express": {"clean_passes": True, "fault_detected": True},
                                                     "quality_counterfactual": {"passed": True}})
    monkeypatch.setattr(study, "manifest_for", lambda _: manifest)
    monkeypatch.setattr(study, "preflight", lambda *a: {"ready": True})
    monkeypatch.setattr(pilot, "wiring_ready", lambda *a: True)
    calls = []
    def invoke(client, model, repo, stage, servers, prompt, timeout, env, **options):
        assert options["answer_schema"] == scoring.ANSWER_SCHEMA
        assert not (repo / "manifest.json").exists()
        returned = copy.deepcopy(answer)
        if calls:
            returned["claims"][0]["verdict"] = "contradicted"
        calls.append(client)
        return {"output": returned, "seconds": 1, "exit_code": 0, "timed_out": False, "quota_exhausted": False,
                "permission_denials": [], "terminal_error": False, "mcp_used": False}
    monkeypatch.setattr(study, "invoke", invoke)
    args = SimpleNamespace(study=directory, quota=None, clients=None, tasks=None, max_runs=2)
    study.run(args)
    results = [json.loads(p.read_text()) for p in sorted((directory / "runs").glob("*/result.json"))]
    assert len(results) == 2 and sum(r["passed"] for r in results) == 1
    assert all(r["status"] == "completed" for r in results)
    before = [(p, p.read_bytes()) for p in (directory / "runs").glob("*/result.json")]
    study.run(args)
    assert len(calls) == 2 and all(p.read_bytes() == data for p, data in before)
    report = {"manifest": manifest, "runs": results, "quality": scoring.summarize(manifest, results)}
    assert report["quality"]["complete"] and not report["quality"]["release_eligible"]
    scoring.write_review(directory, report)
    packets = json.loads((directory / "blind-review.json").read_text())
    assert all("client" not in p and "lane" not in p and "seconds" not in p for p in packets)
    results[0].pop("quality")
    results[0].update(status="interrupted", passed=False, seconds=600)
    summary = scoring.summarize(manifest, results)
    g = next(g for g in summary["groups"] if g["lane"] == results[0]["lane"])
    assert g["metrics"]["grounded_claim_recall"]["mean"] == 0
    assert g["metrics"]["grounded_claim_precision"]["observed"] == 0
