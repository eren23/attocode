"""Offline trace auditing must not turn missing or malformed evidence into misses."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "evals"))
    import search_evidence_audit
    return search_evidence_audit


def event(block):
    return json.dumps({"event": {"message": {"content": [block]}}})


def tool(call_id, name, arguments=None):
    return event({"type": "tool_use", "id": call_id, "name": name, "input": arguments or {}})


def result(call_id, content, **kwargs):
    return event({"type": "tool_result", "tool_use_id": call_id, "content": content, **kwargs})


def row():
    return {"id": "case:0:intel_first", "task": "case", "setup": "intel_first", "trial": 0,
            "events": "runs/case/stage-0/events.jsonl", "files": ["src/main.py"]}


def task():
    return {"id": "case", "gold": ["src/main.py", "src/secondary.py"]}


def response():
    return json.dumps({"data": {"results": [
        {"file_path": "src/secondary.py", "snippet": "# license", "snippet_truncated": True,
         "matched_terms": ["cleanup"], "match_fields": ["source_body"]}]}})


@pytest.mark.parametrize("blocks", [False, True])
def test_delivered_omission_and_observed_read_are_distinct_from_missing_page(module, blocks):
    content = [{"type": "text", "text": response()}] if blocks else response()
    raw = "\n".join([tool("search", "mcp__intel__semantic_search", {"query": "cleanup"}),
                      result("search", content),
                      tool("read", "Read", {"file_path": "/workspace/src/secondary.py"}),
                      result("read", "public code")])
    data = module.audit_run(row(), task(), raw, "/workspace")
    assert data["labeled_delivered_not_answered"] == ["src/secondary.py"]
    assert data["labeled_not_delivered"] == ["src/main.py"]
    hit = data["searches"][0]["hits"][0]
    assert hit["explicit_reads_after_result"] == ["read"]
    assert hit["reported_terms_not_visible"] == ["cleanup"]


@pytest.mark.parametrize("content", ["truncated {", "{}", '{"data":{"results":null}}',
                                    '{"data":{"results":[{}]}}',
                                    '{"data":{"results":[{"file_path":"a.py","matched_terms":null}]}}',
                                    '{"data":{"results":[{"file_path":"a.py","snippet":123}]}}'])
def test_malformed_responses_are_unknown_not_empty_results(module, content):
    raw = "\n".join([tool("search", "semantic_search"), result("search", content)])
    data = module.audit_run(row(), task(), raw)
    assert not data["search_trace_complete"]
    assert data["labeled_not_delivered"] is None
    assert data["searches"][0]["status"] == "unknown"


def test_duplicate_events_are_not_counted_twice_and_conflicts_are_unknown(module):
    call = tool("search", "semantic_search")
    answer = result("search", response())
    calls, warnings = module.trace_calls("\n".join([call, call, answer, answer]))
    assert len(calls) == 1 and not warnings
    calls, warnings = module.trace_calls("\n".join([call, answer, result("search", "other")]))
    assert calls[0]["ambiguous"] and warnings
    assert module.search_result(calls[0])["status"] == "unknown"


def test_missing_failed_or_malformed_events_do_not_establish_absence(module):
    for raw in (tool("search", "semantic_search"),
                "\n".join([tool("search", "semantic_search"), result("search", response(), is_error=True)]),
                "\n".join(["broken json", tool("search", "semantic_search"), result("search", response())])):
        data = module.audit_run(row(), task(), raw)
        assert data["labeled_not_delivered"] is None


def write_study(tmp_path):
    study = tmp_path / "study"
    stage = study / "runs/case/stage-0"
    stage.mkdir(parents=True)
    (study / "manifest.json").write_text(json.dumps({"study_id": "frozen", "model": "none",
        "tasks": [task()], "trials": 1, "setups": ["intel_first"]}))
    (study / "runs.jsonl").write_text(json.dumps(row()) + "\n")
    (stage.parent / "result.json").write_text(json.dumps({"workspace": "/workspace"}))
    (stage / "events.jsonl").write_text("\n".join([
        tool("search", "semantic_search"), result("search", response())]))
    return study


def test_input_hashes_bind_trace_and_duplicate_schedule_is_rejected(module, tmp_path):
    study = write_study(tmp_path)
    data = module.audit(study)
    assert len(data["input_sha256"]) == 4
    assert data["summary"]["runs"] == 1
    assert "1/1" in module.report(data)
    before = data["input_sha256"]["runs/case/stage-0/events.jsonl"]
    with (study / "runs/case/stage-0/events.jsonl").open("a") as stream:
        stream.write("\n{}\n")
    assert module.audit(study)["input_sha256"]["runs/case/stage-0/events.jsonl"] != before
    (study / "runs.jsonl").write_text((json.dumps(row()) + "\n") * 2)
    with pytest.raises(ValueError, match="Duplicate run"):
        module.audit(study)


def test_cli_refuses_overwrite_and_frozen_study_output(module, tmp_path, monkeypatch):
    study = write_study(tmp_path)
    for output in (study / "analysis", tmp_path):
        monkeypatch.setattr("sys.argv", ["audit", "--study", str(study), "--output", str(output)])
        with pytest.raises(SystemExit):
            module.main()
    output = tmp_path / "new-analysis"
    monkeypatch.setattr("sys.argv", ["audit", "--study", str(study), "--output", str(output)])
    module.main()
    assert (output / "ledger.json").is_file() and (output / "report.md").is_file()
    with pytest.raises(SystemExit):
        module.main()
