"""Pilot isolation and observable evidence; subprocess tests never invoke a model."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "evals"))
    import pilot
    import release_gate
    import study
    import study_clients
    import study_events
    return study, study_clients, study_events, pilot, release_gate


def pilot_manifest(study):
    tasks, repetitions, lanes = study.design("pilot")
    tasks = [{**task, "prompts": [study.prompt(task)]} for task in tasks]
    manifest = {"mode": "pilot", "tasks": tasks, "repetitions": repetitions, "lanes": lanes,
                "schedule": study.schedule(tasks, repetitions, lanes=lanes), "timeout": 600,
                "models": {client: "fixed-model" for client in study.CLIENTS}, "engine_sha256": "new",
                "previous_engine_sha256": "old", "selection": "natural",
                "client_versions": {client: "1" for client in study.CLIENTS}}
    manifest["study_id"] = study.digest(manifest)
    return manifest


def test_pilot_schedule_and_engine_precision_isolation(modules, tmp_path):
    study = modules[0]
    manifest = pilot_manifest(study)
    manifest["python"] = sys.executable
    manifest["serena"] = {"command": "serena", "args": ["--context", "ide"]}
    rows = manifest["schedule"]
    assert len(rows) == len({r["id"] for r in rows}) == 54
    assert {r["task"] for r in rows} == {"express:lookup"}
    assert rows == study.schedule(manifest["tasks"], 3, lanes=study.PILOT_LANES)
    for start in range(0, 54, 6):
        block = rows[start:start + 6]
        assert len({(r["client"], r["repeat"]) for r in block}) == 1
        assert {r["lane"] for r in block} == set(study.PILOT_LANES)
    for lane in ("intel_base", "intel_precision", "previous_base", "previous_precision"):
        server = study.servers_for(manifest, tmp_path, tmp_path / "repo", lane, tmp_path, "codex")["intelligence"]
        assert server["env"]["PYTHONPATH"] == str(tmp_path / ("previous-engine" if lane.startswith("previous") else "engine"))
        assert server["env"]["ATTOCODE_INTEL_PRECISION"] == ("off" if lane.endswith("base") else "auto")
    assert study.servers_for(manifest, tmp_path, tmp_path, "native", tmp_path, "codex") == {}
    assert len(study.schedule(study.TASKS)) == 720


def test_pilot_report_retains_unused_tools_failures_and_missing_data(modules):
    study, _, _, pilot, _ = modules
    manifest = pilot_manifest(study)
    rows = [{**row, "study_id": manifest["study_id"], "model": "fixed-model", "status": "completed", "passed": True,
             "seconds": 50 if row["lane"].startswith("intel") else 100,
             "stages": [{"mcp_used": False, "observations": {"mcp_result_tokens": None}}]} for row in manifest["schedule"]]
    result = pilot.summarize(manifest, rows)
    assert result["complete"] and not result["release_eligible"]
    assert len(result["comparisons"]) == 18
    assert all(r["status"] == "promising" for r in result["comparisons"])
    assert all(r["mcp_used_runs"] == 0 and r["observations"]["mcp_result_tokens"] is None for r in result["lanes"])
    for row in rows:
        if row["client"] == "cursor" and row["lane"] == "intel_base":
            row.update(passed=False, seconds=1, status="interrupted")
    result = pilot.summarize(manifest, rows)
    failures = [r for r in result["comparisons"] if r["client"] == "cursor" and r["lane"] == "intel_base"]
    assert all(r["status"] == "needs_work" and r["median_paired_speedup"] < 0 for r in failures)
    assert not pilot.summarize(manifest, rows[:-1])["complete"]
    assert pilot.summarize(manifest, rows + rows[:1])["issues"]


def test_even_release_sized_pilot_cannot_authorize_publication(modules):
    study, _, _, _, gate = modules
    manifest = pilot_manifest(study)
    manifest["repetitions"] = 5
    manifest["study_id"] = study.digest({k: v for k, v in manifest.items() if k != "study_id"})
    result = gate.evaluate({"manifest": manifest, "runs": []}, "new")
    assert any("Pilot reports" in r for r in result["reasons"])


@pytest.mark.parametrize("client", ["claude", "codex", "cursor"])
def test_timed_tool_events_match_ids_not_completion_order(modules, client):
    events = modules[2]
    def record(kind, identity, t, content=None):
        if client == "claude":
            block = ({"type": "tool_use", "id": identity, "name": "mcp__intelligence__inspect_symbol", "input": {"symbol_name": "json"}}
                     if kind == "started" else {"type": "tool_result", "tool_use_id": identity, "content": content})
            raw = {"type": "assistant" if kind == "started" else "user", "message": {"content": [block]}}
        elif client == "codex":
            raw = {"type": "item." + kind, "item": {"type": "mcp_tool_call", "id": identity, "server": "intelligence",
                   "tool": "inspect_symbol", "arguments": {"symbol_name": "json"}, "result": content}}
        else:
            raw = {"type": "tool_call", "subtype": kind, "call_id": identity, "tool_call": {
                "function": {"name": "mcp__intelligence__inspect_symbol", "arguments": '{"symbol_name":"json"}', "result": content}}}
        return {"received_seconds": t, "event": raw}
    records = [record("started", "a", 1), record("started", "b", 2), record("completed", "b", 3, "second"),
               record("completed", "a", 5, "first"), record("completed", "a", 6, "first")]
    parsed = events.parse_events(client, "\n".join(map(json.dumps, records)))
    assert len(parsed["tool_calls"]) == len(parsed["tool_results"]) == 2
    calls = {r["id"]: r for r in parsed["tool_calls"]}
    assert calls["a"]["observed_seconds"] == 4 and calls["b"]["observed_seconds"] == 1
    assert events.observations(parsed)["inspect_symbol_calls"] == 2
    raw = events.parse_events(client, "\n".join(json.dumps(row["event"]) for row in (records[0], records[-1])))
    assert raw["tool_calls"][0]["observed_seconds"] is None
    assert events.observations(raw)["tool_intervals_missing"] == 1
    missing = events.parse_events(client, json.dumps(records[0]))
    assert missing["tool_result_tokens"] is None
    assert events.observations(missing)["mcp_result_tokens"] is None


def test_capture_drains_stderr_and_records_arrival_before_completion(modules, tmp_path):
    events = modules[2]
    script = r'''
import os, time
os.write(1,b'{"type":"system","model":"test"}\n')
os.write(2,b'x'*300000)
time.sleep(.12)
value='{"type":"result","result":"snow: 雪"}'.encode()
os.write(1,value[:-2]); time.sleep(.08); os.write(1,value[-2:])
'''
    result = events.capture([sys.executable, "-u", "-c", script], tmp_path, tmp_path, 5, os.environ)
    rows = [json.loads(r) for r in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert result["exit_code"] == 0 and not result["timed_out"]
    assert rows[1]["received_seconds"] - rows[0]["received_seconds"] >= .1
    assert rows[1]["event"]["result"] == "snow: 雪"
    assert (tmp_path / "stderr.log").stat().st_size == 300000
    assert (tmp_path / "trace.jsonl").stat().st_mode & 0o777 == 0o600


def test_capture_timeout_kills_parent_and_child_and_keeps_partial_trace(modules, tmp_path):
    events = modules[2]
    script = r'''
import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = os.fork()
print('{"type":"system"}', flush=True)
while True: time.sleep(.1)
'''
    result = events.capture([sys.executable, "-u", "-c", script], tmp_path, tmp_path, .2, os.environ, kill_grace=.1)
    assert result["timed_out"] and result["exit_code"] != 0 and result["seconds"] < 2
    assert (tmp_path / "events.jsonl").read_text()


def test_resume_preserves_attempts_and_requires_quota_and_wiring(modules, tmp_path, monkeypatch):
    study, _, _, pilot, _ = modules
    manifest = pilot_manifest(study)
    study.write_json(tmp_path / "preparation.json", {"express": {"clean_passes": True, "fault_detected": True}})
    monkeypatch.setattr(study, "manifest_for", lambda _: manifest)
    monkeypatch.setattr(study, "invoke", lambda *a: pytest.fail("No model calls before guards pass"))
    args = SimpleNamespace(study=tmp_path, clients=None, tasks=None, quota=None, max_runs=None)
    first = manifest["schedule"][0]
    directory = tmp_path / "runs" / first["id"].replace(":", "-")
    study.write_json(directory / "started.json", first)
    monkeypatch.setattr(study, "preflight", lambda *a: {"ready": False})
    study.run(args)
    preserved = (directory / "result.json").read_bytes()
    assert json.loads(preserved)["status"] == "interrupted"
    monkeypatch.setattr(study, "preflight", lambda *a: {"ready": True})
    study.run(args)
    assert (directory / "result.json").read_bytes() == preserved
    assert len(list((tmp_path / "runs").iterdir())) == 1
    assert not pilot.wiring_ready(tmp_path, manifest, "codex")
    study.write_json(tmp_path / "wiring/codex/result.json", {"study_id": "other", "passed": True, "excluded": True})
    assert not pilot.wiring_ready(tmp_path, manifest, "codex")


def test_wiring_requires_real_source_results_not_just_tool_calls(modules, tmp_path):
    _, _, events, pilot, _ = modules
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib/response.js").write_text("res.json = function json(obj) {};\n")
    (tmp_path / "use.js").write_text("res.json({ok:true});\n")
    raw = []
    for name in ("Read", "mcp__previous__search_symbols", "mcp__current__inspect_symbol", "mcp__serena__find_symbol"):
        raw += [{"message": {"content": [{"type": "tool_use", "id": name, "name": name}]}},
                {"message": {"content": [{"type": "tool_result", "tool_use_id": name,
                                           "content": "lib/response.js: res.json = function json(obj) {};"}]}}]
    parsed = events.parse_events("claude", "\n".join(map(json.dumps, raw)))
    parsed["output"] = {"definition": {"path": "lib/response.js", "line": 1, "quote": "res.json = function json(obj) {};"},
                        "usage": {"path": "use.js", "line": 1, "quote": "res.json({ok:true});"}, "tests": []}
    execution = {"exit_code": 0, "timed_out": False, "quota_exhausted": False}
    checks = pilot.wiring_checks(parsed, execution, tmp_path, {"repo": "express", "file": "lib/response.js"}, "fixed")
    assert all(checks.values())
    broken = copy.deepcopy(parsed)
    broken["tool_results"][1]["content"] = None
    assert not all(pilot.wiring_checks(broken, execution, tmp_path, {"repo": "express", "file": "lib/response.js"}, "fixed").values())


def test_freeze_pins_both_engines_and_only_selected_sources(modules, tmp_path, monkeypatch):
    study = modules[0]
    project, repos, baseline = tmp_path / "project", tmp_path / "repos", tmp_path / "baseline"
    for directory, content in ((project / "packages/code-intel/src/attocode_intel", "current"), (baseline / "attocode_intel", "previous")):
        directory.mkdir(parents=True)
        (directory / "entrypoint.py").write_text(content)
    express = repos / "express"
    (express / "lib").mkdir(parents=True)
    (express / "lib/response.js").write_text("var spaces = app.get('json spaces');\n")
    (express / "package-lock.json").write_text("{}")
    subprocess.run(["git", "init", "-q", str(express)], check=True)
    subprocess.run(["git", "add", "."], cwd=express, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "fixture"], cwd=express, check=True)
    models, launcher = tmp_path / "models.json", tmp_path / "serena.json"
    models.write_text(json.dumps({client: "fixed" for client in study.CLIENTS}))
    launcher.write_text(json.dumps({"command": "uvx", "args": ["git+https://example.com/serena@" + "a" * 40]}))
    original_output = study.subprocess.check_output
    def check_output(argv, **kwargs):
        return "client-version" if "--version" in argv else original_output(argv, **kwargs)
    monkeypatch.setattr(study.subprocess, "check_output", check_output)
    monkeypatch.setattr(study, "environment_versions", lambda: {"fixed": True})
    args = SimpleNamespace(project=project, study=tmp_path / "pilot", models=models, serena_launcher=launcher,
                           repo_dir=repos, mode="pilot", baseline_src=baseline)
    study.freeze(args)
    manifest = study.manifest_for(args.study)
    assert len(manifest["schedule"]) == 54 and set(manifest["revisions"]) == {"express"}
    assert [p.name for p in (args.study / "sources").iterdir()] == ["express"]
    (baseline / "attocode_intel/entrypoint.py").write_text("original changed after freeze")
    assert study.manifest_for(args.study) == manifest
    frozen_previous = args.study / "previous-engine/attocode_intel/entrypoint.py"
    frozen_previous.write_text("changed")
    with pytest.raises(ValueError, match="previous engine changed"):
        study.manifest_for(args.study)
    frozen_previous.write_text("previous")
    (args.study / "engine/attocode_intel/entrypoint.py").write_text("changed")
    with pytest.raises(ValueError, match="Frozen engine changed"):
        study.manifest_for(args.study)
    (args.study / "engine/attocode_intel/entrypoint.py").write_text("current")
    accepted = []
    def acceptance(root, task, *unused):
        accepted.append(task["repo"])
        return {"passed": "app.get('json spaces')" in (root / "lib/response.js").read_text()}
    monkeypatch.setattr(study, "acceptance", acceptance)
    monkeypatch.setattr(study.subprocess, "run", lambda *a, **kw: None)
    study.prepare(args)
    assert accepted == ["express", "express"]
    assert study.manifest_for(args.study) == manifest


def test_default_pilot_batch_runs_six_and_resume_keeps_completed_results(modules, tmp_path, monkeypatch):
    study = modules[0]
    manifest = pilot_manifest(study)
    manifest.update(python=sys.executable, serena={"command": "serena", "args": []})
    root = tmp_path / "sources/express"
    (root / "lib").mkdir(parents=True)
    (root / "lib/response.js").write_text("res.json = function json(obj) {};\n")
    (root / "use.js").write_text("res.json({ok:true});\n")
    study.write_json(tmp_path / "preparation.json", {"express": {"clean_passes": True, "fault_detected": True}})
    for client in study.CLIENTS:
        study.write_json(tmp_path / "wiring" / client / "result.json", {"study_id": manifest["study_id"], "passed": True, "excluded": True})
    monkeypatch.setattr(study, "manifest_for", lambda _: manifest)
    monkeypatch.setattr(study, "preflight", lambda *a: {"ready": True})
    invoked = []
    def invoke(client, model, root, directory, servers, *args):
        invoked.append((client, servers))
        return {"seconds": 1, "exit_code": 0, "timed_out": False, "quota_exhausted": False, "permission_denials": [],
                "output": {"definition": {"path": "lib/response.js", "line": 1, "quote": "res.json = function json(obj) {};"},
                           "usage": {"path": "use.js", "line": 1, "quote": "res.json({ok:true});"}, "tests": []}}
    monkeypatch.setattr(study, "invoke", invoke)
    args = SimpleNamespace(study=tmp_path, clients=None, tasks=None, quota=None, max_runs=None)
    study.run(args)
    assert len(invoked) == 6
    saved = {p: p.read_bytes() for p in (tmp_path / "runs").glob("*/result.json")}
    assert len(saved) == 6 and all(json.loads(value)["passed"] for value in saved.values())
    study.run(args)
    assert len(invoked) == 12 and all(p.read_bytes() == value for p, value in saved.items())
