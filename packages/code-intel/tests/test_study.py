"""Benchmark integrity, billing boundaries and independent grading; no model calls."""
import copy
import json
import time
from pathlib import Path

import pytest

EVALS = Path(__file__).parents[1] / "evals"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(EVALS))
    import client_responses
    import release_gate
    import study
    import study_clients
    import study_tasks
    return study, study_clients, study_tasks, release_gate, client_responses


def synthetic_report(modules):
    study, _, tasks, gate, _ = modules
    manifest = {"engine_sha256": "engine", "client_versions": {c: "1" for c in gate.CLIENTS},
                "models": {c: "fixed-model" for c in gate.CLIENTS}, "repetitions": 5,
                "selection": "natural", "timeout": 600}
    manifest["study_id"] = study.digest(manifest)
    runs = [{**row, "study_id": manifest["study_id"], "model": "fixed-model", "status": "completed",
             "passed": True, "seconds": 50 if row["lane"].startswith("intel") else 100}
            for row in study.schedule(tasks.TASKS)]
    volume = {"measurement": "client_visible", "candidate_engine_sha256": "engine", "baseline_engine_sha256": "baseline",
              "rows": [{"id": f"{client}:{repo}:{query}", "before": 1000, "after": 400, "evidence_preserved": True}
                       for client in gate.CLIENTS for repo in gate.REPOS for query in range(5)]}
    return {"manifest": manifest, "runs": runs, "response_volume": volume}


def test_schedule_is_paired_reproducible_and_complete(modules):
    study, _, tasks, _, _ = modules
    rows = study.schedule(tasks.TASKS)
    assert len(rows) == len({row["id"] for row in rows}) == 720
    assert rows == study.schedule(tasks.TASKS)
    assert rows != study.schedule(tasks.TASKS, seed=10)
    for start in range(0, len(rows), 4):
        assert len({(row["task"], row["client"], row["repeat"]) for row in rows[start:start+4]}) == 1
        assert {row["lane"] for row in rows[start:start+4]} == set(study.LANES)


def test_release_requires_complete_revision_bound_evidence(modules):
    gate = modules[3]
    report = synthetic_report(modules)
    assert gate.evaluate(report, "engine")["passed"]
    assert not gate.evaluate(report, "another-engine")["passed"]
    report["runs"].pop()
    assert not gate.evaluate(report, "engine")["passed"]


@pytest.mark.parametrize("change", ["duplicate", "nan", "forced", "quality", "slow", "wire_only", "missing_client", "forged_manifest"])
def test_release_rejects_invalid_or_losing_studies(modules, change):
    gate = modules[3]
    report = synthetic_report(modules)
    if change == "duplicate":
        report["runs"].append(report["runs"][0])
    elif change == "nan":
        report["runs"][0]["seconds"] = float("nan")
    elif change == "forced":
        report["manifest"]["selection"] = "forced"
    elif change in {"quality", "slow"}:
        for row in report["runs"]:
            if row["client"] == "cursor" and row["lane"] == "intel_base":
                if change == "quality":
                    row["passed"] = False
                else:
                    row["seconds"] = 99
    elif change == "wire_only":
        report["response_volume"]["measurement"] = "serialized_mcp_result_all_pages"
    elif change == "missing_client":
        report["response_volume"]["rows"] = report["response_volume"]["rows"][:40]
    else:
        report["manifest"]["study_id"] = "forged"
    assert not gate.evaluate(report, "engine")["passed"]


def test_subscription_boundary_does_not_accept_login_alone(modules, monkeypatch):
    clients = modules[1]
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-use")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-use")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    env = clients.subscription_env()
    assert not any(key in env for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK"))
    assert not clients.quota_ready("claude", {})
    report = {"claude": {"subscription_only": True, "extra_usage_disabled": True, "remaining": True, "checked_at": time.time()}}
    assert clients.quota_ready("claude", report)
    report["claude"]["checked_at"] -= 3601
    assert not clients.quota_ready("claude", report)


def test_parses_actual_tool_result_shapes_without_double_counting(modules):
    clients = modules[1]
    events = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "one", "name": "mcp__intelligence__search_symbols", "input": {"name": "helper"}}]}},
              {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "one", "content": [{"type": "text", "text": "hello"}]}]}},
              {"type": "result", "structured_output": {"summary": "done"}, "modelUsage": {"fixed": {}}}]
    parsed = clients.parse_events("claude", "\n".join(map(json.dumps, events)))
    assert len(parsed["tool_calls"]) == len(parsed["tool_results"]) == 1
    assert parsed["mcp_used"] and parsed["tool_result_tokens"] > 0
    cursor = [{"type": "tool_call", "subtype": state, "call_id": "a", "tool_call": {
        "readToolCall": {"args": {"path": "a.py"}, "result": {"success": {"content": "source"}}}}}
        for state in ("started", "completed")]
    parsed = clients.parse_events("cursor", "\n".join(map(json.dumps, cursor)))
    assert len(parsed["tool_calls"]) == len(parsed["tool_results"]) == 1


def test_source_quotes_are_checked_and_repository_escape_rejected(modules, tmp_path):
    tasks = modules[2]
    root = tmp_path / "repo"
    root.mkdir()
    (root / "lib").mkdir()
    (root / "lib/response.js").write_text("res.json = function json(obj) {}\n")
    (root / "caller.js").write_text("res.json({ok:true});\n")
    task = {"repo": "express", "file": "lib/response.js"}
    answer = {"definition": {"path": "lib/response.js", "line": 1, "quote": "res.json = function json(obj) {}"},
              "usage": {"path": "caller.js", "line": 1, "quote": "res.json({ok:true});"}, "tests": []}
    assert all(tasks.evidence(root, task, answer).values())
    answer["usage"]["quote"] = "fabricated"
    assert not tasks.evidence(root, task, answer)["usage"]
    answer["definition"]["path"] = "../outside.js"
    assert not tasks.evidence(root, task, answer)["definition"]


def test_volume_replay_requires_every_reference_page(modules):
    responses = modules[4]
    ref = {"file_path": "a.py", "line": 1, "ref_kind": "call", "source": "syntax"}
    before = {"responses": [{"metadata": {"workspace": "/repo"}, "data": {"references": [ref]}}]}
    after = copy.deepcopy(before)
    assert responses.preserved(before, after, {}, 1)
    after["responses"][0]["data"]["next_cursor"] = "unfinished"
    assert not responses.preserved(before, after, {}, 1)
